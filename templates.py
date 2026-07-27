"""PivotDesk — the HTML/CSS page templates for the dashboard iframe.

Two ``string.Template`` strings: ``HTML`` for the live dashboard and
``HTML_ERROR`` for the fetch-failed fallback. ``render()`` and
``render_error()`` in :mod:`rendering` substitute values into them.

The full set of placeholders is pinned by ``tests/test_render_smoke.py`` —
``Template.safe_substitute`` leaves an unknown ``$name`` in the page rather
than raising, so a placeholder added to a template but dropped from the
substitute call would silently leak. The smoke test guards against that.
"""

import json
from string import Template


def js_literal(value: str) -> str:
    """Encode *value* as a JS string literal for an inline ``<script>``.

    ``json.dumps`` on its own is not enough. The HTML parser looks for
    ``</script>`` without regard for JavaScript quoting, so a ticker
    containing one would end the block early and spill the rest onto the
    page as markup; escaping the slash keeps it inside the string.
    """
    return json.dumps(value).replace("</", "<\\/")


# Streamlit gives the iframe a fixed height, which clips whatever the page
# grows past it. Match the frame to the content instead, so the outer page
# scrolls as one and nothing at the bottom is cut off. Shared by both
# templates — the error page can overflow 350px just as easily.
_AUTO_HEIGHT_JS = """
(function() {
  let frame = null;
  try { frame = window.frameElement; } catch (err) {}
  if (!frame) {
    document.documentElement.style.overflowY = 'auto';
    return;
  }

  let applied = 0;
  function syncHeight() {
    // Measured off the body box, not scrollHeight: scrollHeight never reports
    // less than the viewport, so it would ratchet up and never shrink back
    // when focus mode or a collapsed chart removes content.
    const h = Math.ceil(document.body.getBoundingClientRect().height);
    if (h > 0 && h !== applied) {
      applied = h;
      frame.style.setProperty('height', h + 'px', 'important');
    }
  }

  // Re-measure after the layout settles as well as immediately: the chart
  // sizes itself a beat after its <details> opens.
  function syncSoon() {
    syncHeight();
    setTimeout(syncHeight, 150);
  }
  window.syncFrameHeight = syncSoon;

  syncHeight();
  window.addEventListener('load', syncHeight);
  // 'toggle' does not bubble, so the chart expander needs capture.
  document.addEventListener('toggle', syncSoon, true);
  const observer = window.ResizeObserver ? new ResizeObserver(syncHeight) : null;
  if (observer) observer.observe(document.body);
  // Web fonts and the chart library both settle after first paint.
  [100, 400, 1200].forEach(ms => setTimeout(syncHeight, ms));
})();
"""


