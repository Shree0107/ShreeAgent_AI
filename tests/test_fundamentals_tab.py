"""Fundamentals tab (phase 8): meaning rules, calendar view + filters, FRED actuals, central-bank estimate,
currency strength, news-summary number guard, bias text, and the /api/fund endpoints. Offline."""
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analysis.fundtab.bias import fundamental_bias, stock_facts
from analysis.fundtab.calendar_view import calendar_view, fred_actual, window
from analysis.fundtab.central_banks import central_banks, expectation
from analysis.fundtab.meaning import classify, meaning, parse_number, plain_title, surprise
from analysis.fundtab.news_view import guard_summaries, summarise, summary_ok
from analysis.fundtab.strength import PAIRS, combine, currency_strength, pair_change
from api import deps
from api.main import create_app
from api.routers import fundamentals_tab as ft
from data.providers.calendar import CalendarEvent, parse_ff
from data.symbols import Symbol
from tests.conftest import FakeData

EURUSD = Symbol("EUR/USD", "forex", "FX")
USDJPY = Symbol("USD/JPY", "forex", "FX")
AAPL = Symbol("AAPL", "stock", "US")
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)  # Tuesday
FEED = [
    {"title": "CPI m/m", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High",
     "forecast": "0.3%", "previous": "0.4%"},
    {"title": "German ZEW Economic Sentiment", "country": "EUR", "date": "2026-11-10T05:00:00-05:00",
     "impact": "Medium", "forecast": "40.1", "previous": "39.3"},
    {"title": "Bank Holiday", "country": "All", "date": "2026-11-11T00:00:00-05:00", "impact": "Holiday"},
    {"title": "RBA Assist Gov Hunter Speaks", "country": "AUD", "date": "2026-11-08T17:30:00-05:00", "impact": "Low"},
    {"title": "BOJ Gov Ueda Speaks", "country": "JPY", "date": "2026-11-10T02:00:00-05:00", "impact": "Low"},
    {"title": "Federal Funds Rate", "country": "USD", "date": "2026-11-13T14:00:00-05:00", "impact": "High",
     "forecast": "3.75%", "previous": "4.00%"},
]


def ff():
    return parse_ff(FEED)


# ---------------- meaning rules ----------------
def test_classify_event_types():
    assert classify("CPI m/m").type == "inflation"
    assert classify("Core CPI m/m").type == "core_inflation"
    assert classify("Unemployment Rate").direction == -1
    assert classify("Non-Farm Employment Change").type == "jobs"
    assert classify("US Non-Farm Payrolls / Unemployment").type == "jobs"
    assert classify("Unemployment Claims").type == "unemployment"
    assert classify("FOMC Member Waller Speaks").type == "speech"
    assert classify("Federal Funds Rate").type == "rate"
    assert classify("Bank Holiday", "holiday").type == "holiday"
    assert classify("Something Odd") is None
    assert plain_title("CPI m/m", "USD") == "US inflation"


def test_meaning_depends_on_base_or_quote():
    m = meaning("CPI m/m", "USD", EURUSD)
    assert "US dollar stronger" in m and "EUR/USD tends to fall" in m          # USD is EUR/USD's quote
    assert "USD/JPY tends to rise" in meaning("CPI m/m", "USD", USDJPY)         # USD is USD/JPY's base
    assert "EUR/USD tends to rise" in meaning("CPI y/y", "EUR", EURUSD)
    assert "weaker" in meaning("Unemployment Rate", "USD", EURUSD) and "EUR/USD tends to rise" in \
        meaning("Unemployment Rate", "USD", EURUSD)
    assert "Little direct effect on EUR/USD" in meaning("CPI m/m", "AUD", EURUSD)
    assert "Bank holiday" in meaning("Bank Holiday", "All", EURUSD, "holiday")
    assert "hint at future interest-rate" in meaning("FOMC Member Waller Speaks", "USD", EURUSD)
    assert "share prices" in meaning("CPI m/m", "USD", AAPL)


def test_meaning_compares_actual_with_forecast():
    m = meaning("CPI m/m", "USD", EURUSD, actual="0.5%", forecast="0.3%")
    assert m.startswith("Came in higher than expected (0.5% vs 0.3% forecast)") and "EUR/USD tends to fall" in m
    m = meaning("CPI m/m", "USD", EURUSD, actual="0.1%", forecast="0.3%")
    assert "lower than expected" in m and "weaker" in m and "EUR/USD tends to rise" in m
    assert "as expected" in meaning("CPI m/m", "USD", EURUSD, actual="0.3%", forecast="0.3%")
    assert parse_number("245K") == 245000 and parse_number("-0.2%") == -0.2 and parse_number("") is None
    assert surprise("119K", "50K") == "higher" and surprise("", "1") is None


