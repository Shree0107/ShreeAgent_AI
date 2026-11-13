"""Upcoming events that can move a symbol, in plain words, with how close they are.

Sources: FRED US release dates + config/events.yaml central-bank meetings (via DataService), and the
next earnings date for stocks. Only MAJOR events can force a WAIT; the rest only show a warning.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from data.symbols import Symbol

log = logging.getLogger(__name__)

# Title fragment -> beginner wording. Order matters (first match wins).
PLAIN_NAMES = [
    ("CPI", "inflation report"),
    ("Non-Farm", "jobs report"),
    ("FOMC", "Federal Reserve interest-rate decision"),
    ("ECB", "European Central Bank interest-rate decision"),
    ("BoE", "Bank of England interest-rate decision"),
    ("BoJ", "Bank of Japan interest-rate decision"),
    ("RBI", "Reserve Bank of India interest-rate decision"),
    ("PCE", "spending & inflation (PCE) report"),
    ("GDP", "economic growth (GDP) report"),
    ("Retail Sales", "retail sales report"),
    ("PPI", "producer prices report"),
    ("JOLTS", "job openings report"),
]
# Events that move prices sharply enough to justify waiting.
MAJOR_KEYWORDS = ("CPI", "Non-Farm", "FOMC", "ECB", "BoE", "BoJ", "RBI", "rate decision", "policy decision", "Earnings")
COUNTRY = {"USD": "US", "EUR": "Eurozone", "GBP": "UK", "JPY": "Japan", "INR": "India", "CHF": "Swiss",
           "AUD": "Australian", "NZD": "New Zealand", "CAD": "Canadian"}
HOME_CURRENCY = {"US": "USD", "NSE": "INR", "BSE": "INR"}


@dataclass
class UpcomingEvent:
    date: str          # YYYY-MM-DD
    title: str         # original title
    plain: str         # beginner wording, e.g. "US inflation report"
    currency: str
    major: bool
    days_away: int     # 0 = today

    def as_dict(self) -> dict:
        return asdict(self)


def plain_title(title: str, currency: str) -> str:
    for frag, words in PLAIN_NAMES:
        if frag.lower() in title.lower():
            if "decision" in words:  # central-bank names already say which country
                return words[0].upper() + words[1:]
            return f"{COUNTRY.get(currency, currency)} {words}"
    return title


def is_major(title: str) -> bool:
    return any(k.lower() in title.lower() for k in MAJOR_KEYWORDS)


def symbol_events(symbol: Symbol, data, next_earnings: str | None = None, days: int = 14,
                  today: date | None = None) -> list[UpcomingEvent]:
    today = today or datetime.now(timezone.utc).date()
    if symbol.is_fx:
        currencies = [c for c in (symbol.base, symbol.quote) if c not in ("XAU", "XAG")]
        if symbol.base in ("XAU", "XAG") and "USD" not in currencies:
            currencies.append("USD")
    else:
        currencies = [HOME_CURRENCY[symbol.market]] if symbol.market in HOME_CURRENCY else []
    out: list[UpcomingEvent] = []
    if currencies:
        try:
            for e in data.upcoming_events(currencies, days):
                d = e.date.date() if isinstance(e.date, datetime) else e.date
                gap = (d - today).days
                if gap >= 0:
                    out.append(UpcomingEvent(d.isoformat(), e.title, plain_title(e.title, e.currency), e.currency,
                                             is_major(e.title) or (e.impact == "high" and "decision" in e.title.lower()), gap))
        except Exception as e:
            log.info("Event calendar unavailable for %s: %s", symbol.ticker, e)
    if next_earnings:
        try:
            d = date.fromisoformat(str(next_earnings)[:10])
            gap = (d - today).days
            if 0 <= gap <= max(days, 30):
                out.append(UpcomingEvent(d.isoformat(), "Earnings", "Company earnings report", "", True, gap))
        except ValueError:
            pass
    return sorted(out, key=lambda e: (e.days_away, not e.major))


def blocking_event(events: list[UpcomingEvent], blackout_days: int, earnings_blackout_days: int) -> UpcomingEvent | None:
    """The first major event close enough to justify WAIT, if any."""
    for e in events:
        limit = earnings_blackout_days if e.title == "Earnings" else blackout_days
        if e.major and e.days_away <= limit:
            return e
    return None