HTML = Template(
    r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>$name — PivotDesk</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0A0E17;--panel:rgba(20,29,48,.72);--line:#1E2C48;--text:#EDF2FB;--muted:#7E8DA8;
--dim:#55637E;--pp:#FFC53D;--res:#FF6B6B;--sup:#2EE6C8;--price:#6FA4FF}
*{box-sizing:border-box;margin:0;padding:0}
html, body{background:var(--bg);color:var(--text);font-family:'Archivo',sans-serif;overflow-y:hidden}
.mono{font-family:'IBM Plex Mono',monospace}
.wrap{max-width:980px;margin:0 auto;padding:10px 16px 28px}
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
.spectrum{position:relative;margin:0 8px 56px;height:114px}
.tick[data-tip]{position:absolute;cursor:pointer}
.tick[data-tip]:hover::after{content:attr(data-tip);position:absolute;top:100%;left:50%;transform:translateX(-50%);background:#0D1527;border:1px solid var(--price);color:var(--text);padding:5px 11px;border-radius:6px;font-size:10.5px;white-space:nowrap;z-index:9999;pointer-events:none;box-shadow:0 6px 16px rgba(0,0,0,.8);margin-top:28px;font-family:'IBM Plex Mono',monospace}
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
.returns{display:flex;gap:8px;justify-content:center;align-items:center;flex-wrap:wrap;margin-bottom:30px}
.ret{background:var(--panel);border:1px solid var(--line);border-radius:99px;padding:6px 14px;font-size:12.5px;transition:all 0.2s ease;cursor:default;display:inline-flex;align-items:center}
.ret:hover{background:rgba(255,255,255,.05);border-color:rgba(111,164,255,.35);box-shadow:0 0 12px rgba(111,164,255,.2);transform:translateY(-1px)}
.ret span{color:var(--dim);font-weight:800;margin-right:7px}
.ret .sc-badge{margin-top:0;margin-left:6px}
.verdict{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
@media(max-width:760px){.verdict{grid-template-columns:1fr}}
.vcard{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 20px;text-align:center;display:flex;flex-direction:column;justify-content:center;align-items:center;height:100%;transition:all 0.25s ease}
.vcard:hover{border-color:rgba(111,164,255,.25);box-shadow:0 8px 24px rgba(0,0,0,.3)}
.vcard .k{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:800;margin-bottom:8px}
.vcard .big{font-size:24px;font-weight:800}
.vcard .sub2{font-size:12px;color:var(--muted);margin-top:5px;font-weight:600;text-align:center}
.sigchips{display:flex;flex-wrap:wrap;gap:5px;justify-content:center;margin-top:10px}
.sigchips span{font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:700;
padding:3px 8px;border-radius:99px;border:1px solid;letter-spacing:.04em;white-space:nowrap;transition:all 0.2s ease}
.sigchips span.on{color:var(--sup);border-color:rgba(46,230,200,.35);background:rgba(46,230,200,.07)}
.sigchips span.off{color:var(--res);border-color:rgba(255,107,107,.30);background:rgba(255,107,107,.06)}
.conf{font-size:11px;color:var(--dim);margin-top:9px;font-weight:600;line-height:1.4}
.conf b{font-weight:800}
.acard{border:1px solid var(--line);border-radius:16px;padding:16px 22px;text-align:center;margin-bottom:16px;background:var(--panel);transition:all 0.25s ease}
.acard.up{border-color:rgba(46,230,200,.4);background:linear-gradient(180deg,rgba(46,230,200,.05),transparent 62%),var(--panel)}
.acard.warn{border-color:rgba(255,197,61,.4);background:linear-gradient(180deg,rgba(255,197,61,.05),transparent 62%),var(--panel)}
.acard.dn{border-color:rgba(255,107,107,.4);background:linear-gradient(180deg,rgba(255,107,107,.05),transparent 62%),var(--panel)}
.acard:hover{box-shadow:0 8px 28px rgba(0,0,0,.35);border-color:rgba(111,164,255,.35)}
.acard .k{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:800;margin-bottom:6px}
.asum{font-size:17.5px;font-weight:800;line-height:1.4;color:var(--text);max-width:640px;margin:0 auto}
.asum .em{margin-right:8px}
.ameta{display:flex;gap:16px;justify-content:center;flex-wrap:wrap;margin-top:14px;font-size:12px;color:var(--muted);font-family:'IBM Plex Mono',monospace}
.ameta b{color:var(--text);font-weight:600}
.atag{margin-top:11px;font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--dim);font-weight:700}
.movectx{font-size:11.5px;color:var(--dim);margin-top:7px;font-weight:600}
.movectx b{color:var(--muted);font-weight:700}
.grid{display:grid;grid-template-columns:340px 1fr;gap:16px;align-items:stretch}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
.panelbox{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 20px;display:flex;flex-direction:column;transition:all 0.25s ease}
.panelbox:hover{border-color:rgba(111,164,255,.2);box-shadow:0 8px 24px rgba(0,0,0,.25)}
.panelbox h3{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:800;margin-bottom:13px;text-align:center}
.chart-expander summary::-webkit-details-marker,.chart-expander summary::marker{display:none !important;content:"" !important}
.chart-expander summary{list-style:none !important;transition:background-color 0.2s ease;border-radius:16px}
.chart-expander summary:hover{background-color:rgba(255,255,255,.03)}
.lrow{display:flex;align-items:center;justify-content:space-between;padding:9px 2px;border-bottom:1px solid var(--line)}
.lrow:last-child{border-bottom:0}
.lrow .nm{font-size:13px;font-weight:800;display:flex;gap:10px;align-items:center}
.chip{width:8px;height:8px;border-radius:3px}
.lrow .v{font-size:15.5px;font-weight:600}
.lr-r .chip{background:var(--res)}.lr-r .v{color:var(--res)}
.lr-p .chip{background:var(--pp)}.lr-p .v{color:var(--pp)}
.lr-s .chip{background:var(--sup)}.lr-s .v{color:var(--sup)}
.lr-w .nm,.lr-w .v{color:var(--dim)}
.sgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;flex:1}
@media(max-width:560px){.sgrid{grid-template-columns:1fr 1fr}}
.sc{background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:12px;padding:14px 13px;text-align:center;display:flex;flex-direction:column;justify-content:center;transition:all 0.2s ease}
.sc:hover{background:rgba(255,255,255,.05);border-color:rgba(111,164,255,.3)}
.sc .k{font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:var(--dim);font-weight:800;margin-bottom:6px}
.sc .v{font-size:17px;font-weight:800}
.sc .s{font-size:10.5px;color:var(--muted);margin-top:4px;font-weight:600}
.sc-badge{display:inline-block;padding:2px 7px;border-radius:99px;font-size:9.5px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;margin-top:5px;align-self:center}
.sc-badge.up{background:rgba(46,230,200,.12);color:var(--sup);border:1px solid rgba(46,230,200,.3);box-shadow:0 0 8px rgba(46,230,200,.2)}
.sc-badge.dn{background:rgba(255,107,107,.12);color:var(--res);border:1px solid rgba(255,107,107,.3);box-shadow:0 0 8px rgba(255,107,107,.2)}
.sc-badge.warn{background:rgba(255,197,61,.12);color:var(--pp);border:1px solid rgba(255,197,61,.3);box-shadow:0 0 8px rgba(255,197,61,.2)}
.score-gauge{display:flex;gap:4px;justify-content:center;margin:6px 0 8px}
.score-gauge .dot-seg{width:22px;height:4px;border-radius:99px;background:rgba(255,255,255,.1);transition:all 0.3s ease}
.copy-btn{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--muted);border-radius:6px;padding:4px 12px;font-size:10.5px;font-weight:700;cursor:pointer;font-family:'IBM Plex Mono',monospace;transition:all 0.2s ease}
.copy-btn:hover{background:rgba(111,164,255,.15);border-color:var(--price);color:var(--price)}
.score-gauge .dot-seg.active.up{background:var(--sup);box-shadow:0 0 8px rgba(46,230,200,.6)}
.score-gauge .dot-seg.active.warn{background:var(--pp);box-shadow:0 0 8px rgba(255,197,61,.6)}
.score-gauge .dot-seg.active.dn{background:var(--res);box-shadow:0 0 8px rgba(255,107,107,.6)}
.rc{background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:12px;
padding:11px 16px;margin-bottom:9px;display:flex;align-items:center;justify-content:space-between;flex:1;transition:all 0.2s ease}
.rc:hover{background:rgba(255,255,255,.05);border-color:rgba(111,164,255,.3)}
.rc:last-child{margin-bottom:0}
.rc .k{font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:var(--dim);font-weight:800}
.rc .v{font-size:16px;font-weight:800;color:var(--text)}
.up{color:var(--sup)}.dn{color:var(--res)}.warn{color:var(--pp)}
.read{margin-top:18px;border-top:1px solid var(--line);padding-top:12px;text-align:center;font-size:10px;color:var(--dim);letter-spacing:.06em}
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
.focus-btn{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--muted);border-radius:99px;padding:3px 10px;font-size:10.5px;font-weight:700;cursor:pointer;font-family:'IBM Plex Mono',monospace;transition:all 0.2s ease;margin-left:8px}
.focus-btn:hover{background:rgba(111,164,255,.15);border-color:var(--price);color:var(--price)}
@media(max-width:480px){
  .wrap{padding:10px 8px 20px}
  .top{flex-direction:column;gap:8px;text-align:center}
  .hero .px{font-size:42px}
  .tick .val{font-size:9.5px;bottom:-18px}
  .tick .lab{font-size:10px;top:-18px}
  .marker .tag{font-size:11px;padding:3px 6px}
}
</style>
<script>
window.FOCUS_KEY = 'pivotdesk_focus';
window.FOCUS_CHANNEL = 'pivotdesk_focus_channel';
// Below this the layout is already single-column, so the page is long enough
// that focus mode earns its keep. Matches the .grid/.verdict media query.
window.FOCUS_NARROW = '(max-width: 760px)';

