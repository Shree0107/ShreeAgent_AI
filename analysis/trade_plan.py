"""Deterministic entry / stop-loss / take-profit zones from ATR and support/resistance.

The LLM explains these numbers but never computes them, so levels are reproducible
and can't be hallucinated. This is analysis only: nothing here places orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class TradePlan:
    direction: str               # long | short | none
    entry_zone: tuple[float, float] | None
    stop_loss: float | None
    take_profits: list[float] = field(default_factory=list)
    risk_reward: list[float] = field(default_factory=list)
    atr: float | None = None
    invalidation: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _round(x: float, price: float) -> float:
    # Precision that matches how the market quotes: EUR/USD 1.08123, USD/JPY 151.234, stocks 2dp
    nd = 2 if price >= 1000 else 3 if price >= 20 else 5 if price >= 1 else 6
    return round(x, nd)


def build_plan(
    bias: str,
    price: float,
    atr: float,
    supports: list[float],
    resistances: list[float],
    min_rr: float = 1.5,
) -> TradePlan:
    """Build long/short zones.

    Long : entry between price-0.3*ATR and price (or a pullback to the nearest support within 1 ATR);
           stop 0.5*ATR below the nearest support (at least 1*ATR from entry); targets at the next
           resistances, then 2R/3R if there aren't enough levels.
    Short: mirror image.
    """
    if not atr or atr <= 0 or not price:
        return TradePlan("none", None, None, notes=["ATR unavailable, cannot size levels"])
    sup = sorted([s for s in supports if s < price], reverse=True)
    res = sorted([r for r in resistances if r > price])

    if bias not in ("bullish", "bearish"):
        plan = TradePlan("none", None, None, atr=_round(atr, price))
        plan.notes.append("Neutral bias: no directional setup. Wait for a break of the levels below.")
        if res:
            plan.notes.append(f"Bullish trigger: daily close above {_round(res[0], price)}")
        if sup:
            plan.notes.append(f"Bearish trigger: daily close below {_round(sup[0], price)}")
        return plan

    long = bias == "bullish"
    if long:
        lo = sup[0] if sup and price - sup[0] <= atr else price - 0.3 * atr
        entry = (lo, price)
        ref = min(entry)
        base_stop = (sup[0] - 0.5 * atr) if sup else ref - 1.5 * atr
        stop = min(base_stop, ref - 1.0 * atr)
        risk = ((entry[0] + entry[1]) / 2) - stop
        targets = [r for r in res if r - ((entry[0] + entry[1]) / 2) >= 0.8 * risk][:2]
    else:
        hi = res[0] if res and res[0] - price <= atr else price + 0.3 * atr
        entry = (price, hi)
        ref = max(entry)
        base_stop = (res[0] + 0.5 * atr) if res else ref + 1.5 * atr
        stop = max(base_stop, ref + 1.0 * atr)
        risk = stop - ((entry[0] + entry[1]) / 2)
        targets = [s for s in sup if ((entry[0] + entry[1]) / 2) - s >= 0.8 * risk][:2]

    mid = (entry[0] + entry[1]) / 2
    sign = 1 if long else -1
    while len(targets) < 2:
        mult = 2 if not targets else 3
        targets.append(mid + sign * mult * risk)
    rr = [round(abs(t - mid) / risk, 2) for t in targets]

    plan = TradePlan(
        direction="long" if long else "short",
        entry_zone=(_round(entry[0], price), _round(entry[1], price)),
        stop_loss=_round(stop, price),
        take_profits=[_round(t, price) for t in targets],
        risk_reward=rr,
        atr=_round(atr, price),
        invalidation=f"{'Close below' if long else 'Close above'} {_round(stop, price)} invalidates the setup",
    )
    if rr[0] < min_rr:
        plan.notes.append(f"First target R:R {rr[0]} is below {min_rr}. Consider waiting for a better entry.")
    return plan
