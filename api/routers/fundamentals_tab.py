"""Fundamentals tab endpoints (platform phase 8), prefix /api/fund.

Each section has its own endpoint, so one failing source never breaks the rest of the tab.
Tests override `get_data`, `get_ff_fetch` and `get_now` (no network, fixed clock).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_data, symbol_or_404
from api.serialize import clean

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fund", tags=["fundamentals-tab"])


def get_ff_fetch():
    from data.providers.calendar import fetch_ff

    return fetch_ff


def get_now() -> datetime:
    return datetime.now(timezone.utc)


def get_llm():
    """None = use the configured LLM (if any). Tests override with a fake provider."""
    return None


def _csv(text: str | None) -> list[str]:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


@router.get("/calendar")
def calendar(symbol: str | None = None, currencies: str | None = None, impact: str | None = None,
             range: str = Query("today", pattern="^(today|week)$"), tz: str | None = None,
             data=Depends(get_data), ff_fetch=Depends(get_ff_fetch), now=Depends(get_now)):
    from analysis.fundtab.calendar_view import calendar_view

    sym = symbol_or_404(symbol) if symbol else None
    try:
        return clean(calendar_view(sym, [c.upper() for c in _csv(currencies)] or None,
                                   [i.lower() for i in _csv(impact)] or None, range, tz, data=data,
                                   ff_fetch=ff_fetch, now=now))
    except Exception as e:
        log.warning("Calendar failed: %s", e)
        raise HTTPException(502, f"Calendar unavailable: {e}") from e


@router.get("/central-banks")
def central_banks(data=Depends(get_data), ff_fetch=Depends(get_ff_fetch), now=Depends(get_now)):
    from analysis.fundtab.central_banks import central_banks as cb
    from data.providers.calendar import get_calendar

    try:
        events = get_calendar(None, days_back=0, days_ahead=14, data=data, ff_fetch=ff_fetch, now=now)
    except Exception as e:  # meeting dates then come from events.yaml only
        log.info("Calendar for central banks unavailable: %s", e)
        events = []
    try:
        return clean(cb(data, events, now=now))
    except Exception as e:
        raise HTTPException(502, f"Central-bank data unavailable: {e}") from e


@router.get("/strength")
def strength(tf: str = Query("1d", pattern="^(1h|4h|1d)$"), data=Depends(get_data), now=Depends(get_now)):
    from analysis.fundtab.strength import currency_strength

    try:
        return clean(currency_strength(data, tf, now=now))
    except Exception as e:
        raise HTTPException(502, f"Currency strength unavailable: {e}") from e


@router.get("/news")
def news(symbol: str, days: int = Query(7, ge=1, le=30), data=Depends(get_data)):
    from analysis.fundtab.news_view import news_feed

    sym = symbol_or_404(symbol)
    try:
        return clean(news_feed(sym, data, days))
    except Exception as e:
        raise HTTPException(502, f"News unavailable: {e}") from e


@router.get("/news-summary")
def news_summary(symbol: str, days: int = Query(7, ge=1, le=30), data=Depends(get_data), llm=Depends(get_llm)):
    """AI one-liners for the same headlines /news returns (cached a day, optional, number-guarded)."""
    from analysis.fundtab.news_view import news_feed, summarise

    sym = symbol_or_404(symbol)
    try:
        feed = news_feed(sym, data, days)
    except Exception as e:
        raise HTTPException(502, f"News unavailable: {e}") from e
    titles = [h["title"] for h in feed["headlines"]]
    res = summarise(sym.ticker, titles, provider=llm)
    return clean({"symbol": sym.ticker, **res, "items": [{"title": t, "summary": s} for t, s in
                                                          zip(titles, res["summaries"] or [None] * len(titles))]})


@router.get("/bias")
def bias(symbol: str, data=Depends(get_data)):
    from analysis.fundtab.bias import fundamental_bias

    sym = symbol_or_404(symbol)
    try:
        return clean(fundamental_bias(sym, data))
    except Exception as e:
        raise HTTPException(502, f"Fundamental bias unavailable: {e}") from e


@router.get("/stock")
def stock(symbol: str, data=Depends(get_data)):
    from analysis.fundtab.bias import stock_view

    sym = symbol_or_404(symbol)
    if sym.is_fx:
        raise HTTPException(400, "Key company numbers are only for stocks.")
    try:
        out = stock_view(sym, data)
        out.pop("_rep", None)
        return clean(out)
    except Exception as e:
        raise HTTPException(502, f"Company numbers unavailable: {e}") from e
