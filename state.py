"""PivotDesk — local state persistence.

Remembers the last ticker, risk budget, position book and recent searches
between visits — but **only when a state file is explicitly configured**, via
the ``PIVOTDESK_STATE_FILE`` environment variable.

Off by default because the file is per *process*, not per browser session, and
one Streamlit process serves every visitor to a deployed app. Persisting
unconditionally handed the next visitor the previous one's ticker, cost basis
and position size. A single-user local run opts in and loses nothing; a
deployment leaves it unset and leaks nothing. Everything the dashboard needs to
restore a view is in the URL either way — see :mod:`positions`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from positions import symbol_key

logger = logging.getLogger(__name__)

STATE_FILE_ENV = "PIVOTDESK_STATE_FILE"


def state_path() -> Path | None:
    """The configured state file, or ``None`` when persistence is off.

    Read per call rather than captured at import so the setting is a property
    of the environment the app runs in, not of when the module was loaded.
    """
    configured = os.environ.get(STATE_FILE_ENV, "").strip()
    return Path(configured) if configured else None


@dataclass
class AppState:
    last_ticker: str = "RELIANCE.NS"
    risk: float | None = None
    positions_raw: str = ""
    recent_searches: list[str] = field(default_factory=list)

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
    """Load application state from JSON file.

    Returns a default state when persistence is off, or the file is missing or
    invalid. An explicit *filepath* overrides the environment.
    """
    path = Path(filepath) if filepath is not None else state_path()
    if path is None or not path.exists():
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
    """Save application state to JSON file, or do nothing if persistence is off."""
    path = Path(filepath) if filepath is not None else state_path()
    if path is None:
        return
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
