"""End-to-end render tests against synthetic data (no network).

``Template.safe_substitute`` leaves unknown placeholders in the output
instead of raising, so a template edit can silently ship a literal
``$chg_html`` to the browser. These tests walk the whole render path and
assert the rendered document is fully substituted.

``data_through`` is the last row in the *raw* daily frame, before
``completed_sessions`` trims it. On a live trading day Yahoo publishes a
partial row for today, so ``data_through`` is today; a weekday where it is
not is what holiday detection keys on.
"""

from __future__ import annotations

import datetime as dt
import math
import re

import pandas as pd
import pytest

import rendering
from config import IST

PLACEHOLDER = re.compile(r"\$[a-zA-Z_][a-zA-Z0-9_]*")

MON = dt.date(2026, 7, 20)
TUE = dt.date(2026, 7, 21)
SAT = dt.date(2026, 7, 25)


def history(last: dt.date, periods: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(last), periods=periods, tz="Asia/Kolkata")
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


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


@pytest.fixture
def rendered(monkeypatch):
    """Render with patched I/O and return the HTML handed to the iframe."""

    def _render(*, data_through, now, live, entry=0.0, qty=0.0, daily_stale=False):
        captured: dict[str, str] = {}
        monkeypatch.setattr(
            rendering.st, "iframe", lambda html, **kw: captured.update(html=html)
        )
        monkeypatch.setattr(
            rendering,
            "fetch_daily_resilient",
            lambda _t: (history(data_through), daily_stale),
        )
        monkeypatch.setattr(rendering, "fetch_live_price", lambda _t: live)
        rendering.render("TEST.NS", entry, now=now, qty=qty)
        return captured["html"]

    return _render


OPEN = dict(data_through=TUE, now=at(TUE, 11, 0))
CLOSED = dict(data_through=TUE, now=at(TUE, 16, 30), live=None)
WEEKEND = dict(data_through=TUE, now=at(SAT, 11, 0), live=None)
HOLIDAY = dict(data_through=MON, now=at(TUE, 11, 0), live=None)


# ---------------------------------------------------------------- substitution


@pytest.mark.parametrize(
    "case", [dict(OPEN, live=(150.0, 148.0, 152.0)), dict(OPEN, live=None), CLOSED,
             WEEKEND, HOLIDAY]
)
def test_render_has_no_unsubstituted_placeholders(rendered, case):
    assert PLACEHOLDER.findall(rendered(**case, entry=100.0, qty=25)) == []


# ---------------------------------------------------------------- stale price


def test_failed_live_fetch_says_so_instead_of_showing_a_flat_change(rendered):
    html = rendered(**OPEN, live=None)
    assert "Live price unavailable" in html
    assert "(+0.00%)" not in html
    assert "· STALE" in html
    # A stale price must not keep the healthy pulsing "market open" dot.
    assert "animation:pulse 2s infinite" not in html
    # No intraday data means no day-range bar (the class always exists in CSS,
    # so match the markup).
    assert '<div class="day-range-box">' not in html


def test_live_render_keeps_the_open_market_indicator(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert "Live price unavailable" not in html
    assert "· STALE" not in html
    assert "animation:pulse 2s infinite" in html
    assert '<div class="day-range-box">' in html


# ---------------------------------------------------------------- change readout


def test_closed_market_shows_the_last_sessions_real_move(rendered):
    """Regression: outside market hours the change was always +0.00."""
    html = rendered(**CLOSED)
    assert "(+0.00%)" not in html
    assert re.search(r"[▲▼] [-+][\d,.]+ \([-+]\d+\.\d\d%\)", html)


def test_weekend_shows_the_last_sessions_real_move(rendered):
    html = rendered(**WEEKEND)
    assert "WEEKEND" in html
    assert "(+0.00%)" not in html


def test_live_change_is_measured_against_the_previous_close(rendered):
    # Today's partial row is dropped, so the anchor is the row before it.
    prev_close = float(history(TUE)["Close"].iloc[-2])
    html = rendered(**OPEN, live=(prev_close + 5.0, 148.0, 152.0))
    assert f"▲ {5.0:+,.2f}" in html


# ---------------------------------------------------------------- holidays


def test_weekday_without_a_session_is_reported_as_a_holiday(rendered):
    """A weekday inside market hours with no row of its own is an NSE holiday,
    not an open market with a broken feed."""
    html = rendered(**HOLIDAY)
    assert "NSE HOLIDAY" in html
    assert "animation:pulse 2s infinite" not in html
    assert "Live price unavailable" not in html  # closed, not stale
    assert "(+0.00%)" not in html  # still shows the last session's real move


def test_normal_trading_day_is_not_a_holiday(rendered):
    assert "HOLIDAY" not in rendered(**OPEN, live=(150.0, 148.0, 152.0))


def test_weekend_is_not_called_a_holiday(rendered):
    assert "HOLIDAY" not in rendered(**WEEKEND)


def test_stale_daily_data_is_not_mistaken_for_a_holiday(rendered):
    """Served-from-cache data is behind by construction; that is a fetch
    failure to report, not a market holiday."""
    html = rendered(**HOLIDAY, daily_stale=True)
    assert "NSE HOLIDAY" not in html
    assert "Yahoo data unavailable" in html


def test_fresh_daily_data_shows_no_banner(rendered):
    assert "Yahoo data unavailable" not in rendered(**OPEN, live=(150.0, 148.0, 152.0))


# ---------------------------------------------------------------- 52-week range


def test_new_high_reads_as_full_range_not_over_100_percent(rendered):
    """Regression: a live price above the completed-session 52w high produced
    an impossible reading like "103% of range"."""
    html = rendered(**OPEN, live=(9_999.0, 9_000.0, 9_999.0))
    assert int(re.search(r">(\d+)% of range<", html).group(1)) == 100


# ---------------------------------------------------------------- bias card


def test_the_signal_breakdown_needs_no_hover(rendered):
    """Regression: the breakdown lived in a title attribute, so it required
    hover and was invisible on every touch device."""
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert 'class="sigchips"' in html
    assert "title=" not in html
    assert "cursor:help" not in html
    assert "ⓘ" not in html


def test_all_six_signals_are_shown_on_the_card(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    chips = re.search(r'<div class="sigchips">(.*?)</div>', html, re.S).group(1)
    assert chips.count("<span") == 6
    for label in ("20D", "50D", "200D", "ST", "MACD", "PIV"):
        assert label in chips


def test_the_chip_count_matches_the_headline_score(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    chips = re.search(r'<div class="sigchips">(.*?)</div>', html, re.S).group(1)
    score = int(re.search(r">(\d)/6 signals bullish", html).group(1))
    assert chips.count('class="on"') == score


def test_the_correlation_caveat_is_not_present(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert "Not six independent reads" not in html
