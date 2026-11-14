"""Synthetic, aligned multi-timeframe data for the intraday tests (5M bars resampled up, so every timeframe agrees)."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from data.providers.base import resample_ohlcv

RULES = {"15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}


def five_min(n_days: int = 40, drift: float = 0.0, vol: float = 0.00035, seed: int = 1, start: float = 1.08,
             end: datetime | None = None, path: np.ndarray | None = None) -> pd.DataFrame:
    """Weekday 5M bars ending at `end` (UTC). drift = per-bar log drift. `path` overrides the closes."""
    end = end or datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    idx = pd.date_range(end=pd.Timestamp(end) - pd.Timedelta(minutes=5), periods=n_days * 288, freq="5min", tz="UTC")
    idx = idx[idx.weekday < 5]
    rng = np.random.default_rng(seed)
    if path is None:
        close = start * np.exp(np.cumsum(rng.normal(drift, vol, len(idx))))
    else:
        close = np.asarray(path, float)[-len(idx):]
        idx = idx[-len(close):]
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0, vol * 0.6, len(close))) * close
    hi = np.maximum(open_, close) + wick
    lo = np.minimum(open_, close) - wick
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close, "volume": 0.0}, index=idx)


def frames_from(m5: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {"5m": m5}
    for tf, rule in RULES.items():
        out[tf] = resample_ohlcv(m5, rule)
    return out


class FrameData:
    """DataService stand-in serving aligned synthetic frames."""

    def __init__(self, frames):
        self.frames = frames

    def get_ohlcv(self, symbol, tf="1d"):
        return self.frames[tf]

    def upcoming_events(self, currencies, days=14):
        return []