window.setFocusMode = function(isFocus) {
  if (!document.body) return;
  document.body.classList.toggle('focus-active', isFocus);
  document.documentElement.classList.toggle('focus-active', isFocus);
  const wrap = document.querySelector('.wrap');
  if (wrap) wrap.classList.toggle('focus-active', isFocus);

  const targets = document.querySelectorAll('.verdict, .grid');
  targets.forEach(el => {
    el.style.display = isFocus ? 'none' : '';
  });

  const btn = document.querySelector('.focus-btn');
  if (btn) {
    if (isFocus) {
      btn.innerText = '👁️ Full Mode';
      btn.style.borderColor = 'var(--price)';
      btn.style.color = 'var(--price)';
      btn.style.background = 'rgba(111,164,255,.2)';
    } else {
      btn.innerText = '👁️ Focus Mode';
      btn.style.borderColor = 'var(--line)';
      btn.style.color = 'var(--muted)';
      btn.style.background = 'rgba(255,255,255,.05)';
    }
  }

  if (window.syncFrameHeight) window.syncFrameHeight();
  // The chart measures itself on resize; it cannot do that while hidden, so
  // nudge it once it is back on screen.
  if (!isFocus) {
    setTimeout(() => window.dispatchEvent(new Event('resize')), 60);
  }
};

