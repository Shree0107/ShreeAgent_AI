"""Currency strength meter: which of the 8 major currencies are strongest / weakest right now.

For each of the 28 pairs between USD, EUR, GBP, JPY, CHF, AUD, CAD, NZD the % change over the window
(1H, 4H or 1D = the last 24 hours) is taken from hourly bars. A pair rising means its base (left) currency
gained against its quote (right) currency, so the base gets +change and the quote -change. Each currency's
strength is the average over its pairs that have data. Missing pairs are skipped and reported.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from itertools import combinations

import pandas as pd

from analysis.fundtab import cur_name
from data.symbols import Symbol

log = logging.getLogger(__name__)

# Market convention for which currency is quoted first.
MAJORS = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY")
PAIRS = [f"{a}/{b}" for a, b in combinations(MAJORS, 2)]  # 28 pairs, e.g. EUR/USD, USD/JPY, AUD/NZD
WINDOWS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(hours=24)}
CACHE_TTL = 300


def pair_change(df: pd.DataFrame, window: timedelta) -> float | None:
    """% change from the close `window` before the last bar to the last close."""
    if df is None or df.empty or "close" not in df:
        return None
    close = df["close"].dropna()
    if len(close) < 2:
        return None
    t_last = close.index[-1]
    prior = close[close.index <= t_last - window]
    if prior.empty:
        return None
    p0, p1 = float(prior.iloc[-1]), float(close.iloc[-1])
    return (p1 / p0 - 1) * 100 if p0 else None


def combine(changes: dict[str, float | None]) -> list[dict]:
    """{pair: % change or None} -> per-currency rows sorted strongest first."""
    acc: dict[str, list[float]] = {c: [] for c in MAJORS}
    for pair, ch in changes.items():
        if ch is None:
            continue
        b, q = pair.split("/")
        acc[b].append(ch)
        acc[q].append(-ch)
    rows = []
    for c, vals in acc.items():
        rows.append({"currency": c, "name": cur_name(c),
                     "strength": round(sum(vals) / len(vals), 4) if vals else None, "n_pairs": len(vals)})
    rows.sort(key=lambda r: (r["strength"] is None, -(r["strength"] or 0)))
    for i, r in enumerate(rows, 1):
        r["rank"] = i if r["strength"] is not None else None
    return rows


def _fetch(data, pair: str):
    try:
        return data.get_ohlcv(Symbol(pair, "forex", "FX", pair), "1h")
    except Exception as e:
        log.info("Strength meter: %s unavailable: %s", pair, e)
        return None


def currency_strength(data, tf: str = "1d", now: datetime | None = None) -> dict:
    if tf not in WINDOWS:
        raise ValueError(f"tf must be one of {list(WINDOWS)}")
    cache = getattr(data, "cache", None)
    key = f"fund:strength:{tf}"
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit
    with ThreadPoolExecutor(max_workers=6) as ex:
        frames = dict(zip(PAIRS, ex.map(lambda p: _fetch(data, p), PAIRS)))
    changes, sources, last_times = {}, set(), []
    for pair, df in frames.items():
        ch = pair_change(df, WINDOWS[tf]) if df is not None else None
        changes[pair] = None if ch is None else round(ch, 4)
        if ch is not None:
            sources.add(df.attrs.get("source", "unknown"))
            last_times.append(df.index[-1])
    rows = combine(changes)
    now = now or datetime.now(timezone.utc)
    as_of = max(last_times).to_pydatetime() if last_times else None
    missing = [p for p, c in changes.items() if c is None]
    live = bool(sources) and sources <= {"oanda"}
    notes = []
    if missing:
        notes.append(f"{len(missing)} of {len(PAIRS)} pairs had no data and were skipped.")
    if as_of is not None and now - as_of > timedelta(hours=3):
        notes.append("No new prices for over 3 hours (market closed?): the meter shows the last trading hours.")
    if not live and sources:
        notes.append("Prices from Yahoo are delayed, not live.")
    out = {"tf": tf, "currencies": rows, "pairs": changes, "missing_pairs": missing,
           "as_of": as_of, "sources": sorted(sources), "live": live, "notes": notes,
           "computed_at": now}
    if cache is not None and not len(missing) == len(PAIRS):
        cache.set(key, out, CACHE_TTL)
    return out
