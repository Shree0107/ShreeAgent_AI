"""Simple baseline forecasts the model must beat to be worth listening to.

- naive ("price stays the same"): every future step equals the last close.
- drift ("the recent trend continues"): a straight line with the average change per candle over the
  last `window` candles.
- moving average ("price returns to its average"): every future step equals the mean of the last
  `window` closes.

All functions take a 1-D array of past closes (oldest first) and return a (horizon,) array.
"""
from __future__ import annotations

import numpy as np

DRIFT_WINDOW = 50
MA_WINDOW = 20

LABELS = {
    "naive": "Price stays the same",
    "drift": "Recent trend continues",
    "moving_average": "Back to the 20-candle average",
}


def _y(closes) -> np.ndarray:
    y = np.atleast_2d(np.asarray(closes, dtype=float))[0]
    if y.size == 0:
        raise ValueError("no closes")
    return y


def naive_path(closes, horizon: int) -> np.ndarray:
    y = _y(closes)
    return np.full(horizon, y[-1])


def drift_path(closes, horizon: int, window: int = DRIFT_WINDOW) -> np.ndarray:
    y = _y(closes)
    w = min(window, len(y))
    slope = (y[-1] - y[-w]) / (w - 1) if w > 1 else 0.0
    return y[-1] + slope * np.arange(1, horizon + 1)


def moving_average_path(closes, horizon: int, window: int = MA_WINDOW) -> np.ndarray:
    y = _y(closes)
    return np.full(horizon, float(np.mean(y[-window:])))


BASELINES = {"naive": naive_path, "drift": drift_path, "moving_average": moving_average_path}


def baseline_paths(closes, horizon: int) -> dict[str, np.ndarray]:
    return {name: fn(closes, horizon) for name, fn in BASELINES.items()}
