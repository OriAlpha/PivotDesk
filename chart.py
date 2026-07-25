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

    return f"""
<div class="panelbox" style="margin-top:20px;padding:16px 20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
    <h3 style="margin-bottom:0;">📈 Pivot & Price Action Chart</h3>
    <div id="chart-legend" style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted);">
      Hover over chart to view OHLC & Volume
    </div>
  </div>
  <div id="tv-chart" style="width:100%;height:360px;position:relative;background:#0A0E17;border-radius:10px;"></div>
</div>

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
    width: container.clientWidth,
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
      timeVisible: true,
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

    let timeStr = param.time;
    if (typeof param.time === 'object' && param.time !== null) {{
      timeStr = param.time.year + '-' + String(param.time.month).padStart(2, '0') + '-' + String(param.time.day).padStart(2, '0');
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

  window.addEventListener('resize', () => {{
    chart.applyOptions({{ width: container.clientWidth }});
  }});
}})();
</script>
"""
