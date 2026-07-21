"""End-to-end render tests against synthetic data (no network).

``Template.safe_substitute`` leaves unknown placeholders in the output
instead of raising, so a template edit can silently ship a literal
``$chg_html`` to the browser. These tests walk the whole render path and
assert the rendered document is fully substituted.
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

TUE = dt.date(2026, 7, 21)  # a Tuesday
MON = dt.date(2026, 7, 20)


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


@pytest.fixture
def rendered(monkeypatch):
    """Render with patched I/O and return the HTML handed to the iframe."""

    def _render(*, last_session, now, live, entry=0.0):
        captured: dict[str, str] = {}
        monkeypatch.setattr(
            rendering.st, "iframe", lambda html, **kw: captured.update(html=html)
        )
        monkeypatch.setattr(rendering, "fetch_daily", lambda _t: history(last_session))
        monkeypatch.setattr(rendering, "fetch_live_price", lambda _t: live)
        rendering.render("TEST.NS", entry, now=now)
        return captured["html"]

    return _render


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


# ---------------------------------------------------------------- substitution


def test_live_render_has_no_unsubstituted_placeholders(rendered):
    html = rendered(
        last_session=MON, now=at(TUE, 11, 0), live=(150.0, 148.0, 152.0), entry=100.0
    )
    assert PLACEHOLDER.findall(html) == []


def test_stale_render_has_no_unsubstituted_placeholders(rendered):
    html = rendered(last_session=MON, now=at(TUE, 11, 0), live=None, entry=100.0)
    assert PLACEHOLDER.findall(html) == []


def test_closed_render_has_no_unsubstituted_placeholders(rendered):
    html = rendered(last_session=TUE, now=at(TUE, 16, 30), live=None)
    assert PLACEHOLDER.findall(html) == []


# ---------------------------------------------------------------- stale path


def test_failed_live_fetch_says_so_instead_of_showing_a_flat_change(rendered):
    html = rendered(last_session=MON, now=at(TUE, 11, 0), live=None)
    assert "Live price unavailable" in html
    assert "(+0.00%)" not in html
    assert "· STALE" in html
    # A stale price must not keep the healthy pulsing "market open" dot.
    assert "animation:pulse 2s infinite" not in html
    # No intraday data means no day-range bar (the class always exists in CSS,
    # so match the markup).
    assert '<div class="day-range-box">' not in html


def test_live_render_keeps_the_open_market_indicator(rendered):
    html = rendered(last_session=MON, now=at(TUE, 11, 0), live=(150.0, 148.0, 152.0))
    assert "Live price unavailable" not in html
    assert "· STALE" not in html
    assert "animation:pulse 2s infinite" in html
    assert '<div class="day-range-box">' in html


# ---------------------------------------------------------------- change readout


def test_closed_market_shows_the_last_sessions_real_move(rendered):
    """Regression: outside market hours the change was always +0.00."""
    html = rendered(last_session=TUE, now=at(TUE, 16, 30), live=None)
    assert "(+0.00%)" not in html
    assert re.search(r"[▲▼] [-+][\d,.]+ \([-+]\d+\.\d\d%\)", html)


def test_weekend_shows_the_last_sessions_real_move(rendered):
    html = rendered(last_session=TUE, now=at(dt.date(2026, 7, 25), 11, 0), live=None)
    assert "WEEKEND" in html
    assert "(+0.00%)" not in html


def test_live_change_is_measured_against_the_previous_close(rendered):
    hist = history(MON)
    prev_close = float(hist["Close"].iloc[-1])
    html = rendered(
        last_session=MON, now=at(TUE, 11, 0), live=(prev_close + 5.0, 148.0, 152.0)
    )
    assert f"▲ {5.0:+,.2f}" in html


# ---------------------------------------------------------------- 52-week range


def test_new_high_reads_as_full_range_not_over_100_percent(rendered):
    """Regression: a live price above the completed-session 52w high produced
    an impossible reading like "103% of range"."""
    html = rendered(last_session=MON, now=at(TUE, 11, 0), live=(9_999.0, 9_000.0, 9_999.0))
    pct = int(re.search(r">(\d+)% of range<", html).group(1))
    assert pct == 100
