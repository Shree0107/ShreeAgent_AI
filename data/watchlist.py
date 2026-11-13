"""Watchlist persistence (user_data/watchlist.yaml)."""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from config.settings import ROOT, get_settings
from data.symbols import parse_symbol


class Watchlist:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or get_settings().user_data_dir / "watchlist.yaml")
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / "config" / "watchlist.default.yaml", self.path)

    def symbols(self) -> list[str]:
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        return list(dict.fromkeys(str(s) for s in data.get("symbols") or []))

    def _save(self, syms: list[str]) -> None:
        self.path.write_text(yaml.safe_dump({"symbols": syms}, sort_keys=False), encoding="utf-8")

    def add(self, ticker: str) -> str:
        sym = parse_symbol(ticker)
        canonical = sym.ticker if sym else ticker.strip().upper()
        syms = self.symbols()
        if canonical not in syms:
            syms.append(canonical)
            self._save(syms)
        return canonical

    def remove(self, ticker: str) -> None:
        self._save([s for s in self.symbols() if s != ticker])
