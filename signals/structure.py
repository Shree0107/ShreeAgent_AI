"""Market-structure facts measured from daily candles.

These are the raw facts the plain-language reasons are built from ("rising for about 3 weeks",
"bounced off a level buyers defended before"). Everything is computed, nothing is guessed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from analysis import indicators as ind
from analysis.levels import swing_points


@dataclass
class Swing:
    price: float
    date: str  # ISO date

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarketFacts:
    price: float
    atr: float
    last_bar: str
    days_in_trend: int          # consecutive-ish days on the trend side of the 21-day average (+up / -down)
    change_20d_pct: float
    above_200d: bool | None
    momentum: str               # rising | falling | flat
    stretched: str              # overbought | oversold | ""
    bounce_level: float | None  # level price recently tested and held (support for up, resistance for down)
    bounce_side: str            # support | resistance | ""
    swing_lows: list[Swing] = field(default_factory=list)   # recent, newest first
    swing_highs: list[Swing] = field(default_factory=list)
    high_60d: float | None = None
    low_60d: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _days_in_trend(close: pd.Series, avg: pd.Series, tolerance: int = 2) -> int:
    """Count bars back from the latest that closed on the same side of the average.

    Up to `tolerance` bars on the other side are forgiven (a normal dip doesn't end a trend);
    `tolerance`+1 in a row ends the count. Positive = above (uptrend), negative = below.
    """
    c, a = close.dropna(), avg.reindex(close.index)
    if c.empty or pd.isna(a.iloc[-1]):
        return 0
    side = 1 if c.iloc[-1] > a.iloc[-1] else -1
    count = against = 0
    for cv, av in zip(reversed(c.values), reversed(a.values)):
        if pd.isna(av):
            break
        if (cv > av) == (side == 1):
            count += 1 + against
            against = 0
        else:
            against += 1
            if against > tolerance:
                break
    return side * count


def recent_swings(df: pd.DataFrame, lookback: int = 30, window: int = 2) -> tuple[list[Swing], list[Swing]]:
    """Swing lows / highs of the last `lookback` bars, newest first.

    A 2-bar window confirms a swing two days after it forms, so the very latest move is included quickly.
    """
    d = df.tail(lookback + window)
    highs, lows = swing_points(d, window)
    to = lambda s: [Swing(float(v), pd.Timestamp(i).date().isoformat()) for i, v in reversed(list(s.items()))]
    return to(lows), to(highs)


def market_facts(df: pd.DataFrame, supports: list[float], resistances: list[float]) -> MarketFacts:
    d = ind.add_all(df, has_volume=False)
    last, prev = d.iloc[-1], d.iloc[-2]
    price = float(last.close)
    atr = float(last.atr_14)
    lows, highs = recent_swings(d)

    hist = d["macd_hist"]
    momentum = "flat"
    if pd.notna(last.macd_hist) and pd.notna(prev.macd_hist):
        if last.macd_hist > 0 and last.macd_hist >= prev.macd_hist:
            momentum = "rising"
        elif last.macd_hist < 0 and last.macd_hist <= prev.macd_hist:
            momentum = "falling"
        elif hist.tail(3).is_monotonic_increasing:
            momentum = "rising"
        elif hist.tail(3).is_monotonic_decreasing:
            momentum = "falling"

    rsi = last.rsi_14
    stretched = "overbought" if pd.notna(rsi) and rsi >= 70 else "oversold" if pd.notna(rsi) and rsi <= 30 else ""

    # Bounce: in the last 5 bars a low came within 0.3 ATR of a support and the price is now above it.
    bounce_level, bounce_side = None, ""
    recent = d.tail(5)
    for s in sorted([s for s in supports if s < price], reverse=True)[:2]:
        if (recent["low"] <= s + 0.3 * atr).any() and price > s:
            bounce_level, bounce_side = s, "support"
            break
    if bounce_level is None:
        for r in sorted([r for r in resistances if r > price])[:2]:
            if (recent["high"] >= r - 0.3 * atr).any() and price < r:
                bounce_level, bounce_side = r, "resistance"
                break

    tail60 = d.tail(60)
    return MarketFacts(
        price=price, atr=atr, last_bar=d.index[-1].isoformat(),
        days_in_trend=_days_in_trend(d["close"], d["ema_21"]),
        change_20d_pct=round((price / float(d["close"].iloc[-21]) - 1) * 100, 2) if len(d) > 21 else 0.0,
        above_200d=None if pd.isna(last.ema_200) else bool(price > last.ema_200),
        momentum=momentum, stretched=stretched, bounce_level=bounce_level, bounce_side=bounce_side,
        swing_lows=lows, swing_highs=highs,
        high_60d=float(tail60["high"].max()), low_60d=float(tail60["low"].min()),
    )
