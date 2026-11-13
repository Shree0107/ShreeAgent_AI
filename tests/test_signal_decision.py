"""BUY / SELL / WAIT gates, confidence and event handling."""
from datetime import date, datetime, timezone

import pytest

from data.providers.base import EconomicEvent
from data.symbols import parse_symbol
from signals.decision import confidence, decide
from signals.events import blocking_event, plain_title, symbol_events
from signals.levels import LevelPlan
from signals.service import expiry_time


def plan(rr1=2.0, problems=(), direction="long"):
    return LevelPlan(direction, 1.097, 1.100, 1.0985, "pullback", 1.097, 1.088, "swing", 1.09, "2026-11-10",
                     1.1172, 1.1292, "level", "level", 1.118, 0.0105, rr1, 2.9, list(problems))


GOOD = dict(score=55, components={"technical": 60, "fundamental": 40, "sentiment": 30, "forecast": 50},
            daily_trend="uptrend", weekly_trend="uptrend", plan=plan(), block=None, data_age_days=0.5)


def run(**kw):
    args = {**GOOD, **kw}
    return decide(**args)


def test_buy_when_everything_agrees():
    d = run()
    assert d.action == "BUY" and d.confidence == "High" and not d.wait_codes


def test_sell_mirror():
    d = run(score=-55, components={k: -v for k, v in GOOD["components"].items()},
            daily_trend="downtrend", weekly_trend="downtrend", plan=plan(direction="short"))
    assert d.action == "SELL" and d.lean == "short"


def test_wait_when_score_too_weak():
    d = run(score=15)
    assert d.action == "WAIT" and "no_direction" in d.wait_codes and d.lean is None


def test_wait_when_price_trend_disagrees():
    d = run(components={**GOOD["components"], "technical": -30})
    assert d.action == "WAIT" and "trend_not_confirming" in d.wait_codes


def test_wait_when_daily_and_weekly_conflict():
    d = run(weekly_trend="downtrend")
    assert d.action == "WAIT" and "timeframes_conflict" in d.wait_codes


def test_wait_when_two_components_oppose():
    d = run(score=30, components={"technical": 70, "fundamental": -40, "sentiment": -50, "forecast": 30})
    assert d.action == "WAIT" and "components_conflict" in d.wait_codes and d.confidence == "Low"


def test_wait_below_configured_confidence():
    medium = run(score=35, components={"technical": 50, "fundamental": 10, "forecast": 30})
    assert medium.confidence == "Medium" and medium.action == "BUY"
    strict = run(score=35, components={"technical": 50, "fundamental": 10, "forecast": 30}, min_confidence="High")
    assert strict.action == "WAIT" and "low_confidence" in strict.wait_codes


def test_wait_before_major_event():
    from signals.events import UpcomingEvent

    ev = UpcomingEvent("2026-11-13", "US CPI (inflation)", "US inflation report", "USD", True, 0)
    d = run(block=ev)
    assert d.action == "WAIT" and "event" in d.wait_codes and d.blocking_event["plain"] == "US inflation report"


def test_wait_on_stale_data():
    assert "stale_data" in run(data_age_days=6).wait_codes


def test_risk_reward_threshold_is_configurable():
    assert run(plan=plan(rr1=1.3)).action == "WAIT"
    assert "rr_too_low" in run(plan=plan(rr1=1.3)).wait_codes
    assert run(plan=plan(rr1=1.3), min_rr=1.2).action == "BUY"
    assert run(plan=plan(rr1=1.5)).action == "BUY"          # exactly at the minimum is allowed


def test_wait_on_level_problems():
    assert "stop_too_wide" in run(plan=plan(problems=["stop_too_wide"])).wait_codes
    assert "level_too_close" in run(plan=plan(problems=["level_too_close"])).wait_codes
    assert "no_levels" in run(plan=None).wait_codes


def test_confidence_levels():
    assert confidence({"technical": 60, "fundamental": 40, "forecast": 50}, 55, "uptrend", "uptrend")[0] == "High"
    # weekly not confirming -> not High
    assert confidence({"technical": 60, "fundamental": 40, "forecast": 50}, 55, "uptrend", "sideways")[0] == "Medium"
    # one opposing component is tolerated at Medium if two agree and it isn't the price trend
    assert confidence({"technical": 60, "fundamental": -40, "forecast": 50}, 35, "uptrend", "uptrend")[0] == "Medium"
    assert confidence({"technical": -60, "fundamental": 40, "forecast": 50}, 30, "uptrend", "uptrend")[0] == "Low"
    assert confidence({"technical": 60}, 20, "uptrend", "uptrend")[0] == "Low"


def test_strength_sorts_actionable_first():
    assert run().strength > run(score=90, plan=plan(rr1=1.0)).strength


# ---------------- events ----------------
class EvData:
    def __init__(self, events):
        self.events = events

    def upcoming_events(self, currencies, days=14):
        return [e for e in self.events if e.currency in currencies]


def _ev(day, cur, title):
    return EconomicEvent(datetime(2026, 11, day, tzinfo=timezone.utc), cur, title, "high", "test")


def test_events_plain_names_and_blocking():
    today = date(2026, 11, 13)
    data = EvData([_ev(13, "USD", "US PPI"), _ev(14, "USD", "US CPI (inflation)"), _ev(17, "EUR", "ECB monetary policy decision"),
                   _ev(15, "JPY", "BoJ policy decision")])
    evs = symbol_events(parse_symbol("EUR/USD"), data, today=today)
    assert [e.plain for e in evs] == ["US producer prices report", "US inflation report",
                                      "European Central Bank interest-rate decision"]
    assert [e.major for e in evs] == [False, True, True]
    # PPI today is minor (warning only); CPI tomorrow is major and inside a 1-day blackout
    b = blocking_event(evs, blackout_days=1, earnings_blackout_days=3)
    assert b.title == "US CPI (inflation)" and b.days_away == 1
    assert blocking_event(evs, blackout_days=0, earnings_blackout_days=3) is None


def test_stock_earnings_blackout():
    today = date(2026, 11, 13)
    evs = symbol_events(parse_symbol("AAPL"), EvData([]), next_earnings="2026-11-15", today=today)
    assert evs[0].title == "Earnings" and evs[0].days_away == 2
    assert blocking_event(evs, 1, earnings_blackout_days=3) is not None
    assert blocking_event(evs, 1, earnings_blackout_days=1) is None


def test_plain_title():
    assert plain_title("US Non-Farm Payrolls / Unemployment", "USD") == "US jobs report"
    assert plain_title("FOMC rate decision", "USD") == "Federal Reserve interest-rate decision"


def test_expiry_skips_weekends():
    fri = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
    exp = expiry_time(fri, 3)
    assert exp.date() == date(2026, 11, 18) and exp.hour == 21     # Mon, Tue, Wed
    assert expiry_time(datetime(2026, 11, 16, 9, tzinfo=timezone.utc), 1).date() == date(2026, 11, 17)


@pytest.mark.parametrize("score", [25, -25])
def test_threshold_edge_is_inclusive(score):
    sign = 1 if score > 0 else -1
    d = run(score=score, components={"technical": 30 * sign, "forecast": 30 * sign},
            daily_trend="uptrend" if sign > 0 else "downtrend", weekly_trend="sideways",
            plan=plan(direction="long" if sign > 0 else "short"))
    assert "no_direction" not in d.wait_codes
