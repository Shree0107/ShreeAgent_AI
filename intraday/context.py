"""The analysis context at one moment: completed bars of every timeframe, as of `now`.

    ctx = build_context(symbol, frames, now, cfg)

`frames` maps timeframe -> OHLC DataFrame (UTC index = bar START time). Only bars that have fully closed by
`now` (start + length <= now) are kept, and each frame is cut to a recent window. Every detector reads only
`ctx`, so a backtest (phase 7) can call `build_context(symbol, full_history, now=close_time_of_bar_i)` and get
exactly what the live engine would have seen at that moment: no look-ahead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property

import numpy as np
import pandas as pd

from data.providers.base import TF_SECONDS
from data.symbols import Symbol
from intraday.config import IntradayConfig
from signals.market import pip_size

TFS = ("5m", "15m", "1h", "4h", "1d")
WINDOW = {"5m": 300, "15m": 400, "1h": 400, "4h": 300, "1d": 300}


def completed(df: pd.DataFrame | None, tf: str, now: datetime, window: int | None = None) -> pd.DataFrame:
    """Bars whose close time (start + timeframe) is at or before `now`, the last `window` of them."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
    end = idx + pd.Timedelta(seconds=TF_SECONDS[tf])
    out = df[end <= pd.Timestamp(now)]
    if out.index.tz is None:
        out = out.tz_localize("UTC")
    return out.tail(window) if window else out


@dataclass
class Spread:
    pips: float | None
    live: bool               # True = measured from the live OANDA price
    note: str = ""

    def as_dict(self) -> dict:
        return {"pips": self.pips, "live": self.live, "note": self.note}


@dataclass
class Context:
    symbol: Symbol
    now: datetime
    frames: dict[str, pd.DataFrame]
    cfg: IntradayConfig
    spread: Spread = field(default_factory=lambda: Spread(None, False))
    events: list = field(default_factory=list)       # data.providers.calendar.CalendarEvent
    price: float | None = None                         # latest price (live mid if known, else last close)

    @property
    def pip(self) -> float | None:
        return pip_size(self.symbol)

    def df(self, tf: str) -> pd.DataFrame:
        return self.frames.get(tf, pd.DataFrame())

    @property
    def main(self) -> pd.DataFrame:
        return self.df(self.cfg.timeframe)

    @property
    def last(self) -> float:
        if self.price is not None:
            return float(self.price)
        return float(self.main["close"].iloc[-1])

    @cached_property
    def atr15(self) -> float:
        from analysis.indicators import atr

        d = self.main
        if len(d) < 15:
            return float((d["high"] - d["low"]).mean()) if len(d) else 0.0
        v = float(atr(d).iloc[-1])
        return v if np.isfinite(v) and v > 0 else float((d["high"] - d["low"]).tail(14).mean())

    @property
    def spread_price(self) -> float:
        """Spread in price units (0 when unknown, e.g. stocks)."""
        if self.spread.pips is None or not self.pip:
            return 0.0
        return self.spread.pips * self.pip

    @property
    def last_bar_time(self) -> datetime | None:
        d = self.main
        return d.index[-1].to_pydatetime() if len(d) else None

    def cache(self) -> dict:
        """Per-context memo for shared analysis (bias, levels, regime)."""
        if not hasattr(self, "_memo"):
            self._memo = {}
        return self._memo


def build_context(symbol: Symbol, frames: dict[str, pd.DataFrame], now: datetime, cfg: IntradayConfig,
                  spread: Spread | None = None, events: list | None = None, price: float | None = None) -> Context:
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    cut = {tf: completed(df, tf, now, WINDOW.get(tf)) for tf, df in frames.items() if tf in TF_SECONDS}
    return Context(symbol, now, cut, cfg, spread or Spread(None, False), events or [], price)
