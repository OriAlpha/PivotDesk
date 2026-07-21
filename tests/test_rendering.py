"""Tests for price resolution, technical scoring, and the position card."""

from __future__ import annotations

import re

import pytest

from rendering import (
    position_card,
    resolve_price,
    sparkline_svg,
    technical_score,
)

# Last completed session, and the one before it.
PREV_CLOSE, PREV_LOW, PREV_HIGH = 145.0, 143.0, 147.0
PRIOR_CLOSE = 140.0


# ---------------------------------------------------------------- price view


def test_live_quote_is_measured_against_the_last_close():
    pv = resolve_price(
        (150.0, 148.0, 152.0), True, PREV_CLOSE, PREV_LOW, PREV_HIGH, PRIOR_CLOSE
    )
    assert pv.price == 150.0
    assert pv.baseline == PREV_CLOSE
    assert (pv.day_low, pv.day_high) == (148.0, 152.0)
    assert pv.stale is False


def test_closed_market_is_measured_against_the_prior_session():
    """Regression: the last close was compared against itself, so the change
    readout was a permanent +0.00 outside market hours."""
    pv = resolve_price(None, False, PREV_CLOSE, PREV_LOW, PREV_HIGH, PRIOR_CLOSE)
    assert pv.price == PREV_CLOSE
    assert pv.baseline == PRIOR_CLOSE
    assert pv.price - pv.baseline == pytest.approx(5.0)
    assert pv.stale is False


def test_closed_market_shows_the_last_session_range():
    pv = resolve_price(None, False, PREV_CLOSE, PREV_LOW, PREV_HIGH, PRIOR_CLOSE)
    assert (pv.day_low, pv.day_high) == (PREV_LOW, PREV_HIGH)


def test_failed_live_fetch_is_flagged_stale():
    """Regression: a failed quote rendered yesterday's close as a live price,
    with a +0.00 change and a healthy pulsing "market open" indicator."""
    pv = resolve_price(None, True, PREV_CLOSE, PREV_LOW, PREV_HIGH, PRIOR_CLOSE)
    assert pv.stale is True
    assert pv.price == PREV_CLOSE
    # No intraday data means no honest day range to draw.
    assert pv.day_low is None
    assert pv.day_high is None


def test_falls_back_to_the_last_close_without_a_prior_session():
    pv = resolve_price(None, False, PREV_CLOSE, PREV_LOW, PREV_HIGH, None)
    assert pv.baseline == PREV_CLOSE


# ---------------------------------------------------------------- scoring


def _score(n: int):
    """Build inputs producing exactly *n* of the six bullish signals."""
    flags = [True] * n + [False] * (6 - n)
    below, above = 99.0, 101.0  # price is 100.0

    def ma(bullish: bool) -> float:
        return below if bullish else above

    return technical_score(
        100.0, ma(flags[0]), ma(flags[1]), ma(flags[2]), flags[3], flags[4], ma(flags[5])
    )


@pytest.mark.parametrize(
    "n,label,cls",
    [
        (6, "Strong bullish", "up"),
        (5, "Bullish", "up"),
        (4, "Leaning bullish", "up"),
        (3, "Neutral", "warn"),
        (2, "Leaning bearish", "dn"),
        (1, "Bearish", "dn"),
        (0, "Strong bearish", "dn"),
    ],
)
def test_technical_score_thresholds(n, label, cls):
    score, got_label, got_cls = _score(n)
    assert score == n
    assert got_label == label
    assert got_cls == cls


def test_technical_score_matches_the_documented_six_signals():
    assert _score(6)[0] == 6
    assert _score(0)[0] == 0


def test_every_score_has_a_distinct_label():
    """Regression: 5-6 and 0-1 shared a "Strong" label, so the headline verdict
    fired on 55.7% of days (measured over 19,443 NSE ticker-days)."""
    labels = [_score(n)[1] for n in range(7)]
    assert len(set(labels)) == 7


def test_only_the_extremes_are_called_strong():
    strong = [n for n in range(7) if "Strong" in _score(n)[1]]
    assert strong == [0, 6]


# ---------------------------------------------------------------- position card


