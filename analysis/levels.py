"""Support / resistance from swing pivots, clustered by ATR, plus classic pivot points."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Level:
    price: float
    kind: str        # support | resistance
    touches: int
    last_touch: str  # ISO date of the most recent pivot in the cluster

    def as_dict(self) -> dict:
        return {"price": self.price, "kind": self.kind, "touches": self.touches, "last_touch": self.last_touch}


def swing_points(df: pd.DataFrame, window: int = 3) -> tuple[pd.Series, pd.Series]:
    """Fractal pivots: a high/low that is the extreme of the surrounding 2*window+1 bars."""
    w = 2 * window + 1
    hi = df["high"]
    lo = df["low"]
    is_high = hi == hi.rolling(w, center=True).max()
    is_low = lo == lo.rolling(w, center=True).min()
    return hi[is_high], lo[is_low]


def _cluster(points: pd.Series, tol: float) -> list[tuple[float, int, pd.Timestamp]]:
    if points.empty:
        return []
    items = sorted(zip(points.values, points.index), key=lambda x: x[0])
    clusters: list[list] = [[items[0]]]
    for p in items[1:]:
        if abs(p[0] - np.mean([q[0] for q in clusters[-1]])) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [(float(np.mean([q[0] for q in c])), len(c), max(q[1] for q in c)) for c in clusters]


def support_resistance(df: pd.DataFrame, lookback: int = 600, window: int = 3, max_levels: int = 4) -> dict:
    """Nearest support levels below and resistance levels above the last close.

    Pivots within 0.5*ATR of each other are merged; more touches = stronger level.
    """
    d = df.tail(lookback)
    if len(d) < 2 * window + 2:
        return {"supports": [], "resistances": []}
    price = float(d["close"].iloc[-1])
    atr_val = float((d["high"] - d["low"]).rolling(14).mean().iloc[-1] or (d["high"] - d["low"]).mean())
    highs, lows = swing_points(d, window)
    clusters = _cluster(pd.concat([highs, lows]), tol=0.5 * atr_val)

    supports, resistances = [], []
    for lvl, touches, last in clusters:
        lv = Level(round(lvl, 6), "support" if lvl < price else "resistance", touches, pd.Timestamp(last).date().isoformat())
        (supports if lvl < price else resistances).append(lv)
    # Nearest first. Ties between nearby levels go to the one with more touches.
    supports.sort(key=lambda l: (price - l.price) / atr_val - 0.3 * l.touches)
    resistances.sort(key=lambda l: (l.price - price) / atr_val - 0.3 * l.touches)
    supports = sorted(supports[:max_levels], key=lambda l: -l.price)
    resistances = sorted(resistances[:max_levels], key=lambda l: l.price)
    return {"supports": supports, "resistances": resistances}


def pivot_points(df: pd.DataFrame) -> dict:
    """Classic floor pivots from the previous completed bar."""
    if len(df) < 2:
        return {}
    prev = df.iloc[-2]
    p = (prev["high"] + prev["low"] + prev["close"]) / 3
    r = prev["high"] - prev["low"]
    return {
        "P": p, "R1": 2 * p - prev["low"], "S1": 2 * p - prev["high"],
        "R2": p + r, "S2": p - r, "R3": prev["high"] + 2 * (p - prev["low"]), "S3": prev["low"] - 2 * (prev["high"] - p),
    }
