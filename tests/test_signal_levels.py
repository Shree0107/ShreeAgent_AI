"""Entry / stop / target calculation (signals/levels.py)."""
import pytest

from signals.levels import (
    MIN_STOP_ATR, STOP_BUFFER_ATR, TARGET_FRONT_RUN_ATR, build_levels,
)

ATR = 0.0080
PRICE = 1.1000


def long_plan(**kw):
    args = dict(
        direction="long", price=PRICE, atr=ATR,
        supports=[1.0970, 1.0850], resistances=[1.1180, 1.1300],
        swing_lows=[(1.0900, "2026-11-10"), (1.0850, "2026-11-01")],
        swing_highs=[(1.0990, "2026-11-11")], high_60d=1.1300, low_60d=1.0800,
        spread=0.0, min_rr=1.5, max_stop_atr=3.0,
    )
    args.update(kw)
    return build_levels(**args)


def test_long_levels_are_ordered_and_structural():
    p = long_plan()
    assert p.direction == "long"
    assert p.stop < p.entry_low <= p.entry_high < p.target1 < p.target2
    # pullback zone leans on the support 0.3 ATR below the price
    assert p.entry_kind == "pullback" and p.entry_anchor == pytest.approx(1.0970)
    assert p.entry_low == pytest.approx(1.0970) and p.entry_high == pytest.approx(PRICE)
    # stop hides below the most recent swing low under the zone, plus the volatility buffer
    assert p.stop_kind == "swing" and p.stop_anchor == pytest.approx(1.0900)
    assert p.stop == pytest.approx(1.0900 - STOP_BUFFER_ATR * ATR, abs=1e-5)
    # target 1 sits just in front of the first resistance, target 2 in front of the next
    assert p.target1 == pytest.approx(1.1180 - TARGET_FRONT_RUN_ATR * ATR, abs=1e-5)
    assert p.target2 == pytest.approx(1.1300 - TARGET_FRONT_RUN_ATR * ATR, abs=1e-5)
    assert p.target1_kind == p.target2_kind == "level"
    assert not p.problems


def test_risk_reward_matches_the_displayed_prices():
    p = long_plan()
    risk = p.entry_mid - p.stop
    assert p.risk == pytest.approx(risk, abs=1e-5)
    assert p.rr1 == pytest.approx(round((p.target1 - p.entry_mid) / risk, 2))
    assert p.rr2 == pytest.approx(round((p.target2 - p.entry_mid) / risk, 2))
    assert p.rr1 >= 1.5


def test_stop_never_closer_than_one_daily_range():
    # A swing low right under the zone would give a tight stop: it gets pushed to 1 x ATR.
    p = long_plan(swing_lows=[(1.0965, "2026-11-12")])
    assert p.stop_kind == "min_distance"
    assert p.entry_mid - p.stop >= MIN_STOP_ATR * ATR - 1e-5


def test_no_recent_swing_uses_volatility_stop():
    p = long_plan(swing_lows=[])
    assert p.stop_kind == "volatility"
    assert p.stop == pytest.approx(p.entry_low - 1.5 * ATR, abs=1e-5)


def test_spread_is_added_to_the_stop():
    a, b = long_plan(), long_plan(spread=0.0001)
    assert b.stop == pytest.approx(a.stop - 0.0001, abs=1e-6)


def test_market_entry_when_no_support_close_by():
    p = long_plan(supports=[1.0850])
    assert p.entry_kind == "market"
    assert p.entry_low == pytest.approx(PRICE - 0.3 * ATR, abs=1e-5)


def test_level_in_the_way_flags_low_reward_and_suggests_better_entry():
    # Resistance only ~1 ATR above: not enough room for 1.5x the risk.
    p = long_plan(resistances=[1.1085, 1.1300], high_60d=None)
    assert p.rr1 < 1.5 and "level_in_way" in p.problems
    e = p.better_entry
    assert e is not None and p.stop < e < p.entry_mid
    assert (p.target1 - e) / (e - p.stop) == pytest.approx(1.5, rel=1e-3)


def test_min_rr_is_configurable():
    loose = long_plan(resistances=[1.1085, 1.1300], high_60d=None, min_rr=0.5)
    assert "level_in_way" not in loose.problems


def test_level_right_in_front_needs_a_breakout():
    p = long_plan(resistances=[1.1020, 1.1300])
    assert "level_too_close" in p.problems
    assert p.breakout_level == pytest.approx(1.1020)


def test_stop_too_wide_is_flagged():
    p = long_plan(swing_lows=[(1.0700, "2026-10-20")], supports=[1.0850])
    assert "stop_too_wide" in p.problems


def test_projected_targets_when_nothing_above():
    p = long_plan(resistances=[], swing_highs=[], high_60d=None)
    assert p.target1_kind == "projected" and p.target2_kind == "projected"
    assert p.target1 > p.entry_high and p.target2 > p.target1
    assert p.rr1 >= 1.5


def test_short_is_exact_mirror_of_long():
    c = PRICE
    m = lambda x: 2 * c - x
    lp = long_plan()
    sp = build_levels(
        "short", c, ATR, supports=[m(1.1180), m(1.1300)], resistances=[m(1.0970), m(1.0850)],
        swing_lows=[(m(1.0990), "2026-11-11")], swing_highs=[(m(1.0900), "2026-11-10"), (m(1.0850), "2026-11-01")],
        high_60d=m(1.0800), low_60d=m(1.1300), min_rr=1.5, max_stop_atr=3.0,
    )
    assert sp.direction == "short"
    assert sp.target2 < sp.target1 < sp.entry_low <= sp.entry_high < sp.stop
    for a, b in ((sp.entry_low, lp.entry_high), (sp.entry_high, lp.entry_low), (sp.stop, lp.stop),
                 (sp.target1, lp.target1), (sp.target2, lp.target2)):
        assert a == pytest.approx(m(b), abs=2e-5)
    assert sp.rr1 == pytest.approx(lp.rr1, abs=0.01) and sp.stop_kind == lp.stop_kind


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        build_levels("sideways", PRICE, ATR, [], [], [], [])
    with pytest.raises(ValueError):
        build_levels("long", PRICE, 0, [], [], [], [])
