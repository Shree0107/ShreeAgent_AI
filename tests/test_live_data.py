"""Live data: candle aggregation, OANDA parsing/reconnect, polling, staleness and the live service."""
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from data.providers.oanda import OandaProvider, candles_to_frame, instrument
from data.stream.aggregator import CandleAggregator, bucket_start
from data.stream.live import LiveService, candles_from_minutes
from data.stream.market_hours import forex_open, market_open
from data.stream.oanda_stream import OandaPriceStream, Price, parse_line
from data.symbols import parse_symbol
from tests.conftest import FakeData

T0 = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc).timestamp()   # Wednesday 10:00 UTC


class RecBus:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, data):
        self.msgs.append((topic, data))
        return 1

    def topics(self, prefix=""):
        return [t for t, _ in self.msgs if t.startswith(prefix)]


# ---------------- aggregator ----------------
def test_bucket_alignment():
    assert bucket_start(T0 + 14 * 60 + 59, "15m") == T0
    assert bucket_start(T0 + 15 * 60, "15m") == T0 + 900
    assert bucket_start(T0, "4h") == T0 - 2 * 3600                        # 10:00 is in the 08:00 candle
    assert bucket_start(T0 + 3600 * 3, "4h") == T0 + 2 * 3600             # 13:00 is in the 12:00 candle
    wk = bucket_start(T0, "1wk")
    assert datetime.fromtimestamp(wk, timezone.utc).strftime("%a %H:%M") == "Mon 00:00"


def test_ticks_build_candles_and_close_on_new_bucket():
    a = CandleAggregator(("1m", "15m"))
    for i, p in enumerate([1.1000, 1.1010, 1.0990, 1.1005]):
        a.on_tick(T0 + i * 10, p)
    m = a.current("1m")
    assert (m["open"], m["high"], m["low"], m["close"], m["volume"]) == (1.1, 1.101, 1.099, 1.1005, 4)
    ev = a.on_tick(T0 + 61, 1.1020)     # next minute: the 1m candle closes, 15m keeps going
    closed = [e for e in ev if e[0] == "closed"]
    assert [(k, tf) for k, tf, _ in closed] == [("closed", "1m")]
    assert closed[0][2]["close"] == 1.1005
    assert a.current("15m")["high"] == 1.102 and a.current("15m")["volume"] == 5


def test_seeded_candle_keeps_provider_open_and_ignores_old_ticks():
    a = CandleAggregator(("15m",))
    a.seed("15m", {"time": T0, "open": 1.09, "high": 1.12, "low": 1.08, "close": 1.10, "volume": 50})
    a.on_tick(T0 + 300, 1.105)
    c = a.current("15m")
    assert (c["open"], c["high"], c["low"], c["close"], c["volume"]) == (1.09, 1.12, 1.08, 1.105, 51)
    assert a.on_tick(T0 - 3600, 1.2) == []          # out-of-order tick from before a reconnect
    assert a.current("15m")["close"] == 1.105


def test_quiet_market_closes_candle_on_time():
    a = CandleAggregator(("1m", "15m"))
    a.on_tick(T0 + 5, 1.1)
    assert a.close_due(T0 + 30) == []
    closed = a.close_due(T0 + 60)
    assert [tf for _, tf, _ in closed] == ["1m"] and a.current("1m") is None and a.current("15m")


# ---------------- OANDA ----------------
def test_oanda_candles_and_instrument_names():
    assert instrument(parse_symbol("EUR/USD")) == "EUR_USD"
    df = candles_to_frame([
        {"complete": True, "volume": 120, "time": "2026-11-13T22:00:00.000000000Z",
         "mid": {"o": "1.10200", "h": "1.10300", "l": "1.10100", "c": "1.10250"},
         "bid": {"o": "1.10195", "h": "1.10295", "l": "1.10095", "c": "1.10245"},
         "ask": {"o": "1.10205", "h": "1.10305", "l": "1.10105", "c": "1.10255"}},
        {"complete": False, "volume": 7, "time": "2026-11-13T22:15:00.000000000Z",
         "bid": {"o": "1.1024", "h": "1.1026", "l": "1.1023", "c": "1.1025"},
         "ask": {"o": "1.1026", "h": "1.1028", "l": "1.1025", "c": "1.1027"}},
    ])
    assert list(df.index.strftime("%H:%M")) == ["22:00", "22:15"] and str(df.index.tz) == "UTC"
    assert df.close.iloc[0] == 1.1025 and df.volume.iloc[0] == 120
    assert df.ask_close.iloc[0] - df.bid_close.iloc[0] == pytest.approx(0.0001)
    assert df.close.iloc[1] == pytest.approx(1.1026)          # mid derived from bid/ask


def test_oanda_provider_only_for_fx_and_needs_token():
    p = OandaProvider(token="", environment="practice")
    assert p.supports(parse_symbol("EUR/USD")) and not p.supports(parse_symbol("AAPL"))
    assert not p.configured
    assert OandaProvider(token="x", environment="live").stream_host == "https://stream-fxtrade.oanda.com"


