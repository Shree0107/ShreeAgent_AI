"""Watchlist scan: runs the deterministic analysis (no LLM cost) and builds a WhatsApp digest.

A symbol is flagged when:
  - its combined score is at or beyond ALERT_SCORE_THRESHOLD (strong bullish/bearish), or
  - its bias changed since the previous scan, or
  - daily RSI is at an extreme (>= 75 or <= 25).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from analysis.combined import full_analysis
from config.settings import get_settings
from data.symbols import resolve
from data.watchlist import Watchlist

log = logging.getLogger(__name__)

_ICON = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}


@dataclass
class ScanRow:
    symbol: str
    price: float | None
    score: float
    bias: str
    confidence: str
    prev_bias: str | None
    rsi_d: float | None
    plan: dict
    flags: list[str]
    error: str = ""


def _state_path():
    return get_settings().user_data_dir / "scan_state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def scan(symbols: list[str] | None = None, include_forecast: bool | None = None, data=None) -> list[ScanRow]:
    s = get_settings()
    include_forecast = s.scan_include_forecast if include_forecast is None else include_forecast
    symbols = symbols or Watchlist().symbols()
    state = _load_state()
    rows: list[ScanRow] = []
    for tk in symbols:
        try:
            sym = resolve(tk)
            a = full_analysis(sym, "1d", 5, include_forecast=include_forecast, include_news=False, data=data)
            c = a["combined"]
            rsi = (a["technical"]["timeframes"].get("1d") or {}).get("snapshot", {}).get("rsi_14")
            prev = state.get(sym.ticker)
            flags = []
            if abs(c["score"]) >= s.alert_score_threshold:
                flags.append(f"strong {c['bias']}")
            if prev and prev != c["bias"]:
                flags.append(f"bias changed {prev}→{c['bias']}")
            if rsi is not None and (rsi >= 75 or rsi <= 25):
                flags.append(f"RSI {rsi:.0f} extreme")
            rows.append(ScanRow(sym.ticker, a["price"], c["score"], c["bias"], c["confidence"], prev, rsi,
                                a["trade_plan"], flags))
            state[sym.ticker] = c["bias"]
        except Exception as e:
            log.warning("Scan failed for %s: %s", tk, e)
            rows.append(ScanRow(tk, None, 0, "n/a", "n/a", None, None, {}, [], str(e)))
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    return rows


def format_digest(rows: list[ScanRow], only_flagged: bool = False) -> str:
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    lines = [f"*ShreeAgent AI: watchlist scan* ({now})"]
    shown = [r for r in rows if r.flags or not only_flagged]
    if not shown:
        lines.append("No alerts today. Nothing crossed the thresholds.")
    for r in shown:
        if r.error:
            lines.append(f"⚠️ {r.symbol}: error ({r.error[:80]})")
            continue
        icon = _ICON.get(r.bias, "⚪")
        lines.append(f"{icon} *{r.symbol}* {r.price:g} | {r.bias} {r.score:+.0f} ({r.confidence})")
        if r.flags:
            lines.append("   ⚡ " + ", ".join(r.flags))
        p = r.plan or {}
        if p.get("direction") in ("long", "short"):
            lines.append(f"   {p['direction']} {p['entry_zone'][0]:g}-{p['entry_zone'][1]:g} SL {p['stop_loss']:g} "
                         f"TP {p['take_profits'][0]:g} (R:R {p['risk_reward'][0]})")
    lines.append("_Analysis only, not financial advice._")
    return "\n".join(lines)


def run_and_notify(only_flagged: bool = False) -> str:
    from alerts.whatsapp import get_notifier

    rows = scan()
    msg = format_digest(rows, only_flagged=only_flagged)
    sent = get_notifier().send(msg)
    log.info("Scan complete (%d symbols), WhatsApp sent=%s", len(rows), sent)
    return msg
