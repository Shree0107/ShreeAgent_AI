"""BUY / SELL / WAIT decision from the combined score, agreement checks, events and the level plan.

The combined score (-100..100) is the weighted blend from analysis.combined (technical 45%,
fundamental 25%, news 10%, forecast 20% scaled by backtest trust). A direction is only turned into
BUY/SELL when EVERY gate passes; otherwise the answer is WAIT with the list of reasons.

Gates (in order):
  no_direction        |score| < min_score
  trend_not_confirming the price trend (technical score) doesn't point the same way (>= 10 in that direction)
  timeframes_conflict daily and weekly trends point in opposite directions
  components_conflict 2+ components point the other way
  low_confidence      confidence below the configured minimum
  event               a major event (CPI, jobs, central bank, earnings) is within the blackout window
  stale_data          the latest daily candle is more than 4 days old
  stop_too_wide       the structural stop is more than max_stop_atr x the daily range away
  level_too_close     a level sits right in front of the price (needs a breakout first)
  rr_too_low          reward/risk to target 1 below min_rr
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from signals.events import UpcomingEvent
from signals.levels import LevelPlan

CONF_RANK = {"Low": 0, "Medium": 1, "High": 2}
COMPONENT_THRESHOLD = 20    # a component "has an opinion" at |score| >= 20
TREND_CONFIRM = 10          # technical score must be at least this far in the trade direction
STALE_DAYS = 4
TREND_SIGN = {"uptrend": 1, "downtrend": -1, "sideways": 0}


@dataclass
class Decision:
    action: str                       # BUY | SELL | WAIT
    lean: str | None                  # long | short | None (direction the score leans, even when WAIT)
    score: float
    confidence: str                   # Low | Medium | High
    agree: list[str] = field(default_factory=list)
    mixed: list[str] = field(default_factory=list)
    oppose: list[str] = field(default_factory=list)
    wait_codes: list[str] = field(default_factory=list)
    blocking_event: dict | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def strength(self) -> float:
        """Sort key: actionable signals first, then by |score| weighted by confidence."""
        return (1000 if self.action != "WAIT" else 0) + abs(self.score) * (1 + 0.5 * CONF_RANK[self.confidence])


def _sign(v: float) -> int:
    return 1 if v >= COMPONENT_THRESHOLD else -1 if v <= -COMPONENT_THRESHOLD else 0


def confidence(components: dict[str, float], score: float, daily_trend: str, weekly_trend: str | None,
               min_score: float = 25, high_score: float = 50) -> tuple[str, list[str], list[str], list[str]]:
    """(label, agreeing, mixed, opposing) component names."""
    d = 1 if score >= 0 else -1
    agree = [k for k, v in components.items() if _sign(v) == d]
    oppose = [k for k, v in components.items() if _sign(v) == -d]
    mixed = [k for k, v in components.items() if _sign(v) == 0]
    n = len(components)
    td, tw = TREND_SIGN.get(daily_trend, 0), TREND_SIGN.get(weekly_trend or "", 0)
    trend_conflict = td * tw == -1
    if (abs(score) >= high_score and not oppose and n >= 2 and len(agree) >= min(3, n)
            and not trend_conflict and tw == d):
        return "High", agree, mixed, oppose
    if abs(score) >= min_score and not trend_conflict and (
            not oppose or (len(oppose) == 1 and len(agree) >= 2 and "technical" not in oppose)):
        return "Medium", agree, mixed, oppose
    return "Low", agree, mixed, oppose


def decide(
    score: float,
    components: dict[str, float],
    daily_trend: str,
    weekly_trend: str | None,
    plan: LevelPlan | None,
    block: UpcomingEvent | None,
    data_age_days: float,
    min_score: float = 25,
    high_score: float = 50,
    min_confidence: str = "Medium",
    min_rr: float = 1.5,
) -> Decision:
    d = 1 if score >= 0 else -1
    lean = "long" if d > 0 else "short"
    conf, agree, mixed, oppose = confidence(components, score, daily_trend, weekly_trend, min_score, high_score)
    codes: list[str] = []

    if abs(score) < min_score:
        codes.append("no_direction")
    if components.get("technical", 0) * d < TREND_CONFIRM:
        codes.append("trend_not_confirming")
    if TREND_SIGN.get(daily_trend, 0) * TREND_SIGN.get(weekly_trend or "", 0) == -1:
        codes.append("timeframes_conflict")
    if len(oppose) >= 2:
        codes.append("components_conflict")
    if CONF_RANK[conf] < CONF_RANK.get(min_confidence, 1):
        codes.append("low_confidence")
    if block is not None:
        codes.append("event")
    if data_age_days > STALE_DAYS:
        codes.append("stale_data")
    if plan is None:
        codes.append("no_levels")
    else:
        if "stop_too_wide" in plan.problems:
            codes.append("stop_too_wide")
        if "level_too_close" in plan.problems:
            codes.append("level_too_close")
        if plan.rr1 < min_rr:
            codes.append("rr_too_low")

    action = "WAIT" if codes else ("BUY" if d > 0 else "SELL")
    return Decision(action, lean if abs(score) >= min_score else None, round(score, 1), conf, agree, mixed, oppose,
                    codes, block.as_dict() if block else None)
