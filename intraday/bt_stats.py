"""Backtest statistics, the auto-disable rule, shrinkage, and the probability JSON files the cards read.

stats(trades)          trades, win rate (target 1 before the stop), average win / loss in pips, profit factor,
                       max drawdown, expectancy, best / worst hours, median minutes to target 1 + IQR
shrink(k, n, p0, m)    (k + m * p0) / (n + m): a beta prior worth m trades at the average p0 (empirical Bayes)
verdict(st)            (enabled, plain reason): off when profit factor < BACKTEST_MIN_PROFIT_FACTOR, fewer than
                       BACKTEST_MIN_TRADES trades, or a win rate not significantly above break-even (one-sided
                       binomial test, p < BACKTEST_SIGNIFICANCE)
result_files(...)      the per symbol x setup dicts in the schema documented in intraday/probability.py
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from intraday.probability import CONTEXT_KEYS, result_path


@dataclass
class Rules:
    min_trades: int = 50
    min_pf: float = 1.15
    alpha: float = 0.05
    prior_trades: int = 20

    @classmethod
    def from_settings(cls, s=None) -> Rules:
        if s is None:
            from config.settings import get_settings

            s = get_settings()
        return cls(s.backtest_min_trades, s.backtest_min_profit_factor, s.backtest_significance, s.backtest_prior_trades)


def _get(t, k):
    return t[k] if isinstance(t, dict) else getattr(t, k)


# ---------------------------------------------------------------- binomial helpers (no scipy needed)
def binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    lp, lq = math.log(p), math.log1p(-p)
    terms = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq
             for i in range(k, n + 1)]
    m = max(terms)
    return min(1.0, math.exp(m) * sum(math.exp(x - m) for x in terms))


def binom_band(n: int, p: float, level: float = 0.90) -> tuple[float, float]:
    """Central `level` range of the win RATE in n trades if the true rate is p: (low, high)."""
    if n <= 0:
        return (0.0, 1.0)
    a = (1 - level) / 2
    lo = next((k for k in range(n + 1) if 1 - binom_sf(k + 1, n, p) >= a), 0)       # P(X <= k) >= a
    hi = next((k for k in range(n + 1) if 1 - binom_sf(k + 1, n, p) >= 1 - a), n)
    return lo / n, hi / n


def shrink(k: float, n: int, p0: float, m: float) -> float:
    return (k + m * p0) / (n + m) if (n + m) else p0


# ---------------------------------------------------------------- statistics
def _pct(xs, q):
    return float(np.percentile(xs, q)) if len(xs) else None


def max_drawdown(pips: list[float]) -> float:
    eq = np.cumsum([0.0, *pips])
    peak = np.maximum.accumulate(eq)
    return float((peak - eq).max()) if len(eq) else 0.0


def stats(trades: list, tz: str = "Europe/Berlin") -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0, "wins": 0, "win_rate": None, "avg_win_pips": None, "avg_loss_pips": None,
                "profit_factor": None, "max_drawdown_pips": 0.0, "expectancy_pips": None, "expectancy_r": None,
                "total_pips": 0.0, "breakeven_win_rate": None, "p_value": None, "best_hours": [], "worst_hours": [],
                "median_minutes_to_tp1": None, "p25_minutes_to_tp1": None, "p75_minutes_to_tp1": None}
    ts = sorted(trades, key=lambda t: _get(t, "closed_at"))
    pips = [float(_get(t, "pips")) for t in ts]
    wins = [t for t in ts if _get(t, "tp1_hit")]
    pos = [p for p in pips if p > 0]
    neg = [p for p in pips if p < 0]
    gp, gl = sum(pos), -sum(neg)
    win_p = [float(_get(t, "pips")) for t in wins]
    loss_p = [float(_get(t, "pips")) for t in ts if not _get(t, "tp1_hit")]
    aw = float(np.mean(win_p)) if win_p else None
    al = float(-np.mean(loss_p)) if loss_p else None
    # break-even win rate: share of target-1 trades needed so that wins pay for the rest
    if aw is None:
        be = 1.0                      # never reached target 1
    elif al is None or al <= 0:
        be = 0.0                      # the other trades didn't lose on average
    elif aw + al <= 0:
        be = 1.0
    else:
        be = al / (aw + al)
    pval = binom_sf(len(wins), n, be) if be is not None else None
    mins = [float(_get(t, "minutes_to_tp1")) for t in wins if _get(t, "minutes_to_tp1") is not None]
    hours: dict[int, list[float]] = {}
    zone = ZoneInfo(tz)
    for t in ts:
        trig = _get(t, "triggered_at")
        trig = datetime.fromisoformat(trig) if isinstance(trig, str) else trig
        hours.setdefault(trig.astimezone(zone).hour, []).append(float(_get(t, "pips")))
    hr = [{"hour": h, "trades": len(v), "avg_pips": round(float(np.mean(v)), 2)} for h, v in hours.items() if len(v) >= 3]
    hr.sort(key=lambda x: -x["avg_pips"])
    return {
        "trades": n, "wins": len(wins), "win_rate": round(len(wins) / n, 4),
        "avg_win_pips": round(aw, 2) if aw is not None else None,
        "avg_loss_pips": round(al, 2) if al is not None else None,
        "profit_factor": round(gp / gl, 3) if gl > 0 else (None if gp == 0 else 99.0),
        "max_drawdown_pips": round(max_drawdown(pips), 2),
        "expectancy_pips": round(float(np.mean(pips)), 2),
        "expectancy_r": round(float(np.mean([float(_get(t, "r")) for t in ts])), 3),
        "total_pips": round(sum(pips), 2),
        "breakeven_win_rate": round(be, 4) if be is not None else None,
        "p_value": round(pval, 4) if pval is not None else None,
        "best_hours": hr[:3], "worst_hours": list(reversed(hr[-3:])) if len(hr) > 3 else [],
        "median_minutes_to_tp1": _pct(mins, 50), "p25_minutes_to_tp1": _pct(mins, 25),
        "p75_minutes_to_tp1": _pct(mins, 75),
    }


def verdict(st: dict, rules: Rules) -> tuple[bool, str]:
    n = st.get("trades") or 0
    if n < rules.min_trades:
        return False, (f"Only {n} test trade{'s' if n != 1 else ''} – at least {rules.min_trades} are needed before "
                       "the results can be trusted.")
    pf = st.get("profit_factor")
    if pf is None or pf < rules.min_pf:
        return False, (f"It didn't make enough money: for every 1 pip lost it won only {pf or 0:.2f} pips "
                       f"(profit factor, needs at least {rules.min_pf:g}).")
    p = st.get("p_value")
    if p is None or p >= rules.alpha:
        wr, be = (st.get("win_rate") or 0) * 100, (st.get("breakeven_win_rate") or 0) * 100
        return False, (f"It reached target 1 in {wr:.0f}% of trades, but {be:.0f}% was needed just to break even – "
                       "the difference could be luck.")
    return True, ""


# ---------------------------------------------------------------- probability files
def _bucket(trades: list, p0: float, m: float) -> dict:
    n = len(trades)
    k = sum(1 for t in trades if _get(t, "tp1_hit"))
    st = stats(trades)
    return {"n": n, "win_rate": round(shrink(k, n, p0, m), 4), "raw_win_rate": round(k / n, 4) if n else None,
            "profit_factor": st["profit_factor"], "expectancy_pips": st["expectancy_pips"],
            "median_minutes_to_tp1": st["median_minutes_to_tp1"], "p25_minutes_to_tp1": st["p25_minutes_to_tp1"],
            "p75_minutes_to_tp1": st["p75_minutes_to_tp1"]}


def buckets(trades: list, p0: float, m: float) -> dict:
    """{"session=london": {...}, "session=london|market=trending_up": {...}, ...} shrunk toward p0."""
    out = {}
    for r in range(1, len(CONTEXT_KEYS) + 1):
        for combo in combinations(CONTEXT_KEYS, r):
            groups: dict[tuple, list] = {}
            for t in trades:
                groups.setdefault(tuple(_get(t, c) for c in combo), []).append(t)
            for vals, ts in groups.items():
                out["|".join(f"{c}={v}" for c, v in zip(combo, vals))] = _bucket(ts, p0, m)
    return out


def result_files(symbol: str, setups: list[str], trades: list, rules: Rules, meta: dict) -> dict[str, dict]:
    """setup -> file dict (schema of intraday/probability.py). `meta`: period, out_of_sample, method, ..."""
    all_k = sum(1 for t in trades if _get(t, "tp1_hit"))
    pooled = all_k / len(trades) if trades else 0.5           # average over every setup of this run
    out = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for s in setups:
        ts = [t for t in trades if _get(t, "setup") == s]
        st = stats(ts)
        ok, why = verdict(st, rules)
        # Too few test trades is missing evidence, not evidence that the setup fails: keep it on, labelled
        # "unproven" (otherwise a short Yahoo history would switch every setup off). Only a large enough sample
        # with a poor result switches a setup off.
        unproven = len(ts) < rules.min_trades
        if unproven:
            ok, note = True, why
            why = ""
        else:
            note = ""
        k = st["wins"]
        overall = {"n": len(ts), "win_rate": round(shrink(k, len(ts), pooled, rules.prior_trades), 4),
                   "raw_win_rate": st["win_rate"], "profit_factor": st["profit_factor"],
                   "expectancy_pips": st["expectancy_pips"], "median_minutes_to_tp1": st["median_minutes_to_tp1"],
                   "p25_minutes_to_tp1": st["p25_minutes_to_tp1"], "p75_minutes_to_tp1": st["p75_minutes_to_tp1"]}
        setup_avg = k / len(ts) if ts else pooled
        out[s] = {"symbol": symbol, "setup": s, "generated_at": now, **meta, "enabled": ok, "disabled_reason": why,
                  "unproven": unproven, "unproven_reason": note,
                  "overall": overall, "stats": st, "buckets": buckets(ts, setup_avg, rules.prior_trades) if ts else {}}
    return out


def write_files(files: dict[str, dict], base: Path | None = None) -> list[Path]:
    paths = []
    for s, d in files.items():
        p = result_path(d["symbol"], s, base)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
        paths.append(p)
    return paths
