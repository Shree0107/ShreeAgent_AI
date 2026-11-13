"""High-level forecasting API used by the agent, the UI and the scanner."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from config.settings import get_settings
from data.symbols import Symbol, related_tickers
from forecasting.backtest import BacktestResult, load_result, run_backtest, save_result
from forecasting.features import build_inputs, future_index
from forecasting.models import Forecaster, get_forecaster

log = logging.getLogger(__name__)


@dataclass
class ForecastResult:
    symbol: str
    timeframe: str
    horizon: int
    model: str
    last_close: float
    last_time: str
    dates: list[str]
    median: list[float]
    q10: list[float]
    q25: list[float]
    q75: list[float]
    q90: list[float]
    expected_change_pct: float
    prob_up: float
    variates: list[str] = field(default_factory=list)
    backtest: dict | None = None

    def as_dict(self, compact: bool = False) -> dict:
        d = asdict(self)
        if compact:  # agent only needs the end points, not every step
            for k in ("dates", "median", "q10", "q25", "q75", "q90"):
                d[k] = [d[k][0], d[k][-1]] if d[k] else []
        return d


def _prob_up(quantile_row: np.ndarray, last: float) -> float:
    """P(price_end > last), interpolated from the 9 quantiles of the final step."""
    qs = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    vals = np.sort(quantile_row)
    if last <= vals[0]:
        return 0.9
    if last >= vals[-1]:
        return 0.1
    return float(1 - np.interp(last, vals, qs))


def _related(symbol: Symbol, timeframe: str, data) -> dict[str, pd.DataFrame]:
    out = {}
    for t in related_tickers(symbol):
        df = data.get_ohlcv_ticker(t, timeframe)
        if df is not None:
            out[t] = df
    return out


def forecast_symbol(
    symbol: Symbol,
    timeframe: str = "1d",
    horizon: int = 10,
    multivariate: bool = True,
    data=None,
    forecaster: Forecaster | None = None,
) -> ForecastResult:
    from data.service import get_data_service

    data = data or get_data_service()
    forecaster = forecaster or get_forecaster()
    df = data.get_ohlcv(symbol, timeframe)
    related = _related(symbol, timeframe, data) if multivariate else {}
    use_vol = multivariate and symbol.has_real_volume
    ctx, cov, names = build_inputs(df, get_settings().timesfm_context_length, related, use_vol)
    path = forecaster.forecast([ctx], horizon, [cov] if cov is not None else None)[0]

    last = float(df["close"].iloc[-1])
    fidx = future_index(df.index, horizon, timeframe)
    bt = load_result(symbol.ticker, timeframe, horizon)
    r = lambda a: [round(float(x), 6) for x in a]
    return ForecastResult(
        symbol=symbol.ticker, timeframe=timeframe, horizon=horizon, model=forecaster.name,
        last_close=last, last_time=df.index[-1].isoformat(), dates=[d.isoformat() for d in fidx],
        median=r(path.median), q10=r(path.q10), q25=r(path.q25), q75=r(path.q75), q90=r(path.q90),
        expected_change_pct=round((float(path.median[-1]) / last - 1) * 100, 3),
        prob_up=round(_prob_up(path.quantiles[-1], last), 3), variates=names,
        backtest=bt.as_dict() if bt else None,
    )


def backtest_symbol(
    symbol: Symbol,
    timeframe: str = "1d",
    horizon: int = 10,
    n_windows: int = 30,
    multivariate: bool = True,
    data=None,
    forecaster: Forecaster | None = None,
    save: bool = True,
) -> BacktestResult:
    from data.service import get_data_service

    data = data or get_data_service()
    forecaster = forecaster or get_forecaster()
    df = data.get_ohlcv(symbol, timeframe)
    related = _related(symbol, timeframe, data) if multivariate else {}
    res = run_backtest(
        df, forecaster, horizon, n_windows=n_windows, related=related,
        use_volume=multivariate and symbol.has_real_volume, symbol=symbol.ticker, timeframe=timeframe,
    )
    if save:
        save_result(res)
    return res
