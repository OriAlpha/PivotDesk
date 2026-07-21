"""Tests for the URL-encoded position book."""

from __future__ import annotations

import pytest

from positions import (
    Position,
    format_positions,
    parse_positions,
    set_position,
    symbol_key,
)


# ---------------------------------------------------------------- symbol keys


@pytest.mark.parametrize(
    "ticker,expected",
    [
        ("RELIANCE.NS", "RELIANCE"),
        ("RELIANCE", "RELIANCE"),
        ("reliance.ns", "RELIANCE"),
        ("  TCS.NS  ", "TCS"),
        ("TATASTEEL.BO", "TATASTEEL"),
        ("", ""),
    ],
)
def test_symbol_key_normalises(ticker, expected):
    assert symbol_key(ticker) == expected


def test_a_position_survives_either_spelling():
    """The quick list stores RELIANCE, the fetcher wants RELIANCE.NS — both
    must reach the same book entry."""
    book = set_position({}, "RELIANCE.NS", 1200.0, 50.0)
    assert book[symbol_key("RELIANCE")] == Position(1200.0, 50.0)


# ---------------------------------------------------------------- round trip


def test_round_trip():
    book = {"RELIANCE": Position(1200.0, 50.0), "TCS": Position(3100.5, 10.0)}
    assert parse_positions(format_positions(book)) == book


def test_encodes_compactly():
    assert format_positions({"RELIANCE": Position(1200.0, 50.0)}) == "RELIANCE:1200:50"
    assert format_positions({"TCS": Position(3100.5, 10.0)}) == "TCS:3100.5:10"


def test_large_values_do_not_go_scientific():
    """%g would render 1234567 as 1.23457e+06 and quietly round the quantity."""
    encoded = format_positions({"X": Position(150000.0, 1234567.0)})
    assert encoded == "X:150000:1234567"
    assert parse_positions(encoded)["X"].qty == 1234567.0


def test_entry_without_quantity_round_trips():
    book = {"INFY": Position(1500.0, None)}
    assert format_positions(book) == "INFY:1500"
    assert parse_positions("INFY:1500") == book


def test_quantity_without_entry_round_trips():
    assert parse_positions("INFY::20") == {"INFY": Position(None, 20.0)}
    assert format_positions({"INFY": Position(None, 20.0)}) == "INFY::20"


# ---------------------------------------------------------------- robustness


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        ",,,",
        ":::",
        "RELIANCE",  # no fields
        "RELIANCE:abc:def",  # unparseable numbers
        "RELIANCE:-5:-2",  # non-positive
        "RELIANCE:0:0",
        ":1200:50",  # no symbol
    ],
)
def test_junk_yields_an_empty_book_without_raising(raw):
    """The string is editable in the address bar, so a typo must cost one
    position at most — never the page."""
    assert parse_positions(raw) == {}


def test_one_bad_entry_does_not_lose_the_others():
    book = parse_positions("RELIANCE:1200:50,GARBAGE:x:y,TCS:3100:10")
    assert set(book) == {"RELIANCE", "TCS"}


def test_extra_fields_are_ignored():
    assert parse_positions("RELIANCE:1200:50:junk:more") == {
        "RELIANCE": Position(1200.0, 50.0)
    }


# ---------------------------------------------------------------- updating


def test_set_position_adds_and_replaces():
    book = set_position({}, "RELIANCE", 1200.0, 50.0)
    book = set_position(book, "RELIANCE", 1250.0, 60.0)
    assert book == {"RELIANCE": Position(1250.0, 60.0)}


def test_set_position_does_not_mutate_the_original():
    original = {"TCS": Position(3100.0, 10.0)}
    set_position(original, "RELIANCE", 1200.0, 50.0)
    assert original == {"TCS": Position(3100.0, 10.0)}


def test_clearing_both_fields_removes_the_symbol():
    book = {"RELIANCE": Position(1200.0, 50.0), "TCS": Position(3100.0, 10.0)}
    assert set_position(book, "RELIANCE", None, None) == {"TCS": Position(3100.0, 10.0)}


def test_clearing_keeps_the_url_free_of_dead_entries():
    book = set_position({"RELIANCE": Position(1200.0, 50.0)}, "RELIANCE", None, None)
    assert format_positions(book) == ""


def test_other_symbols_are_untouched_by_an_edit():
    book = {"RELIANCE": Position(1200.0, 50.0), "TCS": Position(3100.0, 10.0)}
    updated = set_position(book, "TCS", 3200.0, 12.0)
    assert updated["RELIANCE"] == Position(1200.0, 50.0)
