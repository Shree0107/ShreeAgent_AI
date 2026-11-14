"""Forecast tab engine: forecasts on completed candles, re-run at every candle close, cached in the forecast store.

- `refresh_forecast` (runs as a background job, never inside an HTTP request): loads completed candles, scores
  finished forecasts, (re)runs the model-vs-baselines check when it is old, and makes a new forecast when a new
  candle has closed since the last one.
- `is_stale` / `is_due`: pure clock logic. A forecast built on the candle that opened at T is current until the
  next candle closes at T + 2 x timeframe. After that it is stale (the UI greys it out) and due for a re-run;
  if the data provider hasn't delivered the new candle yet, retry every `retry_seconds(tf)`.
- `ForecastScheduler`: keeps viewed symbol/timeframes fresh. A clock loop checks every few seconds (works for
  polled symbols) and the live service's "candle_closed" bus events trigger an immediate check (streamed symbols).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config.settings import get_settings
from data.symbols import Symbol, parse_symbol
from forecasting.accuracy import ForecastStore, get_store
from forecasting.backtest import run_backtest, save_result
from forecasting.baselines import baseline_paths
from forecasting.explain import TF_SECONDS
from forecasting.features import build_inputs, future_index
from forecasting.models import Forecaster, get_forecaster

log = logging.getLogger(__name__)

TAB_TIMEFRAMES = ("15m", "1h", "4h", "1d")
DEFAULT_HORIZONS = {"15m": 16, "1h": 24, "4h": 30, "1d": 10}


def horizon_for(tf: str) -> int:
    return get_settings().forecast_tab_horizon_map.get(tf, DEFAULT_HORIZONS.get(tf, 10))


def _ts(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _now(now=None) -> pd.Timestamp:
    if now is None:
        return pd.Timestamp.now(tz="UTC")
    if isinstance(now, (int, float)):
        return pd.Timestamp(now, unit="s", tz="UTC")
    return _ts(now)


def completed(df: pd.DataFrame, tf: str, now=None) -> pd.DataFrame:
    """Drop the candle that is still forming (its open time + timeframe is in the future)."""
    if df is None or df.empty:
        return df
    now = _now(now)
    step = pd.Timedelta(seconds=TF_SECONDS[tf])
    last = _ts(df.index[-1])
    return df.iloc[:-1] if last + step > now else df


def next_close(last_bar_time, tf: str) -> pd.Timestamp:
    """When the candle after the forecast's last candle closes (= when the forecast becomes out of date)."""
    return _ts(last_bar_time) + pd.Timedelta(seconds=2 * TF_SECONDS[tf])


def retry_seconds(tf: str) -> float:
    return float(min(900, max(120, TF_SECONDS[tf] / 4)))


def is_stale(entry: dict | None, now, tf: str) -> bool:
    """True when a newer candle than the one the forecast used has closed (or there is no forecast)."""
    if not entry:
        return True
    return _now(now) >= next_close(entry["last_bar_time"], tf)


def is_due(entry: dict | None, now, tf: str, last_checked: float | None) -> bool:
    """Should a refresh job run now? Stale, and not already checked since the new candle was due
    (or that check was more than `retry_seconds` ago: the provider may deliver the candle late)."""
    now_t = _now(now)
    if last_checked is not None and now_t.timestamp() - last_checked < 60 and not entry:
        return False  # first forecast failed or is still being made: don't hammer
    if not is_stale(entry, now_t, tf):
        return False
    if last_checked is None:
        return True
    due_at = next_close(entry["last_bar_time"], tf).timestamp() if entry else 0.0
    return last_checked < due_at or now_t.timestamp() - last_checked >= retry_seconds(tf)


# ---------------- related series / model check ----------------
def related_frames(symbol: Symbol, tf: str, data) -> dict[str, pd.DataFrame]:
    """Related series from config/symbols.yaml `related`; unavailable ones are dropped silently."""
    from data.symbols import related_tickers

    out = {}
    for t in related_tickers(symbol):
        try:
            df = data.get_ohlcv_ticker(t, tf)
        except Exception as e:
            log.info("Related %s %s unavailable: %s", t, tf, e)
            df = None
        if df is not None and not df.empty:
            out[t] = df
    return out


def _check_path(ticker: str, tf: str, horizon: int):
    d = get_settings().cache_dir / "forecast_checks"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{ticker.replace('/', '').replace('^', '')}_{tf}_h{horizon}.json"


def load_check(ticker: str, tf: str, horizon: int) -> dict | None:
    p = _check_path(ticker, tf, horizon)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_is_old(check: dict | None, now=None) -> bool:
    if not check:
        return True
    age_h = (_now(now) - _ts(check["run_at"])).total_seconds() / 3600
    return age_h >= get_settings().forecast_check_hours


