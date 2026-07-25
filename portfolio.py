"""PivotDesk — the portfolio watchlist rollup.

One row per held-or-favorite symbol: last price, day change, technical-bias
score, and P&L when a position is set. Reuses the same resilient fetch, market
clock, and scoring path as the single-stock view so the two never disagree.

A symbol that fails to load (typo, delisted, transient Yahoo outage) yields a
row with ``ok=False`` and is rendered dimmed — one bad ticker never blanks the
table. Fetching is therefore the caller's responsibility to gate (the table is
behind a toggle in ``app.py`` so a collapsed view does zero extra requests).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from config import IST
from data import (
    completed_sessions,
    fetch_daily_resilient,
    fetch_live_price,
    is_holiday,
    market_status,
)
from indicators import compute_indicators
from rendering import resolve_price, technical_score


@dataclass(frozen=True)
class Row:
    """One watchlist row. ``ok=False`` marks a symbol that would not load."""

    symbol: str
    ok: bool
    price: float | None = None
    day_pct: float | None = None
    score: int | None = None  # 0–6, same signals as the bias card
    pnl_pct: float | None = None  # only when a position entry is set
    stale: bool = False  # price is a fallback close, not a live quote


def _row_for(
    symbol: str,
    ticker: str,
    book: dict,
    now: dt.datetime,
) -> Row:
    """Build one row, loading and scoring a single symbol. Never raises — a
    fetch failure becomes ``ok=False`` so the rest of the table still renders."""
    try:
        is_open, _ = market_status(now)
        daily, daily_stale = fetch_daily_resilient(ticker)

        daily_last = (
            daily.index[-1].astimezone(IST).date()
            if daily.index.tz
            else daily.index[-1].date()
        )
        if not daily_stale and is_holiday(daily_last, now):
            is_open = False

        comp = completed_sessions(daily, now)
        if len(comp) < 60:
            return Row(symbol=symbol, ok=False)

        ind = compute_indicators(comp, now.date())
        prev_close = ind.prev_close

        live = fetch_live_price(ticker) if is_open else None
        pv = resolve_price(
            live,
            is_open,
            prev_close=prev_close,
            prev_low=ind.prev_low,
            prev_high=ind.prev_high,
            prior_close=float(comp["Close"].iloc[-2]) if len(comp) >= 2 else None,
        )

        score, _, _ = technical_score(
            pv.price,
            ind.sma20,
            ind.sma50,
            ind.sma200,
            ind.st_up,
            ind.macd_bull,
            ind.piv["PP"],
        )
        day_pct = (
            None
            if pv.stale
            else (pv.price / pv.baseline - 1) * 100
            if pv.baseline
            else 0.0
        )

        pos = book.get(symbol)
        pnl_pct = (pv.price / pos.entry - 1) * 100 if pos and pos.entry else None

        return Row(
            symbol=symbol,
            ok=True,
            price=pv.price,
            day_pct=day_pct,
            score=score,
            pnl_pct=pnl_pct,
            stale=pv.stale,
        )
    except Exception:
        # A typo, a delisted name, a transient Yahoo outage — dim the row, do
        # not let it take the rest of the watchlist with it.
        return Row(symbol=symbol, ok=False)


def snapshot(symbols: list[str], book: dict, now: dt.datetime) -> list[Row]:
    """One row per symbol, in the order given. Symbols are expected already
    upper-cased and de-suffixed (matching the position-book keys)."""
    rows: list[Row] = []
    for symbol in symbols:
        ticker = symbol + ".NS" if "." not in symbol else symbol
        rows.append(_row_for(symbol, ticker, book, now))
    return rows
