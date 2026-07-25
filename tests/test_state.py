"""Tests for state.py local JSON persistence and recent searches."""

from __future__ import annotations

from state import AppState, load_state, save_state


def test_add_recent_search_places_search_first_and_caps_at_5():
    state = AppState()
    tickers = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "TATAMOTORS", "SBIN", "WIPRO"]
    for t in tickers:
        state.add_recent_search(t)

    # Most recent is WIPRO, followed by SBIN, TATAMOTORS, HDFCBANK, INFY (max 5 items)
    assert state.recent_searches == ["WIPRO", "SBIN", "TATAMOTORS", "HDFCBANK", "INFY"]


def test_add_recent_search_deduplicates():
    state = AppState()
    state.add_recent_search("RELIANCE")
    state.add_recent_search("TCS")
    state.add_recent_search("RELIANCE")
    assert state.recent_searches == ["RELIANCE", "TCS"]


def test_load_and_save_state_json_roundtrip(tmp_path):
    state_file = tmp_path / "test_state.json"
    state = AppState(
        last_ticker="SBIN.NS",
        risk=10000.0,
        positions_raw="SBIN:750:100",
        recent_searches=["SBIN", "TCS", "RELIANCE"],
    )
    save_state(state, state_file)

    loaded = load_state(state_file)
    assert loaded.last_ticker == "SBIN.NS"
    assert loaded.risk == 10000.0
    assert loaded.positions_raw == "SBIN:750:100"
    assert loaded.recent_searches == ["SBIN", "TCS", "RELIANCE"]
