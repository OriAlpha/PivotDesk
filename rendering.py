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
from html import escape as html_escape
from urllib.parse import quote

import streamlit as st

from chart import render_chart_html
from config import IST, MARKET_CLOSE
from data import (
    completed_sessions,
    fetch_daily_resilient,
    fetch_live_price,
    is_holiday,
    last_session_date,
    market_status,
)
from indicators import compute_indicators
from templates import CHART_PAGE, HTML, HTML_ERROR, js_literal
from verdict import (
    OVERBOUGHT_RSI,
    action_card,
    entry_verdict,
    fmt,
    move_phrase_text,
    plain_summary,
)

__all__ = [
    "HTML",
    "HTML_ERROR",
    "OVERBOUGHT_RSI",
    "PriceView",
    "action_card",
    "entry_verdict",
    "expected_range_label",
    "fmt",
    "move_phrase_text",
    "plain_summary",
    "position_card",
    "render",
    "render_chart_panel",
    "render_error",
    "resolve_price",
    "signal_chips",
    "technical_score",
]


# Where render() leaves the chart markup for render_chart_panel() to pick up.
CHART_STATE_KEY = "pivotdesk_chart_html"


# ---------------------------------------------------------------- helpers


def reload_url(ticker: str, entry: float, positions_str: str = "") -> str:
    """The self-link that forces a refetch.

    Both the ticker and the position book arrive straight from the query
    string, so each value is percent-encoded and the finished URL escaped for
    the ``href`` it lands in — otherwise a quote in either one closes the
    attribute early and whatever follows becomes markup.
    """
    url = f"?ticker={quote(ticker, safe='')}&entry={entry}"
    if positions_str:
        # ':' and ',' separate the book's own fields; they are legal here and
        # leaving them be keeps the URL readable.
        url += f"&positions={quote(positions_str, safe=':,')}"
    return html_escape(url + "&reload=1", quote=True)


def expected_range_label(now: dt.datetime, is_open: bool, holiday: bool = False) -> str:
    """Name the session the ATR range applies to.

    Once the bell has rung the range describes the *next* open, not the one
    that just finished. Future holidays are unknowable — only weekends are
    skipped — so the worst case is naming a day the exchange turns out to be
    shut, never a day already in the past.
    """
    session = now.date()
    if holiday or (not is_open and now.time() > MARKET_CLOSE):
        session += dt.timedelta(days=1)
    while session.weekday() >= 5:
        session += dt.timedelta(days=1)

    if session == now.date():
        return "Exp Today"
    if session == now.date() + dt.timedelta(days=1):
        return "Exp Tomorrow"
    return f"Exp {session:%A}"


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


def render_chart_panel() -> None:
    """Draw the chart frame from the markup ``render()`` last produced.

    Called from outside the refreshing fragment, so a fragment rerun leaves
    this frame alone — the chart keeps its zoom, its crosshair and its
    timeframe selection instead of being rebuilt every minute. The candles
    only change when a session completes, so redrawing on full script runs is
    as fresh as the data ever gets.
    """
    chart_html = st.session_state.get(CHART_STATE_KEY)
    if not chart_html:
        return
    html = CHART_PAGE.safe_substitute(chart_html=chart_html)
    st.iframe(html, height=520)


