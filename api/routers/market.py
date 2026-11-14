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
    live = _live_state(sym.ticker)
    if before is None and live is not None:
        # The live feed's current candle is newer than the (cached) history: put it on the end.
        cur = live.agg.current(tf)
        if cur and bars and cur["time"] >= bars[-1]["time"]:
            bars = [b for b in bars if b["time"] != cur["time"]] + [clean(cur)]
    return {"symbol": sym.ticker, "tf": tf, "source": (live.source if live and live.source == "oanda" else None)
            or df.attrs.get("source", ""), "candles": bars, "has_more": len(older) > limit,
            "live_status": live.status if live else None}


def _live_state(ticker: str):
    from data.stream.live import get_live

    live = get_live()
    return live.states.get(ticker) if live else None


@router.get("/live/status")
def live_status():
    from data.stream.live import get_live

    live = get_live()
    return clean(live.status() if live else {"feeds": {}, "symbols": {}, "oanda_configured": False})


@router.get("/quote")
def quote(symbol: str, data=Depends(get_data)):
    sym = symbol_or_404(symbol)
    try:
        q = clean(data.last_price(sym))
        st = _live_state(sym.ticker)
        if st is not None and st.mid is not None and st.status in ("live", "delayed"):
            # Same % base (previous day close) with the live price.
            base = q["price"] / (1 + q["change_pct"] / 100) if q.get("change_pct") is not None else None
            q.update({"price": st.mid, "bid": st.bid, "ask": st.ask, "spread_pips": st.spread_pips,
                      "source": "oanda" if st.source == "oanda" else q["source"], "live_status": st.status,
                      "change_pct": (st.mid / base - 1) * 100 if base else q["change_pct"]})
        return q
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
