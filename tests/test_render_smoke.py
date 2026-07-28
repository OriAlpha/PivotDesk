"""End-to-end render tests against synthetic data (no network).

``Template.safe_substitute`` leaves unknown placeholders in the output
instead of raising, so a template edit can silently ship a literal
``$chg_html`` to the browser. These tests walk the whole render path and
assert the rendered document is fully substituted.

``data_through`` is the last row in the *raw* daily frame, before
``completed_sessions`` trims it. On a live trading day Yahoo publishes a
partial row for today, so ``data_through`` is today; a weekday where it is
not is what holiday detection keys on.
"""

from __future__ import annotations

import datetime as dt
import math
import re

import pandas as pd
import pytest

import rendering
from config import IST
from data import completed_sessions
from templates import js_literal

PLACEHOLDER = re.compile(r"\$[a-zA-Z_][a-zA-Z0-9_]*")

MON = dt.date(2026, 7, 20)
TUE = dt.date(2026, 7, 21)
SAT = dt.date(2026, 7, 25)


def history(last: dt.date, periods: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(last), periods=periods, tz="Asia/Kolkata")
    closes = [100 + i * 0.1 + 5 * math.sin(i / 7) for i in range(periods)]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 2 for c in closes],
            "Low": [c - 2 for c in closes],
            "Close": closes,
            "Volume": [10_000 + i for i in range(periods)],
        },
        index=idx,
    )


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


@pytest.fixture
def rendered(monkeypatch):
    """Render with patched I/O and return the HTML handed to the iframe."""

    def _render(
        *,
        data_through,
        now,
        live,
        entry=0.0,
        qty=0.0,
        daily_stale=False,
    ):
        captured: dict[str, str] = {}
        monkeypatch.setattr(
            rendering.st, "iframe", lambda html, **kw: captured.update(html=html)
        )
        monkeypatch.setattr(
            rendering,
            "fetch_daily_resilient",
            lambda _t: (history(data_through), daily_stale),
        )
        monkeypatch.setattr(rendering, "fetch_live_price", lambda _t: live)
        rendering.render("TEST.NS", entry, now=now, qty=qty)
        return captured["html"]

    return _render


OPEN = dict(data_through=TUE, now=at(TUE, 11, 0))
CLOSED = dict(data_through=TUE, now=at(TUE, 16, 30), live=None)
WEEKEND = dict(data_through=TUE, now=at(SAT, 11, 0), live=None)
HOLIDAY = dict(data_through=MON, now=at(TUE, 11, 0), live=None)


# ---------------------------------------------------------------- substitution


@pytest.mark.parametrize(
    "case",
    [
        dict(OPEN, live=(150.0, 148.0, 152.0)),
        dict(OPEN, live=None),
        CLOSED,
        WEEKEND,
        HOLIDAY,
    ],
)
def test_render_has_no_unsubstituted_placeholders(rendered, case):
    assert PLACEHOLDER.findall(rendered(**case, entry=100.0, qty=25)) == []


def test_every_supplied_value_has_a_placeholder(rendered, monkeypatch):
    """The mirror of the test above, which only catches a placeholder with no
    value. ``safe_substitute`` drops surplus keys without a word, so a value
    whose placeholder has been edited out of the markup goes on being built
    and passed on every draw while rendering nothing — which is how the
    footer, the move-context line and the backtest readout all went missing.
    """
    supplied: dict[str, object] = {}
    real = rendering.HTML.safe_substitute

    def spy(**kwargs):
        supplied.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(rendering.HTML, "safe_substitute", spy)
    rendered(**CLOSED)

    assert set(supplied) == set(rendering.HTML.get_identifiers())


def test_chart_page_is_handed_exactly_what_it_asks_for(monkeypatch):
    """Same guard for the chart frame."""
    supplied: dict[str, object] = {}
    real = rendering.CHART_PAGE.safe_substitute

    def spy(**kwargs):
        supplied.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(rendering.CHART_PAGE, "safe_substitute", spy)
    monkeypatch.setattr(rendering.st, "iframe", lambda html, **kw: None)
    monkeypatch.setitem(
        rendering.st.session_state, rendering.CHART_STATE_KEY, "<div>chart</div>"
    )
    rendering.render_chart_panel()

    assert set(supplied) == set(rendering.CHART_PAGE.get_identifiers())


# ---------------------------------------------------------------- stale price


def test_failed_live_fetch_says_so_instead_of_showing_a_flat_change(rendered):
    html = rendered(**OPEN, live=None)
    assert "Live price unavailable" in html
    assert "(+0.00%)" not in html
    assert "· STALE" in html
    # A stale price must not keep the healthy pulsing "market open" dot.
    assert "animation:pulse 2s infinite" not in html
    # No intraday data means no day-range bar (the class always exists in CSS,
    # so match the markup).
    assert '<div class="day-range-box">' not in html


