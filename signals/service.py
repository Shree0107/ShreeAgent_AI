"""Build beginner signal cards: analysis -> levels -> decision -> plain-language explanation -> history.

    build_signal(symbol)          one card (dict, JSON-safe)
    watchlist_signals(force)      every watchlist symbol, reusing stored cards younger than SIGNAL_REFRESH_MINUTES
    with_sizing(card, ...)        fill in the position size / money figures for the user's account
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from config.settings import get_settings
from data.symbols import Symbol, parse_symbol, resolve
from signals.decision import decide
from signals.events import blocking_event, symbol_events
from signals.explain import DISCLAIMER, build_explanation, money_texts
from signals.history import SignalHistory
from signals.levels import build_levels
from signals.market import conversion_rate, fmt_price, instrument_currency, pip_size, price_decimals
from signals.polish import polish
from signals.sizing import position_size
from signals.structure import market_facts

log = logging.getLogger(__name__)

CARD_VERSION = 2           # bump when the card layout changes so stored cards are rebuilt
EXPIRY_HOUR_UTC = 21       # New York close, when the daily forex candle ends


def expiry_time(now: datetime, bars: int) -> datetime:
    """`bars` trading days after `now` (weekends skipped), at the daily close."""
    d = now.astimezone(timezone.utc)
    added = 0
    while added < bars:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.replace(hour=EXPIRY_HOUR_UTC, minute=0, second=0, microsecond=0)


def display_name(symbol: Symbol) -> str:
    if symbol.is_fx:
        from signals.explain import CURRENCY_NAME

        metals = {"XAU": "Gold", "XAG": "Silver"}
        b = metals.get(symbol.base) or CURRENCY_NAME.get(symbol.base, symbol.base).capitalize()
        return f"{b} / {CURRENCY_NAME.get(symbol.quote, symbol.quote)}"
    return symbol.name


def _sym(ticker: str) -> Symbol:
    return parse_symbol(ticker) or resolve(ticker)


def build_signal(symbol: Symbol, data=None, forecaster=None, now: datetime | None = None,
                 analysis: dict | None = None, history: SignalHistory | None = None, save: bool = True) -> dict:
    from analysis.combined import full_analysis
    from data.service import get_data_service

    s = get_settings()
    data = data or get_data_service()
    now = now or datetime.now(timezone.utc)
    tf = s.signal_timeframe
    a = analysis or full_analysis(symbol, tf, s.signal_forecast_horizon, include_forecast=s.signal_include_forecast,
                                  include_news=True, data=data, forecaster=forecaster)
    tfs = a["technical"]["timeframes"]
    sig_tf = tfs.get(tf) or next(iter(tfs.values()))
    supports = [l["price"] for l in sig_tf["supports"]]
    resistances = [l["price"] for l in sig_tf["resistances"]]
    df = data.get_ohlcv(symbol, tf)
    facts = market_facts(df, supports, resistances)

    comb = a["combined"]
    score = comb["score"]
    comps = {k: v for k, v in comb["components"].items() if k in comb.get("weights", comb["components"])}
    lean = "long" if score >= 0 else "short"
    pip = pip_size(symbol)
    plan = None
    try:
        plan = build_levels(
            lean, facts.price, facts.atr, supports, resistances,
            [(x.price, x.date) for x in facts.swing_lows], [(x.price, x.date) for x in facts.swing_highs],
            facts.high_60d, facts.low_60d, spread=(s.spread_pips * pip) if pip else 0.0,
            min_rr=s.signal_min_rr, max_stop_atr=s.signal_max_stop_atr, decimals=price_decimals(symbol, facts.price),
        )
    except ValueError as e:
        log.warning("Levels unavailable for %s: %s", symbol.ticker, e)

    next_earn = ((a.get("fundamental") or {}).get("metrics") or {}).get("next_earnings_date")
    events = symbol_events(symbol, data, next_earn, days=max(14, s.signal_event_warning_days), today=now.date())
    block = blocking_event(events, s.signal_event_blackout_days, s.signal_earnings_blackout_days)
    age = (now - pd.Timestamp(facts.last_bar).to_pydatetime().astimezone(timezone.utc)).total_seconds() / 86400

    d = decide(score, comps, sig_tf["trend"], (tfs.get("1wk") or {}).get("trend"), plan, block, age,
               min_score=s.signal_min_score, high_score=s.signal_high_score,
               min_confidence=s.signal_min_confidence, min_rr=s.signal_min_rr)
    expires = expiry_time(now, s.signal_expiry_bars)
    exp = build_explanation(symbol, d, plan, facts, a, events, None, expires,
                            warning_days=s.signal_event_warning_days, min_rr=s.signal_min_rr, today=now.date())

    polished = False
    if s.signal_llm_polish:
        texts = exp.reasons + exp.waiting_for
        out = polish(texts)
        polished = out != texts
        exp.reasons, exp.waiting_for = out[: len(exp.reasons)], out[len(exp.reasons):]

    card = {
        "version": CARD_VERSION,
        "symbol": symbol.ticker, "name": display_name(symbol), "asset_class": symbol.asset_class, "market": symbol.market,
        "is_fx": symbol.is_fx, "pip_size": pip, "instrument_currency": instrument_currency(
            symbol, ((a.get("fundamental") or {}).get("metrics") or {}).get("currency")),
        "price": facts.price, "price_text": fmt_price(symbol, facts.price),
        "change_pct": (sig_tf.get("snapshot") or {}).get("change_pct"),
        "action": d.action, "lean": d.lean, "score": d.score, "confidence": d.confidence,
        "strength": round(d.strength, 1), "decision": d.as_dict(),
        "levels": plan.as_dict() if plan else None,
        "explanation": exp.as_dict(), "polished": polished,
        "generated_at": now.isoformat(timespec="seconds"), "expires_at": expires.isoformat(timespec="seconds"),
        "timeframe": tf, "last_bar": facts.last_bar,
        "details": {
            "facts": facts.as_dict(), "components": comb["components"], "weights": comb.get("weights"),
            "confidence_reasons": comb.get("confidence_reasons"), "timeframes": {
                k: {kk: v.get(kk) for kk in ("score", "bias", "trend", "trend_strength", "reasons", "snapshot")}
                for k, v in tfs.items()},
            "supports": sig_tf["supports"], "resistances": sig_tf["resistances"],
            "forecast": a.get("forecast"), "fundamental_bias": (a.get("fundamental") or {}).get("bias"),
            "sentiment": {k: (a.get("sentiment") or {}).get(k) for k in ("label", "score", "n_articles", "method")},
        },
        "errors": a.get("errors", {}),
        "disclaimer": DISCLAIMER,
    }
    if save:
        h = history or SignalHistory()
        h.save_latest(card)
        h.record(card)
    return card


def with_sizing(card: dict, account_size: float, risk_pct: float, account_currency: str, data=None) -> dict:
    """Copy of the card with position size, money gains and the risk/reward sentence for this account."""
    c = copy.deepcopy(card)
    lv = c.get("levels")
    ex = c["explanation"]
    if c["action"] not in ("BUY", "SELL") or not lv:
        return c
    s = get_settings()
    sym = _sym(c["symbol"])
    rate = conversion_rate(c["instrument_currency"], account_currency, sym, lv["entry_mid"], data)
    try:
        size = position_size(sym, lv["entry_mid"], lv["stop"], lv["target1"], lv["target2"], account_size, risk_pct,
                             account_currency, rate, c["instrument_currency"], s.fx_lot_size, s.fx_min_lot, s.leverage)
    except ValueError as e:
        ex["size_text"], ex["size_note"] = "", str(e)
        return c
    m = money_texts(sym, c["action"], lv["rr1"], lv["rr2"], size, account_currency)
    ex["rr_text"], ex["size_text"], ex["size_note"] = m["rr_text"], m["size_text"], m["size_note"]
    for t, money in zip(ex["targets"], m["target_money"]):
        t["money"] = money
    c["size"] = size.as_dict()
    return c


def _bars_for(data):
    def get(ticker: str) -> pd.DataFrame:
        sym = _sym(ticker)
        try:
            return data.get_ohlcv(sym, "1h")   # hourly bars give a more precise stop-vs-target order
        except Exception:
            return data.get_ohlcv(sym, "1d")
    return get


def is_fresh(card: dict | None, now: datetime, minutes: int) -> bool:
    if not card or card.get("version") != CARD_VERSION:
        return False
    try:
        gen = datetime.fromisoformat(card["generated_at"])
    except (KeyError, ValueError):
        return False
    return now - gen < timedelta(minutes=minutes) and now < datetime.fromisoformat(card["expires_at"])


def watchlist_signals(symbols: list[str] | None = None, force: bool = False, data=None, forecaster=None,
                      history: SignalHistory | None = None, now: datetime | None = None,
                      on_progress=None) -> list[dict]:
    """Cards for every symbol, strongest first. Errors come back as {'symbol', 'error'} cards."""
    from data.service import get_data_service
    from data.watchlist import Watchlist

    s = get_settings()
    data = data or get_data_service()
    h = history or SignalHistory()
    now = now or datetime.now(timezone.utc)
    symbols = symbols or Watchlist().symbols()
    cards: list[dict] = []
    for i, tk in enumerate(symbols):
        if on_progress:
            on_progress(i, len(symbols), tk)
        try:
            sym = _sym(tk)
            cached = None if force else h.latest(sym.ticker)
            cards.append(cached if is_fresh(cached, now, s.signal_refresh_minutes)
                         else build_signal(sym, data=data, forecaster=forecaster, now=now, history=h))
        except Exception as e:
            log.warning("Signal failed for %s: %s", tk, e)
            cards.append({"symbol": tk, "action": "ERROR", "error": str(e), "strength": -1})
    try:
        h.update_outcomes(_bars_for(data), now)
    except Exception as e:
        log.warning("Outcome update failed: %s", e)
    return sort_cards(cards)


def sort_cards(cards: list[dict]) -> list[dict]:
    return sorted(cards, key=lambda c: -(c.get("strength") or 0))


def compact(card: dict) -> dict:
    """Short version of a card for the agent, the report and the WhatsApp digest."""
    if card.get("action") == "ERROR":
        return {"symbol": card["symbol"], "action": "ERROR", "error": card.get("error")}
    ex, lv = card["explanation"], card.get("levels") or {}
    out = {"symbol": card["symbol"], "action": card["action"], "confidence": ex["confidence_text"],
           "price": card["price_text"], "reasons": ex["reasons"], "generated_at": card["generated_at"],
           "expires_at": card["expires_at"], "event_warning": ex.get("event_warning")}
    if card["action"] == "WAIT":
        out["waiting_for"] = ex["waiting_for"]
    elif lv:
        out.update({"entry": ex["entry_text"], "entry_condition": ex["entry_confirm"], "stop_loss": lv["stop"],
                    "stop_why": ex["stop_why"], "target1": lv["target1"], "target2": lv["target2"],
                    "reward_to_risk": [lv["rr1"], lv["rr2"]], "cancel_if": ex["cancel"]})
    return out


def attach_signal(symbol: Symbol, analysis: dict, data=None) -> dict:
    """Add a compact beginner signal (built from this same analysis) to a full_analysis() result."""
    try:
        card = build_signal(symbol, data=data, analysis=analysis, save=False)
        analysis["signal"] = compact(card)
    except Exception as e:
        log.warning("Signal for %s failed: %s", symbol.ticker, e)
        analysis.setdefault("errors", {})["signal"] = str(e)
    return analysis
