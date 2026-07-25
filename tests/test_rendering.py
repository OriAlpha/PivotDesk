"""Tests for price resolution, technical scoring, and the position card."""

from __future__ import annotations

import pytest

from rendering import (
    action_card,
    entry_verdict,
    move_context,
    plain_summary,
    position_card,
    resolve_price,
    signal_chips,
    technical_score,
)


def _piv(pp, s1, s2, r1, r2):
    return {"PP": pp, "S1": s1, "S2": s2, "R1": r1, "R2": r2}


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
        100.0,
        ma(flags[0]),
        ma(flags[1]),
        ma(flags[2]),
        flags[3],
        flags[4],
        ma(flags[5]),
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


# ---------------------------------------------------------------- signal chips


def test_signal_chips_render_one_per_signal():
    html = signal_chips([True] * 6)
    assert html.count("<span") == 6
    for label in ("20D", "50D", "200D", "ST", "MACD", "PP"):
        assert label in html


def test_signal_chips_distinguish_pass_from_fail():
    html = signal_chips([True, False, True, False, True, False])
    assert html.count('class="on"') == 3
    assert html.count('class="off"') == 3


def test_signal_chips_do_not_rely_on_colour_alone():
    """Shape must carry the state too, for red-green colour blindness."""
    assert "●" in signal_chips([True] + [False] * 5)
    assert "○" in signal_chips([True] + [False] * 5)


def test_signal_chip_order_matches_the_scoring_order():
    # Only the third signal (200D) passes.
    html = signal_chips([False, False, True, False, False, False])
    assert '<span class="on">● 200D</span>' in html


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


# ---------------------------------------------------------------- position sizing


def test_position_card_sizes_off_the_entry_to_stop_distance():
    """₹5,000 risk, entry 100, stop 95 → 5 per share of downside → 1000 shares
    at ₹100,000 cost."""
    html = position_card(100.0, 110.0, True, 95.0, risk_budget=5000.0)
    assert "1,000 sh" in html
    assert "100,000.00 cost" in html
    assert "₹5,000.00 risk" in html


def test_position_card_omits_sizing_without_a_risk_budget():
    html = position_card(100.0, 110.0, True, 95.0)
    assert "Size:" not in html


def test_position_card_omits_sizing_in_a_downtrend():
    """The stop sits above the entry when the trend is down, so there is no
    downside distance to size a position off — the line must not appear."""
    html = position_card(100.0, 90.0, False, 104.0, risk_budget=5000.0)
    assert "Size:" not in html


def test_position_card_omits_sizing_when_the_stop_is_at_or_above_entry():
    """Zero or negative entry-to-stop would divide by zero or invert the math."""
    assert "Size:" not in position_card(100.0, 110.0, True, 100.0, risk_budget=5000.0)
    assert "Size:" not in position_card(100.0, 110.0, True, 105.0, risk_budget=5000.0)


# ---------------------------------------------------------------- entry verdict


def test_downtrend_stands_aside_whatever_the_price():
    """Gate 1: a broken trend is a wait, however cheap the price looks."""
    v = entry_verdict(100.0, 1, False, 104.0, 40.0, 2.0, _piv(101, 98, 94, 106, 110))
    assert v.label == "Don't buy yet"
    assert v.css == "dn"
    assert v.kind == "reclaim"
    # No buy range is offered when there is no trend to buy into.
    assert v.zone_lo is None and v.zone_hi is None


def test_uptrend_with_bearish_signals_waits_for_confirmation():
    v = entry_verdict(100.0, 2, True, 97.0, 45.0, 2.0, _piv(101, 98, 94, 106, 110))
    assert v.label == "Wait — not clear yet"
    assert v.css == "warn"
    assert v.kind == "mixed"
    assert v.zone_lo is None and v.zone_hi is None


def test_near_support_in_an_uptrend_is_a_buy_zone():
    v = entry_verdict(100.0, 5, True, 97.0, 55.0, 2.0, _piv(99, 96, 92, 103, 107))
    assert v.label == "Good spot to buy"
    assert v.css == "up"
    # The band is real support below the price, low first.
    assert v.zone_lo <= v.zone_hi < 100.0
    assert v.risk_pct == pytest.approx(3.0)


def test_overbought_uptrend_waits_for_a_better_price():
    v = entry_verdict(100.0, 5, True, 97.0, 75.0, 2.0, _piv(99, 96, 92, 103, 107))
    assert v.label == "Wait for a better price"
    assert v.css == "warn"
    assert "overheated" in v.reason  # reason matches the real trigger
    # Even when chasing, it still names the range to wait for.
    assert v.zone_lo is not None and v.zone_hi is not None


def test_stretched_far_above_the_pivot_waits_for_a_better_price():
    """No overbought RSI, but ~5 ATR above the pivot is still a chase."""
    v = entry_verdict(110.0, 5, True, 96.0, 55.0, 2.0, _piv(100, 97, 93, 113, 117))
    assert v.label == "Wait for a better price"
    assert "jumped far" in v.reason