def test_live_render_keeps_the_open_market_indicator(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert "Live price unavailable" not in html
    assert "· STALE" not in html
    assert "animation:pulse 2s infinite" in html
    assert '<div class="day-range-box">' in html


@pytest.mark.parametrize("case", [CLOSED, WEEKEND, HOLIDAY])
def test_no_day_range_bar_once_the_session_is_over(rendered, case):
    """The bar used to fall back to the last session's low/high, restating the
    Reference card's Prev L/H under a heading that no longer meant today."""
    html = rendered(**case)
    assert '<div class="day-range-box">' not in html
    # The numbers themselves are not lost — Reference still carries them.
    raw = history(case["data_through"])
    prev = completed_sessions(raw, case["now"]).iloc[-1]
    assert f"{prev['Low']:,.2f}" in html
    assert f"{prev['High']:,.2f}" in html


# ---------------------------------------------------------------- change readout


def test_closed_market_shows_the_last_sessions_real_move(rendered):
    """Regression: outside market hours the change was always +0.00."""
    html = rendered(**CLOSED)
    assert "(+0.00%)" not in html
    assert re.search(r"[▲▼] [-+][\d,.]+ \([-+]\d+\.\d\d%\)", html)


def test_weekend_shows_the_last_sessions_real_move(rendered):
    html = rendered(**WEEKEND)
    assert "WEEKEND" in html
    assert "(+0.00%)" not in html


def test_live_change_is_measured_against_the_previous_close(rendered):
    # Today's partial row is dropped, so the anchor is the row before it.
    prev_close = float(history(TUE)["Close"].iloc[-2])
    html = rendered(**OPEN, live=(prev_close + 5.0, 148.0, 152.0))
    assert f"▲ {5.0:+,.2f}" in html


# ---------------------------------------------------------------- holidays


def test_weekday_without_a_session_is_reported_as_a_holiday(rendered):
    """A weekday inside market hours with no row of its own is an NSE holiday,
    not an open market with a broken feed."""
    html = rendered(**HOLIDAY)
    assert "NSE HOLIDAY" in html
    assert "animation:pulse 2s infinite" not in html
    assert "Live price unavailable" not in html  # closed, not stale
    assert "(+0.00%)" not in html  # still shows the last session's real move


def test_normal_trading_day_is_not_a_holiday(rendered):
    assert "HOLIDAY" not in rendered(**OPEN, live=(150.0, 148.0, 152.0))


def test_weekend_is_not_called_a_holiday(rendered):
    assert "HOLIDAY" not in rendered(**WEEKEND)


def test_stale_daily_data_is_not_mistaken_for_a_holiday(rendered):
    """Served-from-cache data is behind by construction; that is a fetch
    failure to report, not a market holiday."""
    html = rendered(**HOLIDAY, daily_stale=True)
    assert "NSE HOLIDAY" not in html
    assert "Yahoo data unavailable" in html


def test_fresh_daily_data_shows_no_banner(rendered):
    assert "Yahoo data unavailable" not in rendered(**OPEN, live=(150.0, 148.0, 152.0))


# ---------------------------------------------------------------- 52-week range


def test_new_high_reads_as_full_range_not_over_100_percent(rendered):
    """Regression: a live price above the completed-session 52w high produced
    an impossible reading like "103% of range"."""
    html = rendered(**OPEN, live=(9_999.0, 9_000.0, 9_999.0))
    assert int(re.search(r">(\d+)% of range<", html).group(1)) == 100


# ---------------------------------------------------------------- pivot tooltips


def test_pivot_tooltips_are_reachable_without_a_pointer(rendered):
    """Regression: the level names lived behind :hover alone, so on a phone --
    the way this dashboard is mostly read -- they could not be opened at all."""
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    # A tap sets .tip-open; hover is fenced off to devices that actually hover.
    assert ".tick[data-tip].tip-open::after" in html
    assert "@media(hover:hover)" in html
    assert "tip-open" in html.split("<script>")[-1]  # the toggle ships too
    # Every tick is focusable and announces its own label.
    for lvl in ("S2", "S1", "PP", "R1", "R2"):
        assert f'aria-label="{lvl} ' in html
    assert html.count('tabindex="0" role="button"') == 5


def test_outer_pivot_tooltips_are_pinned_inside_the_frame(rendered):
    """S2 and R2 sit at 4%/96%, so a centred tooltip hangs off the edge."""
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert ".tick.t-s2::after{left:0;transform:none}" in html
    assert ".tick.t-r2::after{left:auto;right:0;transform:none}" in html


# ---------------------------------------------------------------- bias card


def test_the_signal_breakdown_needs_no_hover(rendered):
    """Regression: the breakdown lived in a title attribute, so it required
    hover and was invisible on every touch device."""
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert 'class="sigchips"' in html
    assert "title=" not in html
    assert "cursor:help" not in html
    assert "ⓘ" not in html


def test_all_six_signals_are_shown_on_the_card(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    chips = re.search(r'<div class="sigchips">(.*?)</div>', html, re.S).group(1)
    assert chips.count("<span") == 6
    for label in ("20D", "50D", "200D", "ST", "MACD", "PP"):
        assert label in chips


def test_the_chip_count_matches_the_headline_score(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    chips = re.search(r'<div class="sigchips">(.*?)</div>', html, re.S).group(1)
    score = int(re.search(r">(\d)/6 signals bullish", html).group(1))
    assert chips.count('class="on"') == score


def test_the_correlation_caveat_is_not_present(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert "Not six independent reads" not in html


# ---------------------------------------------------------------- action card


def test_action_card_renders_without_an_advice_disclaimer(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert 'class="acard' in html
    assert "not investment advice" not in html


def test_action_card_notes_when_the_price_is_stale(rendered):
    html = rendered(**OPEN, live=None)  # market open but the quote failed
    assert 'class="acard' in html
    assert "not live" in html


# ---------------------------------------------------------------- plain summary


def test_summary_sentence_is_the_action_headline(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert 'class="asum"' in html
    # It leads with the clean symbol, not the "· NSE" display name.
    assert "TEST is" in html


def test_move_context_shows_next_to_a_real_change(rendered):
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert "Safety Exit" in html


def test_no_move_context_when_the_price_is_stale(rendered):
    """A failed quote has no real change, so there is no day to size up."""
    html = rendered(**OPEN, live=None)
    assert "on the last close, not live" in html


def test_reload_url_preserves_positions():
    import rendering

    html = rendering.HTML.safe_substitute(
        name="TEST",
        mkt_label="",
        reload_cls="",
        dot_color="",
        dot_anim="",
        ph="",
        pl="",
        pc="",
        price="",
        px_cls="",
        chg_html="",
        pp="",
        r1="",
        r2="",
        s1="",
        s2="",
        s1_pct="",
        r1_pct="",
        px_pct="",
        wpp="",
        returns_html="",
        rng_pct="",
        bias_label="",
        bias_cls="",
        bias_n="",
        bias_caution="",
        bias_chips="",
        action_card="",
        move_ctx="",
        day_range_html="",
        data_banner="",
        pos_card="",
        ma_v="",
        ma_cls="",
        ma_s="",
        rsi_v="",
        rsi_cls="",
        rsi_s="",
        macd_v="",
        macd_cls="",
        macd_s="",
        st_v="",
        st_cls="",
        st_stop="",
        atr_v="",
        atr_pct="",
        vol_v="",
        vol_cls="",
        vol_s="",
        symbol_js='"RELIANCE"',
        reload_url="?ticker=RELIANCE.NS&entry=1200&positions=RELIANCE:1200:50,TCS:3100:10&reload=1",
    )
    assert "&positions=RELIANCE:1200:50,TCS:3100:10" in html


# ---------------------------------------------------------------- escaping


def test_reload_url_neutralises_a_quote_in_the_position_book():
    """Regression: ``?positions=`` was echoed into the reload ``href`` as-is,
    so a quote closed the attribute and everything after it became live
    markup on a link the page invites you to click."""
    url = rendering.reload_url("RELIANCE.NS", 1200.0, '" onmouseover="STEAL()')
    assert 'onmouseover="STEAL()' not in url
    assert "%22" in url


def test_reload_url_leaves_an_ordinary_book_readable():
    """Escaping must not mangle the separators the book is built from."""
    url = rendering.reload_url("RELIANCE.NS", 1200.0, "RELIANCE:1200:50,TCS:3100:10")
    assert "positions=RELIANCE:1200:50,TCS:3100:10" in url


def test_the_error_page_sizes_itself_to_its_content():
    """It renders into a fixed 350px iframe, so a long message would be cut
    off with no way to scroll to the rest — the same clipping the dashboard
    had before the frame was matched to its content."""
    page = rendering.HTML_ERROR.safe_substitute(error_msg="boom", reload_url="?x=1")
    assert "syncFrameHeight" in page


def test_a_ticker_cannot_close_the_inline_script_block():
    """The ticker reaches an inline <script>, and the HTML parser ends that
    block at ``</script>`` no matter what the JavaScript quoting says."""
    assert "</script>" not in js_literal("AB</script><img src=x>")


# ---------------------------------------------------------------- benchmark


def test_vs_nifty_benchmark_line_is_removed(rendered):
    """The page must render without any vs-NIFTY benchmark line."""
    html = rendered(**OPEN, live=(150.0, 148.0, 152.0))
    assert "vs NIFTY" not in html
