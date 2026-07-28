"""PivotDesk — the buy/wait action engine.

Turns the dashboard's raw signals (trend, RSI, ATR distance, support levels)
into a plain-language buy / wait / stand-aside call, plus the supporting
summary sentence. Fully decoupled from Streamlit and the network — pure
functions over floats, exercised directly by ``tests/test_rendering.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- helpers


def fmt(x: float) -> str:
    """Format a float as ₹-style with commas and 2 decimals."""
    return f"{x:,.2f}"


# ---------------------------------------------------------------- verdict

# Thresholds that turn the raw signals into a buy/wait call. Kept as named
# constants so the judgement calls stay visible and tunable in one place instead
# of hiding as magic numbers inside the branch conditions.
OVERBOUGHT_RSI = 70.0  # RSI at/above this is a stretched, chase-prone entry
EXTENDED_ATR = 2.0  # price this many ATRs above the pivot reads as extended
EXTENDED_RISK = 8.0  # a stop this far below (%) is a loose, late entry
SUPPORT_ATR = 0.5  # within this many ATRs of the pivot counts as "at support"
SUPPORT_RISK = 4.0  # a stop this close (%) means the downside is tightly defined
MIXED_MAX_SCORE = 2  # trend up but <= this many bullish signals = conflicted


@dataclass(frozen=True)
class Verdict:
    """A buy/wait read synthesised from signals already on the dashboard.

    A *reading of current conditions*, not a prediction of the low.
    ``zone_lo``/``zone_hi`` describe a support band worth buying into; both are
    ``None`` when the trend does not warrant buying at all. ``kind`` selects how
    the bottom line reads — in the downtrend (``"reclaim"``) case ``stop`` sits
    *above* the price, a level to reclaim rather than a stop-loss beneath it.
    """

    label: str
    css: str  # up | warn | dn — reuses the template's existing colour classes
    reason: str
    stop: float
    risk_pct: float
    zone_lo: float | None = None
    zone_hi: float | None = None
    kind: str = "buy"  # buy | wait | mixed | reclaim — selects the meta line


def entry_verdict(
    price: float,
    score: int,
    st_up: bool,
    st_stop: float,
    rsi_val: float,
    atr_val: float,
    piv: dict[str, float],
) -> Verdict:
    """Turn the computed signals into a buy / wait / stand-aside call.

    Two gates, in order:

    1. **Trend** — a down Supertrend, or an up one with the signals still mostly
       bearish, means there is no trend to ride: wait, whatever the price.
    2. **Location** — with the trend up, decide whether *this* price is a good
       entry (near support, tight stop) or a chase (overbought / stretched far
       above the pivot), and hand back the support band to buy into either way.
    """
    risk_pct = (price - st_stop) / price * 100 if price else 0.0

    # -- Gate 1: is there an uptrend to ride at all?
    if not st_up:
        return Verdict(
            label="Don't buy yet",
            css="dn",
            reason=(
                "Trying to buy while it is dropping is risky. Wait until it "
                f"climbs back above ₹{fmt(st_stop)} — the first sign it is "
                "turning around."
            ),
            stop=st_stop,
            risk_pct=risk_pct,
            kind="reclaim",
        )
    if score <= MIXED_MAX_SCORE:
        return Verdict(
            label="Wait — not clear yet",
            css="warn",
            reason=(
                "Most of the signs still look weak — give them time to line up "
                "before buying."
            ),
            stop=st_stop,
            risk_pct=risk_pct,
            kind="mixed",
        )

    # -- Gate 2: the trend is up; is *this* price a good spot to enter?
    pp = piv["PP"]
    ext_atr = (price - pp) / atr_val if atr_val else 0.0

    # The band to buy into: the two nearest support levels below the price.
    supports = sorted(
        (lvl for lvl in (pp, piv["S1"], piv["S2"], st_stop) if lvl < price),
        reverse=True,
    )
    if len(supports) >= 2:
        zone_hi, zone_lo = supports[0], supports[1]
    elif len(supports) == 1:
        zone_hi, zone_lo = supports[0], st_stop
    else:  # price already under every pivot — lean on the trend stop alone
        zone_hi = zone_lo = st_stop

    overbought = rsi_val >= OVERBOUGHT_RSI
    extended = ext_atr >= EXTENDED_ATR or risk_pct >= EXTENDED_RISK
    at_support = ext_atr <= SUPPORT_ATR or risk_pct <= SUPPORT_RISK

    if overbought or extended:
        if overbought:
            reason = (
                "It has shot up fast and looks overheated — buying now means "
                "paying up. Better to let it cool down toward the buy range "
                "below."
            )
        elif ext_atr >= EXTENDED_ATR:
            reason = (
                "It has jumped far above its usual level, fast — buying now is "
                "chasing it. Better to let it settle back toward the buy range "
                "below."
            )
        else:  # the safety exit is simply too far below the current price
            reason = (
                "It is a long way above its safety exit — you would risk about "
                f"{risk_pct:.0f}% before getting out. Wait for a dip so the exit "
                "sits closer."
            )
        return Verdict(
            label="Wait for a better price",
            css="warn",
            reason=reason,
            stop=st_stop,
            risk_pct=risk_pct,
            zone_lo=zone_lo,
            zone_hi=zone_hi,
            kind="wait",
        )
    if at_support:
        return Verdict(
            label="Good spot to buy",
            css="up",
            reason=(
                "It is sitting close to a level it tends to bounce from, so "
                f"your exit is near (about {risk_pct:.0f}% away) — if it goes "
                "wrong, the loss stays small."
            ),
            stop=st_stop,
            risk_pct=risk_pct,
            zone_lo=zone_lo,
            zone_hi=zone_hi,
            kind="buy",
        )
    return Verdict(
        label="OK, but wait for a dip",
        css="up",
        reason=(
            "It is in the middle of its range — not cheap right now. Waiting "
            "for a small dip toward the buy range below gets you a better price "
            "and a closer exit."
        ),
        stop=st_stop,
        risk_pct=risk_pct,
        zone_lo=zone_lo,
        zone_hi=zone_hi,
        kind="buy",
    )


def action_card(
    v: Verdict,
    summary: str,
    stale: bool = False,
    rr_str: str = "",
) -> str:
    """Build the Action card: the plain summary sentence leads, then the why
    and the plan. ``summary`` comes from :func:`plain_summary`, so the headline
    and the supporting detail always describe the same call."""

    def zone() -> str:
        return (
            f"₹{fmt(v.zone_lo)}"
            if v.zone_lo == v.zone_hi
            else f"₹{fmt(v.zone_lo)}–₹{fmt(v.zone_hi)}"
        )

    if v.kind == "reclaim":  # downtrend — the stop sits above, as a turn signal
        meta = f"<span>Wait for a move back above <b>₹{fmt(v.stop)}</b></span>"
    elif v.kind == "mixed":  # trend up but unconfirmed — no buy range yet
        meta = f"<span>If you hold, Safety Exit <b>₹{fmt(v.stop)}</b></span>"
    elif v.kind == "wait":  # buy range named
        meta = (
            f"<span>Better buy <b>{zone()}</b></span>"
            f"<span>Safety Exit <b>₹{fmt(v.stop)}</b></span>"
        )
    else:  # "buy" — actionable now, so show what it costs you if it's wrong
        meta = (
            f"<span>Buy <b>{zone()}</b></span>"
            f"<span>Safety Exit <b>₹{fmt(v.stop)}</b></span>"
            f"<span>risk ~<b>{v.risk_pct:.0f}%</b></span>"
        )

    if rr_str:
        meta += f"<span>{rr_str}</span>"

    emoji = {"up": "🟢", "warn": "🟡", "dn": "🔴"}[v.css]
    # Only a functional note remains — a flag that the read is on a stale price.
    stale_note = '<div class="atag">on the last close, not live</div>' if stale else ""
    copy_btn = (
        '<div style="margin-top:12px;">'
        '<button type="button" class="copy-btn">'
        "📋 Copy Trade Plan</button></div>"
    )
    return (
        f'<div class="acard {v.css}"><div class="k">Action</div>'
        f'<div class="asum"><span class="em">{emoji}</span>{summary}</div>'
        f'<div class="ameta">{meta}</div>'
        f"{copy_btn}"
        f"{stale_note}</div>"
    )


# ---------------------------------------------------------------- plain summary

# The Action label, reworded as a sentence ending so the summary reads naturally.
SUMMARY_CONCLUSION = {
    "Good spot to buy": "a lower-risk spot to start buying",
    "OK, but wait for a dip": "you could buy, but a small dip is a better deal",
    "Wait for a better price": "better to wait for a dip",
    "Wait — not clear yet": "better to wait until the signs agree",
    "Don't buy yet": "best to wait until it turns back up",
}


def plain_summary(
    name: str, score: int, st_up: bool, rsi_val: float, verdict: Verdict
) -> str:
    """One plain sentence describing the whole dashboard: trend, heat, and call.

    Built from the same inputs as the Action card, so the two never disagree.
    """
    if not st_up:
        trend = "is falling right now"
    elif score >= 5:
        trend = "is rising strongly"
    elif score == 4:
        trend = "is rising"
    elif score == 3:
        trend = "is edging higher"
    else:
        trend = "is just starting to turn up"

    if rsi_val >= OVERBOUGHT_RSI:
        heat = " but looks hot (it has risen fast)"
    elif rsi_val <= 30:
        heat = " and looks beaten-down (it has fallen hard)"
    else:
        heat = ""

    conclusion = SUMMARY_CONCLUSION.get(verdict.label, verdict.label)
    return f"{name} {trend}{heat} — {conclusion}."
