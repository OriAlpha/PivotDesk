"""PivotDesk — HTML rendering, technical scoring, and position tracking.

The top-level ``render()`` / ``render_error()`` entry points that produce the
dashboard iframe, plus the price-resolution state machine, the technical-bias
scoring, and the position-card builder.

The buy/wait action engine lives in :mod:`verdict` and the page templates in
:mod:`templates`; this module orchestrates them. The verdict names are
re-exported below so existing ``from rendering import ...`` callers (notably
``tests/test_rendering.py``) keep working.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import streamlit as st

from backtest import signal_confidence
from chart import render_chart_html
from config import IST
from data import (
    completed_sessions,
    fetch_daily_resilient,
    fetch_live_price,
    is_holiday,
    market_status,
)
from indicators import compute_indicators
from templates import HTML, HTML_ERROR
from verdict import (
    OVERBOUGHT_RSI,
    action_card,
    entry_verdict,
    fmt,
    move_context,
    plain_summary,
)

__all__ = [
    "HTML",
    "HTML_ERROR",
    "OVERBOUGHT_RSI",
    "PriceView",
    "action_card",
    "compose_read",
    "entry_verdict",
    "fmt",
    "move_context",
    "plain_summary",
    "position_card",
    "render",
    "render_error",
    "resolve_price",
    "signal_chips",
    "technical_score",
]


# ---------------------------------------------------------------- helpers


def compose_read() -> str:
    """Data attribution footer."""
    return "Data: Yahoo Finance"


# ---------------------------------------------------------------- price view


@dataclass(frozen=True)
class PriceView:
    """What to display as *the* price, and what to measure its move against.

    ``prev_close`` anchors the pivots for the **next** session, so it is not
    always the right baseline for the day's change — see ``resolve_price``.
    """

    price: float
    baseline: float  # close the change is measured against
    day_low: float | None
    day_high: float | None
    stale: bool  # price is a fallback, not a live quote


def resolve_price(
    live: tuple[float, float, float] | None,
    is_open: bool,
    prev_close: float,
    prev_low: float,
    prev_high: float,
    prior_close: float | None,
) -> PriceView:
    """Pick the displayed price and the close its change is measured against.

    ``prev_*`` describe the last *completed* session — the one the pivots are
    built from. ``prior_close`` is the close before that.

    - Live quote available: price is live, measured against the last close.
    - Market open but the quote failed: the last close is all we have, and it
      is **not** the current price. Flag it rather than showing a fake +0.00.
    - Market closed: the last completed session *is* today (or Friday), so the
      move is measured against the session before it.
    """
    if live is not None:
        price, day_low, day_high = live
        return PriceView(price, prev_close, day_low, day_high, stale=False)
    if is_open:
        return PriceView(prev_close, prev_close, None, None, stale=True)
    baseline = prior_close if prior_close is not None else prev_close
    return PriceView(prev_close, baseline, prev_low, prev_high, stale=False)


# ---------------------------------------------------------------- scoring


# One label per score, calibrated against 19,443 ticker-days (39 NSE symbols,
# 2y each). Bucketing 5-6 as "Strong bullish" and 0-1 as "Strong bearish" put a
# "Strong" verdict on 55.7% of all days — a headline that fires on the majority
# of observations does not discriminate. Splitting them puts "Strong" on 21.1%,
# with no bucket above 19% of days:
#
#     6/6  8.5%   5/6 16.0%   4/6 15.3%   3/6 15.0%
#     2/6 14.0%   1/6 18.6%   0/6 12.5%
BIAS_LABELS: dict[int, tuple[str, str]] = {
    6: ("Strong bullish", "up"),
    5: ("Bullish", "up"),
    4: ("Leaning bullish", "up"),
    3: ("Neutral", "warn"),
    2: ("Leaning bearish", "dn"),
    1: ("Bearish", "dn"),
    0: ("Strong bearish", "dn"),
}

# Short labels for the per-signal chips, in scoring order.
SIGNAL_LABELS = ("20D", "50D", "200D", "ST", "MACD", "PP")


def signal_chips(flags: list[bool]) -> str:
    """Per-signal pass/fail chips.

    Replaces a ``title`` tooltip, which needs hover and so was invisible on
    every touch device — taking the whole point of a transparent score with
    it. Shape (● / ○) carries the state as well as colour, so the row does not
    rely on red-green discrimination.
    """
    return "".join(
        f'<span class="{"on" if ok else "off"}">{"●" if ok else "○"} {label}</span>'
        for label, ok in zip(SIGNAL_LABELS, flags)
    )


def technical_score(
    price: float,
    sma20: float,
    sma50: float,
    sma200: float,
    st_up: bool,
    macd_bull: bool,
    pp: float,
) -> tuple[int, str, str]:
    """Count of 6 transparent bullish signals → (score, label, css_class)."""
    score = int(
        sum(
            [price > sma20, price > sma50, price > sma200, st_up, macd_bull, price > pp]
        )
    )
    label, css = BIAS_LABELS[score]
    return score, label, css


def position_card(
    entry: float,
    price: float,
    st_up: bool,
    st_stop: float,
    stale: bool = False,
    qty: float = 0.0,
    risk_budget: float = 0.0,
) -> str:
    """Build the HTML for the position-tracking card."""
    if not entry or entry <= 0:
        return (
            '<div class="vcard"><div class="k">Your position</div>'
            '<div class="big" style="color:var(--dim)">—</div>'
            '<div class="sub2">enter your buy price above to track P&L '
            "and your trend stop</div></div>"
        )
    pnl = (price / entry - 1) * 100
    pnl_color = "var(--sup)" if pnl >= 0 else "var(--res)"
    pnl_val = price - entry
    # With a quantity the rupee figure is what you actually act on, so it leads;
    # per-share is only meaningful when the size is unknown.
    if qty and qty > 0:
        total = pnl_val * qty
        pnl_val_str = f"+₹{total:,.0f}" if total >= 0 else f"-₹{abs(total):,.0f}"
    else:
        pnl_val_str = (
            f"+₹{pnl_val:,.2f}/sh" if pnl_val >= 0 else f"-₹{abs(pnl_val):,.2f}/sh"
        )

    if st_up:
        pct_to_stop = (price - st_stop) / st_stop * 100 if st_stop else 0.0
        if pct_to_stop <= 1.5:
            stat = f"⚠️ APPROACHING STOP · breaks below ₹{fmt(st_stop)} ({pct_to_stop:.1f}%)"
            stat_cls = "warn-flash"
        else:
            stat = f"Trend intact · breaks below ₹{fmt(st_stop)}"
            stat_cls = "up"
    else:
        stat = f"Trend broken · recovery above ₹{fmt(st_stop)}"
        stat_cls = "dn"

    # Position sizing from the stop: a fixed rupee risk, divided by the
    # per-share downside to the trend stop. Only meaningful with an uptrend
    # (stop below entry) — in a downtrend the stop sits above the entry, so
    # there is no downside distance to size off.
    sizing_html = ""
    if risk_budget and risk_budget > 0 and st_up and entry > st_stop:
        risk_per_share = entry - st_stop
        trade_val = (entry * qty) if (qty and qty > 0) else (entry * 100.0)
        rupee_risk = (risk_budget / 100.0) * trade_val
        shares = rupee_risk / risk_per_share
        cost = shares * entry
        sizing_html = (
            f'<div class="sub2" style="font-size:11px;color:var(--muted)">'
            f"Size: {risk_budget:.1f}% risk (₹{fmt(rupee_risk)}) &rarr; {shares:,.0f} sh "
            f"(₹{fmt(cost)} cost)</div>"
        )

    now_label = (
        f"last close ₹{fmt(price)} · not live" if stale else f"now ₹{fmt(price)}"
    )
    size_label = f" · {qty:,.0f} sh" if qty and qty > 0 else ""
    return (
        f'<div class="vcard"><div class="k">Your position</div>'
        f'<div class="big mono" style="color:{pnl_color}">{pnl:+.1f}% '
        f'<span style="font-size:12.5px;font-weight:600;margin-left:4px">'
        f"({pnl_val_str})</span></div>"
        f'<div class="sub2 {stat_cls}">{stat}</div>'
        f'<div class="sub2" style="font-size:11px;color:var(--dim)">'
        f"entry ₹{fmt(entry)}{size_label} · {now_label}</div>"
        f"{sizing_html}</div>"
    )


# ---------------------------------------------------------------- render entry points


def render_error(
    ticker: str,
    error_msg: str,
    entry: float = 0.0,
    positions_str: str = "",
) -> None:
    """Render a minimal error page inside an iframe."""
    pos_qp = f"&positions={positions_str}" if positions_str else ""
    html = HTML_ERROR.safe_substitute(
        error_msg=error_msg,
        reload_url=f"?ticker={ticker}&entry={entry}{pos_qp}&reload=1",
    )
    st.iframe(html, height=350)


def render(
    ticker: str,
    entry: float = 0.0,
    now: dt.datetime | None = None,
    reload_cls: str = "",
    qty: float = 0.0,
    positions_str: str = "",
    risk_budget: float = 0.0,
    total_visits: int = 0,
    device_count: int = 1,
) -> None:
    """Build and display the full dashboard for *ticker*."""
    entry_val = float(entry) if entry is not None else 0.0
    qty_val = float(qty) if qty else 0.0
    risk_val = float(risk_budget) if risk_budget else 0.0
    now = now or dt.datetime.now(IST)
    is_open, mkt_label = market_status(now)

    daily, daily_stale = fetch_daily_resilient(ticker)

    # A weekday with no session row of its own is an NSE holiday: treat it as
    # closed so we neither chase a live quote nor pulse an "open" indicator.
    daily_last = (
        daily.index[-1].astimezone(IST).date()
        if daily.index.tz
        else daily.index[-1].date()
    )
    holiday = not daily_stale and is_holiday(daily_last, now)
    if holiday:
        is_open, mkt_label = False, "MARKET CLOSED · NSE HOLIDAY"

    comp = completed_sessions(daily, now)
    if len(comp) < 60:
        st.error("Not enough history for this symbol (need ≥60 sessions).")
        return

    # ---- indicators (cached — only recomputed when data or date changes)
    ind = compute_indicators(comp, now.date())

    ph, pl, pc = ind.prev_high, ind.prev_low, ind.prev_close
    piv = ind.piv

    # ---- live price (refreshes every 55 s independently of indicators)
    live = fetch_live_price(ticker) if is_open else None
    pv = resolve_price(
        live,
        is_open,
        prev_close=pc,
        prev_low=pl,
        prev_high=ph,
        prior_close=float(comp["Close"].iloc[-2]) if len(comp) >= 2 else None,
    )
    price = pv.price

    # ---- day range bar (meaningless without a session to range over)
    if pv.day_low is None or pv.day_high is None:
        day_range_html = ""
    else:
        day_span = pv.day_high - pv.day_low
        px_pct_day = (price - pv.day_low) / day_span * 100 if day_span > 0 else 50.0
        px_pct_day = max(2.0, min(98.0, px_pct_day))
        day_range_html = f"""
    <div class="day-range-box">
      <span class="lbl">L {fmt(pv.day_low)}</span>
      <div class="bar-bg">
        <div class="bar-dot" style="left: {px_pct_day:.1f}%"></div>
      </div>
      <span class="lbl">H {fmt(pv.day_high)}</span>
    </div>
    """

    # ---- change block (never fabricate a +0.00 for a price we could not fetch)
    move_ctx_html = ""
    if pv.stale:
        chg_html = (
            '<div class="chg stale">⚠ Live price unavailable · showing last close</div>'
        )
    else:
        chg = price - pv.baseline
        chg_pct = chg / pv.baseline * 100 if pv.baseline else 0.0
        chg_html = (
            f'<div class="chg mono" '
            f'style="color:{"var(--sup)" if chg >= 0 else "var(--res)"}">'
            f"{'▲' if chg >= 0 else '▼'} {chg:+,.2f} ({chg_pct:+.2f}%)</div>"
        )
        move_ctx_html = move_context(
            chg_pct, ind.atr_val / price * 100 if price else 0.0
        )

    # ---- moving-average classification (depends on live price)
    above = sum(price > m for m in (ind.sma20, ind.sma50, ind.sma200))
    ma_v = (
        "Above all"
        if above == 3
        else ("Below all" if above == 0 else f"Above {above}/3")
    )
    ma_s = f"₹{ind.sma20:,.0f} · ₹{ind.sma50:,.0f} · ₹{ind.sma200:,.0f}"
    ma_cls = "up" if above == 3 else ("dn" if above == 0 else "warn")

    # ---- RSI classification
    rsi_cls = "warn" if ind.rsi_val >= 70 else ("dn" if ind.rsi_val <= 30 else "up")
    rsi_s = (
        "overbought"
        if ind.rsi_val >= 70
        else ("oversold" if ind.rsi_val <= 30 else "neutral zone")
    )

    # ---- 52-week range position. The 52w bounds come from completed sessions,
    # so a live price can sit outside them; widen rather than clamp, so a new
    # high reads as 100% of range instead of an impossible 103%.
    hi52 = max(ind.hi52, price)
    lo52 = min(ind.lo52, price)
    rng_pct = (price - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else 50.0

    # ---- returns HTML
    rets: list[str] = []
    for lab, r in ind.returns:
        if r is not None:
            color = "var(--sup)" if r >= 0 else "var(--res)"
            rets.append(
                f'<span class="ret"><span>{lab}</span>'
                f'<b class="mono" style="color:{color}">{r:+.1f}%</b></span>'
            )

    # ---- spectrum tick positions
    span = piv["R2"] - piv["S2"]

    def pivot_pct(v: float) -> float:
        return max(2.0, min(98.0, 4 + 92 * (v - piv["S2"]) / span))

    # ---- technical bias
    score, bias_label, bias_cls = technical_score(
        price, ind.sma20, ind.sma50, ind.sma200, ind.st_up, ind.macd_bull, piv["PP"]
    )
    if ind.rsi_val >= 70:
        bias_caution = f" · RSI {ind.rsi_val:.0f} extended"
    elif ind.rsi_val <= 30:
        bias_caution = f" · RSI {ind.rsi_val:.0f} washed out"
    else:
        bias_caution = ""

    # ---- per-signal breakdown, in the same order technical_score counts them
    bias_chips = signal_chips(
        [
            price > ind.sma20,
            price > ind.sma50,
            price > ind.sma200,
            ind.st_up,
            ind.macd_bull,
            price > piv["PP"],
        ]
    )

    # ---- historical confidence: how the same (score, RSI band) setup has
    # played out before. Silent when too few samples to trust — never quotes a
    # win rate off three observations.
    conf = signal_confidence(comp, score, ind.rsi_val)
    if conf is None:
        bias_confidence = ""
    else:
        pct = conf.win_rate * 100
        cls = "up" if pct >= 55 else ("dn" if pct <= 45 else "warn")
        bias_confidence = (
            f'<div class="conf">Up 5d later: <b class="{cls}">{pct:.0f}%</b> '
            f"of {conf.n} similar days &middot; avg {conf.avg_return:+.1f}%</div>"
        )

    # ---- action verdict (headline buy/wait call, synthesised from the signals)
    verdict = entry_verdict(
        price, score, ind.st_up, ind.st_stop, ind.rsi_val, ind.atr_val, piv
    )

    # ---- plain-English summary sentence (the Action card's headline)
    summary_sentence = plain_summary(
        ticker.replace(".NS", ""), score, ind.st_up, ind.rsi_val, verdict
    )

    # ---- final HTML assembly
    pos_qp = f"&positions={positions_str}" if positions_str else ""
    html = HTML.safe_substitute(
        name=ticker.replace(".NS", "") + " · NSE",
        mkt_label=f"{mkt_label} · STALE" if pv.stale else mkt_label,
        reload_cls=reload_cls,
        reload_url=f"?ticker={ticker}&entry={entry_val}{pos_qp}&reload=1",
        dot_color=(
            "var(--pp)" if pv.stale else ("var(--sup)" if is_open else "var(--dim)")
        ),
        dot_anim="animation:pulse 2s infinite" if is_open and not pv.stale else "",
        ph=fmt(ph),
        pl=fmt(pl),
        pc=fmt(pc),
        price=fmt(price),
        px_cls="stale" if pv.stale else "",
        chg_html=chg_html,
        pp=fmt(piv["PP"]),
        r1=fmt(piv["R1"]),
        r2=fmt(piv["R2"]),
        s1=fmt(piv["S1"]),
        s2=fmt(piv["S2"]),
        s1_pct=f"{pivot_pct(piv['S1']):.1f}",
        r1_pct=f"{pivot_pct(piv['R1']):.1f}",
        px_pct=f"{pivot_pct(price):.1f}",
        wpp=fmt(ind.weekly_pp),
        returns_html="".join(rets),
        rng_pct=f"{rng_pct:.0f}",
        bias_label=bias_label,
        bias_cls=bias_cls,
        bias_n=str(score),
        bias_caution=bias_caution,
        bias_chips=bias_chips,
        bias_confidence=bias_confidence,
        action_card=action_card(verdict, summary_sentence, stale=pv.stale),
        move_ctx=move_ctx_html,
        day_range_html=day_range_html,
        data_banner=(
            '<div class="databanner">⚠ Yahoo data unavailable · showing the last '
            "successful fetch, levels may be a session behind</div>"
            if daily_stale
            else ""
        ),
        pos_card=position_card(
            entry_val,
            price,
            ind.st_up,
            ind.st_stop,
            stale=pv.stale,
            qty=qty_val,
            risk_budget=risk_val,
        ),
        ma_v=ma_v,
        ma_cls=ma_cls,
        ma_s=ma_s,
        rsi_v=f"{ind.rsi_val:.0f}",
        rsi_cls=rsi_cls,
        rsi_s=rsi_s,
        macd_v="Bullish" if ind.macd_bull else "Bearish",
        macd_cls="up" if ind.macd_bull else "dn",
        macd_s="momentum building" if ind.macd_building else "momentum cooling",
        st_v="Buy" if ind.st_up else "Sell",
        st_cls="up" if ind.st_up else "dn",
        st_stop=fmt(ind.st_stop),
        atr_v=fmt(ind.atr_val),
        atr_pct=f"{ind.atr_val / price * 100:.1f}" if price else "—",
        vol_v=f"{ind.vol_ratio:.1f}",
        vol_cls=(
            "dn" if ind.vol_ratio < 0.8 else ("up" if ind.vol_ratio > 1.2 else "warn")
        ),
        vol_s=(
            "below average"
            if ind.vol_ratio < 0.8
            else ("above average" if ind.vol_ratio > 1.2 else "in line")
        ),
        chart_html=render_chart_html(daily, piv, st_stop=ind.st_stop, ticker=ticker),
        read=compose_read(),
        visit_count=f"{total_visits:,}",
        device_count=str(device_count),
    )
    st.iframe(html, height=1550)
