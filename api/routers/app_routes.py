"""Watchlist, settings, jobs, agent chat, report export, watchlist scan."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.deps import get_data, get_watchlist, symbol_or_404
from api.serialize import clean
from config.settings import get_settings

router = APIRouter(prefix="/api", tags=["app"])


# ---------------- watchlist ----------------
@router.get("/watchlist")
def watchlist(wl=Depends(get_watchlist)):
    return wl.symbols()


class AddSymbol(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)


@router.post("/watchlist")
def watchlist_add(body: AddSymbol, wl=Depends(get_watchlist)):
    wl.add(symbol_or_404(body.symbol).ticker)
    return wl.symbols()


@router.delete("/watchlist")
def watchlist_remove(symbol: str, wl=Depends(get_watchlist)):
    wl.remove(symbol)
    return wl.symbols()


# ---------------- settings & status ----------------
@router.get("/settings")
def public_settings():
    """Non-secret settings the UI needs. API keys are reported only as configured / not configured."""
    s = get_settings()
    return {
        "account": {"size": s.account_size, "currency": s.account_currency, "risk_pct": s.risk_per_trade_pct,
                    "leverage": s.leverage, "lot_size": s.fx_lot_size, "min_lot": s.fx_min_lot},
        "signals": {"timeframe": s.signal_timeframe, "min_rr": s.signal_min_rr, "min_confidence": s.signal_min_confidence,
                    "refresh_minutes": s.signal_refresh_minutes, "expiry_bars": s.signal_expiry_bars},
        "configured": {"claude": bool(s.anthropic_api_key), "fred": bool(s.fred_api_key),
                       "finnhub": bool(s.finnhub_api_key), "marketaux": bool(s.marketaux_api_key),
                       "twelvedata": bool(s.twelvedata_api_key), "whatsapp": s.whatsapp_backend != "none"},
        "models": {"chat": s.llm_model, "deep": s.llm_deep_model, "forecast": s.forecast_model},
    }


@router.get("/jobs/{job_id}")
def job(request: Request, job_id: str):
    j = request.app.state.jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Unknown or expired job")
    return j.public()


# ---------------- agent chat ----------------
class Turn(BaseModel):
    role: str
    content: str


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[Turn] = []
    deep: bool = False


@router.post("/agent/ask")
def agent_ask(body: AskBody):
    from agent.agent import TradingAgent

    try:
        res = TradingAgent().ask(body.question, [t.model_dump() for t in body.history], deep=body.deep)
    except Exception as e:
        raise HTTPException(502, str(e)) from e
    return clean({"text": res.text, "model": res.model, "tool_calls": [{"name": c.name, "input": c.input, "ok": c.ok}
                                                                        for c in res.tool_calls]})


# ---------------- report ----------------
@router.get("/report")
def report(symbol: str, tf: str = "1d", horizon: int = 10, forecast: bool = True, format: str = "md",
           data=Depends(get_data)):
    from agent.report import analysis_to_markdown, markdown_to_pdf
    from analysis.combined import full_analysis
    from signals.service import attach_signal

    sym = symbol_or_404(symbol)
    try:
        md = analysis_to_markdown(attach_signal(sym, full_analysis(sym, tf, horizon, include_forecast=forecast, data=data),
                                                data=data))
    except Exception as e:
        raise HTTPException(502, f"Report failed: {e}") from e
    name = f"{sym.plain}_report"
    if format == "pdf":
        return Response(markdown_to_pdf(md), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    return Response(md, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.md"'})


# ---------------- watchlist scan (WhatsApp digest) ----------------
@router.post("/scan")
def scan(request: Request, send: bool = False):
    def work():
        from alerts.scanner import format_digest
        from alerts.scanner import scan as run_scan

        rows = run_scan()
        digest = format_digest(rows)
        sent = None
        if send:
            from alerts.whatsapp import get_notifier

            sent = get_notifier().send(digest)
        return {"rows": [r.__dict__ for r in rows], "digest": digest, "sent": sent}

    return request.app.state.jobs.submit("scan", f"scan:{send}", work).public(with_result=False)
