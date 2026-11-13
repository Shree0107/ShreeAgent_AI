"""Build model inputs: target close series, optional related assets (extra variates) and volume (covariate)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_inputs(
    df: pd.DataFrame,
    context_length: int,
    related: dict[str, pd.DataFrame] | None = None,
    use_volume: bool = False,
    end: int | None = None,
) -> tuple[np.ndarray, np.ndarray | None, list[str]]:
    """Return (context, past_only_covariates, variate_names).

    context: 1-D close prices, or 2-D (1 + n_related, L) with the target in row 0.
    Related series are aligned to the target's timestamps (forward-filled, never using future data).
    end: index position (exclusive) for backtests. Data at or after `end` is never used.
    """
    d = df.iloc[:end] if end is not None else df
    d = d.tail(context_length)
    names = ["close"]
    rows = [d["close"].to_numpy(dtype=np.float64)]
    for name, rdf in (related or {}).items():
        if rdf is None or rdf.empty:
            continue
        aligned = rdf["close"].reindex(d.index, method="ffill")
        if aligned.notna().mean() < 0.8:
            continue  # not enough overlap (e.g. different trading hours)
        rows.append(aligned.ffill().bfill().to_numpy(dtype=np.float64))
        names.append(name)
    context = rows[0] if len(rows) == 1 else np.vstack(rows)

    cov = None
    if use_volume and "volume" in d and d["volume"].sum() > 0:
        v = np.log1p(d["volume"].to_numpy(dtype=np.float64))
        cov = ((v - v.mean()) / (v.std() + 1e-9))[None, :]
    return context, cov, names


def future_index(index: pd.DatetimeIndex, horizon: int, timeframe: str) -> pd.DatetimeIndex:
    """Timestamps for the forecast steps. Business days for daily data. Calendar steps otherwise (approximate)."""
    last = index[-1]
    if timeframe == "1d":
        return pd.bdate_range(last + pd.Timedelta(days=1), periods=horizon, tz=last.tz)
    step = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "1wk": pd.Timedelta(weeks=1)}[timeframe]
    return pd.DatetimeIndex([last + step * (i + 1) for i in range(horizon)])
