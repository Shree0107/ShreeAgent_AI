"""Technical indicators implemented in pandas (no TA-Lib or C build needed).

All functions take a DataFrame with open/high/low/close/volume columns and return Series/DataFrames
aligned to its index. Wilder smoothing is used where the original definition uses it (RSI, ATR, ADX).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = _wilder(delta.clip(lower=0), n)
    loss = _wilder(-delta.clip(upper=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # No losses in the window means RSI = 100.
    return out.where(loss != 0, 100.0).where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    return pd.DataFrame(
        {"bb_mid": mid, "bb_upper": upper, "bb_lower": lower,
         "bb_pctb": (close - lower) / (upper - lower), "bb_width": (upper - lower) / mid}
    )


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return _wilder(true_range(df), n)


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3, smooth: int = 3) -> pd.DataFrame:
    lo, hi = df["low"].rolling(k).min(), df["high"].rolling(k).max()
    raw = 100 * (df["close"] - lo) / (hi - lo).replace(0, np.nan)
    k_line = raw.rolling(smooth).mean()
    return pd.DataFrame({"stoch_k": k_line, "stoch_d": k_line.rolling(d).mean()})


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = _wilder(true_range(df), n)
    plus_di = 100 * _wilder(plus_dm, n) / tr
    minus_di = 100 * _wilder(minus_dm, n) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame({"adx": _wilder(dx, n), "plus_di": plus_di, "minus_di": minus_di})


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def vwap(df: pd.DataFrame, intraday: bool, n: int = 20) -> pd.Series:
    """Session-anchored VWAP for intraday bars, rolling n-bar VWAP for daily/weekly bars."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = tp * df["volume"]
    if intraday:
        day = df.index.normalize()
        return pv.groupby(day).cumsum() / df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return pv.rolling(n).sum() / df["volume"].rolling(n).sum().replace(0, np.nan)


def add_all(df: pd.DataFrame, has_volume: bool = True, intraday: bool = False) -> pd.DataFrame:
    """Return a copy of df with every indicator column added."""
    out = df.copy()
    c = out["close"]
    for n in (20, 50, 200):
        out[f"sma_{n}"] = sma(c, n)
    for n in (9, 21, 50, 200):
        out[f"ema_{n}"] = ema(c, n)
    out["rsi_14"] = rsi(c)
    out = out.join(macd(c)).join(bollinger(c)).join(stochastic(out)).join(adx(out))
    out["atr_14"] = atr(out)
    if has_volume and out["volume"].sum() > 0:
        out["vol_sma_20"] = sma(out["volume"], 20)
        out["obv"] = obv(out)
        out["vwap"] = vwap(out, intraday)
    return out
