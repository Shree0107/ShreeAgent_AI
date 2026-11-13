"""Forecast accuracy metrics."""
from __future__ import annotations

import numpy as np


def mae(actual, pred) -> float:
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(pred))))


def mape(actual, pred) -> float:
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    mask = a != 0
    return float(np.mean(np.abs((a[mask] - p[mask]) / a[mask])) * 100)


def directional_accuracy(last, actual_end, pred_end) -> float:
    """Share of windows where the forecast got the sign of (end - last) right. Flat moves count as misses."""
    da = np.sign(np.asarray(actual_end) - np.asarray(last))
    dp = np.sign(np.asarray(pred_end) - np.asarray(last))
    return float(np.mean((da == dp) & (da != 0)) * 100)


def coverage(actual, lo, hi) -> float:
    a = np.asarray(actual)
    return float(np.mean((a >= np.asarray(lo)) & (a <= np.asarray(hi))) * 100)
