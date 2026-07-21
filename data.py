"""PivotDesk — data fetching and market status.

Thread-safe session management, Yahoo Finance data retrieval with caching,
and NSE market clock utilities.
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests

from config import IST, MARKET_CLOSE, MARKET_OPEN

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- market clock


def market_status(now: dt.datetime) -> tuple[bool, str]:
    """(is_open, label). Weekdays 09:15–15:30 IST. NSE holidays appear
    closed only through stale data; see README."""
    if now.weekday() >= 5:
        return False, "MARKET CLOSED · WEEKEND"
    if MARKET_OPEN <= now.time() <= MARKET_CLOSE:
        return True, f"MARKET OPEN · {now:%H:%M} IST"
    return False, f"MARKET CLOSED · {now:%H:%M} IST"


# ---------------------------------------------------------------- session


@st.cache_resource
def get_session() -> requests.Session:
    """Thread-safe cached session for yfinance requests.

    Uses ``st.cache_resource`` so that one session is shared per Streamlit
    process rather than a bare global — safe under concurrent requests.
    """
    return requests.Session(impersonate="chrome")


# ---------------------------------------------------------------- data fetch


@st.cache_data(ttl=600, show_spinner=False)
def fetch_daily(ticker: str) -> pd.DataFrame:
    """Fetch 2 years of daily OHLCV from Yahoo Finance (cached 10 min)."""
    session = get_session()
    df = yf.Ticker(ticker, session=session).history(
        period="2y", interval="1d", auto_adjust=False
    )
    if df.empty:
        raise ValueError(
            f"No data for '{ticker}'. Check the symbol (e.g. BHAGYANGR.NS)."
        )
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


@st.cache_data(ttl=55, show_spinner=False)
def fetch_live_price(ticker: str) -> tuple[float, float, float] | None:
    """Fetch latest intraday price, day-low, day-high (cached 55 s).

    Returns ``None`` on any failure — errors are logged rather than
    silently swallowed.
    """
    try:
        session = get_session()
        intra = yf.Ticker(ticker, session=session).history(
            period="1d", interval="1m"
        )
        if not intra.empty:
            return (
                float(intra["Close"].iloc[-1]),
                float(intra["Low"].min()),
                float(intra["High"].max()),
            )
    except Exception as e:
        logger.warning("Live price fetch failed for %s: %s", ticker, e)
    return None


def completed_sessions(df: pd.DataFrame, now: dt.datetime) -> pd.DataFrame:
    """Drop today's candle unless today's session has actually finished.

    Anything dated today before 15:30 IST is a partial candle — during the
    session *and* pre-open, where Yahoo may already publish a near-empty
    row. Keying on the clock rather than on ``is_open`` covers both.
    """
    last_date = (
        df.index[-1].astimezone(IST).date() if df.index.tz else df.index[-1].date()
    )
    if last_date == now.date() and now.time() < MARKET_CLOSE:
        return df.iloc[:-1]
    return df
