import pandas as pd

from analysis.levels import pivot_points, support_resistance
from analysis.patterns import detect_at
from analysis.technical import analyse_frame, analyse_symbol, bias_label
from data.symbols import parse_symbol
from tests.conftest import FakeData, make_ohlcv


def test_uptrend_is_bullish_downtrend_is_bearish():
    up = analyse_frame(make_ohlcv(400, drift=0.004, seed=1), "1d")
    down = analyse_frame(make_ohlcv(400, drift=-0.004, seed=1), "1d")
    assert up.bias == "bullish" and up.trend == "uptrend"
    assert down.bias == "bearish" and down.trend == "downtrend"
    assert up.reasons and -100 <= up.score <= 100


def test_bias_label_thresholds():
    assert bias_label(25) == "bullish" and bias_label(-25) == "bearish" and bias_label(5) == "neutral"


def test_support_below_resistance_above_price():
    df = make_ohlcv(400, seed=3)
    sr = support_resistance(df)
    price = df.close.iloc[-1]
    assert all(l.price < price for l in sr["supports"])
    assert all(l.price > price for l in sr["resistances"])
    assert set(pivot_points(df)) >= {"P", "R1", "S1"}


def test_bullish_engulfing_detected():
    idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    df = pd.DataFrame({"open": [10, 10.0, 9.4], "high": [10.2, 10.1, 10.6], "low": [9.8, 9.4, 9.3],
                       "close": [10.1, 9.5, 10.5], "volume": [1, 1, 1]}, index=idx)
    names = [n for n, _ in detect_at(df, 2)]
    assert "Bullish Engulfing" in names


def test_multi_timeframe_with_fake_data():
    sig = analyse_symbol(parse_symbol("EUR/USD"), data=FakeData(drift=0.003))
    assert set(sig.timeframes) == {"1h", "4h", "1d", "1wk"}
    assert sig.alignment in ("aligned", "mixed", "conflicting")
    d = sig.as_dict(compact=True)
    assert "pivots" not in d["timeframes"]["1d"]
