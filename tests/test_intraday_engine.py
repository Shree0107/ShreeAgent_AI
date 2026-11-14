"""Intraday engine: multi-timeframe rule, sideways detection, entry/stop/targets, gates (news, session, spread),
completed-bars-only context and the jargon-free main view."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from data.providers.calendar import CalendarEvent
from data.symbols import parse_symbol
from intraday import probability
from intraday.bias import TFBias, market_state, mtf
from intraday.config import IntradayConfig
from intraday.context import Spread, build_context, completed
from intraday.explain import has_jargon, main_view_texts
from intraday.levels import Level
from intraday.plan import build_card, targets
from intraday.setups import Candidate, _breakouts, trend_pullback
from tests.intraday_fixtures import five_min, frames_from

EU = parse_symbol("EUR/USD")
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)      # Wednesday, London session
CFG = IntradayConfig()


def b(tf, direction, score=None):
    s = score if score is not None else {"up": 70, "down": -70, "neutral": 0}[direction]
    return TFBias(tf, direction, s, 0, 0, 0.0)


def biases(d, h4, h1, m15="neutral"):
    return {"1d": b("1d", d), "4h": b("4h", h4), "1h": b("1h", h1), "15m": b("15m", m15)}


# ---------------------------------------------------------------- multi-timeframe rule
def test_mtf_needs_big_picture_and_1h_to_agree():
    m = mtf(biases("up", "up", "up"))
    assert m.allows("long") and not m.allows("short") and m.conflict is None
    m = mtf(biases("up", "neutral", "up"))
    assert m.allows("long")                                   # 4H neutral doesn't oppose
    m = mtf(biases("up", "down", "up"))
    assert not m.allows("long") and "daily chart is rising but the 4-hour chart is falling" in m.conflict
    m = mtf(biases("down", "down", "up"))
    assert not m.allows("long") and not m.allows("short") and "need to agree" in m.conflict
    m = mtf(biases("up", "up", "neutral"))
    assert not m.allows("long") and "1-hour chart has no clear direction" in m.conflict
    strong = biases("neutral", "neutral", "up")
    strong["1h"] = b("1h", "up", 80)
    assert mtf(strong).allows("long")                         # very strong 1H trend with a neutral big picture
    weak = biases("neutral", "neutral", "up")
    weak["1h"] = b("1h", "up", 40)
    assert not mtf(weak).allows("long")


# ---------------------------------------------------------------- sideways detection
def _df_from_close(close):
    import pandas as pd

    idx = pd.date_range("2026-11-02", periods=len(close), freq="15min", tz="UTC")
    o = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, close) + 0.0002, "low": np.minimum(o, close) - 0.0002,
                         "close": close, "volume": 0.0}, index=idx)


def test_sideways_and_trending_labels():
    t = np.arange(300)
    flat = 1.10 + 0.0008 * np.sin(t / 3.0)
    st = market_state(_df_from_close(flat))
    assert st["state"] == "sideways" and st["range"]["low"] < 1.0995 and st["range"]["high"] > 1.1005
    up = 1.10 + 0.0004 * t + 0.0002 * np.sin(t)
    st = market_state(_df_from_close(up), direction="up")
    assert st["state"] == "trending_up" and st["range"] is None
    st = market_state(_df_from_close(1.10 - 0.0004 * t + 0.0002 * np.sin(t)), direction="down")
    assert st["state"] == "trending_down"
    assert market_state(_df_from_close(up[:10]))["state"] == "sideways"       # too little data: no trend claimed


# ---------------------------------------------------------------- context: completed bars only
def test_context_drops_unfinished_bars_and_future():
    fr = frames_from(five_min(n_days=10))
    ctx = build_context(EU, fr, NOW - timedelta(minutes=7), CFG)
    last5 = ctx.df("5m").index[-1]
    assert last5 + timedelta(minutes=5) <= NOW - timedelta(minutes=7)
    assert ctx.df("15m").index[-1] + timedelta(minutes=15) <= NOW - timedelta(minutes=7)
    assert ctx.df("1h").index[-1] + timedelta(hours=1) <= NOW - timedelta(minutes=7)
    assert len(completed(None, "15m", NOW)) == 0


def test_card_ignores_future_bars():
    """Truncation invariance: data after `now` must not change the card."""
    m5 = five_min(drift=0.00002, end=NOW + timedelta(hours=6))
    full = frames_from(m5)
    cut = frames_from(m5[m5.index + timedelta(minutes=5) <= NOW])
    a = build_card(build_context(EU, full, NOW, CFG))
    c = build_card(build_context(EU, cut, NOW, CFG))
    for k in ("action", "setup", "entry", "stop", "target1", "target2", "market"):
        assert a[k] == c[k], k


# ---------------------------------------------------------------- entry / stop / targets
def _ctx(levels=None, spread=None):
    fr = frames_from(five_min(n_days=20, drift=0.0))
    ctx = build_context(EU, fr, NOW, CFG, spread or Spread(1.0, False))
    if levels is not None:
        ctx.cache()["levels"] = levels
    return ctx


def test_targets_from_risk_multiples_when_no_levels():
    ctx = _ctx(levels=[])
    c = Candidate("trend_pullback", "long", "limit", 1.1000, 1.0995, 1.1000, 1.0980, "", "pullback")
    tp1, tp2, ob = targets(ctx, c, 1.5)
    assert tp1 == pytest.approx(1.1030) and tp2 == pytest.approx(1.1050) and ob is None
    s = Candidate("trend_pullback", "short", "limit", 1.1000, 1.1000, 1.1005, 1.1020, "", "pullback")
    tp1, tp2, _ = targets(ctx, s, 1.5)
    assert tp1 == pytest.approx(1.0970) and tp2 == pytest.approx(1.0950)


def test_targets_snap_to_levels_and_detect_obstacles():
    lv = [Level(1.1040, "zone_1h", "a price area", 1.0, 1.1038, 1.1042), Level(1.1075, "pdh", "yesterday's high", 2.0)]
    ctx = _ctx(levels=lv)
    c = Candidate("trend_pullback", "long", "limit", 1.1000, 1.0995, 1.1000, 1.0980, "", "pullback")
    tp1, tp2, ob = targets(ctx, c, 1.5)
    assert 1.1035 < tp1 < 1.1040 and 1.1070 < tp2 < 1.1075 and ob is None     # just before each level
    ctx = _ctx(levels=[Level(1.1015, "pdh", "yesterday's high", 2.0)])
    tp1, _, ob = targets(ctx, c, 1.5)
    assert ob["label"] == "yesterday's high" and tp1 < 1.1015                  # strong level in the way


def test_breakout_entry_and_stop_geometry():
    ctx = _ctx(levels=[])
    atr, sp = ctx.atr15, ctx.spread_price
    price = ctx.last
    lo, hi = price - 1.0 * atr, price + 1.0 * atr
    long, short = _breakouts(ctx, "range_breakout", lo, hi, "the sideways range", {})
    assert long.entry_type == "stop" and long.entry == pytest.approx(hi + 0.1 * atr + sp)
    assert long.stop < long.entry and long.stop >= lo - 0.1 * atr - sp - 1e-12
    assert short.entry == pytest.approx(lo - 0.1 * atr - sp) and short.stop > short.entry
    assert long.risk >= 0.5 * atr - 1e-12                                    # minimum stop distance
    assert _breakouts(ctx, "range_breakout", price + 2 * atr, price + 4 * atr, "x", {}) == []   # already outside


def test_trend_pullback_limit_below_price_with_stop_below_zone():
    ctx = _ctx()
    atr, price = ctx.atr15, ctx.last
    ctx.cache()["biases"] = biases("up", "up", "up", "up")
    ctx.cache()["levels"] = [Level(price - 1.0 * atr, "pdl", "yesterday's low", 2.0)]
    [c] = trend_pullback(ctx)
    assert c.direction == "long" and c.entry_type == "limit"
    assert c.entry_low < c.entry <= c.entry_high < price
    assert c.stop < c.entry_low and c.level_label == "yesterday's low" and "yesterday's low" in c.stop_reason


# ---------------------------------------------------------------- full card + gates
@pytest.fixture(scope="module")
def trend_frames():
    return frames_from(five_min(drift=0.00004))


def test_card_contract_and_buy_in_uptrend(trend_frames):
    c = build_card(build_context(EU, trend_frames, NOW, CFG, Spread(1.0, False)))
    for k in ("symbol", "action", "state", "setup", "direction", "entry", "entry_low", "entry_high", "entry_type", "stop",
              "target1", "target2", "generated_at", "expires_at", "market", "range", "scenarios", "probability", "size",
              "explanation", "details", "stale"):
        assert k in c, k
    assert c["action"] == "BUY" and c["direction"] == "long" and c["entry_type"] in ("limit", "stop")
    assert c["stop"] < c["entry"] < c["target1"] < c["target2"]
    assert (c["target1"] - c["entry"]) / (c["entry"] - c["stop"]) >= CFG.min_rr - 1e-9
    assert len(c["details"]["confirmations"]) >= CFG.min_confirmations
    ex = c["explanation"]
    assert "pips" in ex["stop_text"] and ex["time_stop_text"].startswith("Close the trade by 21:30")
    assert ex["probability_text"] == "No backtest yet – treat as unproven"
    assert ex["disclaimer"] == "Analysis only, not financial advice. Always use a stop loss."
    assert not has_jargon(main_view_texts(c))


def test_news_blackout_blocks_new_signals(trend_frames):
    ev = CalendarEvent(NOW + timedelta(minutes=20), "USD", "CPI m/m", "high")
    c = build_card(build_context(EU, trend_frames, NOW, CFG, Spread(1.0, False), events=[ev]))
    assert c["action"] == "WAIT"
    assert "news" in [g["code"] for g in c["details"]["gates"]]
    assert "CPI" in c["explanation"]["news_warning"] and "No new trades" in c["explanation"]["news_warning"]
    # outside the window: only a warning
    ev2 = CalendarEvent(NOW + timedelta(hours=2), "USD", "CPI m/m", "high")
    c2 = build_card(build_context(EU, trend_frames, NOW, CFG, Spread(1.0, False), events=[ev2]))
    assert c2["action"] == "BUY" and "CPI" in c2["explanation"]["news_warning"]
    # low-impact or other-currency news never blocks
    ev3 = CalendarEvent(NOW + timedelta(minutes=5), "JPY", "BoJ thing", "high")
    assert build_card(build_context(EU, trend_frames, NOW, CFG, Spread(1.0, False), events=[ev3]))["action"] == "BUY"


@pytest.mark.parametrize("kw,code", [
    ({"spread": Spread(3.5, True)}, "spread"),
    ({"now": NOW.replace(hour=17, minute=15)}, "after_cutoff"),
])
def test_gates_spread_and_cutoff(trend_frames, kw, code):
    now = kw.pop("now", NOW)
    c = build_card(build_context(EU, trend_frames, now, CFG, kw.get("spread", Spread(1.0, False))))
    assert c["action"] == "WAIT" and code in [g["code"] for g in c["details"]["gates"]]


def test_daily_loss_limit_and_disabled_setup(trend_frames, tmp_path, monkeypatch):
    c = build_card(build_context(EU, trend_frames, NOW, CFG, Spread(1.0, False)), losses_today=2)
    assert c["action"] == "WAIT" and "daily_loss_limit" in [g["code"] for g in c["details"]["gates"]]
    ok = build_card(build_context(EU, trend_frames, NOW, CFG, Spread(1.0, False)))
    cfg = IntradayConfig(setups_enabled=tuple(s for s in CFG.setups_enabled if s != ok["setup"]))
    c2 = build_card(build_context(EU, trend_frames, NOW, cfg, Spread(1.0, False)))
    assert c2["setup"] != ok["setup"] or c2["action"] == "WAIT"


def test_stale_data_and_weekend(trend_frames):
    c = build_card(build_context(EU, trend_frames, NOW + timedelta(hours=2), CFG))
    assert c["action"] == "WAIT" and "stale_data" in [g["code"] for g in c["details"]["gates"]]
    sat = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
    fr = frames_from(five_min(end=datetime(2026, 11, 13, 22, 0, tzinfo=timezone.utc)))
    c = build_card(build_context(EU, fr, sat, CFG))
    assert c["action"] == "WAIT" and c["state"] == "market_closed" and c["market_open"] is False
    assert c["explanation"]["headline"].startswith("Market closed – ") and "it opens again Sun 23:00" in c["explanation"]["headline"]
    assert "stale_data" not in [g["code"] for g in c["details"]["gates"]]


def test_wait_card_shows_range_and_both_scenarios():
    t = np.arange(40 * 288)
    path = 1.10 + 0.0012 * np.sin(t / 40.0)
    fr = frames_from(five_min(path=path))
    c = build_card(build_context(EU, fr, NOW, CFG, Spread(1.0, False)), losses_today=5)   # forces WAIT
    assert c["action"] == "WAIT" and c["direction"] is None and c["entry"] is None
    assert c["market"] == "sideways" and c["explanation"]["headline"].startswith("WAIT – stuck between")
    assert c["range"] and c["range"]["low"] < c["range"]["high"]
    texts = [s["text"] for s in c["scenarios"]]
    assert any(t.startswith("Buy if it breaks above") for t in texts)
    assert any(t.startswith("Sell if it breaks below") for t in texts)
    assert sum(s["likely_pct"] for s in c["scenarios"]) == 100
    assert not has_jargon(main_view_texts(c))


# ---------------------------------------------------------------- probability hook
def test_probability_lookup_and_setup_switch(tmp_path):
    import json

    assert probability.lookup("trend_pullback", "EUR/USD", {}, base=tmp_path) is None
    assert probability.setup_enabled("trend_pullback", "EUR/USD", base=tmp_path)
    p = probability.result_path("EUR/USD", "trend_pullback", tmp_path)
    p.write_text(json.dumps({"enabled": False, "disabled_reason": "profit factor below 1.15",
                             "overall": {"n": 120, "win_rate": 0.52, "p25_minutes_to_tp1": 30, "p75_minutes_to_tp1": 150},
                             "buckets": {"session=london": {"n": 40, "win_rate": 0.6},
                                         "session=asian": {"n": 5, "win_rate": 0.9}}}), encoding="utf-8")
    assert probability.lookup("trend_pullback", "EUR/USD", {"session": "london"}, base=tmp_path)["win_rate"] == 0.6
    r = probability.lookup("trend_pullback", "EUR/USD", {"session": "asian"}, base=tmp_path)
    assert r["win_rate"] == 0.52 and r["bucket"] == "overall"                 # too few samples: overall
    assert not probability.setup_enabled("trend_pullback", "EUR/USD", base=tmp_path)
