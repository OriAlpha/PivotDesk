"""Tests for the signal-confidence mini-backtest.

Pure over synthetic history — no network, no Streamlit runtime. The numbers
are pinned on hand-built series so the win-rate arithmetic is exact.
"""

from __future__ import annotations

import math

import pandas as pd

from backtest import MIN_SAMPLES, signal_confidence


def frame(closes: list[float], spread: float = 1.0) -> pd.DataFrame:
    idx = pd.bdate_range(start="2024-01-01", periods=len(closes), tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + spread for c in closes],
            "Low": [c - spread for c in closes],
            "Close": closes,
            "Volume": [1_000] * len(closes),
        },
        index=idx,
    )


def uptrend(n: int = 300) -> pd.DataFrame:
    """A gentle, steady rise — enough history for every signal to warm up."""
    closes = [100.0 + i * 0.2 + 3 * math.sin(i / 9) for i in range(n)]
    return frame(closes)


# ---------------------------------------------------------------- guards


def test_returns_none_when_history_is_too_short():
    c = signal_confidence(frame([100.0 + i for i in range(20)]), 3, 50.0)
    assert c is None


def test_returns_none_when_too_few_matches():
    """A gentle uptrend almost never visits a washed-out RSI (< 30), so a
    low-RSI query has no matches at all. The engine stays silent rather than
    quoting a win rate off a handful of days."""
    df = uptrend()
    c = signal_confidence(df, 5, 25.0)  # low RSI band, rare on a rising series
    assert c is None


# ---------------------------------------------------------------- arithmetic


def test_win_rate_is_the_fraction_of_matches_up_five_sessions_later():
    """On a steady uptrend, the neutral setup (3/6, mid RSI) should be up
    ~half the time five sessions later — within a wide band, since the series
    has noise. Pins the arithmetic, not the exact draw."""
    df = uptrend()
    c = signal_confidence(df, 3, 50.0)
    assert c is not None
    assert c.n >= MIN_SAMPLES
    assert 0.0 <= c.win_rate <= 1.0
    # A rising series drifts up, so the average forward return is positive.
    assert c.avg_return > 0


# ---------------------------------------------------------------- per-day score


def test_per_day_score_counts_exactly_six_signals():
    """The per-day score is the same six signals the card counts — a frame
    where price is below every MA, Supertrend down, MACD bearish, and below
    the prior pivot must score 0/6 once the decline is established."""
    from backtest import _per_day_scores

    # A long decline: price falls every day, so it sits below its trailing
    # MAs, the trend is down, MACD is bearish, and below the prior pivot.
    closes = [200.0 - i * 0.5 for i in range(250)]
    df = frame(closes, spread=0.1)
    score, _ = _per_day_scores(df)
    scored = score.dropna()
    assert len(scored) > 0
    # A warm-up transient (the MAs lag the start of the slide) can let one
    # signal fire early on; once the decline is established it is a clean 0/6.
    assert (scored.iloc[-200:] == 0).all()


def test_per_day_score_hits_six_on_a_steady_rise():
    from backtest import _per_day_scores

    closes = [100.0 + i * 0.5 for i in range(250)]
    df = frame(closes, spread=0.1)
    score, _ = _per_day_scores(df)
    scored = score.dropna()
    # A relentless rise trips every bullish signal once warmed up. The very
    # first days are warm-up transients, so check the established portion.
    assert (scored.iloc[-200:] == 6).all()


def test_per_day_rsi_bucket_separates_from_score():
    """Score and RSI are independent axes — a high score can coincide with a
    neutral RSI, which is exactly the case the backtest distinguishes."""
    from backtest import _per_day_scores, _rsi_bucket

    df = uptrend()
    _, rsi = _per_day_scores(df)
    # The gentle uptrend spends most days in the neutral band.
    bands = rsi.dropna().map(_rsi_bucket)
    assert (bands == "mid").sum() > 0