# ---------------- calendar ----------------
def test_window_today_and_week():
    lo, hi = window("today", NOW, "Europe/Berlin")
    assert lo == datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc) and hi == datetime(2026, 11, 10, 23, 0, tzinfo=timezone.utc)
    lo, hi = window("week", NOW, "UTC")
    assert lo == datetime(2026, 11, 9, tzinfo=timezone.utc) and hi == datetime(2026, 11, 16, tzinfo=timezone.utc)
    sat = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    lo, hi = window("week", sat, "UTC")  # weekend: today until the end of next week
    assert lo == datetime(2026, 11, 14, tzinfo=timezone.utc) and hi == datetime(2026, 11, 23, tzinfo=timezone.utc)


def test_calendar_view_filters_meaning_and_next_major():
    v = calendar_view(EURUSD, None, None, "today", "UTC", data=FakeData(), ff_fetch=ff, now=NOW)
    titles = [e["title"] for e in v["events"]]
    assert titles == ["BOJ Gov Ueda Speaks", "German ZEW Economic Sentiment"]
    boj = v["events"][0]
    assert boj["past"] and not boj["affects_symbol"] and "Little direct effect" in boj["meaning"]
    assert v["next_major"]["title"] == "CPI m/m" and "EUR/USD tends to fall" in v["next_major"]["meaning"]
    assert v["feed_ok"]

    week = calendar_view(EURUSD, ["USD"], ["high"], "week", "UTC", data=FakeData(), ff_fetch=ff, now=NOW)
    assert [e["title"] for e in week["events"]] == ["CPI m/m", "Federal Funds Rate"]
    assert all(e["impact"] == "high" for e in week["events"])
    hol = calendar_view(None, ["EUR"], ["holiday"], "week", "UTC", data=FakeData(), ff_fetch=ff, now=NOW)
    assert [e["title"] for e in hol["events"]] == ["Bank Holiday"]  # global events kept under a currency filter


class FredData(FakeData):
    def __init__(self, last_obs="2026-10-01"):
        super().__init__()
        self.last_obs = last_obs

    def get_macro_series(self, sid):
        idx = pd.date_range(end=self.last_obs, periods=30, freq="MS")
        vals = np.linspace(300, 310, 30)
        vals[-1] = vals[-2] * 1.003  # +0.3% m/m in the last month
        return pd.Series(vals, index=idx)


def test_fred_fills_actual_for_us_release_only_when_fresh():
    cpi = CalendarEvent(datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc), "USD", "CPI m/m", "high", "0.3%", "0.4%")
    assert fred_actual(cpi, FredData("2026-10-01")) == "0.3%"
    assert fred_actual(cpi, FredData("2026-09-01")) == ""   # FRED not updated yet: never show last month's number
    v = calendar_view(EURUSD, ["USD"], None, "week", "UTC", data=FredData(), ff_fetch=ff,
                      now=datetime(2026, 11, 12, 15, tzinfo=timezone.utc))
    row = next(e for e in v["events"] if e["title"] == "CPI m/m")
    assert row["actual"] == "0.3%" and row["actual_source"] == "FRED" and row["surprise"] == "inline"


def test_calendar_notes_missing_fred_key():
    class NoFred(FakeData):
        def get_macro_series(self, sid):
            raise RuntimeError("FRED_API_KEY not set")

    v = calendar_view(EURUSD, ["USD"], None, "week", "UTC", data=NoFred(), ff_fetch=ff,
                      now=datetime(2026, 11, 12, 15, tzinfo=timezone.utc))
    assert any("FRED_API_KEY" in n for n in v["notes"])
    assert next(e for e in v["events"] if e["title"] == "CPI m/m")["actual"] == ""


# ---------------- central banks ----------------
def test_expectation_proxy():
    assert expectation(-0.5, 2.1, 2.0, None, None)["lean"] == "cut"
    assert expectation(0.0, 4.0, 2.0, None, None)["lean"] == "hike"
    assert expectation(0.0, 2.2, 2.0, None, None)["lean"] == "hold"
    e = expectation(0.0, 2.0, 2.0, 3.2, 3.75)
    assert e["lean"] == "cut" and "markets expect cuts" in e["reasons"][-1] and "estimate" in e["label"]
    assert expectation(None, None, None, None, None)["lean"] == "unknown"


