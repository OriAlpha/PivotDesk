"""PivotDesk — HTML rendering, technical scoring, and position tracking.

Contains the HTML/CSS templates, the technical-bias scoring logic,
position-card builder, and the top-level ``render()`` / ``render_error()``
entry points that produce the dashboard iframe.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from string import Template

import streamlit as st

from config import IST
from data import (
    completed_sessions,
    fetch_daily_resilient,
    fetch_live_price,
    is_holiday,
    market_status,
)
from indicators import compute_indicators

# ---------------------------------------------------------------- helpers


def fmt(x: float) -> str:
    """Format a float as ₹-style with commas and 2 decimals."""
    return f"{x:,.2f}"


def compose_read() -> str:
    """Data attribution footer."""
    return "Data: Yahoo Finance &middot; levels roll each NSE session"


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

# Pairwise agreement measured on the same sample. The signals are not six
# independent votes: price-vs-SMA20, price-vs-SMA50, Supertrend and MACD agree
# with each other 76-80% of the time, against a ~50% baseline for independent
# signals. Price-vs-pivot is the most orthogonal (52-62%) because it re-anchors
# daily. Surfaced in the tooltip so the score is not read as 6 separate reads.
SIGNAL_CAVEAT = (
    "These are not 6 independent signals: the moving averages, Supertrend and "
    "MACD agree 76-80% of the time (~50% would be independent), so a 6/6 or 0/6 "
    "is closer to 3 confirming reads than 6. Price vs pivot is the most "
    "independent of the set."
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
        sum([price > sma20, price > sma50, price > sma200, st_up, macd_bull, price > pp])
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
        pnl_val_str = (
            f"+₹{total:,.0f}" if total >= 0 else f"-₹{abs(total):,.0f}"
        )
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
        f"entry ₹{fmt(entry)}{size_label} · {now_label}</div></div>"
    )


# ---------------------------------------------------------------- html templates

HTML = Template(
    r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>$name — PivotDesk</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0A0E17;--panel:rgba(20,29,48,.72);--line:#1E2C48;--text:#EDF2FB;--muted:#7E8DA8;
--dim:#55637E;--pp:#FFC53D;--res:#FF6B6B;--sup:#2EE6C8;--price:#6FA4FF}
*{box-sizing:border-box;margin:0;padding:0}
body{background:radial-gradient(900px 420px at 15% -8%,rgba(46,230,200,.06),transparent 60%),
radial-gradient(900px 420px at 85% -8%,rgba(255,107,107,.06),transparent 60%),var(--bg);
color:var(--text);font-family:'Archivo',sans-serif}
.mono{font-family:'IBM Plex Mono',monospace}
.wrap{max-width:940px;margin:0 auto;padding:10px 16px 28px}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:26px}
.brand{font-weight:800;font-size:17px}.brand em{font-style:normal;color:var(--pp)}
.mkt{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12.5px}
.reload-lnk{color:var(--muted);text-decoration:none;font-size:10px;font-weight:800;
text-transform:uppercase;letter-spacing:.08em;border:1px solid var(--line);
border-radius:6px;padding:3px 8px;background:rgba(255,255,255,.02);
transition:all 0.2s ease;margin-right:8px;display:flex;align-items:center;gap:4px}
.reload-lnk.success{color:var(--sup) !important;border-color:var(--sup) !important;background:rgba(46,230,200,.05) !important}
.reload-lnk.failed{color:var(--res) !important;border-color:var(--res) !important;background:rgba(255,107,107,.05) !important}
.reload-lnk:hover{color:var(--price);border-color:var(--price);background:rgba(111,164,255,.05)}
.dot{width:8px;height:8px;border-radius:50%;background:$dot_color;box-shadow:0 0 8px $dot_color;$dot_anim}
@keyframes pulse{50%{opacity:.4}}
.hero{text-align:center;margin-bottom:30px}
.hero h1{font-size:22px;font-weight:800}
.hero .sub{color:var(--dim);font-size:12px;margin:4px 0 14px}
.hero .px{font-size:62px;font-weight:600;color:var(--price);line-height:1;text-shadow:0 0 40px rgba(111,164,255,.4)}
.hero .px.stale{color:var(--muted);text-shadow:none}
.hero .chg{font-size:15px;margin-top:8px}
.hero .chg.stale{color:var(--pp);font-size:12.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
.spectrum{position:relative;margin:0 8px 44px;height:114px}
.band{position:absolute;left:0;right:0;top:50px;height:14px;border-radius:99px;
background:linear-gradient(90deg,#2EE6C8 0%,#1C7F71 22%,#2A3B5E 44%,#77602A 56%,#8F4040 78%,#FF6B6B 100%);
box-shadow:inset 0 1px 3px rgba(0,0,0,.5)}
.tick{position:absolute;top:36px;width:2px;height:42px;background:currentColor;opacity:.9;border-radius:2px}
.tick .lab{position:absolute;top:-24px;left:50%;transform:translateX(-50%);font-size:12px;font-weight:800}
.tick .val{position:absolute;bottom:-24px;left:50%;transform:translateX(-50%);font-size:12px;white-space:nowrap}
.t-s2{left:4%;color:var(--sup)}.t-s1{left:$s1_pct%;color:var(--sup)}
.t-pp{left:50%;color:var(--pp);height:50px;top:32px;width:3px}
.t-r1{left:$r1_pct%;color:var(--res)}.t-r2{left:96%;color:var(--res)}
.marker{position:absolute;left:$px_pct%;top:14px;transform:translateX(-50%);text-align:center}
.marker .tag{background:var(--price);color:#08101F;font-weight:800;font-size:13px;padding:5px 10px;border-radius:8px;
box-shadow:0 0 22px rgba(111,164,255,.6)}
.marker .stem{width:2px;height:32px;background:var(--price);margin:2px auto 0;border-radius:2px}
.returns{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-bottom:30px}
.ret{background:var(--panel);border:1px solid var(--line);border-radius:99px;padding:7px 15px;font-size:12.5px}
.ret span{color:var(--dim);font-weight:800;margin-right:7px}
.verdict{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
@media(max-width:760px){.verdict{grid-template-columns:1fr}}
.vcard{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 20px;text-align:center}
.vcard .k{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:800;margin-bottom:8px}
.vcard .big{font-size:24px;font-weight:800}
.vcard .sub2{font-size:12px;color:var(--muted);margin-top:5px;font-weight:600}
.grid{display:grid;grid-template-columns:340px 1fr;gap:16px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
.panelbox{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 20px}
.panelbox h3{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:800;margin-bottom:13px}
.lrow{display:flex;align-items:center;justify-content:space-between;padding:9px 2px;border-bottom:1px solid var(--line)}
.lrow:last-child{border-bottom:0}
.lrow .nm{font-size:13px;font-weight:800;display:flex;gap:10px;align-items:center}
.chip{width:8px;height:8px;border-radius:3px}
.lrow .v{font-size:15.5px;font-weight:600}
.lr-r .chip{background:var(--res)}.lr-r .v{color:var(--res)}
.lr-p .chip{background:var(--pp)}.lr-p .v{color:var(--pp)}
.lr-s .chip{background:var(--sup)}.lr-s .v{color:var(--sup)}
.lr-w .nm,.lr-w .v{color:var(--dim)}
.sgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
@media(max-width:560px){.sgrid{grid-template-columns:1fr 1fr}}
.sc{background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:12px;padding:12px 13px;text-align:center}
.sc .k{font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:var(--dim);font-weight:800;margin-bottom:6px}
.sc .v{font-size:17px;font-weight:800}
.sc .s{font-size:10.5px;color:var(--muted);margin-top:4px;font-weight:600}
.rc{background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:12px;
padding:12px 16px;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between}
.rc:last-child{margin-bottom:0}
.rc .k{font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:var(--dim);font-weight:800}
.rc .v{font-size:16px;font-weight:800;color:var(--text)}
.up{color:var(--sup)}.dn{color:var(--res)}.warn{color:var(--pp)}
.read{margin-top:18px;border-top:1px solid var(--line);padding-top:12px;text-align:center;color:var(--dim);font-weight:600;font-size:11px;letter-spacing:.04em;text-transform:uppercase}
.day-range-box{display:flex;align-items:center;justify-content:center;gap:10px;margin-top:10px;font-size:11px;color:var(--muted)}
.day-range-box .lbl{font-family:'IBM Plex Mono',monospace;font-weight:500}
.day-range-box .bar-bg{position:relative;width:140px;height:5px;background:#1E2C48;border-radius:99px;box-shadow:inset 0 1px 2px rgba(0,0,0,.3)}
.day-range-box .bar-dot{position:absolute;top:50%;transform:translate(-50%,-50%);width:9px;height:9px;background:var(--price);border-radius:50%;box-shadow:0 0 8px var(--price)}
.databanner{background:rgba(255,197,61,.08);border:1px solid var(--pp);color:var(--pp);
border-radius:10px;padding:8px 14px;margin-bottom:16px;text-align:center;
font-size:11.5px;font-weight:800;letter-spacing:.05em}
@keyframes pulse-warn {
  0% { color: #FFC53D; text-shadow: 0 0 4px rgba(255, 197, 61, 0.2); }
  50% { color: #FF6B6B; text-shadow: 0 0 10px rgba(255, 107, 107, 0.6); }
  100% { color: #FFC53D; text-shadow: 0 0 4px rgba(255, 197, 61, 0.2); }
}
.warn-flash {
  animation: pulse-warn 1.5s infinite !important;
  font-weight: 800 !important;
}
@media(max-width:480px){
  .wrap{padding:10px 8px 20px}
  .top{flex-direction:column;gap:8px;text-align:center}
  .hero .px{font-size:42px}
  .tick .val{font-size:9.5px;bottom:-18px}
  .tick .lab{font-size:10px;top:-18px}
  .marker .tag{font-size:11px;padding:3px 6px}
}
</style></head><body><div class="wrap">
<div class="top"><div class="brand">Pivot<em>Desk</em></div>
<div class="mkt"><a href="$reload_url" target="_parent" class="reload-lnk $reload_cls">🔄 Reload</a><span class="dot"></span><span class="mono">$mkt_label</span></div></div>
<div class="hero"><h1>$name</h1>
<div class="sub mono">Prev: H $ph · L $pl · C $pc</div>
<div class="px mono $px_cls">₹$price</div>
$chg_html
$day_range_html
</div>
$data_banner
<div class="spectrum">
<div class="band"></div>
<div class="tick t-s2"><span class="lab">S2</span><span class="val mono">$s2</span></div>
<div class="tick t-s1"><span class="lab">S1</span><span class="val mono">$s1</span></div>
<div class="tick t-pp"><span class="lab">PP</span><span class="val mono">$pp</span></div>
<div class="tick t-r1"><span class="lab">R1</span><span class="val mono">$r1</span></div>
<div class="tick t-r2"><span class="lab">R2</span><span class="val mono">$r2</span></div>
<div class="marker"><span class="tag mono">$price</span><div class="stem"></div></div>
</div>
<div class="returns">$returns_html
<span class="ret"><span>52W</span><b class="mono" style="color:var(--pp)">$rng_pct% of range</b></span></div>
<div class="verdict">
<div class="vcard"><div class="k">Technical bias</div>
<div class="big $bias_cls">$bias_label</div>
<div class="sub2" title="$bias_tooltip" style="cursor:help">$bias_n/6 signals bullish$bias_caution <span style="font-size:10.5px;color:var(--dim)">ⓘ</span></div></div>
$pos_card
</div>
<div class="grid">
<div class="panelbox"><h3>Reference</h3>
<div class="rc"><span class="k">Prev High</span><span class="v mono">₹$ph</span></div>
<div class="rc"><span class="k">Prev Low</span><span class="v mono">₹$pl</span></div>
<div class="rc"><span class="k">Prev Close</span><span class="v mono">₹$pc</span></div>
<div class="rc"><span class="k">Weekly PP</span><span class="v mono">₹$wpp</span></div></div>
<div class="panelbox"><h3>Swing view</h3><div class="sgrid">
<div class="sc"><div class="k">MAs 20·50·200</div><div class="v $ma_cls">$ma_v</div><div class="s">$ma_s</div></div>
<div class="sc"><div class="k">RSI 14</div><div class="v $rsi_cls">$rsi_v</div><div class="s">$rsi_s</div></div>
<div class="sc"><div class="k">MACD</div><div class="v $macd_cls">$macd_v</div><div class="s">$macd_s</div></div>
<div class="sc"><div class="k">Supertrend</div><div class="v $st_cls">$st_v</div><div class="s">stop ₹$st_stop</div></div>
<div class="sc"><div class="k">ATR 14</div><div class="v mono">₹$atr_v</div><div class="s">≈$atr_pct% per day</div></div>
<div class="sc"><div class="k">Vol vs 30D</div><div class="v $vol_cls">$vol_v×</div><div class="s">$vol_s</div></div>
</div><div class="read">$read</div></div></div>
</div></body></html>"""
)

