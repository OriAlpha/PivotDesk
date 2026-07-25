"""Tests for the portfolio watchlist rollup.

Pure over synthetic history with patched fetchers — no network. The row
arithmetic (price, day change, bias score, P&L) is pinned on hand-built frames.
"""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import pytest

import portfolio
from config import IST
from positions import Position

TUE = dt.date(2026, 7, 21)


def _history(periods: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(TUE), periods=periods, tz="Asia/Kolkata")
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
def patched(monkeypatch):
    """Patch the fetchers on the portfolio namespace; return a 'now' to use."""
    monkeypatch.setattr(
        portfolio, "fetch_daily_resilient", lambda _t: (_history(), False)
    )
    monkeypatch.setattr(portfolio, "fetch_live_price", lambda _t: (150.0, 148.0, 152.0))
    return dt.datetime(2026, 7, 21, 11, 0, tzinfo=IST)  # mid-session Tuesday


# ---------------------------------------------------------------- happy path


def test_snapshot_returns_one_row_per_symbol_in_order(patched):
    rows = portfolio.snapshot(["RELIANCE", "TCS", "INFY"], {}, patched)
    assert [r.symbol for r in rows] == ["RELIANCE", "TCS", "INFY"]


def test_a_loaded_symbol_carries_price_day_and_score(patched):
    rows = portfolio.snapshot(["RELIANCE"], {}, patched)
    r = rows[0]
    assert r.ok is True
    assert r.price == 150.0
    assert r.day_pct is not None
    assert r.score is not None and 0 <= r.score <= 6


def test_a_held_position_adds_pnl(patched):
    book = {"RELIANCE": Position(entry=120.0, qty=50)}
    rows = portfolio.snapshot(["RELIANCE"], book, patched)
    # Entry 120, price 150 → +25.0%.
    assert rows[0].pnl_pct == pytest.approx(25.0)


def test_a_symbol_without_a_position_has_no_pnl(patched):
    rows = portfolio.snapshot(["RELIANCE"], {}, patched)
    assert rows[0].pnl_pct is None


# ---------------------------------------------------------------- graceful failure


def test_a_symbol_that_fails_to_load_is_marked_unavailable(monkeypatch):
    """A typo or outage must dim one row, not blank the table."""
    now = dt.datetime(2026, 7, 21, 11, 0, tzinfo=IST)

    def flaky(ticker):
        if ticker == "BAD.NS":
            raise ValueError("No data for 'BAD'")
        return (_history(), False)

    monkeypatch.setattr(portfolio, "fetch_daily_resilient", flaky)
    monkeypatch.setattr(portfolio, "fetch_live_price", lambda _t: (150.0, 148.0, 152.0))
    rows = portfolio.snapshot(["RELIANCE", "BAD", "TCS"], {}, now)
    assert [r.ok for r in rows] == [True, False, True]
    assert rows[1].price is None
    # The good rows still scored normally.
    assert rows[0].score is not None and rows[2].score is not None


def test_a_symbol_with_too_little_history_is_marked_unavailable(monkeypatch):
    """The dashboard needs >=60 sessions; a fresh listing has fewer."""
    now = dt.datetime(2026, 7, 21, 11, 0, tzinfo=IST)
    short = _history(periods=40)
    monkeypatch.setattr(portfolio, "fetch_daily_resilient", lambda _t: (short, False))
    monkeypatch.setattr(portfolio, "fetch_live_price", lambda _t: (150.0, 148.0, 152.0))
    rows = portfolio.snapshot(["NEW"], {}, now)
    assert rows[0].ok is False


# ---------------------------------------------------------------- staleness


def test_a_failed_live_quote_marks_the_row_stale(monkeypatch):
    """Market open but the quote failed → the price is a fallback close, not
    a live one, and the row says so."""
    now = dt.datetime(2026, 7, 21, 11, 0, tzinfo=IST)
    monkeypatch.setattr(
        portfolio, "fetch_daily_resilient", lambda _t: (_history(), False)
    )
    monkeypatch.setattr(portfolio, "fetch_live_price", lambda _t: None)
    rows = portfolio.snapshot(["RELIANCE"], {}, now)
    assert rows[0].stale is True
    # A stale price has no honest day change to report.
    assert rows[0].day_pct is None
