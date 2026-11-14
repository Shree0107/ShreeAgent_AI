"""Performance tab (phase 7): intraday backtest results and live tracking of the Trade Plan outcomes.

GET  /api/performance/summary?symbol=            per setup x symbol x session table, plain-words lines,
                                                  switched-off setups and why (from the last backtest run)
GET  /api/performance/equity?symbol=             backtest equity curve (out-of-sample trades) + live equity curve
GET  /api/performance/live-vs-backtest?symbol=   live win rate / profit factor / average pips vs the range the
                                                  backtest expected (90% binomial band) + a plain sentence
POST /api/performance/run?symbol=&setups=&months=  start a backtest in the background (one job per symbol)
GET  /api/performance/run?symbol=                 that job's status and progress
Backtests never run inside a request: they take minutes (the engine is replayed candle by candle).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request

from api.deps import symbol_or_404
from api.routers.plans import get_plan_service
from api.serialize import clean
from intraday import walkforward
from intraday.bt_stats import binom_band
from intraday.setups import SETUP_NAME

router = APIRouter(prefix="/api/performance", tags=["performance"])
TRADE_OUTCOMES = ("tp1_hit", "tp2_hit", "sl_hit", "breakeven", "time_stop")
EMPTY_TEXT = ("No backtest yet – click Run backtest. With Yahoo data only about 60 days of 5-minute history is "
              "available, so the results are a rough guide.")
_progress: dict[str, dict] = {}
_lock = threading.Lock()


def get_backtest_base() -> Path | None:
    """Folder of the result files (None = the default {user_data_dir}/intraday_backtests). Tests override this."""
    return None


def runner():
    """The backtest function (tests replace it with a fast fake)."""
    return walkforward.run_backtest


def _runs(base, symbol: str | None) -> list[dict]:
    runs = walkforward.all_runs(base)
    if symbol:
        runs = [r for r in runs if r.get("symbol") == symbol]
    return sorted(runs, key=lambda r: r.get("symbol", ""))


def _run_info(r: dict) -> dict:
    keep = ("symbol", "generated_at", "method", "method_text", "out_of_sample", "period", "period_text", "months",
            "costs", "rules", "grid", "windows", "setups", "decisions", "cards_built", "overall", "notes",
            "elapsed_s", "data")
    return {k: r.get(k) for k in keep}


@router.get("/summary")
def summary(symbol: str | None = None, base=Depends(get_backtest_base)):
    sym = symbol_or_404(symbol).ticker if symbol else None
    runs = _runs(base, sym)
    rows, lines, disabled = [], [], []
    for r in runs:
        rows += r.get("rows") or []
        lines += r.get("lines") or []
        disabled += r.get("disabled") or []
    return clean({"has_backtest": bool(runs), "empty_text": EMPTY_TEXT if not runs else None,
                  "runs": [_run_info(r) for r in runs], "rows": rows, "lines": lines, "disabled": disabled})


def _live_trades(store, symbol: str | None) -> list[dict]:
    rows = [r for r in store.history(symbol, limit=100_000)
            if r.get("outcome") in TRADE_OUTCOMES and r.get("triggered_at") and r.get("pips") is not None]
    return sorted(rows, key=lambda r: r.get("closed_at") or "")


@router.get("/equity")
def equity(symbol: str | None = None, base=Depends(get_backtest_base), svc=Depends(get_plan_service)):
    sym = symbol_or_404(symbol).ticker if symbol else None
    bt = {}
    for r in _runs(base, sym):
        bt[r["symbol"]] = r.get("equity") or []
    live, cum = [], 0.0
    for t in _live_trades(svc.store, sym):
        cum += float(t["pips"])
        live.append({"t": t["closed_at"], "pips": round(cum, 2), "setup": t["setup_type"], "symbol": t["symbol"]})
    return clean({"backtest": bt, "live": live})


def _live_stats(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0, "wins": 0, "win_rate": None, "profit_factor": None, "avg_pips": None, "total_pips": 0.0}
    pips = [float(t["pips"]) for t in trades]
    wins = sum(1 for t in trades if t["outcome"] in ("tp1_hit", "tp2_hit"))
    gp, gl = sum(p for p in pips if p > 0), -sum(p for p in pips if p < 0)
    return {"trades": n, "wins": wins, "win_rate": round(wins / n, 4),
            "profit_factor": round(gp / gl, 3) if gl > 0 else (None if gp == 0 else 99.0),
            "avg_pips": round(sum(pips) / n, 2), "total_pips": round(sum(pips), 2)}


def compare(live: dict, bt_rate: float | None, bt_trades: int, bt_avg: float | None, level: float = 0.90) -> dict:
    n = live["trades"]
    out = {"live": live, "backtest": {"win_rate": bt_rate, "trades": bt_trades, "avg_pips": bt_avg},
           "band": None, "status": "no_backtest", "sentence": ""}
    if bt_rate is None:
        out["sentence"] = "No backtest to compare with yet – run one on this page."
        return out
    if n == 0:
        out["status"] = "no_live"
        out["sentence"] = "No finished live trades yet – the comparison starts after your first trade closes."
        return out
    lo, hi = binom_band(n, bt_rate, level)
    out["band"] = {"low": lo, "high": hi, "level": level}
    wr = live["win_rate"]
    rng = f"{lo * 100:.0f}–{hi * 100:.0f}%"
    if wr < lo:
        out["status"] = "below"
        out["sentence"] = (f"Live results are below the range the backtest expected: {wr * 100:.0f}% of trades reached "
                           f"target 1, the backtest expected {rng} for {n} trades. Something may have changed – "
                           "trade smaller or pause this setup.")
    elif wr > hi:
        out["status"] = "above"
        out["sentence"] = (f"Live results are above the range the backtest expected ({wr * 100:.0f}% vs {rng}). "
                           "Nice, but it may be luck – don't increase your risk because of it.")
    else:
        out["status"] = "inside"
        out["sentence"] = (f"Live results are inside the range the backtest expected ({wr * 100:.0f}% reached target 1; "
                           f"expected {rng} for {n} trades).")
    if n < 10:
        out["sentence"] += f" Only {n} live trade{'s' if n != 1 else ''} so far, so this says very little yet."
    return out


@router.get("/live-vs-backtest")
def live_vs_backtest(symbol: str | None = None, base=Depends(get_backtest_base), svc=Depends(get_plan_service)):
    sym = symbol_or_404(symbol).ticker if symbol else None
    trades = _live_trades(svc.store, sym)
    runs = _runs(base, sym)
    bt_rows = [r for run in runs for r in (run.get("rows") or []) if r.get("session") == "all"]
    out_rows = []
    keys = sorted({(r["symbol"], r["setup"]) for r in bt_rows} | {(t["symbol"], t["setup_type"]) for t in trades})
    for tk, setup in keys:
        b = next((r for r in bt_rows if r["symbol"] == tk and r["setup"] == setup), None)
        lt = [t for t in trades if t["symbol"] == tk and t["setup_type"] == setup]
        c = compare(_live_stats(lt), b.get("win_rate") if b else None, (b or {}).get("trades") or 0,
                    (b or {}).get("expectancy_pips") if b else None)
        out_rows.append({"symbol": tk, "setup": setup, "setup_name": SETUP_NAME.get(setup, setup), **c})
    # overall: every backtest trade pooled vs every live trade
    n_bt = sum(r.get("trades") or 0 for r in bt_rows)
    w_bt = sum(r.get("wins") or 0 for r in bt_rows)
    avg_bt = (sum((r.get("expectancy_pips") or 0) * (r.get("trades") or 0) for r in bt_rows) / n_bt) if n_bt else None
    overall = compare(_live_stats(trades), (w_bt / n_bt) if n_bt else None, n_bt, round(avg_bt, 2) if avg_bt is not None else None)
    return clean({"overall": overall, "rows": out_rows})


@router.post("/run")
def run(request: Request, symbol: str = "EUR/USD", setups: str | None = None,
        months: int | None = Query(None, ge=1, le=120), base=Depends(get_backtest_base), fn=Depends(runner)):
    tk = symbol_or_404(symbol).ticker
    sel = [s.strip() for s in setups.split(",") if s.strip() in SETUP_NAME] if setups else None

    def progress(stage, done, total, msg):
        with _lock:
            _progress[tk] = {"stage": stage, "done": done, "total": total, "message": msg, "at": time.time()}

    def job():
        progress("queued", 0, 0, "Starting…")
        res = fn(tk, months=months, setups=sel, progress=progress, out_base=base)
        return {k: res.get(k) for k in ("symbol", "method", "period_text", "lines", "disabled", "overall", "elapsed_s",
                                        "notes")}

    j = request.app.state.jobs.submit("performance", f"performance:{tk}", job)
    return clean({**j.public(with_result=False), "symbol": tk})


@router.get("/run")
def run_status(request: Request, symbol: str = "EUR/USD"):
    tk = symbol_or_404(symbol).ticker
    j = request.app.state.jobs.latest(f"performance:{tk}")
    return clean({"symbol": tk, "job": j.public(with_result=j.status in ("done", "error")) if j else None,
                  "progress": _progress.get(tk)})
