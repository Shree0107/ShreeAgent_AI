"""ZigZag swing points filtered by volatility.

A swing high is the highest high of an up-leg, accepted only once price has since fallen by at least
`mult` x ATR from it (mirror for swing lows). Small wiggles are ignored, so the swings match what a trader
would mark by eye. `confirmed_at` = index of the bar where the reversal reached the threshold.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from analysis import indicators as ind


@dataclass
class Swing:
    idx: int            # bar index of the extreme
    time: int           # unix seconds of that bar
    price: float
    kind: str           # "H" (swing high) | "L" (swing low)
    confirmed_at: int   # bar index where the swing became known
    label: str = ""     # HH / HL / LH / LL (filled by structure.label_swings)

    def as_dict(self) -> dict:
        return asdict(self)


def atr_series(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    a = ind.atr(df, n).to_numpy()
    fallback = float(np.nanmean((df["high"] - df["low"]).to_numpy())) or 1e-9
    return np.where(np.isnan(a), fallback, a)


def times_of(df: pd.DataFrame) -> np.ndarray:
    idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
    return idx.as_unit("s").asi8


def zigzag(df: pd.DataFrame, mult: float = 2.0, atr_n: int = 14) -> list[Swing]:
    """Alternating swing highs/lows. The last, still-forming leg is not included.

    State machine: while in an up-leg, track the highest high; once price falls `mult` x ATR below it, that
    high is a confirmed swing and a down-leg starts (tracking the lowest low since the high), and vice versa.
    """
    if len(df) < 3:
        return []
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    atr = atr_series(df, atr_n)
    t = times_of(df)
    swings: list[Swing] = []
    leg = None          # None (not known yet) | "up" | "down"
    hi_i = lo_i = 0     # index of the extreme of the current leg
    for i in range(len(df)):
        if leg in (None, "up") and hi[i] >= hi[hi_i]:
            hi_i = i
        if leg in (None, "down") and lo[i] <= lo[lo_i]:
            lo_i = i
        thr = mult * atr[i]
        if leg in (None, "up") and hi_i < i and hi[hi_i] - lo[i] >= thr:
            swings.append(Swing(hi_i, int(t[hi_i]), float(hi[hi_i]), "H", i))
            leg = "down"
            lo_i = hi_i + 1 + int(np.argmin(lo[hi_i + 1:i + 1]))
        elif leg in (None, "down") and lo_i < i and hi[i] - lo[lo_i] >= thr:
            swings.append(Swing(lo_i, int(t[lo_i]), float(lo[lo_i]), "L", i))
            leg = "up"
            hi_i = lo_i + 1 + int(np.argmax(hi[lo_i + 1:i + 1]))
    return _dedupe(swings)


def _dedupe(swings: list[Swing]) -> list[Swing]:
    """Guarantee alternation H, L, H, ... (keep the more extreme of two same-kind neighbours)."""
    out: list[Swing] = []
    for s in swings:
        if out and out[-1].kind == s.kind:
            better = (s.price > out[-1].price) if s.kind == "H" else (s.price < out[-1].price)
            if better:
                out[-1] = s
            continue
        out.append(s)
    return out


def known_at(swings: list[Swing], i: int) -> list[Swing]:
    """Swings that were already confirmed at bar i (for look-ahead-free use)."""
    return [s for s in swings if s.confirmed_at <= i]
