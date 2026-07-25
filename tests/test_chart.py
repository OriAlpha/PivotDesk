"""Tests for chart.py."""

from __future__ import annotations

import math

import pandas as pd

from chart import render_chart_html


def _sample_daily(periods: int = 100) -> pd.DataFrame:
    idx = pd.bdate_range(
        end=pd.Timestamp("2026-07-21"), periods=periods, tz="Asia/Kolkata"
    )
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


def test_render_chart_html_generates_valid_snippet():
    daily = _sample_daily()
    piv = {"PP": 105.0, "S1": 102.0, "S2": 98.0, "R1": 108.0, "R2": 112.0}
    html = render_chart_html(daily, piv, st_stop=99.0)
    assert "tv-chart" in html
    assert "LightweightCharts" in html
    assert "PP" in html
    assert "ST STOP" in html