def test_far_from_the_exit_reads_as_risky_not_stretched():
    """Regression: an entry only ~0.3 ATR above the pivot still tripped the wait,
    because the stop was >8% away — but the reason wrongly said 'stretched'.
    The wording must describe the exit distance, not a run-up that did not happen."""
    v = entry_verdict(100.0, 5, True, 90.0, 55.0, 2.0, _piv(99.4, 96, 92, 103, 107))
    assert v.label == "Wait for a better price"
    assert "safety exit" in v.reason
    assert "jumped" not in v.reason and "overheated" not in v.reason


def test_midrange_uptrend_accumulates_on_dips():
    v = entry_verdict(103.0, 5, True, 97.0, 60.0, 2.0, _piv(100, 98, 94, 106, 110))
    assert v.label == "OK, but wait for a dip"
    assert v.css == "up"


def test_verdict_zone_bounds_sit_below_the_price():
    v = entry_verdict(100.0, 5, True, 97.0, 55.0, 2.0, _piv(99, 96, 92, 103, 107))
    assert v.zone_hi < 100.0
    assert v.zone_lo <= v.zone_hi


# ---------------------------------------------------------------- action card


def _buy_zone():
    return entry_verdict(100.0, 5, True, 97.0, 55.0, 2.0, _piv(99, 96, 92, 103, 107))


_SUMMARY = "RELIANCE is rising strongly — a lower-risk spot to start buying."


def test_action_card_leads_with_the_summary_sentence():
    html = action_card(_buy_zone(), _SUMMARY)
    assert _SUMMARY in html  # the sentence is the headline, not a separate label
    assert 'class="asum"' in html
    assert 'class="acard up"' in html
    assert "Buy" in html and "sell below" in html and "risk ~" in html


def test_action_card_has_no_advice_disclaimer():
    assert "not investment advice" not in action_card(_buy_zone(), _SUMMARY)


def test_action_card_marks_a_stale_price():
    fresh = action_card(_buy_zone(), _SUMMARY)
    stale = action_card(_buy_zone(), _SUMMARY, stale=True)
    assert "not live" not in fresh
    assert "not live" in stale


def test_action_card_shows_how_far_the_exit_sits_when_waiting():
    # price 110, stop 96 → (110-96)/110 ≈ 12.7% → "~13% above exit".
    v = entry_verdict(110.0, 5, True, 96.0, 55.0, 2.0, _piv(100, 97, 93, 113, 117))
    assert v.kind == "wait"
    html = action_card(v, "X is rising strongly — better to wait for a dip.")
    assert "above exit" in html
    assert "13%" in html


def test_action_card_for_a_downtrend_offers_a_reclaim_not_an_entry_zone():
    v = entry_verdict(100.0, 1, False, 104.0, 40.0, 2.0, _piv(101, 98, 94, 106, 110))
    html = action_card(
        v, "INFY is falling right now — best to wait until it turns back up."
    )
    assert "falling right now" in html
    assert 'class="acard dn"' in html
    assert "move back above" in html
    assert "sell below" not in html  # nothing to buy, so no buy-range line


# ---------------------------------------------------------------- plain summary


def _buy_verdict():
    return entry_verdict(100.0, 5, True, 97.0, 55.0, 2.0, _piv(99, 96, 92, 103, 107))


def test_summary_names_the_stock_and_ends_with_the_call():
    s = plain_summary("RELIANCE", 5, True, 55.0, _buy_verdict())
    assert s.startswith("RELIANCE ")
    assert "rising" in s
    assert s.endswith("buying.")


def test_summary_flags_a_hot_stock():
    hot = entry_verdict(100.0, 5, True, 97.0, 75.0, 2.0, _piv(99, 96, 92, 103, 107))
    s = plain_summary("TCS", 5, True, 75.0, hot)
    assert "hot" in s
    assert "wait" in s


def test_summary_for_a_downtrend_says_falling_and_wait():
    dn = entry_verdict(100.0, 1, False, 104.0, 40.0, 2.0, _piv(101, 98, 94, 106, 110))
    s = plain_summary("INFY", 1, False, 40.0, dn)
    assert "falling" in s
    assert "turns back up" in s


def test_summary_never_contradicts_the_verdict():
    """The summary and the Action card come from the same inputs, so a 'buy'
    verdict must not produce a 'wait' sentence, or vice versa."""
    v = _buy_verdict()
    assert "wait" not in plain_summary("X", 5, True, 55.0, v).lower()


# ---------------------------------------------------------------- move context


@pytest.mark.parametrize(
    "chg,phrase",
    [
        (0.4, "smaller than a normal day"),
        (2.0, "about a normal day"),
        (3.5, "bigger than a normal day"),
        (6.0, "much bigger than a normal day"),
    ],
)
def test_move_context_scales_to_the_stocks_own_normal_day(chg, phrase):
    # A 2%/day stock: the same ₹ move reads differently than for a calm stock.
    assert phrase in move_context(chg, 2.0)


def test_move_context_is_blank_without_a_usable_daily_range():
    assert move_context(1.5, 0.0) == ""


def test_move_context_is_direction_agnostic():
    """A 3% drop is as big a day as a 3% rise."""
    assert move_context(-3.5, 2.0) == move_context(3.5, 2.0)
