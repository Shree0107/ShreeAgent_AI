"""Forecaster interface, the TimesFM-3 implementation and a naive baseline.

Every forecaster takes a batch of contexts (1-D arrays, or 2-D (n_variates, length) arrays where row 0
is the target) and returns median + q10..q90 quantile paths for the target series.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from config.settings import get_settings

log = logging.getLogger(__name__)

QUANTILES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


@dataclass
class ForecastPath:
    median: np.ndarray      # (horizon,)
    quantiles: np.ndarray   # (horizon, 9), columns follow QUANTILES

    @property
    def q10(self) -> np.ndarray:
        return self.quantiles[:, 0]

    @property
    def q90(self) -> np.ndarray:
        return self.quantiles[:, -1]

    @property
    def q25(self) -> np.ndarray:  # interpolate between q0.2 and q0.3
        return (self.quantiles[:, 1] + self.quantiles[:, 2]) / 2

    @property
    def q75(self) -> np.ndarray:
        return (self.quantiles[:, 6] + self.quantiles[:, 7]) / 2


class Forecaster(Protocol):
    name: str

    def forecast(
        self,
        contexts: list[np.ndarray],
        horizon: int,
        past_only_covariates: list[np.ndarray | None] | None = None,
    ) -> list[ForecastPath]: ...


def pick_device(pref: str = "auto") -> str:
    """'auto' -> cuda if available, else mps (Apple), else cpu."""
    if pref and pref != "auto":
        return pref
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


class TimesFMForecaster:
    """Google TimesFM-3 (zero-shot, multivariate). Weights load lazily on first use and are shared."""

    name = "timesfm-3"
    _model = None
    _lock = threading.Lock()

    def __init__(self, checkpoint: str | None = None, device: str | None = None, batch_size: int | None = None):
        s = get_settings()
        self.checkpoint = checkpoint or s.timesfm_checkpoint
        self.device = pick_device(device or s.timesfm_device)
        self.batch_size = batch_size or s.timesfm_batch_size
        self.token = s.hf_token or None

    def _load(self):
        with TimesFMForecaster._lock:
            if TimesFMForecaster._model is None:
                try:
                    from timesfm3 import TimesFM3Forecaster
                except ImportError as e:
                    raise RuntimeError("timesfm is not installed. Run: pip install \"timesfm[torch]\"") from e
                log.info("Loading TimesFM-3 (%s) on %s, first run downloads ~1.3 GB", self.checkpoint, self.device)
                TimesFMForecaster._model = TimesFM3Forecaster.from_pretrained(
                    self.checkpoint, device=self.device, token=self.token, per_core_batch_size=self.batch_size
                )
                log.info("TimesFM-3 loaded")
        return TimesFMForecaster._model

    def forecast(self, contexts, horizon, past_only_covariates=None) -> list[ForecastPath]:
        model = self._load()
        outs = model.predict_batch(
            contexts=[np.asarray(c, dtype=np.float32) for c in contexts],
            horizon=horizon,
            past_only_covariates=past_only_covariates,
            return_quantiles=True,
            make_positive=True,   # prices can't go negative
            sort_quantiles=True,
        )
        paths = []
        for o in outs:
            q = np.asarray(o.quantiles)
            if q.ndim == 3:   # multivariate: (n_variates, horizon, 9), row 0 is the target
                q = q[0]
            paths.append(ForecastPath(median=q[:, 4].copy(), quantiles=q))
        return paths


class NaiveForecaster:
    """Random-walk baseline: tomorrow = today, with intervals from historical log-return volatility.

    Used as the benchmark in backtests, and as a fallback when TimesFM is unavailable.
    """

    name = "naive"

    def forecast(self, contexts, horizon, past_only_covariates=None) -> list[ForecastPath]:
        from statistics import NormalDist

        z = np.array([NormalDist().inv_cdf(q) for q in QUANTILES])
        out = []
        for c in contexts:
            y = np.atleast_2d(np.asarray(c, dtype=float))[0]
            last = y[-1]
            r = np.diff(np.log(np.clip(y[-250:], 1e-12, None)))
            sigma = float(np.std(r)) if len(r) > 2 else 0.0
            steps = np.sqrt(np.arange(1, horizon + 1))[:, None]
            q = last * np.exp(z[None, :] * sigma * steps)
            out.append(ForecastPath(median=np.full(horizon, last), quantiles=q))
        return out


_default: Forecaster | None = None


def get_forecaster(name: str | None = None) -> Forecaster:
    global _default
    name = name or get_settings().forecast_model
    if name == "naive":
        return NaiveForecaster()
    if _default is None:
        _default = TimesFMForecaster()
    return _default
