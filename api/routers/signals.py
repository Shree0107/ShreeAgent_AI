"""Beginner signal cards (daily swing mode, signals/). Intraday cards join in a later phase.

GET returns the stored cards immediately (never blocks on TimesFM). Stale or missing cards trigger a
background refresh job; the UI shows the stored card greyed out with its age until the job finishes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request

from api.deps import get_data, get_history, get_watchlist, symbol_or_404
from api.serialize import clean
from config.settings import get_settings

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _sized(card: dict, account: float | None, risk: float | None, ccy: str | None, data) -> dict:
    from signals.service import with_sizing

    s = get_settings()
    if card.get("action") not in ("BUY", "SELL"):
        return card
    try:
        return with_sizing(card, account or s.account_size, risk or s.risk_per_trade_pct,
                           (ccy or s.account_currency).upper(), data=data)
    except Exception as e:
        return {**card, "size_error": str(e)}


def _refresh(request: Request, symbols: list[str], force: bool, data, history):
    from signals.service import watchlist_signals

    return request.app.state.jobs.submit(
        "signals", f"signals:{','.join(symbols)}:{force}",
        lambda: watchlist_signals(symbols, force=force, data=data, history=history))


@router.get("")
def list_signals(request: Request, account: float | None = Query(None, gt=0), risk: float | None = Query(None, gt=0, le=10),
                 ccy: str | None = None, symbols: str | None = None, data=Depends(get_data),
                 history=Depends(get_history), wl=Depends(get_watchlist)):
    from signals.service import is_fresh, sort_cards

    s = get_settings()
    syms = [x.strip() for x in symbols.split(",")] if symbols else wl.symbols()
    now = datetime.now(timezone.utc)
    cards, stale = [], []
    for tk in syms:
        try:
            sym = symbol_or_404(tk)
        except Exception as e:
            cards.append({"symbol": tk, "action": "ERROR", "error": str(e), "strength": -1})
            continue
        c = history.latest(sym.ticker)
        if not is_fresh(c, now, s.signal_refresh_minutes):
            stale.append(sym.ticker)
        if c:
            c = _sized(c, account, risk, ccy, data)
            c["stale"] = sym.ticker in stale
            cards.append(c)
        else:
            cards.append({"symbol": sym.ticker, "action": "PENDING", "strength": -0.5,
                          "message": "Analysing for the first time…"})
    job = _refresh(request, stale, False, data, history).public(with_result=False) if stale else None
    return clean({"cards": sort_cards(cards), "refresh_job": job, "generated_at": now.isoformat(),
                  "win_rates": history.win_rates()})


@router.post("/refresh")
def refresh(request: Request, symbols: str | None = None, data=Depends(get_data), history=Depends(get_history),
            wl=Depends(get_watchlist)):
    syms = [x.strip() for x in symbols.split(",")] if symbols else wl.symbols()
    return _refresh(request, syms, True, data, history).public(with_result=False)


@router.get("/history")
def signal_history(symbol: str | None = None, limit: int = Query(300, le=5000), history=Depends(get_history)):
    return clean({"history": history.history(symbol, limit), "win_rates": history.win_rates()})
