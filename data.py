"""PivotDesk — data fetching and market status.

Thread-safe session management, Yahoo Finance data retrieval with caching,
and NSE market clock utilities.
"""

from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)

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


def completed_sessions(
    df: pd.DataFrame, now: dt.datetime, is_open: bool
) -> pd.DataFrame:
    """Drop today's partial candle while the market is open."""
    last_date = (
        df.index[-1].astimezone(IST).date() if df.index.tz else df.index[-1].date()
    )
    if is_open and last_date == now.date():
        return df.iloc[:-1]
    return df
