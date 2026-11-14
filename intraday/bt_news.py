"""High-impact news for past dates, for the backtest's news blackout.

The live engine reads the ForexFactory feed, which only covers this week and next week, so the backtest builds an
approximate history instead (LIMITATION: it is incomplete, see below):
  1. US jobs report (Non-Farm Payrolls): first Friday of each month, 08:30 New York time (a rule, usually right;
     a few months move it to the second Friday).
  2. Central-bank meetings from config/events.yaml (the curated list; only the dates entered there), at their
     standard announcement times (FOMC 14:00 New York, ECB 14:15 Frankfurt, BoE 12:00 London, ...).
  3. Optional: your own list in {user_data_dir}/intraday_backtests/news_history.csv with the columns
     time (UTC, ISO), currency, title  - e.g. exported from a calendar website. Every row counts as high impact.
Missing: US CPI, GDP, retail sales, euro-area data, ... unless you add them in (3). So the backtest may take some
trades the live engine would have blocked; results around big news days are therefore a bit too optimistic or
pessimistic.
"""
from __future__ import annotations

import bisect
import csv
import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from data.providers.calendar import CalendarEvent, standard_time

log = logging.getLogger(__name__)
NOTE = ("News history is approximate: the US jobs report (first Friday rule), the central-bank dates in "
        "config/events.yaml and your own news_history.csv. Other big news days are not filtered out.")


class UserEvent(CalendarEvent):
    """A row of the user's own news list: always counts as high impact (no keyword check)."""

    @property
    def major(self) -> bool:
        return True


def nfp_events(start: date, end: date) -> list[CalendarEvent]:
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        d = date(y, m, 1)
        d += timedelta(days=(4 - d.weekday()) % 7)            # first Friday
        t = datetime.combine(d, time(8, 30), ZoneInfo("America/New_York")).astimezone(timezone.utc)
        out.append(CalendarEvent(t, "USD", "Non-Farm Payrolls (first-Friday rule)", "high", source="backtest_rule",
                                 time_exact=False))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def curated_events() -> list[CalendarEvent]:
    out = []
    try:
        from data.service import _curated_events

        for e in _curated_events():
            t, _ = standard_time(e.title, e.date)
            out.append(CalendarEvent(t, e.currency, e.title, "high", source="events.yaml", time_exact=False))
    except Exception as e:
        log.info("Curated events unavailable: %s", e)
    return out


def user_events(path=None) -> list[CalendarEvent]:
    if path is None:
        from config.settings import get_settings

        path = get_settings().user_data_dir / "intraday_backtests" / "news_history.csv"
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    t = datetime.fromisoformat(row["time"].strip().replace("Z", "+00:00"))
                    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
                    out.append(UserEvent(t.astimezone(timezone.utc), row["currency"].strip().upper(),
                                         (row.get("title") or "News").strip(), "high", source="user_csv"))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return out


class NewsHistory:
    """Sorted events with a fast window query: events(now) ~ what the live calendar would list at `now`."""

    def __init__(self, events: list[CalendarEvent]):
        self.items = sorted(events, key=lambda e: e.time)
        self.times = [e.time for e in self.items]

    @classmethod
    def build(cls, start: datetime, end: datetime, extra: list[CalendarEvent] | None = None) -> NewsHistory:
        ev = nfp_events(start.date(), end.date()) + curated_events() + user_events() + list(extra or [])
        return cls(ev)

    def events(self, now: datetime, back: timedelta = timedelta(days=1), ahead: timedelta = timedelta(days=2)) -> list:
        lo = bisect.bisect_left(self.times, now - back)
        hi = bisect.bisect_right(self.times, now + ahead)
        return self.items[lo:hi]
