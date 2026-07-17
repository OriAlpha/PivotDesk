"""PivotDesk — technical indicators and cached computation bundle.

All heavy indicator math lives here.  ``compute_indicators()`` wraps
everything behind ``@st.cache_data`` so work is only repeated when the
underlying daily data or the calendar date changes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------- primitives


def pivots(h: float, l: float, c: float) -> dict[str, float]:
    """Standard daily pivot points (PP, R1/R2, S1/S2)."""
    pp = (h + l + c) / 3
    return {
        "PP": pp,
        "R1": 2 * pp - l,
        "S1": 2 * pp - h,
        "R2": pp + (h - l),
        "S2": pp - (h - l),
    }


def rsi(close: pd.Series, period: int = 14) -> float:
    """Wilder-smoothed RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder-smoothed)."""
    prev_close = df["Close"].shift()
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def macd_state(close: pd.Series) -> tuple[bool, bool]:
    """(is_bullish, momentum_building)."""
    macd_line = (
        close.ewm(span=12, adjust=False).mean()
        - close.ewm(span=26, adjust=False).mean()
    )
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return bool(hist.iloc[-1] > 0), bool(abs(hist.iloc[-1]) >= abs(hist.iloc[-2]))


def supertrend(
    df: pd.DataFrame, period: int = 10, mult: float = 3.0
) -> tuple[bool, float]:
    """(is_uptrend, stop_level) — classic Supertrend.

    Inner loops operate on raw NumPy arrays instead of Pandas ``.iloc``
    indexing, which avoids per-access overhead and is ~20-50× faster.
    """
    hl2 = (df["High"] + df["Low"]) / 2
    a = atr(df, period)
    ub = (hl2 + mult * a).values
    lb = (hl2 - mult * a).values
    close_arr = df["Close"].values
    n = len(df)

    fub = ub.copy()
    flb = lb.copy()
    for i in range(1, n):
        fub[i] = (
            ub[i]
            if (ub[i] < fub[i - 1] or close_arr[i - 1] > fub[i - 1])
            else fub[i - 1]
        )
        flb[i] = (
            lb[i]
            if (lb[i] > flb[i - 1] or close_arr[i - 1] < flb[i - 1])
            else flb[i - 1]
        )

    up = True
    for i in range(period, n):
        up = close_arr[i] > fub[i] if not up else close_arr[i] >= flb[i]

    return up, float(flb[-1] if up else fub[-1])


def weekly_pivot(df: pd.DataFrame, today: dt.date) -> float:
    """Weekly pivot point from last completed week's H/L/C."""
    wk = (
        df.resample("W-FRI")
        .agg({"High": "max", "Low": "min", "Close": "last"})
        .dropna()
    )
    if not wk.empty:
        wk_end = (
            wk.index[-1].date()
            if not wk.index.tz
            else wk.index[-1].astimezone(IST).date()
        )
        if wk_end >= today:  # current week still in progress
            wk = wk.iloc[:-1]
    h, l, c = wk.iloc[-1][["High", "Low", "Close"]]
    return (h + l + c) / 3


def pct_return(close: pd.Series, sessions: int) -> float | None:
    """Percentage return over *sessions* trading days, or None if not enough data."""
    if len(close) <= sessions:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - sessions] - 1) * 100


# ---------------------------------------------------------------- cached bundle


@dataclass
class IndicatorBundle:
    """Pre-computed indicator values, cached to avoid redundant recomputation."""

    prev_high: float
    prev_low: float
    prev_close: float
    piv: dict[str, float]
    sma20: float
    sma50: float
    sma200: float
    rsi_val: float
    macd_bull: bool
    macd_building: bool
    st_up: bool
    st_stop: float
    atr_val: float
    vol_ratio: float
    lo52: float
    hi52: float
    weekly_pp: float
    returns: list[tuple[str, float | None]]


@st.cache_data(show_spinner=False)
def compute_indicators(df: pd.DataFrame, today: dt.date) -> IndicatorBundle:
    """Compute every indicator from completed-session daily data.

    Cached by DataFrame content hash + calendar date, so indicators are
    only recomputed when the underlying daily data changes or a new
    trading day starts — not on every 60-second live-price refresh.
    """
    close = df["Close"]
    prev = df.iloc[-1]
    ph = float(prev["High"])
    pl = float(prev["Low"])
    pc = float(prev["Close"])
    piv = pivots(ph, pl, pc)

    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = (
        float(close.rolling(200).mean().iloc[-1])
        if len(close) >= 200
        else float(close.mean())
    )

    rsi_val = rsi(close)
    bull, building = macd_state(close)
    st_up, st_stop = supertrend(df)
    atr_val = float(atr(df).iloc[-1])

    vol_mean = df["Volume"].iloc[-31:-1].mean()
    vol_ratio = (
        float(df["Volume"].iloc[-1] / vol_mean)
        if vol_mean and not pd.isna(vol_mean)
        else 1.0
    )

    yr = df.tail(252)
    lo52 = float(yr["Low"].min())
    hi52 = float(yr["High"].max())

    wpp = weekly_pivot(df, today)

    rets: list[tuple[str, float | None]] = []
    for lab, n in (("1W", 5), ("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252)):
        rets.append((lab, pct_return(close, n)))

    return IndicatorBundle(
        prev_high=ph,
        prev_low=pl,
        prev_close=pc,
        piv=piv,
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        rsi_val=rsi_val,
        macd_bull=bull,
        macd_building=building,
        st_up=st_up,
        st_stop=st_stop,
        atr_val=atr_val,
        vol_ratio=vol_ratio,
        lo52=lo52,
        hi52=hi52,
        weekly_pp=wpp,
        returns=rets,
    )
