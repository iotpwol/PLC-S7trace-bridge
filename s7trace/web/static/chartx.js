"use strict";
// Chart tools shared by the live chart and the recording view (the counterparts of the desktop program):
//  - "Znacznik poziomu sygnału" = cursors H1/H2 (value in the lane under the line, ΔY),
//  - the time axis of the chart: seconds from the start (as before) or a clock HH:MM:SS.mmm of the server / the PLC with a +- offset,
//  - zoom with Ctrl + mouse wheel, pan by dragging, Shift + drag = zoom to the selected range,
//  - overview strip of the whole data with the shown range (drag it, click to centre, drag an edge to resize),
//  - "Punkty" (sample points) and the chart layout (lanes by Share / offset Y + gain) for this viewer.
// cfg = { range(): [t0, t1], limits(): [lo, hi], setRange(a, b), redraw(), busy(): marker placement / drag in progress,
//         overview: { cv, ds(): data of the whole range } | null, defaults(): { layout, auto_y, y_min, y_max, show_points } }
const CX_MIN_WINDOW = 0.1;
const CX_NUM = (v) => String(+(+v).toPrecision(5));

function cxAttach(cv, cfg) {
  const st = cv._cx = { hOn: false, h: [], layout: "", legend: "", taxis: "", toff: null, points: null, cfg, drag: null, pan: null };
  const px = (ev) => { const r = cv.getBoundingClientRect(); return [(ev.clientX - r.left) * cv.width / r.width, (ev.clientY - r.top) * cv.height / r.height]; };
  const geo = () => cv._geo;
  const tAt = (x) => { const g = geo(); return g.t0 + Math.min(Math.max((x - g.pad.l) / (g.W - g.pad.l - g.pad.r), 0), 1) * (g.t1 - g.t0); };
  const xOf = (t) => { const g = geo(); return g.pad.l + (t - g.t0) / ((g.t1 - g.t0) || 1) * (g.W - g.pad.l - g.pad.r); };
  const yOf = (f) => { const g = geo(); return g.pad.t + f * (g.H - g.pad.t - g.pad.b); };
  const clampRange = (a, b) => {
    const [lo, hi] = cfg.limits(); let w = Math.max(b - a, CX_MIN_WINDOW);
    if (w >= hi - lo) return [lo, Math.max(hi, lo + CX_MIN_WINDOW)];
    a = Math.min(Math.max(a, lo), hi - w); return [a, a + w];
  };
  const hit = (x, y) => {                                    // a cursor line under the mouse
    const g = geo(), tol = 6 * cv.width / cv.getBoundingClientRect().width;
    for (let i = 0; i < st.h.length; i++) if (Math.abs(yOf(st.h[i]) - y) <= tol) return { kind: "h", i };
    return null;
  };
  cv.addEventListener("mousedown", (e) => {
    if (e.button !== 0 || !geo()) return;
    const [x, y] = px(e), h = hit(x, y);
    if (h) { e.stopImmediatePropagation(); e.preventDefault(); st.drag = h; return; }
    if (cfg.busy()) return;
    st.pan = { x0: x, r: cfg.range(), moved: false, shift: e.shiftKey, lim: cfg.limits() };   // (a marker under the mouse starts its own drag; busy() tells)
  }, true);
  window.addEventListener("mousemove", (e) => {
    if (st.drag) {
      const [x, y] = px(e), g = geo(); if (!g) return;
      st.h[st.drag.i] = Math.min(Math.max((y - g.pad.t) / (g.H - g.pad.t - g.pad.b), 0), 1);
      cfg.redraw(); return;
    }
    const p = st.pan; if (!p || !geo()) return;
    const [x] = px(e), g = geo();
    if (Math.abs(x - p.x0) > 3) p.moved = true;
    if (!p.moved || cfg.busy()) return;
    if (p.shift) { p.x1 = x; return; }                      // Shift: the range is taken on release
    const dt = (x - p.x0) / (g.W - g.pad.l - g.pad.r) * (p.r[1] - p.r[0]);
    const [a, b] = clampRange(p.r[0] - dt, p.r[1] - dt); cfg.setRange(a, b);
  });
  window.addEventListener("mouseup", (e) => {
    if (st.drag) { st.drag = null; cfg.redraw(); return; }
    const p = st.pan; st.pan = null; if (!p || !geo()) return;
    const [x, y] = px(e);
    if (p.moved && p.shift && p.x1 !== undefined) {
      const a = tAt(Math.min(p.x0, p.x1)), b = tAt(Math.max(p.x0, p.x1));
      if (b - a >= CX_MIN_WINDOW) { const [lo, hi] = clampRange(a, b); cfg.setRange(lo, hi); }
      return;
    }
    if (p.moved || cfg.busy() || e.target !== cv) return;
    const g = geo();                                         // a click: a new cursor in the active mode
    if (st.hOn) { st.h.push(Math.min(Math.max((y - g.pad.t) / (g.H - g.pad.t - g.pad.b), 0), 1)); if (st.h.length > 2) st.h.shift(); }
    if (st.hOn) cfg.redraw();
  });
  cv.addEventListener("mousemove", (e) => {
    if (st.pan?.moved || st.drag || !geo()) return;
    const [x, y] = px(e), h = hit(x, y);
    if (h) cv.style.cursor = "row-resize";
    else if (!cv.style.cursor || cv.style.cursor === "col-resize" || cv.style.cursor === "row-resize") cv.style.cursor = st.hOn ? "crosshair" : "";
  });
  cv.addEventListener("wheel", (e) => {
    if (!geo() || !(e.ctrlKey || e.metaKey)) return; e.preventDefault();      // Ctrl + wheel: plain wheel keeps scrolling the page
    const [x] = px(e), [a, b] = cfg.range(), tc = tAt(x), f = e.deltaY < 0 ? 0.8 : 1.25;
    const [na, nb] = clampRange(tc - (tc - a) * f, tc + (b - tc) * f); cfg.setRange(na, nb);
  }, { passive: false });
  if (cfg.overview) cxAttachOverview(cfg, clampRange);
  return st;
}

