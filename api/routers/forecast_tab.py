"""Forecast tab (phase 9): cached TimesFM forecasts per timeframe, model-vs-baselines verdict, live accuracy and
agreement with the trade plan.

GET /api/forecast/live returns the stored forecast immediately with its age and never runs the model itself:
when a newer candle has closed it starts (or joins) a background job; the UI refetches when that job finishes
(bus topics "job" and "forecast:{SYM}:{TF}") or by polling.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.deps import get_data, symbol_or_404
from api.serialize import clean

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/forecast", tags=["forecast"])


def get_forecast_store():
    from forecasting.accuracy import get_store

    return get_store()


def _scheduler(request: Request, store):
    from forecasting.live import ForecastScheduler

    sched = getattr(request.app.state, "forecast_scheduler", None)
    if sched is None or sched.store is not store:
        from api.bus import get_bus

        sched = ForecastScheduler(request.app.state.jobs, store=store, bus=get_bus())
        request.app.state.forecast_scheduler = sched
    return sched


def _tf(tf: str) -> str:
    from forecasting.live import TAB_TIMEFRAMES

    if tf not in TAB_TIMEFRAMES:
        raise HTTPException(400, f"timeframe must be one of {list(TAB_TIMEFRAMES)}")
    return tf


def _units(sym):
    from signals.market import pip_size

    pip = pip_size(sym)
    return pip, ("pips" if pip else "%")


def _to_units(x: float | None, pip: float | None, price: float) -> float | None:
    if x is None:
        return None
    return round(x / pip, 1) if pip else round(x / price * 100, 3)


def _check_view(check: dict | None, sym, tf: str, price: float) -> dict:
    from forecasting.baselines import LABELS
    from forecasting.explain import verdict

    bt = (check or {}).get("chosen")
    v = verdict(bt, sym.ticker, tf)
    if not bt:
        return {**v, "table": [], "run_at": None}
    pip, units = _units(sym)
    rows = [{"name": "model", "label": f"Model ({bt['model']})", "error": _to_units(bt["mae"], pip, price),
             "direction_pct": bt.get("directional_accuracy")}]
    for name, b in (bt.get("baselines") or {"naive": {"mae": bt["naive_mae"], "directional_accuracy": None}}).items():
        rows.append({"name": name, "label": LABELS.get(name, name), "error": _to_units(b["mae"], pip, price),
                     # "no change" never predicts a direction, so a hit rate means nothing for it
                     "direction_pct": None if name == "naive" else b.get("directional_accuracy")})
    uni, multi = check.get("univariate"), check.get("multivariate")
    return {**v, "table": rows, "units": units, "n_windows": bt["n_windows"], "run_at": check["run_at"],
            "coverage_50": bt.get("coverage_50"), "coverage_80": bt.get("coverage_80"),
            "skill_vs_naive": bt.get("skill_vs_naive"),
            "multivariate": {"tested": bool(check.get("multi_tested")), "used": bool(check.get("use_multi")),
                             "variates_tested": (multi or {}).get("variates"),
                             "error_own_prices": _to_units(uni["mae"], pip, price) if uni else None,
                             "error_with_extras": _to_units(multi["mae"], pip, price) if multi else None}}


def _summary_fmt(sym):
    """Prices in sentences: forex to the pip (1.0912), like most apps quote ranges; stocks as usual."""
    import math

    from signals.market import fmt_price, pip_size

    pip = pip_size(sym)
    if pip:
        d = max(0, round(-math.log10(pip)))
        return lambda x: f"{x:,.{d}f}"
    return lambda x: fmt_price(sym, x)


def _forecast_view(rec: dict, sym, tf: str) -> dict:
    from forecasting.accuracy import bands
    from forecasting.explain import direction, summary_sentence
    b = {k: [round(float(x), 6) for x in v] for k, v in bands(rec["quantiles"]).items()}
    last = rec["last_close"]
    code, words = direction(last, rec["median"][-1], b["q10"][-1], b["q90"][-1], rec["prob_up"])
    text = summary_sentence(sym.ticker, tf, rec["horizon"], last, rec["median"][-1], b["q10"][-1], b["q25"][-1],
                            b["q75"][-1], b["q90"][-1], rec["prob_up"], _summary_fmt(sym))
    return {
        "made_at": rec["made_at"], "last_bar_time": rec["last_bar_time"], "last_close": last, "model": rec["model"],
        "variates": rec["variates"], "dates": rec["dates"], "median": rec["median"], **b,
        "prob_up": rec["prob_up"], "expected_change_pct": round((rec["median"][-1] / last - 1) * 100, 3),
        "baselines": rec.get("baselines") or {}, "direction": code, "direction_words": words, "summary": text,
    }


@router.get("/live")
def live_forecast(request: Request, symbol: str, tf: str = "1h", data=Depends(get_data),
                  store=Depends(get_forecast_store)):
    from datetime import datetime, timezone

    from forecasting.explain import horizon_text, variates_text
    from forecasting.live import horizon_for, is_stale, load_check, next_close

    tf = _tf(tf)
    sym = symbol_or_404(symbol)
    h = horizon_for(tf)
    sched = _scheduler(request, store)
    sched.watch(sym.ticker, tf)
    job = sched.maybe_refresh(sym, tf, data=data)
    rec = store.latest(sym.ticker, tf, h)
    now = datetime.now(timezone.utc)
    check = load_check(sym.ticker, tf, h)
    out = {"symbol": sym.ticker, "tf": tf, "horizon": h, "horizon_text": horizon_text(tf, h),
           "now": now.isoformat(timespec="seconds"), "forecast": None, "stale": True, "age_s": None,
           "next_update_at": None, "refresh_job": job.public(with_result=False) if job else None}
    if rec:
        fv = _forecast_view(rec, sym, tf)
        out.update({
            "forecast": fv, "stale": is_stale(rec, now, tf),
            "age_s": round((now - datetime.fromisoformat(rec["made_at"])).total_seconds()),
            "next_update_at": next_close(rec["last_bar_time"], tf).isoformat(),
            "variates_text": variates_text(check, rec["variates"]),
        })
        out["check"] = _check_view(check, sym, tf, rec["last_close"])
    else:
        out["check"] = _check_view(check, sym, tf, 1.0) if check else None
    last_job = sched.jobs.latest(sched.key(sym.ticker, tf, h))
    if last_job and last_job.status == "error":
        out["last_error"] = last_job.error
    return clean(out)


@router.post("/live/refresh")
def refresh_live(request: Request, symbol: str, tf: str = "1h", data=Depends(get_data),
                 store=Depends(get_forecast_store)):
    tf = _tf(tf)
    sym = symbol_or_404(symbol)
    return _scheduler(request, store).maybe_refresh(sym, tf, data=data, force=True).public(with_result=False)


@router.get("/accuracy")
def accuracy(symbol: str, tf: str = "1h", limit: int = Query(20, ge=1, le=200), store=Depends(get_forecast_store)):
    from forecasting.accuracy import summarize
    from forecasting.explain import accuracy_text
    from forecasting.live import horizon_for

    tf = _tf(tf)
    sym = symbol_or_404(symbol)
    pip, units = _units(sym)
    h = horizon_for(tf)
    rows = store.recent_scored(sym.ticker, tf, h, limit=max(limit, 50))
    stats = summarize(rows, pip)
    recent = []
    for r in rows[:limit]:
        pred_end, act_end, last = r["median"][-1], r["actual"][-1], r["last_close"]
        sign = lambda x: "up" if x > 0 else "down" if x < 0 else "flat"
        recent.append({
            "made_at": r["made_at"], "last_bar_time": r["last_bar_time"], "last_close": last,
            "predicted_end": pred_end, "actual_end": act_end,
            "predicted_dir": sign(pred_end - last), "actual_dir": sign(act_end - last),
            "dir_correct": r["dir_correct"], "error": _to_units(r["mae"], pip, last),
            "end_in50": r["end_in50"], "end_in80": r["end_in80"],
        })
    return clean({"symbol": sym.ticker, "tf": tf, "horizon": h, "units": units, "stats": stats,
                  "text": accuracy_text(stats, sym.ticker, tf), "recent": recent})


async def _plan_card(request: Request, ticker: str) -> dict | None:
    """The intraday plan card (GET /api/plans, if that phase is installed), else the daily signal card."""
    import httpx

    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://internal", timeout=20) as c:
        for path, source in (("/api/plans", "intraday"), ("/api/signals", "daily")):
            try:
                r = await c.get(path, params={"symbols": ticker})
                if r.status_code != 200:
                    continue
                cards = r.json().get("cards") or []
            except Exception as e:
                log.info("Plan lookup %s failed: %s", path, e)
                continue
            card = next((x for x in cards if x.get("symbol") == ticker), None)
            if card and card.get("action") in ("BUY", "SELL", "WAIT"):
                return {"source": source, **card}
    return None


@router.get("/agreement")
async def agreement(request: Request, symbol: str, tf: str = "1h"):
    from fastapi.concurrency import run_in_threadpool

    from forecasting.explain import agreement as agree
    from forecasting.live import horizon_for

    tf = _tf(tf)
    sym = symbol_or_404(symbol)
    store = request.app.dependency_overrides.get(get_forecast_store, get_forecast_store)()
    rec = await run_in_threadpool(store.latest, sym.ticker, tf, horizon_for(tf))
    fc_dir = _forecast_view(rec, sym, tf)["direction"] if rec else None
    plan = await _plan_card(request, sym.ticker)
    res = agree(fc_dir, plan)
    p = None
    if plan:
        p = {k: plan.get(k) for k in ("source", "action", "direction", "state", "entry", "stop", "target1",
                                       "generated_at", "stale")}
    return clean({**res, "forecast_direction": fc_dir, "plan": p})
