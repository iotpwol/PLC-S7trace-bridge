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

// ---- pauses of the chart (the counterpart of core/gapmap.py): the data stay on the real chart time, the chart is drawn on display positions.
// Width g = 0: every pause (Stop -> Start of the reading) is cut out: the line before it and after it meet in one junction, one mark stands there and the axis
// labels jump (30 | 50). Width g > 0: a pause is a BAND of that width (gap_px pixels whatever its duration; the time inside is mapped proportionally).
// gm = { a, b, L, cum, g, D, E, j } (a / b = Stop / Start, D / E = display start / end of the band, j = its centre) or null (= the full axis).
function gmMake(gaps, width) {
  const g = (gaps || []).map((x) => [+x.t0, +x.t1]).filter((x) => x[1] - x[0] > 0.002).sort((p, q) => p[0] - q[0]), m = [];
  for (const x of g) { if (m.length && x[0] <= m[m.length - 1][1]) m[m.length - 1][1] = Math.max(m[m.length - 1][1], x[1]); else m.push([x[0], x[1]]); }
  if (!m.length) return null;
  const w = Math.max(0, +width || 0), a = m.map((x) => x[0]), b = m.map((x) => x[1]), L = a.map((v, i) => b[i] - v), cum = [0]; L.forEach((v, i) => cum.push(cum[i] + v));
  const D = a.map((v, i) => v - cum[i] + w * i);
  return { a, b, L, cum, g: w, D, E: D.map((v) => v + w), j: D.map((v) => v + w / 2) };
}
function gmCount(arr, v, orEqual) { let lo = 0, hi = arr.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (orEqual ? arr[mid] <= v : arr[mid] < v) lo = mid + 1; else hi = mid; } return lo; }
function gmD(gm, t) {            // real time -> display position
  if (!gm) return t;
  const k = gmCount(gm.a, t, true), p = k - 1;
  if (k > 0 && t < gm.b[p]) return gm.D[p] + (gm.g > 0 ? gm.g * (t - gm.a[p]) / gm.L[p] : 0);
  return t - gm.cum[k] + gm.g * k;
}
function gmR(gm, x, hi) {        // display position -> real time; at a zero-width junction: the Stop side, or the Start side (hi)
  if (!gm) return x;
  if (!(gm.g > 0)) return x + gm.cum[gmCount(gm.D, x, !!hi)];
  const k = gmCount(gm.D, x, false), p = k - 1;
  if (k > 0 && x < gm.E[p]) return gm.a[p] + (x - gm.D[p]) / gm.g * gm.L[p];
  return x + gm.cum[k] - gm.g * k;
}
// inside a zero-width pause (a < t <= b): the empty rows the acquisition puts there are skipped, so the line steps from the old value to the new one
function gmJoinRow(gm, t) { if (!gm || gm.g > 0) return false; const k = gmCount(gm.a, t, false); return k > 0 && t <= gm.b[k - 1]; }
function gmSeg(gm, d0, d1) {     // the real-time stretches visible between the display positions d0 .. d1 outside the pauses
  const out = []; let pos = d0, any = false;
  for (let i = 0; gm && i < gm.a.length; i++) {
    if (!(gm.E[i] > d0 && gm.D[i] < d1)) continue; any = true;
    if (gm.D[i] > pos) out.push([gmR(gm, pos, true), gmR(gm, gm.D[i], false)]);
    pos = Math.max(pos, gm.E[i]);
  }
  if (d1 > pos) out.push([gmR(gm, pos, true), gmR(gm, d1, false)]);
  if (!any && !out.length) out.push([gmR(gm, d0, false), gmR(gm, d1, false)]);
  return out;
}
function gmFit(gm, t0, t1, px, plotPx) {   // display width of one pause so that it takes px pixels on a plot plotPx wide showing the real stretch t0 .. t1
  if (!gm || !(px > 0) || !(plotPx > 0) || !(t1 > t0)) return 0;
  let ov = 0, c = 0; for (let i = 0; i < gm.a.length; i++) { const o = Math.max(Math.min(gm.b[i], t1) - Math.max(gm.a[i], t0), 0); ov += o; c += o / gm.L[i]; }
  const room = Math.max(1 - c * px / plotPx, 0.05), wv = Math.max((t1 - t0) - ov, 1e-6) / room;
  return px * wv / plotPx;
}
const cxPlotW = (geo) => geo.W - geo.pad.l - geo.pad.r;
function cxX(geo, t) { const gm = geo.gm, d0 = gmD(gm, geo.t0), d1 = gmD(gm, geo.t1); return geo.pad.l + (gmD(gm, t) - d0) / ((d1 - d0) || 1) * cxPlotW(geo); }
function cxT(geo, px, clamp) {   // real time under the x pixel of the canvas
  const gm = geo.gm, d0 = gmD(gm, geo.t0), d1 = gmD(gm, geo.t1); let f = (px - geo.pad.l) / cxPlotW(geo); if (clamp) f = Math.min(Math.max(f, 0), 1);
  return gmR(gm, d0 + f * (d1 - d0));
}
// the pauses of a canvas: only the live chart has them. The viewer's choice (st.gapmode / st.gappx) wins over the connection's (layout.gap_mode / gap_px).
// -> { gaps, px } (px 0 = cut out) or null (the full axis); `cxGm` makes the time map for a view (the width of a band follows the view)
function cxFindGaps(ds, minLen = 1) {   // pauses of a LOADED recording = stretches where every signal is empty (same rule as core.gapmap.find_gaps)
  if (!ds || !ds.t || ds.t.length < 3 || !ds.values || !ds.values.length) return [];
  if (ds._gapsFor === ds.t) return ds._gaps;
  const t = ds.t, n = t.length, v = ds.values, out = []; let i = 0;
  const empty = (k) => v.every((c) => c[k] === null || c[k] === undefined || Number.isNaN(c[k]));
  while (i < n) {
    if (!empty(i)) { i++; continue; }
    let j = i; while (j + 1 < n && empty(j + 1)) j++;
    if (i > 0 && j + 1 < n && t[j + 1] - t[i] >= minLen) out.push({ n: out.length + 1, t0: t[i], t1: t[j + 1] });
    i = j + 1;
  }
  ds._gapsFor = ds.t; ds._gaps = out; return out;
}
function cxGapSpec(cv, ds) {
  const st = cv._cx || {}, d = (ds && ds.layout) || {}, mode = st.gapmode || d.gap_mode || "full";
  if (mode === "full" || (cv.id !== "canvas" && cv.id !== "rv-canvas") || typeof recmGaps !== "function") return null;
  const gaps = cv.id === "rv-canvas" ? cxFindGaps(ds) : recmGaps(); if (!gmMake(gaps)) return null;
  return { gaps, px: mode === "fixed" ? Math.max(8, Math.min(300, +(st.gappx || d.gap_px || 40))) : 0 };
}
function cxGm(spec, t0, t1, plotPx, followSec) {
  if (!spec) return null;
  const base = gmMake(spec.gaps, 0); if (!base || !(spec.px > 0)) return base;
  const g = followSec > 0 ? spec.px * followSec / plotPx : gmFit(base, t0, t1, spec.px, plotPx);
  return gmMake(spec.gaps, g);
}

