"""Automatic chart structure detectors, on synthetic price paths built to contain each pattern."""
import numpy as np
import pandas as pd
import pytest

from analysis.structure import liquidity as liq
from analysis.structure.lines import channels, trendlines
from analysis.structure.market import fibonacci, label_swings, structure_events, trend_from_labels
from analysis.structure.overlay import build_overlay
from analysis.structure.patterns_chart import chart_patterns, divergences, regime
from analysis.structure.swings import known_at, zigzag
from analysis.structure.zones import fair_value_gaps, order_blocks, sr_zones, supply_demand


def path_df(waypoints, bars_per_leg=10, wick=0.05, start="2026-01-05", freq="h", noise=0.0, seed=1):
    """Piecewise-linear closes through the waypoints, with small symmetric wicks."""
    rng = np.random.default_rng(seed)
    closes = [waypoints[0]]
    for a, b in zip(waypoints, waypoints[1:]):
        closes += list(np.linspace(a, b, bars_per_leg + 1)[1:])
    c = np.array(closes) + rng.normal(0, noise, len(closes))
    o = np.r_[c[0], c[:-1]]
    df = pd.DataFrame({"open": o, "high": np.maximum(o, c) + wick, "low": np.minimum(o, c) - wick, "close": c,
                       "volume": 0.0}, index=pd.date_range(start, periods=len(c), freq=freq, tz="UTC"))
    return df


UPTREND = [100, 106, 103, 109, 106, 112, 109, 115, 112, 118]   # higher highs + higher lows


def test_zigzag_swings_and_labels():
    df = path_df(UPTREND)
    s = label_swings(zigzag(df, 1.5))
    assert [x.kind for x in s] == ["L", "H", "L", "H", "L", "H", "L", "H", "L"][: len(s)]
    highs = [x.price for x in s if x.kind == "H"]
    assert highs == sorted(highs)                                     # each high higher than the last
    assert {x.label for x in s if x.kind == "H" and x.label} == {"HH"}
    assert {x.label for x in s if x.kind == "L" and x.label} == {"HL"}
    assert trend_from_labels(s) == "up"
    assert all(x.confirmed_at > x.idx for x in s[1:])                 # a swing is known only after it formed


def test_no_lookahead_in_swings():
    df = path_df(UPTREND)
    full = zigzag(df, 1.5)
    cut = 45
    early = zigzag(df.iloc[:cut + 1], 1.5)
    # Every swing known at bar `cut` using all data must also be found with data only up to `cut`.
    assert [(x.idx, x.kind) for x in known_at(full, cut)] == [(x.idx, x.kind) for x in early]


def test_break_of_structure_and_change_of_character():
    df = path_df([100, 106, 103, 109, 106, 112, 104, 100])      # uptrend, then breaks the last higher low
    s = label_swings(zigzag(df, 1.5))
    events, trend = structure_events(df, s)
    kinds = [(e.kind, e.direction) for e in events]
    assert ("BOS", "up") in kinds                                   # continuation breaks during the uptrend
    last_up = max(i for i, k in enumerate(kinds) if k == ("BOS", "up"))
    after = kinds[last_up + 1:]
    assert after[0] == ("CHoCH", "down")      # the first break against the uptrend = change of character
    assert all(k == ("BOS", "down") for k in after[1:]) and trend == "down"   # further breaks continue it


def test_trendline_support_in_uptrend():
    df = path_df(UPTREND)
    s = zigzag(df, 1.5)
    lines = trendlines(df, s)
    sup = [ln for ln in lines if ln.kind == "support"]
    assert sup and sup[0].slope > 0 and sup[0].touches >= 3
    # the line sits under the lows: every close is above it
    i = np.arange(sup[0].i1, len(df))
    assert np.all(df.close.to_numpy()[i] >= sup[0].price_at(i) - 0.5)