window.toggleFocusMode = function() {
  const isFocus = !(document.body && document.body.classList.contains('focus-active'));
  window.setFocusMode(isFocus);
  // Remember the choice: the dashboard fragment rebuilds this page every 60s.
  try { sessionStorage.setItem(window.FOCUS_KEY, isFocus ? 'on' : 'off'); } catch (err) {}
  // The chart lives in a sibling frame that this document cannot reach into,
  // so tell it directly rather than through the DOM.
  try { new BroadcastChannel(window.FOCUS_CHANNEL).postMessage({ focus: isFocus }); } catch (err) {}
};

document.addEventListener('click', function(e) {
  if (e.target) {
    const focusBtn = e.target.closest('.focus-btn');
    if (focusBtn) {
      e.preventDefault();
      window.toggleFocusMode();
      return;
    }
    const copyBtn = e.target.closest('.copy-btn');
    if (copyBtn) {
      e.preventDefault();
      if (window.copyTradePlan) window.copyTradePlan();
      return;
    }
  }
});
</script>
</head><body><div class="wrap">
<div class="top"><div class="brand">Pivot<em>Desk</em></div>
<div class="mkt"><a href="$reload_url" target="_parent" class="reload-lnk $reload_cls">🔄 Reload</a><button type="button" class="focus-btn">👁️ Focus Mode</button><span class="dot"></span><span class="mono">$mkt_label</span></div></div>
<div class="hero"><h1>$name</h1>
<div class="sub mono">Prev: H $ph · L $pl · C $pc</div>
$exp_range_html
<div class="px mono $px_cls">₹$price</div>
$chg_html
$move_ctx
$day_range_html
$vol_spike_html
</div>
$data_banner
<div class="spectrum">
<div class="band"></div>
<div class="tick t-s2" data-tip="S2 ₹$s2 · Support 2 Zone"><span class="lab">S2</span><span class="val mono">$s2</span></div>
<div class="tick t-s1" data-tip="S1 ₹$s1 · Support 1 Zone"><span class="lab">S1</span><span class="val mono">$s1</span></div>
<div class="tick t-pp" data-tip="PP ₹$pp · Intraday Pivot Baseline"><span class="lab">PP</span><span class="val mono">$pp</span></div>
<div class="tick t-r1" data-tip="R1 ₹$r1 · Resistance 1 Target"><span class="lab">R1</span><span class="val mono">$r1</span></div>
<div class="tick t-r2" data-tip="R2 ₹$r2 · Resistance 2 Target"><span class="lab">R2</span><span class="val mono">$r2</span></div>
<div class="marker"><span class="tag mono">$price</span><div class="stem"></div></div>
</div>
<div class="returns">$returns_html
<span class="ret"><span>52W</span><b class="mono" style="color:var(--pp)">$rng_pct% of range</b>$rng_badge</span></div>
$action_card
<div class="verdict">
<div class="vcard"><div class="k">Technical bias</div>
<div class="big $bias_cls">$bias_label</div>
$score_gauge
<div class="sub2">$bias_n/6 signals bullish$bias_caution</div>
<div class="sigchips">$bias_chips</div>
$mtf_badge
$bias_confidence</div>
$pos_card
</div>
<div class="grid">
<div class="panelbox"><h3>Reference</h3>
<div class="rc"><span class="k">Prev High</span><span class="v mono">₹$ph$ph_tag</span></div>
<div class="rc"><span class="k">Prev Low</span><span class="v mono">₹$pl$pl_tag</span></div>
<div class="rc"><span class="k">Prev Close</span><span class="v mono">₹$pc</span></div>
<div class="rc"><span class="k">Weekly PP</span><span class="v mono">₹$wpp</span></div></div>
<div class="panelbox"><h3>Swing view</h3><div class="sgrid">
<div class="sc"><div class="k">MAs 20·50·200</div><div class="v $ma_cls">$ma_v</div><div class="s">$ma_s</div></div>
<div class="sc"><div class="k">RSI 14</div><div class="v $rsi_cls">$rsi_v</div><div class="s">$rsi_s</div></div>
<div class="sc"><div class="k">MACD</div><div class="v $macd_cls">$macd_v</div><div class="s">$macd_s</div></div>
<div class="sc"><div class="k">Supertrend</div><div class="v $st_cls">$st_v</div><div class="s">stop ₹$st_stop</div></div>
<div class="sc"><div class="k">ATR 14</div><div class="v mono">₹$atr_v</div><div class="s">≈$atr_pct% per day</div></div>
<div class="sc"><div class="k">Vol vs 30D</div><div class="v $vol_cls">$vol_v×</div><div class="s">$vol_s</div></div>
</div></div></div>
</div>
<script>
window.copyTradePlan = function() {
  const asum = document.querySelector('.asum');
  const metaSpans = document.querySelectorAll('.ameta span');
  const txts = [];
  if (asum) txts.push(asum.innerText.trim());
  metaSpans.forEach(s => {
    const t = s.innerText.trim();
    if (t) txts.push(t);
  });
  const copyText = txts.join(' · ');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(copyText).then(() => {
      const btn = document.querySelector('.copy-btn');
      if (btn) {
        const orig = btn.innerText;
        btn.innerText = '✅ Copied to Clipboard!';
        setTimeout(() => btn.innerText = orig, 2200);
      }
    });
  }
};

