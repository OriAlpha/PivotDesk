"""PivotDesk — local state persistence.

Saves and loads user state (last active ticker, risk budget, position book, and recent searches)
to/from a local JSON file so settings persist across app reloads.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from positions import (
    Position,
    format_positions,
    parse_positions,
    set_position,
    symbol_key,
)

logger = logging.getLogger(__name__)

STATE_FILE = Path("pivotdesk_state.json")


@dataclass
class AppState:
    last_ticker: str = "RELIANCE.NS"
    risk: float | None = None
    positions_raw: str = ""
    recent_searches: list[str] = field(default_factory=list)

    def get_book(self) -> dict[str, Position]:
        return parse_positions(self.positions_raw)

    def set_symbol_position(
        self, ticker: str, entry: float | None, qty: float | None
    ) -> dict[str, Position]:
        book = self.get_book()
        book = set_position(book, symbol_key(ticker), entry, qty)
        self.positions_raw = format_positions(book)
        return book

    def add_recent_search(self, ticker: str, max_items: int = 5) -> None:
        sym = symbol_key(ticker)
        if not sym:
            return
        if self.recent_searches is None:
            self.recent_searches = []
        if sym in self.recent_searches:
            self.recent_searches.remove(sym)
        self.recent_searches.insert(0, sym)
        self.recent_searches = self.recent_searches[:max_items]


def load_state(filepath: Path | str | None = None) -> AppState:
    """Load application state from JSON file. Returns default state if file missing or invalid."""
    path = Path(filepath) if filepath is not None else STATE_FILE
    if not path.exists():
        return AppState()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AppState(
            last_ticker=data.get("last_ticker", "RELIANCE.NS"),
            risk=data.get("risk"),
            positions_raw=data.get("positions_raw", ""),
            recent_searches=data.get("recent_searches", []),
        )
    except Exception as e:
        logger.warning("Failed to load state from %s: %s", path, e)
        return AppState()


def save_state(state: AppState, filepath: Path | str | None = None) -> None:
    """Save application state to JSON file."""
    path = Path(filepath) if filepath is not None else STATE_FILE
    try:
        data = {
            "last_ticker": state.last_ticker,
            "risk": state.risk,
            "positions_raw": state.positions_raw,
            "recent_searches": state.recent_searches,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save state to %s: %s", path, e)
