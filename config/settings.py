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

    # ---- Forecasting ----
    forecast_model: str = "timesfm"  # timesfm | naive
    timesfm_checkpoint: str = "google/timesfm-3.0-pytorch"
    timesfm_device: str = "auto"  # auto | cpu | cuda | mps
    timesfm_batch_size: int = 8
    timesfm_context_length: int = 1024
    hf_token: str = ""
    forecast_horizons: str = "5,10,30"

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

    log_level: str = "INFO"

    @property
    def horizons(self) -> list[int]:
        return [int(h) for h in self.forecast_horizons.split(",") if h.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    s.user_data_dir.mkdir(parents=True, exist_ok=True)
    return s
