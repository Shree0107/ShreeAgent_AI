"""Phase 7 intraday backtest: fills and costs, same-bar rule, gates in the simulation, walk-forward splits,
statistics, shrinkage, the disable rule, the probability JSON round trip, and the look-ahead checks
(truncation invariance, future tampering, completed bars only). Offline, synthetic data."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data.symbols import parse_symbol
from intraday import probability, walkforward
from intraday.backtest import Costs, Decision, Frames, Idea, Params, decisions, simulate
from intraday.bt_news import NewsHistory, nfp_events
from intraday.bt_stats import (Rules, binom_band, binom_sf, max_drawdown, result_files, shrink, stats, verdict,
                               write_files)
from intraday.config import IntradayConfig
from tests.intraday_fixtures import five_min, frames_from

EU = parse_symbol("EUR/USD")
T0 = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)        # Monday 11:00 Berlin: London session
P = Params(3, 1.5)
NOCOST = Costs(0.0, 0.0)


def bars(rows, start=T0 - timedelta(minutes=5), ba_spread: float | None = None) -> pd.DataFrame:
    """rows of (open, high, low, close) as 5M bars; the first one CLOSES at T0 (the decision time)."""
    idx = pd.date_range(start, periods=len(rows), freq="5min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 0.0
    if ba_spread is not None:
        for k in ("open", "high", "low", "close"):
            df[f"bid_{k}"] = df[k] - ba_spread / 2
            df[f"ask_{k}"] = df[k] + ba_spread / 2
    return df


def long_idea(**kw) -> Idea:
    d = dict(setup="trend_pullback", direction="long", entry_type="limit", entry=1.1000, stop=1.0990, tp1=1.1020,
             tp2=1.1040, rr1=2.0, confirmations=4, score=50.0, gates=())
    d.update(kw)
    return Idea(**d)


def dec(t=T0, *ideas, atr=0.0008) -> Decision:
    return Decision(t, list(ideas), atr, 1.0, "london", "trending_up", "BUY", t - timedelta(minutes=5))


FLAT = (1.1010, 1.1012, 1.1008, 1.1010)


# ---------------------------------------------------------------- fills, costs, same-bar rule
def test_limit_buy_fills_on_the_ask_not_the_mid_and_tp1_then_breakeven():
    m5 = bars([FLAT,
               (1.1008, 1.1009, 1.09997, 1.1003),   # mid dips 0.3 pip below the entry, ask (+0.5 pip) doesn't
               (1.1003, 1.1004, 1.09990, 1.1001),   # ask low 1.09995 <= 1.1000: filled at the limit price
               (1.1001, 1.1030, 1.1001, 1.1025),    # bid high 1.10295 >= target 1 (and +1R): half closed, stop to entry
               (1.1025, 1.1026, 1.0999, 1.1000)])   # bid low 1.09985 <= entry: the rest closes at break-even
    tr = simulate(EU, m5, [dec(T0, long_idea())], P, IntradayConfig(), Costs(0.0, 0.2))
    assert len(tr) == 1
    t = tr[0]
    assert t.triggered_at == T0 + timedelta(minutes=10)          # the third bar, not the second
    assert t.fill == pytest.approx(1.1000) and t.tp1_hit and t.outcome == "tp1_hit"
    assert t.exit == pytest.approx(1.1000 - 0.00002)             # break-even stop on the bid, minus slippage
    assert t.pips == pytest.approx(0.5 * 20 + 0.5 * -0.2, abs=1e-6)
    assert t.minutes_to_tp1 == 5 and t.spread_pips == pytest.approx(1.0)


def test_same_bar_stop_and_target_counts_as_the_stop_and_costs_are_charged():
    rows = [FLAT, (1.1003, 1.1004, 1.0999, 1.1001), (1.1001, 1.1040, 1.0980, 1.1000)]
    tr = simulate(EU, bars(rows), [dec(T0, long_idea())], P, IntradayConfig(), Costs(0.0, 0.2))
    assert [t.outcome for t in tr] == ["sl_hit"]
    assert tr[0].exit == pytest.approx(1.0990 - 0.00002) and tr[0].pips == pytest.approx(-10.2, abs=1e-6)
    assert tr[0].r == pytest.approx(-1.02, abs=1e-3)
    with_comm = simulate(EU, bars(rows), [dec(T0, long_idea())], P, IntradayConfig(), Costs(0.5, 0.2))
    assert with_comm[0].pips == pytest.approx(-10.7, abs=1e-6)


def test_entry_bar_checks_the_stop_on_the_exit_side():
    # fills (ask low <= entry) and in the same bar the BID touches the stop: counted as a loss at once
    rows = [FLAT, (1.1003, 1.1004, 1.09904, 1.0995)]   # bid low 1.09899 <= 1.0990
    tr = simulate(EU, bars(rows), [dec(T0, long_idea())], P, IntradayConfig(), NOCOST)
    assert [t.outcome for t in tr] == ["sl_hit"]


def test_no_fill_on_the_decision_bar_itself():
    rows = [(1.1010, 1.1012, 1.0995, 1.1010)] + [FLAT] * 6   # only the bar that closes AT the decision dips
    assert simulate(EU, bars(rows), [dec(T0, long_idea())], P, IntradayConfig(), NOCOST) == []


def test_bid_ask_bars_use_their_own_spread():
    rows = [FLAT, (1.1003, 1.1004, 1.09990, 1.1001)] + [FLAT] * 3
    wide = bars(rows, ba_spread=0.0003)                  # 3 pips: ask low 1.10005 never reaches the entry
    assert simulate(EU, wide, [dec(T0, long_idea())], P, IntradayConfig(), NOCOST) == []


def test_sell_stop_entry_gets_slippage_and_stop_exit_on_the_ask():
    idea = long_idea(direction="short", entry_type="stop", entry=1.0990, stop=1.1000, tp1=1.0970, tp2=1.0950,
                     setup="range_breakout")
    rows = [(1.0995, 1.0997, 1.0993, 1.0995), (1.0995, 1.0996, 1.0985, 1.0988), (1.0988, 1.1001, 1.0987, 1.0999)]
    tr = simulate(EU, bars(rows), [dec(T0, idea)], P, IntradayConfig(), Costs(0.0, 0.2))
    assert len(tr) == 1 and tr[0].outcome == "sl_hit"
    assert tr[0].fill == pytest.approx(1.0990 - 0.00002) and tr[0].exit == pytest.approx(1.1000 + 0.00002)
    assert tr[0].pips == pytest.approx(-10.4, abs=1e-6)


def test_daily_loss_limit_stops_new_plans():
    loser = [(1.1003, 1.1004, 1.0999, 1.1001), (1.1001, 1.1002, 1.0985, 1.0990), FLAT]
    rows = [FLAT] + loser * 3                            # three 15-minute blocks, each fills and loses
    ds = [dec(T0 + timedelta(minutes=15 * i), long_idea()) for i in range(3)]
    tr = simulate(EU, bars(rows), ds, P, IntradayConfig(daily_loss_limit=2), NOCOST)
    assert [t.outcome for t in tr] == ["sl_hit", "sl_hit"]


def test_waiting_plan_is_cancelled_when_the_idea_disappears_and_params_filter_ideas():
    rows = [FLAT, FLAT, FLAT, FLAT, (1.1003, 1.1004, 1.0999, 1.1001), (1.1001, 1.1030, 1.1001, 1.1025),
            (1.1025, 1.1026, 1.0999, 1.1000)]
    ds = [dec(T0, long_idea()), dec(T0 + timedelta(minutes=15))]            # next 15M close: no idea any more
    assert simulate(EU, bars(rows), ds, P, IntradayConfig(), NOCOST) == []
    weak = long_idea(confirmations=3, rr1=1.6)
    assert simulate(EU, bars(rows), [dec(T0, weak)], Params(4, 1.5), IntradayConfig(), NOCOST) == []
    assert simulate(EU, bars(rows), [dec(T0, weak)], Params(3, 2.0), IntradayConfig(), NOCOST) == []
    assert len(simulate(EU, bars(rows), [dec(T0, weak)], Params(3, 1.5), IntradayConfig(), NOCOST)) == 1
    gated = long_idea(gates=("news",))
    assert simulate(EU, bars(rows), [dec(T0, gated)], P, IntradayConfig(), NOCOST) == []


# ---------------------------------------------------------------- walk-forward splits
def test_walk_forward_windows_roll_by_the_test_length():
    s = datetime(2024, 1, 1, tzinfo=timezone.utc)
    method, ws = walkforward.splits(s, datetime(2026, 1, 1, tzinfo=timezone.utc), 12, 3)
    assert method == "walk_forward" and len(ws) == 4
    assert ws[0].train_start == s and ws[0].test_start == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert ws[0].test_end == ws[1].test_start == datetime(2025, 4, 1, tzinfo=timezone.utc)
    assert ws[-1].test_end == datetime(2026, 1, 1, tzinfo=timezone.utc)
    for a, b in zip(ws, ws[1:]):                       # test periods never overlap, training is always before
        assert a.test_end <= b.test_start and b.train_end <= b.test_start
    method, ws = walkforward.splits(s, s + timedelta(days=55), 12, 3)
    assert method == "single_split" and len(ws) == 1 and ws[0].train_end == ws[0].test_start
    assert (ws[0].test_end - ws[0].test_start).days == 22
    method, ws = walkforward.splits(s, s + timedelta(days=5), 12, 3)
    assert method == "in_sample"


# ---------------------------------------------------------------- statistics, shrinkage, disable rule
def _t(pips, tp1, hour=9, mins=30.0, setup="trend_pullback", session="london", market="trending_up", direction="long",
       day=0):
    trig = datetime(2026, 1, 5, hour, 0, tzinfo=timezone.utc) + timedelta(days=day)
    return {"pips": pips, "tp1_hit": tp1, "r": pips / 10, "minutes_to_tp1": mins if tp1 else None,
            "closed_at": trig + timedelta(hours=1), "triggered_at": trig, "setup": setup, "session": session,
            "market": market, "direction": direction}


def test_stats_numbers():
    ts = [_t(10, True, day=0), _t(-10, False, day=1), _t(10, True, day=2), _t(-10, False, day=3), _t(-10, False, day=4),
          _t(20, True, day=5, mins=90)]
    st = stats(ts, tz="UTC")
    assert st["trades"] == 6 and st["wins"] == 3 and st["win_rate"] == 0.5
    assert st["avg_win_pips"] == pytest.approx(13.33, abs=0.01) and st["avg_loss_pips"] == 10
    assert st["profit_factor"] == pytest.approx(40 / 30, abs=1e-3)
    assert st["max_drawdown_pips"] == 20 and st["expectancy_pips"] == pytest.approx(10 / 6, abs=0.01)
    assert st["median_minutes_to_tp1"] == 30 and st["p75_minutes_to_tp1"] == 60
    assert st["breakeven_win_rate"] == pytest.approx(10 / 23.333, abs=1e-3)
    assert st["best_hours"][0]["hour"] == 9 and st["best_hours"][0]["trades"] == 6
    assert max_drawdown([5, -3, -4, 10, -20]) == 20
    assert stats([])["trades"] == 0


def test_binomial_and_shrinkage():
    assert binom_sf(0, 10, 0.3) == 1.0 and binom_sf(11, 10, 0.3) == 0.0
    assert binom_sf(10, 10, 0.5) == pytest.approx(0.5 ** 10)
    assert binom_sf(6, 10, 0.5) == pytest.approx(386 / 1024)
    lo, hi = binom_band(100, 0.5, 0.90)
    assert 0.40 <= lo <= 0.43 and 0.57 <= hi <= 0.60
    assert shrink(9, 10, 0.5, 20) == pytest.approx(19 / 30)   # 90% on 10 trades pulled toward 50%
    assert shrink(900, 1000, 0.5, 20) == pytest.approx(910 / 1020)


def test_disable_rule_reasons_in_plain_words():
    r = Rules()
    ok, why = verdict({"trades": 12, "profit_factor": 3.0, "p_value": 0.001}, r)
    assert not ok and "12 test trades" in why and "50" in why
    ok, why = verdict({"trades": 80, "profit_factor": 1.05, "p_value": 0.001}, r)
    assert not ok and "profit factor" in why and "1.15" in why
    ok, why = verdict({"trades": 80, "profit_factor": 1.4, "p_value": 0.2, "win_rate": 0.5, "breakeven_win_rate": 0.45}, r)
    assert not ok and "luck" in why
    assert verdict({"trades": 80, "profit_factor": 1.4, "p_value": 0.01}, r) == (True, "")


def test_probability_json_round_trip_with_lookup(tmp_path):
    good = [_t(15, True, day=i) for i in range(45)] + [_t(-10, False, day=i, session="new_york") for i in range(25)]
    files = result_files("EUR/USD", ["trend_pullback", "bos_retest"], good, Rules(),
                         {"period": {"start": "2026-01-01", "end": "2026-03-01"}, "out_of_sample": True,
                          "method": "walk_forward"})
    write_files(files, tmp_path)
    raw = json.loads(probability.result_path("EUR/USD", "trend_pullback", tmp_path).read_text(encoding="utf-8"))
    for k in ("symbol", "setup", "generated_at", "period", "out_of_sample", "enabled", "disabled_reason", "overall",
              "buckets"):
        assert k in raw
    for k in ("n", "win_rate", "profit_factor", "median_minutes_to_tp1", "p25_minutes_to_tp1", "p75_minutes_to_tp1"):
        assert k in raw["overall"]
    assert raw["overall"]["n"] == 70 and raw["enabled"] is True
    assert "session=london|market=trending_up" in raw["buckets"]
    lon = probability.lookup("trend_pullback", "EUR/USD", {"session": "london", "market": "trending_up",
                                                          "direction": "long"}, base=tmp_path)
    assert lon["bucket"] == "session=london|market=trending_up|direction=long" and lon["n"] == 45
    assert 45 / 70 < lon["win_rate"] < 1.0                      # shrunk toward the setup average (45/70)
    ny = probability.lookup("trend_pullback", "EUR/USD", {"session": "new_york"}, base=tmp_path)
    assert ny["bucket"] == "overall"                            # 25 trades < MIN_N -> overall
    assert probability.setup_enabled("trend_pullback", "EUR/USD", base=tmp_path)
    assert not probability.setup_enabled("bos_retest", "EUR/USD", base=tmp_path)
    assert "0 test trades" in probability.disabled_reason("bos_retest", "EUR/USD", base=tmp_path)
    with probability.ignore_results():
        assert probability.lookup("trend_pullback", "EUR/USD", {}, base=tmp_path) is None
        assert probability.setup_enabled("bos_retest", "EUR/USD", base=tmp_path)


def test_news_history_rule_and_window():
    ev = nfp_events(datetime(2026, 5, 1).date(), datetime(2026, 6, 30).date())
    assert [e.time.isoformat() for e in ev] == ["2026-05-01T12:30:00+00:00", "2026-06-05T12:30:00+00:00"]
    assert all(e.major for e in ev)
    nh = NewsHistory(ev)
    assert nh.events(datetime(2026, 6, 4, 12, tzinfo=timezone.utc)) == [ev[1]]
    assert nh.events(datetime(2026, 5, 20, tzinfo=timezone.utc)) == []


# ---------------------------------------------------------------- run_backtest wiring (engine replaced by a fake)
def _fake_decisions(m5):
    out = []
    for t in (m5.index + pd.Timedelta(minutes=5)):
        if t.minute == 0 and t.hour in (9, 13) and t.weekday() < 5:
            px = float(m5["close"].asof(t - pd.Timedelta(minutes=5)))
            out.append(Decision(t.to_pydatetime(), [long_idea(entry=px - 0.0002, stop=px - 0.0012, tp1=px + 0.0003,
                                                              tp2=px + 0.0013)],
                                0.0008, 1.0, "london" if t.hour == 9 else "overlap", "trending_up", "BUY"))
    return out


def test_run_backtest_writes_files_and_run_summary(tmp_path, monkeypatch):
    m5 = five_min(40, vol=0.0003, seed=5)
    monkeypatch.setattr(walkforward, "decisions", lambda sym, fr, cfg, s, e, news, progress=None: _fake_decisions(m5))
    calls = []
    r = walkforward.run_backtest("EUR/USD", frames={"5m": m5}, out_base=tmp_path, setups=["trend_pullback"],
                                 progress=lambda *a: calls.append(a[0]))
    assert r["method"] == "single_split" and r["out_of_sample"] and len(r["windows"]) == 1
    assert r["windows"][0]["chosen"] and r["windows"][0]["tried"]
    assert r["overall"]["trades"] > 0 and r["lines"][0].startswith("Pullback in the trend reached target 1 in")
    assert {row["session"] for row in r["rows"]} >= {"all"}
    assert r["equity"] and r["equity"][-1]["pips"] == pytest.approx(sum(t["pips"] for t in r["trades"]), abs=0.05)
    assert any("60 days" in n for n in r["notes"])
    assert all(datetime.fromisoformat(t["created_at"]) >= datetime.fromisoformat(r["windows"][0]["test_start"])
               for t in r["trades"])                                      # only out-of-sample trades reported
    f = json.loads(probability.result_path("EUR/USD", "trend_pullback", tmp_path).read_text(encoding="utf-8"))
    assert f["method"] == "single_split" and f["enabled"] is False and f["disabled_reason"]
    assert walkforward.load_run("EUR/USD", tmp_path)["symbol"] == "EUR/USD"
    assert "done" in calls and "simulate" in calls


# ---------------------------------------------------------------- look-ahead checks (the real engine)
CUT = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
W0, W1 = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc), datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def engine_run():
    m5 = five_min(30, drift=0.00002, seed=3)
    fr = Frames(frames_from(m5))
    cfg = IntradayConfig()
    decs = decisions(EU, fr, cfg, W0, W1)
    return m5, fr, cfg, decs


def _cut(m5, t):
    """All timeframes rebuilt from 5M bars that had closed by t (what a live feed would have had at t)."""
    return frames_from(m5[m5.index + pd.Timedelta(minutes=5) <= pd.Timestamp(t)])


def _key(d: Decision):
    return (d.t, d.skipped, d.action, [(i.setup, i.direction, round(i.entry, 8), round(i.stop, 8), round(i.tp1, 8),
                                        i.confirmations, i.gates) for i in d.ideas])


def test_completed_bars_only(engine_run):
    _, _, _, decs = engine_run
    built = [d for d in decs if not d.skipped]
    assert len(built) > 10
    assert all(d.used_until is not None and d.used_until <= d.t for d in built)


def test_truncation_invariance(engine_run):
    m5, fr, cfg, decs = engine_run
    cut = Frames(_cut(m5, CUT))
    decs_cut = decisions(EU, cut, cfg, W0, CUT)
    assert [_key(d) for d in decs_cut] == [_key(d) for d in decs if d.t <= CUT]
    full = simulate(EU, fr.frames["5m"], decs, P, cfg, Costs(), W0, W1)
    trunc = simulate(EU, cut.frames["5m"], decs_cut, P, cfg, Costs(), W0, CUT)
    before = [t.as_dict() for t in full if t.closed_at <= CUT]
    assert before, "the fixture should produce trades before the cut"
    assert [t.as_dict() for t in trunc if t.closed_at <= CUT] == before


def test_future_tampering_does_not_change_earlier_decisions(engine_run):
    m5, _, cfg, decs = engine_run
    bad = m5.copy()
    later = bad.index >= pd.Timestamp(CUT)
    for k in ("open", "high", "low", "close"):
        bad.loc[later, k] = bad.loc[later, k] * 1.02           # a 2% jump right after the cut
    tampered = decisions(EU, Frames(frames_from(bad)), cfg, W0, CUT)
    assert [_key(d) for d in tampered] == [_key(d) for d in decs if d.t <= CUT]
