"""Backtest TimesFM-3 forecasts against the naive baseline.

Examples:
  python scripts/run_backtest.py EUR/USD
  python scripts/run_backtest.py RELIANCE.NS AAPL --timeframe 1d --horizons 5 10 30 --windows 40
  python scripts/run_backtest.py --watchlist --univariate
Results are printed as a table and saved to .cache/backtests/ (the agent and dashboard read them).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging_setup import setup_logging
from data.symbols import resolve
from data.watchlist import Watchlist
from forecasting.models import get_forecaster
from forecasting.service import backtest_symbol


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("symbols", nargs="*")
    p.add_argument("--watchlist", action="store_true", help="backtest every watchlist symbol")
    p.add_argument("--timeframe", default="1d", choices=["1h", "4h", "1d", "1wk"])
    p.add_argument("--horizons", nargs="+", type=int, default=[5, 10])
    p.add_argument("--windows", type=int, default=30)
    p.add_argument("--univariate", action="store_true", help="price only (no related assets / volume)")
    p.add_argument("--model", default=None, choices=["timesfm", "naive"])
    a = p.parse_args()

    syms = list(a.symbols) + (Watchlist().symbols() if a.watchlist else [])
    if not syms:
        p.error("give at least one symbol or --watchlist")
    fc = get_forecaster(a.model)
    hdr = f"{'symbol':<14}{'tf':<5}{'h':>4}{'win':>5}{'MAPE%':>8}{'naive%':>8}{'dir%':>7}{'cov80%':>8}{'skill':>8}  trust"
    print(hdr)
    print("-" * len(hdr))
    for s in syms:
        for h in a.horizons:
            try:
                r = backtest_symbol(resolve(s), a.timeframe, h, n_windows=a.windows,
                                    multivariate=not a.univariate, forecaster=fc)
                print(f"{r.symbol:<14}{r.timeframe:<5}{r.horizon:>4}{r.n_windows:>5}{r.mape:>8.2f}{r.naive_mape:>8.2f}"
                      f"{r.directional_accuracy:>7.0f}{r.coverage_80:>8.0f}{r.skill_vs_naive:>+8.3f}  {r.trust}")
            except Exception as e:
                print(f"{s:<14}{a.timeframe:<5}{h:>4}  ERROR: {e}")
    print("\nHow to read: skill > 0 means better than 'price stays the same'. dir% above ~55 is useful. "
          "cov80% near 80 means the bands are well calibrated.")


if __name__ == "__main__":
    main()
