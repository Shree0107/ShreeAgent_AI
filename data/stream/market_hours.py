"""When markets are open, so a quiet feed can be told apart from a broken one.

Forex trades from Sunday 17:00 to Friday 17:00 New York time (DST handled by zoneinfo). Stock exchanges use
their local hours; an unknown exchange is treated as 'maybe open' so we never hide a real outage.
Same rules as web/src/lib/sessions.ts.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

# market -> (timezone, open, close) on weekdays
EXCHANGES = {
    "US": ("America/New_York", time(9, 30), time(16, 0)),
    "NSE": ("Asia/Kolkata", time(9, 15), time(15, 30)),
    "BSE": ("Asia/Kolkata", time(9, 15), time(15, 30)),
}


def forex_open(now: datetime | None = None) -> bool:
    t = (now or datetime.now(timezone.utc)).astimezone(NY)
    wd, h = t.weekday(), t.hour + t.minute / 60  # Mon=0 .. Sun=6
    if wd == 5:
        return False
    if wd == 4 and h >= 17:
        return False
    if wd == 6 and h < 17:
        return False
    return True


def market_open(market: str, is_fx: bool, now: datetime | None = None) -> bool | None:
    """True / False, or None when the exchange hours are unknown."""
    if is_fx:
        return forex_open(now)
    spec = EXCHANGES.get(market)
    if not spec:
        return None
    tz, o, c = spec
    t = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz))
    return t.weekday() < 5 and o <= t.time() < c
