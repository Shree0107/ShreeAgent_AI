"""Forecast tab (phase 9): baselines, plain text, accuracy scoring, staleness, agreement and the API. Offline."""
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import deps
from api.main import create_app
from api.routers import forecast_tab
from data.symbols import parse_symbol
from forecasting import explain, live
from forecasting.accuracy import ForecastStore, actual_after, score_forecast, summarize
from forecasting.backtest import BacktestResult, load_result, run_backtest
from forecasting.baselines import baseline_paths, drift_path, moving_average_path, naive_path
from forecasting.models import NaiveForecaster
from tests.conftest import FakeData, make_ohlcv

EURUSD = parse_symbol("EUR/USD")


# ---------- baselines ----------
def test_baselines():
    y = np.arange(1.0, 101.0)  # rises by 1 per candle
    assert np.all(naive_path(y, 3) == 100)
    assert np.allclose(drift_path(y, 3), [101, 102, 103])
    assert np.allclose(moving_average_path(y, 2, window=20), [90.5, 90.5])
    paths = baseline_paths(y, 5)
    assert set(paths) == {"naive", "drift", "moving_average"} and all(len(p) == 5 for p in paths.values())
    assert drift_path([5.0], 2).tolist() == [5.0, 5.0]  # one point: flat


def test_backtest_reports_baselines_and_bands():
    df = make_ohlcv(400, drift=0.003, seed=3)
    r = run_backtest(df, NaiveForecaster(), horizon=5, n_windows=20, context_length=256)
    assert set(r.baselines) == {"naive", "drift", "moving_average"}
    assert r.baselines["naive"]["mae"] == pytest.approx(r.naive_mae)
    assert r.mae == pytest.approx(r.naive_mae)  # the naive model *is* the naive baseline
    assert 0 <= r.coverage_50 <= r.coverage_80 <= 100
    assert r.variates == ["close"]
    # strong steady trend: drift beats "no change"
    assert r.baselines["drift"]["mae"] < r.baselines["naive"]["mae"]
    assert r.baselines["drift"]["directional_accuracy"] >= 70


def test_old_backtest_json_still_loads(tmp_path, monkeypatch):
    from forecasting import backtest as B

    monkeypatch.setattr(B, "_path", lambda *a: tmp_path / "old.json")
    (tmp_path / "old.json").write_text(
        '{"symbol":"X","timeframe":"1d","horizon":5,"model":"naive","n_windows":20,"mae":1,"mape":1,'
        '"directional_accuracy":50,"coverage_80":80,"naive_mae":1,"naive_mape":1,"skill_vs_naive":0,'
        '"trust":"low","run_at":"2026-01-01"}', encoding="utf-8")
    r = load_result("X", "1d", 5)
    assert isinstance(r, BacktestResult) and r.baselines is None


# ---------- plain text ----------
def test_horizon_text():
    assert explain.horizon_text("15m", 16) == "4 hours"
    assert explain.horizon_text("1h", 24) == "24 hours"
    assert explain.horizon_text("4h", 30) == "5 trading days"
    assert explain.horizon_text("1d", 10) == "10 trading days"
    assert explain.horizon_text("15m", 2) == "30 minutes"


def test_direction_words():
    assert explain.direction(1.0, 1.0, 0.99, 1.01, 0.5)[0] == "flat"
    assert explain.direction(1.0, 1.002, 0.99, 1.01, 0.6) == ("up", "slightly upward")
    assert explain.direction(1.0, 1.004, 0.99, 1.01, 0.7) == ("up", "upward")
    assert explain.direction(1.0, 0.99, 0.98, 1.0, 0.1) == ("down", "clearly downward")
    assert explain.direction(1.0, 1.004, 0.99, 1.01, 0.52)[0] == "flat"  # ~coin flip: no real opinion


