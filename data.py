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

from config import HOLIDAY_GRACE, IST, MARKET_CLOSE, MARKET_OPEN

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
    # Keep Adj Close alongside the raw OHLC. Levels must stay unadjusted so they
    # match what a broker terminal shows, but returns should be total-return —
    # see compute_indicators.
    cols = ["Open", "High", "Low", "Close", "Volume"]
    if "Adj Close" in df.columns:
        cols.append("Adj Close")
    return df[cols].dropna()


@st.cache_resource
def _last_good_daily() -> dict[str, pd.DataFrame]:
    """Last successful daily frame per ticker, surviving cache expiry.

    ``fetch_daily``'s TTL means a Yahoo rate-limit at the wrong moment leaves
    nothing to render. Keeping the last good frame lets the dashboard degrade
    to stale-but-labelled instead of a blank error page.
    """
    return {}


def fetch_daily_resilient(ticker: str) -> tuple[pd.DataFrame, bool]:
    """``(daily, is_stale)`` — fall back to the last good frame on failure.

    Only falls back for a ticker that has succeeded before. A symbol we have
    never fetched is far more likely to be a typo than a rate-limit, and
    silently swallowing that would hide a real error.
    """
    store = _last_good_daily()
    try:
        df = fetch_daily(ticker)
    except Exception as e:
        cached = store.get(ticker)
        if cached is None:
            raise
        logger.warning("Daily fetch failed for %s, serving last good: %s", ticker, e)
        return cached, True
    store[ticker] = df
    return df, False


@st.cache_data(ttl=55, show_spinner=False)
def fetch_live_price(ticker: str) -> tuple[float, float, float] | None:
    """Fetch latest price, day-low, day-high from Yahoo's quote (cached 55 s).

    Reads the quote snapshot, **not** the 1-minute chart series. The 1m bars
    disagree with the authoritative daily candle: measured across NSE names,
    the last bar was off by up to ₹1.10 and the day high by ₹3.90, because the
    chart aggregation lags the closing auction and misses part of the day's
    extremes. The quote matches the daily candle exactly.

    Note this is the *last traded price*, which is not NSE's official closing
    price — see the README. No Yahoo endpoint publishes the latter.

    Returns ``None`` on any failure — errors are logged rather than
    silently swallowed.
    """
    try:
        session = get_session()
        quote = yf.Ticker(ticker, session=session).fast_info
        price = float(quote["last_price"])
        low = float(quote["day_low"])
        high = float(quote["day_high"])
        if not (price > 0 and low > 0 and high >= low):
            logger.warning(
                "Implausible quote for %s: last=%s low=%s high=%s",
                ticker, price, low, high,
            )
            return None
        # Keep the day range coherent if the quote updates before its extremes.
        return price, min(low, price), max(high, price)
    except Exception as e:
        logger.warning("Live price fetch failed for %s: %s", ticker, e)
    return None


def is_holiday(daily_last: dt.date, now: dt.datetime) -> bool:
    """True when a weekday inside market hours has no session of its own.

    Derived rather than looked up: on a trading day Yahoo publishes a row for
    today within minutes of the open, so a weekday that still has none well
    after the bell is a holiday. Self-maintaining — no annual list to update.
    """
    if now.weekday() >= 5 or not (HOLIDAY_GRACE <= now.time() <= MARKET_CLOSE):
        return False
    return daily_last < now.date()


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
