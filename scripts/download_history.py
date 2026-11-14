"""Download price history into the local bar store for the intraday backtest (user_data/bars/*.parquet).

Examples:
  python scripts/download_history.py EUR/USD                 # 2 years of 5m, 15m, 1h, 4h and daily bars
  python scripts/download_history.py EUR/USD GBP/USD --years 3 --timeframes 5m 1h
Sources:
  OANDA (OANDA_API_TOKEN set): bid AND ask prices, years of 5-minute bars, downloaded in pages of 5000 candles.
  Yahoo (no token):            only about the LAST 60 DAYS of 5- and 15-minute bars (Yahoo's limit), mid prices
                               only, about 2 years of hourly bars. Enough for a rough first test, NOT for the
                               12 + 3 month walk-forward test. Get a free OANDA practice token for that.
Running it again adds new bars to the files (nothing is downloaded twice from OANDA once a file covers the range).
Files are Parquet (pyarrow) or CSV when pyarrow isn't installed.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging_setup import setup_logging  # noqa: E402
from data.providers.base import resample_ohlcv  # noqa: E402
from data.symbols import parse_symbol, resolve  # noqa: E402
from intraday import bar_store  # noqa: E402

TFS = ("5m", "15m", "1h", "4h", "1d")


def from_oanda(sym, tf: str, years: float):
    from data.providers.oanda import OandaProvider

    p = OandaProvider()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(365 * years))
    old = bar_store.load(sym.ticker, tf)
    if old is not None and len(old) and old.attrs.get("source") == "oanda" and old.index[0] <= start + timedelta(days=3):
        start = old.index[-1].to_pydatetime()        # only the new part
    return p.history(sym, tf, start, end, price="MBA"), "oanda"


def from_yahoo(sym, tf: str):
    from data.providers.yfinance_provider import YFinanceProvider

    return YFinanceProvider().get_ohlcv(sym, tf), "yfinance"


def main() -> None:
    setup_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--years", type=float, default=2.0, help="history length for OANDA (Yahoo has fixed limits)")
    ap.add_argument("--timeframes", nargs="+", default=list(TFS), choices=TFS)
    ap.add_argument("--source", choices=["auto", "oanda", "yahoo"], default="auto")
    a = ap.parse_args()

    from config.settings import get_settings

    use_oanda = a.source == "oanda" or (a.source == "auto" and bool(get_settings().oanda_api_token))
    if not use_oanda:
        print("No OANDA token: using Yahoo. Yahoo only has about the last 60 days of 5-minute bars, so the backtest "
              "will be a rough guide (one short test period instead of a 12 + 3 month walk-forward).")
    print(f"Saving to {bar_store.bars_dir()} as {'Parquet' if bar_store.has_parquet() else 'CSV (pip install pyarrow for Parquet)'}")
    for t in a.symbols:
        sym = parse_symbol(t) or resolve(t)
        for tf in a.timeframes:
            try:
                if use_oanda and sym.is_fx:
                    if tf == "4h":                   # OANDA has H4, but build it from H1 so it lines up with Yahoo/live
                        h1 = bar_store.load(sym.ticker, "1h")
                        df, src = (resample_ohlcv(h1, "4h"), "oanda") if h1 is not None else from_oanda(sym, tf, a.years)
                    else:
                        df, src = from_oanda(sym, tf, a.years)
                else:
                    df, src = from_yahoo(sym, tf)
                if df is None or df.empty:
                    print(f"  {sym.ticker} {tf}: no data")
                    continue
                p = bar_store.save(sym.ticker, tf, df, src)
                full = bar_store.load(sym.ticker, tf)
                days = (full.index[-1] - full.index[0]).days
                print(f"  {sym.ticker} {tf:>3}: {len(full):>7} bars, {full.index[0]:%Y-%m-%d} to {full.index[-1]:%Y-%m-%d} "
                      f"({days} days, {src}{', bid/ask' if 'bid_close' in full.columns else ''}) -> {p.name}")
            except Exception as e:  # keep going with the other timeframes
                print(f"  {sym.ticker} {tf}: failed – {e}")


if __name__ == "__main__":
    main()
