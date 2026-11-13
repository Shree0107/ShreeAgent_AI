"""Instrument conventions: pip size, price precision, currencies, money formatting, FX conversion."""
from __future__ import annotations

import logging

from data.symbols import Symbol, parse_symbol

log = logging.getLogger(__name__)

CURRENCY_SIGNS = {"EUR": "€", "USD": "$", "GBP": "£", "INR": "₹", "JPY": "¥", "CHF": "CHF ", "PLN": "zł "}


def pip_size(symbol: Symbol) -> float | None:
    """Size of one pip. None for stocks (they're measured in price and %)."""
    if not symbol.is_fx:
        return None
    if symbol.base == "XAU":
        return 0.1
    if symbol.base == "XAG":
        return 0.01
    return 0.01 if symbol.quote == "JPY" else 0.0001


def price_decimals(symbol: Symbol, price: float) -> int:
    if symbol.is_fx:
        if symbol.base in ("XAU", "XAG"):
            return 2 if symbol.base == "XAU" else 3
        return 3 if symbol.quote == "JPY" else 5
    return 2


def round_price(symbol: Symbol, x: float, price: float | None = None) -> float:
    return round(float(x), price_decimals(symbol, price or x))


def fmt_price(symbol: Symbol, x: float | None) -> str:
    if x is None:
        return "n/a"
    nd = price_decimals(symbol, x)
    # Forex: show 4 decimals (1.0912) unless the 5th digit matters; that is how most apps quote it.
    if symbol.is_fx and nd == 5 and round(x, 4) == round(x, 5):
        nd = 4
    return f"{x:,.{nd}f}"


def instrument_currency(symbol: Symbol, reported: str | None = None) -> str:
    """Currency that profit/loss is booked in for one unit of this instrument."""
    if symbol.is_fx:
        return symbol.quote
    if symbol.market in ("NSE", "BSE"):
        return "INR"
    return (reported or "USD").upper()


def fmt_money(amount: float | None, ccy: str, signed: bool = False) -> str:
    if amount is None:
        return "n/a"
    sign = ("+" if amount > 0 else "−" if amount < 0 else "") if signed else ("−" if amount < 0 else "")
    sym = CURRENCY_SIGNS.get(ccy.upper())
    body = f"{abs(amount):,.2f}" if abs(amount) < 100 else f"{abs(amount):,.0f}"
    return f"{sign}{sym}{body}" if sym else f"{sign}{body} {ccy.upper()}"


def distance(symbol: Symbol, a: float, b: float) -> float:
    """|a-b| in pips (forex) or % of a (stocks)."""
    pip = pip_size(symbol)
    if pip:
        return abs(a - b) / pip
    return abs(a - b) / a * 100 if a else 0.0


def fmt_distance(symbol: Symbol, a: float, b: float) -> str:
    d = distance(symbol, a, b)
    return f"{d:.0f} pips" if pip_size(symbol) else f"{d:.1f}%"


def conversion_rate(from_ccy: str, to_ccy: str, symbol: Symbol | None = None, price: float | None = None,
                    data=None) -> float | None:
    """How many `to_ccy` one unit of `from_ccy` is worth. None if no rate can be found.

    Uses the instrument's own price when possible (e.g. USD -> EUR from EUR/USD itself),
    otherwise the daily close of the FX pair from the data service.
    """
    f, t = from_ccy.upper(), to_ccy.upper()
    if f == t:
        return 1.0
    if symbol is not None and symbol.is_fx and price:
        if symbol.base == t and symbol.quote == f:
            return 1.0 / price
        if symbol.base == f and symbol.quote == t:
            return price
    if data is None:
        from data.service import get_data_service

        data = get_data_service()
    for pair, invert in ((f"{f}/{t}", False), (f"{t}/{f}", True)):
        sym = parse_symbol(pair)
        if not sym:
            continue
        try:
            last = float(data.get_ohlcv(sym, "1d")["close"].iloc[-1])
            if last > 0:
                return 1.0 / last if invert else last
        except Exception as e:  # rate not available from any provider
            log.info("FX rate %s unavailable: %s", pair, e)
    return None