// ---- time axis: the clock of the server ("app") or of the PLC ("plc") + the offset; null = seconds from the start (labels drawn by app.js)
// Offset of the clock axis = sign + days (the date part) + HH:MM:SS.mmm; kept in three inputs, read / written in seconds (helpers shared with the editor in app.js)
const CX_OFF_MAX = 3650 * 86400;
function cxOffGet(sEl, dEl, tEl) {   // null = nothing typed ("per connection"), NaN = not a valid time
  const d = dEl.value.trim(), t = tEl.value.trim(); if (d === "" && t === "") return null;
  const m = t === "" ? [0, 0, 0, 0, 0] : /^(\d{1,2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,3}))?)?$/.exec(t); if (!m || (d !== "" && !(+d >= 0))) return NaN;
  const ms = (+m[1] * 3600 + +m[2] * 60 + +(m[3] || 0)) * 1000 + +((m[4] || "0").padEnd(3, "0")), v = Math.round(+d || 0) * 86400 + ms / 1000;
  return Math.max(-CX_OFF_MAX, Math.min(CX_OFF_MAX, sEl.value === "-1" ? -v : v));
}
function cxOffSet(sEl, dEl, tEl, sec) {
  const v = Math.max(-CX_OFF_MAX, Math.min(CX_OFF_MAX, +sec || 0)), a = Math.abs(v), tot = Math.round(a * 1000), days = Math.floor(tot / 86400000), ms = tot % 86400000, p = (n, l = 2) => String(n).padStart(l, "0");
  sEl.value = v < 0 && tot > 0 ? "-1" : "1"; dEl.value = days; tEl.value = `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)}.${p(ms % 1000, 3)}`;
}
const cxOffFmt = (sec) => { const v = Math.round(Math.abs(sec) * 1000), d = Math.floor(v / 86400000), ms = v % 86400000, p = (n, l = 2) => String(n).padStart(l, "0");
  return `${sec < 0 && v ? "-" : "+"}${d} d ${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)}.${p(ms % 1000, 3)}`; };
