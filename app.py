"""PivotDesk — live pivot-point dashboard for NSE stocks.

Daily pivots roll automatically from the last completed NSE session.
Swing metrics (MAs, RSI, MACD, Supertrend, ATR, volume, returns) are
computed from daily history. Live price refreshes every 60s while the
market is open. Data: Yahoo Finance via yfinance. Not investment advice.
"""

from __future__ import annotations

import datetime as dt
from string import Template
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)

# ---------------------------------------------------------------- market clock

def market_status(now: dt.datetime) -> tuple[bool, str]:
    """(is_open, label). Weekdays 09:15–15:30 IST. NSE holidays appear
    closed only through stale data; see README."""
    if now.weekday() >= 5:
        return False, "MARKET CLOSED · WEEKEND"
    if MARKET_OPEN <= now.time() <= MARKET_CLOSE:
        return True, f"MARKET OPEN · {now:%H:%M} IST"
    return False, f"MARKET CLOSED · {now:%H:%M} IST"

# ---------------------------------------------------------------- data fetch

from curl_cffi import requests

@st.cache_data(ttl=600, show_spinner=False)
def fetch_daily(ticker: str) -> pd.DataFrame:
    session = requests.Session(impersonate="chrome")
    df = yf.Ticker(ticker, session=session).history(period="2y", interval="1d", auto_adjust=False)
    if df.empty:
        raise ValueError(f"No data for '{ticker}'. Check the symbol (e.g. BHAGYANGR.NS).")
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()

@st.cache_data(ttl=55, show_spinner=False)
def fetch_live_price(ticker: str) -> float | None:
    try:
        session = requests.Session(impersonate="chrome")
        intra = yf.Ticker(ticker, session=session).history(period="1d", interval="1m")
        if not intra.empty:
            return float(intra["Close"].iloc[-1])
    except Exception:
        pass
    return None

def completed_sessions(df: pd.DataFrame, now: dt.datetime, is_open: bool) -> pd.DataFrame:
    """Drop today's partial candle while the market is open."""
    last_date = df.index[-1].astimezone(IST).date() if df.index.tz else df.index[-1].date()
    if is_open and last_date == now.date():
        return df.iloc[:-1]
    return df

# ---------------------------------------------------------------- indicators

def pivots(h: float, l: float, c: float) -> dict[str, float]:
    pp = (h + l + c) / 3
    return {
        "PP": pp,
        "R1": 2 * pp - l,
        "S1": 2 * pp - h,
        "R2": pp + (h - l),
        "S2": pp - (h - l),
    }

def rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return float((100 - 100 / (1 + rs)).iloc[-1])

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["Close"].shift()
    tr = pd.concat(
        [df["High"] - df["Low"],
         (df["High"] - prev_close).abs(),
         (df["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()

def macd_state(close: pd.Series) -> tuple[bool, bool]:
    """(is_bullish, momentum_building)."""
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return bool(hist.iloc[-1] > 0), bool(abs(hist.iloc[-1]) >= abs(hist.iloc[-2]))

def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> tuple[bool, float]:
    """(is_uptrend, stop_level) — classic Supertrend."""
    hl2 = (df["High"] + df["Low"]) / 2
    a = atr(df, period)
    ub, lb = hl2 + mult * a, hl2 - mult * a
    fub, flb = ub.copy(), lb.copy()
    close = df["Close"]
    for i in range(1, len(df)):
        fub.iloc[i] = ub.iloc[i] if (ub.iloc[i] < fub.iloc[i - 1] or close.iloc[i - 1] > fub.iloc[i - 1]) else fub.iloc[i - 1]
        flb.iloc[i] = lb.iloc[i] if (lb.iloc[i] > flb.iloc[i - 1] or close.iloc[i - 1] < flb.iloc[i - 1]) else flb.iloc[i - 1]
    up = True
    for i in range(period, len(df)):
        up = close.iloc[i] > fub.iloc[i] if not up else close.iloc[i] >= flb.iloc[i]
    return up, float(flb.iloc[-1] if up else fub.iloc[-1])

def weekly_pivot(df: pd.DataFrame, now: dt.datetime) -> float:
    wk = df.resample("W-FRI").agg({"High": "max", "Low": "min", "Close": "last"}).dropna()
    if not wk.empty:
        wk_end = wk.index[-1].date() if not wk.index.tz else wk.index[-1].astimezone(IST).date()
        if wk_end >= now.date():        # current week still in progress
            wk = wk.iloc[:-1]
    h, l, c = wk.iloc[-1][["High", "Low", "Close"]]
    return (h + l + c) / 3

def pct_return(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - sessions] - 1) * 100

# ---------------------------------------------------------------- read line

def compose_read(price: float, pp: float, sma200: float, st_up: bool,
                 rsi_v: float, vol_ratio: float) -> str:
    if price > sma200 and st_up:
        trend = "Uptrend intact"
    elif price < sma200 and not st_up:
        trend = "Downtrend in force"
    else:
        trend = "Mixed trend"
    clauses = []
    if rsi_v >= 70:
        clauses.append(f"stretched (RSI {rsi_v:.0f})")
    elif rsi_v <= 30:
        clauses.append(f"washed out (RSI {rsi_v:.0f})")
    if vol_ratio < 0.8:
        clauses.append("volume fading")
    elif vol_ratio > 1.5:
        clauses.append("volume expanding")
    mid = " — " + ", ".join(clauses) if clauses else ""
    side = "below" if price > pp else "above"
    return f"{trend}{mid}. Bias flips {side} ₹{pp:,.2f}."

# ---------------------------------------------------------------- verdict

def technical_score(price: float, sma20: float, sma50: float, sma200: float,
                    st_up: bool, macd_bull: bool, pp: float) -> tuple[int, str, str]:
    """Count of 6 transparent bullish signals → (score, label, css_class)."""
    score = sum([price > sma20, price > sma50, price > sma200,
                 st_up, macd_bull, price > pp])
    if score >= 5:
        return score, "Strong bullish", "up"
    if score == 4:
        return score, "Bullish", "up"
    if score == 3:
        return score, "Neutral", "warn"
    if score == 2:
        return score, "Bearish", "dn"
    return score, "Strong bearish", "dn"

def position_card(entry: float, price: float, st_up: bool, st_stop: float) -> str:
    if not entry or entry <= 0:
        return ('<div class="vcard"><div class="k">Your position</div>'
                '<div class="big" style="color:var(--dim)">—</div>'
                '<div class="sub2">enter your buy price above to track P&L '
                'and your trend stop</div></div>')
    pnl = (price / entry - 1) * 100
    pnl_color = "var(--sup)" if pnl >= 0 else "var(--res)"
    if st_up:
        stat, stat_cls = f"Trend intact · breaks below ₹{fmt(st_stop)}", "up"
    else:
        stat, stat_cls = f"Trend broken · recovery above ₹{fmt(st_stop)}", "dn"
    return (f'<div class="vcard"><div class="k">Your position</div>'
            f'<div class="big mono" style="color:{pnl_color}">{pnl:+.1f}%</div>'
            f'<div class="sub2">entry ₹{fmt(entry)} · now ₹{fmt(price)}</div>'
            f'<div class="sub2 {stat_cls}">{stat}</div></div>')

# ---------------------------------------------------------------- html render

HTML = Template(r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
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
.hero .chg{color:$chg_color;font-size:15px;margin-top:8px}
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
.read{margin-top:16px;text-align:center;color:#C9D4E8;font-size:13.5px;line-height:1.6}
footer{margin-top:22px;color:var(--dim);font-size:11px;text-align:center}
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
<div class="px mono">₹$price</div>
<div class="chg mono">$chg_arrow $chg_abs ($chg_pct%)</div></div>
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
<div class="sub2">$bias_n/6 signals bullish$bias_caution</div></div>
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
<footer>Data: Yahoo Finance · levels roll each NSE session · descriptive only, not investment advice</footer>
</div></body></html>""")

def fmt(x: float) -> str:
    return f"{x:,.2f}"

HTML_ERROR = Template(r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
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
</div></body></html>""")

def render_error(ticker: str, error_msg: str, entry: float = 0.0) -> None:
    html = HTML_ERROR.safe_substitute(
        error_msg=error_msg,
        reload_url=f"?ticker={ticker}&entry={entry}&reload=1"
    )
    st.iframe(html, height=350)

def render(ticker: str, entry: float = 0.0, now: dt.datetime | None = None, reload_cls: str = "") -> None:
    now = now or dt.datetime.now(IST)
    is_open, mkt_label = market_status(now)

    daily = fetch_daily(ticker)
    comp = completed_sessions(daily, now, is_open)
    if len(comp) < 60:
        st.error("Not enough history for this symbol (need ≥60 sessions).")
        return

    prev = comp.iloc[-1]
    ph, pl, pc = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
    piv = pivots(ph, pl, pc)

    live = fetch_live_price(ticker) if is_open else None
    price = live if live is not None else pc
    chg = price - pc
    chg_pct = chg / pc * 100 if pc else 0.0

    close = comp["Close"]
    sma20, sma50 = close.rolling(20).mean().iloc[-1], close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else close.mean()
    above = sum(price > m for m in (sma20, sma50, sma200))
    ma_v = "Above all" if above == 3 else ("Below all" if above == 0 else f"Above {above}/3")
    ma_s = f"₹{sma20:,.0f} · ₹{sma50:,.0f} · ₹{sma200:,.0f}"
    ma_cls = "up" if above == 3 else ("dn" if above == 0 else "warn")

    rsi_v = rsi(close)
    rsi_cls = "warn" if rsi_v >= 70 else ("dn" if rsi_v <= 30 else "up")
    rsi_s = "overbought" if rsi_v >= 70 else ("oversold" if rsi_v <= 30 else "neutral zone")

    bull, building = macd_state(close)
    st_up, st_stop = supertrend(comp)
    atr_v = float(atr(comp).iloc[-1])
    vol_ratio = float(comp["Volume"].iloc[-1] / comp["Volume"].iloc[-31:-1].mean())

    yr = comp.tail(252)
    lo52, hi52 = float(yr["Low"].min()), float(yr["High"].max())
    rng_pct = (price - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else 50.0

    rets = []
    for lab, n in (("1W", 5), ("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252)):
        r = pct_return(close, n)
        if r is not None:
            color = "var(--sup)" if r >= 0 else "var(--res)"
            rets.append(f'<span class="ret"><span>{lab}</span>'
                        f'<b class="mono" style="color:{color}">{r:+.1f}%</b></span>')

    span = piv["R2"] - piv["S2"]
    pos = lambda v: max(2.0, min(98.0, 4 + 92 * (v - piv["S2"]) / span))

    score, bias_label, bias_cls = technical_score(
        price, float(sma20), float(sma50), float(sma200), st_up, bull, piv["PP"])
    if rsi_v >= 70:
        bias_caution = f" · RSI {rsi_v:.0f} extended"
    elif rsi_v <= 30:
        bias_caution = f" · RSI {rsi_v:.0f} washed out"
    else:
        bias_caution = ""

    html = HTML.safe_substitute(
        name=ticker.replace(".NS", "") + " · NSE",
        mkt_label=mkt_label,
        reload_cls=reload_cls,
        reload_url=f"?ticker={ticker}&entry={entry}&reload=1",
        dot_color="var(--sup)" if is_open else "var(--dim)",
        dot_anim="animation:pulse 2s infinite" if is_open else "",
        ph=fmt(ph), pl=fmt(pl), pc=fmt(pc),
        price=fmt(price),
        chg_color="var(--sup)" if chg >= 0 else "var(--res)",
        chg_arrow="▲" if chg >= 0 else "▼",
        chg_abs=f"{chg:+,.2f}", chg_pct=f"{chg_pct:+.2f}",
        pp=fmt(piv["PP"]), r1=fmt(piv["R1"]), r2=fmt(piv["R2"]),
        s1=fmt(piv["S1"]), s2=fmt(piv["S2"]),
        s1_pct=f"{pos(piv['S1']):.1f}", r1_pct=f"{pos(piv['R1']):.1f}",
        px_pct=f"{pos(price):.1f}",
        wpp=fmt(weekly_pivot(comp, now)),
        returns_html="".join(rets),
        rng_pct=f"{rng_pct:.0f}",
        bias_label=bias_label, bias_cls=bias_cls,
        bias_n=str(score), bias_caution=bias_caution,
        pos_card=position_card(entry, price, st_up, st_stop),
        ma_v=ma_v, ma_cls=ma_cls,
        ma_s=ma_s,
        rsi_v=f"{rsi_v:.0f}", rsi_cls=rsi_cls, rsi_s=rsi_s,
        macd_v="Bullish" if bull else "Bearish",
        macd_cls="up" if bull else "dn",
        macd_s="momentum building" if building else "momentum cooling",
        st_v="Buy" if st_up else "Sell", st_cls="up" if st_up else "dn",
        st_stop=fmt(st_stop),
        atr_v=fmt(atr_v), atr_pct=f"{atr_v / price * 100:.1f}",
        vol_v=f"{vol_ratio:.1f}",
        vol_cls="dn" if vol_ratio < 0.8 else ("up" if vol_ratio > 1.2 else "warn"),
        vol_s="below average" if vol_ratio < 0.8 else ("above average" if vol_ratio > 1.2 else "in line"),
        read=compose_read(price, piv["PP"], sma200, st_up, rsi_v, vol_ratio),
    )
    st.iframe(html, height="content")

# ---------------------------------------------------------------- streamlit ui

st.set_page_config(page_title="PivotDesk", page_icon="📐", layout="centered",
                   initial_sidebar_state="collapsed")

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
</style>""", unsafe_allow_html=True)

default_ticker = st.query_params.get("ticker", "BHAGYANGR.NS")
default_entry = 0.0
try:
    default_entry = float(st.query_params.get("entry", "0.0"))
except ValueError:
    pass

c1, c2 = st.columns([3, 2])
with c1:
    raw = st.text_input("NSE ticker", value=default_ticker,
                        help="Any NSE symbol — .NS is added automatically")
with c2:
    entry = st.number_input("Your buy price ₹ (optional)", min_value=0.0,
                            value=default_entry, step=0.05, format="%.2f",
                            help="Average entry price — enables the position monitor")

if raw != default_ticker or entry != default_entry:
    st.query_params["ticker"] = raw
    st.query_params["entry"] = str(entry)
ticker = raw.strip().upper()
if ticker and "." not in ticker:
    ticker += ".NS"

@st.fragment(run_every="60s")
def dashboard() -> None:
    try:
        render(ticker, entry, reload_cls=reload_status)
    except ValueError as e:
        st.error(str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        st.session_state["reload_status"] = "failed"
        render_error(ticker, str(e), entry=entry)

if ticker:
    dashboard()
