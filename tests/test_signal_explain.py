"""Plain-language explanations and the locked-numbers LLM polish."""
import re
from datetime import date, datetime, timezone

from data.symbols import parse_symbol
from signals.decision import decide
from signals.events import UpcomingEvent
from signals.explain import GLOSSARY, build_explanation, money_texts
from signals.levels import build_levels
from signals.polish import accept, guard, polish
from signals.sizing import position_size
from signals.structure import MarketFacts, Swing

EURUSD = parse_symbol("EUR/USD")
JARGON = re.compile(r"\b(RSI|MACD|ATR|EMA|SMA|ADX|VWAP|Fibonacci|Bollinger|stochastic|R:R|bullish|bearish)\b", re.I)
TODAY = date(2026, 11, 13)


def facts(**kw):
    f = dict(price=1.1000, atr=0.008, last_bar="2026-11-13T00:00:00+00:00", days_in_trend=16, change_20d_pct=1.8,
             above_200d=True, momentum="rising", stretched="", bounce_level=1.0970, bounce_side="support",
             swing_lows=[Swing(1.0900, "2026-11-10")], swing_highs=[], high_60d=1.13, low_60d=1.08)
    f.update(kw)
    return MarketFacts(**f)


ANALYSIS = {
    "technical": {"timeframes": {"1wk": {"trend": "uptrend"}}},
    "fundamental": {"base": {"policy_rate": 2.0, "rate_change_6m": 0.0, "central_bank": "ECB"},
                    "quote": {"policy_rate": 4.0, "rate_change_6m": -0.5, "central_bank": "Federal Reserve"},
                    "rate_differential": -2.0, "n_factors": 3, "score": -10},
    "sentiment": {"label": "mixed", "n_articles": 5, "headlines": [{"sentiment": 0.3}, {"sentiment": -0.3}, {"sentiment": 0}]},
    "forecast": {"prob_up": 0.62, "expected_change_pct": 0.8, "horizon": 10, "timeframe": "1d"},
    "key_levels": {"supports": [{"price": 1.097}], "resistances": [{"price": 1.118}]},
}


def make(score=55, block=None, events=(), comps=None, min_rr=1.5, **plan_kw):
    f = facts()
    p = build_levels("long" if score >= 0 else "short", f.price, f.atr, [1.097, 1.085], plan_kw.get("res", [1.118, 1.13]),
                     [(1.09, "2026-11-10")], [], 1.13, 1.08, min_rr=min_rr)
    d = decide(score, comps or {"technical": 60, "fundamental": 30, "forecast": 40}, "uptrend", "uptrend", p, block, 0.3,
               min_rr=min_rr)
    rate = 1 / 1.0985
    size = position_size(EURUSD, p.entry_mid, p.stop, p.target1, p.target2, 10_000, 1, "EUR", rate, "USD")
    exp = build_explanation(EURUSD, d, p, f, ANALYSIS, list(events), size,
                            datetime(2026, 11, 18, 21, tzinfo=timezone.utc), today=TODAY)
    return d, p, exp


def main_texts(exp):
    yield from exp.reasons
    yield from exp.waiting_for
    yield from exp.cancel
    yield from (exp.entry_text, exp.entry_confirm, exp.stop_text, exp.stop_why, exp.confidence_text, exp.rr_text,
                exp.size_text, exp.event_warning or "")
    for t in exp.targets:
        yield t["why"]


def test_buy_card_answers_every_question_in_plain_words():
    d, p, exp = make()
    assert d.action == "BUY"
    assert 2 <= len(exp.reasons) <= 4
    assert exp.reasons[0] == "The price has been rising steadily for about 3 weeks"
    assert exp.entry_text == "Buy between 1.0970 and 1.1000"
    assert "1.0970" in exp.entry_confirm
    assert exp.stop_text.startswith("1.0880 (105 pips below your entry)")
    assert "recent low of 1.0900" in exp.stop_why and "won't knock you out" in exp.stop_why
    assert [t["label"] for t in exp.targets] == ["Target 1", "Target 2"]
    assert all(t["money"].startswith("+€") and t["pct"] > 0 for t in exp.targets)
    assert exp.rr_text.startswith(f"You risk €1 to potentially make €{p.rr1:.2f}")
    assert exp.size_text.startswith("Buy 0.10 lots")
    assert any("1.0880" in c and "don't enter" in c for c in exp.cancel)
    assert any("expired" in c for c in exp.cancel)
    assert exp.confidence_text.startswith("High")
    assert not exp.waiting_for
    for t in main_texts(exp):
        assert not JARGON.search(t), t