const CX_NICE = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400];
function cxClock(cv, ds) {
  const st = cv._cx || {}, d = (ds && ds.layout) || {}, mode = st.taxis || d.time_axis || "rel";
  if (mode === "rel" || !ds || !ds.start_us) return null;
  const off = st.toff !== null && st.toff !== undefined ? st.toff : (+d.time_offset || 0), diff = ds.plc_diff ?? ds.device?.time_diff;
  return { mode, shift: ds.start_us / 1e6 + (mode === "plc" ? +diff || 0 : 0) + off, noPlc: mode === "plc" && (diff === null || diff === undefined),
           tz: ds.tz_offset === null || ds.tz_offset === undefined ? null : -ds.tz_offset };   // the server's zone (a recording: the browser's)
}
function cxAxis(g, geo, clock) {   // ticks on whole clock seconds / minutes; only as many parts of the time as the zoom needs
  const { t0, t1, pad, W, H } = geo, span = t1 - t0, wpx = W - pad.l - pad.r; if (!(span > 0)) return;
  const sp = CX_NICE.find((n) => span / n <= Math.max(wpx / 120, 1)) || 86400, tz = clock.tz ?? new Date((clock.shift + t0) * 1000).getTimezoneOffset() * 60;
  const first = Math.ceil((t0 + clock.shift - tz) / sp), last = Math.min(Math.floor((t1 + clock.shift - tz) / sp), first + 400), p = (n, l = 2) => String(n).padStart(l, "0");
  g.save(); g.font = "11px sans-serif"; g.fillStyle = "#aaa"; g.strokeStyle = "#777"; g.textAlign = "center"; g.lineWidth = 1;
  for (let k = first; k <= last; k++) {
    const x = pad.l + (k * sp - clock.shift + tz - t0) / span * wpx, d = new Date(Math.round(k * sp * 1000));        // (the local clock read with the UTC getters)
    const hm = `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
    g.beginPath(); g.moveTo(x, H - pad.b); g.lineTo(x, H - pad.b + 4); g.stroke();
    g.fillText(sp >= 60 ? hm : sp >= 1 ? `${hm}:${p(d.getUTCSeconds())}` : `${hm}:${p(d.getUTCSeconds())}.${p(d.getUTCMilliseconds(), 3)}`, x, H - pad.b + 16);
  }
  if (clock.noPlc) { g.fillStyle = "#e0a030"; g.fillText("brak czasu PLC – pokazano czas serwera", pad.l + wpx / 2, H - 4); }
  g.restore();
}

// ---- cursors on the chart
function cxPaint(g, cv) {
  const st = cv._cx, geo = cv._geo, ds = cv._ds; if (!st || !geo || !st.h.length) return;
  const { t0, t1, pad, W, H } = geo, lines = [];
  g.save(); g.lineWidth = 1; g.setLineDash([6, 4]); g.font = "12px sans-serif";
  st.h.forEach((f, i) => {
    const y = pad.t + f * (H - pad.t - pad.b);
    g.strokeStyle = g.fillStyle = "#ffd24a"; g.beginPath(); g.moveTo(pad.l, y); g.lineTo(W - pad.r, y); g.stroke(); g.fillText("H" + (i + 1), pad.l + 3, y - 3);
  });
  g.restore();
  const hv = st.h.map((f) => {
    const y = pad.t + f * (H - pad.t - pad.b);
    for (const l of geo.lanes || []) if (y >= l.top && y <= l.bot && l.bot > l.top) return { name: geo.offsetMode ? "y" : l.name, v: l.lo + (l.bot - 3 - y) / (l.bot - l.top - 6) * l.span };
    return null;
  });
  hv.forEach((h, i) => lines.push(h ? `H${i + 1}: ${h.name} = ${CX_NUM(h.v)}` : `H${i + 1}: (poza pasmem sygnału)`));
  if (hv.length === 2 && hv[0] && hv[1] && hv[0].name === hv[1].name) lines.push(`ΔY = ${CX_NUM(hv[1].v - hv[0].v)}`);
  if (!lines.length) return;
  g.font = "12px monospace";
  const w = Math.max(...lines.map((l) => g.measureText(l).width)) + 12, h = lines.length * 15 + 8, x0 = W - pad.r - w - 4, y0 = pad.t + 4;
  g.fillStyle = "rgba(0,0,0,0.78)"; g.fillRect(x0, y0, w, h); g.strokeStyle = "#666"; g.setLineDash([]); g.strokeRect(x0, y0, w, h);
  g.fillStyle = "#e8e8e8"; lines.forEach((l, i) => g.fillText(l, x0 + 6, y0 + 15 + i * 15));
}

// ---- the options of one canvas: the viewer's own choice, else what the connection / recording says
function cxOpts(cv, ds) {
  const st = cv._cx || {}, d = (ds && ds.layout) || {};
  if (st.syncPoints && (st.points === null || st.points === undefined)) st.syncPoints(d.show_points);
  return { layout: st.layout || d.y_layout || "lanes", autoY: d.auto_y !== false, yMin: d.y_min ?? 0, yMax: d.y_max ?? 10, clock: cxClock(cv, ds),
           points: st.points === null || st.points === undefined ? !!d.show_points : st.points };
}
// legend text: the signal name or its address / OPC node (viewer's choice, else the connection's)
function cxLegend(cv, ds, k) {
  const mode = cv._cx?.legend || ds.layout?.legend_mode || "name";
  return mode === "address" && ds.addresses?.[k] ? ds.addresses[k] : ds.names[k];
}
function cxToolbar(box, cv) {
  const st = cv._cx;
  box.innerHTML = `<button type="button" data-x="h" title="Kliknij na wykresie, aby postawić poziomy znacznik poziomu sygnału (maks. 2; można je przeciągać) – pokazuje wartość i różnicę wartości">Znacznik poziomu sygnału</button>
    <label title="Pokazuje punkty próbek na krzywych"><input type="checkbox" data-x="pts"> Punkty</label>
    <label>Układ <select data-x="lay"><option value="">wg połączenia</option><option value="lanes">Pasma wg Share</option><option value="offset">Offset Y + wzmocnienie</option></select></label>
    <label>Legenda <select data-x="leg"><option value="">wg połączenia</option><option value="name">Nazwa</option><option value="address">Adres / węzeł OPC</option></select></label>
    <label title="Opisy osi czasu: sekundy od startu albo zegar HH:MM:SS.mmm – serwera (aplikacji) lub sterownika PLC">Oś czasu <select data-x="tax"><option value="">wg połączenia</option><option value="rel">Względna</option><option value="app">Czas aplikacji</option><option value="plc">Czas PLC</option></select></label>
    <span title="Korekta czasu na osi zegarowej: znak, data (pełne doby) i godzina HH:MM:SS.mmm (puste = wg połączenia)">Offset
      <select data-x="toff-s"><option value="1">+</option><option value="-1">-</option></select>
      <input type="number" min="0" max="3650" step="1" data-x="toff-d" style="width:5em" placeholder="dni"> d
      <input type="text" data-x="toff-t" style="width:8.5em" placeholder="HH:MM:SS.mmm"></span>
    <span class="muted">Ctrl + kółko – przybliżanie, przeciąganie – przesuwanie, Shift + przeciąganie – zakres.</span>`;
  const q = (k) => box.querySelector(`[data-x=${k}]`), sync = () => { q("h").classList.toggle("on", st.hOn); };
  q("h").onclick = () => { st.hOn = !st.hOn; if (!st.hOn) st.h = []; sync(); cv.style.cursor = st.hOn ? "crosshair" : ""; st.cfg.redraw(); };
  q("tax").onchange = () => { st.taxis = q("tax").value; st.cfg.redraw(); };
  const offIn = () => { const v = cxOffGet(q("toff-s"), q("toff-d"), q("toff-t")); st.toff = v === null || Number.isNaN(v) ? null : v; q("toff-t").style.outline = Number.isNaN(v) ? "2px solid #c33" : ""; st.cfg.redraw(); };
  for (const k of ["toff-s", "toff-d", "toff-t"]) q(k).oninput = offIn;
  q("pts").onchange = () => { st.points = q("pts").checked; st.cfg.redraw(); };
  q("lay").onchange = () => { st.layout = q("lay").value; st.cfg.redraw(); };
  q("leg").onchange = () => { st.legend = q("leg").value; st.cfg.redraw(); };
  st.syncPoints = (def) => { if (st.points === null) q("pts").checked = !!def; };
  sync();
}

// ---- overview strip: the whole data with the shown range
function cxAttachOverview(cfg, clampRange) {
  const ov = cfg.overview.cv; let drag = null;
  const px = (ev) => { const r = ov.getBoundingClientRect(); return (ev.clientX - r.left) * ov.width / r.width; };
  const span = () => cfg.limits(), tOf = (x) => { const [lo, hi] = span(); return lo + Math.min(Math.max(x / ov.width, 0), 1) * (hi - lo); };
  ov.addEventListener("mousedown", (e) => {
    const [lo, hi] = span(); if (!(hi > lo)) return;
    const x = px(e), t = tOf(x), [a, b] = cfg.range(), xa = (a - lo) / (hi - lo) * ov.width, xb = (b - lo) / (hi - lo) * ov.width;
    if (Math.abs(x - xa) < 7) drag = { part: "a" }; else if (Math.abs(x - xb) < 7) drag = { part: "b" };
    else if (x > xa && x < xb) drag = { part: "body", t0: t, r: [a, b] };
    else { const w = b - a, [na, nb] = clampRange(t - w / 2, t + w / 2); cfg.setRange(na, nb); drag = { part: "body", t0: t, r: [na, nb] }; }
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return; const t = tOf(px(e)), [a, b] = cfg.range();
    if (drag.part === "a") cfg.setRange(...clampRange(Math.min(t, b - CX_MIN_WINDOW), b));
    else if (drag.part === "b") cfg.setRange(...clampRange(a, Math.max(t, a + CX_MIN_WINDOW)));
    else { const dt = t - drag.t0; cfg.setRange(...clampRange(drag.r[0] + dt, drag.r[1] + dt)); }
  });
  window.addEventListener("mouseup", () => { drag = null; });
}
function cxOverview(cv) {
  const st = cv._cx, ovc = st?.cfg.overview; if (!ovc) return;
  const o = ovc.cv, ds = ovc.ds(), g = o.getContext("2d"), W = o.width, H = o.height;
  g.fillStyle = "#0a0a0a"; g.fillRect(0, 0, W, H);
  if (!ds || !ds.t.length) return;
  const [lo, hi] = st.cfg.limits(), sp = (hi - lo) || 1, X = (t) => (t - lo) / sp * W;
  ds.names.forEach((_, k) => {
    const col = ds.values[k] || [], fin = col.filter((x) => x !== null && x !== undefined);
    if (!fin.length) return; const a = Math.min(...fin), b = Math.max(...fin), s = b - a || 1;
    g.strokeStyle = (ds.colors || [])[k] || COLORS[k % COLORS.length]; g.globalAlpha = 0.8; g.lineWidth = 1; g.beginPath(); let pen = false, py = 0;
    for (let i = 0; i < ds.t.length; i++) {
      const v = col[i]; if (v === null || v === undefined) { pen = false; continue; }
      const x = X(ds.t[i]), y = H - 4 - (v - a) / s * (H - 8);
      if (!pen) { g.moveTo(x, y); pen = true; } else { g.lineTo(x, py); g.lineTo(x, y); }
      py = y;
    }
    g.stroke();
  });
  g.globalAlpha = 1;
  const [a, b] = st.cfg.range(), xa = X(a), xb = X(b);
  g.fillStyle = "rgba(255,255,255,0.12)"; g.fillRect(xa, 0, Math.max(xb - xa, 2), H);
  g.strokeStyle = "#ffffff"; g.lineWidth = 1; g.strokeRect(xa + 0.5, 0.5, Math.max(xb - xa, 2), H - 1);
}
