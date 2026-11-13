import numpy as np
import pandas as pd

from analysis import indicators as ind
from tests.conftest import make_ohlcv


def test_sma_matches_rolling_mean():
    s = pd.Series(np.arange(1, 31, dtype=float))
    assert ind.sma(s, 5).iloc[-1] == np.mean(np.arange(26, 31))


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.linspace(1, 50, 100))
    assert ind.rsi(up).iloc[-1] == 100.0
    r = ind.rsi(make_ohlcv(300).close).dropna()
    assert r.between(0, 100).all()


def test_macd_hist_is_line_minus_signal():
    m = ind.macd(make_ohlcv(200).close).dropna()
    assert np.allclose(m.macd_hist, m.macd - m.macd_signal)


def test_bollinger_order_and_atr_positive():
    df = make_ohlcv(200)
    bb = ind.bollinger(df.close).dropna()
    assert (bb.bb_upper >= bb.bb_mid).all() and (bb.bb_mid >= bb.bb_lower).all()
    assert (ind.atr(df).dropna() > 0).all()


def test_adx_and_stochastic_ranges():
    df = make_ohlcv(300, drift=0.003)
    a = ind.adx(df).dropna()
    st = ind.stochastic(df).dropna()
    assert a.adx.between(0, 100).all()
    assert st.stoch_k.between(0, 100).all()


def test_add_all_skips_volume_for_fx():
    df = make_ohlcv(250, volume=False)
    out = ind.add_all(df, has_volume=False)
    assert "vwap" not in out and "rsi_14" in out
    out2 = ind.add_all(make_ohlcv(250), has_volume=True)
    assert "vwap" in out2 and out2.vwap.dropna().gt(0).all()