(function() {
  const symbol = $symbol_js || "stock";
  const storageKey = "pivotdesk_position_" + symbol;

  document.addEventListener('change', (e) => {
    if (e.target && e.target.form) {
      const form = e.target.form;
      const entryInput = form.querySelector('input[name="entry"]');
      const qtyInput = form.querySelector('input[name="qty"]');
      const riskInput = form.querySelector('input[name="risk"]');
      if (entryInput || qtyInput || riskInput) {
        const data = {
          entry: entryInput ? entryInput.value : '',
          qty: qtyInput ? qtyInput.value : '',
          risk: riskInput ? riskInput.value : ''
        };
        try { localStorage.setItem(storageKey, JSON.stringify(data)); } catch(err) {}
      }
    }
  });

  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      const data = JSON.parse(saved);
      const entryInput = document.querySelector('input[name="entry"]');
      const qtyInput = document.querySelector('input[name="qty"]');
      const riskInput = document.querySelector('input[name="risk"]');
      if (entryInput && (!entryInput.value || entryInput.value === '0.00')) entryInput.value = data.entry || '';
      if (qtyInput && (!qtyInput.value || qtyInput.value === '0')) qtyInput.value = data.qty || '';
      if (riskInput && (!riskInput.value || riskInput.value === '5.0')) riskInput.value = data.risk || '';
    }
  } catch(err) {}
})();

// Phones start focused — the full page is a long scroll on a small screen —
// while desktops start with everything on show. An explicit toggle wins over
// the device default for the rest of the tab's session.
(function() {
  const mq = window.matchMedia ? window.matchMedia(window.FOCUS_NARROW) : null;

  function wanted() {
    let saved = null;
    try { saved = sessionStorage.getItem(window.FOCUS_KEY); } catch (err) {}
    if (saved !== null) return saved === 'on';
    return mq ? mq.matches : document.documentElement.clientWidth <= 760;
  }

  function applyDefault() { window.setFocusMode(wanted()); }

  applyDefault();
  // The frame is still at its unlaid-out width when this first runs, so a
  // desktop briefly measures as narrow. Re-check once the layout settles, and
  // whenever the breakpoint is crossed while no explicit choice is stored.
  window.addEventListener('load', applyDefault);
  if (mq && mq.addEventListener) mq.addEventListener('change', applyDefault);
})();

