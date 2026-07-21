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


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(
        rendering, "fetch_daily_resilient", lambda _t: (_history(), False)
    )
    monkeypatch.setattr(rendering, "fetch_live_price", lambda _t: (150.0, 148.0, 152.0))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


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


def test_picking_a_symbol_loads_it_and_clears_the_position(app):
    app.query_params["entry"] = "100.0"
    app.query_params["qty"] = "5"
    click(app, "Quick list ▾")
    click(app, "TCS")
    assert query_param(app, "ticker") == "TCS.NS"
    assert "entry" not in app.query_params
    assert "qty" not in app.query_params
