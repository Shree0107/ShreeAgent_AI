"""PlanService (store, state tracking, bus events) and the /api/plans contract. Offline: synthetic aligned data."""
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.main import create_app
from api.routers import plans as plans_router
from data.symbols import parse_symbol
from data.watchlist import Watchlist
from intraday.config import IntradayConfig
from intraday.history import PlanStore
from intraday.scheduler import next_run_after
from intraday.service import PlanService, is_stale
from tests.intraday_fixtures import FrameData, five_min, frames_from

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


class Bus:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, data):
        self.msgs.append((topic, data))
        return 1


@pytest.fixture(scope="module")
def frames():
    return frames_from(five_min(drift=0.00004))


def make_service(tmp_path, frames, clock=NOW):
    return PlanService(data=FrameData(frames), store=PlanStore(tmp_path / "p.sqlite"), cfg=IntradayConfig(),
                       events_fn=lambda s, n: [], live_fn=lambda: None, bus=Bus(), clock=lambda: clock)


def test_refresh_creates_plan_and_tracks_it_to_entry(tmp_path, frames):
    svc = make_service(tmp_path, frames)
    svc_sym = parse_symbol("EUR/USD")
    card = svc.refresh_one(svc_sym)
    assert card["action"] == "BUY" and card["plan_id"] and card["state"] in ("waiting", "ready")
    assert ("plan:EUR/USD" in [t for t, _ in svc.bus.msgs])
    row = svc.store.open_plan("EUR/USD")
    assert row["setup_type"] == card["setup"] and row["entry"] == card["entry"] and row["session"] == "london"
    # same analysis again -> same plan kept, not duplicated
    again = svc.refresh_one(svc_sym)
    assert again["plan_id"] == card["plan_id"] and len(svc.store.history("EUR/USD")) == 1
    # live price reaches the entry -> entry_triggered event on the bus and in the store
    svc.bus.msgs.clear()
    evs = svc.on_price("EUR/USD", NOW + timedelta(minutes=1), card["entry"] - (1e-5 if card["entry_type"] == "limit" else -1e-5))
    assert "entry_triggered" in [e.kind for e in evs]
    events = [d for t, d in svc.bus.msgs if t == "plan_event"]
    assert events and events[-1]["kind"] in ("entry_triggered", "get_ready") and "message" in events[-1]
    assert svc.store.latest("EUR/USD")["state"] == "triggered"
    # then the stop -> sl_hit, outcome stored with pips and R
    svc.on_price("EUR/USD", NOW + timedelta(minutes=2), card["entry"])
    svc.on_price("EUR/USD", NOW + timedelta(minutes=3), card["stop"] - 1e-5)
    h = svc.store.history("EUR/USD")[0]
    assert h["outcome"] == "sl_hit" and h["r_multiple"] < -0.9 and h["pips"] < 0 and h["closed_at"]
    assert svc.store.losses_today(NOW + timedelta(minutes=5)) == 1
    kinds = [e["kind"] for e in svc.store.events("EUR/USD")]
    assert "sl_hit" in kinds and "entry_triggered" in kinds


def test_wait_cancels_pending_plan(tmp_path, frames):
    from data.providers.calendar import CalendarEvent

    svc = make_service(tmp_path, frames)
    sym = parse_symbol("EUR/USD")
    first = svc.refresh_one(sym)
    assert first["action"] == "BUY"
    svc.events_fn = lambda s, n: [CalendarEvent(NOW + timedelta(minutes=10), "USD", "Non-Farm Employment Change", "high")]
    second = svc.refresh_one(sym)
    assert second["action"] == "WAIT"
    assert svc.store.history("EUR/USD")[0]["outcome"] == "cancelled"
    ev = [d for t, d in svc.bus.msgs if t == "plan_event" and d["kind"] == "cancelled"]
    assert ev and "Non-Farm" in ev[-1]["message"]


def test_catch_up_from_bars_without_live_feed(tmp_path):
    m5 = five_min(drift=0.00004, end=NOW + timedelta(hours=3))
    svc = make_service(tmp_path, frames_from(m5))
    card = svc.refresh_one(parse_symbol("EUR/USD"))
    assert card["action"] == "BUY"
    svc.clock = lambda: NOW + timedelta(hours=3)
    svc.catch_up(parse_symbol("EUR/USD"), m5, NOW + timedelta(hours=3))
    row = svc.store.history("EUR/USD")[0]
    assert row["state"] != "waiting" or row["outcome"] in ("expired", "cancelled")


def test_staleness_and_scheduler_timing():
    assert is_stale({"generated_at": (NOW - timedelta(minutes=20)).isoformat()}, NOW)
    assert not is_stale({"generated_at": (NOW - timedelta(minutes=5)).isoformat()}, NOW)
    assert is_stale(None, NOW)
    t = NOW.timestamp()                        # exactly on a 15M close
    assert next_run_after(t, 20) == t + 20
    assert next_run_after(t + 21, 20) == t + 900 + 20


# ---------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path, frames):
    app = create_app(background=False)
    wl = tmp_path / "wl.yaml"
    wl.write_text("symbols:\n  - EUR/USD\n", encoding="utf-8")
    svc = make_service(tmp_path, frames)
    app.dependency_overrides[plans_router.get_plan_service] = lambda: svc
    app.dependency_overrides[deps.get_watchlist] = lambda: Watchlist(wl)
    with TestClient(app) as c:
        c.svc = svc
        yield c


def wait_job(client, jid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise AssertionError("job timed out")


CARD_KEYS = {"symbol", "action", "state", "setup", "direction", "entry", "entry_low", "entry_high", "entry_type", "stop",
             "target1", "target2", "generated_at", "expires_at", "market", "range", "scenarios", "probability", "size",
             "explanation", "details", "stale"}


def test_plans_contract(client):
    r = client.get("/api/plans").json()          # nothing stored yet: placeholder at once + background job
    assert r["cards"][0]["state"] == "pending" and r["cards"][0]["action"] == "WAIT" and r["refresh_job"]
    assert CARD_KEYS <= set(r["cards"][0])
    assert wait_job(client, r["refresh_job"]["id"])["status"] == "done"
    r = client.get("/api/plans", params={"symbols": "EUR/USD", "account": 2000, "risk": 1, "ccy": "EUR"}).json()
    c = r["cards"][0]
    assert CARD_KEYS <= set(c) and "generated_at" in r and r["refresh_job"] is None
    assert c["action"] in ("BUY", "SELL", "WAIT") and c["market"] in ("trending_up", "trending_down", "sideways")
    assert c["stale"] is False
    if c["action"] in ("BUY", "SELL"):
        assert c["direction"] in ("long", "short") and c["entry_type"] in ("limit", "stop")
        assert c["size"]["lots"] is not None and c["size"]["currency"] == "EUR"
        assert c["explanation"]["stop_money"].startswith("−€")
    h = client.get("/api/plans/history", params={"symbol": "EUR/USD"}).json()
    assert "plans" in h and "stats" in h
    assert "events" in client.get("/api/plans/events").json()
    job = client.post("/api/plans/refresh").json()
    assert wait_job(client, job["id"])["status"] == "done"
