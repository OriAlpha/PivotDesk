"""Tests for the market clock and the completed-session filter."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

import data
from config import IST
from data import completed_sessions, fetch_daily_resilient, is_holiday, market_status

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


# ---------------------------------------------------------------- holidays


MON = dt.date(2026, 7, 20)


@pytest.mark.parametrize(
    "daily_last,when,expected,why",
    [
        (MON, at(TUE, 11, 0), True, "weekday, mid-session, no row for today"),
        (TUE, at(TUE, 11, 0), False, "today's partial row exists"),
        (MON, at(TUE, 9, 30), False, "before the grace period; row may be pending"),
        (MON, at(TUE, 9, 45), True, "grace period elapsed"),
        (MON, at(TUE, 16, 30), False, "after the close; nothing left to publish"),
        (MON, at(SAT, 11, 0), False, "weekend is not a holiday"),
    ],
)
def test_holiday_detection(daily_last, when, expected, why):
    assert is_holiday(daily_last, when) is expected, why


# ---------------------------------------------------------------- resilience


def _raise(exc):
    def _fn(_ticker):
        raise exc

    return _fn


def test_resilient_fetch_serves_the_last_good_frame_on_failure(monkeypatch):
    data._last_good_daily().clear()
    good = frame_ending(TUE)
    monkeypatch.setattr(data, "fetch_daily", lambda _t: good)
    df, stale = fetch_daily_resilient("X.NS")
    assert stale is False and df.equals(good)

    monkeypatch.setattr(data, "fetch_daily", _raise(RuntimeError("rate limited")))
    df, stale = fetch_daily_resilient("X.NS")
    assert stale is True
    assert df.equals(good)


def test_resilient_fetch_propagates_for_a_never_seen_symbol(monkeypatch):
    """A symbol we have never fetched is far more likely a typo than a
    rate-limit, and swallowing that would hide a real error."""
    data._last_good_daily().clear()
    monkeypatch.setattr(data, "fetch_daily", _raise(ValueError("No data for 'NOPE'")))
    with pytest.raises(ValueError):
        fetch_daily_resilient("NOPE.NS")


def test_resilient_fetch_keeps_each_ticker_separate(monkeypatch):
    data._last_good_daily().clear()
    good = frame_ending(TUE)
    monkeypatch.setattr(data, "fetch_daily", lambda _t: good)
    fetch_daily_resilient("A.NS")

    monkeypatch.setattr(data, "fetch_daily", _raise(RuntimeError("down")))
    _, stale = fetch_daily_resilient("A.NS")
    assert stale is True
    with pytest.raises(RuntimeError):
        fetch_daily_resilient("B.NS")  # never succeeded, so no fallback
