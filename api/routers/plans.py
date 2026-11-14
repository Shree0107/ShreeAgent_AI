"""Intraday trade plans (15-minute engine, intraday/). The daily swing cards stay at /api/signals.

GET /api/plans?symbols=A,B&account=&risk=&ccy=   stored cards at once; missing/stale ones refresh in a background job
    -> {"cards": [card...], "generated_at", "refresh_job", "config", "account"}
GET /api/plans/history?symbol=&limit=             stored plans with outcomes (+ per-setup live stats)
GET /api/plans/events?symbol=&limit=              status-change events (get_ready, entry_triggered, tp_hit, ...)
POST /api/plans/refresh?symbols=                  force a re-run (background job)
Live updates: WebSocket topics plan:{SYM} (card) and plan_event.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from api.deps import get_watchlist, symbol_or_404
from api.serialize import clean
from config.settings import get_settings

router = APIRouter(prefix="/api/plans", tags=["plans"])
_service = None


def get_plan_service():
    """One PlanService per process (tests override this dependency with an offline one)."""
    global _service
    if _service is None:
        from api.bus import get_bus
        from intraday.service import PlanService

        _service = PlanService(bus=get_bus())
    return _service


def _syms(symbols: str | None, wl) -> list[str]:
    return [x.strip() for x in symbols.split(",") if x.strip()] if symbols else wl.symbols()


def _refresh(request: Request, svc, symbols: list[str]):
    return request.app.state.jobs.submit("plans", f"plans:{','.join(symbols)}", lambda: svc.refresh(symbols))


@router.get("")
def list_plans(request: Request, symbols: str | None = None, account: float | None = Query(None, gt=0),
               risk: float | None = Query(None, gt=0, le=10), ccy: str | None = None,
               svc=Depends(get_plan_service), wl=Depends(get_watchlist)):
    from intraday.explain import with_size

    s = get_settings()
    now = svc.clock()          # the service's clock (real time in production, fixed in tests)
    acct, rk, cur = account or s.account_size, risk or s.risk_per_trade_pct, (ccy or s.account_currency).upper()
    tickers, bad = [], []
    for tk in _syms(symbols, wl):
        try:
            tickers.append(symbol_or_404(tk).ticker)
        except Exception as e:
            bad.append({"symbol": tk, "action": "WAIT", "state": "waiting", "error": str(e), "strength": -1,
                        "stale": True, "explanation": {"headline": str(e)}})
    cards, todo = svc.cards(tickers, now)
    out = []
    for c in cards:
        if c.get("action") in ("BUY", "SELL"):
            try:
                c = with_size(c, acct, rk, cur, symbol_or_404(c["symbol"]), data=svc.data)
            except Exception as e:
                c = {**c, "size": None, "size_error": str(e)}
        out.append(c)
    job = _refresh(request, svc, todo).public(with_result=False) if todo else None
    out.sort(key=lambda c: -(c.get("strength") or 0))
    return clean({"cards": out + bad, "generated_at": now.isoformat(), "refresh_job": job,
                  "config": svc.cfg.as_dict(), "account": {"size": acct, "risk_pct": rk, "currency": cur}})


@router.post("/refresh")
def refresh(request: Request, symbols: str | None = None, svc=Depends(get_plan_service), wl=Depends(get_watchlist)):
    return _refresh(request, svc, [symbol_or_404(t).ticker for t in _syms(symbols, wl)]).public(with_result=False)


@router.get("/history")
def plan_history(symbol: str | None = None, limit: int = Query(200, ge=1, le=5000), svc=Depends(get_plan_service)):
    return clean({"plans": svc.store.history(symbol, limit), "stats": svc.store.stats()})


@router.get("/events")
def plan_events(symbol: str | None = None, limit: int = Query(100, ge=1, le=1000), svc=Depends(get_plan_service)):
    return clean({"events": svc.store.events(symbol, limit)})
