"""Signal history, outcome tracking, win rate, and the end-to-end service (offline)."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from data.symbols import parse_symbol
from signals.history import SignalHistory, evaluate
from signals.service import build_signal, is_fresh, watchlist_signals, with_sizing
from tests.conftest import FakeData

GEN = "2026-11-02T09:00:00+00:00"
EXP = "2026-11-05T21:00:00+00:00"
SIG = {"action": "BUY", "entry_low": 1.0970, "entry_high": 1.1000, "stop": 1.0880, "target1": 1.1170,
       "target2": 1.1290, "generated_at": GEN, "expires_at": EXP}


def bars(rows, start="2026-11-02T10:00:00+00:00"):
    """rows: (low, high, close) per hourly bar."""
    idx = pd.date_range(start, periods=len(rows), freq="h")
    return pd.DataFrame({"open": [r[2] for r in rows], "low": [r[0] for r in rows], "high": [r[1] for r in rows],
                         "close": [r[2] for r in rows]}, index=idx)


NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def test_target_hit_after_entry():
    o = evaluate(SIG, bars([(1.1010, 1.1030, 1.102), (1.0985, 1.1010, 1.099), (1.1000, 1.1180, 1.115)]), NOW)
    assert o.status == "hit_target1" and o.entered_at is not None


def test_target2_and_stop_after_target1():
    b = bars([(1.0990, 1.1000, 1.0995), (1.1000, 1.1180, 1.115), (1.1150, 1.1300, 1.129)])
    assert evaluate(SIG, b, NOW).status == "hit_target2"
    b2 = bars([(1.0990, 1.1000, 1.0995), (1.1000, 1.1180, 1.115), (1.0870, 1.1100, 1.09)])
    assert evaluate(SIG, b2, NOW).status == "hit_target1"   # target 1 already banked -> still a win


def test_stop_hit_and_same_bar_counts_as_stop():
    assert evaluate(SIG, bars([(1.0985, 1.1000, 1.099), (1.0870, 1.0990, 1.088)]), NOW).status == "hit_stop"
    assert evaluate(SIG, bars([(1.0985, 1.1000, 1.099), (1.0870, 1.1200, 1.1)]), NOW).status == "hit_stop"


def test_not_entered_expired_missed_cancelled():
    assert evaluate(SIG, bars([(1.1010, 1.1050, 1.104)]), NOW).status == "expired"
    assert evaluate(SIG, bars([(1.1010, 1.1050, 1.104)]), datetime(2026, 11, 3, tzinfo=timezone.utc)).status == "waiting_entry"
    assert evaluate(SIG, bars([(1.1010, 1.1180, 1.115)]), NOW).status == "missed"
    sell = {**SIG, "action": "SELL", "entry_low": 1.1000, "entry_high": 1.1030, "stop": 1.1120, "target1": 1.0900, "target2": 1.0800}
    assert evaluate(sell, bars([(1.0950, 1.0990, 1.096)]), NOW).status == "expired"
    assert evaluate(sell, bars([(1.1040, 1.1130, 1.1125)]), NOW).status == "cancelled"
    assert evaluate(sell, bars([(1.0990, 1.1010, 1.1005), (1.0890, 1.0990, 1.0895)]), NOW).status == "hit_target1"


def card(symbol="EUR/USD", action="BUY", stop=1.0880, gen=GEN):
    return {"symbol": symbol, "action": action, "generated_at": gen, "expires_at": EXP, "confidence": "Medium",
            "score": 40, "levels": {"entry_low": 1.097, "entry_high": 1.1, "entry_mid": 1.0985, "stop": stop,
                                    "target1": 1.117, "target2": 1.129}}


def test_record_dedupes_and_replaces(tmp_path):
    h = SignalHistory(tmp_path / "s.sqlite")
    assert h.record(card()) is not None
    assert h.record(card()) is None                       # same idea again -> not duplicated
    assert h.record({**card(), "action": "WAIT"}) is None  # WAIT isn't a trade
    new_id = h.record(card(stop=1.0850))                  # different levels -> replaces the pending one
    rows = h.history()
    assert len(rows) == 2 and rows[0]["id"] == new_id
    assert {r["status"] for r in rows} == {"waiting_entry", "replaced"}


def test_outcomes_and_win_rate(tmp_path):
    h = SignalHistory(tmp_path / "s.sqlite")
    h.record(card("EUR/USD"))
    h.record(card("GBP/USD"))
    win = bars([(1.0990, 1.1000, 1.0995), (1.1000, 1.1180, 1.115)])
    loss = bars([(1.0990, 1.1000, 1.0995), (1.0870, 1.0990, 1.088)])
    assert h.update_outcomes(lambda s: win if s == "EUR/USD" else loss, NOW) == 2
    wr = h.win_rates()
    assert wr["EUR/USD"]["wins"] == 1 and wr["EUR/USD"]["win_rate"] == 100.0
    assert wr["GBP/USD"]["losses"] == 1 and wr["GBP/USD"]["win_rate"] == 0.0
    assert h.update_outcomes(lambda s: win if s == "EUR/USD" else loss, NOW) == 0   # idempotent


# ---------------- end-to-end, offline ----------------
def test_build_signal_end_to_end_offline(tmp_path):
    h = SignalHistory(tmp_path / "s.sqlite")
    now = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
    c = build_signal(parse_symbol("EUR/USD"), data=FakeData(), now=now, history=h)
    json.dumps(c)                                          # stored as JSON
    assert c["action"] in ("BUY", "SELL", "WAIT")
    assert c["disclaimer"] == "This is analysis, not financial advice. Always use a stop loss."
    # FakeData has a US CPI release today: a major event, so the answer must be WAIT
    assert c["action"] == "WAIT" and "event" in c["decision"]["wait_codes"]
    assert any("inflation report" in w for w in c["explanation"]["waiting_for"])
    assert h.latest("EUR/USD")["generated_at"] == c["generated_at"]
    assert is_fresh(c, now + timedelta(minutes=5), 60) and not is_fresh(c, now + timedelta(hours=2), 60)


class QuietData(FakeData):
    def upcoming_events(self, currencies, days=14):
        return []


def test_watchlist_sorted_and_sized(tmp_path):
    h = SignalHistory(tmp_path / "s.sqlite")
    now = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
    cards = watchlist_signals(["EUR/USD", "AAPL"], data=QuietData(drift=0.003), history=h, now=now)
    assert len(cards) == 2 and all("error" not in c for c in cards)
    assert cards[0]["strength"] >= cards[1]["strength"]
    for c in cards:
        sized = with_sizing(c, 10_000, 1, "EUR", data=QuietData())
        if sized["action"] in ("BUY", "SELL"):
            assert sized["size"]["actual_risk"] <= 100
            assert sized["explanation"]["size_text"]
    # second call reuses the stored cards (same generated_at)
    again = watchlist_signals(["EUR/USD", "AAPL"], data=QuietData(drift=0.003), history=h, now=now + timedelta(minutes=1))
    assert {c["generated_at"] for c in again} == {c["generated_at"] for c in cards}
