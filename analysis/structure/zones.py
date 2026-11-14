"""Price zones: support/resistance, order blocks, fair value gaps, supply & demand.

S/R zones : swing prices clustered within 0.5 x ATR; the zone spans the cluster (min..max, at least 0.3 ATR
            wide). strength = touches + rejections (wicks into the zone that closed back out), recent ones
            weighted more. Role = support if price is above the zone now, resistance if below (a zone flips
            role once price closes through it).
Order block: the last opposite-colour candle before an impulse (>= 1.5 x ATR within 3 bars) that broke
            structure; mitigated once price trades back into it.
FVG       : 3-candle imbalance, high[i-2] < low[i] (bullish) or low[i-2] > high[i] (bearish), at least
            0.1 x ATR tall; filled when price trades back through the whole gap.
Supply/demand: a base of 1-3 small candles (range <= 0.6 ATR) followed by a strong departure (>= 2 ATR within
            3 bars); demand if the departure is up. Fresh until price first returns to it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from analysis.structure.swings import Swing, atr_series, times_of


@dataclass
class Zone:
    kind: str            # support | resistance | demand | supply | bull_ob | bear_ob | bull_fvg | bear_fvg
    low: float
    high: float
    t_start: int         # unix seconds where the zone begins
    idx: int             # bar index where it was created/confirmed
    strength: float = 0.0
    touches: int = 0
    status: str = "fresh"   # fresh | tested | mitigated | filled
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def sr_zones(df: pd.DataFrame, swings: list[Swing], max_zones: int = 6) -> list[Zone]:
    if not swings:
        return []
    atr = float(atr_series(df)[-1])
    hi, lo, close = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    n = len(df)
    pts = sorted(swings, key=lambda s: s.price)
    clusters: list[list[Swing]] = [[pts[0]]]
    for s in pts[1:]:
        if abs(s.price - np.mean([q.price for q in clusters[-1]])) <= 0.5 * atr:
            clusters[-1].append(s)
        else:
            clusters.append([s])
    price = close[-1]
    zones = []
    for c in clusters:
        z_lo, z_hi = min(q.price for q in c), max(q.price for q in c)
        if z_hi - z_lo < 0.3 * atr:
            mid = (z_hi + z_lo) / 2
            z_lo, z_hi = mid - 0.15 * atr, mid + 0.15 * atr
        first = min(q.idx for q in c)
        seg = slice(first, n)
        # rejections: a wick enters the zone but the close stays outside
        into = (lo[seg] <= z_hi) & (hi[seg] >= z_lo)
        outside = (close[seg] > z_hi) | (close[seg] < z_lo)
        rejections = int(np.sum(into & outside))
        recency = np.mean([(q.idx + 1) / n for q in c])
        strength = round(len(c) * 1.5 + min(rejections, 10) * 0.5 + recency * 2, 2)
        kind = "support" if price >= z_hi else "resistance" if price <= z_lo else \
            ("support" if price >= (z_lo + z_hi) / 2 else "resistance")
        zones.append(Zone(kind, float(z_lo), float(z_hi), min(q.time for q in c), first, strength, len(c),
                          "tested" if rejections else "fresh"))
    # Keep the strongest zones nearest the current price.
    zones.sort(key=lambda z: (abs((z.low + z.high) / 2 - price) / atr) - 0.4 * z.strength)
    return sorted(zones[:max_zones], key=lambda z: z.low)


def fair_value_gaps(df: pd.DataFrame, min_atr: float = 0.1, keep: int = 8) -> list[Zone]:
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    atr = atr_series(df)
    t = times_of(df)
    n = len(df)
    out: list[Zone] = []
    for i in range(2, n):
        if lo[i] - hi[i - 2] >= min_atr * atr[i]:
            z = Zone("bull_fvg", float(hi[i - 2]), float(lo[i]), int(t[i - 1]), i)
        elif lo[i - 2] - hi[i] >= min_atr * atr[i]:
            z = Zone("bear_fvg", float(hi[i]), float(lo[i - 2]), int(t[i - 1]), i)
        else:
            continue
        later = slice(i + 1, n)
        if z.kind == "bull_fvg":
            filled = np.any(lo[later] <= z.low)
            touched = np.any(lo[later] < z.high)
        else:
            filled = np.any(hi[later] >= z.high)
            touched = np.any(hi[later] > z.low)
        z.status = "filled" if filled else "tested" if touched else "fresh"
        out.append(z)
    return [z for z in out if z.status != "filled"][-keep:]


def order_blocks(df: pd.DataFrame, swings: list[Swing], impulse_atr: float = 1.5, keep: int = 6) -> list[Zone]:
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    atr = atr_series(df)
    t = times_of(df)
    n = len(df)
    out: list[Zone] = []
    for i in range(1, n - 3):
        up_move = c[min(i + 3, n - 1)] - c[i]
        down_move = c[i] - c[min(i + 3, n - 1)]
        known_h = [s for s in swings if s.kind == "H" and s.confirmed_at <= i]
        known_l = [s for s in swings if s.kind == "L" and s.confirmed_at <= i]
        if c[i] < o[i] and up_move >= impulse_atr * atr[i]:
            # bearish candle before a strong up-move that breaks the last swing high
            if known_h and np.max(c[i + 1:i + 4]) > known_h[-1].price:
                z = Zone("bull_ob", float(lo[i]), float(hi[i]), int(t[i]), i)
                z.status = "mitigated" if np.any(lo[i + 4:] <= z.high) else "fresh"
                out.append(z)
        elif c[i] > o[i] and down_move >= impulse_atr * atr[i]:
            if known_l and np.min(c[i + 1:i + 4]) < known_l[-1].price:
                z = Zone("bear_ob", float(lo[i]), float(hi[i]), int(t[i]), i)
                z.status = "mitigated" if np.any(hi[i + 4:] >= z.low) else "fresh"
                out.append(z)
    return out[-keep:]


def supply_demand(df: pd.DataFrame, base_atr: float = 0.6, depart_atr: float = 2.0, keep: int = 6) -> list[Zone]:
    hi, lo, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    atr = atr_series(df)
    t = times_of(df)
    n = len(df)
    out: list[Zone] = []
    i = 0
    while i < n - 4:
        best = None
        for blen in (1, 2, 3):
            j = i + blen
            if j + 3 >= n:
                break
            b_hi, b_lo = hi[i:j].max(), lo[i:j].min()
            if b_hi - b_lo > base_atr * atr[i] * blen:
                break
            up = c[j:j + 3].max() - b_hi
            dn = b_lo - c[j:j + 3].min()
            if up >= depart_atr * atr[i]:
                best = Zone("demand", float(b_lo), float(b_hi), int(t[i]), j - 1)
            elif dn >= depart_atr * atr[i]:
                best = Zone("supply", float(b_lo), float(b_hi), int(t[i]), j - 1)
            if best:
                k = j + 3
                returned = np.any(lo[k:] <= best.high) if best.kind == "demand" else np.any(hi[k:] >= best.low)
                best.status = "tested" if returned else "fresh"
                out.append(best)
                i = j + 3
                break
        if best is None:
            i += 1
    return out[-keep:]
