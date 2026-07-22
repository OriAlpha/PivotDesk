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

# ---------------------------------------------------------------- page config

st.set_page_config(
    page_title="PivotDesk",
    page_icon="📐",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------- reload logic

# ``.clear()`` empties the cache for the whole process, not just this session —
# on Streamlit Community Cloud one process serves every viewer. So it is wired
# only to the explicit Reload link, never to page or session load, where it
# would multiply Yahoo requests and invite the rate-limiting it is meant to
# recover from. Routine freshness is the TTLs' job (see data.py).
DEFAULT_FAVORITES = "BHAGYANGR,RELIANCE,TCS,INFY,TATASTEEL"

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

st.markdown("""<style>
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
</style>""", unsafe_allow_html=True)

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


default_ticker = st.query_params.get("ticker", "BHAGYANGR.NS")
book = parse_positions(st.query_params.get("positions", ""))
current_symbol = symbol_key(default_ticker)

# Fold any legacy ?entry=/?qty= URL into the book, so bookmarks made before
# positions existed keep working instead of silently losing their cost basis.
legacy_entry, legacy_qty = _positive_param("entry"), _positive_param("qty")
if legacy_entry is not None or legacy_qty is not None:
    book = set_position(book, current_symbol, legacy_entry, legacy_qty)
    st.query_params["positions"] = format_positions(book)
    for legacy in ("entry", "qty"):
        if legacy in st.query_params:
            del st.query_params[legacy]

held = book.get(current_symbol, Position())
default_entry, default_qty = held.entry, held.qty

c1, c2, c3 = st.columns([3, 2, 1.4])
with c1:
    raw = st.text_input("NSE ticker", value=default_ticker,
                        help="Any NSE symbol — .NS is added automatically")
with c2:
    entry = st.number_input("Your buy price ₹ (optional)", min_value=0.0,
                            value=default_entry, step=0.05, format="%.2f",
                            placeholder="Enter entry price",
                            key=f"entry_input_{default_ticker}",
                            help="Average entry price — enables the position monitor")
with c3:
    qty = st.number_input("Qty (optional)", min_value=0.0,
                          value=default_qty, step=1.0, format="%.0f",
                          placeholder="Shares",
                          key=f"qty_input_{default_ticker}",
                          help="Share count — shows P&L in rupees instead of per share")


# A ticker change and a position edit are handled separately and never in the
# same run. The entry/qty widgets are keyed to the *old* ticker while its
# replacement is being typed, so writing them here would file one stock's cost
# basis under another's name.
if raw != default_ticker:
    st.query_params["ticker"] = raw
    st.rerun()  # reload so the inputs repopulate from the new symbol's position
elif entry != default_entry or qty != default_qty:
    book = set_position(book, current_symbol, entry, qty)
    if book:
        st.query_params["positions"] = format_positions(book)
    elif "positions" in st.query_params:
        del st.query_params["positions"]

# ---------------------------------------------------------------- quick-access pills

favs_str = st.query_params.get("favorites", DEFAULT_FAVORITES)
favorites = [f.strip().upper() for f in favs_str.split(",") if f.strip()]

show_favs = st.session_state.get("show_favs", False)
toggle_col, _ = st.columns([1.4, 6], gap="small")
with toggle_col:
    if st.button(f"Quick list {'▴' if show_favs else '▾'}", key="toggle_favs",
                 use_container_width=True, help="Show or hide your saved symbols"):
        st.session_state["show_favs"] = not show_favs
        if show_favs:  # collapsing also closes the editor beneath it
            st.session_state["show_edit_favs"] = False
        st.rerun()

if show_favs:
    cols_fav = st.columns([1] * len(favorites) + [0.6], gap="small")
    for idx, fav in enumerate(favorites):
        with cols_fav[idx]:
            if st.button(fav, key=f"fav_{fav}", use_container_width=True):
                # The position travels with the symbol now — nothing to clear.
                st.query_params["ticker"] = fav + ".NS"
                st.rerun()
    with cols_fav[-1]:
        show_edit = st.session_state.get("show_edit_favs", False)
        if st.button("✏️", key="toggle_edit_favs", help="Edit favorite stock list"):
            st.session_state["show_edit_favs"] = not show_edit
            st.rerun()

    if st.session_state.get("show_edit_favs", False):
        new_favs = st.text_input("Edit favorites (comma-separated, e.g. TCS, RELIANCE, INFY)",
                                 value=favs_str,
                                 help="Type your symbols, then press Enter to save to your Quick list")
        if new_favs != favs_str:
            st.query_params["favorites"] = new_favs
            st.rerun()

ticker = raw.strip().upper()
if ticker and "." not in ticker:
    ticker += ".NS"

# ---------------------------------------------------------------- dashboard

@st.fragment(run_every="60s")
def dashboard() -> None:
    favs_str = st.query_params.get("favorites", DEFAULT_FAVORITES)
    pos_str = st.query_params.get("positions", "")
    try:
        render(ticker, entry, reload_cls=reload_status, favorites_str=favs_str,
               qty=qty, positions_str=pos_str)
    except ValueError as e:
        st.error(str(e))
    except Exception as e:
        traceback.print_exc()
        # No reload_status write here: the header above already ran and will not
        # re-run for a fragment refresh, and HTML_ERROR renders its own failed
        # state. Setting it would only leak onto the next full page load.
        render_error(ticker, str(e), entry=entry, favorites_str=favs_str, positions_str=pos_str)

if ticker:
    dashboard()
