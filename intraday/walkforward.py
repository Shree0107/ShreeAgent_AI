"""Walk-forward intraday backtest for one symbol: tune on 12 months, test on the next 3, roll on; report only the
test months ("out-of-sample": results on data the settings were NOT chosen on).

    result = run_backtest("EUR/USD", months=24)       # also writes the probability files the cards read

Splits (splits()):
  walk_forward   at least TRAIN + TEST months of 5-minute bars: windows train [a, a+12m) -> test [a+12m, a+15m),
                 moved on by 3 months each time
  single_split   less history (e.g. Yahoo's ~60 days of 5-minute bars): tune on the first 60 %, test on the last
                 40 % - ONE out-of-sample period, labelled as such (a rough guide, not proof)
  in_sample      under MIN_DAYS of history: no tuning at all, the current settings tested on everything
                 (out_of_sample = false)
"Tuning" is deliberately small: the grid of minimum confirmations x minimum reward/risk from the settings; the
choice with the best total result (in R) on the training part wins, provided it made at least MIN_TUNE_TRADES
trades (else the current settings are kept). Every window records what was chosen.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from data.symbols import Symbol, parse_symbol, resolve
from intraday import bar_store
from intraday.backtest import Costs, Decision, Frames, Params, Trade, base_config, decisions, simulate
from intraday.bt_news import NOTE as NEWS_NOTE
from intraday.bt_news import NewsHistory
from intraday.bt_stats import Rules, result_files, stats, write_files
from intraday.config import IntradayConfig, from_settings
from intraday.context import TFS
from intraday.probability import backtest_dir
from intraday.setups import SETUP_NAME
from data.providers.base import resample_ohlcv

log = logging.getLogger(__name__)
MIN_DAYS = 14                    # below this: in-sample only
MIN_TUNE_TRADES = 10
WARMUP = timedelta(days=4)       # first days of 5-minute bars only fill the 15-minute window
SESSION_NAME = {"london": "London", "overlap": "London–New York overlap", "new_york": "New York",
                "asian": "Asian", "off": "Quiet hours", "all": "All sessions"}
METHOD_TEXT = {
    "walk_forward": "Walk-forward: settings chosen on 12 months, then tested on the next 3 months (repeated). "
                    "Only the test months are shown.",
    "single_split": "Only a short history was available, so the settings were chosen on the first 60% of it and "
                    "tested once on the last 40%. A rough guide, not proof.",
    "in_sample": "Very little history: the current settings were tested on all of it, without a separate test "
                 "period. Treat as a rough first look only.",
}


@dataclass
class Window:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    def as_dict(self) -> dict:
        return {k: getattr(self, k).isoformat() for k in ("train_start", "train_end", "test_start", "test_end")}


def _add_months(t: datetime, m: int) -> datetime:
    return (pd.Timestamp(t) + pd.DateOffset(months=m)).to_pydatetime()


def splits(start: datetime, end: datetime, train_months: int = 12, test_months: int = 3) -> tuple[str, list[Window]]:
    if _add_months(start, train_months + test_months) <= end:
        out, a = [], start
        while True:
            tr_end = _add_months(a, train_months)
            te_end = min(_add_months(tr_end, test_months), end)
            if tr_end >= end or (te_end - tr_end) < timedelta(days=7):
                break
            out.append(Window(a, tr_end, tr_end, te_end))
            if te_end >= end:
                break
            a = _add_months(a, test_months)
        return "walk_forward", out
    if end - start >= timedelta(days=MIN_DAYS):
        cut = start + (end - start) * 0.6
        return "single_split", [Window(start, cut, cut, end)]
    return "in_sample", [Window(start, start, start, end)]


def grid_from_settings(s=None, cfg: IntradayConfig | None = None) -> list[Params]:
    if s is None:
        from config.settings import get_settings

        s = get_settings()
    confs = [int(x) for x in str(s.backtest_grid_min_confirmations).split(",") if x.strip()]
    rrs = [float(x) for x in str(s.backtest_grid_min_rr).split(",") if x.strip()]
    if cfg is not None:
        confs = sorted(set(confs) | {cfg.min_confirmations})
        rrs = sorted(set(rrs) | {cfg.min_rr})
    return [Params(c, r) for c in confs for r in rrs]


def tune(symbol: Symbol, m5: pd.DataFrame, decs: list[Decision], grid: list[Params], default: Params,
         cfg: IntradayConfig, costs: Costs, start: datetime, end: datetime) -> tuple[Params, list[dict]]:
    tried = []
    for p in grid:
        ts = simulate(symbol, m5, decs, p, cfg, costs, start, end)
        tried.append({"params": p, "trades": len(ts), "total_r": round(sum(t.r for t in ts), 2)})
    ok = [x for x in tried if x["trades"] >= MIN_TUNE_TRADES]
    best = max(ok, key=lambda x: (x["total_r"], x["params"] == default)) if ok else None
    chosen = best["params"] if best else default
    return chosen, [{"choice": x["params"].label(), "trades": x["trades"], "total_r": x["total_r"]} for x in tried]


# ---------------------------------------------------------------- data
def _sym(t: str) -> Symbol:
    s = parse_symbol(t) or resolve(t)
    if s is None:
        raise ValueError(f"Unknown symbol {t}")
    return s


def load_frames(sym: Symbol, data=None, store_base: Path | None = None) -> tuple[dict[str, pd.DataFrame], dict]:
    """Every timeframe from the local bar store (scripts/download_history.py), else from the data service."""
    frames, src = {}, {}
    for tf in TFS:
        df = bar_store.load(sym.ticker, tf, store_base)
        where = f"bar store ({df.attrs.get('source', '?')})" if df is not None and not df.empty else None
        if df is None or df.empty:
            try:
                if data is None:
                    from data.service import get_data_service

                    data = get_data_service()
                df = data.get_ohlcv(sym, tf)
                where = (df.attrs.get("source") if hasattr(df, "attrs") else None) or "data service"
            except Exception as e:
                log.info("No %s data for %s: %s", tf, sym.ticker, e)
                df = None
        if df is not None and not df.empty:
            frames[tf] = df
            src[tf] = {"source": where, "bars": int(len(df)), "start": df.index[0].isoformat(),
                       "end": df.index[-1].isoformat(), "bid_ask": "bid_close" in df.columns}
    if "5m" in frames and "15m" not in frames:
        frames["15m"] = resample_ohlcv(frames["5m"], "15min")
        src["15m"] = {"source": "built from 5-minute bars", "bars": len(frames["15m"])}
    return frames, src


# ---------------------------------------------------------------- the run
def _period_text(start: datetime, end: datetime) -> str:
    days = (end - start).days
    if days >= 60:
        m = round(days / 30.4)
        return f"{m} months" if m < 24 or m % 12 else f"{m // 12} years"
    return f"{days} days"


def summary_rows(trades: list[Trade], symbol: str, setups: list[str], tz: str) -> list[dict]:
    rows = []
    for s in setups:
        ts = [t for t in trades if t.setup == s]
        sessions = sorted({t.session for t in ts})
        for sess in ["all", *sessions]:
            sub = ts if sess == "all" else [t for t in ts if t.session == sess]
            rows.append({"setup": s, "setup_name": SETUP_NAME.get(s, s), "symbol": symbol, "session": sess,
                         "session_name": SESSION_NAME.get(sess, sess), **stats(sub, tz)})
    return rows


def plain_lines(rows: list[dict], files: dict[str, dict], symbol: str, period: str, method: str) -> list[str]:
    tag = {"walk_forward": "out-of-sample", "single_split": "one out-of-sample test", "in_sample": "not out-of-sample"}[method]
    out = []
    for r in rows:
        if r["session"] != "all":
            continue
        name = r["setup_name"]
        if not r["trades"]:
            out.append(f"{name}: no trades on {symbol} in the test period (last {period}).")
            continue
        f = files.get(r["setup"]) or {}
        line = (f"{name} reached target 1 in {r['wins']} of {r['trades']} trades on {symbol} "
                f"(last {period}, {tag}); on average {r['expectancy_pips']:+.1f} pips per trade after costs.")
        if f and not f.get("enabled", True):
            line += " Switched off for the live cards: " + f.get("disabled_reason", "")
        out.append(line)
    return out


def equity(trades: list[Trade]) -> list[dict]:
    cum_p = cum_r = 0.0
    out = []
    for t in sorted(trades, key=lambda x: x.closed_at):
        cum_p += t.pips
        cum_r += t.r
        out.append({"t": t.closed_at.isoformat(), "pips": round(cum_p, 2), "r": round(cum_r, 3), "setup": t.setup})
    return out


def runs_dir(base: Path | None = None) -> Path:
    return (base or backtest_dir()) / "_runs"


def run_path(symbol: str, base: Path | None = None) -> Path:
    return runs_dir(base) / f"{symbol.replace('/', '_').upper()}.json"


def load_run(symbol: str, base: Path | None = None) -> dict | None:
    p = run_path(symbol, base)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except Exception as e:
        log.warning("Bad run file %s: %s", p, e)
        return None


def all_runs(base: Path | None = None) -> list[dict]:
    d = runs_dir(base)
    out = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def run_backtest(ticker: str, months: int | None = None, setups: list[str] | None = None, data=None,
                 frames: dict | None = None, cfg: IntradayConfig | None = None, costs: Costs | None = None,
                 rules: Rules | None = None, grid: list[Params] | None = None, out_base: Path | None = None,
                 store_base: Path | None = None, write: bool = True, progress=None, settings=None,
                 news: NewsHistory | None = None) -> dict:
    """The whole thing for one symbol. progress(stage, done, total, message) is called along the way."""
    t0 = time.time()
    if settings is None:
        from config.settings import get_settings

        settings = get_settings()
    sym = _sym(ticker)
    cfg = cfg or from_settings(settings)
    costs = costs or Costs.from_settings(settings)
    rules = rules or Rules.from_settings(settings)
    grid = grid or grid_from_settings(settings, cfg)
    months = months or settings.backtest_months
    setups = [s for s in (setups or list(cfg.setups_enabled)) if s in SETUP_NAME]
    notes: list[str] = []

    def say(stage, done=0, total=0, msg=""):
        if progress:
            progress(stage, done, total, msg)

    say("data", 0, 0, "Loading price history…")
    if frames is None:
        frames, src = load_frames(sym, data, store_base)
    else:
        src = {tf: {"source": "given", "bars": len(df)} for tf, df in frames.items()}
    m5 = frames.get("5m")
    if m5 is None or m5.empty:
        raise ValueError(f"No 5-minute price history for {sym.ticker}. Run scripts/download_history.py first.")
    fr = Frames(frames)
    m5 = fr.frames["5m"]
    data_end = (m5.index[-1] + pd.Timedelta(minutes=5)).to_pydatetime()
    data_start = (m5.index[0]).to_pydatetime() + WARMUP
    start = max(data_start, _add_months(data_end, -months))
    if start >= data_end:
        raise ValueError(f"Not enough 5-minute history for {sym.ticker} (needs more than {WARMUP.days} days).")
    span_days = (data_end - start).days
    if not (src.get("5m") or {}).get("bid_ask"):
        notes.append("No bid/ask prices in the history: buys and sells are filled at the middle price plus half of "
                     f"the typical spread ({cfg.typical_spread_for(sym.ticker):g} pips).")
    if span_days < 120:
        notes.append(f"Only {span_days} days of 5-minute history were available (Yahoo keeps about 60 days). "
                     "For a proper 12 + 3 month walk-forward test, add an OANDA token and run "
                     "scripts/download_history.py.")
    method, windows = splits(start, data_end, settings.backtest_train_months, settings.backtest_test_months)
    if news is None:
        news = NewsHistory.build(start - timedelta(days=2), data_end + timedelta(days=2))
    notes.append(NEWS_NOTE)

    bcfg = base_config(cfg, grid, tuple(setups))
    say("cards", 0, 0, "Replaying the 15-minute engine…")
    decs = decisions(sym, fr, bcfg, start, data_end, news,
                     progress=lambda i, n: say("cards", i, n, f"Replaying the engine: {i} of {n} 15-minute candles"))
    default = Params(cfg.min_confirmations, cfg.min_rr)
    if default not in grid:
        grid = [default, *grid]
    say("simulate", 0, len(windows), "Testing the trades…")
    oos: list[Trade] = []
    wins_out = []
    for i, w in enumerate(windows):
        if method == "in_sample":
            chosen, tried = default, []
        else:
            chosen, tried = tune(sym, m5, decs, grid, default, bcfg, costs, w.train_start, w.train_end)
        ts = simulate(sym, m5, decs, chosen, bcfg, costs, w.test_start, w.test_end)
        ts = [t for t in ts if t.created_at < w.test_end]
        oos += ts
        wins_out.append({**w.as_dict(), "chosen": chosen.label(), "min_confirmations": chosen.min_confirmations,
                         "min_rr": chosen.min_rr, "tried": tried, "test_trades": len(ts)})
        say("simulate", i + 1, len(windows), f"Tested window {i + 1} of {len(windows)}")
    # a trade can't belong to two windows (windows don't overlap; a trade is kept by the window that opened it)
    test_start, test_end = windows[0].test_start, windows[-1].test_end
    period = _period_text(test_start, test_end)
    meta = {"period": {"start": test_start.date().isoformat(), "end": test_end.date().isoformat()},
            "out_of_sample": method != "in_sample", "method": method}
    files = result_files(sym.ticker, setups, oos, rules, meta)
    rows = summary_rows(oos, sym.ticker, setups, cfg.tz)
    res = {
        "symbol": sym.ticker, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": method, "method_text": METHOD_TEXT[method], "out_of_sample": method != "in_sample",
        "period": meta["period"], "period_text": period, "data": src, "months": months,
        "costs": {"commission_pips": costs.commission_pips, "slippage_pips": costs.slippage_pips,
                  "typical_spread_pips": cfg.typical_spread_for(sym.ticker)},
        "rules": {"min_trades": rules.min_trades, "min_profit_factor": rules.min_pf, "significance": rules.alpha,
                  "prior_trades": rules.prior_trades},
        "grid": [p.label() for p in grid], "windows": wins_out, "setups": setups,
        "decisions": len(decs), "cards_built": sum(1 for d in decs if not d.skipped),
        "overall": stats(oos, cfg.tz), "rows": rows,
        "lines": plain_lines(rows, files, sym.ticker, period, method),
        "disabled": [{"symbol": sym.ticker, "setup": s, "setup_name": SETUP_NAME.get(s, s),
                      "reason": f["disabled_reason"]} for s, f in files.items() if not f["enabled"]],
        "trades": [t.as_dict() for t in sorted(oos, key=lambda t: t.closed_at)],
        "equity": equity(oos), "notes": notes, "elapsed_s": round(time.time() - t0, 1),
    }
    if write:
        write_files(files, out_base)
        p = run_path(sym.ticker, out_base)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    say("done", 1, 1, "Done")
    return res
