"""Liquidity: where stop orders tend to cluster, and when price runs them.

Levels: previous day / week high & low, Asian session high & low (Tokyo 09:00-18:00 = 00:00-09:00 UTC),
equal highs / lows (>= 2 swings within 0.1 x ATR), round numbers (00 and 50 levels for forex).
Sweep (stop hunt): a wick beyond a level that closes back on the original side within 1-3 bars.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from analysis.structure.swings import Swing, atr_series, times_of


@dataclass
class LiqLevel:
    kind: str        # pdh | pdl | pwh | pwl | asian_high | asian_low | equal_highs | equal_lows | round
    price: float
    t_start: int
    label: str
    swept: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Sweep:
    level_kind: str
    level: float
    direction: str   # "up" = wick above a high then back below (bearish hint); "down" = mirror (bullish hint)
    idx: int
    time: int

    def as_dict(self) -> dict:
        return asdict(self)


def _utc(df: pd.DataFrame) -> pd.DatetimeIndex:
    return df.index if df.index.tz is not None else df.index.tz_localize("UTC")


def session_levels(df: pd.DataFrame) -> list[LiqLevel]:
    """Previous day/week high & low and today's Asian range (intraday bars; daily bars give the week levels)."""
    idx = _utc(df)
    out: list[LiqLevel] = []
    days = idx.normalize()
    last_day = days[-1]
    prev_days = days[days < last_day]
    if len(prev_days):
        d = df[days == prev_days[-1]]
        t0 = int(last_day.timestamp())
        out += [LiqLevel("pdh", float(d.high.max()), t0, "Previous day high"),
                LiqLevel("pdl", float(d.low.min()), t0, "Previous day low")]
    weeks = days - pd.to_timedelta(idx.weekday, unit="D")      # Monday 00:00 UTC of each bar's week
    this_week = weeks[-1]
    prev_weeks = weeks[weeks < this_week]
    if len(prev_weeks):
        w = df[weeks == prev_weeks[-1]]
        t0 = int(this_week.timestamp())
        out += [LiqLevel("pwh", float(w.high.max()), t0, "Previous week high"),
                LiqLevel("pwl", float(w.low.min()), t0, "Previous week low")]
    if len(df) > 1 and (idx[1] - idx[0]) < pd.Timedelta(hours=4):
        asian = df[(days == last_day) & (idx.hour < 9)]
        if len(asian):
            t0 = int(last_day.timestamp())
            out += [LiqLevel("asian_high", float(asian.high.max()), t0, "Asian session high"),
                    LiqLevel("asian_low", float(asian.low.min()), t0, "Asian session low")]
    return out


def equal_levels(df: pd.DataFrame, swings: list[Swing], tol_atr: float = 0.1) -> list[LiqLevel]:
    atr = float(atr_series(df)[-1])
    out: list[LiqLevel] = []
    for kind, label in (("H", "equal_highs"), ("L", "equal_lows")):
        pts = [s for s in swings if s.kind == kind][-10:]
        used: set[int] = set()
        for i, a in enumerate(pts):
            if a.idx in used:
                continue
            group = [b for b in pts[i + 1:] if abs(b.price - a.price) <= tol_atr * atr]
            if group:
                used |= {b.idx for b in group}
                price = float(np.mean([a.price] + [b.price for b in group]))
                out.append(LiqLevel(label, price, a.time, f"Equal {'highs' if kind == 'H' else 'lows'} ({len(group) + 1}x)"))
    return out


def round_numbers(price: float, is_fx: bool, n_each_side: int = 2) -> list[LiqLevel]:
    if price <= 0:
        return []
    if is_fx:
        step = 0.005 if price < 10 else 0.5   # 1.0950 / 1.1000 ; JPY 151.50 / 152.00
    else:
        mag = 10 ** int(np.floor(np.log10(price)))
        step = mag / 2 if price / mag < 5 else mag
    base = np.floor(price / step) * step
    return [LiqLevel("round", float(round(base + k * step, 6)), 0, "Round number")
            for k in range(-n_each_side + 1, n_each_side + 1)]


def sweeps(df: pd.DataFrame, levels: list[LiqLevel], window: int = 3, lookback: int = 50) -> list[Sweep]:
    hi, lo, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    t = times_of(df)
    n = len(df)
    out: list[Sweep] = []
    for lv in levels:
        start = max(1, n - lookback)
        for i in range(start, n):
            if t[i] < lv.t_start:
                continue
            is_high = lv.kind in ("pdh", "pwh", "asian_high", "equal_highs") or (lv.kind == "round" and c[i - 1] < lv.price)
            if is_high and hi[i] > lv.price and c[i - 1] <= lv.price:
                if any(c[j] < lv.price for j in range(i, min(n, i + window))):
                    out.append(Sweep(lv.kind, lv.price, "up", i, int(t[i])))
                    lv.swept = True
                    break
            if not is_high and lo[i] < lv.price and c[i - 1] >= lv.price:
                if any(c[j] > lv.price for j in range(i, min(n, i + window))):
                    out.append(Sweep(lv.kind, lv.price, "down", i, int(t[i])))
                    lv.swept = True
                    break
    return sorted(out, key=lambda s: s.idx)
