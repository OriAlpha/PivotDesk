"""PivotDesk — the HTML/CSS page templates for the dashboard iframe.

Two ``string.Template`` strings: ``HTML`` for the live dashboard and
``HTML_ERROR`` for the fetch-failed fallback. ``render()`` and
``render_error()`` in :mod:`rendering` substitute values into them.

The full set of placeholders is pinned by ``tests/test_render_smoke.py`` —
``Template.safe_substitute`` leaves an unknown ``$name`` in the page rather
than raising, so a placeholder added to a template but dropped from the
substitute call would silently leak. The smoke test guards against that.
"""

from string import Template

HTML = Template(
    r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>$name — PivotDesk</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0A0E17;--panel:rgba(20,29,48,.72);--line:#1E2C48;--text:#EDF2FB;--muted:#7E8DA8;
--dim:#55637E;--pp:#FFC53D;--res:#FF6B6B;--sup:#2EE6C8;--price:#6FA4FF}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);
color:var(--text);font-family:'Archivo',sans-serif}
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
.sigchips{display:flex;flex-wrap:wrap;gap:5px;justify-content:center;margin-top:10px}
.sigchips span{font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:700;
padding:3px 8px;border-radius:99px;border:1px solid;letter-spacing:.04em;white-space:nowrap}
.sigchips span.on{color:var(--sup);border-color:rgba(46,230,200,.35);background:rgba(46,230,200,.07)}
.sigchips span.off{color:var(--res);border-color:rgba(255,107,107,.30);background:rgba(255,107,107,.06)}
.conf{font-size:11px;color:var(--dim);margin-top:9px;font-weight:600;line-height:1.4}
.conf b{font-weight:800}
.acard{border:1px solid var(--line);border-radius:16px;padding:16px 22px;text-align:center;margin-bottom:16px;background:var(--panel)}
.acard.up{border-color:rgba(46,230,200,.4);background:linear-gradient(180deg,rgba(46,230,200,.05),transparent 62%),var(--panel)}
.acard.warn{border-color:rgba(255,197,61,.4);background:linear-gradient(180deg,rgba(255,197,61,.05),transparent 62%),var(--panel)}
.acard.dn{border-color:rgba(255,107,107,.4);background:linear-gradient(180deg,rgba(255,107,107,.05),transparent 62%),var(--panel)}
.acard .k{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:800;margin-bottom:6px}
.asum{font-size:17.5px;font-weight:800;line-height:1.4;color:var(--text);max-width:640px;margin:0 auto}
.asum .em{margin-right:8px}
.ameta{display:flex;gap:16px;justify-content:center;flex-wrap:wrap;margin-top:14px;font-size:12px;color:var(--muted);font-family:'IBM Plex Mono',monospace}
.ameta b{color:var(--text);font-weight:600}
.atag{margin-top:11px;font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--dim);font-weight:700}
.movectx{font-size:11.5px;color:var(--dim);margin-top:7px;font-weight:600}
.movectx b{color:var(--muted);font-weight:700}
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
$move_ctx
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
$action_card
<div class="verdict">
<div class="vcard"><div class="k">Technical bias</div>
<div class="big $bias_cls">$bias_label</div>
<div class="sub2">$bias_n/6 signals bullish$bias_caution</div>
<div class="sigchips">$bias_chips</div>
$bias_confidence</div>
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
</div></div></div>
$chart_html
<div class="read">$read</div>
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
</div></body></html>"""
)