def test_summary_sentence():
    s = explain.summary_sentence("EUR/USD", "15m", 16, 1.0930, 1.0938, 1.0890, 1.0910, 1.0960, 1.0985, 0.58,
                                 lambda x: f"{x:.4f}")
    assert s.startswith("The model expects EUR/USD to be between 1.0910 and 1.0960 in the next 4 hours, slightly upward.")
    assert "1.0890 to 1.0985" in s and "58% chance" in s and "(1.0930)" in s


def _bt(mae, naive, drift=None, ma=None, n=20, dir_acc=55.0):
    return {"mae": mae, "naive_mae": naive, "n_windows": n, "directional_accuracy": dir_acc,
            "baselines": {"naive": {"mae": naive}, "drift": {"mae": drift or naive * 1.2},
                          "moving_average": {"mae": ma or naive * 1.3}}}


def test_verdict():
    assert explain.verdict(None, "EUR/USD", "1h")["status"] == "unknown"
    assert explain.verdict(_bt(1, 1, n=5), "EUR/USD", "1h")["status"] == "unknown"
    better = explain.verdict(_bt(0.8, 1.0), "EUR/USD", "1h")
    assert better["status"] == "better" and "20% smaller" in better["text"]
    same = explain.verdict(_bt(1.01, 1.0), "EUR/USD", "1h")
    assert same["status"] == "same" and "rough guide" in same["text"]
    worse = explain.verdict(_bt(1.2, 1.0), "EUR/USD", "1h")
    assert worse["status"] == "worse"
    assert worse["text"].startswith("On EUR/USD 1-hour forecasts the model has not done better than simply assuming")
    # beaten by drift even though better than naive -> not "better"
    assert explain.verdict(_bt(0.9, 1.0, drift=0.7), "EUR/USD", "1h")["status"] == "worse"


def test_variates_text():
    assert "own prices" in explain.variates_text(None, ["close"])
    assert "did not make" in explain.variates_text({"multi_tested": True}, ["close"])
    assert "GBP/USD" in explain.variates_text({"multi_tested": True}, ["close", "GBP/USD"])


# ---------- agreement ----------
@pytest.mark.parametrize("fc,plan,status,phrase", [
    ("up", {"action": "BUY"}, "agree", "The forecast agrees with the BUY plan."),
    ("down", {"action": "SELL"}, "agree", "agrees with the SELL plan"),
    ("down", {"action": "BUY"}, "disagree", "The forecast points down while the plan says BUY – be careful."),
    ("up", {"action": "SELL"}, "disagree", "points up while the plan says SELL"),
    ("flat", {"action": "BUY"}, "neutral", "neither supports nor contradicts"),
    ("up", {"action": "WAIT", "direction": "long"}, "neutral", "a possible buy is forming"),
    ("up", None, "none", "No trade plan"),
    ("up", {"action": "PENDING"}, "none", "No trade plan"),
    (None, {"action": "BUY"}, "none", "No forecast"),
])
def test_agreement(fc, plan, status, phrase):
    r = explain.agreement(fc, plan)
    assert r["status"] == status and phrase in r["text"]


# ---------- accuracy scoring ----------
def _rec(last=1.0, median=(1.01, 1.02), q_lo=0.01, q_mid=0.005):
    med = np.array(median)
    # 9 quantiles: q10 = med - q_lo, q20/q30 = med - q_mid, ..., q90 = med + q_lo
    q = np.column_stack([med - q_lo, med - q_mid, med - q_mid, med, med, med, med + q_mid, med + q_mid, med + q_lo])
    return {"last_close": last, "median": list(med), "quantiles": q.tolist(), "horizon": len(med)}


def test_score_forecast_inside_bands():
    s = score_forecast(_rec(), [1.012, 1.021])
    assert s["dir_correct"] is True
    assert s["mae"] == pytest.approx((0.002 + 0.001) / 2)
    assert s["naive_mae"] == pytest.approx((0.012 + 0.021) / 2)
    assert s["in50"] == 1.0 and s["in80"] == 1.0 and s["end_in50"] and s["end_in80"]


