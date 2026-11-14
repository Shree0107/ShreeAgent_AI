"""Symbols, candles, quotes, technical analysis."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_data, symbol_or_404
from api.serialize import candles as to_candles
from api.serialize import clean
from data.providers.base import TIMEFRAMES

router = APIRouter(prefix="/api", tags=["market"])


def symbol_info(sym) -> dict:
    from signals.market import pip_size, price_decimals
    from signals.service import display_name

    return {"ticker": sym.ticker, "name": display_name(sym), "asset_class": sym.asset_class, "market": sym.market,
            "is_fx": sym.is_fx, "has_volume": sym.has_real_volume, "pip_size": pip_size(sym),
            "decimals": price_decimals(sym, 1.0 if sym.is_fx else 100.0), "investing_url": sym.investing_url}


@router.get("/symbols/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(8, le=20)):
    from data.symbols import search_symbols

    return [{**symbol_info(c.symbol), "exchange": c.exchange} for c in search_symbols(q, limit)]


@router.get("/symbols/resolve")
def resolve_symbol(symbol: str):
    return symbol_info(symbol_or_404(symbol))


@router.get("/timeframes")
def timeframes():
    return list(TIMEFRAMES)


@router.get("/candles")
def get_candles(symbol: str, tf: str = "1d", limit: int = Query(500, ge=10, le=5000), before: int | None = None,
                data=Depends(get_data)):
    if tf not in TIMEFRAMES:
        raise HTTPException(400, f"timeframe must be one of {list(TIMEFRAMES)}")
    sym = symbol_or_404(symbol)
    try:
        df = data.get_ohlcv(sym, tf)
    except Exception as e:
        raise HTTPException(502, f"Price data unavailable: {e}") from e
    import pandas as pd

    older = df if before is None else df[df.index < pd.Timestamp(before, unit="s", tz="UTC")]
    bars = to_candles(older, limit)
    return {"symbol": sym.ticker, "tf": tf, "source": df.attrs.get("source", ""), "candles": bars,
            "has_more": len(older) > limit}


@router.get("/quote")
def quote(symbol: str, data=Depends(get_data)):
    sym = symbol_or_404(symbol)
    try:
        return clean(data.last_price(sym))
    except Exception as e:
        raise HTTPException(502, f"Price data unavailable: {e}") from e


@router.get("/technical")
def technical(symbol: str, data=Depends(get_data)):
    from analysis.technical import analyse_symbol

    sym = symbol_or_404(symbol)
    try:
        return clean(analyse_symbol(sym, data=data).as_dict(compact=True))
    except Exception as e:
        raise HTTPException(502, f"Technical analysis failed: {e}") from e
