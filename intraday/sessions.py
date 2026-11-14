"""Trading sessions and the intraday time rules (same session hours as web/src/lib/sessions.ts).

  Asian (Tokyo)  09:00-18:00 Asia/Tokyo
  London         08:00-17:00 Europe/London
  New York       08:00-17:00 America/New_York
  Forex closed   Friday 17:00 - Sunday 17:00 America/New_York
Each session is evaluated in its own time zone (zoneinfo), so summer/winter time is handled automatically.

Time rules (in the configured SESSION_TIMEZONE, default Europe/Berlin):
  * no new entries after NO_NEW_ENTRIES_AFTER (18:00)
  * every trade closed by FLAT_BY (21:30) - the time stop
  * EUR/USD and the other European/US pairs only take new entries in the London or New York session
    (the London-New York overlap is the busiest and best time); yen/aussie/kiwi pairs also in the Asian session.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from data.stream.market_hours import NY, forex_open, market_open
from data.symbols import Symbol
from intraday.config import IntradayConfig

SESSIONS = (("Asian", "Asia/Tokyo", 9, 18), ("London", "Europe/London", 8, 17), ("New York", "America/New_York", 8, 17))
ASIAN_OK = {"JPY", "AUD", "NZD"}


def _hour(now: datetime, tz: str) -> tuple[float, int]:
    t = now.astimezone(ZoneInfo(tz))
    return t.hour + t.minute / 60, t.weekday()


def active_sessions(now: datetime) -> list[str]:
    if not forex_open(now):
        return []
    out = []
    for name, tz, o, c in SESSIONS:
        h, wd = _hour(now, tz)
        if wd < 5 and o <= h < c:
            out.append(name)
    return out


def session_label(now: datetime) -> str:
    if not forex_open(now):
        return "Market closed (weekend)"
    a = active_sessions(now)
    if "London" in a and "New York" in a:
        return "London–New York overlap"
    if not a:
        return "Between sessions (quiet)"
    return " + ".join(a) + " session"


def session_key(now: datetime) -> str:
    """Short key stored with each plan (for per-session statistics): asian | london | overlap | new_york | off."""
    a = active_sessions(now)
    if "London" in a and "New York" in a:
        return "overlap"
    if "London" in a:
        return "london"
    if "New York" in a:
        return "new_york"
    if "Asian" in a:
        return "asian"
    return "off"


def next_forex_open(now: datetime) -> datetime:
    """Next Sunday 17:00 New York time (UTC), or `now` if forex is open."""
    if forex_open(now):
        return now
    t = now.astimezone(NY)
    days = (6 - t.weekday()) % 7
    d = (t + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)
    if d <= t:
        d += timedelta(days=7)
    return d.astimezone(timezone.utc)


def local_at(now: datetime, tz: str, hhmm) -> datetime:
    """Today's (in `tz`) wall-clock time `hhmm`, as an aware UTC datetime."""
    loc = now.astimezone(ZoneInfo(tz))
    return loc.replace(hour=hhmm.hour, minute=hhmm.minute, second=0, microsecond=0).astimezone(timezone.utc)


def entry_cutoff(now: datetime, cfg: IntradayConfig) -> datetime:
    return local_at(now, cfg.tz, cfg.no_new_entries_after)


def flat_time(now: datetime, cfg: IntradayConfig) -> datetime:
    """When an open trade must be closed: today's FLAT_BY, or tomorrow's if that already passed."""
    t = local_at(now, cfg.tz, cfg.flat_by)
    return t if t > now else local_at(now + timedelta(days=1), cfg.tz, cfg.flat_by)


def fmt_local(t: datetime, cfg: IntradayConfig, with_day: bool = False) -> str:
    loc = t.astimezone(ZoneInfo(cfg.tz))
    return loc.strftime("%a %H:%M") if with_day else loc.strftime("%H:%M")


def entries_allowed(now: datetime, symbol: Symbol, cfg: IntradayConfig) -> tuple[bool, str | None, str]:
    """(allowed, code, plain reason). Codes: market_closed | after_cutoff | quiet_session."""
    is_open = market_open(symbol.market, symbol.is_fx, now)
    if is_open is False:
        if symbol.is_fx:
            return False, "market_closed", f"The market is closed. It opens again {fmt_local(next_forex_open(now), cfg, True)} ({cfg.tz.split('/')[-1]} time)."
        return False, "market_closed", "The stock exchange is closed right now."
    cut = entry_cutoff(now, cfg)
    loc = now.astimezone(ZoneInfo(cfg.tz))
    if now >= cut or loc.time() >= cfg.flat_by:
        return False, "after_cutoff", (f"It's after {cfg.no_new_entries_after.strftime('%H:%M')} – too late in the day "
                                       "to open a new trade that must be closed the same day.")
    if symbol.is_fx:
        a = active_sessions(now)
        ok = "London" in a or "New York" in a or ("Asian" in a and (symbol.base in ASIAN_OK or symbol.quote in ASIAN_OK))
        if not ok:
            return False, "quiet_session", ("It's a quiet time of day for this pair (outside the London and New York "
                                            "sessions): price moves are small and less reliable.")
    return True, None, ""