def test_score_forecast_band_coverage_and_wrong_direction():
    # step 1 inside 80% only (|err| 0.008), step 2 outside both and below the start
    s = score_forecast(_rec(), [1.018, 0.99])
    assert s["dir_correct"] is False
    assert s["in50"] == 0.0 and s["in80"] == 0.5 and not s["end_in80"]
    flat = score_forecast(_rec(), [1.0, 1.0])
    assert flat["dir_correct"] is None  # no move: neither right nor wrong


def test_actual_after_needs_all_candles():
    df = make_ohlcv(10, freq="h")
    t = df.index[5].isoformat()
    assert actual_after(df, t, 4) == list(df.close.iloc[6:10])
    assert actual_after(df, t, 5) is None


def test_store_scores_pending_and_summarizes(tmp_path):
    store = ForecastStore(tmp_path / "f.sqlite")
    df = make_ohlcv(50, freq="h")
    for i in (30, 40, 47):  # the last one can't be scored yet (needs 3 candles after it)
        store.save({"symbol": "EUR/USD", "tf": "1h", "horizon": 3, "made_at": "x", "last_close": float(df.close.iloc[i]),
                    "last_bar_time": df.index[i].isoformat(), "dates": [], "median": [float(df.close.iloc[i])] * 3,
                    "quantiles": [[float(df.close.iloc[i]) + d for d in np.linspace(-1, 1, 9)]] * 3,
                    "model": "naive", "variates": ["close"], "baselines": {}, "prob_up": 0.5})
    assert store.score_pending("EUR/USD", "1h", df) == 2
    assert len(store.pending("EUR/USD", "1h")) == 1
    rows = store.recent_scored("EUR/USD", "1h", 3)
    assert len(rows) == 2 and rows[0]["last_bar_time"] > rows[1]["last_bar_time"]
    st = summarize(rows, pip=None)
    assert st["n"] == 2 and st["units"] == "%" and st["mae"] == pytest.approx(st["naive_mae"])
    assert st["direction_n"] == 0  # flat (naive) forecasts have no direction to score
    # same candle saved again replaces the forecast instead of duplicating it
    rec = store.latest("EUR/USD", "1h", 3)
    store.save({**rec, "id": None, "model": "timesfm-3", "scored_at": None})
    assert store.latest("EUR/USD", "1h", 3)["model"] == "timesfm-3"
    assert len(store._query("WHERE 1=1", ())) == 3


def test_summarize_pips_and_text():
    rows = [{"scored_at": "x", "last_close": 1.1, "dir_correct": d, "mae": 0.0010, "naive_mae": 0.0012,
             "in50": 0.5, "in80": 0.75} for d in (True, True, False, None)]
    st = summarize(rows, pip=0.0001)
    assert st == {"n": 4, "units": "pips", "direction_n": 3, "direction_hits": 2, "direction_pct": 66.7,
                  "mae": 10.0, "naive_mae": 12.0, "in50_pct": 50.0, "in80_pct": 75.0}
    t = explain.accuracy_text(st, "EUR/USD", "1h")
    assert "right 2 of 3 times" in t and "10 pips" in t and "small sample" in t
    assert "no live track record" in explain.accuracy_text({"n": 0}, "EUR/USD", "1h")


# ---------- staleness / scheduling ----------
def test_completed_drops_forming_candle():
    df = make_ohlcv(5, freq="h")  # 2022-01-03 00:00..04:00
    assert len(live.completed(df, "1h", pd.Timestamp("2022-01-03 04:30", tz="UTC"))) == 4
    assert len(live.completed(df, "1h", pd.Timestamp("2022-01-03 05:00", tz="UTC"))) == 5