def test_parallel_channel():
    df = path_df(UPTREND)
    ch = channels(df, zigzag(df, 1.5))
    assert ch and ch[0].direction == "up"
    assert ch[0].upper_now > ch[0].lower_now and ch[0].inside_pct >= 0.8


def test_support_resistance_zones_count_touches():
    df = path_df([100, 110, 100, 110, 100, 110, 105])               # range between ~100 and ~110
    z = sr_zones(df, zigzag(df, 1.5))
    lows = [x for x in z if x.low < 101 and x.high > 99]
    highs = [x for x in z if x.low < 111 and x.high > 109]
    assert lows and highs and lows[0].touches >= 3 and highs[0].touches >= 3
    assert lows[0].kind == "support" and highs[0].kind == "resistance"   # price (105) is between them


def test_fibonacci_from_last_major_swing():
    df = path_df([100, 120, 110])
    f = fibonacci(df, zigzag(df, 1.5))
    assert f["direction"] == "up"
    r = {x["ratio"]: x["price"] for x in f["retracements"]}
    lo, hi = f["from"]["price"], f["to"]["price"]
    assert r[0.5] == pytest.approx((lo + hi) / 2)
    assert r[0.618] == pytest.approx(hi - 0.618 * (hi - lo))
    assert {x["ratio"] for x in f["extensions"]} == {1.272, 1.618}


def test_fair_value_gap_detected_and_fill_status():
    df = path_df([100, 100.5, 101], bars_per_leg=10, wick=0.02)
    # insert a gap: three bars where bar i low is well above bar i-2 high
    k = 12
    df.iloc[k, df.columns.get_loc("open")] = df.close.iloc[k - 1]
    for j, lvl in ((k, 102.0), (k + 1, 104.0)):
        df.iloc[j, :4] = [lvl - 0.3, lvl + 0.3, lvl - 0.3, lvl + 0.2]
    df.iloc[k + 2:, :4] = df.iloc[k + 2:, :4] + 3.5                  # price stays above: gap not filled
    gaps = fair_value_gaps(df, min_atr=0.1)
    assert any(g.kind == "bull_fvg" and g.status != "filled" for g in gaps)


def test_order_block_before_impulse():
    wp = [100, 104, 102, 105, 103]
    df = path_df(wp, bars_per_leg=8, wick=0.05)
    n = len(df)
    k = n - 6
    df.iloc[k, :4] = [103.4, 103.45, 102.9, 103.0]                  # bearish candle ...
    for j, step in zip(range(k + 1, n), (1.5, 3.0, 4.5, 5.5, 6.0)):  # ... then a strong rally through the highs
        c = 103 + step
        df.iloc[j, :4] = [c - 1.4, c + 0.05, c - 1.45, c]
    obs = order_blocks(df, zigzag(df, 1.5), impulse_atr=1.5)
    assert any(z.kind == "bull_ob" and z.idx == k for z in obs)


def test_supply_demand_zone():
    flat = [100, 100.05, 99.98, 100.02]
    closes = flat + [101.5, 103, 104.5, 105, 105.2] + list(np.linspace(105, 103, 8))
    o = np.r_[closes[0], closes[:-1]]
    df = pd.DataFrame({"open": o, "high": np.maximum(o, closes) + 0.05, "low": np.minimum(o, closes) - 0.05,
                       "close": closes, "volume": 0.0},
                      index=pd.date_range("2026-01-05", periods=len(closes), freq="h", tz="UTC"))
    df = pd.concat([path_df([99, 100], bars_per_leg=20, wick=0.3, start="2026-01-04"), df])
    df = df[~df.index.duplicated()].sort_index()
    sd = supply_demand(df, base_atr=1.0, depart_atr=2.0)
    assert any(z.kind == "demand" and z.low <= 100.0 <= z.high + 0.1 for z in sd)


