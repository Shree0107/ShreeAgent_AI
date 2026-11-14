"""Backtest the intraday (15-minute) setups and switch off the ones that don't hold up.

Examples:
  python scripts/run_intraday_backtest.py EUR/USD
  python scripts/run_intraday_backtest.py EUR/USD --setups squeeze_breakout trend_pullback --months 24
  python scripts/run_intraday_backtest.py EUR/USD --no-write           # report only, don't change the live cards
It replays the live engine candle by candle (slow: a few minutes for 60 days, about an hour for 2 years),
prints a plain report and writes user_data/intraday_backtests/*.json, which the Trade Plan cards read
("~58% reached target 1 first") and which can switch a setup off. Data: the local bar store
(scripts/download_history.py) or, if empty, the normal data source (Yahoo: only ~60 days of 5-minute bars).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging_setup import setup_logging  # noqa: E402
from intraday.config import ALL_SETUPS  # noqa: E402


def main() -> None:
    setup_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol")
    ap.add_argument("--setups", nargs="+", choices=ALL_SETUPS, help="default: the setups enabled in the settings")
    ap.add_argument("--months", type=int, default=None, help="history to use (default BACKTEST_MONTHS)")
    ap.add_argument("--no-write", action="store_true", help="don't write the result files")
    a = ap.parse_args()

    from intraday.walkforward import run_backtest

    last = {"stage": None}

    def progress(stage, done, total, msg):
        if stage != last["stage"] or (total and done in (total, total // 2)):
            print(f"  … {msg}", flush=True)
            last["stage"] = stage

    r = run_backtest(a.symbol, months=a.months, setups=a.setups, write=not a.no_write, progress=progress)
    o = r["overall"]
    print()
    print(f"{r['symbol']} – {r['method_text']}")
    print(f"Test period: {r['period']['start']} to {r['period']['end']} ({r['period_text']}); "
          f"{r['cards_built']} 15-minute candles analysed in {r['elapsed_s']:.0f} s.")
    for w in r["windows"]:
        print(f"  window {w['test_start'][:10]}–{w['test_end'][:10]}: chose {w['chosen']} ({w['test_trades']} test trades)")
    print()
    for line in r["lines"]:
        print("• " + line)
    print()
    if o["trades"]:
        print(f"All setups together: {o['trades']} trades, target 1 reached in {o['win_rate'] * 100:.0f}%, "
              f"profit factor {o['profit_factor']}, {o['total_pips']:+.1f} pips in total, "
              f"worst losing streak {o['max_drawdown_pips']:.1f} pips.")
    hdr = f"{'setup':<22}{'session':<18}{'trades':>7}{'win%':>6}{'avgW':>7}{'avgL':>7}{'PF':>6}{'exp':>7}{'maxDD':>7}{'TP1 min':>12}"
    print(hdr)
    for row in r["rows"]:
        if not row["trades"]:
            continue
        wr = f"{row['win_rate'] * 100:.0f}" if row["win_rate"] is not None else "-"
        f = lambda v, d=1: "-" if v is None else f"{v:.{d}f}"  # noqa: E731
        tp = (f"{f(row['median_minutes_to_tp1'], 0)} ({f(row['p25_minutes_to_tp1'], 0)}-{f(row['p75_minutes_to_tp1'], 0)})"
              if row["median_minutes_to_tp1"] is not None else "-")
        print(f"{row['setup']:<22}{row['session']:<18}{row['trades']:>7}{wr:>6}{f(row['avg_win_pips']):>7}"
              f"{f(row['avg_loss_pips']):>7}{f(row['profit_factor'], 2):>6}{f(row['expectancy_pips']):>7}"
              f"{f(row['max_drawdown_pips']):>7}{tp:>12}")
    if r["disabled"]:
        print("\nSwitched off for the live cards:")
        for d in r["disabled"]:
            print(f"  {d['setup_name']}: {d['reason']}")
    for n in r["notes"]:
        print("Note: " + n)
    if not a.no_write:
        print("\nResults written to user_data/intraday_backtests/ (the Trade Plan cards and the Performance tab read them).")


if __name__ == "__main__":
    main()