def test_central_banks_table():
    out = central_banks(FakeData(), [], now=NOW)
    by = {b["currency"]: b for b in out["banks"]}
    assert by["USD"]["policy_rate"] == 5.0 and by["USD"]["expectation"]["lean"] in ("hike", "hold", "cut")
    assert by["EUR"]["rate_change_6m"] < 0 and by["EUR"]["next_meeting"]["date"] == "2026-12-17"
    assert by["CHF"]["next_meeting_text"] == "date not in calendar file"
    assert "estimate" in out["tooltip"]
    ev = [e for e in ff() if e.title == "Federal Funds Rate"]
    assert central_banks(FakeData(), ev, now=NOW)["banks"][0]["next_meeting"]["source"] == "ForexFactory"


# ---------------- strength ----------------
class TrendData:
    """Synthetic prices: each currency has a value index; USD rises 0.2% per hour, JPY falls 0.1%."""
    drift = {"USD": 0.002, "JPY": -0.001}

    def __init__(self, missing=()):
        self.missing = set(missing)

    def get_ohlcv(self, symbol, timeframe="1h"):
        if symbol.ticker in self.missing:
            raise RuntimeError("no data")
        idx = pd.date_range("2026-11-10", periods=48, freq="h", tz="UTC")
        t = np.arange(48)
        b, q = symbol.ticker.split("/")
        val = lambda c: np.exp(self.drift.get(c, 0.0) * t)
        close = val(b) / val(q)
        df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 0.0}, index=idx)
        df.attrs["source"] = "yfinance"
        return df


def test_strength_usd_rising_is_strongest():
    out = currency_strength(TrendData(), "4h", now=datetime(2026, 11, 11, 23, tzinfo=timezone.utc))
    rows = out["currencies"]
    assert rows[0]["currency"] == "USD" and rows[-1]["currency"] == "JPY"
    assert rows[0]["n_pairs"] == 7 and rows[0]["strength"] > 0 > rows[-1]["strength"]
    assert not out["live"] and any("delayed" in n for n in out["notes"])
    assert len(PAIRS) == 28


def test_strength_handles_missing_pairs():
    out = currency_strength(TrendData(missing={"EUR/USD", "GBP/USD"}), "1d",
                            now=datetime(2026, 11, 11, 23, tzinfo=timezone.utc))
    usd = next(r for r in out["currencies"] if r["currency"] == "USD")
    assert usd["n_pairs"] == 5 and set(out["missing_pairs"]) == {"EUR/USD", "GBP/USD"}
    assert out["currencies"][0]["currency"] == "USD"
    assert pair_change(None, pd.Timedelta(hours=1)) is None
    assert all(r["strength"] is None for r in combine({p: None for p in PAIRS}))


# ---------------- news summary ----------------
def test_summary_number_guard():
    h = "Fed cuts rates by 25 basis points to 3.75%"
    assert summary_ok(h, "The Fed lowered rates by 25 basis points, which can weaken the dollar.")
    assert not summary_ok(h, "The Fed cut rates to 3.5%, a big move.")            # 3.5 is not in the headline
    assert not summary_ok(h, "")
    assert guard_summaries([h], ["ok summary", "extra"]) == [None]


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def run(self, system, messages, tools, execute, model=None, max_steps=1, on_event=None):
        self.calls += 1
        return SimpleNamespace(text=self.reply)


class MemCache:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v, ttl):
        self.d[k] = v


def test_summarise_cached_and_guarded():
    heads = ["Apple beats estimates, shares rise 5%", "Apple faces EU probe"]
    llm, cache = FakeLLM('["Apple earned more than expected and shares rose 5%.", "Apple sales fell 12% after an EU probe."]'), MemCache()
    r = summarise("AAPL", heads, provider=llm, cache=cache)
    assert r["summaries"][0].startswith("Apple earned") and r["summaries"][1] is None  # invented 12% dropped
    r2 = summarise("AAPL", heads, provider=llm, cache=cache)
    assert llm.calls == 1 and r2["cached"]
    off = summarise("AAPL", heads)  # no API key in tests
    assert not off["enabled"] and "ANTHROPIC_API_KEY" in off["note"] and off["summaries"] == [None, None]


# ---------------- bias ----------------
def test_fx_bias_text():
    b = fundamental_bias(EURUSD, FakeData())
    assert b["bias"] in ("bullish", "bearish", "neutral") and 1 <= len(b["why"]) <= 3
    assert any("Interest rates are higher in the US (5.00%)" in s for s in b["why"])
    assert b["bias"] == "bearish" and "EUR/USD leans down" in b["why"][0]


def test_fx_bias_without_fred():
    class NoFred(FakeData):
        def get_macro_series(self, sid):
            raise RuntimeError("FRED_API_KEY not set")

    b = fundamental_bias(EURUSD, NoFred())
    assert b["bias"] == "unknown" and "FRED_API_KEY" in b["why"][0]


