"""Plan state machine: Waiting -> Ready -> Entry triggered -> In trade -> TP1 / TP2 / SL / break-even / time stop."""
from datetime import datetime, timedelta, timezone

from intraday.state import Bar, PlanState, advance, from_dict, tick

T0 = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)


def plan(direction="long", entry_type="limit", entry=1.1000, stop=1.0980, tp1=1.1030, tp2=1.1050, **kw):
    return PlanState(direction, entry_type, entry, stop, tp1, tp2, T0 + timedelta(hours=2), T0 + timedelta(hours=10),
                     ready_distance=0.0005, **kw)


def bar(m, o, h, l, c, closed=True):
    return Bar(T0 + timedelta(minutes=m), o, h, l, c, closed)


def kinds(evs):
    return [e.kind for e in evs]


def test_limit_long_full_cycle_to_target2():
    ps = plan()
    assert kinds(advance(ps, bar(5, 1.1020, 1.1022, 1.1012, 1.1015))) == []          # far away: waiting
    assert ps.state == "waiting"
    assert kinds(advance(ps, bar(10, 1.1015, 1.1016, 1.1004, 1.1004))) == ["get_ready"]
    assert ps.state == "ready" and ps.ready_at is not None
    evs = advance(ps, bar(15, 1.1004, 1.1006, 1.0995, 1.1002))
    assert kinds(evs) == ["entry_triggered"] and ps.state == "triggered" and ps.fill == 1.1000
    advance(ps, bar(20, 1.1002, 1.1010, 1.0998, 1.1008))
    assert ps.state == "in_trade"
    evs = advance(ps, bar(25, 1.1008, 1.1031, 1.1007, 1.1028))
    assert "breakeven_set" in kinds(evs) and "tp_hit" in kinds(evs)
    assert ps.state == "tp1_hit" and ps.stop_now == 1.1000 and not ps.closed
    evs = advance(ps, bar(30, 1.1028, 1.1052, 1.1025, 1.1049))
    assert kinds(evs) == ["tp_hit"] and ps.state == "tp2_hit" and ps.closed
    assert ps.r_multiple == round(0.5 * 1.5 + 0.5 * 2.5, 3)


def test_same_bar_stop_and_target_counts_as_stop():
    ps = plan()
    advance(ps, bar(5, 1.1003, 1.1004, 1.0999, 1.1001))                # filled
    evs = advance(ps, bar(10, 1.1001, 1.1035, 1.0975, 1.1010))         # touches both SL and TP1
    assert kinds(evs) == ["sl_hit"] and ps.state == "sl_hit" and ps.r_multiple == -1.0


def test_same_bar_entry_and_stop_is_a_loss():
    ps = plan(direction="long", entry_type="stop", entry=1.1010, stop=1.0990, tp1=1.1040, tp2=1.1060)
    evs = advance(ps, bar(5, 1.1000, 1.1045, 1.0985, 1.1000))
    assert kinds(evs) == ["entry_triggered", "sl_hit"] and ps.state == "sl_hit"


def test_breakeven_after_one_r():
    ps = plan()
    advance(ps, bar(5, 1.1002, 1.1003, 1.0999, 1.1001))
    evs = advance(ps, bar(10, 1.1001, 1.1021, 1.1000, 1.1018))        # +1R = 1.1020 reached
    assert "breakeven_set" in kinds(evs) and ps.stop_now == 1.1000
    evs = advance(ps, bar(15, 1.1018, 1.1019, 1.0999, 1.1000))
    assert kinds(evs) == ["breakeven"] and ps.state == "breakeven" and ps.r_multiple == 0.0


def test_target1_then_breakeven_keeps_target1_outcome():
    ps = plan()
    advance(ps, bar(5, 1.1002, 1.1003, 1.0999, 1.1001))
    advance(ps, bar(10, 1.1001, 1.1032, 1.1000, 1.1029))
    evs = advance(ps, bar(15, 1.1029, 1.1030, 1.0995, 1.0996))
    assert kinds(evs) == ["breakeven"] and ps.state == "tp1_hit" and ps.closed
    assert ps.r_multiple == 0.75


def test_time_stop_closes_at_flat_by():
    ps = plan()
    advance(ps, bar(5, 1.1002, 1.1003, 1.0999, 1.1001))
    evs = advance(ps, Bar(T0 + timedelta(hours=10), 1.1005, 1.1008, 1.1004, 1.1006))
    assert kinds(evs) == ["time_stop"] and ps.state == "time_stop" and ps.r_multiple == 0.3


def test_expiry_and_cancel_before_entry():
    ps = plan()
    evs = advance(ps, Bar(T0 + timedelta(hours=3), 1.1020, 1.1021, 1.1019, 1.1020))
    assert kinds(evs) == ["expired"] and ps.state == "expired"
    # breakout plan: a completed candle closing beyond the stop before entry cancels it
    ps = plan(entry_type="stop", entry=1.1010, stop=1.0990, tp1=1.1040, tp2=1.1060)
    assert kinds(advance(ps, bar(5, 1.1000, 1.1002, 1.0985, 1.0988, closed=False))) == []   # live tick: wait for close
    evs = advance(ps, bar(15, 1.0995, 1.0996, 1.0984, 1.0987))
    assert kinds(evs) == ["cancelled"] and ps.state == "cancelled"


def test_stop_entry_gap_fills_at_open_and_short_mirror():
    ps = plan(entry_type="stop", entry=1.1010, stop=1.0990, tp1=1.1040, tp2=1.1060)
    advance(ps, bar(5, 1.1015, 1.1018, 1.1013, 1.1016))
    assert ps.fill == 1.1015
    ps = plan(direction="short", entry=1.1000, stop=1.1020, tp1=1.0970, tp2=1.0950)
    advance(ps, bar(5, 1.0995, 1.1001, 1.0994, 1.0998))
    assert ps.state == "triggered"
    evs = advance(ps, bar(10, 1.0998, 1.0999, 1.0968, 1.0972))
    assert "tp_hit" in kinds(evs) and ps.state == "tp1_hit"


def test_tick_and_roundtrip():
    ps = plan()
    assert kinds(tick(ps, T0 + timedelta(minutes=1), 1.1004)) == ["get_ready"]
    ps2 = from_dict(ps.as_dict())
    assert ps2.state == "ready" and ps2.expires_at == ps.expires_at and ps2.checked_at == ps.checked_at
    assert kinds(tick(ps2, T0 + timedelta(minutes=2), 1.1000)) == ["entry_triggered"]