__AUTO_HEIGHT_JS__

window.addEventListener('keydown', (e) => {
  if (e.key === 'r' || e.key === 'R') {
    if (document.activeElement && (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA')) {
      return;
    }
    e.preventDefault();
    const reloadBtn = document.querySelector('.reload-lnk');
    if (reloadBtn) reloadBtn.click();
  }
});
</script>
</body></html>""".replace("__AUTO_HEIGHT_JS__", _AUTO_HEIGHT_JS)
)

CHART_PAGE = Template(
    r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0A0E17;--panel:rgba(20,29,48,.72);--line:#1E2C48;--text:#EDF2FB;--muted:#7E8DA8;
--dim:#55637E;--pp:#FFC53D;--res:#FF6B6B;--sup:#2EE6C8;--price:#6FA4FF}
*{box-sizing:border-box;margin:0;padding:0}
html, body{background:var(--bg);color:var(--text);font-family:'Archivo',sans-serif;overflow-y:hidden}
.mono{font-family:'IBM Plex Mono',monospace}
.wrap{max-width:980px;margin:0 auto;padding:0 16px 28px}
.panelbox{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 20px;display:flex;flex-direction:column;transition:all 0.25s ease}
.panelbox:hover{border-color:rgba(111,164,255,.2);box-shadow:0 8px 24px rgba(0,0,0,.25)}
.panelbox h3{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:800;margin-bottom:13px;text-align:center}
.chart-expander summary::-webkit-details-marker,.chart-expander summary::marker{display:none !important;content:"" !important}
.chart-expander summary{list-style:none !important;transition:background-color 0.2s ease;border-radius:16px}
.chart-expander summary:hover{background-color:rgba(255,255,255,.03)}
.read{margin-top:18px;border-top:1px solid var(--line);padding-top:12px;text-align:center;font-size:10px;color:var(--dim);letter-spacing:.06em}
</style>
</head><body><div class="wrap">
$chart_html
<div class="read mono">$read · $visit_count views</div>
</div>
<script>
// The chart is a sibling frame of the dashboard, so focus mode reaches it by
// broadcast rather than through the DOM. Only the chart hides — the
// attribution footer below it is the last thing on the page either way.
(function() {
  const KEY = 'pivotdesk_focus';
  const details = document.querySelector('.chart-expander');

  function apply(isFocus) {
    if (details) details.style.display = isFocus ? 'none' : '';
    if (window.syncFrameHeight) window.syncFrameHeight();
  }

  const mq = window.matchMedia ? window.matchMedia('(max-width: 760px)') : null;

  function stored() {
    let saved = null;
    try { saved = sessionStorage.getItem(KEY); } catch (err) {}
    if (saved !== null) return saved === 'on';
    return mq ? mq.matches : document.documentElement.clientWidth <= 760;
  }

  function applyStored() { apply(stored()); }

  applyStored();
  // Same width race as the dashboard frame: measure again after layout.
  window.addEventListener('load', applyStored);
  if (mq && mq.addEventListener) mq.addEventListener('change', applyStored);

  try {
    const channel = new BroadcastChannel('pivotdesk_focus_channel');
    channel.onmessage = (e) => {
      if (e.data && typeof e.data.focus === 'boolean') apply(e.data.focus);
    };
  } catch (err) {}
  // Backstop for browsers without BroadcastChannel: sessionStorage writes
  // raise 'storage' in every same-origin document except the writer.
  window.addEventListener('storage', (e) => {
    if (!e.key || e.key === KEY) apply(stored());
  });
})();

__AUTO_HEIGHT_JS__
</script>
</body></html>""".replace("__AUTO_HEIGHT_JS__", _AUTO_HEIGHT_JS)
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
.wrap{max-width:980px;margin:0 auto;padding:10px 16px 28px}
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
</div>
<script>
__AUTO_HEIGHT_JS__
</script>
</body></html>""".replace("__AUTO_HEIGHT_JS__", _AUTO_HEIGHT_JS)
)