def test_position_card_prompts_without_an_entry_price():
    html = position_card(0.0, 110.0, True, 95.0)
    assert "enter your buy price" in html
    assert "%" not in html.split('class="big"')[1][:40]


def test_position_card_reports_gain_and_trend_stop():
    html = position_card(100.0, 110.0, True, 95.0)
    assert "+10.0%" in html
    assert "+₹10.00/sh" in html
    assert "Trend intact" in html


def test_position_card_reports_loss():
    html = position_card(100.0, 90.0, False, 95.0)
    assert "-10.0%" in html
    assert "-₹10.00/sh" in html
    assert "Trend broken" in html


def test_position_card_warns_when_price_nears_the_stop():
    html = position_card(100.0, 110.0, True, 109.0)
    assert "APPROACHING STOP" in html
    assert "warn-flash" in html


def test_position_card_marks_a_stale_price():
    fresh = position_card(100.0, 110.0, True, 95.0)
    stale = position_card(100.0, 110.0, True, 95.0, stale=True)
    assert "not live" not in fresh
    assert "not live" in stale


def test_position_card_reports_rupees_when_given_a_quantity():
    html = position_card(100.0, 110.0, True, 95.0, qty=40)
    assert "+₹400" in html  # 40 shares x ₹10
    assert "/sh" not in html
    assert "40 sh" in html


def test_position_card_falls_back_to_per_share_without_a_quantity():
    assert "/sh" in position_card(100.0, 110.0, True, 95.0)
    assert "/sh" in position_card(100.0, 110.0, True, 95.0, qty=0)


# ---------------------------------------------------------------- sparkline

LEVELS = {"S2": 96.0, "S1": 98.0, "PP": 100.0, "R1": 102.0, "R2": 104.0}


def _line_ys(svg: str) -> list[float]:
    return [float(y) for y in re.findall(r'<line x1="0" y1="([\d.]+)"', svg)]


def test_sparkline_needs_at_least_two_points():
    assert sparkline_svg([], LEVELS).svg == ""
    assert sparkline_svg([100.0], LEVELS).svg == ""


def test_sparkline_draws_a_path_and_all_five_levels():
    spark = sparkline_svg([100.0, 105.0, 102.0, 108.0], LEVELS)
    assert spark.svg.startswith('<svg class="spark"')
    assert "<polyline" in spark.svg and "<polygon" in spark.svg
    assert len(_line_ys(spark.svg)) == 5  # S2, S1, R1, R2, PP
    assert "<rect" in spark.svg  # the shaded S2..R2 zone


def test_sparkline_colours_by_direction():
    assert "--sup" in sparkline_svg([100.0, 110.0], LEVELS).svg  # rising
    assert "--res" in sparkline_svg([110.0, 100.0], LEVELS).svg  # falling


def test_sparkline_reports_the_range_it_scaled_to():
    spark = sparkline_svg([100.0, 130.0], LEVELS)
    assert spark.high == 130.0  # a close above R2 widens the top
    assert spark.low == 96.0  # S2 sits below every close, so it sets the floor


@pytest.mark.parametrize(
    "levels",
    [
        LEVELS,
        {"S2": 10.0, "S1": 20.0, "PP": 30.0, "R1": 40.0, "R2": 50.0},  # far below
        {"S2": 500.0, "S1": 600.0, "PP": 700.0, "R1": 800.0, "R2": 900.0},  # far above
    ],
)
def test_sparkline_keeps_every_level_inside_the_viewbox(levels):
    """Levels outside the close range must not be clipped out of sight."""
    spark = sparkline_svg([100.0, 101.0, 102.0], levels, height=120)
    ys = _line_ys(spark.svg)
    assert len(ys) == 5
    assert all(0 <= y <= 120 for y in ys)


def test_sparkline_extends_to_the_live_price():
    """During a session the curve must reach the price shown in the hero,
    not stop at the last completed close."""
    without = sparkline_svg([100.0, 101.0, 102.0], LEVELS)
    with_live = sparkline_svg([100.0, 101.0, 102.0], LEVELS, live=140.0)
    assert len(with_live.svg.split()) > len(without.svg.split())
    assert with_live.high == 140.0
    # The end dot tracks the live point, and a jump up must lift the top.
    assert with_live.high > without.high
