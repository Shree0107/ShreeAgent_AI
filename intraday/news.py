"""News filter: no new signals NEWS_BLACKOUT_MINUTES before and after high-impact news for the symbol's currencies.

Events come from data/providers/calendar.get_calendar (ForexFactory feed with exact times, fallback table).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from data.providers.calendar import blackout, get_calendar, next_major
from data.symbols import Symbol
from intraday.config import IntradayConfig
from intraday.sessions import fmt_local

log = logging.getLogger(__name__)


def currencies(symbol: Symbol) -> list[str]:
    if symbol.is_fx:
        return [symbol.base if symbol.base not in ("XAU", "XAG") else "USD", symbol.quote]
    if symbol.market in ("NSE", "BSE"):
        return ["INR"]
    if symbol.market in ("US", "", None):
        return ["USD"]
    return {"DE": ["EUR"], "PA": ["EUR"], "AS": ["EUR"], "MI": ["EUR"], "L": ["GBP"], "T": ["JPY"]}.get(symbol.market, ["USD"])


def load_events(symbol: Symbol, now: datetime, data=None, fetch=None) -> list:
    try:
        kw = {"ff_fetch": fetch} if fetch is not None else {}
        return get_calendar(currencies(symbol), days_back=1, days_ahead=2, data=data, now=now, **kw)
    except Exception as e:  # calendar unavailable: the card says so in the details
        log.info("Calendar unavailable for %s: %s", symbol.ticker, e)
        return []


def news_check(events: list, symbol: Symbol, now: datetime, cfg: IntradayConfig) -> dict:
    """{'blocked': event dict | None, 'warning': plain text | None, 'next': event dict | None, 'text': ...}"""
    cur = currencies(symbol)
    b = blackout(events, cur, now, cfg.blackout_minutes)
    nxt = next_major(events, cur, now)
    win = timedelta(minutes=cfg.blackout_minutes)
    out = {"blocked": b.as_dict() if b else None, "next": nxt.as_dict() if nxt else None, "warning": None,
           "block_text": None}
    if b:
        out["block_text"] = (f"Important news: {b.title} ({b.currency}) at {fmt_local(b.time, cfg)}. No new trades from "
                             f"{fmt_local(b.time - win, cfg)} to {fmt_local(b.time + win, cfg)} – prices can jump wildly.")
        out["warning"] = out["block_text"]
    elif nxt and nxt.time - now <= timedelta(hours=6):
        out["warning"] = (f"{nxt.title} ({nxt.currency}) at {fmt_local(nxt.time, cfg)} – no new trades "
                          f"{fmt_local(nxt.time - win, cfg)}–{fmt_local(nxt.time + win, cfg)}.")
    return out
