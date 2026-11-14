"""Start the ShreeAgent AI backend:  python -m server  [--host 0.0.0.0] [--port 8000] [--reload]"""
from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(description="ShreeAgent AI API server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="auto-reload on code changes (development)")
    a = p.parse_args()
    uvicorn.run("api.main:app", host=a.host, port=a.port, reload=a.reload, log_level="info")


if __name__ == "__main__":
    main()
