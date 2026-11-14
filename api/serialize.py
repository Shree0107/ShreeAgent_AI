"""Turn engine output (dataclasses, numpy, pandas, NaN) into strict JSON-safe Python objects."""
from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime

import numpy as np
import pandas as pd


def clean(obj):
    """Recursively convert to JSON-safe types. NaN/inf become None (strict JSON has no NaN)."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (datetime, date, pd.Timestamp)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [clean(v) for v in obj.tolist()]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return clean(dataclasses.asdict(obj))
    if hasattr(obj, "as_dict"):
        return clean(obj.as_dict())
    return str(obj)


def candles(df: pd.DataFrame, limit: int | None = None, before: int | None = None) -> list[dict]:
    """OHLCV frame -> [{time (unix s, UTC), open, high, low, close, volume}], oldest first.

    `before` (unix seconds) returns bars strictly older than it, for scroll-back paging.
    """
    d = df
    if before is not None:
        d = d[d.index < pd.Timestamp(before, unit="s", tz="UTC")]
    if limit:
        d = d.tail(limit)
    idx = d.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    # Explicit unit: pandas 3 may store datetimes in us or ns, so never assume asi8 is nanoseconds.
    times = idx.tz_convert("UTC").as_unit("s").asi8.tolist()
    out = []
    for t, o, h, l, c, v in zip(times, d["open"], d["high"], d["low"], d["close"],
                                d["volume"] if "volume" in d else [0] * len(d)):
        out.append({"time": int(t), "open": clean(o), "high": clean(h), "low": clean(l), "close": clean(c),
                    "volume": clean(v) or 0})
    return out
