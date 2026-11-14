"""Trade-plan alerts: formatting, per-type switches, de-duplication, Telegram sender."""
import asyncio

from alerts.dispatcher import AlertDispatcher, format_alert
from alerts.telegram import TelegramNotifier
from api.bus import MemoryBus


class RecBus:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, data):
        self.msgs.append((topic, data))
        return 1


class RecSender:
    name = "rec"

    def __init__(self):
        self.texts = []

    def send(self, text):
        self.texts.append(text)
        return True


EV = {"type": "entry_triggered", "symbol": "EUR/USD", "setup": "squeeze_breakout", "plan_id": "p1",
      "message": "Price broke above 1.0952 – the BUY plan is now active", "entry": 1.0952, "stop": 1.0931,
      "target1": 1.0983, "target2": 1.1004}


def test_format_plain_words_with_prices():
    title, body = format_alert(EV)
    assert title == "🚀 Entry triggered: EUR/USD"
    assert "Stop loss: 1.0931" in body and "Target 2: 1.1004" in body


def test_dispatch_dedupe_and_disabled_types(monkeypatch):
    monkeypatch.setenv("ALERT_EVENTS", "get_ready,entry_triggered,tp_hit,sl_hit,cancelled")
    from config.settings import get_settings

    get_settings.cache_clear()
    try:
        bus, snd = RecBus(), RecSender()
        now = {"t": 1000.0}
        d = AlertDispatcher(bus, senders=[snd], clock=lambda: now["t"])
        assert d.handle(EV) is True
        assert d.handle(EV) is False                       # same plan + type again: duplicate
        now["t"] += 3600
        assert d.handle(EV) is True                        # long after: allowed again
        assert d.handle({**EV, "type": "tp2_hit"}) is True  # tp1/tp2 count as tp_hit
        assert d.handle({**EV, "type": "expired"}) is False  # not in the enabled list
        assert [t for t, _ in bus.msgs] == ["alert"] * 3
        assert all("not financial advice" in x for x in snd.texts)
    finally:
        get_settings.cache_clear()


def test_one_broken_channel_does_not_stop_others():
    class Broken:
        name = "broken"

        def send(self, text):
            raise RuntimeError("down")

    good = RecSender()
    d = AlertDispatcher(RecBus(), senders=[Broken(), good])
    assert d.handle({**EV, "plan_id": "p2"}) and len(good.texts) == 1


def test_runs_on_the_bus():
    async def go():
        bus = MemoryBus()
        snd = RecSender()
        d = AlertDispatcher(bus, senders=[snd])
        alerts = bus.subscribe({"alert"})
        d.start()
        await asyncio.sleep(0)
        bus.publish("plan_event", {**EV, "plan_id": "p3"})
        msg = await asyncio.wait_for(alerts.get(), 2)
        d.stop()
        return msg

    msg = asyncio.run(go())
    assert msg["topic"] == "alert" and msg["data"]["symbol"] == "EUR/USD"


def test_telegram_sender_posts_and_splits_long_messages():
    calls = []

    class R:
        status_code, text = 200, "ok"

    class Http:
        def post(self, url, json, timeout):
            calls.append((url, json))
            return R()

    t = TelegramNotifier(token="T0K", chat_id="42", session=Http())
    assert t.send("x" * 5000)
    assert len(calls) == 2 and calls[0][0].endswith("/botT0K/sendMessage") and calls[0][1]["chat_id"] == "42"
    assert not TelegramNotifier(token="", chat_id="", session=Http()).send("hi")


def test_api_lifespan_turns_plan_events_into_alerts(monkeypatch):
    """With background=True the API starts the dispatcher: a plan_event on the bus becomes an `alert`."""
    import api.main as main
    from api.bus import get_bus
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "warm_up", lambda: None)
    monkeypatch.setattr(main, "start_live", lambda bus: None)
    monkeypatch.setattr("alerts.telegram.TelegramNotifier.configured", property(lambda self: False))
    with TestClient(main.create_app(background=True)) as c:
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["topic"] == "hello"
            ws.send_json({"op": "subscribe", "topics": ["alert"]})
            ws.receive_json()  # subscription acknowledged
            get_bus().publish("plan_event", {**EV, "plan_id": "lifespan-test"})
            for _ in range(5):
                msg = ws.receive_json()
                if msg.get("topic") == "alert":
                    break
    assert msg["topic"] == "alert" and msg["data"]["title"].startswith("🚀 Entry triggered")
