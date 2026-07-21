"""Tests for the market clock and the completed-session filter."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from config import IST
from data import completed_sessions, market_status

# 2026-07-21 is a Tuesday; 07-25 a Saturday; 07-26 a Sunday.
TUE = dt.date(2026, 7, 21)
SAT = dt.date(2026, 7, 25)
SUN = dt.date(2026, 7, 26)


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


def frame_ending(last: dt.date, periods: int = 5) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(last), periods=periods, tz="Asia/Kolkata")
    closes = [float(100 + i) for i in range(periods)]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Volume": [1_000] * periods,
        },
        index=idx,
    )


# ---------------------------------------------------------------- market clock


@pytest.mark.parametrize(
    "when,is_open",
    [
        (at(TUE, 9, 14), False),  # one minute before the bell
        (at(TUE, 9, 15), True),  # open, inclusive
        (at(TUE, 12, 0), True),
        (at(TUE, 15, 30), True),  # close, inclusive
        (at(TUE, 15, 31), False),
        (at(SAT, 12, 0), False),
        (at(SUN, 12, 0), False),
    ],
)
def test_market_status_boundaries(when, is_open):
    assert market_status(when)[0] is is_open


def test_market_status_labels_the_weekend():
    assert "WEEKEND" in market_status(at(SAT, 12, 0))[1]
    assert "WEEKEND" not in market_status(at(TUE, 12, 0))[1]


# ---------------------------------------------------------------- session filter


def test_drops_todays_candle_during_the_session():
    df = frame_ending(TUE)
    kept = completed_sessions(df, at(TUE, 11, 0))
    assert len(kept) == len(df) - 1
    assert kept.index[-1].date() < TUE


def test_drops_todays_candle_before_the_open():
    """Yahoo can publish a near-empty pre-open row; it is not a session."""
    df = frame_ending(TUE)
    kept = completed_sessions(df, at(TUE, 8, 0))
    assert len(kept) == len(df) - 1


def test_keeps_todays_candle_once_the_session_has_closed():
    df = frame_ending(TUE)
    kept = completed_sessions(df, at(TUE, 16, 30))
    assert len(kept) == len(df)
    assert kept.index[-1].date() == TUE


def test_keeps_everything_when_the_last_row_predates_today():
    df = frame_ending(TUE)
    kept = completed_sessions(df, at(SAT, 11, 0))
    assert len(kept) == len(df)