def test_stock_bias_and_plain_facts():
    b = fundamental_bias(AAPL, FakeData())
    assert b["kind"] == "stock" and b["bias"] == "bullish" and len(b["why"]) <= 3
    assert "The company's sales grew 20% over the last year." in b["why"]
    from analysis.fundamental import analyse_stock

    facts = {f["key"]: f for f in stock_facts(analyse_stock(AAPL, data=FakeData()))}
    assert facts["margin"]["text"] == "Out of every 100 in sales, about 20 is left as profit."
    assert facts["debt"]["value"] == "0.30x" and facts["debt"]["tone"] == "good"


# ---------------- API ----------------
@pytest.fixture
def client():
    app = create_app(background=False)
    app.dependency_overrides[deps.get_data] = lambda: FakeData()
    app.dependency_overrides[ft.get_ff_fetch] = lambda: ff
    app.dependency_overrides[ft.get_now] = lambda: NOW
    with TestClient(app) as c:
        yield c, app


def test_api_calendar_filters(client):
    c, _ = client
    r = c.get("/api/fund/calendar", params={"symbol": "EUR/USD", "range": "week", "currencies": "USD,EUR",
                                            "impact": "high,medium", "tz": "Europe/Berlin"})
    assert r.status_code == 200
    j = r.json()
    assert [e["title"] for e in j["events"]] == ["German ZEW Economic Sentiment", "CPI m/m", "Federal Funds Rate"]
    assert j["next_major"]["title"] == "CPI m/m" and j["tz"] == "Europe/Berlin"
    assert c.get("/api/fund/calendar", params={"range": "month"}).status_code == 422


def test_api_sections(client):
    c, app = client
    cb = c.get("/api/fund/central-banks").json()
    assert {b["currency"] for b in cb["banks"]} >= {"USD", "EUR", "GBP", "JPY"}
    app.dependency_overrides[deps.get_data] = lambda: TrendData()
    s = c.get("/api/fund/strength", params={"tf": "1h"}).json()
    assert s["currencies"][0]["currency"] == "USD"
    assert c.get("/api/fund/strength", params={"tf": "2h"}).status_code == 422
    app.dependency_overrides[deps.get_data] = lambda: FakeData()
    assert c.get("/api/fund/bias", params={"symbol": "EUR/USD"}).json()["bias"] == "bearish"
    assert c.get("/api/fund/bias", params={"symbol": "AAPL"}).json()["kind"] == "stock"
    st = c.get("/api/fund/stock", params={"symbol": "AAPL"}).json()
    assert st["facts"] and st["analysts"]["upside_pct"] == 25.0
    assert c.get("/api/fund/stock", params={"symbol": "EUR/USD"}).status_code == 400
    n = c.get("/api/fund/news", params={"symbol": "AAPL"}).json()
    assert n["headlines"][0]["label"] == "positive"
    ns = c.get("/api/fund/news-summary", params={"symbol": "AAPL"}).json()
    assert ns["enabled"] is False and len(ns["items"]) == 2
    app.dependency_overrides[ft.get_llm] = lambda: FakeLLM('["Test Corp did better than expected.", "Analysts like it."]')
    ns = c.get("/api/fund/news-summary", params={"symbol": "AAPL", "days": 3}).json()
    assert ns["enabled"] and ns["items"][0]["summary"] == "Test Corp did better than expected."


def test_api_section_failure_is_isolated(client):
    c, app = client

    class Broken(FakeData):
        def get_ohlcv(self, symbol, timeframe="1d"):
            raise RuntimeError("offline")

    app.dependency_overrides[deps.get_data] = lambda: Broken()
    s = c.get("/api/fund/strength").json()  # all pairs missing: still a valid, empty meter
    assert len(s["missing_pairs"]) == 28 and all(r["strength"] is None for r in s["currencies"])
    assert c.get("/api/fund/calendar").status_code == 200


def test_next_event_beyond_feed_uses_fallback_and_notes_missing_week():
    from data.providers.base import EconomicEvent

    class Later(FakeData):
        def upcoming_events(self, currencies, days=14):
            return [EconomicEvent(datetime(2026, 12, 9, tzinfo=timezone.utc), "USD", "FOMC rate decision", "high", "events.yaml")]

    sat = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)  # feed's events all in the past, next week not published
    v = calendar_view(EURUSD, None, None, "week", "UTC", data=Later(), ff_fetch=ff, now=sat)
    assert v["next_major"]["title"] == "FOMC rate decision" and v["next_major"]["time_exact"] is False
    assert any("not published next week's list" in n for n in v["notes"])
