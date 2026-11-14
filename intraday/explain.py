"""Plain-language text for intraday cards. Every number comes from the engine; no indicator names in main-view text.

JARGON lists the words that must never appear in the main view (tests check it); they are allowed in `details`.
"""
from __future__ import annotations

import copy
import math

from data.symbols import Symbol
from signals.explain import DISCLAIMER as _D, GLOSSARY as _G
from signals.market import conversion_rate, fmt_distance, fmt_money, fmt_price, instrument_currency
from signals.sizing import position_size

DISCLAIMER = "Analysis only, not financial advice. Always use a stop loss."
_ = _D
JARGON = ("RSI", "MACD", "ATR", "EMA", "SMA", "Fibonacci", "Fib ", "BOS", "CHoCH", "ADX", "Bollinger", "Keltner",
          "stochastic", "Stochastic", "VWAP", "order block", "FVG", "pivot", "zigzag", "divergence")

GLOSSARY = {
    **{k: v for k, v in _G.items() if k in ("Stop loss", "Take profit", "Pip", "Spread", "Lot", "Margin", "Risk vs reward")},
    "Break-even": "Moving your stop loss to your entry price, so the trade can no longer lose money.",
    "Limit order": "An order that waits for the price to come back to your price (buy lower / sell higher than now).",
    "Stop order": "An order that only opens the trade if the price moves through your price (a breakout).",
    "Time stop": "Closing the trade at a set time of day, even if neither the stop nor the target was hit.",
    "Sideways": "The price moves back and forth between a floor and a ceiling without a clear direction.",
    "Session": "The main trading hours of a financial centre: Asian (Tokyo), London and New York.",
    "Get ready": "The price is close to the planned entry. Prepare the order, but only act if the condition is met.",
    "Confidence": "How many independent checks agree with the trade idea (trend, momentum, price levels, candles, timing).",
}

DIR_WORD = {"long": "Buy", "short": "Sell"}
MARKET_TEXT = {"trending_up": "Trending up", "trending_down": "Trending down", "sideways": "Sideways"}


def entry_text(sym: Symbol, direction: str, entry_type: str, entry: float, lo: float, hi: float) -> tuple[str, str]:
    """(entry sentence, order type in plain words)."""
    w = DIR_WORD[direction]
    if entry_type == "stop":
        side = "above" if direction == "long" else "below"
        return f"{w} only if the price breaks {side} {fmt_price(sym, entry)}", f"{w} Stop order (breakout)"
    zone = fmt_price(sym, entry) if abs(hi - lo) < 1e-12 else f"{fmt_price(sym, lo)}–{fmt_price(sym, hi)}"
    move = "dips" if direction == "long" else "rises"
    return f"{w} when the price {move} to {zone}", f"{w} Limit order at {fmt_price(sym, entry)} (pullback)"


def rr_words(rr: float) -> str:
    return f"You risk 1 to make {rr:.2f}".rstrip("0").rstrip(".") if rr else ""


def window_text(minutes_lo: float, minutes_hi: float) -> str:
    def f(m):
        return f"{m / 60:.0f}" if m >= 60 else f"{m:.0f}"
    if minutes_hi < 60:
        return f"likely within the next {f(minutes_lo)}–{f(minutes_hi)} minutes"
    lo_h = max(1, round(minutes_lo / 60))
    hi_h = max(lo_h + 1, math.ceil(minutes_hi / 60))
    return f"likely within the next {lo_h}–{hi_h} hours"


def pips_text(sym: Symbol, a: float, b: float, signed: str = "") -> str:
    return f"{signed}{fmt_distance(sym, a, b)}"


def main_view_texts(card: dict) -> list[str]:
    """All main-view strings of a card (for the jargon test and the LLM polish step)."""
    ex = card.get("explanation") or {}
    out: list[str] = [card.get("market_text") or ""]
    for k, v in ex.items():
        if k in ("glossary",):
            continue
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            for x in v:
                out.append(x if isinstance(x, str) else " ".join(str(y) for y in (x or {}).values() if isinstance(y, str)))
    for s in card.get("scenarios") or []:
        out += [s.get("text", ""), s.get("why", "")]
    return [x for x in out if x]


def has_jargon(texts: list[str]) -> list[str]:
    return [t for t in texts for j in JARGON if j in t]


def with_size(card: dict, account: float, risk_pct: float, account_ccy: str, sym: Symbol, data=None, settings=None) -> dict:
    """Copy of a card with the position size and money for stop/targets in the account currency."""
    c = copy.deepcopy(card)
    if c.get("action") not in ("BUY", "SELL") or c.get("entry") is None or c.get("stop") is None:
        c["size"] = None
        return c
    if settings is None:
        from config.settings import get_settings

        settings = get_settings()
    ccy = instrument_currency(sym)
    try:
        rate = conversion_rate(ccy, account_ccy, sym, c["entry"], data)
        size = position_size(sym, c["entry"], c["stop"], c["target1"], c["target2"], account, risk_pct, account_ccy,
                             rate, ccy, settings.fx_lot_size, settings.fx_min_lot, settings.leverage)
    except Exception as e:
        c["size"] = None
        c["explanation"]["size_text"] = ""
        c["explanation"]["size_note"] = str(e)
        return c
    s = size.as_dict()
    c["size"] = s
    ex = c["explanation"]
    m = size.currency
    ex["stop_money"] = fmt_money(-size.actual_risk, m, signed=True)
    ex["tp1_money"] = fmt_money(size.gain_target1, m, signed=True)
    ex["tp2_money"] = fmt_money(size.gain_target2, m, signed=True)
    if size.too_small:
        ex["size_text"] = "Your risk amount is too small for the smallest possible trade."
        ex["size_note"] = (f"The smallest trade (0.01 lots) would risk {fmt_money(size.min_trade_risk, m)} – more than "
                           f"{fmt_money(size.risk_budget, m)}. Skip this trade or use a bigger account/risk.")
    else:
        what = f"{size.lots:.2f} lots" if size.lots is not None else f"{size.units:.0f} shares"
        ex["size_text"] = f"{DIR_WORD[c['direction']]} {what}"
        ex["size_note"] = (f"If the stop loss is hit you lose about {fmt_money(size.actual_risk, m)} "
                           f"({risk_pct:g}% of {fmt_money(account, m)})." + ("" if size.converted else
                                                                             " (No exchange rate found: amounts are in the instrument's currency.)"))
    if size.actual_risk > 0 and not size.too_small:
        ex["rr_money_text"] = (f"You risk {fmt_money(size.actual_risk, m)} to make {fmt_money(size.gain_target1, m)} "
                               f"at target 1 ({fmt_money(size.gain_target2, m)} at target 2)")
    return c
