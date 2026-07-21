# PivotDesk 📐

A live pivot-point dashboard for NSE stocks. Classic daily pivots (PP, S1/S2, R1/R2) roll forward automatically from each completed session, with a swing-view panel (20/50/200-day MAs, RSI-14, MACD, Supertrend, ATR-14, volume trend, 1W–1Y returns, 52-week range) for multi-day context.

Data comes from Yahoo Finance via `yfinance` — free, no API key. Live price refreshes every 60 seconds while NSE is open (09:15–15:30 IST).

## Run locally

Dependencies are managed with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run streamlit run app.py
```

Enter any NSE symbol (`.NS` is appended automatically): `BHAGYANGR`, `RELIANCE`, `TATAMOTORS`...

## Tests

```bash
uv run pytest
```

The indicator math (`pivots`, `rsi`, `atr`, `supertrend`, `weekly_pivot`) is pure and covered by golden-value tests. `tests/test_render_smoke.py` walks the full render path against synthetic data — no network — and asserts the emitted HTML is fully substituted, since `Template.safe_substitute` leaves unknown placeholders in the page rather than raising.

`pyproject.toml` is the source of truth for dependencies. `requirements.txt` is generated from `uv.lock` for Streamlit Community Cloud, which does not read lockfiles — regenerate it after any dependency change:

```bash
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt
```

## Deploy free on Streamlit Community Cloud

1. Push this folder to a GitHub repo (public or **private** — both work)
2. Go to share.streamlit.io → **New app** → pick the repo, branch `main`, file `app.py` → **Deploy**
3. Optional, to keep the app private: app **Settings → Sharing** → disable public access and add your email to the viewer allow-list

## Technical bias & position monitor

The **Technical bias** card counts six transparent bullish signals: price above the 20-day, 50-day, and 200-day moving averages, Supertrend on Buy, MACD above its signal line, and price above the daily pivot. One label per score, with an RSI flag when the reading is extreme (≥70 or ≤30):

| Score | Label | Share of days |
|---|---|---|
| 6/6 | Strong bullish | 8.5% |
| 5/6 | Bullish | 16.0% |
| 4/6 | Leaning bullish | 15.3% |
| 3/6 | Neutral | 15.0% |
| 2/6 | Leaning bearish | 14.0% |
| 1/6 | Bearish | 18.6% |
| 0/6 | Strong bearish | 12.5% |

Those shares are measured over 19,443 ticker-days (39 NSE symbols, 2 years each). The buckets matter: grouping 5–6 as "Strong bullish" and 0–1 as "Strong bearish" put a *Strong* verdict on **55.7% of all days**, which is not a verdict at all. One label per score puts it on 21.1%.

**The six signals are not independent.** On the same sample, price-vs-SMA20, price-vs-SMA50, Supertrend and MACD agree with each other 76–80% of the time, against a ~50% baseline for genuinely independent signals — so 6/6 is closer to three confirming reads than six. Price-vs-pivot is the most orthogonal of the set (52–62%) because it re-anchors daily. The tooltip says so too.

Enter your average buy price to activate the **position monitor**: live P&L plus the level where the technical picture changes (the Supertrend stop). Add a quantity to see P&L in rupees rather than per share. This is a summary of indicator states — not a buy/sell recommendation.

Positions are remembered per symbol and kept in the URL, alongside the ticker and your quick list:

```
?ticker=RELIANCE.NS&positions=RELIANCE:1200:50,TCS:3100.5:10
```

So switching symbols loads that stock's cost basis rather than clearing it, and one bookmark restores the whole book. Note this puts your cost basis in the address bar — bear that in mind before sharing a link or handing over your screen.

## How the levels work

- **Daily pivots** use the previous completed session's High/Low/Close: `PP=(H+L+C)/3`, `R1=2PP−L`, `S1=2PP−H`, `R2=PP+(H−L)`, `S2=PP−(H−L)`. While the market is open, today's partial candle is excluded, so levels stay fixed for the session and roll forward automatically the next trading day.
- **Weekly pivot** uses the last completed week's H/L/C.
- **NSE holidays** are detected, not looked up. On a trading day Yahoo publishes a row for the current session within minutes of the open, so a weekday that still has none by 09:45 IST is a holiday — the market is marked closed and the last session's data is shown. No calendar to maintain each year.
- **Returns** (1W–1Y) use Adj Close so a dividend doesn't read as a loss; ignoring this distorts a single day's return by up to ~2% on an ex-dividend date. Every other number, including all the levels, uses raw Close so it matches what your broker terminal shows.

## Which price you're looking at

The close that anchors the pivots is not always the right baseline for the day's change, so the two are tracked separately:

- **Market open, quote available** — live price, change measured against the previous session's close.
- **Market closed** — the last completed session's close, change measured against the session *before* it. So on Saturday you see Friday's close and Friday's move.
- **Market open, quote failed** — Yahoo rate-limits. The last close is shown greyed out with a **live price unavailable** banner, the status dot turns amber and stops pulsing, and the day-range bar is hidden. The app will not present a stale price as a live one.

If the *daily* fetch fails too, the dashboard falls back to the last frame it fetched successfully and says so in a banner, rather than replacing the page with an error. That fallback only applies to a symbol that has loaded before — an unrecognised ticker still errors, since a typo shouldn't look like an outage.

### Why the close can differ from a quote you saw elsewhere

The dashboard shows NSE's **official closing price**, which is not the last traded price. They are different numbers, and the official one is what pivots are built from.

Verified against NSE's own bhavcopy for 2026-07-21 — Yahoo's daily close matched NSE's official `ClsPric` on **10 of 10** symbols, and NSE's `LastPric` on **0 of 10**:

| | official close | last traded |
|---|---|---|
| BHAGYANGR | 379.00 | 380.00 |
| RELIANCE | 1303.70 | 1304.60 |
| TCS | 2221.10 | 2219.00 |
| INFY | 1073.50 | 1070.60 |

So if a site quotes BHAGYANGR at ₹380, it is showing the last trade; ₹379 is the official close and the correct input to the levels.

This also means there is nothing to gain by moving the daily series to NSE directly — the free feed already carries exchange-official OHLC. NSE's live quote API blocks non-browser clients (HTTP 403) in any case, and its bhavcopy only publishes after the session ends.

## Disclaimer

Everything shown is descriptive statistics computed from public price history. It is not a prediction, recommendation, or investment advice.
