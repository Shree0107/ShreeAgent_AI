"""Intraday engine (15-minute chart): sessions, multi-timeframe bias, setups, plans, state tracking.

Pure analysis functions take a `Context` (completed bars only, as of a given time) so the same code runs live
and in the bar-by-bar backtest (phase 7). Never places orders.
"""