def run_check(symbol: Symbol, tf: str, horizon: int, df: pd.DataFrame, related: dict, forecaster: Forecaster,
              now=None) -> dict:
    """Rolling backtest of the model (own prices only, and with related series/volume when available) vs the
    naive, drift and moving-average baselines. Keeps the extra inputs only if they don't hurt accuracy."""
    s = get_settings()
    windows = s.forecast_check_windows
    uni = run_backtest(df, forecaster, horizon, n_windows=windows, symbol=symbol.ticker, timeframe=tf)
    use_vol = symbol.has_real_volume
    multi = None
    if related or use_vol:
        try:
            multi = run_backtest(df, forecaster, horizon, n_windows=windows, related=related, use_volume=use_vol,
                                 symbol=symbol.ticker, timeframe=tf)
            if multi.variates == ["close"] and not use_vol:
                multi = None  # related series didn't overlap: nothing different was tested
        except Exception as e:
            log.info("Multivariate check failed for %s %s: %s", symbol.ticker, tf, e)
    use_multi = bool(multi and multi.mae <= uni.mae)
    chosen = multi if use_multi else uni
    save_result(chosen)  # the agent and the signal engine read the latest saved backtest
    check = {"run_at": _now(now).isoformat(), "univariate": uni.as_dict(),
             "multivariate": multi.as_dict() if multi else None, "multi_tested": multi is not None,
             "use_multi": use_multi, "chosen": chosen.as_dict()}
    _check_path(symbol.ticker, tf, horizon).write_text(json.dumps(check, indent=2), encoding="utf-8")
    return check


def use_multivariate(check: dict | None) -> bool:
    mode = get_settings().forecast_multivariate.lower()
    if mode == "off":
        return False
    if mode == "on":
        return True
    return bool(check and check.get("use_multi"))  # auto: own prices only until the check says extras help


# ---------------- the refresh job ----------------
def _candles(data, symbol: Symbol, tf: str, now) -> pd.DataFrame:
    df = completed(data.get_ohlcv(symbol, tf), tf, now)
    behind = df is not None and len(df) and _now(now) >= next_close(df.index[-1], tf) + pd.Timedelta(seconds=30)
    cache = getattr(data, "cache", None)
    if behind and cache is not None and hasattr(cache, "delete"):
        # The cached candles end before the last closed candle: fetch again once.
        cache.delete(f"ohlcv:{symbol.ticker}:{tf}")
        try:
            df = completed(data.get_ohlcv(symbol, tf), tf, now)
        except Exception as e:
            log.info("Refetch of %s %s failed: %s", symbol.ticker, tf, e)
    return df


def make_forecast(symbol: Symbol, tf: str, horizon: int, df: pd.DataFrame, related: dict, multi: bool,
                  forecaster: Forecaster, now=None) -> dict:
    use_vol = multi and symbol.has_real_volume
    ctx, cov, names = build_inputs(df, get_settings().timesfm_context_length, related if multi else {}, use_vol)
    if cov is not None:
        names = [*names, "volume"]
    path = forecaster.forecast([ctx], horizon, [cov] if cov is not None else None)[0]
    closes = df["close"].to_numpy(dtype=float)
    last = float(closes[-1])
    from forecasting.service import _prob_up

    r = lambda a: [round(float(x), 6) for x in a]
    return {
        "symbol": symbol.ticker, "tf": tf, "horizon": horizon,
        "made_at": _now(now).isoformat(timespec="seconds"),
        "last_close": last, "last_bar_time": _ts(df.index[-1]).isoformat(),
        "dates": [_ts(d).isoformat() for d in future_index(df.index, horizon, tf)],
        "median": r(path.median), "quantiles": [r(row) for row in np.asarray(path.quantiles)],
        "model": forecaster.name, "variates": names,
        "baselines": {k: r(v) for k, v in baseline_paths(closes, horizon).items()},
        "prob_up": round(_prob_up(np.asarray(path.quantiles)[-1], last), 3),
    }


def refresh_forecast(symbol: Symbol, tf: str, horizon: int | None = None, data=None,
                     forecaster: Forecaster | None = None, store: ForecastStore | None = None, now=None,
                     publish=None) -> dict:
    """The background job. Returns a short status dict (the result itself is read from the store)."""
    from data.service import get_data_service

    horizon = horizon or horizon_for(tf)
    data = data or get_data_service()
    forecaster = forecaster or get_forecaster()
    store = store or get_store()
    df = _candles(data, symbol, tf, now)
    if df is None or len(df) < 100:
        raise ValueError(f"Not enough {tf} candles for {symbol.ticker} to forecast")
    scored = store.score_pending(symbol.ticker, tf, df)

    latest = store.latest(symbol.ticker, tf, horizon)
    last_bar = _ts(df.index[-1]).isoformat()
    check = load_check(symbol.ticker, tf, horizon)
    related = related_frames(symbol, tf, data) if get_settings().forecast_multivariate.lower() != "off" else {}
    made = False
    want_multi = use_multivariate(check)
    if not latest or latest["last_bar_time"] != last_bar:
        store.save(make_forecast(symbol, tf, horizon, df, related, want_multi, forecaster, now))
        made = True
        if publish:
            publish(symbol.ticker, tf)

    if check_is_old(check, now):
        try:
            check = run_check(symbol, tf, horizon, df, related, forecaster, now)
        except ValueError as e:  # too little history: forecasts still work, the verdict says "not checked"
            log.info("Check skipped for %s %s: %s", symbol.ticker, tf, e)
        if use_multivariate(check) != want_multi:  # the check changed the inputs: redo this candle's forecast
            store.save(make_forecast(symbol, tf, horizon, df, related, use_multivariate(check), forecaster, now))
            made = True
            if publish:
                publish(symbol.ticker, tf)
    return {"symbol": symbol.ticker, "tf": tf, "horizon": horizon, "last_bar_time": last_bar,
            "new_forecast": made, "scored": scored}