def test_parse_stream_lines():
    line = json.dumps({"type": "PRICE", "instrument": "EUR_USD", "time": "2026-11-13T10:00:00.123456789Z",
                       "bids": [{"price": "1.10275"}], "asks": [{"price": "1.10283"}], "tradeable": True})
    p = parse_line(line)
    assert isinstance(p, Price) and p.symbol == "EUR/USD" and p.mid == pytest.approx(1.10279)
    assert parse_line('{"type":"HEARTBEAT","time":"2026-11-13T10:00:05Z"}') == "heartbeat"
    assert parse_line("not json") is None and parse_line("") is None


def test_stream_reconnects_after_drops():
    prices, statuses, sleeps = [], [], []
    calls = {"n": 0}
    good = json.dumps({"type": "PRICE", "instrument": "EUR_USD", "time": "2026-11-13T10:00:00Z",
                       "bids": [{"price": "1.1"}], "asks": [{"price": "1.1002"}]})

    def open_lines(instruments):
        calls["n"] += 1
        assert instruments == ["EUR_USD"]
        if calls["n"] <= 2:
            raise ConnectionError("network down")
        yield good
        stream.stop()
        yield good

    stream = OandaPriceStream(OandaProvider(token="t"), ["EUR/USD"], prices.append,
                              lambda s, d: statuses.append(s), open_lines=open_lines, sleep=sleeps.append)
    stream.run()
    assert calls["n"] == 3 and len(prices) == 1
    assert statuses[:3] == ["connecting", "reconnecting", "reconnecting"] and "live" in statuses
    assert len(sleeps) == 2 and sleeps[1] >= sleeps[0] * 0.5          # backoff applied between retries
    assert stream.attempt == 0                                        # reset after a good connection


# ---------------- market hours ----------------
def test_market_hours():
    assert forex_open(datetime(2026, 11, 11, 12, tzinfo=timezone.utc))
    assert not forex_open(datetime(2026, 11, 14, 12, tzinfo=timezone.utc))      # Saturday
    assert forex_open(datetime(2026, 11, 15, 23, tzinfo=timezone.utc))          # Sunday evening NY
    assert market_open("US", False, datetime(2026, 11, 11, 15, tzinfo=timezone.utc))   # 10:00 New York
    assert not market_open("US", False, datetime(2026, 11, 11, 22, tzinfo=timezone.utc))
    assert market_open("XETRA", False) is None


# ---------------- live service ----------------
class FakeOanda:
    configured = True

    def supports(self, s):
        return s.is_fx


def test_live_service_streams_fx_and_publishes():
    bus = RecBus()
    svc = LiveService(bus, data=FakeData(), oanda=FakeOanda(), clock=lambda: T0 + 30)
    svc.ensure("EUR/USD")
    svc.on_price("EUR/USD", T0 + 10, 1.1000, 1.1002)
    st = svc.states["EUR/USD"]
    assert st.status == "live" and st.spread_pips == pytest.approx(2.0) and st.mid == pytest.approx(1.1001)
    assert "price:EUR/USD" in bus.topics() and "candle:EUR/USD:15m" in bus.topics()
    svc.on_price("EUR/USD", T0 + 70, 1.1003, 1.1005)       # new minute -> 1m candle closes
    assert ("candle_closed", "1m") in [(t, d.get("tf")) for t, d in bus.msgs if t == "candle_closed"]


def test_staleness_closed_market_and_resync():
    bus = RecBus()
    now = {"t": T0 + 10}
    svc = LiveService(bus, data=FakeData(), oanda=FakeOanda(), clock=lambda: now["t"])
    svc.ensure("EUR/USD")
    svc.on_price("EUR/USD", T0 + 10, 1.1, 1.1002)
    now["t"] = T0 + 200                                   # 190 s without a price while the market is open
    svc.check_staleness()
    assert svc.states["EUR/USD"].status == "stale"
    svc.on_feed_status("oanda", "reconnecting")
    svc.on_feed_status("oanda", "live")                   # back: clients must reload missed candles
    assert "resync:EUR/USD" in bus.topics()
    now["t"] = datetime(2026, 11, 14, 12, tzinfo=timezone.utc).timestamp()   # Saturday
    svc.check_staleness()
    assert svc.states["EUR/USD"].status == "closed"


def test_polling_path_for_stocks_is_delayed():
    bus = RecBus()
    svc = LiveService(bus, data=FakeData(), oanda=FakeOanda())
    svc.ensure("AAPL")
    svc.poll_once()
    st = svc.states["AAPL"]
    assert st.status == "delayed" and st.source == "yfinance" and st.bid is None
    assert "price:AAPL" in bus.topics() and "candle:AAPL:1h" in bus.topics()


def test_candles_from_minutes():
    m1 = FakeData().get_ohlcv(parse_symbol("AAPL"), "1m")
    bar = candles_from_minutes(m1, "15m")
    last = m1.index[-1]
    part = m1[m1.index >= pd.Timestamp(bar["time"], unit="s", tz="UTC")]
    assert part.index[0] <= last and bar["close"] == m1.close.iloc[-1] and bar["high"] == part.high.max()
