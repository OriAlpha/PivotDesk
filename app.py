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
from rendering import render, render_error

# ---------------------------------------------------------------- page config

st.set_page_config(
    page_title="PivotDesk",
    page_icon="📐",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------- reload logic

# Check if query parameter "reload" is set to "1" to clear cache
if st.query_params.get("reload") == "1":
    fetch_live_price.clear()
    fetch_daily.clear()
    params = st.query_params.to_dict()
    if "reload" in params:
        del params["reload"]
    st.query_params.clear()
    for k, v in params.items():
        st.query_params[k] = v
    st.session_state["reload_status"] = "success"
    st.session_state["initialized"] = True
    st.rerun()

# Clear cache on new browser tab session load
if not st.session_state.get("initialized"):
    fetch_live_price.clear()
    fetch_daily.clear()
    st.session_state["initialized"] = True

reload_status = st.session_state.get("reload_status", "")
if "reload_status" in st.session_state:
    del st.session_state["reload_status"]

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

default_ticker = st.query_params.get("ticker", "BHAGYANGR.NS")
default_entry = None
if "entry" in st.query_params:
    try:
        val = float(st.query_params["entry"])
        if val > 0:
            default_entry = val
    except ValueError:
        pass

c1, c2 = st.columns([3, 2])
with c1:
    raw = st.text_input("NSE ticker", value=default_ticker,
                        help="Any NSE symbol — .NS is added automatically")
with c2:
    entry = st.number_input("Your buy price ₹ (optional)", min_value=0.0,
                            value=default_entry, step=0.05, format="%.2f",
                            placeholder="Enter entry price",
                            key=f"entry_input_{default_ticker}",
                            help="Average entry price — enables the position monitor")

if raw != default_ticker or (entry is not None and entry != default_entry) or (entry is None and default_entry is not None):
    st.query_params["ticker"] = raw
    if entry is not None:
        st.query_params["entry"] = str(entry)
    else:
        if "entry" in st.query_params:
            del st.query_params["entry"]

# ---------------------------------------------------------------- quick-access pills

favs_str = st.query_params.get("favorites", "BHAGYANGR,RELIANCE,TCS,INFY,TATASTEEL")
favorites = [f.strip().upper() for f in favs_str.split(",") if f.strip()]

col_widths = [1.2] + [1] * len(favorites) + [0.6]
cols_fav = st.columns(col_widths, gap="small")
with cols_fav[0]:
    st.markdown("<div style='color:#7E8DA8;font-size:11px;font-weight:700;margin-top:6px;text-transform:uppercase;letter-spacing:0.05em'>Quick list:</div>", unsafe_allow_html=True)
for idx, fav in enumerate(favorites):
    with cols_fav[idx + 1]:
        if st.button(fav, key=f"fav_{fav}", use_container_width=True):
            st.query_params["ticker"] = fav + ".NS"
            if "entry" in st.query_params:
                del st.query_params["entry"]
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
    favs_str = st.query_params.get("favorites", "BHAGYANGR,RELIANCE,TCS,INFY,TATASTEEL")
    try:
        render(ticker, entry, reload_cls=reload_status, favorites_str=favs_str)
    except ValueError as e:
        st.error(str(e))
    except Exception as e:
        traceback.print_exc()
        st.session_state["reload_status"] = "failed"
        render_error(ticker, str(e), entry=entry, favorites_str=favs_str)

if ticker:
    dashboard()
