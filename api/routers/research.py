"""Fundamentals, news, events, forecasts and backtests."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.deps import get_data, symbol_or_404
from api.serialize import clean
from data.providers.base import TIMEFRAMES

router = APIRouter(prefix="/api", tags=["research"])


@router.get("/fundamentals")
def fundamentals(symbol: str, data=Depends(get_data)):
    sym = symbol_or_404(symbol)
    try:
        if sym.is_fx:
            from analysis.macro_fx import analyse_fx

            return clean({"kind": "fx", **analyse_fx(sym, data=data).as_dict()})
        from analysis.fundamental import analyse_stock

        return clean({"kind": "stock", **analyse_stock(sym, data=data).as_dict()})
    except Exception as e:
        raise HTTPException(502, f"Fundamentals unavailable: {e}") from e


@router.get("/news")
def news(symbol: str, days: int = Query(7, ge=1, le=30), data=Depends(get_data)):
    from analysis.sentiment import analyse_news

    return clean(analyse_news(symbol_or_404(symbol), days=days, data=data).as_dict())


@router.get("/events")
def events(currencies: str = "USD,EUR", days: int = Query(14, ge=1, le=60), data=Depends(get_data)):
    from signals.events import is_major, plain_title

    out = []
    for e in data.upcoming_events([c.strip().upper() for c in currencies.split(",") if c.strip()], days):
        out.append({"date": e.date, "currency": e.currency, "title": e.title, "plain": plain_title(e.title, e.currency),
                    "impact": e.impact, "major": is_major(e.title), "source": e.source})
    return clean(out)


@router.post("/forecast")
def run_forecast(request: Request, symbol: str, tf: str = "1d", horizon: int = Query(10, ge=1, le=128),
                 multivariate: bool = True, data=Depends(get_data)):
    """Start (or join) a TimesFM forecast job. Poll /api/jobs/{id} for the result."""
    if tf not in TIMEFRAMES:
        raise HTTPException(400, f"timeframe must be one of {list(TIMEFRAMES)}")
    sym = symbol_or_404(symbol)

    def work():
        from forecasting.service import forecast_symbol

        return forecast_symbol(sym, tf, horizon, multivariate=multivariate, data=data).as_dict()

    return request.app.state.jobs.submit("forecast", f"forecast:{sym.ticker}:{tf}:{horizon}:{multivariate}",
                                         work).public(with_result=False)


@router.get("/backtests")
def backtests(symbol: str, tf: str = "1d"):
    from config.settings import get_settings
    from forecasting.backtest import load_result

    sym = symbol_or_404(symbol)
    hs = sorted(set(get_settings().horizons + [5, 10, 30]))
    return clean({h: (r.as_dict() if (r := load_result(sym.ticker, tf, h)) else None) for h in hs})


@router.post("/backtests")
def run_backtest(request: Request, symbol: str, tf: str = "1d", horizon: int = 10, windows: int = Query(30, ge=5, le=60),
                 multivariate: bool = True, data=Depends(get_data)):
    sym = symbol_or_404(symbol)

    def work():
        from forecasting.service import backtest_symbol

        return backtest_symbol(sym, tf, horizon, n_windows=windows, multivariate=multivariate, data=data).as_dict()

    return request.app.state.jobs.submit("backtest", f"backtest:{sym.ticker}:{tf}:{horizon}", work).public(with_result=False)
