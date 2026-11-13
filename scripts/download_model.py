"""Download the TimesFM-3 weights into the Hugging Face cache and run a smoke test.

Usage:  python scripts/download_model.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from config.logging_setup import setup_logging
from forecasting.models import TimesFMForecaster, pick_device


def main() -> None:
    setup_logging()
    print(f"Device: {pick_device()}")
    t0 = time.time()
    fc = TimesFMForecaster()
    x = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 512))
    path = fc.forecast([x], horizon=10)[0]
    print(f"Loaded + forecast in {time.time() - t0:.1f}s")
    print("Last value:", round(float(x[-1]), 3))
    print("Median forecast:", np.round(path.median, 3))
    print("10% / 90% at step 10:", round(float(path.q10[-1]), 3), "/", round(float(path.q90[-1]), 3))
    print("TimesFM-3 is ready.")


if __name__ == "__main__":
    main()