def test_wait_card_lists_exact_conditions():
    ev = UpcomingEvent("2026-11-14", "US CPI (inflation)", "US inflation report", "USD", True, 1)
    d, p, exp = make(block=ev, events=[ev])
    assert d.action == "WAIT"
    assert any("US inflation report tomorrow (Sat 14 Nov)" in w for w in exp.waiting_for)
    assert exp.event_warning.startswith("The US inflation report is tomorrow")
    assert not exp.entry_text and not exp.targets and not exp.cancel
    for t in main_texts(exp):
        assert not JARGON.search(t), t


def test_wait_for_better_price_when_reward_too_small():
    d, p, exp = make(res=[1.1085, 1.13])
    assert "rr_too_low" in d.wait_codes
    assert any(w.startswith("Wait for the price to dip to about") for w in exp.waiting_for)


def test_wait_without_direction_gives_both_triggers():
    d, p, exp = make(score=10, comps={"technical": 10, "forecast": 5})
    w = " ".join(exp.waiting_for)
    assert "above 1.1180 would point to a buy" in w and "below 1.0970 would point to a sell" in w


def test_reasons_describe_interest_rates_in_plain_words():
    _, _, exp = make(score=-55, comps={"technical": -60, "fundamental": -40, "forecast": -30})
    all_reasons = " ".join(exp.reasons)
    assert "Interest rates are higher in the US than in the Eurozone" in all_reasons or exp.reasons


def test_money_texts_for_too_small_account():
    size = position_size(EURUSD, 1.10, 1.095, 1.11, 1.12, 100, 1, "EUR", 1 / 1.1, "USD")
    m = money_texts(EURUSD, "BUY", 2.0, 3.0, size, "EUR")
    assert "too small" in m["size_text"] and m["target_money"] == [None, None]


def test_glossary_has_one_liners():
    for term in ("Stop loss", "Take profit", "Lot", "Pip", "Spread", "Margin"):
        assert term in GLOSSARY and len(GLOSSARY[term]) < 160


# ---------------- LLM polish guard ----------------
def test_guard_rejects_changed_numbers_and_jargon():
    o = "Wait for a daily close above 1.0950"
    assert accept(o, "Hold off until the day ends above 1.0950")
    assert not accept(o, "Hold off until the day ends above 1.0960")       # changed number
    assert not accept(o, "Hold off until the day ends above 1.0950 or 1.1")  # added number
    assert not accept(o, "Wait for RSI to confirm above 1.0950")           # jargon
    assert guard([o], ["x", "y"]) == [o]                                    # wrong length -> originals


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def run(self, system, messages, tools, execute, model=None, max_steps=12, on_event=None):
        from agent.llm.base import AgentResult

        return AgentResult(self.reply)


class DictCache:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v, ttl):
        self.d[k] = v


def test_polish_keeps_good_rewrites_and_drops_bad_ones():
    texts = ["The price has been rising steadily for about 3 weeks", "Wait for a daily close above 1.0950"]
    reply = '["For roughly 3 weeks the price has climbed steadily", "Wait until a day finishes above 1.0990"]'
    out = polish(texts, provider=FakeLLM(reply), cache=DictCache())
    assert out[0] == "For roughly 3 weeks the price has climbed steadily"
    assert out[1] == texts[1]     # number changed -> template kept


def test_polish_failure_returns_originals():
    class Boom:
        def run(self, *a, **k):
            raise RuntimeError("no key")

    texts = ["Recent news is mixed"]
    assert polish(texts, provider=Boom(), cache=DictCache()) == texts
