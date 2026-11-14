"""Central configuration loaded from environment variables / .env.

Every setting has a safe default so the app starts even with an empty .env;
features that need a missing key degrade gracefully and say so in the UI.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- LLM ----
    llm_provider: str = "anthropic"  # anthropic | openai_compat
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"
    llm_deep_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"  # low | medium | high | xhigh | max
    llm_max_tokens: int = 16000
    openai_api_key: str = ""
    openai_base_url: str = ""

    # ---- Data providers ----
    price_provider: str = "yfinance"
    price_fallback_provider: str = "twelvedata"
    twelvedata_api_key: str = ""
    fred_api_key: str = ""
    finnhub_api_key: str = ""
    marketaux_api_key: str = ""

    # ---- Live data (OANDA v20: free practice account gives real-time forex/gold streaming) ----
    oanda_api_token: str = ""
    oanda_account_id: str = ""           # optional: discovered from the token when empty
    oanda_environment: str = "practice"  # practice | live
    live_enabled: bool = True            # stream / poll prices for open charts and the watchlist
    live_poll_seconds: int = 15          # polling interval for symbols without a stream (Yahoo, delayed)
    stale_after_seconds: int = 60        # no new price for this long while the market is open -> "stale"

    # ---- Forecasting ----
    forecast_model: str = "timesfm"  # timesfm | naive
    timesfm_checkpoint: str = "google/timesfm-3.0-pytorch"
    timesfm_device: str = "auto"  # auto | cpu | cuda | mps
    timesfm_batch_size: int = 8
    timesfm_context_length: int = 1024
    hf_token: str = ""
    forecast_horizons: str = "5,10,30"

    # ---- Forecast tab (phase 9) ----
    forecast_tab_horizons: str = "15m:16,1h:24,4h:30,1d:10"  # candles ahead per timeframe
    forecast_multivariate: str = "auto"   # auto (keep related series only if past tests say they help) | on | off
    forecast_check_hours: float = 24.0    # re-run the model-vs-baselines check this often
    forecast_check_windows: int = 20      # past test windows in that check
    forecast_watch_minutes: int = 120     # keep re-forecasting a symbol/timeframe this long after it was viewed

    # ---- Sentiment ----
    sentiment_model: str = "finbert"  # finbert | lexicon

    # ---- Storage ----
    cache_dir: Path = ROOT / ".cache"
    user_data_dir: Path = ROOT / "user_data"

    # ---- Alerts (WhatsApp) ----
    whatsapp_backend: str = "none"  # callmebot | twilio | none
    callmebot_phone: str = ""
    callmebot_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"
    twilio_whatsapp_to: str = ""
    scan_time: str = "08:00"
    scan_timezone: str = "Asia/Kolkata"
    scan_include_forecast: bool = False
    alert_score_threshold: float = 40.0

    # ---- Beginner signals (Signals tab) ----
    signal_timeframe: str = "1d"            # chart the entry/stop/targets are built on
    signal_forecast_horizon: int = 10       # TimesFM candles used in the decision
    signal_include_forecast: bool = True
    signal_min_rr: float = 1.5              # BUY/SELL only if reward/risk to target 1 >= this
    signal_min_score: float = 25.0          # |combined score| needed for a direction (0-100)
    signal_high_score: float = 50.0         # |score| needed for High confidence
    signal_min_confidence: str = "Medium"   # Low | Medium | High: anything below -> WAIT
    signal_event_blackout_days: int = 1     # WAIT if a high-impact event is today or within N days
    signal_event_warning_days: int = 7      # show a warning for events within N days
    signal_earnings_blackout_days: int = 3  # stocks: WAIT if earnings are within N days
    signal_max_stop_atr: float = 3.0        # WAIT if the structural stop is wider than N x daily range
    signal_expiry_bars: int = 3             # trading days a signal stays valid
    signal_refresh_minutes: int = 60        # reuse stored signals younger than this
    signal_llm_polish: bool = False         # let the LLM reword the explanations (numbers locked)

    # ---- Position size helper (defaults; editable in the app) ----
    account_size: float = 1000.0
    account_currency: str = "EUR"
    risk_per_trade_pct: float = 1.0
    leverage: float = 30.0                  # EU retail max for major FX pairs (XTB, ESMA rules)
    spread_pips: float = 1.0                # added to the stop so the broker spread can't trigger it
    fx_lot_size: int = 100_000              # units of the base currency in 1 standard lot
    fx_min_lot: float = 0.01

    log_level: str = "INFO"

    @property
    def horizons(self) -> list[int]:
        return [int(h) for h in self.forecast_horizons.split(",") if h.strip()]

    @property
    def forecast_tab_horizon_map(self) -> dict[str, int]:  # phase 9
        out = {}
        for part in self.forecast_tab_horizons.split(","):
            tf, _, h = part.partition(":")
            if tf.strip() and h.strip().isdigit():
                out[tf.strip()] = int(h)
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    s.user_data_dir.mkdir(parents=True, exist_ok=True)
    return s
