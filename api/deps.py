"""Shared dependencies. Tests override `get_data` / `get_history` / `get_watchlist` with offline fakes."""
from __future__ import annotations

from fastapi import HTTPException

from data.symbols import Symbol, parse_symbol, resolve


def get_data():
    from data.service import get_data_service

    return get_data_service()


def get_history():
    from signals.history import SignalHistory

    return SignalHistory()


def get_watchlist():
    from data.watchlist import Watchlist

    return Watchlist()


def symbol_or_404(text: str) -> Symbol:
    """Fast path for canonical tickers (no network), search fallback for names like 'apple'."""
    sym = parse_symbol(text)
    if sym and (sym.is_fx or "." in sym.ticker or sym.asset_class == "index" or text.isupper()):
        return sym
    try:
        return resolve(text)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
