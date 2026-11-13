"""Entry zone, stop loss and targets from market structure + volatility.

Rules (BUY; SELL is the exact mirror, computed by negating every price):
  Entry   : nearest support within 0.5 x ATR below price -> zone [support, price] ("pullback");
            otherwise [price - 0.3 x ATR, price] ("market"). Zone width is capped at 0.5 x ATR.
  Stop    : below the most recent swing low under the entry zone (last 30 bars), minus 0.25 x ATR and
            the broker spread. Never closer than 1 x ATR to the entry midpoint, so normal noise can't
            hit it. Wider than `max_stop_atr` x ATR -> problem "stop_too_wide".
  Target 1: the nearest real level above the zone (support/resistance, recent swing high, 60-day high),
            placed 0.1 x ATR in front of it. If its reward/risk is below `min_rr` -> problem "level_in_way".
            A level closer than 0.5 x ATR above the price -> problem "level_too_close" (needs a breakout).
  Target 2: the next level at least 0.5 x ATR beyond target 1; if none, projected (entry + 3 x risk).
  Risk/reward is measured from the middle of the entry zone.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

ENTRY_ZONE_MAX_ATR = 0.5
MARKET_ZONE_ATR = 0.3
STOP_BUFFER_ATR = 0.25
MIN_STOP_ATR = 1.0
TARGET_FRONT_RUN_ATR = 0.1
MIN_LEVEL_ROOM_ATR = 0.5
SWING_LOOKBACK = 30


@dataclass
class LevelPlan:
    direction: str                     # long | short
    entry_low: float
    entry_high: float
    entry_mid: float
    entry_kind: str                    # pullback | market
    entry_anchor: float | None         # the support/resistance the pullback zone leans on
    stop: float
    stop_kind: str                     # swing | min_distance | volatility
    stop_anchor: float | None          # the swing low/high the stop hides behind
    stop_anchor_date: str | None
    target1: float
    target2: float
    target1_kind: str                  # level | projected
    target2_kind: str
    target1_level: float | None        # the level target 1 sits in front of
    risk: float                        # |entry_mid - stop|
    rr1: float
    rr2: float
    problems: list[str] = field(default_factory=list)   # stop_too_wide | level_in_way | level_too_close
    better_entry: float | None = None  # entry that would give min_rr against target 1 (for WAIT text)
    breakout_level: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _dedupe(levels: list[float], tol: float) -> list[float]:
    out: list[float] = []
    for lv in sorted(levels):
        if not out or lv - out[-1] > tol:
            out.append(lv)
    return out


def _long_plan(price, atr, supports, resistances, swing_lows, swing_highs, high_60d, spread, min_rr, max_stop_atr):
    sup = sorted([s for s in supports if s < price], reverse=True)

    # ---- entry ----
    anchor = None
    if sup and price - sup[0] <= ENTRY_ZONE_MAX_ATR * atr:
        lo, kind, anchor = sup[0], "pullback", sup[0]
    else:
        lo, kind = price - MARKET_ZONE_ATR * atr, "market"
    hi = price
    mid = (lo + hi) / 2

    # ---- stop ----
    below = [(p, d) for p, d in swing_lows if p < lo]
    if below:
        s_anchor, s_date = below[0]                      # newest first -> most recent swing low under the zone
        stop = s_anchor - STOP_BUFFER_ATR * atr - spread
        stop_kind = "swing"
    else:
        s_anchor, s_date = None, None
        stop = lo - 1.5 * atr - spread
        stop_kind = "volatility"
    if mid - stop < MIN_STOP_ATR * atr:
        stop = mid - MIN_STOP_ATR * atr - spread
        stop_kind = "min_distance" if s_anchor is not None else "volatility"
    risk = mid - stop

    problems: list[str] = []
    if risk > max_stop_atr * atr:
        problems.append("stop_too_wide")

    # ---- targets ----
    cands = [r for r in resistances if r > hi] + [h for h, _ in swing_highs if h > hi]
    if high_60d and high_60d > hi:
        cands.append(high_60d)
    cands = _dedupe(cands, 0.3 * atr)

    breakout = None
    if cands and cands[0] - price < MIN_LEVEL_ROOM_ATR * atr:
        problems.append("level_too_close")
        breakout = cands[0]

    t1_level = None
    if cands:
        t1_level = cands[0]
        t1, t1_kind = t1_level - TARGET_FRONT_RUN_ATR * atr, "level"
        if t1 <= mid:  # level is inside the zone: aim for the next one
            t1_level = cands[1] if len(cands) > 1 else None
            t1, t1_kind = (t1_level - TARGET_FRONT_RUN_ATR * atr, "level") if t1_level else (mid + max(2 * atr, min_rr * risk), "projected")
    else:
        t1, t1_kind = mid + max(2 * atr, min_rr * risk), "projected"

    beyond = [c for c in cands if c - TARGET_FRONT_RUN_ATR * atr >= t1 + MIN_LEVEL_ROOM_ATR * atr]
    if beyond:
        t2, t2_kind = beyond[0] - TARGET_FRONT_RUN_ATR * atr, "level"
    else:
        t2 = max(mid + 3 * risk, t1 + risk)
        t2_kind = "projected"

    rr1 = (t1 - mid) / risk if risk > 0 else 0.0
    rr2 = (t2 - mid) / risk if risk > 0 else 0.0
    better = None
    if rr1 < min_rr:
        problems.append("level_in_way")
        e = (t1 + min_rr * stop) / (1 + min_rr)        # entry where (t1-e)/(e-stop) == min_rr
        if e - stop >= MIN_STOP_ATR * atr * 0.5:
            better = e
        if breakout is None and t1_kind == "level":
            breakout = t1_level

    return dict(
        entry_low=lo, entry_high=hi, entry_mid=mid, entry_kind=kind, entry_anchor=anchor,
        stop=stop, stop_kind=stop_kind, stop_anchor=s_anchor, stop_anchor_date=s_date,
        target1=t1, target2=t2, target1_kind=t1_kind, target2_kind=t2_kind, target1_level=t1_level,
        risk=risk, rr1=rr1, rr2=rr2, problems=problems, better_entry=better, breakout_level=breakout,
    )


def build_levels(
    direction: str,
    price: float,
    atr: float,
    supports: list[float],
    resistances: list[float],
    swing_lows: list[tuple[float, str]],
    swing_highs: list[tuple[float, str]],
    high_60d: float | None = None,
    low_60d: float | None = None,
    spread: float = 0.0,
    min_rr: float = 1.5,
    max_stop_atr: float = 3.0,
    decimals: int = 5,
) -> LevelPlan:
    """direction: 'long' or 'short'. Swings are (price, iso_date), newest first."""
    if direction not in ("long", "short"):
        raise ValueError("direction must be 'long' or 'short'")
    if not atr or atr <= 0 or not price or price <= 0:
        raise ValueError("price and ATR must be positive")

    if direction == "long":
        p = _long_plan(price, atr, supports, resistances, swing_lows, swing_highs, high_60d, spread, min_rr, max_stop_atr)
    else:
        # Mirror: negate every price so a short is a long on the negated series. Supports <-> resistances,
        # swing highs <-> swing lows, 60-day low <-> 60-day high.
        neg = lambda xs: [-x for x in xs]
        p = _long_plan(
            -price, atr, neg(resistances), neg(supports),
            [(-x, d) for x, d in swing_highs], [(-x, d) for x, d in swing_lows],
            -low_60d if low_60d else None, spread, min_rr, max_stop_atr,
        )
        for k in ("entry_low", "entry_high", "entry_mid", "entry_anchor", "stop", "stop_anchor",
                  "target1", "target2", "target1_level", "better_entry", "breakout_level"):
            if p[k] is not None:
                p[k] = -p[k]
        p["entry_low"], p["entry_high"] = p["entry_high"], p["entry_low"]

    r = lambda x: None if x is None else round(float(x), decimals)
    for k in ("entry_low", "entry_high", "entry_mid", "entry_anchor", "stop", "stop_anchor",
              "target1", "target2", "target1_level", "better_entry", "breakout_level", "risk"):
        p[k] = r(p[k])
    # Recompute R:R from the rounded prices so the card's numbers are self-consistent.
    risk = abs(p["entry_mid"] - p["stop"])
    p["risk"] = r(risk)
    p["rr1"] = round(abs(p["target1"] - p["entry_mid"]) / risk, 2) if risk else 0.0
    p["rr2"] = round(abs(p["target2"] - p["entry_mid"]) / risk, 2) if risk else 0.0
    return LevelPlan(direction=direction, **p)