function cxAttach(cv, cfg) {
  const st = cv._cx = { hOn: false, h: [], layout: "", legend: "", lstyle: "", gapmode: "", gappx: 0, taxis: "", toff: null, points: null, cfg, drag: null, pan: null };
  const px = (ev) => { const r = cv.getBoundingClientRect(); return [(ev.clientX - r.left) * cv.width / r.width, (ev.clientY - r.top) * cv.height / r.height]; };
  const geo = () => cv._geo;
  const tAt = (x) => cxT(geo(), x, true);
  const xOf = (t) => cxX(geo(), t);
  const yOf = (f) => { const g = geo(); return g.pad.t + f * (g.H - g.pad.t - g.pad.b); };
  const clampRange = (a, b) => {                              // in display positions (the pauses cut out take no width), the result in real times
    const gm = cfg.gm || null, lim = cfg.limits(), lo = gmD(gm, lim[0]), hi = gmD(gm, lim[1]); a = gmD(gm, a); b = gmD(gm, b);
    const w = Math.max(b - a, CX_MIN_WINDOW);
    if (w >= hi - lo) return [lim[0], Math.max(lim[1], gmR(gm, lo + CX_MIN_WINDOW, true))];
    a = Math.min(Math.max(a, lo), hi - w); return [gmR(gm, a), gmR(gm, a + w, true)];
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
    const gm = g.gm, da = gmD(gm, p.r[0]), db = gmD(gm, p.r[1]), dd = (x - p.x0) / cxPlotW(g) * (db - da);
    const [a, b] = clampRange(gmR(gm, da - dd), gmR(gm, db - dd, true)); cfg.setRange(a, b);
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
    const [x] = px(e), [a, b] = cfg.range(), gm = geo().gm, f = e.deltaY < 0 ? 0.8 : 1.25, da = gmD(gm, a), db = gmD(gm, b), dc = gmD(gm, tAt(x));
    const [na, nb] = clampRange(gmR(gm, dc - (dc - da) * f), gmR(gm, dc + (db - dc) * f, true)); cfg.setRange(na, nb);
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
  // clock.mode "rel" = the same ticks in seconds of the chart time (used when pauses are cut out); a junction of a cut-out pause carries both times: "30 s | 50 s"
  const { t0, t1, pad, W, H, gm } = geo, d0 = gmD(gm, t0), d1 = gmD(gm, t1), span = d1 - d0, wpx = W - pad.l - pad.r; if (!(span > 0)) return;
  const rel = clock.mode === "rel", sh = rel ? 0 : clock.shift;
  const sp = CX_NICE.find((n) => span / n <= Math.max(wpx / 120, 1)) || 86400, tz = rel ? 0 : clock.tz ?? new Date((clock.shift + t0) * 1000).getTimezoneOffset() * 60;
  const p = (n, l = 2) => String(n).padStart(l, "0"), dec = sp < 1 ? Math.min(6, Math.ceil(-Math.log10(sp))) : 0;
  const label = (tr) => {                                                                              // the label of the real chart time tr
    if (rel) { const v = +tr.toFixed(dec); return Math.abs(v) >= 3600 ? `${Math.floor(v / 3600)}:${p(Math.floor(v % 3600 / 60))}:${p(Math.floor(v % 60))}` : `${v} s`; }
    const d = new Date(Math.round((tr + sh - tz) * 1000)), hm = `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;       // (the local clock read with the UTC getters)
    return sp >= 60 ? hm : sp >= 1 ? `${hm}:${p(d.getUTCSeconds())}` : `${hm}:${p(d.getUTCSeconds())}.${p(d.getUTCMilliseconds(), 3)}`;
  };
  const dx = (d) => pad.l + (d - d0) / span * wpx, jx = (gm ? gm.j : []).filter((c) => c >= d0 && c <= d1).map((c, i) => ({ c, x: dx(c), i: gm.j.indexOf(c) }));
  g.save(); g.font = "11px sans-serif"; g.fillStyle = "#aaa"; g.strokeStyle = "#777"; g.textAlign = "center"; g.lineWidth = 1;
  for (const [r0, r1] of gmSeg(gm, d0, d1)) {
    const first = Math.ceil((r0 + sh - tz) / sp), last = Math.min(Math.floor((r1 + sh - tz) / sp), first + 400);
    for (let k = first; k <= last; k++) {
      const tr = k * sp - sh + tz, x = dx(gmD(gm, tr)); if (jx.some((q) => Math.abs(q.x - x) < 90)) continue;           // room for the double label of a junction
      g.beginPath(); g.moveTo(x, H - pad.b); g.lineTo(x, H - pad.b + 4); g.stroke(); g.fillText(label(tr), x, H - pad.b + 16);
    }
  }
  for (const q of jx) { g.beginPath(); g.moveTo(q.x, H - pad.b); g.lineTo(q.x, H - pad.b + 6); g.stroke(); g.fillText(`${label(gm.a[q.i])} | ${label(gm.b[q.i])}`, q.x, H - pad.b + 18); }
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
  return { layout: st.layout || d.y_layout || "lanes", autoY: d.auto_y !== false, yMin: d.y_min ?? 0, yMax: d.y_max ?? 10, clock: cxClock(cv, ds), gaps: cxGapSpec(cv, ds),
           points: st.points === null || st.points === undefined ? !!d.show_points : st.points };
}
// legend text: the signal name or its address / OPC node (viewer's choice, else the connection's)
function cxLegend(cv, ds, k) {
  const mode = cv._cx?.legend || ds.layout?.legend_mode || "name";
  return mode === "address" && ds.addresses?.[k] ? ds.addresses[k] : ds.names[k];
}
// the 'labels' style of the signal names: a boxed name (translucent background) at the middle of every lane (offset layout: at its curve),
// just right of the vertical axis; the boxes are kept in cv._tags for the right click menu and the tool tip
function cxTags(g, cv, ds, lanes, colors, pad, H) {
  const bh = 18, top = pad.t, bottom = H - pad.b;
  const tags = lanes.map((l, k) => ({ k, y: l.tagY, c: colors[k] || COLORS[k % COLORS.length], text: cxLegend(cv, ds, k) })).filter((t) => t.y !== null && t.y !== undefined && Number.isFinite(t.y));
  if (cv._geo.offsetMode) {                                                              // close curves: push the boxes apart, keep them inside the plot
    tags.sort((a, b) => a.y - b.y);
    tags.forEach((t, i) => { t.y = Math.max(t.y, i ? tags[i - 1].y + bh + 2 : top + bh / 2); });
    for (let i = tags.length - 1; i >= 0; i--) tags[i].y = Math.min(tags[i].y, i === tags.length - 1 ? bottom - bh / 2 : tags[i + 1].y - bh - 2);
  }
  g.font = "12px sans-serif";
  for (const t of tags) {
    const w = Math.ceil(g.measureText(t.text).width) + 10, x = pad.l + 6, y = t.y - bh / 2;
    g.fillStyle = "rgba(0,0,0,0.67)"; g.fillRect(x, y, w, bh); g.strokeStyle = "#b0b0b0"; g.lineWidth = 1; g.strokeRect(x + 0.5, y + 0.5, w - 1, bh - 1);
    g.fillStyle = t.c; g.fillText(t.text, x + 5, y + bh - 5);
    cv._tags.push({ k: t.k, x, y, w, h: bh });
  }
}
function cxTagAt(cv, ev) {
  if (!cv._tags || !cv._tags.length) return null;
  const r = cv.getBoundingClientRect(), x = (ev.clientX - r.left) * cv.width / r.width, y = (ev.clientY - r.top) * cv.height / r.height;
  return cv._tags.find((t) => x >= t.x && x <= t.x + t.w && y >= t.y && y <= t.y + t.h) || null;
}
function cxToolbar(box, cv) {
  const st = cv._cx;
  box.innerHTML = `<button type="button" data-x="h" title="Kliknij na wykresie, aby postawić poziomy znacznik poziomu sygnału (maks. 2; można je przeciągać) – pokazuje wartość i różnicę wartości">Znacznik poziomu sygnału</button>
    <label title="Pokazuje punkty próbek na krzywych"><input type="checkbox" data-x="pts"> Punkty</label>
    <label>Układ <select data-x="lay"><option value="">wg połączenia</option><option value="lanes">Pasma wg Share</option><option value="offset">Offset Y + wzmocnienie</option></select></label>
    <label>Legenda <select data-x="leg"><option value="">wg połączenia</option><option value="name">Nazwa</option><option value="address">Adres / węzeł OPC</option></select></label>
    <label title="Jak wykres pokazuje nazwy sygnałów: lista pod wykresem albo osobny opis w półprzezroczystej ramce przy każdym sygnale (po prawej stronie osi pionowej). Wybór zapisuje się przy tym połączeniu (jeśli możesz je edytować); „wg połączenia” = ustawienie połączenia lub domyślne konta.">Nazwy sygnałów <select data-x="lst"><option value="">wg połączenia</option><option value="legend">Legenda (lista)</option><option value="labels">Opisy przy sygnałach</option></select></label>
    <label title="Pauza między Stop a Start odczytu: pusta przerwa w pełnej długości albo wycięta z wykresu (linie się stykają, w tym miejscu stoi jeden znacznik, a opisy osi czasu przeskakują, np. 30 s | 50 s). Trzecia możliwość: pas o stałej szerokości w pikselach (pole „px”) niezależnie od czasu przerwy. Wybór zapisuje się przy tym połączeniu (jeśli możesz je edytować); „wg połączenia” = ustawienie połączenia.">Przerwy Stop → Start <select data-x="gj"><option value="">wg połączenia</option><option value="full">Pełna przerwa</option><option value="join">Wytnij z wykresu</option><option value="fixed">Pas o stałej szerokości</option></select></label>
    <label title="Szerokość przerwy w pikselach (tryb „Pas o stałej szerokości”): stała, niezależna od czasu trwania przerwy (8 – 300). Puste = wg połączenia."><input type="number" min="8" max="300" step="1" data-x="gpx" style="width:4.5em" placeholder="px"> px</label>
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
  q("lst").onchange = () => legendStyleThis(cv, q("lst").value);
  q("gj").onchange = () => gapModeThis(cv, q("gj").value, q("gpx").value);
  q("gpx").oninput = () => { st.gappx = Math.max(0, Math.min(300, Math.round(+q("gpx").value || 0))); if (q("gj").value === "fixed" || st.gapmode === "fixed") gapModeThis(cv, "fixed", q("gpx").value); };
  cv.addEventListener("contextmenu", (e) => {                                            // right click on a name box: what the names show, legend / labels style
    const tg = cxTagAt(cv, e); if (!tg) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const mode = st.legend || cv._ds?.layout?.legend_mode || "name";
    ctxMenu(e.clientX, e.clientY, [["Legenda pokazuje", null, undefined, [["Nazwę sygnału", () => { st.legend = "name"; q("leg").value = "name"; st.cfg.redraw(); }, mode !== "address"],
        ["Adres / węzeł OPC", () => { st.legend = "address"; q("leg").value = "address"; st.cfg.redraw(); }, mode === "address"]]],
      ["Nazwy sygnałów na wykresie (to połączenie)", null, undefined, [["Legenda (lista)", () => legendStyleThis(cv, "legend"), legStyle(cv, cv._ds) !== "labels"], ["Opisy przy sygnałach", () => legendStyleThis(cv, "labels"), legStyle(cv, cv._ds) === "labels"],
        "-", ["Wszystkie połączenia: Legenda (lista)", () => legendStyleAll("legend")], ["Wszystkie połączenia: Opisy przy sygnałach", () => legendStyleAll("labels")]]]]);
  }, true);
  cv.addEventListener("mousemove", (e) => { const tg = cxTagAt(cv, e); const nt = tg ? (cv._ds?.tips?.[tg.k] || cv._ds?.names?.[tg.k] || "") : ""; if (cv.title !== nt && (tg || cv.title)) cv.title = nt; });
  st.syncPoints = (def) => { if (st.points === null) q("pts").checked = !!def; };
  sync();
}

// ---- overview strip: the whole data with the shown range
function cxAttachOverview(cfg, clampRange) {
  const ov = cfg.overview.cv; let drag = null;
  const px = (ev) => { const r = ov.getBoundingClientRect(); return (ev.clientX - r.left) * ov.width / r.width; };
  const gmo = () => cfg.gm || null, D = (t) => gmD(gmo(), t), R = (x, hi) => gmR(gmo(), x, hi);          // the strip is drawn on display positions too
  const span = () => cfg.limits(), tOf = (x) => { const [lo, hi] = span(), d0 = D(lo); return R(d0 + Math.min(Math.max(x / ov.width, 0), 1) * (D(hi) - d0)); };
  const shift = (r, dd) => clampRange(R(D(r[0]) + dd), R(D(r[1]) + dd, true));
  ov.addEventListener("mousedown", (e) => {
    const [lo, hi] = span(); if (!(D(hi) > D(lo))) return;
    const x = px(e), t = tOf(x), [a, b] = cfg.range(), sp = D(hi) - D(lo), xa = (D(a) - D(lo)) / sp * ov.width, xb = (D(b) - D(lo)) / sp * ov.width;
    if (Math.abs(x - xa) < 7) drag = { part: "a" }; else if (Math.abs(x - xb) < 7) drag = { part: "b" };
    else if (x > xa && x < xb) drag = { part: "body", t0: t, r: [a, b] };
    else { const w = D(b) - D(a), [na, nb] = clampRange(R(D(t) - w / 2), R(D(t) + w / 2, true)); cfg.setRange(na, nb); drag = { part: "body", t0: t, r: [na, nb] }; }
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return; const t = tOf(px(e)), [a, b] = cfg.range();
    if (drag.part === "a") cfg.setRange(...clampRange(R(Math.min(D(t), D(b) - CX_MIN_WINDOW)), b));
    else if (drag.part === "b") cfg.setRange(...clampRange(a, R(Math.max(D(t), D(a) + CX_MIN_WINDOW), true)));
    else cfg.setRange(...shift(drag.r, D(t) - D(drag.t0)));
  });
  window.addEventListener("mouseup", () => { drag = null; });
}
function cxOverview(cv) {
  const st = cv._cx, ovc = st?.cfg.overview; if (!ovc) return;
  const o = ovc.cv, ds = ovc.ds(), g = o.getContext("2d"), W = o.width, H = o.height;
  g.fillStyle = "#0a0a0a"; g.fillRect(0, 0, W, H);
  if (!ds || !ds.t.length) return;
  const gm = st.cfg.gm || null, [lo, hi] = st.cfg.limits(), sp = (gmD(gm, hi) - gmD(gm, lo)) || 1, X = (t) => (gmD(gm, t) - gmD(gm, lo)) / sp * W;
  ds.names.forEach((_, k) => {
    const col = ds.values[k] || [], fin = col.filter((x) => x !== null && x !== undefined);
    if (!fin.length) return; const a = Math.min(...fin), b = Math.max(...fin), s = b - a || 1;
    g.strokeStyle = (ds.colors || [])[k] || COLORS[k % COLORS.length]; g.globalAlpha = 0.8; g.lineWidth = 1; g.beginPath(); let pen = false, py = 0;
    for (let i = 0; i < ds.t.length; i++) {
      const v = col[i]; if (v === null || v === undefined) { if (!gmJoinRow(gm, ds.t[i])) pen = false; continue; }          // (the empty rows of a cut-out pause do not break the line)
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
