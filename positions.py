"""PivotDesk — the position book, encoded in the URL query string.

The dashboard already persists ticker and favourites in the URL, so positions
go the same way: one bookmark restores the whole book, and switching symbols
loads that symbol's cost basis instead of forgetting it.

Wire format is ``SYM:entry:qty`` comma-separated, e.g.
``RELIANCE:1200:50,TCS:3100.5:10``. Either field may be empty.
"""

from __future__ import annotations

from dataclasses import dataclass

EXCHANGE_SUFFIXES = (".NS", ".BO")


@dataclass(frozen=True)
class Position:
    """An average entry price and an optional share count."""

    entry: float | None = None
    qty: float | None = None

    def __bool__(self) -> bool:
        return self.entry is not None or self.qty is not None


def symbol_key(ticker: str) -> str:
    """Canonical book key: upper-cased, exchange suffix stripped.

    Keys match the favourites list (``RELIANCE``), not the Yahoo symbol
    (``RELIANCE.NS``), so a position survives either spelling.
    """
    symbol = ticker.strip().upper()
    for suffix in EXCHANGE_SUFFIXES:
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)]
    return symbol


def _number(text: str) -> float | None:
    """Positive float, or None. Never raises."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def _plain(value: float) -> str:
    """Compact decimal without scientific notation, which ``%g`` would use
    above 1e6 and quietly round a large quantity."""
    return f"{value:.4f}".rstrip("0").rstrip(".")


def parse_positions(raw: str) -> dict[str, Position]:
    """Decode the query-string form. Malformed entries are skipped.

    This string is user-editable in the address bar, so nothing here may
    raise — a typo should cost one position, not the whole page.
    """
    book: dict[str, Position] = {}
    for chunk in raw.split(","):
        if not chunk.strip():
            continue
        parts = chunk.split(":")
        symbol = symbol_key(parts[0])
        if not symbol:
            continue
        position = Position(
            entry=_number(parts[1]) if len(parts) > 1 else None,
            qty=_number(parts[2]) if len(parts) > 2 else None,
        )
        if position:
            book[symbol] = position
    return book


def format_positions(book: dict[str, Position]) -> str:
    """Encode for the query string, dropping symbols with nothing set."""
    chunks = []
    for symbol, position in book.items():
        if not position:
            continue
        entry = _plain(position.entry) if position.entry is not None else ""
        qty = _plain(position.qty) if position.qty is not None else ""
        chunks.append(f"{symbol}:{entry}:{qty}".rstrip(":"))
    return ",".join(chunks)


def set_position(
    book: dict[str, Position],
    ticker: str,
    entry: float | None,
    qty: float | None,
) -> dict[str, Position]:
    """Return a copy of *book* with *ticker* updated.

    Clearing both fields removes the symbol rather than storing an empty
    record, so the URL does not accumulate dead entries.
    """
    updated = dict(book)
    symbol = symbol_key(ticker)
    position = Position(entry, qty)
    if position:
        updated[symbol] = position
    else:
        updated.pop(symbol, None)
    return updated
