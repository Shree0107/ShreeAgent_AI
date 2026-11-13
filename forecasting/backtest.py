"""Rolling-origin backtest of a forecaster vs. the naive random-walk baseline.

For each of `n_windows` origins (spaced `stride` bars apart, ending `horizon` bars before the last bar),
the model sees only data up to the origin and forecasts `horizon` bars ahead. We then compare:
  - MAE / MAPE of the full forecast path
  - directional accuracy of the end-of-horizon move (50% = coin flip)
  - coverage of the 10-90% interval (should be ~80% if the intervals are calibrated)
  - MAE skill vs. naive: 1 - MAE_model / MAE_naive (> 0 means the model beats "no change")
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config.settings import get_settings
from forecasting import metrics as M
from forecasting.features import build_inputs
from forecasting.models import Forecaster, NaiveForecaster

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    horizon: int
    model: str
    n_windows: int
    mae: float
    mape: float
    directional_accuracy: float
    coverage_80: float
    naive_mae: float
    naive_mape: float
    skill_vs_naive: float
    trust: str
    run_at: str
    multivariate: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def trust_label(skill: float, dir_acc: float, cov: float, n: int) -> str:
    """Rough rule of thumb, so the agent knows how much weight to give the forecast."""
    if n < 10:
        return "insufficient data"
    if skill > 0.05 and dir_acc >= 55 and 65 <= cov <= 95:
        return "moderate"
    if skill > 0.0 and dir_acc >= 52:
        return "low"
    return "very low (no better than naive)"


def run_backtest(
    df: pd.DataFrame,
    forecaster: Forecaster,
    horizon: int,
    n_windows: int = 30,
    stride: int | None = None,
    context_length: int | None = None,
    related: dict | None = None,
    use_volume: bool = False,
    symbol: str = "",
    timeframe: str = "",
) -> BacktestResult:
    ctx_len = context_length or get_settings().timesfm_context_length
    stride = stride or max(1, horizon // 2)
    n = len(df)
    last_origin = n - horizon
    origins = [last_origin - i * stride for i in range(n_windows)]
    origins = sorted(o for o in origins if o >= 64)
    if len(origins) < 3:
        raise ValueError(f"Not enough history for a backtest ({n} bars, horizon {horizon})")

    contexts, covs, actuals, lasts = [], [], [], []
    for o in origins:
        ctx, cov, _ = build_inputs(df, ctx_len, related, use_volume, end=o)
        contexts.append(ctx)
        covs.append(cov)
        actuals.append(df["close"].iloc[o : o + horizon].to_numpy())
        lasts.append(df["close"].iloc[o - 1])

    has_cov = any(c is not None for c in covs)
    preds = forecaster.forecast(contexts, horizon, covs if has_cov else None)
    naive = NaiveForecaster().forecast([np.atleast_2d(c)[0] for c in contexts], horizon)

    A = np.concatenate(actuals)
    P = np.concatenate([p.median for p in preds])
    LO = np.concatenate([p.q10 for p in preds])
    HI = np.concatenate([p.q90 for p in preds])
    NP = np.concatenate([p.median for p in naive])

    mae, naive_mae = M.mae(A, P), M.mae(A, NP)
    skill = 1 - mae / naive_mae if naive_mae > 0 else 0.0
    dir_acc = M.directional_accuracy(lasts, [a[-1] for a in actuals], [p.median[-1] for p in preds])
    cov80 = M.coverage(A, LO, HI)
    return BacktestResult(
        symbol=symbol, timeframe=timeframe, horizon=horizon, model=forecaster.name, n_windows=len(origins),
        mae=round(mae, 6), mape=round(M.mape(A, P), 3), directional_accuracy=round(dir_acc, 1),
        coverage_80=round(cov80, 1), naive_mae=round(naive_mae, 6), naive_mape=round(M.mape(A, NP), 3),
        skill_vs_naive=round(skill, 3), trust=trust_label(skill, dir_acc, cov80, len(origins)),
        run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        multivariate=bool(related) or use_volume,
    )


# ---------- persistence: the agent reads the latest result ----------
def _path(symbol: str, timeframe: str, horizon: int):
    d = get_settings().cache_dir / "backtests"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{symbol.replace('/', '').replace('^', '')}_{timeframe}_h{horizon}.json"


def save_result(r: BacktestResult) -> None:
    _path(r.symbol, r.timeframe, r.horizon).write_text(json.dumps(r.as_dict(), indent=2), encoding="utf-8")


def load_result(symbol: str, timeframe: str, horizon: int) -> BacktestResult | None:
    p = _path(symbol, timeframe, horizon)
    if not p.exists():
        return None
    try:
        return BacktestResult(**json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None
