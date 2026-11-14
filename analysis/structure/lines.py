"""Automatic trendlines and parallel channels from swing points.

Trendline candidates connect two swing lows (support line) or two swing highs (resistance line). A line is
kept when no close between and after its anchors cuts through it by more than a small tolerance, and it is
scored by how many other swings touch it (within 0.25 x ATR), its length and how recent it is.
A channel is the best trendline plus a parallel line through the most extreme opposite swing in its span,
kept when both sides have >= 2 touches and >= 80% of closes stay inside.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from analysis.structure.swings import Swing, atr_series, times_of

TOUCH_ATR = 0.25
CUT_ATR = 0.35
MAX_DIST_ATR = 10.0   # lines further than this from the current price are not useful for trading


@dataclass
class Line:
    kind: str                 # support | resistance
    i1: int
    i2: int
    t1: int
    p1: float
    t2: int
    p2: float
    slope: float              # price per bar
    touches: int
    score: float
    end_time: int = 0         # last bar time (the line is drawn to here)
    end_price: float = 0.0

    def price_at(self, i: float) -> float:
        return self.p1 + self.slope * (i - self.i1)

    def as_dict(self) -> dict:
        return asdict(self)


def trendlines(df: pd.DataFrame, swings: list[Swing], lookback_swings: int = 12, top: int = 2) -> list[Line]:
    if len(df) < 20 or len(swings) < 3:
        return []
    close = df["close"].to_numpy(float)
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    atr = float(atr_series(df)[-1])
    t = times_of(df)
    n = len(df)
    out: list[Line] = []
    for kind, sk in (("support", "L"), ("resistance", "H")):
        pts = [s for s in swings if s.kind == sk][-lookback_swings:]
        cands: list[Line] = []
        for a_i in range(len(pts)):
            for b_i in range(a_i + 1, len(pts)):
                a, b = pts[a_i], pts[b_i]
                if b.idx - a.idx < 3:
                    continue
                slope = (b.price - a.price) / (b.idx - a.idx)
                line = lambda i: a.price + slope * (i - a.idx)  # noqa: E731
                seg = np.arange(a.idx, n)
                ref = line(seg)
                # A support line must not be closed below (resistance: above) beyond the tolerance.
                cut = (close[seg] < ref - CUT_ATR * atr) if kind == "support" else (close[seg] > ref + CUT_ATR * atr)
                if cut.any():
                    continue
                # Must still matter now: the line's current value within MAX_DIST_ATR of the price.
                if abs(line(n - 1) - close[-1]) > MAX_DIST_ATR * atr:
                    continue
                touches = sum(1 for s in pts if s.idx >= a.idx and abs(s.price - line(s.idx)) <= TOUCH_ATR * atr)
                wick = lo if kind == "support" else hi
                # extra touches by wicks between swings
                touches += int(np.sum(np.abs(wick[seg] - ref) <= TOUCH_ATR * atr * 0.5)) // 4
                length = (b.idx - a.idx) / n
                recency = 1 - (n - 1 - b.idx) / n
                score = touches * 2 + length * 3 + recency * 2
                end = n - 1
                cands.append(Line(kind, a.idx, b.idx, a.time, a.price, b.time, b.price, slope, touches, round(score, 3),
                                  int(t[end]), float(line(end))))
        cands.sort(key=lambda l: -l.score)
        kept: list[Line] = []
        for c in cands:  # skip near-duplicates (same anchors region / near-identical slope)
            if all(abs(c.slope - k.slope) > 0.05 * atr or abs(c.end_price - k.end_price) > atr for k in kept):
                kept.append(c)
            if len(kept) >= top:
                break
        out += kept
    return out


@dataclass
class Channel:
    direction: str            # up | down | flat
    base: Line
    offset: float             # parallel line = base + offset
    inside_pct: float
    touches_base: int
    touches_parallel: int
    upper_now: float = 0.0
    lower_now: float = 0.0
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["base"] = self.base.as_dict()
        return d


def channels(df: pd.DataFrame, swings: list[Swing], lines: list[Line] | None = None) -> list[Channel]:
    lines = lines if lines is not None else trendlines(df, swings)
    if not lines:
        return []
    close = df["close"].to_numpy(float)
    atr = float(atr_series(df)[-1])
    n = len(df)
    out: list[Channel] = []
    for base in lines[:2]:
        opp = [s for s in swings if s.kind == ("H" if base.kind == "support" else "L") and s.idx >= base.i1]
        if len(opp) < 2:
            continue
        dists = [s.price - base.price_at(s.idx) for s in opp]
        off = max(dists) if base.kind == "support" else min(dists)
        tp = sum(1 for d in dists if abs(d - off) <= TOUCH_ATR * 1.5 * atr)
        seg = np.arange(base.i1, n)
        lower = base.price_at(seg) + (0 if base.kind == "support" else off)
        upper = base.price_at(seg) + (off if base.kind == "support" else 0)
        inside = float(np.mean((close[seg] >= lower - 0.2 * atr) & (close[seg] <= upper + 0.2 * atr)))
        if tp >= 2 and base.touches >= 2 and inside >= 0.8 and abs(off) >= 1.5 * atr:
            slope_atr = base.slope / atr
            direction = "up" if slope_atr > 0.02 else "down" if slope_atr < -0.02 else "flat"
            out.append(Channel(direction, base, float(off), round(inside, 3), base.touches, tp,
                               float(upper[-1]), float(lower[-1])))
    return out
