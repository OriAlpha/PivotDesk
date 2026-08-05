"""Tests for state.py local JSON persistence and recent searches."""

from __future__ import annotations

from state import STATE_FILE_ENV, AppState, load_state, save_state


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


# ---------------------------------------------------------------- opt-in persistence


def test_persistence_is_off_unless_a_state_file_is_configured(monkeypatch, tmp_path):
    """The deployed default.

    One Streamlit process serves every visitor, so a state file written on
    their behalf is a shared one — the next visitor would load the previous
    one's ticker, cost basis and position size. With nothing configured
    nothing is written and nothing is read back.
    """
    monkeypatch.delenv(STATE_FILE_ENV, raising=False)
    monkeypatch.chdir(tmp_path)

    save_state(AppState(last_ticker="SBIN.NS", positions_raw="SBIN:750:100"))

    assert list(tmp_path.iterdir()) == []
    assert load_state() == AppState()


def test_a_configured_state_file_round_trips(monkeypatch, tmp_path):
    """What a single-user local run opts into."""
    state_file = tmp_path / "configured.json"
    monkeypatch.setenv(STATE_FILE_ENV, str(state_file))

    save_state(AppState(last_ticker="TCS.NS", risk=7.5, positions_raw="TCS:3200:15"))

    assert state_file.exists()
    loaded = load_state()
    assert loaded.last_ticker == "TCS.NS"
    assert loaded.risk == 7.5
    assert loaded.positions_raw == "TCS:3200:15"


def test_an_explicit_path_overrides_the_environment(monkeypatch, tmp_path):
    """Callers passing a path get that path, configured or not."""
    monkeypatch.delenv(STATE_FILE_ENV, raising=False)
    explicit = tmp_path / "explicit.json"

    save_state(AppState(last_ticker="INFY.NS"), explicit)

    assert load_state(explicit).last_ticker == "INFY.NS"
