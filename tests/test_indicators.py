"""Golden-value tests for the indicator math.

Every function here is pure — no network, no Streamlit runtime — so the
numbers the dashboard reports can be pinned down exactly.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from indicators import (
    atr,
    macd_state,
    pct_return,
    pivots,
    rsi,
    supertrend,
    weekly_pivot,
)


def frame(closes: list[float], spread: float = 1.0, start: str = "2025-01-06"):
    """Daily OHLCV frame on business days, High/Low a fixed spread around Close."""
    idx = pd.bdate_range(start=start, periods=len(closes), tz="Asia/Kolkata")
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


# ---------------------------------------------------------------- pivots


def test_pivots_symmetric_golden():
    assert pivots(110.0, 90.0, 100.0) == pytest.approx(
        {"PP": 100.0, "R1": 110.0, "S1": 90.0, "R2": 120.0, "S2": 80.0}
    )


def test_pivots_asymmetric_golden():
    # PP = (105+95+104)/3 = 101.3333
    p = pivots(105.0, 95.0, 104.0)
    assert p["PP"] == pytest.approx(304 / 3)
    assert p["R1"] == pytest.approx(2 * (304 / 3) - 95)
    assert p["S1"] == pytest.approx(2 * (304 / 3) - 105)
    assert p["R2"] == pytest.approx(304 / 3 + 10)
    assert p["S2"] == pytest.approx(304 / 3 - 10)


def test_pivots_ordered():
    p = pivots(105.0, 95.0, 104.0)
    assert p["S2"] < p["S1"] < p["PP"] < p["R1"] < p["R2"]


# ---------------------------------------------------------------- rsi


def test_rsi_unbroken_gains_is_100():
    assert rsi(pd.Series(range(1, 40), dtype=float)) == 100.0


def test_rsi_unbroken_losses_is_0():
    assert rsi(pd.Series(range(40, 1, -1), dtype=float)) == pytest.approx(0.0)


def test_rsi_flat_series_is_neutral():
    assert rsi(pd.Series([100.0] * 40)) == 50.0


def test_rsi_no_downside_never_returns_nan():
    """Regression: ``gain / loss`` with zero loss yielded NaN, rendered "nan"."""
    value = rsi(pd.Series([100.0] * 20 + [101.0] * 20))
    assert value == value  # NaN is the only value that fails this
    assert value == 100.0


def test_rsi_mid_range_for_mixed_moves():
    closes = [100.0 + (1 if i % 2 else -1) for i in range(60)]
    assert 30 < rsi(pd.Series(closes)) < 70


# ---------------------------------------------------------------- atr


def test_atr_constant_true_range():
    # H-L is 10 daily and Close never gaps, so TR == 10 on every bar.
    df = frame([100.0] * 30, spread=5.0)
    assert float(atr(df).iloc[-1]) == pytest.approx(10.0)


def test_atr_accounts_for_overnight_gaps():
    flat = frame([100.0] * 30, spread=1.0)
    gappy = frame([100.0 + 10 * i for i in range(30)], spread=1.0)
    assert float(atr(gappy).iloc[-1]) > float(atr(flat).iloc[-1])


# ---------------------------------------------------------------- macd


def test_macd_bullish_in_uptrend():
    bull, _ = macd_state(pd.Series(range(1, 200), dtype=float))
    assert bull is True


def test_macd_bearish_in_downtrend():
    bull, _ = macd_state(pd.Series(range(200, 1, -1), dtype=float))
    assert bull is False


# ---------------------------------------------------------------- supertrend


def test_supertrend_uptrend_puts_stop_below_price():
    closes = [100.0 + i for i in range(120)]
    up, stop = supertrend(frame(closes))
    assert up is True
    assert stop < closes[-1]


def test_supertrend_downtrend_puts_stop_above_price():
    closes = [300.0 - i for i in range(120)]
    up, stop = supertrend(frame(closes))
    assert up is False
    assert stop > closes[-1]


def test_supertrend_flips_down_after_a_crash():
    closes = [100.0 + i for i in range(100)] + [199.0 - 8 * i for i in range(1, 21)]
    up, stop = supertrend(frame(closes))
    assert up is False
    assert stop > closes[-1]


# ---------------------------------------------------------------- weekly pivot


def test_weekly_pivot_uses_last_completed_week():
    # 15 business days from Mon 2025-01-06 = three full weeks. Week three is
    # closes 11..15, so High 20, Low 6, Close 15.
    df = frame([float(i) for i in range(1, 16)], spread=5.0)
    assert weekly_pivot(df, dt.date(2025, 1, 27)) == pytest.approx((20 + 6 + 15) / 3)


def test_weekly_pivot_skips_the_week_in_progress():
    # Same data, but "today" sits inside week three, so week two is the last
    # completed one: closes 6..10 → High 15, Low 1, Close 10.
    df = frame([float(i) for i in range(1, 16)], spread=5.0)
    assert weekly_pivot(df, dt.date(2025, 1, 22)) == pytest.approx((15 + 1 + 10) / 3)


def test_weekly_pivot_keeps_the_only_week_it_has():
    """Regression: trimming the in-progress week emptied a single-week frame."""
    df = frame([100.0, 101.0, 102.0], spread=5.0)
    assert weekly_pivot(df, dt.date(2025, 1, 8)) == pytest.approx((107 + 95 + 102) / 3)


def test_weekly_pivot_rejects_empty_history():
    empty = frame([]).astype({"Close": float})
    with pytest.raises(ValueError):
        weekly_pivot(empty, dt.date(2025, 1, 8))


# ---------------------------------------------------------------- returns


def test_pct_return_exact():
    closes = pd.Series([100.0, 0.0, 0.0, 0.0, 0.0, 110.0])
    assert pct_return(closes, 5) == pytest.approx(10.0)


def test_pct_return_negative():
    closes = pd.Series([100.0, 0.0, 0.0, 0.0, 0.0, 90.0])
    assert pct_return(closes, 5) == pytest.approx(-10.0)


def test_pct_return_none_when_history_too_short():
    assert pct_return(pd.Series([1.0] * 5), 5) is None
    assert pct_return(pd.Series([1.0] * 6), 5) is not None
