"""/api/performance contract: summary, equity, live-vs-backtest and the background run job. Offline."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.routers import performance as perf
from api.routers import plans as plans_router
from intraday import walkforward
from intraday.history import PlanStore
from tests.test_intraday_backtest import _fake_decisions
from tests.intraday_fixtures import five_min


class Svc:
    def __init__(self, store):
        self.store = store


def _live_plan(store, outcome, pips, i):
    t = datetime(2026, 11, 3, 9, tzinfo=timezone.utc) + timedelta(hours=i)
    card = {"symbol": "EUR/USD", "setup": "trend_pullback", "direction": "long", "entry_type": "limit", "entry": 1.1,
            "entry_low": 1.1, "entry_high": 1.1, "stop": 1.099, "target1": 1.102, "target2": 1.104,
            "generated_at": t.isoformat(), "session": "london"}

    class PS:
        ready_at = None
        state = "waiting"

        def as_dict(self):
            return {}
    pid = store.create(card, PS(), 1.0)
    with store._conn() as c:
        c.execute("UPDATE plans SET outcome=?, pips=?, triggered_at=?, closed_at=?, state=? WHERE id=?",
                  (outcome, pips, t.isoformat(), (t + timedelta(minutes=30)).isoformat(), outcome, pid))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    base = tmp_path / "bt"
    store = PlanStore(tmp_path / "plans.sqlite")
    app = create_app(background=False)
    app.dependency_overrides[perf.get_backtest_base] = lambda: base
    app.dependency_overrides[plans_router.get_plan_service] = lambda: Svc(store)
    m5 = five_min(40, vol=0.0003, seed=5)
    monkeypatch.setattr(walkforward, "decisions", lambda sym, fr, cfg, s, e, news, progress=None: _fake_decisions(m5))

    def fake_run(tk, months=None, setups=None, progress=None, out_base=None):
        return walkforward.run_backtest(tk, frames={"5m": m5}, setups=setups or ["trend_pullback"], out_base=out_base,
                                        progress=progress)
    app.dependency_overrides[perf.runner] = lambda: fake_run
    with TestClient(app) as c:
        c.store, c.base = store, base
        yield c


def test_empty_state(client):
    r = client.get("/api/performance/summary").json()
    assert r["has_backtest"] is False and "No backtest yet" in r["empty_text"] and "60 days" in r["empty_text"]
    lv = client.get("/api/performance/live-vs-backtest").json()
    assert lv["overall"]["status"] == "no_backtest" and lv["rows"] == []
    assert client.get("/api/performance/equity").json() == {"backtest": {}, "live": []}
    assert client.get("/api/performance/run?symbol=EUR/USD").json()["job"] is None


def test_run_job_then_summary_equity_and_live_comparison(client):
    j = client.post("/api/performance/run?symbol=EUR/USD&setups=trend_pullback").json()
    assert j["symbol"] == "EUR/USD" and j["status"] in ("queued", "running", "done")
    for _ in range(100):
        st = client.get("/api/performance/run?symbol=EUR/USD").json()
        if st["job"]["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert st["job"]["status"] == "done", st
    assert st["progress"]["stage"] == "done" and st["job"]["result"]["lines"]
    s = client.get("/api/performance/summary?symbol=EUR/USD").json()
    assert s["has_backtest"] and s["runs"][0]["method"] == "single_split"
    assert any(r["session"] == "all" and r["setup"] == "trend_pullback" for r in s["rows"])
    assert s["lines"][0].startswith("Pullback in the trend") and s["disabled"][0]["reason"]
    e = client.get("/api/performance/equity?symbol=EUR/USD").json()
    assert e["backtest"]["EUR/USD"] and e["live"] == []
    for i, (o, p) in enumerate([("tp1_hit", 10), ("sl_hit", -10), ("tp2_hit", 30)]):
        _live_plan(client.store, o, p, i)
    e = client.get("/api/performance/equity?symbol=EUR/USD").json()
    assert [x["pips"] for x in e["live"]] == [10, 0, 30]
    lv = client.get("/api/performance/live-vs-backtest?symbol=EUR/USD").json()
    row = lv["rows"][0]
    assert row["setup"] == "trend_pullback" and row["live"]["trades"] == 3 and row["live"]["wins"] == 2
    assert row["live"]["profit_factor"] == 4.0 and row["band"]["level"] == 0.9
    assert row["status"] in ("inside", "below", "above") and "Live results are" in row["sentence"]
    assert "Only 3 live trades" in row["sentence"]


def test_compare_sentences():
    live = {"trades": 40, "wins": 10, "win_rate": 0.25, "profit_factor": 0.6, "avg_pips": -2.0, "total_pips": -80}
    c = perf.compare(live, 0.55, 200, 2.0)
    assert c["status"] == "below" and c["sentence"].startswith("Live results are below the range")
    c = perf.compare({**live, "wins": 22, "win_rate": 0.55}, 0.55, 200, 2.0)
    assert c["status"] == "inside" and c["band"]["low"] < 0.55 < c["band"]["high"]
    assert perf.compare({**live, "trades": 0}, 0.55, 200, 2.0)["status"] == "no_live"