# ---------------- scheduler ----------------
class ForecastScheduler:
    def __init__(self, jobs, store: ForecastStore | None = None, bus=None, clock=time.time, data_factory=None):
        self.jobs = jobs
        self.store = store or get_store()
        self.bus = bus
        self.clock = clock
        self.data_factory = data_factory
        self.watched: dict[tuple[str, str], float] = {}
        self.last_checked: dict[tuple[str, str], float] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def key(self, ticker: str, tf: str, horizon: int) -> str:
        return f"fclive:{ticker}:{tf}:{horizon}"

    def watch(self, ticker: str, tf: str) -> None:
        with self._lock:
            self.watched[(ticker, tf)] = self.clock()

    def _publish(self, ticker: str, tf: str) -> None:
        if self.bus:
            self.bus.publish(f"forecast:{ticker}:{tf}", {"symbol": ticker, "tf": tf, "ts": self.clock()})

    def running_job(self, ticker: str, tf: str, horizon: int):
        j = self.jobs.latest(self.key(ticker, tf, horizon))
        return j if j and j.status in ("queued", "running") else None

    def maybe_refresh(self, symbol: Symbol, tf: str, data=None, forecaster=None, force: bool = False):
        """Submit a refresh job if the cached forecast is due. Returns the Job or None. Never blocks."""
        h = horizon_for(tf)
        k = (symbol.ticker, tf)
        entry = self.store.latest(symbol.ticker, tf, h)
        if not force and not is_due(entry, self.clock(), tf, self.last_checked.get(k)):
            return self.running_job(symbol.ticker, tf, h)
        self.last_checked[k] = self.clock()
        if data is None and self.data_factory:
            data = self.data_factory()

        def work():
            try:
                return refresh_forecast(symbol, tf, h, data=data, forecaster=forecaster, store=self.store,
                                        publish=self._publish)
            finally:
                self.last_checked[k] = self.clock()

        return self.jobs.submit("forecast_live", self.key(symbol.ticker, tf, h), work)

    def tick(self) -> None:
        ttl = get_settings().forecast_watch_minutes * 60
        now = self.clock()
        with self._lock:
            for k, seen in list(self.watched.items()):
                if now - seen > ttl:
                    self.watched.pop(k, None)
            items = list(self.watched)
        for ticker, tf in items:
            sym = parse_symbol(ticker)
            if sym:
                try:
                    self.maybe_refresh(sym, tf)
                except Exception as e:
                    log.warning("Forecast refresh %s %s failed: %s", ticker, tf, e)

    def on_candle_closed(self, msg: dict) -> None:
        d = msg.get("data") or {}
        k = (d.get("symbol"), d.get("tf"))
        if k in self.watched:
            sym = parse_symbol(k[0])
            if sym:
                self.maybe_refresh(sym, k[1])

    def run(self, every: float = 10.0) -> None:
        while not self._stop.wait(every):
            self.tick()

    def stop(self) -> None:
        self._stop.set()


def start_scheduler(app, bus) -> ForecastScheduler:
    """Called from the API lifespan (inside the event loop): clock thread + candle_closed listener."""
    from data.service import get_data_service

    sched = ForecastScheduler(app.state.jobs, bus=bus, data_factory=get_data_service)
    app.state.forecast_scheduler = sched
    threading.Thread(target=sched.run, name="forecast-scheduler", daemon=True).start()
    q = bus.subscribe({"candle_closed"})

    async def listen():
        loop = asyncio.get_running_loop()
        while not sched._stop.is_set():
            msg = await q.get()
            await loop.run_in_executor(None, sched.on_candle_closed, msg)

    sched._task = asyncio.get_running_loop().create_task(listen())
    sched._queue = q
    return sched


def stop_scheduler(sched: ForecastScheduler | None, bus) -> None:
    if not sched:
        return
    sched.stop()
    task = getattr(sched, "_task", None)
    if task:
        task.cancel()
    if getattr(sched, "_queue", None) is not None:
        bus.unsubscribe(sched._queue)
