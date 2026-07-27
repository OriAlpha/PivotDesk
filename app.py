"""PivotDesk — live pivot-point dashboard for NSE stocks.

Daily pivots roll automatically from the last completed NSE session.
Swing metrics (MAs, RSI, MACD, Supertrend, ATR, volume, returns) are
computed from daily history. Live price refreshes every 60s while the
market is open. Data: Yahoo Finance via yfinance. Not investment advice.
"""

from __future__ import annotations

import datetime as dt
import traceback

import streamlit as st

from config import IST
from data import (
    fetch_daily,
    fetch_daily_resilient,
    fetch_live_price,
    market_status,
    session_is_live,
)
from positions import (
    Position,
    format_positions,
    parse_positions,
    set_position,
    symbol_key,
)
from rendering import CHART_STATE_KEY, render, render_chart_panel, render_error
from state import load_state, save_state

# ---------------------------------------------------------------- page config

st.set_page_config(
    page_title="PivotDesk",
    page_icon="📐",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------- reload logic

if st.query_params.get("reload") == "1":
    fetch_live_price.clear()
    fetch_daily.clear()
    params = st.query_params.to_dict()
    del params["reload"]
    st.query_params.clear()
    for k, v in params.items():
        st.query_params[k] = v
    st.session_state["reload_status"] = "success"
    st.rerun()

reload_status = st.session_state.pop("reload_status", "")

# ---------------------------------------------------------------- premium CSS

st.markdown(
    """<style>
  .stApp{background:#0A0E17}
  header, header[data-testid="stHeader"]{display:none!important}
  div[data-testid="stToolbar"],footer, div[data-testid="stDecoration"]{visibility:hidden;display:none!important}
  /* Premium Input Styling */
  .stTextInput input, div[data-testid="stNumberInputContainer"] {
    background-color: #0D1527 !important;
    color: #EDF2FB !important;
    border: 1px solid #1E2C48 !important;
    border-radius: 10px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    transition: all 0.3s ease-in-out !important;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.4) !important;
  }
  
  /* Inner input inside number input container needs to have no border and same color */
  div[data-testid="stNumberInputContainer"] input {
    border: none !important;
    background-color: transparent !important;
    color: #EDF2FB !important;
  }
  
  /* Focus glow states */
  .stTextInput input:focus, div[data-testid="stNumberInputContainer"]:focus-within {
    border-color: #6FA4FF !important;
    box-shadow: 0 0 12px rgba(111, 164, 255, 0.25), inset 0 1px 3px rgba(0, 0, 0, 0.4) !important;
    background-color: #111A30 !important;
  }
  
  /* Style number input step buttons (+ and -) */
  div[data-testid="stNumberInputContainer"] button {
    background-color: transparent !important;
    border: none !important;
    color: #7E8DA8 !important;
    transition: all 0.2s ease !important;
  }
  div[data-testid="stNumberInputContainer"] button:hover {
    color: #6FA4FF !important;
  }

  /* Premium Labels styling */
  .stTextInput label, .stNumberInput label {
    color: #7E8DA8 !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.12em !important;
    margin-bottom: 6px !important;
    white-space: nowrap !important;
  }
  
  /* Widen and center the main container and remove excess top padding */
  .stMainBlockContainer, .block-container, div[data-testid="stAppViewBlockContainer"] {
    max-width: 980px !important;
    padding-top: 0.5rem !important;
    padding-bottom: 1rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    margin: 0 auto !important;
    margin-top: 0px !important;
  }
  
  .stMain {
    margin-top: 0px !important;
    padding-top: 0px !important;
  }
  
  /* Ensure iframe occupies full width without inner scrollbars */
  iframe {
    width: 100% !important;
    border: none !important;
    overflow: hidden !important;
  }
  
  /* Style the buttons inside columns to look like premium pills */
  div[data-testid="stColumn"] button, div[data-testid="column"] button {
    background-color: rgba(255, 255, 255, 0.03) !important;
    color: #7E8DA8 !important;
    border: 1px solid #1E2C48 !important;
    border-radius: 99px !important;
    padding: 2px 6px !important;
    font-size: 10.5px !important;
    font-weight: 700 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    white-space: nowrap !important;
    text-overflow: ellipsis !important;
    overflow: hidden !important;
    transition: all 0.2s ease !important;
    height: auto !important;
    line-height: 1.2 !important;
    min-height: 24px !important;
  }
  div[data-testid="stColumn"] button:hover, div[data-testid="column"] button:hover {
    color: #6FA4FF !important;
    border-color: #6FA4FF !important;
    background-color: rgba(111, 164, 255, 0.05) !important;
  }
  
  /* Smooth fade-in animation for input toggles */
  @keyframes slide-fade-in {
    0% { opacity: 0; transform: translateY(-8px); }
    100% { opacity: 1; transform: translateY(0); }
  }
  div[data-testid="stTextInput"] {
    animation: slide-fade-in 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards !important;
  }

  /* Premium POSITIONS Card matching Action Card 1:1 */
  div[data-testid="stExpander"] {
    background-color: #0A0E17 !important;
    border: 1px solid #1E2C48 !important;
    border-radius: 16px !important;
    margin-bottom: 16px !important;
    margin-top: 10px !important;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3) !important;
    overflow: hidden !important;
  }
  div[data-testid="stExpander"] details {
    border: none !important;
    background-color: transparent !important;
  }
  div[data-testid="stExpander"] summary {
    background-color: rgba(255, 255, 255, 0.02) !important;
    border: none !important;
    padding: 14px 20px !important;
    border-radius: 16px !important;
    outline: none !important;
    box-shadow: none !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    text-align: center !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
    list-style: none !important;
  }
  div[data-testid="stExpander"] summary::-webkit-details-marker,
  div[data-testid="stExpander"] summary::marker {
    display: none !important;
    content: "" !important;
  }
  div[data-testid="stExpander"] summary:hover, div[data-testid="stExpander"] summary:focus {
    background-color: rgba(255, 255, 255, 0.04) !important;
    outline: none !important;
    box-shadow: none !important;
  }
  /* Hide expander toggle icon, SVG, and browser detail markers */
  div[data-testid="stExpander"] summary [data-testid="stExpanderToggleIcon"],
  div[data-testid="stExpander"] summary [data-testid="stExpanderIcon"],
  div[data-testid="stExpander"] summary [data-testid="stIconMaterial"],
  div[data-testid="stExpander"] summary svg,
  div[data-testid="stExpander"] summary i,
  div[data-testid="stExpander"] summary img,
  div[data-testid="stExpander"] summary [class*="material"],
  div[data-testid="stExpander"] summary [class*="icon"],
  div[data-testid="stExpander"] summary [class*="Icon"] {
    display: none !important;
    font-size: 0px !important;
    line-height: 0 !important;
    color: transparent !important;
    width: 0px !important;
    height: 0px !important;
    max-width: 0px !important;
    max-height: 0px !important;
    opacity: 0 !important;
    visibility: hidden !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    pointer-events: none !important;
  }
  /* Style and guarantee visibility of POSITIONS text */
  div[data-testid="stExpander"] summary p,
  div[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    font-size: 11px !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    color: #7E8DA8 !important;
    font-weight: 800 !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    text-align: center !important;
    margin: 0 auto !important;
    padding: 0 !important;
    width: 100% !important;
    justify-content: center !important;
    align-items: center !important;
  }
  div[data-testid="stExpanderDetails"] {
    padding: 16px 20px 18px 20px !important;
    background-color: transparent !important;
    border-top: 1px solid #1E2C48 !important;
  }
</style>""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- inputs


def _positive_param(name: str) -> float | None:
    """Read a positive float from the query string, or None."""
    if name not in st.query_params:
        return None
    try:
        val = float(st.query_params[name])
    except ValueError:
        return None
    return val if val > 0 else None


# Load persistent local state
app_state = load_state()

# Record unique session visit
if "visited" not in st.session_state:
    st.session_state.visited = True
    app_state.record_visit(is_new_session=True)
    save_state(app_state)

# Default parameters: query string overrides local file storage if non-empty
raw_ticker = st.query_params.get("ticker", "").strip()
if not raw_ticker:
    raw_ticker = (app_state.last_ticker or "").strip()
if not raw_ticker:
    raw_ticker = "RELIANCE.NS"

default_ticker = raw_ticker
positions_raw = st.query_params.get("positions")
if positions_raw is None:
    positions_raw = app_state.positions_raw

book = parse_positions(positions_raw)
current_symbol = symbol_key(default_ticker)

# Fold legacy ?entry=/?qty= into the book
legacy_entry, legacy_qty = _positive_param("entry"), _positive_param("qty")
if legacy_entry is not None or legacy_qty is not None:
    book = set_position(book, current_symbol, legacy_entry, legacy_qty)
    st.query_params["positions"] = format_positions(book)
    for legacy in ("entry", "qty"):
        if legacy in st.query_params:
            del st.query_params[legacy]

held = book.get(current_symbol, Position())
default_entry, default_qty = held.entry, held.qty

# Risk percentage (defaults to 5.0%)
url_risk = _positive_param("risk")
if url_risk is not None and url_risk <= 100.0:
    default_risk = url_risk
elif app_state.risk is not None and app_state.risk <= 100.0:
    default_risk = app_state.risk
else:
    default_risk = 5.0

default_risk = min(100.0, max(0.1, float(default_risk)))

# Keep query params in sync with active defaults
if not st.query_params.get("ticker"):
    st.query_params["ticker"] = default_ticker
if positions_raw and "positions" not in st.query_params:
    st.query_params["positions"] = positions_raw
if default_risk is not None and "risk" not in st.query_params:
    st.query_params["risk"] = f"{default_risk:.1f}"

with st.expander("POSITIONS", expanded=False):
    c1, c2, c3, c4 = st.columns([2.5, 2.2, 1.3, 1.3])
    with c1:
        raw = st.text_input(
            "NSE ticker",
            value=default_ticker,
            help="Any NSE symbol — .NS is added automatically",
        )
    with c2:
        entry = st.number_input(
            "Buy price ₹ *",
            min_value=0.0,
            value=default_entry,
            step=0.05,
            format="%.2f",
            placeholder="Enter entry price",
            key=f"entry_input_{default_ticker}",
            help="Average entry price — enables the position monitor",
        )
    with c3:
        qty = st.number_input(
            "Quantity *",
            min_value=0.0,
            value=default_qty,
            step=1.0,
            format="%.0f",
            placeholder="Shares",
            key=f"qty_input_{default_ticker}",
            help="Share count — shows P&L in rupees instead of per share",
        )
    with c4:
        risk = st.number_input(
            "Risk % *",
            min_value=0.1,
            max_value=100.0,
            value=default_risk,
            step=0.5,
            format="%.1f",
            placeholder="5.0%",
            key="risk_input",
            help="Percentage of trade capital to risk — sizes position off Supertrend stop distance",
        )

    # Handle ticker & position updates, saving state to file as well
    if raw != default_ticker:
        if raw.strip():
            st.query_params["ticker"] = raw.strip()
            app_state.last_ticker = raw.strip()
            app_state.add_recent_search(raw.strip())
            save_state(app_state)
            st.rerun()
    elif entry != default_entry or qty != default_qty:
        book = set_position(book, current_symbol, entry, qty)
        formatted = format_positions(book)
        if book:
            st.query_params["positions"] = formatted
        elif "positions" in st.query_params:
            del st.query_params["positions"]
        app_state.positions_raw = formatted
        save_state(app_state)

    if risk and risk > 0:
        if st.query_params.get("risk") != f"{risk:.1f}":
            st.query_params["risk"] = f"{risk:.1f}"
        app_state.risk = risk
        save_state(app_state)
    elif "risk" in st.query_params:
        del st.query_params["risk"]
        app_state.risk = None
        save_state(app_state)

    ticker = raw.strip().upper()
    if ticker and "." not in ticker:
        ticker += ".NS"

    # Ensure active ticker is in recent searches
    app_state.add_recent_search(ticker)
    save_state(app_state)

    # ---------------------------------------------------------------- quick jump pills

    DEFAULT_PILLS = [
        "RELIANCE",
        "TCS",
        "INFY",
        "HDFCBANK",
        "TATAMOTORS",
        "BHAGYANGR",
    ]
    jump_symbols: list[str] = []
    # Recent user searches lead first, followed by held positions, followed by defaults
    for sym in (app_state.recent_searches or []) + list(book.keys()) + DEFAULT_PILLS:
        clean_sym = symbol_key(sym)
        if clean_sym and clean_sym not in jump_symbols:
            jump_symbols.append(clean_sym)

    jump_symbols = jump_symbols[:5]  # Show 5 pills on screen

    if jump_symbols:
        cols_jump = st.columns([1] * len(jump_symbols), gap="small")
        active_key = symbol_key(default_ticker)
        for idx, sym in enumerate(jump_symbols):
            with cols_jump[idx]:
                is_active = sym == active_key
                label = f"● {sym}" if is_active else sym
                if st.button(label, key=f"pill_{sym}", use_container_width=True):
                    st.query_params["ticker"] = sym + ".NS"
                    app_state.last_ticker = sym + ".NS"
                    app_state.add_recent_search(sym + ".NS")
                    save_state(app_state)
                    st.rerun()

# ---------------------------------------------------------------- dashboard


def session_live_now() -> bool:
    """Whether a real NSE session is running, holidays included.

    The daily fetch is cached and ``render()`` makes the same call moments
    later, so consulting it here is effectively free. If it fails outright,
    fall back to the clock and let ``render()`` surface the error properly
    rather than crashing the script before the page exists.
    """
    now = dt.datetime.now(IST)
    try:
        daily, daily_stale = fetch_daily_resilient(ticker)
    except Exception:
        return market_status(now)[0]
    return session_is_live(daily, daily_stale, now)


# Only a live session produces new prices. Outside one the whole page — chart
# included — was being rebuilt every minute to redraw the same numbers, so the
# beat slows down after the bell and picks back up at the next open.
MARKET_LIVE_AT_LOAD = session_live_now()
REFRESH_EVERY = "60s" if MARKET_LIVE_AT_LOAD else "5m"


@st.fragment(run_every=REFRESH_EVERY)
def dashboard() -> None:
    # run_every was fixed when the script last ran in full, and a fragment
    # rerun does not re-read it. A tab left open across the bell needs an app
    # rerun to pick up the other cadence.
    if session_live_now() != MARKET_LIVE_AT_LOAD:
        st.rerun(scope="app")

    pos_str = st.query_params.get("positions", "")
    risk_str = st.query_params.get("risk", "")
    # A failed render must not leave the previous chart standing next to an
    # error message as though it were current.
    st.session_state.pop(CHART_STATE_KEY, None)
    try:
        render(
            ticker,
            entry,
            reload_cls=reload_status,
            qty=qty,
            positions_str=pos_str,
            risk_budget=float(risk_str) if risk_str else 0.0,
        )
    except ValueError as e:
        st.error(str(e))
    except Exception as e:
        traceback.print_exc()
        render_error(ticker, str(e), entry=entry, positions_str=pos_str)


if ticker:
    dashboard()
    # Outside the fragment on purpose: this frame is left alone by the 60s
    # rerun, so the chart keeps its zoom and timeframe between refreshes.
    render_chart_panel(total_visits=app_state.total_visits)
