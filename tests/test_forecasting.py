import numpy as np
import pytest

from forecasting import metrics as M
from forecasting.backtest import load_result, run_backtest, save_result, trust_label
from forecasting.features import build_inputs, future_index
from forecasting.models import ForecastPath, NaiveForecaster
from forecasting.service import _prob_up, forecast_symbol
from data.symbols import parse_symbol
from tests.conftest import FakeData, make_ohlcv


class PerfectForecaster:
    """Cheats by reading the future. Used to check the backtest is wired correctly."""

    name = "perfect"

    def __init__(self, df):
        self.df = df

    def forecast(self, contexts, horizon, past_only_covariates=None):
        out = []
        closes = self.df.close.to_numpy()
        for c in contexts:
            last = np.atleast_2d(c)[0][-1]
            i = int(np.where(np.isclose(closes, last))[0][-1])
            fut = closes[i + 1 : i + 1 + horizon]
            out.append(ForecastPath(fut, np.repeat(fut[:, None], 9, axis=1)))
        return out


def test_metrics():
    assert M.mae([1, 2], [2, 4]) == 1.5
    assert M.mape([100, 200], [110, 180]) == pytest.approx(10.0)
    assert M.directional_accuracy([1, 1, 1], [2, 0, 2], [3, 0.5, 0.5]) == pytest.approx(200 / 3)
    assert M.coverage([1, 5], [0, 0], [2, 2]) == 50.0


def test_naive_forecaster_shapes_and_monotone_quantiles():
    p = NaiveForecaster().forecast([make_ohlcv(300).close.to_numpy()], 10)[0]
    assert p.median.shape == (10,) and p.quantiles.shape == (10, 9)
    assert (np.diff(p.quantiles, axis=1) >= 0).all()
    assert (p.q90 - p.q10)[-1] > (p.q90 - p.q10)[0]  # bands widen with horizon


def test_backtest_perfect_model_beats_naive():
    df = make_ohlcv(500, drift=0.002, seed=5)
    r = run_backtest(df, PerfectForecaster(df), horizon=5, n_windows=20, context_length=256)
    assert r.mae == pytest.approx(0, abs=1e-9)
    assert r.directional_accuracy > 90 and r.skill_vs_naive == pytest.approx(1.0)


def test_backtest_naive_has_zero_skill_and_persists(tmp_path):
    df = make_ohlcv(500, seed=6)
    r = run_backtest(df, NaiveForecaster(), horizon=5, n_windows=20, context_length=256, symbol="TEST", timeframe="1d")
    assert r.skill_vs_naive == pytest.approx(0.0) and r.trust.startswith("very low")
    save_result(r)
    assert load_result("TEST", "1d", 5).mae == r.mae


def test_no_lookahead_in_inputs():
    df = make_ohlcv(300)
    ctx, cov, names = build_inputs(df, 100, use_volume=True, end=200)
    assert ctx[-1] == df.close.iloc[199] and len(ctx) == 100
    assert cov.shape == (1, 100) and names == ["close"]


def test_trust_label_and_prob_up():
    assert trust_label(0.1, 60, 80, 30) == "moderate"
    assert trust_label(-0.1, 50, 80, 30).startswith("very low")
    q = np.array([90, 92, 94, 96, 100, 104, 106, 108, 110.0])
    assert _prob_up(q, 100) == pytest.approx(0.5)
    assert _prob_up(q, 80) == 0.9


def test_forecast_symbol_with_fake_data():
    fc = forecast_symbol(parse_symbol("EUR/USD"), "1d", 5, data=FakeData(), forecaster=NaiveForecaster())
    assert len(fc.median) == 5 and len(fc.dates) == 5 and 0 <= fc.prob_up <= 1
    assert fc.q10[-1] <= fc.median[-1] <= fc.q90[-1]


def test_future_index_business_days():
    df = make_ohlcv(10)
    idx = future_index(df.index, 5, "1d")
    assert all(d.weekday() < 5 for d in idx)
