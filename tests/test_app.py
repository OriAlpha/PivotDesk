"""Tests for app.py's controls, driven through Streamlit's AppTest.

Hermetic — the data layer is patched out, so no network is involved and the
dashboard renders from synthetic history.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import rendering

APP = str(Path(__file__).resolve().parent.parent / "app.py")
FAVOURITES = ["BHAGYANGR", "RELIANCE", "TCS", "INFY", "TATASTEEL"]


def _history(periods: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range(
        end=pd.Timestamp("2026-07-21"), periods=periods, tz="Asia/Kolkata"
    )
    closes = [100 + i * 0.1 + 5 * math.sin(i / 7) for i in range(periods)]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 2 for c in closes],
            "Low": [c - 2 for c in closes],
            "Close": closes,
            "Volume": [10_000 + i for i in range(periods)],
        },
        index=idx,
    )


def _fresh(monkeypatch, **query_params):
    """Boot the app with the data layer patched out and a given URL."""
    monkeypatch.setattr(
        rendering, "fetch_daily_resilient", lambda _t: (_history(), False)
    )
    monkeypatch.setattr(rendering, "fetch_live_price", lambda _t: (150.0, 148.0, 152.0))
    at = AppTest.from_file(APP, default_timeout=60)
    for key, value in query_params.items():
        at.query_params[key] = value
    at.run()
    return at


@pytest.fixture
def app(monkeypatch):
    return _fresh(monkeypatch)


@pytest.fixture
def book_app(monkeypatch):
    """Booted holding two positions, viewing the first."""
    return _fresh(
        monkeypatch,
        ticker="RELIANCE.NS",
        positions="RELIANCE:1200:50,TCS:3100.5:10",
    )


def labels(at) -> list[str]:
    return [b.label for b in at.button]


def click(at, label: str):
    next(b for b in at.button if b.label == label).click().run()
    return at


def query_param(at, name: str) -> str | None:
    """AppTest hands back list-valued params; the app itself sees scalars."""
    value = at.query_params.get(name)
    return value[0] if isinstance(value, list) else value


# ---------------------------------------------------------------- baseline


def test_app_runs_without_error(app):
    assert not app.exception
    assert not app.error


def test_core_inputs_are_always_present(app):
    assert [i.label for i in app.text_input] == ["NSE ticker"]
    assert [i.label for i in app.number_input] == [
        "Your buy price ₹ (optional)",
        "Qty (optional)",
    ]


# ---------------------------------------------------------------- quick list


def test_quick_list_is_collapsed_by_default(app):
    assert "Quick list ▾" in labels(app)
    assert not set(FAVOURITES) & set(labels(app))


def test_toggling_reveals_the_symbols(app):
    click(app, "Quick list ▾")
    assert set(FAVOURITES) <= set(labels(app))
    assert "Quick list ▴" in labels(app)


def test_toggling_again_hides_them(app):
    click(app, "Quick list ▾")
    click(app, "Quick list ▴")
    assert not set(FAVOURITES) & set(labels(app))
    assert "Quick list ▾" in labels(app)


def test_editor_is_hidden_until_asked_for(app):
    click(app, "Quick list ▾")
    assert len(app.text_input) == 1  # ticker only
    click(app, "✏️")
    assert any("Edit favorites" in i.label for i in app.text_input)


def test_collapsing_closes_the_editor_beneath_it(app):
    click(app, "Quick list ▾")
    click(app, "✏️")
    click(app, "Quick list ▴")  # collapse
    click(app, "Quick list ▾")  # and reopen
    assert not any("Edit favorites" in i.label for i in app.text_input)


def test_picking_a_symbol_loads_it(app):
    click(app, "Quick list ▾")
    click(app, "TCS")
    assert query_param(app, "ticker") == "TCS.NS"


# ---------------------------------------------------------------- positions


def entry_input(at):
    return next(i for i in at.number_input if i.label.startswith("Your buy price"))


def qty_input(at):
    return next(i for i in at.number_input if i.label.startswith("Qty"))


def test_editing_the_position_writes_it_to_the_url(app):
    entry_input(app).set_value(1200.0).run()
    qty_input(app).set_value(50.0).run()
    assert query_param(app, "positions") == "BHAGYANGR:1200:50"


def test_each_symbol_keeps_its_own_position(book_app):
    """Switching symbols must load that symbol's cost basis, not clear it and
    not carry the previous one over."""
    assert entry_input(book_app).value == 1200.0
    assert qty_input(book_app).value == 50.0

    click(book_app, "Quick list ▾")
    click(book_app, "TCS")
    assert entry_input(book_app).value == 3100.5
    assert qty_input(book_app).value == 10.0


def test_a_symbol_without_a_position_starts_empty(book_app):
    click(book_app, "Quick list ▾")
    click(book_app, "INFY")  # not in the book
    assert entry_input(book_app).value is None
    assert qty_input(book_app).value is None


def test_switching_away_and_back_restores_the_position(book_app):
    click(book_app, "Quick list ▾")
    click(book_app, "INFY")
    click(book_app, "RELIANCE")
    assert entry_input(book_app).value == 1200.0
    assert qty_input(book_app).value == 50.0


def test_legacy_entry_and_qty_urls_are_migrated(monkeypatch):
    """Bookmarks made before the book existed must keep their cost basis."""
    at = _fresh(monkeypatch, ticker="RELIANCE.NS", entry="1200.0", qty="50")
    assert query_param(at, "positions") == "RELIANCE:1200:50"
    assert "entry" not in at.query_params
    assert "qty" not in at.query_params
    assert entry_input(at).value == 1200.0


def test_a_junk_positions_url_does_not_break_the_page(monkeypatch):
    at = _fresh(monkeypatch, ticker="RELIANCE.NS", positions="!!!:::,,,")
    assert not at.exception
    assert entry_input(at).value is None


def test_reload_param_clears_cache_and_restores_params(monkeypatch):
    at = _fresh(
        monkeypatch,
        ticker="RELIANCE.NS",
        reload="1",
        positions="RELIANCE:1200:50,TCS:3100.5:10",
    )
    assert not at.exception
    assert query_param(at, "reload") is None
    assert query_param(at, "ticker") == "RELIANCE.NS"
    assert query_param(at, "positions") == "RELIANCE:1200:50,TCS:3100.5:10"

