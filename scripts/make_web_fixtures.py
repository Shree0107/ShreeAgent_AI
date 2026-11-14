"""Write golden indicator values from the Python engine for the frontend tests.

    python scripts/make_web_fixtures.py

The TypeScript indicators (web/src/lib/indicators.ts) must reproduce analysis/indicators.py exactly,
so the chart shows the same numbers the signals are computed from.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis import indicators as ind  # noqa: E402

OUT = ROOT / "web" / "src" / "lib" / "__fixtures__" / "indicators.json"


def main() -> None:
    rng = np.random.default_rng(7)
    n = 300
    close = 1.10 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.0015, n)) * close
    df = pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close) + spread, "low": np.minimum(open_, close) - spread,
        "close": close, "volume": rng.integers(100, 1000, n).astype(float),
    }, index=pd.date_range("2026-01-05", periods=n, freq="D", tz="UTC"))
    d = ind.add_all(df, has_volume=True, intraday=False)
    s = lambda col: [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in d[col]]
    payload = {
        "candles": [{"time": int(t.timestamp()), "open": float(r.open), "high": float(r.high), "low": float(r.low),
                     "close": float(r.close), "volume": float(r.volume)} for t, r in df.iterrows()],
        "expected": {k: s(k) for k in ("sma_20", "ema_21", "ema_200", "rsi_14", "macd", "macd_signal", "macd_hist",
                                        "bb_upper", "bb_lower", "atr_14", "stoch_k", "stoch_d", "vwap")},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({n} bars)")


if __name__ == "__main__":
    main()
