"""Probability hook: how often similar setups worked in the backtest (results are written by phase 7).

File location and schema (one JSON file per symbol and setup):

    {user_data_dir}/intraday_backtests/{SYMBOL with '/' -> '_'}_{setup}.json      e.g. EUR_USD_trend_pullback.json
    {
      "symbol": "EUR/USD", "setup": "trend_pullback",
      "generated_at": "2026-11-20T10:00:00+00:00",
      "period": {"start": "2024-11-01", "end": "2026-11-01"},
      "out_of_sample": true,
      "enabled": true,                       # false = backtest switched the setup off ...
      "disabled_reason": "",                 # ... and why, in plain words (e.g. "profit factor below 1.15")
      "overall": {"n": 212, "win_rate": 0.58, "profit_factor": 1.31,
                  "median_minutes_to_tp1": 95, "p25_minutes_to_tp1": 40, "p75_minutes_to_tp1": 180},
      "buckets": {                           # optional, per context; keys "<field>=<value>" joined with "|"
        "session=london": {"n": 90, "win_rate": 0.61, "median_minutes_to_tp1": 80, ...},
        "session=london|market=trending_up": {...}
      }
    }
`win_rate` = share of trades that reached target 1 before the stop (already shrunk toward the setup average for
small samples by phase 7). lookup() picks the most specific bucket matching `context` with n >= MIN_N, else
"overall". Missing file -> None (the card then says "No backtest yet – treat as unproven").
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)
MIN_N = 30
CONTEXT_KEYS = ("session", "market", "direction")


def backtest_dir() -> Path:
    from config.settings import get_settings

    return get_settings().user_data_dir / "intraday_backtests"


def result_path(symbol: str, setup: str, base: Path | None = None) -> Path:
    return (base or backtest_dir()) / f"{symbol.replace('/', '_').upper()}_{setup}.json"


def _load(symbol: str, setup: str, base: Path | None) -> dict | None:
    p = result_path(symbol, setup, base)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Bad backtest file %s: %s", p, e)
        return None


def lookup(setup_type: str, symbol: str, context: dict, base: Path | None = None) -> dict | None:
    """{'win_rate', 'n', 'median_minutes_to_tp1', 'p25_minutes_to_tp1', 'p75_minutes_to_tp1', 'bucket', ...} or None."""
    res = _load(symbol, setup_type, base)
    if not res:
        return None
    buckets = res.get("buckets") or {}
    keys = [k for k in CONTEXT_KEYS if context.get(k)]
    best, best_key = None, "overall"
    # most specific first: all keys, then subsets in order
    for r in range(len(keys), 0, -1):
        for combo in _combos(keys, r):
            k = "|".join(f"{c}={context[c]}" for c in combo)
            b = buckets.get(k)
            if b and (b.get("n") or 0) >= MIN_N:
                best, best_key = b, k
                break
        if best:
            break
    best = best or res.get("overall")
    if not best or not best.get("n"):
        return None
    return {**best, "bucket": best_key, "generated_at": res.get("generated_at"),
            "out_of_sample": res.get("out_of_sample", True), "period": res.get("period")}


def _combos(keys: list[str], r: int):
    from itertools import combinations

    return combinations(keys, r)


def setup_enabled(setup_type: str, symbol: str, base: Path | None = None) -> bool:
    """True when there are no results; False when the backtest marked the setup as disabled."""
    res = _load(symbol, setup_type, base)
    return True if not res else bool(res.get("enabled", True))


def disabled_reason(setup_type: str, symbol: str, base: Path | None = None) -> str:
    res = _load(symbol, setup_type, base) or {}
    return res.get("disabled_reason") or ""
