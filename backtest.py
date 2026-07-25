"""PivotDesk — signal-confidence mini-backtest.

Answers the trust question behind the technical-bias card: *when this exact
setup (score + RSI band) has occurred before, how often was the stock up N
sessions later?* Built from the same daily history the dashboard already
holds, so no extra network.

The match is intentionally coarse-but-specific: the 0–6 bias score crossed
with three RSI bands (lo < 30, mid, hi >= 70). Coarse enough to amass 8+
samples on 2y of data, specific enough to mean something. Fewer than 8
historical cases returns ``None`` — the card stays silent rather than quoting
a win rate off three observations.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from indicators import supertrend_series

HOLD = 5  # sessions forward to measure the outcome over
MIN_SAMPLES = 8  # below this we won't quote a win rate


@dataclass(frozen=True)
class Confidence:
    """How the same setup has played out historically."""

    win_rate: float  # fraction of matching days that were up HOLD sessions later
    n: int  # number of historical matches
    avg_return: float  # mean forward return across those matches, %


def _rsi_bucket(val: float) -> str:
    """Three-band RSI bucket, matching the card's own extreme flags."""
    if val < 30:
        return "lo"
    if val >= 70:
        return "hi"
    return "mid"


def _per_day_scores(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Per-day ``(score, rsi)`` over the same six signals the card counts.

    Each signal is computed on data available *on that day*: moving averages
    and MACD are trailing, Supertrend and the daily pivot use the prior
    session's H/L/C so the score for day *i* could actually have been read at
    the close of day *i*. Warm-up rows where SMA200 is still NaN are masked
    (NA) — those days had no real score, only gaps.
    """
    close = df["Close"]
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    # SMA200 mirrors the card's own fallback: the full-history mean when there
    # are fewer than 200 sessions. Per day, that is the expanding mean up to
    # that day — what the card would have shown on that date.
    sma200 = close.rolling(200).mean().fillna(close.expanding().mean())

    macd_line = (
        close.ewm(span=12, adjust=False).mean()
        - close.ewm(span=26, adjust=False).mean()
    )
    signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_bull = (macd_line - signal) > 0

    up_series, _ = supertrend_series(df)

    # Daily pivot PP uses the *prior* session's H/L/C, so a day's score is
    # readable at that day's close, not with hindsight into the day itself.
    prev_high = df["High"].shift(1)
    prev_low = df["Low"].shift(1)
    prev_close = close.shift(1)
    pp = (prev_high + prev_low + prev_close) / 3

    parts = [
        (close > sma20).fillna(False),
        (close > sma50).fillna(False),
        (close > sma200).fillna(False),
        up_series,
        macd_bull.fillna(False),
        (close > pp).fillna(False),
    ]
    score = sum(p.astype(int) for p in parts)
    # Drop the warm-up rows where the slowest signal (sma200) is still NaN.
    score = score.where(~sma200.isna(), other=pd.NA)
    return score, _rsi_series(close)


def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """Per-day Wilder RSI. The flat-series edge case (gain 0 → 50) is applied
    per-day so a stretch of no-downside reads as neutral, not maximally hot."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss)
    # Where there is no downside at all, gain/loss → inf → RSI 100; but a flat
    # stretch has no upside either, so call it the neutral 50.
    flat = loss <= 0
    rsi = rsi.where(~flat | (gain > 0), other=50.0)
    rsi = rsi.where(~(flat & (gain <= 0)), other=50.0)
    return rsi


def signal_confidence(
    df: pd.DataFrame, score: int, rsi_val: float, hold: int = HOLD
) -> Confidence | None:
    """How often the same (score, RSI band) setup led to a gain ``hold``
    sessions later. Returns ``None`` when too few historical matches to trust."""
    if len(df) <= hold + 1:
        return None

    per_day_score, per_day_rsi = _per_day_scores(df)
    close = df["Close"]

    # Forward return over ``hold`` sessions, aligned to the day the setup was
    # readable (i.e. the close the score was computed at).
    fwd = close.shift(-hold) / close - 1

    target_bucket = _rsi_bucket(rsi_val)
    mask = (per_day_score == score) & (
        per_day_rsi.map(lambda v: _rsi_bucket(v) if pd.notna(v) else None)
        == target_bucket
    )
    mask = mask & per_day_score.notna() & fwd.notna()
    matched = fwd[mask]
    n = len(matched)
    if n < MIN_SAMPLES:
        return None
    wins = (matched > 0).sum()
    return Confidence(
        win_rate=float(wins / n),
        n=n,
        avg_return=float(matched.mean() * 100),
    )