def test_is_stale_and_due():
    e = {"last_bar_time": "2026-11-13T10:00:00+00:00"}  # candle 10:00-11:00 used; next closes at 12:00
    t = lambda s: pd.Timestamp(f"2026-11-13 {s}", tz="UTC")
    assert live.is_stale(None, t("11:00"), "1h")
    assert not live.is_stale(e, t("11:59"), "1h")
    assert live.is_stale(e, t("12:00"), "1h")
    assert not live.is_due(e, t("11:30"), "1h", None)
    assert live.is_due(e, t("12:00"), "1h", None)
    assert live.is_due(e, t("12:00:05"), "1h", t("11:30").timestamp())  # last check was before the close
    # checked after the close but the provider had no new candle yet: wait retry_seconds before trying again
    assert not live.is_due(e, t("12:01"), "1h", t("12:00:10").timestamp())
    assert live.is_due(e, t("12:20"), "1h", t("12:00:10").timestamp())
    assert live.retry_seconds("15m") == 225 and live.retry_seconds("1d") == 900
    # no forecast yet: run, but not again within a minute of a failed attempt
    assert live.is_due(None, t("12:00"), "1h", None)
    assert not live.is_due(None, t("12:00:30"), "1h", t("12:00").timestamp())


def test_refresh_forecast_job_end_to_end(tmp_path):
    store = ForecastStore(tmp_path / "f.sqlite")
    sym = parse_symbol("GBP/USD")
    out = live.refresh_forecast(sym, "4h", data=FakeData(), forecaster=NaiveForecaster(), store=store)
    assert out["new_forecast"]
    rec = store.latest("GBP/USD", "4h", 30)
    assert len(rec["median"]) == 30 and len(rec["quantiles"]) == 30 and len(rec["quantiles"][0]) == 9
    assert set(rec["baselines"]) == {"naive", "drift", "moving_average"} and rec["variates"] == ["close"]
    check = live.load_check("GBP/USD", "4h", 30)
    assert check and check["chosen"]["baselines"] and check["multi_tested"] is False
    # same candles again: no duplicate forecast
    again = live.refresh_forecast(sym, "4h", data=FakeData(), forecaster=NaiveForecaster(), store=store)
    assert not again["new_forecast"]


class RelatedData(FakeData):
    def get_ohlcv_ticker(self, ticker, timeframe="1d"):
        if ticker == "USD/JPY":
            raise RuntimeError("provider down")  # dropped gracefully
        return make_ohlcv(400, seed=7, freq={"1h": "h", "1d": "D"}.get(timeframe, "h"), volume=False)


def test_related_series_dropped_when_unavailable_and_check_compares():
    frames = live.related_frames(EURUSD, "1h", RelatedData())
    assert set(frames) == {"GBP/USD", "USD/CHF"}
    df = RelatedData().get_ohlcv(EURUSD, "1h")
    check = live.run_check(EURUSD, "1h", 24, df, frames, NaiveForecaster())
    assert check["multi_tested"] and check["multivariate"]["variates"] == ["close", "GBP/USD", "USD/CHF"]
    assert check["use_multi"]  # naive ignores extras: equal error, so they "don't hurt"


def test_scheduler_submits_only_when_due(tmp_path):
    class Jobs:
        def __init__(self):
            self.n = 0

        def submit(self, kind, key, fn):
            self.n += 1
            fn()
            return type("J", (), {"status": "done", "public": lambda s, with_result=True: {}})()

        def latest(self, key):
            return None

    clock = [pd.Timestamp("2026-11-14 12:00", tz="UTC").timestamp()]
    jobs = Jobs()
    s = live.ForecastScheduler(jobs, store=ForecastStore(tmp_path / "f.sqlite"), clock=lambda: clock[0],
                               data_factory=FakeData)
    s.watch("EUR/USD", "1d")
    s.tick()  # FakeData's candles are from 2022: forecast made (stale data, retried later)
    assert jobs.n == 1
    s.tick()
    assert jobs.n == 1  # just checked: wait retry_seconds
    clock[0] += 901
    s.tick()
    assert jobs.n == 2
    clock[0] += 3 * 3600  # not viewed for 2 hours: stop refreshing
    s.tick()
    assert jobs.n == 2 and not s.watched


# ---------- API ----------
@pytest.fixture
def client(tmp_path):
    app = create_app(background=False)
    store = ForecastStore(tmp_path / "fc.sqlite")
    app.dependency_overrides[deps.get_data] = lambda: FakeData(drift=0.001)
    app.dependency_overrides[forecast_tab.get_forecast_store] = lambda: store
    with TestClient(app) as c:
        c.store = store
        yield c