def test_liquidity_levels_and_sweep():
    # two days of hourly data; day 2 wicks above day 1's high and closes back below = sweep (stop hunt)
    d1 = path_df([100, 102, 101], bars_per_leg=12, start="2026-03-02 00:00")
    d2 = path_df([101, 101.5], bars_per_leg=10, start="2026-03-03 00:00")
    df = pd.concat([d1.iloc[:24], d2])
    pdh = float(df.loc[df.index.normalize() == pd.Timestamp("2026-03-02", tz="UTC"), "high"].max())
    i = len(df) - 3
    df.iloc[i, :4] = [101.6, pdh + 0.3, 101.5, 101.7]                 # wick above, close back below
    levels = liq.session_levels(df)
    kinds = {lv.kind for lv in levels}
    assert {"pdh", "pdl", "asian_high", "asian_low"} <= kinds
    sw = liq.sweeps(df, levels)
    assert any(s.level_kind == "pdh" and s.direction == "up" for s in sw)


def test_equal_highs_and_round_numbers():
    df = path_df([100, 105, 101, 105.02, 101.5, 104])
    eq = liq.equal_levels(df, zigzag(df, 1.5), tol_atr=0.5)
    assert any(lv.kind == "equal_highs" and lv.price == pytest.approx(105.06, abs=0.05) for lv in eq)
    rn = [lv.price for lv in liq.round_numbers(1.0962, True)]
    assert 1.095 in rn and 1.1 in [round(x, 4) for x in rn]


def test_double_top_and_head_shoulders():
    dt = path_df([100, 110, 104, 110.1, 102])
    names = {p.name: p for p in chart_patterns(dt, zigzag(dt, 1.5))}
    assert "double_top" in names and names["double_top"].confirmed and names["double_top"].direction == "bearish"
    hs = path_df([100, 108, 104, 112, 104, 108.2, 100])
    names = {p.name for p in chart_patterns(hs, zigzag(hs, 1.5))}
    assert "head_shoulders" in names


def test_regime_trending_vs_sideways_and_squeeze():
    up = path_df(list(np.linspace(100, 160, 13)), bars_per_leg=5, noise=0.05)
    assert regime(up)["state"] == "trending_up"
    side = path_df([100, 101, 100, 101, 100, 101, 100, 101, 100, 101], bars_per_leg=6, noise=0.02)
    r = regime(side)
    assert r["state"] == "sideways" and r["range"]["low"] < r["range"]["high"]
    # volatility compression after wide swings -> squeeze
    sq = pd.concat([path_df([100, 110, 100, 110, 100], bars_per_leg=5, noise=0.3, seed=2),
                    path_df([100, 100.2, 100], bars_per_leg=20, wick=0.02, start="2026-01-06", seed=3)])
    sq = sq[~sq.index.duplicated()].sort_index()
    assert regime(sq)["squeeze"] is True


def test_bearish_divergence():
    # second high is higher, but reached slowly (weaker momentum) after a fast first rally
    closes = list(np.linspace(100, 110, 6)) + list(np.linspace(110, 106, 6)) + list(np.linspace(106, 110.5, 25)) + \
        list(np.linspace(110.5, 107, 6))
    o = np.r_[closes[0], closes[:-1]]
    df = pd.DataFrame({"open": o, "high": np.maximum(o, closes) + 0.05, "low": np.minimum(o, closes) - 0.05,
                       "close": closes, "volume": 0.0}, index=pd.date_range("2026-01-05", periods=len(closes), freq="h", tz="UTC"))
    df = pd.concat([path_df([95, 100], bars_per_leg=30, start="2026-01-03"), df])
    df = df[~df.index.duplicated()].sort_index()
    div = divergences(df, zigzag(df, 1.5))
    assert any(d["type"] == "bearish" for d in div)


def test_overlay_bundle_is_json_ready():
    import json

    df = path_df(UPTREND + [115, 121, 117], noise=0.05)
    o = build_overlay(df)
    json.dumps(o)
    assert {"swings", "structure", "trendlines", "zones", "fibonacci", "liquidity", "regime", "fvgs"} <= set(o)