def render_error(
    ticker: str,
    error_msg: str,
    entry: float = 0.0,
    positions_str: str = "",
) -> None:
    """Render a minimal error page inside an iframe."""
    html = HTML_ERROR.safe_substitute(
        error_msg=html_escape(error_msg),
        reload_url=reload_url(ticker, entry, positions_str),
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
    holiday = not daily_stale and is_holiday(last_session_date(daily), now)
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
    chg_pct = 0.0
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

    # ---- action verdict (headline buy/wait call, synthesised from the signals)
    verdict = entry_verdict(
        price, score, ind.st_up, ind.st_stop, ind.rsi_val, ind.atr_val, piv
    )

    # ---- plain-English summary sentence (the Action card's headline)
    summary_sentence = plain_summary(
        ticker.replace(".NS", ""), score, ind.st_up, ind.rsi_val, verdict
    )

    # ---- 6-segment score gauge
    gauge_dots = []
    for i in range(1, 7):
        active_cls = f"active {bias_cls}" if i <= score else ""
        gauge_dots.append(f'<span class="dot-seg {active_cls}"></span>')
    score_gauge_html = f'<div class="score-gauge">{"".join(gauge_dots)}</div>'

    # ---- Risk-to-Reward (R:R) Ratio
    downside = price - ind.st_stop if (ind.st_stop and price > ind.st_stop) else 0.0
    if piv.get("R1") and piv["R1"] > price:
        target = piv["R1"]
        target_lbl = "R1"
    elif piv.get("R2") and piv["R2"] > price:
        target = piv["R2"]
        target_lbl = "R2"
    else:
        target = price * 1.05
        target_lbl = "+5%"
    upside = target - price if target > price else 0.0
    if downside > 0 and upside > 0:
        rr_val = upside / downside
        caution_tag = (
            ' <span style="color:var(--pp);font-weight:700">⚠️ Target too close</span>'
            if rr_val < 1.0
            else ""
        )
        total_dist = target - ind.st_stop
        current_dist = price - ind.st_stop
        prog_pct = (
            max(0.0, min(100.0, current_dist / total_dist * 100))
            if total_dist > 0
            else 0.0
        )
        prog_str = f" · Progress <b>{prog_pct:.0f}%</b>"
        rr_str = f"Target <b>{target_lbl} ₹{fmt(target)}</b> (R:R <b>1:{rr_val:.1f}</b>{caution_tag}){prog_str}"
    else:
        rr_str = ""

    ph_tag = (
        ' <span class="sc-badge up" style="font-size:9px;padding:1px 5px;margin-left:4px;">🚀 Broken</span>'
        if price > ph
        else ""
    )
    pl_tag = (
        ' <span class="sc-badge dn" style="font-size:9px;padding:1px 5px;margin-left:4px;">🔻 Broken</span>'
        if price < pl
        else ""
    )

    rsi_bar = (
        f'<div style="position:relative;width:100%;height:4px;background:rgba(255,255,255,.1);border-radius:99px;margin-top:6px;overflow:hidden;">'
        f'<div style="position:absolute;left:{min(98.0, max(2.0, ind.rsi_val)):.1f}%;top:50%;transform:translate(-50%,-50%);width:7px;height:7px;'
        f'background:var(--{"pp" if 30 < ind.rsi_val < 70 else ("sup" if ind.rsi_val >= 70 else "res")});border-radius:50%;box-shadow:0 0 6px currentColor;"></div></div>'
    )

    # ---- Multi-Timeframe Trend Alignment (Daily + Weekly)
    daily_up = price > ind.sma50
    weekly_up = price > ind.weekly_pp if ind.weekly_pp else False
    if daily_up and weekly_up:
        mtf_badge = '<div style="margin-top:8px;"><span class="sc-badge up">Daily 🟢 + Weekly 🟢 Trend Aligned</span></div>'
    elif not daily_up and not weekly_up:
        mtf_badge = '<div style="margin-top:8px;"><span class="sc-badge dn">Daily 🔴 + Weekly 🔴 Downtrend Aligned</span></div>'
    else:
        mtf_badge = '<div style="margin-top:8px;"><span class="sc-badge warn">Daily & Weekly Mixed Alignment</span></div>'

    vol_spike_html = (
        f'<div style="margin-top:8px;"><span class="sc-badge up warn-flash" style="font-size:10px;padding:3px 9px;">🔥 High Volume Spike ({ind.vol_ratio:.1f}× 30D avg)</span></div>'
        if ind.vol_ratio >= 1.5
        else ""
    )

    if rng_pct >= 95:
        rng_badge = ' <span class="sc-badge up">🚀 52W High</span>'
    elif rng_pct <= 10:
        rng_badge = ' <span class="sc-badge dn">🛡️ 52W Support</span>'
    else:
        rng_badge = ""

    macd_sub = "momentum building" if ind.macd_building else "momentum cooling"
    vol_cls = "dn" if ind.vol_ratio < 0.8 else ("up" if ind.vol_ratio > 1.2 else "warn")
    vol_sub = (
        "below average"
        if ind.vol_ratio < 0.8
        else ("above average" if ind.vol_ratio > 1.2 else "in line")
    )

    exp_lo = price - ind.atr_val if price else 0.0
    exp_hi = price + ind.atr_val if price else 0.0
    atr_pct_val = ind.atr_val / price * 100 if price else 0.0
    exp_label = expected_range_label(now, is_open, holiday)
    exp_range_html = (
        f'<div class="exprange mono">'
        f'<span class="xr-lab">{exp_label}</span>'
        f'<span class="xr-val">₹{fmt(exp_lo)}<em>–</em>₹{fmt(exp_hi)}</span>'
        f'<span class="xr-pct">±{atr_pct_val:.1f}%</span>'
        f"</div>"
    )

    # ---- final HTML assembly
    symbol = ticker.replace(".NS", "")
    html = HTML.safe_substitute(
        name=html_escape(symbol + " · NSE"),
        symbol_js=js_literal(symbol),
        mkt_label=f"{mkt_label} · STALE" if pv.stale else mkt_label,
        reload_cls=reload_cls,
        reload_url=reload_url(ticker, entry_val, positions_str),
        dot_color=(
            "var(--pp)" if pv.stale else ("var(--sup)" if is_open else "var(--dim)")
        ),
        dot_anim="animation:pulse 2s infinite" if is_open and not pv.stale else "",
        ph=fmt(ph),
        pl=fmt(pl),
        pc=fmt(pc),
        ph_tag=ph_tag,
        pl_tag=pl_tag,
        price=fmt(price),
        px_cls="stale" if pv.stale else "",
        chg_html=chg_html,
        exp_range_html=exp_range_html,
        vol_spike_html=vol_spike_html,
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
        rng_badge=rng_badge,
        bias_label=bias_label,
        bias_cls=bias_cls,
        score_gauge=score_gauge_html,
        mtf_badge=mtf_badge,
        bias_n=str(score),
        bias_caution=bias_caution,
        bias_chips=bias_chips,
        action_card=action_card(
            verdict,
            summary_sentence,
            stale=pv.stale,
            rr_str=rr_str,
        ),
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
        rsi_s=f'<span class="sc-badge {rsi_cls}">{rsi_s}</span>{rsi_bar}',
        macd_v="Bullish" if ind.macd_bull else "Bearish",
        macd_cls="up" if ind.macd_bull else "dn",
        macd_s=f'<span class="sc-badge {"up" if ind.macd_bull else "dn"}">{macd_sub}</span>',
        st_v="Buy" if ind.st_up else "Sell",
        st_cls="up" if ind.st_up else "dn",
        st_stop=fmt(ind.st_stop),
        atr_v=fmt(ind.atr_val),
        atr_pct=f"{ind.atr_val / price * 100:.1f}" if price else "—",
        vol_v=f"{ind.vol_ratio:.1f}",
        vol_cls=(
            "dn" if ind.vol_ratio < 0.8 else ("up" if ind.vol_ratio > 1.2 else "warn")
        ),
        vol_s=f'<span class="sc-badge {vol_cls}">{vol_sub}</span>',
    )
    st.iframe(html, height=1690)

    # The chart is drawn in its own frame outside the refreshing fragment, so
    # it survives the 60s beat instead of being torn down and rebuilt. Handing
    # the markup over here keeps it on the single pass that already has the
    # indicators and the verdict in hand.
    st.session_state[CHART_STATE_KEY] = render_chart_html(
        daily,
        piv,
        st_stop=ind.st_stop,
        ticker=ticker,
        target_price=target,
        buy_lo=verdict.zone_lo,
        buy_hi=verdict.zone_hi,
    )