def _wait(client, job_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise AssertionError("job timed out")


def test_live_endpoint_returns_immediately_then_cached(client):
    r = client.get("/api/forecast/live", params={"symbol": "EUR/USD", "tf": "1h"}).json()
    assert r["horizon"] == 24 and r["horizon_text"] == "24 hours"
    assert r["refresh_job"]
    j = _wait(client, r["refresh_job"]["id"])
    assert j["status"] == "done", j
    r = client.get("/api/forecast/live", params={"symbol": "EUR/USD", "tf": "1h"}).json()
    f = r["forecast"]
    assert f and len(f["median"]) == len(f["q10"]) == len(f["q25"]) == len(f["q75"]) == len(f["q90"]) == 24
    assert f["summary"].startswith("The model expects EUR/USD to be between ")
    assert "in the next 24 hours" in f["summary"]
    assert r["stale"] is True  # FakeData's candles are years old: never shown as current
    assert r["next_update_at"] and r["age_s"] is not None
    assert r["check"]["status"] in ("same", "worse", "better") and len(r["check"]["table"]) == 4
    assert r["check"]["units"] == "pips" and r["variates_text"]
    assert r["check"]["table"][1]["direction_pct"] is None  # "no change" has no direction


def test_live_endpoint_rejects_bad_timeframe(client):
    assert client.get("/api/forecast/live", params={"symbol": "EUR/USD", "tf": "1m"}).status_code == 400


def test_accuracy_endpoint(client):
    df = FakeData().get_ohlcv(EURUSD, "1h")
    i = len(df) - 30
    last = float(df.close.iloc[i])
    client.store.save({"symbol": "EUR/USD", "tf": "1h", "horizon": 24, "made_at": "2022-01-01T00:00:00+00:00",
                       "last_close": last, "last_bar_time": df.index[i].isoformat(), "dates": [],
                       "median": [last * 1.001] * 24, "quantiles": [[last * (1 + d) for d in np.linspace(-0.01, 0.01, 9)]] * 24,
                       "model": "naive", "variates": ["close"], "baselines": {}, "prob_up": 0.6})
    client.store.score_pending("EUR/USD", "1h", df)
    r = client.get("/api/forecast/accuracy", params={"symbol": "EUR/USD", "tf": "1h"}).json()
    assert r["stats"]["n"] == 1 and r["units"] == "pips" and len(r["recent"]) == 1
    row = r["recent"][0]
    assert row["predicted_dir"] == "up" and row["actual_end"] == pytest.approx(float(df.close.iloc[i + 24]))
    assert "Of the last 1 finished forecasts" in r["text"]


def test_agreement_endpoint_uses_plans_when_available(client):
    r = client.get("/api/forecast/agreement", params={"symbol": "EUR/USD", "tf": "1h"}).json()
    assert r["status"] == "none"  # no forecast yet
    df = FakeData().get_ohlcv(EURUSD, "1h")
    last = float(df.close.iloc[-1])
    client.store.save({"symbol": "EUR/USD", "tf": "1h", "horizon": 24, "made_at": "2022-01-01T00:00:00+00:00",
                       "last_close": last, "last_bar_time": df.index[-1].isoformat(), "dates": [],
                       "median": [last * 0.995] * 24,
                       "quantiles": [[last * (0.995 + d) for d in np.linspace(-0.006, 0.006, 9)]] * 24,
                       "model": "naive", "variates": ["close"], "baselines": {}, "prob_up": 0.2})

    @client.app.get("/api/plans")
    def plans(symbols: str):
        return {"cards": [{"symbol": "EUR/USD", "action": "BUY", "direction": "long", "entry": 1.1, "stop": 1.09}]}

    r = client.get("/api/forecast/agreement", params={"symbol": "EUR/USD", "tf": "1h"}).json()
    assert r["status"] == "disagree" and r["plan"]["source"] == "intraday"
    assert r["text"] == "The forecast points down while the plan says BUY – be careful."
