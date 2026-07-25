"""PivotDesk — live pivot-point dashboard for NSE stocks.

Daily pivots roll automatically from the last completed NSE session.
Swing metrics (MAs, RSI, MACD, Supertrend, ATR, volume, returns) are
computed from daily history. Live price refreshes every 60s while the
market is open. Data: Yahoo Finance via yfinance. Not investment advice.
"""

from __future__ import annotations

import traceback

import streamlit as st

from data import fetch_daily, fetch_live_price
from positions import (
    Position,
    format_positions,
    parse_positions,
    set_position,
    symbol_key,
)
from rendering import render, render_error
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
  
  /* Ensure iframe occupies full width */
  iframe {
    width: 100% !important;
    border: none !important;
  }
  
  /* Style the buttons inside columns to look like premium pills */
  div[data-testid="stColumn"] button, div[data-testid="column"] button {
    background-color: rgba(255, 255, 255, 0.03) !important;
    color: #7E8DA8 !important;
    border: 1px solid #1E2C48 !important;
    border-radius: 99px !important;
    padding: 2px 10px !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    font-family: 'IBM Plex Mono', monospace !important;
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

  /* Premium Expander styling to match PivotDesk card panels */
  div[data-testid="stExpander"] {
    background-color: rgba(20, 29, 48, 0.72) !important;
    border: 1px solid #1E2C48 !important;
    border-radius: 16px !important;
    overflow: hidden !important;
    margin-top: 16px !important;
  }
  div[data-testid="stExpander"] summary {
    background-color: transparent !important;
    color: #7E8DA8 !important;
    font-size: 11px !important;
    font-weight: 800 !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    padding: 12px 18px !important;
  }
  div[data-testid="stExpander"] summary:hover {
    color: #EDF2FB !important;
  }
  div[data-testid="stExpanderDetails"] {
    padding: 0px 14px 14px 14px !important;
    background-color: transparent !important;
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

# Risk budget
default_risk = _positive_param("risk")
if default_risk is None:
    default_risk = app_state.risk

# Keep query params in sync with active defaults
if not st.query_params.get("ticker"):
    st.query_params["ticker"] = default_ticker
if positions_raw and "positions" not in st.query_params:
    st.query_params["positions"] = positions_raw
if default_risk is not None and "risk" not in st.query_params:
    st.query_params["risk"] = f"{default_risk:.0f}"

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
        "Qty *",
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
        "Risk ₹ *",
        min_value=0.0,
        value=default_risk,
        step=500.0,
        format="%.0f",
        placeholder="Budget",
        key="risk_input",
        help="Rupees you'd risk on the trade — sizes the position off the entry-to-stop distance",
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
    if st.query_params.get("risk") != f"{risk:.0f}":
        st.query_params["risk"] = f"{risk:.0f}"
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

DEFAULT_PILLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "TATAMOTORS", "BHAGYANGR"]
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


@st.fragment(run_every="60s")
def dashboard() -> None:
    pos_str = st.query_params.get("positions", "")
    risk_str = st.query_params.get("risk", "")
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
