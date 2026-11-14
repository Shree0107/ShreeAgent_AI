"""Local bar store for backtests: {user_data_dir}/bars/{SYMBOL with '/' -> '_'}_{tf}.parquet (CSV without pyarrow).

    save(symbol, tf, df, source)   merge new bars into the file (newer rows win), remember where they came from
    load(symbol, tf)               the stored frame (UTC index = bar START time) or None
    info(symbol)                   {tf: {"bars", "start", "end", "source", "bid_ask"}} for the report / UI

Columns: open high low close volume, plus bid_open..bid_close / ask_open..ask_close when the source has them
(OANDA). Filled by scripts/download_history.py; the backtest falls back to the normal data service when empty.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
TFS = ("5m", "15m", "1h", "4h", "1d")


def has_parquet() -> bool:
    try:
        import pyarrow  # noqa: F401

        return True
    except ImportError:
        return False


def bars_dir(base: Path | None = None) -> Path:
    if base is not None:
        return Path(base)
    from config.settings import get_settings

    return get_settings().user_data_dir / "bars"


def _stem(symbol: str, tf: str) -> str:
    return f"{symbol.replace('/', '_').upper()}_{tf}"


def path_for(symbol: str, tf: str, base: Path | None = None) -> Path:
    ext = ".parquet" if has_parquet() else ".csv"
    return bars_dir(base) / (_stem(symbol, tf) + ext)


def _existing(symbol: str, tf: str, base: Path | None) -> Path | None:
    for ext in (".parquet", ".csv"):
        p = bars_dir(base) / (_stem(symbol, tf) + ext)
        if p.exists():
            return p
    return None


def _meta_path(base: Path | None) -> Path:
    return bars_dir(base) / "sources.json"


def _read_meta(base: Path | None) -> dict:
    p = _meta_path(base)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def load(symbol: str, tf: str, base: Path | None = None) -> pd.DataFrame | None:
    p = _existing(symbol, tf, base)
    if p is None:
        return None
    try:
        if p.suffix == ".parquet":
            df = pd.read_parquet(p)
        else:
            df = pd.read_csv(p, index_col=0)
        idx = pd.to_datetime(df.index, utc=True)
        df.index = idx
        df.index.name = "time"
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df.attrs["source"] = _read_meta(base).get(_stem(symbol, tf), {}).get("source", "store")
        return df
    except Exception as e:
        log.warning("Bad bar file %s: %s", p, e)
        return None


def save(symbol: str, tf: str, df: pd.DataFrame, source: str, base: Path | None = None) -> Path:
    d = bars_dir(base)
    d.mkdir(parents=True, exist_ok=True)
    new = df.copy()
    idx = pd.to_datetime(new.index)
    new.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    old = load(symbol, tf, base)
    if old is not None and not old.empty:
        new = pd.concat([old, new])
        new = new[~new.index.duplicated(keep="last")].sort_index()
    new.index.name = "time"
    p = path_for(symbol, tf, base)
    other = _existing(symbol, tf, base)
    if other is not None and other != p:
        other.unlink()
    if p.suffix == ".parquet":
        new.to_parquet(p)
    else:
        new.to_csv(p)
    meta = _read_meta(base)
    meta[_stem(symbol, tf)] = {"source": source, "bars": int(len(new)), "start": new.index[0].isoformat(),
                               "end": new.index[-1].isoformat(), "bid_ask": "bid_close" in new.columns}
    _meta_path(base).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return p


def info(symbol: str, base: Path | None = None) -> dict:
    meta = _read_meta(base)
    return {tf: meta[_stem(symbol, tf)] for tf in TFS if _stem(symbol, tf) in meta and _existing(symbol, tf, base)}
