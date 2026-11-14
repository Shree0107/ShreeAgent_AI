"""Automatic chart structure: swings, market structure, trendlines, zones, Fibonacci, channels, liquidity,
order blocks, fair value gaps, supply/demand, chart patterns, divergences and regime.

Every detector is a pure function of an OHLC DataFrame and uses completed bars only. Objects carry the bar
index at which they became known (`confirmed_at`), so backtests can use them without look-ahead.
"""
