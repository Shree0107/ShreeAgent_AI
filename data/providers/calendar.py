"""Economic calendar with exact event times (needed for the +-30 min news filter and the Fundamentals tab).

Sources, merged:
  1. ForexFactory weekly feed (free, unofficial): https://nfs.faireconomy.media/ff_calendar_thisweek.json
     (and ..._nextweek.json). Exact time, currency, impact (High/Medium/Low/Holiday), forecast, previous.
     It has no "actual" values.
  2. Fallback when the feed is unavailable: FRED US release dates + config/events.yaml central-bank meetings,
     at their standard release times (US data 08:30 New York, JOLTS 10:00, FOMC 14:00 New York, ECB 14:15
     Frankfurt, BoE 12:00 London, BoJ ~12:00 Tokyo, RBI 10:00 Mumbai).
All times are returned in UTC.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from data.http import ProviderError, get_json

log = logging.getLogger(__name__)

FF_URLS = {
    "thisweek": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "nextweek": "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
}
MAJOR_KEYWORDS = ("CPI", "Non-Farm", "NFP", "Employment Change", "FOMC", "Federal Funds Rate", "Main Refinancing",
                  "ECB", "Official Bank Rate", "BOE", "BOJ", "Policy Rate", "Cash Rate", "Overnight Rate",
                  "Rate Statement", "Press Conference", "Monetary Policy")

# title fragment -> (timezone, local release time) for the fallback calendar
STANDARD_TIMES = [
    ("JOLTS", "America/New_York", time(10, 0)),
    ("FOMC", "America/New_York", time(14, 0)),
    ("ECB", "Europe/Berlin", time(14, 15)),
    ("BoE", "Europe/London", time(12, 0)),
    ("BoJ", "Asia/Tokyo", time(12, 0)),
    ("RBI", "Asia/Kolkata", time(10, 0)),
    ("US ", "America/New_York", time(8, 30)),   # CPI, NFP, PPI, retail sales, GDP, PCE
]


@dataclass
class CalendarEvent:
    time: datetime          # UTC
    currency: str           # USD, EUR, ... ("All" for global holidays)
    title: str
    impact: str             # high | medium | low | holiday
    forecast: str = ""
    previous: str = ""
    actual: str = ""
    source: str = "forexfactory"
    time_exact: bool = True  # False when the time is the standard release time (fallback source)

    @property
    def major(self) -> bool:
        """ForexFactory's own impact rating is reliable: only High counts (so "FOMC Member X Speaks", rated Low,
        does not block trading). Fallback events have no rating, so keywords decide there."""
        if self.source == "forexfactory":
            return self.impact == "high"
        return any(k.lower() in self.title.lower() for k in MAJOR_KEYWORDS)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["time"] = self.time.isoformat()
        d["major"] = self.major
        return d


def parse_ff(items: list[dict]) -> list[CalendarEvent]:
    out = []
    for it in items or []:
        try:
            t = pd.Timestamp(it["date"]).tz_convert("UTC").to_pydatetime()
        except Exception:
            continue
        out.append(CalendarEvent(t, str(it.get("country", "")).upper().replace("ALL", "All"), it.get("title", ""),
                                 str(it.get("impact", "")).lower() or "low", it.get("forecast") or "",
                                 it.get("previous") or "", it.get("actual") or "", "forexfactory", True))
    return out


def standard_time(title: str, day: datetime) -> tuple[datetime, bool]:
    for frag, tz, t in STANDARD_TIMES:
        if frag.lower() in title.lower():
            local = datetime.combine(day.date(), t, ZoneInfo(tz))
            return local.astimezone(timezone.utc), True
    return datetime.combine(day.date(), time(12, 0), timezone.utc), False


def fallback_events(data, currencies: list[str], days: int) -> list[CalendarEvent]:
    out = []
    try:
        for e in data.upcoming_events(currencies, days):
            t, known = standard_time(e.title, e.date)
            out.append(CalendarEvent(t, e.currency, e.title, "high" if e.impact == "high" else "medium",
                                     source=e.source or "fallback", time_exact=False))
    except Exception as e:
        log.info("Fallback calendar unavailable: %s", e)
    return out


def fetch_ff(cache=None) -> list[CalendarEvent]:
    """This week + next week from the feed (each cached for an hour). Raises ProviderError if both fail."""
    if cache is None:
        from data.cache import get_cache

        cache = get_cache()
    events: list[CalendarEvent] = []
    errors = []
    for key, url in FF_URLS.items():
        try:
            items = cache.get_or_fetch(f"cal:ff:{key}", 3600, lambda url=url: get_json(url, provider="forexfactory", cpm=6))
            events += parse_ff(items)
        except Exception as e:  # next week's file is often missing early in the week
            errors.append(f"{key}: {e}")
    if not events:
        raise ProviderError("ForexFactory calendar unavailable: " + "; ".join(errors))
    return events


def get_calendar(currencies: list[str] | None = None, days_back: int = 1, days_ahead: int = 7, data=None,
                 ff_fetch=fetch_ff, now: datetime | None = None) -> list[CalendarEvent]:
    """Events from (now - days_back) to (now + days_ahead), sorted by time, optionally filtered by currency.
    Global events (currency 'All', e.g. holidays) are always kept."""
    now = now or datetime.now(timezone.utc)
    lo, hi = now - timedelta(days=days_back), now + timedelta(days=days_ahead)
    cur = {c.upper() for c in currencies} if currencies else None
    try:
        events = ff_fetch()
    except Exception as e:
        log.info("Using fallback calendar: %s", e)
        if data is None:
            from data.service import get_data_service

            data = get_data_service()
        events = fallback_events(data, sorted(cur) if cur else ["USD", "EUR", "GBP", "JPY", "INR"], days_ahead)
    seen = set()
    out = []
    for e in sorted(events, key=lambda x: x.time):
        if not (lo <= e.time <= hi):
            continue
        if cur and e.currency not in cur and e.currency != "All":
            continue
        k = (e.time, e.currency, e.title)
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def blackout(events: list[CalendarEvent], currencies: list[str], now: datetime | None = None,
             minutes: int = 30) -> CalendarEvent | None:
    """The major event (for these currencies) whose +-`minutes` window contains `now`, if any."""
    now = now or datetime.now(timezone.utc)
    cur = {c.upper() for c in currencies}
    win = timedelta(minutes=minutes)
    for e in events:
        if e.major and (e.currency in cur or e.currency == "All") and e.impact != "holiday" and \
                e.time - win <= now <= e.time + win:
            return e
    return None


def next_major(events: list[CalendarEvent], currencies: list[str], now: datetime | None = None) -> CalendarEvent | None:
    now = now or datetime.now(timezone.utc)
    cur = {c.upper() for c in currencies}
    return next((e for e in events if e.major and e.currency in cur and e.time > now and e.impact != "holiday"), None)
