"""Key price levels for today (from completed bars only).

  previous day high / low / close     from the 1H bars of the previous UTC day
  Asian session high / low            today's bars from 00:00 to 08:00 UTC (Tokyo session, before London)
  floor pivots P / R1 / S1            from the previous daily bar
  round numbers                       00 / 50 levels (forex), round prices (stocks)
  support / resistance zones          clustered swing points on the 1H and 15M charts
  Fibonacci 38.2 / 50 / 61.8          of the last big 1H swing
  VWAP (stocks only, real volume)     today's volume-weighted average price
Each level has a plain `label` for the main view and a `kind` for details/scoring.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from analysis import indicators as ind
from analysis.levels import pivot_points
from analysis.structure.liquidity import round_numbers
from analysis.structure.market import fibonacci, label_swings
from analysis.structure.swings import zigzag
from analysis.structure.zones import sr_zones


@dataclass
class Level:
    price: float
    kind: str          # pdh pdl pdc asian_high asian_low pivot r1 s1 round zone_1h zone_15m fib vwap
    label: str         # plain words
    strength: float = 1.0
    low: float | None = None    # zones: price band
    high: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _utc(df: pd.DataFrame) -> pd.DatetimeIndex:
    return df.index if df.index.tz is not None else df.index.tz_localize("UTC")


def previous_day(h1: pd.DataFrame, now) -> dict | None:
    if h1 is None or h1.empty:
        return None
    idx = _utc(h1)
    days = idx.normalize()
    today = pd.Timestamp(now).tz_convert("UTC").normalize()
    prev = days[days < today]
    if not len(prev):
        return None
    d = h1[days == prev[-1]]
    return {"high": float(d.high.max()), "low": float(d.low.min()), "close": float(d.close.iloc[-1]),
            "day": prev[-1].date().isoformat()}


def asian_range(df: pd.DataFrame, now) -> dict | None:
    """Today's 00:00-08:00 UTC range (needs >= 8 bars of 15 min)."""
    if df is None or df.empty:
        return None
    idx = _utc(df)
    today = pd.Timestamp(now).tz_convert("UTC").normalize()
    part = df[(idx >= today) & (idx < today + pd.Timedelta(hours=8))]
    if len(part) < 8:
        return None
    return {"high": float(part.high.max()), "low": float(part.low.min()), "bars": len(part),
            "complete": bool(pd.Timestamp(now) >= today + pd.Timedelta(hours=8))}


def key_levels(ctx) -> list[Level]:
    memo = ctx.cache()
    if "levels" in memo:
        return memo["levels"]
    out: list[Level] = []
    h1, m15, d1 = ctx.df("1h"), ctx.main, ctx.df("1d")
    pd_ = previous_day(h1 if len(h1) else m15, ctx.now)
    if pd_:
        out += [Level(pd_["high"], "pdh", "yesterday's high", 2.0), Level(pd_["low"], "pdl", "yesterday's low", 2.0),
                Level(pd_["close"], "pdc", "yesterday's closing price", 1.0)]
    if ctx.symbol.is_fx:
        ar = asian_range(m15, ctx.now)
        if ar:
            out += [Level(ar["high"], "asian_high", "the high of the night (Asian session)", 1.5),
                    Level(ar["low"], "asian_low", "the low of the night (Asian session)", 1.5)]
    if len(d1) >= 2:
        pv = _pivots(d1)
        out += [Level(pv["P"], "pivot", "today's middle level", 1.0), Level(pv["R1"], "r1", "today's first upper level", 1.0),
                Level(pv["S1"], "s1", "today's first lower level", 1.0)]
    if len(m15):
        for r in round_numbers(ctx.last, ctx.symbol.is_fx, 2):
            out.append(Level(r.price, "round", "a round number", 1.0))
    for tf, df, kind, w in (("1h", h1, "zone_1h", 1.0), ("15m", m15, "zone_15m", 0.6)):
        if len(df) >= 60:
            d = df.tail(300)
            sw = zigzag(d, 2.0)
            for z in sr_zones(d, sw, max_zones=6):
                mid = (z.low + z.high) / 2
                lbl = "a price area that held several times" + (" on the 1-hour chart" if tf == "1h" else "")
                out.append(Level(mid, kind, lbl, round(w * min(z.strength, 10) / 3, 2), z.low, z.high))
    if len(h1) >= 60:
        d = h1.tail(300)
        fib = fibonacci(d, label_swings(zigzag(d, 2.0)), 3.0)
        if fib:
            for r in fib["retracements"]:
                if r["ratio"] in (0.382, 0.5, 0.618):
                    out.append(Level(r["price"], "fib", "a typical pullback level of the last big move", 0.8))
    if not ctx.symbol.is_fx and len(m15) and m15["volume"].sum() > 0:
        v = ind.vwap(m15.tail(60), intraday=True)
        if pd.notna(v.iloc[-1]):
            out.append(Level(float(v.iloc[-1]), "vwap", "today's average traded price", 1.0))
    memo["levels"] = out
    return out


def _pivots(d1: pd.DataFrame) -> dict:
    # pivot_points uses the second-to-last row as "previous completed": our frame holds completed bars only,
    # so append a dummy row to make the last completed daily bar the one it reads.
    pad = pd.concat([d1.tail(1), d1.tail(1)])
    return pivot_points(pad)


def levels_beyond(levels: list[Level], price: float, direction: str, min_dist: float = 0.0) -> list[Level]:
    """Levels above (long) / below (short) `price` by at least `min_dist`, nearest first."""
    if direction == "long":
        xs = [l for l in levels if l.price > price + min_dist]
        return sorted(xs, key=lambda l: l.price)
    xs = [l for l in levels if l.price < price - min_dist]
    return sorted(xs, key=lambda l: -l.price)


def nearest_label(levels: list[Level], price: float, tol: float) -> Level | None:
    best = None
    for l in levels:
        d = abs(l.price - price)
        if l.low is not None and l.high is not None and l.low - tol <= price <= l.high + tol:
            d = 0
        if d <= tol and (best is None or l.strength > best.strength):
            best = l
    return best
