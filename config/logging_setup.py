"""Logging: console + rotating file in the cache directory."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config.settings import get_settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    s = get_settings()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(s.log_level.upper())

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = s.cache_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(log_dir / "shreeagent.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Third-party libraries are noisy at INFO.
    for noisy in ("urllib3", "yfinance", "httpx", "httpx2", "httpcore", "huggingface_hub", "peewee", "matplotlib",
                  "filelock", "transformers", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True
