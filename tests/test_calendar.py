"""Economic calendar: feed parsing, fallback with standard release times, filters, news blackout."""
from datetime import datetime, timezone

from data.providers.base import EconomicEvent
from data.providers.calendar import (
    CalendarEvent, blackout, get_calendar, next_major, parse_ff, standard_time,
)

FEED = [
    {"title": "CPI m/m", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High",
     "forecast": "0.3%", "previous": "0.4%"},
    {"title": "German ZEW Economic Sentiment", "country": "EUR", "date": "2026-11-10T05:00:00-05:00", "impact": "Medium",
     "forecast": "40.1", "previous": "39.3"},
    {"title": "Bank Holiday", "country": "All", "date": "2026-11-11T00:00:00-05:00", "impact": "Holiday",
     "forecast": "", "previous": ""},
    {"title": "RBA Assist Gov Hunter Speaks", "country": "AUD", "date": "2026-11-08T17:30:00-05:00", "impact": "Low"},
]
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def test_parse_feed_to_utc():
    ev = parse_ff(FEED)
    cpi = next(e for e in ev if e.title == "CPI m/m")
    assert cpi.time == datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc)       # 08:30 New York (EST) = 13:30 UTC
    assert cpi.impact == "high" and cpi.major and cpi.forecast == "0.3%" and cpi.time_exact
    assert not next(e for e in ev if "ZEW" in e.title).major


def test_filter_by_currency_and_window_keeps_global_events():
    ev = get_calendar(["EUR", "USD"], days_back=1, days_ahead=7, ff_fetch=lambda: parse_ff(FEED), now=NOW)
    assert [e.title for e in ev] == ["German ZEW Economic Sentiment", "Bank Holiday", "CPI m/m"]  # AUD dropped, sorted


def test_blackout_30_minutes_around_major_news():
    ev = parse_ff(FEED)
    cpi_t = datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc)
    assert blackout(ev, ["EUR", "USD"], cpi_t.replace(minute=5)).title == "CPI m/m"     # 25 min before
    assert blackout(ev, ["EUR", "USD"], cpi_t.replace(hour=14, minute=0)) is not None  # 30 min after
    assert blackout(ev, ["EUR", "USD"], cpi_t.replace(hour=14, minute=1)) is None
    assert blackout(ev, ["GBP"], cpi_t) is None                                          # not this pair's currency
    assert next_major(ev, ["USD"], NOW).title == "CPI m/m"


def test_fallback_uses_standard_release_times_when_feed_fails():
    class D:
        def upcoming_events(self, currencies, days=14):
            return [EconomicEvent(datetime(2026, 11, 12, tzinfo=timezone.utc), "USD", "US CPI (inflation)", "high", "FRED"),
                    EconomicEvent(datetime(2026, 12, 17, tzinfo=timezone.utc), "EUR", "ECB monetary policy decision", "high", "events.yaml")]

    def broken():
        raise RuntimeError("feed down")

    ev = get_calendar(["USD", "EUR"], days_back=1, days_ahead=60, data=D(), ff_fetch=broken, now=NOW)
    cpi = ev[0]
    assert cpi.time == datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc) and not cpi.time_exact
    ecb = ev[1]
    assert ecb.time == datetime(2026, 12, 17, 13, 15, tzinfo=timezone.utc)              # 14:15 Frankfurt (CET)
    assert standard_time("Something else", NOW)[1] is False


def test_event_json():
    e = CalendarEvent(NOW, "USD", "Non-Farm Employment Change", "high")
    d = e.as_dict()
    assert d["major"] is True and d["time"].startswith("2026-11-10T09:00")


def test_low_impact_speeches_are_not_major():
    ev = parse_ff([{"title": "FOMC Member Bowman Speaks", "country": "USD", "date": "2026-11-10T08:40:00-05:00", "impact": "Low"},
                   {"title": "German Final CPI m/m", "country": "EUR", "date": "2026-11-11T02:00:00-05:00", "impact": "Low"}])
    assert not any(e.major for e in ev)
