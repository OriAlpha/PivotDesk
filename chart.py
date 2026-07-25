"""PivotDesk — TradingView Lightweight Charts integration.

Generates HTML/JS for a native TradingView vector chart overlaid with daily
pivot levels, volume histograms, and interactive hover legend.
"""

from __future__ import annotations

import json

import pandas as pd


def render_chart_html(
    daily: pd.DataFrame,
    piv: dict[str, float],
    st_stop: float | None = None,
    sessions: int = 252,
    ticker: str = "",
) -> str:
    """Return HTML/JS snippet embedding a TradingView Lightweight Chart."""
    if daily is None or daily.empty:
        return '<div class="panelbox" style="margin-top:20px;padding:20px;text-align:center;color:var(--muted);">No chart data available.</div>'

    df = daily.tail(sessions).copy()

    candles = []
    volume = []
    for date, row in df.iterrows():
        time_str = (
            date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)[:10]
        )
        open_val = float(row["Open"]) if pd.notna(row.get("Open")) else 0.0
        high_val = float(row["High"]) if pd.notna(row.get("High")) else 0.0
        low_val = float(row["Low"]) if pd.notna(row.get("Low")) else 0.0
        close_val = float(row["Close"]) if pd.notna(row.get("Close")) else 0.0
        vol = (
            float(row["Volume"]) if "Volume" in row and pd.notna(row["Volume"]) else 0.0
        )

        candles.append(
            {
                "time": time_str,
                "open": open_val,
                "high": high_val,
                "low": low_val,
                "close": close_val,
            }
        )
        vol_color = (
            "rgba(46, 230, 200, 0.55)"
            if close_val >= open_val
            else "rgba(255, 107, 107, 0.55)"
        )
        volume.append({"time": time_str, "value": vol, "color": vol_color})

    levels = [
        {"title": "R2", "price": piv.get("R2"), "color": "#FF6B6B", "style": 2},
        {"title": "R1", "price": piv.get("R1"), "color": "#FF8E8E", "style": 1},
        {"title": "PP", "price": piv.get("PP"), "color": "#FFC53D", "style": 0},
        {"title": "S1", "price": piv.get("S1"), "color": "#4EE6C8", "style": 1},
        {"title": "S2", "price": piv.get("S2"), "color": "#2EE6C8", "style": 2},
    ]

    if st_stop and st_stop > 0:
        levels.append(
            {"title": "ST STOP", "price": st_stop, "color": "#6FA4FF", "style": 3}
        )

    candles_json = json.dumps(candles)
    volume_json = json.dumps(volume)
    levels_json = json.dumps([lvl for lvl in levels if lvl["price"] is not None])
    clean_ticker = (ticker or "").strip().upper()

    return f"""
<details class="panelbox chart-expander" style="margin-top:20px;padding:0;">
  <summary style="padding:14px 20px;cursor:pointer;list-style:none;outline:none;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;user-select:none;">
    <h3 style="margin:0;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:800;text-align:center;">PIVOT & PRICE ACTION CHART</h3>
    <div id="chart-legend" style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted);text-align:center;margin-top:4px;">
      Hover over chart to view OHLC & Volume
    </div>
  </summary>
  <div style="padding:0 20px 18px 20px;border-top:1px solid var(--line);">
    <div id="tv-chart" style="width:100%;height:360px;position:relative;background:#0A0E17;border-radius:10px;margin-top:16px;"></div>
  </div>
</details>

<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<script>
(function() {{
  const container = document.getElementById('tv-chart');
  const legend = document.getElementById('chart-legend');
  if (!container) return;
  
  const layoutBg = (window.LightweightCharts && LightweightCharts.ColorType && LightweightCharts.ColorType.Solid)
    ? {{ background: {{ type: LightweightCharts.ColorType.Solid, color: '#0A0E17' }} }}
    : {{ backgroundColor: '#0A0E17' }};

  const chartOpts = Object.assign({{
    width: container.clientWidth || 900,
    height: 360,
    grid: {{
      vertLines: {{ color: 'rgba(30, 44, 72, 0.35)' }},
      horzLines: {{ color: 'rgba(30, 44, 72, 0.35)' }},
    }},
    crosshair: {{
      mode: 0,
      vertLine: {{ color: 'rgba(111, 164, 255, 0.4)', labelBackgroundColor: '#111A30' }},
      horzLine: {{ color: 'rgba(111, 164, 255, 0.4)', labelBackgroundColor: '#111A30' }},
    }},
    rightPriceScale: {{
      borderColor: '#1E2C48',
      scaleMargins: {{ top: 0.1, bottom: 0.25 }},
    }},
    timeScale: {{
      borderColor: '#1E2C48',
      timeVisible: false,
      secondsVisible: false,
    }},
  }}, layoutBg);

  chartOpts.layout = Object.assign({{
    textColor: '#7E8DA8',
    fontFamily: "'IBM Plex Mono', monospace",
    fontSize: 11,
  }}, layoutBg);

  const chart = LightweightCharts.createChart(container, chartOpts);

  const addCandles = chart.addCandlestickSeries ? chart.addCandlestickSeries.bind(chart) : (opts) => chart.addSeries(LightweightCharts.CandlestickSeries, opts);
  const addHistogram = chart.addHistogramSeries ? chart.addHistogramSeries.bind(chart) : (opts) => chart.addSeries(LightweightCharts.HistogramSeries, opts);

  const candleSeries = addCandles({{
    upColor: '#2EE6C8',
    downColor: '#FF6B6B',
    borderUpColor: '#2EE6C8',
    borderDownColor: '#FF6B6B',
    wickUpColor: '#2EE6C8',
    wickDownColor: '#FF6B6B',
  }});
  candleSeries.setData({candles_json});

  const volumeSeries = addHistogram({{
    priceFormat: {{ type: 'volume' }},
    priceScaleId: 'volume',
  }});
  if (chart.priceScale) {{
    chart.priceScale('volume').applyOptions({{
      scaleMargins: {{ top: 0.75, bottom: 0 }},
    }});
  }}
  volumeSeries.setData({volume_json});

  const levels = {levels_json};
  levels.forEach(lvl => {{
    candleSeries.createPriceLine({{
      price: lvl.price,
      color: lvl.color,
      lineWidth: 1,
      lineStyle: lvl.style,
      axisLabelVisible: true,
      title: lvl.title,
    }});
  }});

  chart.subscribeCrosshairMove(param => {{
    if (!param || !param.time || !param.seriesData || !legend) {{
      if (legend) legend.innerHTML = 'Hover over chart to view OHLC & Volume';
      return;
    }}
    const candle = param.seriesData.get(candleSeries);
    const vol = param.seriesData.get(volumeSeries);
    if (!candle) return;

    let timeStr = '';
    if (typeof param.time === 'string') {{
      timeStr = param.time;
    }} else if (typeof param.time === 'object' && param.time !== null) {{
      timeStr = param.time.year + '-' + String(param.time.month).padStart(2, '0') + '-' + String(param.time.day).padStart(2, '0');
    }} else if (typeof param.time === 'number') {{
      const d = new Date(param.time * 1000);
      timeStr = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }}
    const volVal = (vol && vol.value !== undefined) ? Number(vol.value).toLocaleString('en-IN') : '—';
    const cColor = candle.close >= candle.open ? '#2EE6C8' : '#FF6B6B';

    legend.innerHTML = `
      <span style="color:var(--text);font-weight:700;">${{timeStr}}</span> · 
      O: <b style="color:${{cColor}}">₹${{candle.open.toFixed(2)}}</b> 
      H: <b style="color:${{cColor}}">₹${{candle.high.toFixed(2)}}</b> 
      L: <b style="color:${{cColor}}">₹${{candle.low.toFixed(2)}}</b> 
      C: <b style="color:${{cColor}}">₹${{candle.close.toFixed(2)}}</b> · 
      Vol: <b style="color:var(--text)">${{volVal}}</b>
    `;
  }});

  const storageKey = 'pivotdesk_chart_range_' + ('{clean_ticker}' || 'default');
  const openKey = 'pivotdesk_chart_open_' + ('{clean_ticker}' || 'default');

  function restoreVisibleRange() {{
    try {{
      const savedRangeStr = sessionStorage.getItem(storageKey);
      if (savedRangeStr) {{
        const savedRange = JSON.parse(savedRangeStr);
        if (savedRange && savedRange.from !== undefined && savedRange.to !== undefined) {{
          chart.timeScale().setVisibleLogicalRange(savedRange);
          return true;
        }}
      }}
    }} catch(e) {{}}
    return false;
  }}

  const detailsEl = container.closest('details');
  if (detailsEl) {{
    const savedOpen = sessionStorage.getItem(openKey);
    if (savedOpen === 'true') {{
      detailsEl.open = true;
    }} else if (savedOpen === 'false') {{
      detailsEl.open = false;
    }}

    detailsEl.addEventListener('toggle', () => {{
      sessionStorage.setItem(openKey, detailsEl.open ? 'true' : 'false');
      if (detailsEl.open) {{
        setTimeout(() => {{
          chart.applyOptions({{ width: container.clientWidth || 900 }});
          if (!restoreVisibleRange()) {{
            chart.timeScale().fitContent();
          }}
        }}, 50);
      }}
    }});
  }}

  // Restore saved view state on load
  restoreVisibleRange();

  // Persist zoom and pan state to sessionStorage
  chart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
    if (range) {{
      try {{
        sessionStorage.setItem(storageKey, JSON.stringify(range));
      }} catch(e) {{}}
    }}
  }});

  window.addEventListener('resize', () => {{
    if (!detailsEl || detailsEl.open) {{
      chart.applyOptions({{ width: container.clientWidth }});
    }}
  }});
}})();
</script>
"""
