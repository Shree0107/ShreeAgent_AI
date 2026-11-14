"""API layer (FastAPI): offline, with the FakeData provider and temp storage."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.bus import MemoryBus
from api.main import create_app
from api.serialize import candles, clean
from data.watchlist import Watchlist
from signals.history import SignalHistory
from tests.conftest import FakeData, make_ohlcv


class QuietData(FakeData):
    def upcoming_events(self, currencies, days=14):
        return []


@pytest.fixture
def client(tmp_path):
    app = create_app(background=False)
    wl_path = tmp_path / "wl.yaml"
    wl_path.write_text("symbols:\n  - EUR/USD\n", encoding="utf-8")
    hist = SignalHistory(tmp_path / "s.sqlite")
    app.dependency_overrides[deps.get_data] = lambda: QuietData(drift=0.002)
    app.dependency_overrides[deps.get_history] = lambda: hist
    app.dependency_overrides[deps.get_watchlist] = lambda: Watchlist(wl_path)
    with TestClient(app) as c:
        yield c


def wait_job(client, job_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise AssertionError("job timed out")


def test_clean_makes_strict_json():
    import numpy as np

    out = clean({"a": float("nan"), "b": np.float64(1.5), "c": [np.int64(2), np.inf], 3: True})
    assert out == {"a": None, "b": 1.5, "c": [2, None], "3": True}


def test_candles_paging():
    df = make_ohlcv(50)
    bars = candles(df, limit=10)
    assert len(bars) == 10 and bars[-1]["time"] == int(df.index[-1].timestamp())
    older = candles(df, limit=5, before=bars[0]["time"])
    assert older[-1]["time"] < bars[0]["time"] and len(older) == 5


def test_health_and_settings(client):
    assert client.get("/api/health").json()["ok"]
    s = client.get("/api/settings").json()
    assert s["account"]["currency"] == "EUR" and "configured" in s
    assert "anthropic_api_key" not in str(s)   # secrets never leave the server


def test_candles_endpoint(client):
    r = client.get("/api/candles", params={"symbol": "EUR/USD", "tf": "1h", "limit": 100})
    assert r.status_code == 200
    j = r.json()
    assert len(j["candles"]) == 100 and j["has_more"] is True
    assert set(j["candles"][0]) == {"time", "open", "high", "low", "close", "volume"}
    r2 = client.get("/api/candles", params={"symbol": "EUR/USD", "tf": "1h", "limit": 50, "before": j["candles"][0]["time"]})
    assert r2.json()["candles"][-1]["time"] < j["candles"][0]["time"]
    assert client.get("/api/candles", params={"symbol": "EUR/USD", "tf": "3m"}).status_code == 400


def test_quote_technical_fundamentals_news(client):
    assert client.get("/api/quote", params={"symbol": "EUR/USD"}).json()["symbol"] == "EUR/USD"
    t = client.get("/api/technical", params={"symbol": "EUR/USD"}).json()
    assert t["bias"] in ("bullish", "bearish", "neutral")
    f = client.get("/api/fundamentals", params={"symbol": "AAPL"}).json()
    assert f["kind"] == "stock" and f["bias"] == "bullish"
    n = client.get("/api/news", params={"symbol": "AAPL"}).json()
    assert n["n_articles"] == 2


def test_watchlist_crud(client):
    assert client.get("/api/watchlist").json() == ["EUR/USD"]
    assert client.post("/api/watchlist", json={"symbol": "gbpusd"}).json() == ["EUR/USD", "GBP/USD"]
    assert client.request("DELETE", "/api/watchlist", params={"symbol": "GBP/USD"}).json() == ["EUR/USD"]


def test_signals_first_call_pending_then_refresh_job(client):
    j = client.get("/api/signals").json()
    assert j["cards"][0]["action"] == "PENDING" and j["refresh_job"]
    done = wait_job(client, j["refresh_job"]["id"])
    assert done["status"] == "done", done.get("error")
    j2 = client.get("/api/signals", params={"account": 10000, "risk": 1, "ccy": "EUR"}).json()
    card = j2["cards"][0]
    assert card["action"] in ("BUY", "SELL", "WAIT") and card["stale"] is False and j2["refresh_job"] is None
    if card["action"] in ("BUY", "SELL"):
        assert card["size"]["actual_risk"] <= 100


def test_forecast_job(client):
    job = client.post("/api/forecast", params={"symbol": "EUR/USD", "tf": "1d", "horizon": 5}).json()
    done = wait_job(client, job["id"])
    assert done["status"] == "done", done.get("error")
    assert len(done["result"]["median"]) == 5 and 0 <= done["result"]["prob_up"] <= 1
    # same request while running/done -> a new job only after the previous finished
    assert client.get("/api/jobs/doesnotexist").status_code == 404


def test_report_markdown(client):
    r = client.get("/api/report", params={"symbol": "AAPL", "horizon": 5, "forecast": False})
    assert r.status_code == 200 and r.text.startswith("# AAPL")


def test_websocket_subscribe_and_receive(client):
    from api.bus import get_bus

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["topic"] == "hello"
        ws.send_json({"op": "subscribe", "topics": ["price:*"]})
        assert "price:*" in ws.receive_json()["data"]
        get_bus().publish("price:EUR/USD", {"bid": 1.1})
        get_bus().publish("candle:EUR/USD:1h", {"x": 1})       # not subscribed
        msg = ws.receive_json()
        assert msg == {"topic": "price:EUR/USD", "data": {"bid": 1.1}}
        ws.send_json({"op": "ping"})
        assert ws.receive_json()["topic"] == "pong"


def test_memory_bus_patterns_and_threads():
    async def run():
        bus = MemoryBus()
        q = bus.subscribe({"plan:EUR/USD", "price:*"})
        import threading

        t = threading.Thread(target=lambda: bus.publish("price:GBP/USD", 1))
        t.start()
        t.join()
        assert bus.publish("plan:EUR/USD", 2) == 1
        assert bus.publish("plan:GBP/USD", 3) == 0
        got = [await asyncio.wait_for(q.get(), 1), await asyncio.wait_for(q.get(), 1)]
        assert [m["data"] for m in got] == [1, 2]

    asyncio.run(run())


def test_websocket_sends_status_snapshot_on_connect(client):
    from data.stream.live import LiveService, set_live
    from api.bus import get_bus

    svc = LiveService(get_bus(), data=QuietData())
    svc.ensure("EUR/USD")
    set_live(svc)
    try:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["topic"] == "hello"
            snap = ws.receive_json()
            assert snap["topic"] == "status" and "EUR/USD" in snap["data"]["symbols"]
    finally:
        set_live(None)