HTML_ERROR = Template(
    r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Error — PivotDesk</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0A0E17;--panel:rgba(20,29,48,.72);--line:#1E2C48;--text:#EDF2FB;--muted:#7E8DA8;
--dim:#55637E;--res:#FF6B6B;--price:#6FA4FF}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Archivo',sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:10px 16px 28px}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:26px}
.brand{font-weight:800;font-size:17px}.brand em{font-style:normal;color:#FFC53D}
.mkt{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12.5px}
.reload-lnk{color:var(--res);text-decoration:none;font-size:10px;font-weight:800;
text-transform:uppercase;letter-spacing:.08em;border:1px solid var(--res);
border-radius:6px;padding:3px 8px;background:rgba(255,107,107,.05);
transition:all 0.2s ease;margin-right:8px;display:flex;align-items:center;gap:4px}
.reload-lnk:hover{color:var(--price);border-color:var(--price);background:rgba(111,164,255,.05)}
.error-box{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px;text-align:center;margin-top:40px}
.error-box h2{color:var(--res);font-size:18px;margin-bottom:12px;font-weight:800}
.error-box p{color:var(--muted);font-size:13.5px;line-height:1.6}
</style></head><body><div class="wrap">
<div class="top"><div class="brand">Pivot<em>Desk</em></div>
<div class="mkt"><a href="$reload_url" target="_parent" class="reload-lnk failed">🔄 Reload</a><span class="dot" style="width:8px;height:8px;border-radius:50%;background:var(--res);box-shadow:0 0 8px var(--res)"></span><span class="mono" style="color:var(--res)">FETCH FAILED</span></div></div>
<div class="error-box">
  <h2>Data Fetch Failed</h2>
  <p>$error_msg — Yahoo may be rate-limiting. Retrying in 60s.</p>
</div>
</div></body></html>"""
)


# ---------------------------------------------------------------- render entry points


def render_error(
    ticker: str,
    error_msg: str,
    entry: float = 0.0,
    favorites_str: str = "",
) -> None:
    """Render a minimal error page inside an iframe."""
    favs_qp = f"&favorites={favorites_str}" if favorites_str else ""
    html = HTML_ERROR.safe_substitute(
        error_msg=error_msg,
        reload_url=f"?ticker={ticker}&entry={entry}{favs_qp}&reload=1",
    )
    st.iframe(html, height=350)


def render(
    ticker: str,
    entry: float = 0.0,
    now: dt.datetime | None = None,
    reload_cls: str = "",
    favorites_str: str = "",
    qty: float = 0.0,
) -> None:
    """Build and display the full dashboard for *ticker*."""
    entry_val = float(entry) if entry is not None else 0.0
    qty_val = float(qty) if qty else 0.0
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
        px_pct_day = (
            (price - pv.day_low) / day_span * 100 if day_span > 0 else 50.0
        )
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
    if pv.stale:
        chg_html = (
            '<div class="chg stale">⚠ Live price unavailable · '
            "showing last close</div>"
        )
    else:
        chg = price - pv.baseline
        chg_pct = chg / pv.baseline * 100 if pv.baseline else 0.0
        chg_html = (
            f'<div class="chg mono" '
            f'style="color:{"var(--sup)" if chg >= 0 else "var(--res)"}">'
            f'{"▲" if chg >= 0 else "▼"} {chg:+,.2f} ({chg_pct:+.2f}%)</div>'
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
    rsi_cls = (
        "warn" if ind.rsi_val >= 70 else ("dn" if ind.rsi_val <= 30 else "up")
    )
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

    # ---- tooltip
    sig_sma20 = price > ind.sma20
    sig_sma50 = price > ind.sma50
    sig_sma200 = price > ind.sma200
    tooltip_lines = [
        "Technical Bias Breakdown:",
        f"{'🟢' if sig_sma20 else '🔴'} Price > 20D MA (₹{ind.sma20:,.0f})",
        f"{'🟢' if sig_sma50 else '🔴'} Price > 50D MA (₹{ind.sma50:,.0f})",
        f"{'🟢' if sig_sma200 else '🔴'} Price > 200D MA (₹{ind.sma200:,.0f})",
        f"{'🟢' if ind.st_up else '🔴'} Supertrend: Buy",
        f"{'🟢' if ind.macd_bull else '🔴'} MACD: Bullish",
        f"{'🟢' if price > piv['PP'] else '🔴'} Price > Pivot (₹{piv['PP']:,.2f})",
        "",
        SIGNAL_CAVEAT,
    ]
    bias_tooltip = "\n".join(tooltip_lines)

    # ---- final HTML assembly
    html = HTML.safe_substitute(
        name=ticker.replace(".NS", "") + " · NSE",
        mkt_label=f"{mkt_label} · STALE" if pv.stale else mkt_label,
        reload_cls=reload_cls,
        reload_url=f"?ticker={ticker}&entry={entry_val}&favorites={favorites_str}&reload=1",
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
        bias_tooltip=bias_tooltip,
        day_range_html=day_range_html,
        data_banner=(
            '<div class="databanner">⚠ Yahoo data unavailable · showing the last '
            "successful fetch, levels may be a session behind</div>"
            if daily_stale
            else ""
        ),
        pos_card=position_card(
            entry_val, price, ind.st_up, ind.st_stop, stale=pv.stale, qty=qty_val
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
            "dn"
            if ind.vol_ratio < 0.8
            else ("up" if ind.vol_ratio > 1.2 else "warn")
        ),
        vol_s=(
            "below average"
            if ind.vol_ratio < 0.8
            else ("above average" if ind.vol_ratio > 1.2 else "in line")
        ),
        read=compose_read(),
    )
    st.iframe(html, height="content")
