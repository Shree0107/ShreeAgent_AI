"""Calendar for the Fundamentals tab: Today / This week windows, currency + impact filters, the next big event,
plain-language meaning lines, and 'actual' numbers for US releases from FRED (the free feed has none)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from analysis.fundtab import symbol_currencies
from analysis.fundtab.meaning import classify, meaning, plain_title, surprise
from data.providers.calendar import CalendarEvent, fallback_events, fetch_ff, get_calendar, next_major

log = logging.getLogger(__name__)

IMPACTS = ("high", "medium", "low", "holiday")

# ForexFactory title (USD) -> (FRED series, transform, format, max age of the observation at release, in days).
# The observation must be the period the release reports (e.g. October CPI, released mid-November), so an older
# observation (FRED not updated yet) is rejected rather than shown as the new number.
FRED_ACTUALS = {
    "cpi m/m": ("CPIAUCSL", "mom", "{:.1f}%", (20, 50)),
    "cpi y/y": ("CPIAUCSL", "yoy", "{:.1f}%", (20, 50)),
    "core cpi m/m": ("CPILFESL", "mom", "{:.1f}%", (20, 50)),
    "core cpi y/y": ("CPILFESL", "yoy", "{:.1f}%", (20, 50)),
    "unemployment rate": ("UNRATE", "level", "{:.1f}%", (20, 50)),
    "non-farm employment change": ("PAYEMS", "diff", "{:.0f}K", (20, 50)),
    "retail sales m/m": ("RSAFS", "mom", "{:.1f}%", (10, 50)),
    "core pce price index m/m": ("PCEPILFE", "mom", "{:.1f}%", (20, 65)),
    "ppi m/m": ("PPIFIS", "mom", "{:.1f}%", (10, 50)),
    "unemployment claims": ("ICSA", "level_k", "{:.0f}K", (0, 13)),
}


def _tz(name: str | None) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name) if name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def window(range_: str, now: datetime, tz_name: str | None = None) -> tuple[datetime, datetime]:
    """'today' = the user's local calendar day. 'week' = Monday..Sunday of this week in local time; on a weekend
    (markets shut) it is today until the end of next week, so the coming week is visible."""
    tz = _tz(tz_name)
    local = now.astimezone(tz)
    start_today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_ == "today":
        lo, hi = start_today, start_today + timedelta(days=1)
    else:
        wd = start_today.weekday()
        if wd >= 5:
            lo, hi = start_today, start_today + timedelta(days=7 - wd + 7)
        else:
            lo = start_today - timedelta(days=wd)
            hi = lo + timedelta(days=7)
    return lo.astimezone(timezone.utc), hi.astimezone(timezone.utc)


def _fred_series(data, sid: str) -> pd.Series:
    # Shortly after a release DataService's 24 h macro cache would hide the new number: use a 30 min cache.
    macro, cache = getattr(data, "macro", None), getattr(data, "cache", None)
    if macro is not None and cache is not None:
        return cache.get_or_fetch(f"fund:fred:{sid}", 1800, lambda: macro.get_series(sid))
    return data.get_macro_series(sid)


def fred_actual(ev: CalendarEvent, data) -> str:
    """The released number for a US event from FRED, formatted like the feed ('0.3%', '119K'), or ''."""
    spec = FRED_ACTUALS.get(ev.title.strip().lower())
    if ev.currency != "USD" or not spec:
        return ""
    sid, how, fmt, (min_age, max_age) = spec
    s = _fred_series(data, sid).dropna()
    if len(s) < 14:
        return ""
    obs_date = s.index[-1]
    t = pd.Timestamp(ev.time).tz_convert(None) if pd.Timestamp(ev.time).tzinfo else pd.Timestamp(ev.time)
    age = (t.normalize() - obs_date.normalize()).days
    if not (min_age <= age <= max_age):
        return ""
    last, prev = float(s.iloc[-1]), float(s.iloc[-2])
    if how == "mom":
        v = (last / prev - 1) * 100
    elif how == "yoy":
        prior = s[s.index <= obs_date - pd.DateOffset(months=12)]
        if prior.empty:
            return ""
        v = (last / float(prior.iloc[-1]) - 1) * 100
    elif how == "diff":
        v = last - prev
    elif how == "level_k":
        v = last / 1000
    else:
        v = last
    out = fmt.format(v)
    return "0.0%" if out == "-0.0%" else out


def calendar_view(symbol=None, currencies: list[str] | None = None, impacts: list[str] | None = None,
                  range_: str = "today", tz_name: str | None = None, data=None, ff_fetch=fetch_ff,
                  now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    lo, hi = window(range_, now, tz_name)
    impacts = [i for i in (impacts or IMPACTS) if i in IMPACTS] or list(IMPACTS)
    notes: list[str] = []
    days_back = max(1, (now - lo).days + 1)
    events = get_calendar(None, days_back=days_back, days_ahead=14, data=data, ff_fetch=ff_fetch, now=now)
    feed_ok = any(e.source == "forexfactory" for e in events)
    if not feed_ok:
        notes.append("The ForexFactory calendar feed is unavailable: showing US release dates (FRED) and central-bank "
                     "meetings (config/events.yaml) at their usual release times, so times are approximate.")

    sym_cur = symbol_currencies(symbol) if symbol is not None else []
    focus = sym_cur or (currencies or [])
    nxt = next_major(events, focus, now) if focus else next((e for e in events if e.major and e.time > now
                                                             and e.impact != "holiday"), None)
    if feed_ok:
        covered = max(e.time for e in events if e.source == "forexfactory")
        if hi > covered + timedelta(days=1):
            notes.append("ForexFactory has not published next week's list yet: events after "
                         f"{covered.date().isoformat()} are missing for now.")
    if nxt is None and feed_ok:
        # Beyond the feed: the next known release / central-bank meeting (FRED + events.yaml), approximate time.
        try:
            later = [e for e in fallback_events(data, focus or ["USD", "EUR", "GBP", "JPY"], 30)
                     if e.major and e.time > now and (not focus or e.currency in focus)]
            nxt = min(later, key=lambda e: e.time) if later else None
        except Exception as ex:
            log.info("No fallback next event: %s", ex)
    cur = {c.upper() for c in currencies} if currencies else None
    fred_errors: list[str] = []
    rows = []
    for e in events:
        if not (lo <= e.time < hi):
            continue
        if cur and e.currency not in cur and e.currency != "All":
            continue
        if e.impact not in impacts:
            continue
        actual, actual_source = e.actual, ("forexfactory" if e.actual else "")
        if not actual and e.time <= now and e.currency == "USD":
            try:
                actual = fred_actual(e, data)
                actual_source = "FRED" if actual else ""
            except Exception as ex:  # no FRED key, offline, unknown series
                fred_errors.append(str(ex))
        rule = classify(e.title, e.impact)
        row = e.as_dict()
        row.update(actual=actual, actual_source=actual_source, past=e.time <= now,
                   type=rule.type if rule else "other", plain_title=plain_title(e.title, e.currency, e.impact),
                   surprise=surprise(actual, e.forecast) if actual else None,
                   affects_symbol=bool(symbol is not None and e.currency in sym_cur),
                   meaning=meaning(e.title, e.currency, symbol, e.impact, actual, e.forecast) if symbol is not None else "")
        rows.append(row)
    if fred_errors:
        notes.append("Actual numbers for US releases come from FRED and are unavailable right now "
                     f"({fred_errors[0]}). Set FRED_API_KEY in .env to fill them in.")
    nxt_d = None
    if nxt is not None:
        nxt_d = nxt.as_dict()
        nxt_d["plain_title"] = plain_title(nxt.title, nxt.currency, nxt.impact)
        if symbol is not None:
            nxt_d["meaning"] = meaning(nxt.title, nxt.currency, symbol, nxt.impact)
    return {
        "range": range_, "range_start": lo, "range_end": hi, "tz": tz_name or "UTC", "now": now,
        "events": rows, "next_major": nxt_d, "focus_currencies": focus,
        "source": "ForexFactory weekly feed" if feed_ok else "Fallback (FRED + events.yaml, approximate times)",
        "feed_ok": feed_ok, "notes": notes,
    }
