"use strict";
// Chart tools shared by the live chart and the recording view (the counterparts of the desktop program):
//  - cursors V1/V2 (time, Δt, frequency, values of the signals) and H1/H2 (value in the lane under the line, ΔY),
//  - zoom with Ctrl + mouse wheel, pan by dragging, Shift + drag = zoom to the selected range,
//  - overview strip of the whole data with the shown range (drag it, click to centre, drag an edge to resize),
//  - "Punkty" (sample points) and the chart layout (lanes by Share / offset Y + gain) for this viewer.
// cfg = { range(): [t0, t1], limits(): [lo, hi], setRange(a, b), redraw(), busy(): marker placement / drag in progress,
//         overview: { cv, ds(): data of the whole range } | null, defaults(): { layout, auto_y, y_min, y_max, show_points } }
const CX_MIN_WINDOW = 0.1;
const CX_NUM = (v) => String(+(+v).toPrecision(5));

function cxAttach(cv, cfg) {
  const st = cv._cx = { vOn: false, hOn: false, v: [], h: [], layout: "", legend: "", points: null, cfg, drag: null, pan: null };
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
    for (let i = 0; i < st.v.length; i++) if (Math.abs(xOf(st.v[i]) - x) <= tol) return { kind: "v", i };
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
      if (st.drag.kind === "v") st.v[st.drag.i] = tAt(x); else st.h[st.drag.i] = Math.min(Math.max((y - g.pad.t) / (g.H - g.pad.t - g.pad.b), 0), 1);
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
    if (st.vOn) { st.v.push(tAt(x)); if (st.v.length > 2) st.v.shift(); }
    if (st.hOn) { st.h.push(Math.min(Math.max((y - g.pad.t) / (g.H - g.pad.t - g.pad.b), 0), 1)); if (st.h.length > 2) st.h.shift(); }
    if (st.vOn || st.hOn) cfg.redraw();
  });
  cv.addEventListener("mousemove", (e) => {
    if (st.pan?.moved || st.drag || !geo()) return;
    const [x, y] = px(e), h = hit(x, y);
    if (h) cv.style.cursor = h.kind === "v" ? "col-resize" : "row-resize";
    else if (!cv.style.cursor || cv.style.cursor === "col-resize" || cv.style.cursor === "row-resize") cv.style.cursor = st.vOn || st.hOn ? "crosshair" : "";
  });
  cv.addEventListener("wheel", (e) => {
    if (!geo() || !(e.ctrlKey || e.metaKey)) return; e.preventDefault();      // Ctrl + wheel: plain wheel keeps scrolling the page
    const [x] = px(e), [a, b] = cfg.range(), tc = tAt(x), f = e.deltaY < 0 ? 0.8 : 1.25;
    const [na, nb] = clampRange(tc - (tc - a) * f, tc + (b - tc) * f); cfg.setRange(na, nb);
  }, { passive: false });
  if (cfg.overview) cxAttachOverview(cfg, clampRange);
  return st;
}

// ---- cursors on the chart
function cxPaint(g, cv) {
  const st = cv._cx, geo = cv._geo, ds = cv._ds; if (!st || !geo || (!st.v.length && !st.h.length)) return;
  const { t0, t1, pad, W, H } = geo, X = (t) => pad.l + (t - t0) / ((t1 - t0) || 1) * (W - pad.l - pad.r), lines = [];
  g.save(); g.lineWidth = 1; g.setLineDash([6, 4]); g.font = "12px sans-serif";
  st.v.forEach((t, i) => {
    if (t < t0 || t > t1) return;
    g.strokeStyle = g.fillStyle = "#ffffff"; g.beginPath(); g.moveTo(X(t), pad.t); g.lineTo(X(t), H - pad.b); g.stroke(); g.fillText("V" + (i + 1), X(t) + 3, pad.t + 12);
  });
  st.h.forEach((f, i) => {
    const y = pad.t + f * (H - pad.t - pad.b);
    g.strokeStyle = g.fillStyle = "#ffd24a"; g.beginPath(); g.moveTo(pad.l, y); g.lineTo(W - pad.r, y); g.stroke(); g.fillText("H" + (i + 1), pad.l + 3, y - 3);
  });
  g.restore();
  st.v.forEach((t, i) => {
    let vals = "";
    if (ds && ds.t.length) {
      let lo = 0, hi = ds.t.length - 1; if (t < ds.t[0]) hi = -1;
      while (lo < hi) { const m = (lo + hi + 1) >> 1; if (ds.t[m] <= t) lo = m; else hi = m - 1; }
      if (hi >= 0) vals = "  " + ds.names.map((nm, k) => { const v = (ds.values[k] || [])[lo]; return nm + "=" + (v === null || v === undefined ? "–" : CX_NUM(v)); }).join("  ");
    }
    lines.push(`V${i + 1}: t=${t.toFixed(3)} s${vals}`);
  });
  if (st.v.length === 2) { const dt = st.v[1] - st.v[0]; lines.push(`Δt = ${dt.toFixed(3)} s` + (dt ? `  (${(1 / Math.abs(dt)).toFixed(3)} Hz)` : "")); }
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
  return { layout: st.layout || d.y_layout || "lanes", autoY: d.auto_y !== false, yMin: d.y_min ?? 0, yMax: d.y_max ?? 10,
           points: st.points === null || st.points === undefined ? !!d.show_points : st.points };
}
// legend text: the signal name or its address / OPC node (viewer's choice, else the connection's)
function cxLegend(cv, ds, k) {
  const mode = cv._cx?.legend || ds.layout?.legend_mode || "name";
  return mode === "address" && ds.addresses?.[k] ? ds.addresses[k] : ds.names[k];
}
function cxToolbar(box, cv) {
  const st = cv._cx;
  box.innerHTML = `<button type="button" data-x="v" title="Kliknij na wykresie, aby postawić kursor czasu (maks. 2; można je przeciągać)">Kursory V</button>
    <button type="button" data-x="h" title="Kliknij na wykresie, aby postawić kursor wartości (maks. 2; można je przeciągać)">Kursory H</button>
    <label title="Pokazuje punkty próbek na krzywych"><input type="checkbox" data-x="pts"> Punkty</label>
    <label>Układ <select data-x="lay"><option value="">wg połączenia</option><option value="lanes">Pasma wg Share</option><option value="offset">Offset Y + wzmocnienie</option></select></label>
    <label>Legenda <select data-x="leg"><option value="">wg połączenia</option><option value="name">Nazwa</option><option value="address">Adres / węzeł OPC</option></select></label>
    <span class="muted">Ctrl + kółko – przybliżanie, przeciąganie – przesuwanie, Shift + przeciąganie – zakres.</span>`;
  const q = (k) => box.querySelector(`[data-x=${k}]`), sync = () => { q("v").classList.toggle("on", st.vOn); q("h").classList.toggle("on", st.hOn); };
  q("v").onclick = () => { st.vOn = !st.vOn; if (!st.vOn) st.v = []; sync(); cv.style.cursor = st.vOn || st.hOn ? "crosshair" : ""; st.cfg.redraw(); };
  q("h").onclick = () => { st.hOn = !st.hOn; if (!st.hOn) st.h = []; sync(); cv.style.cursor = st.vOn || st.hOn ? "crosshair" : ""; st.cfg.redraw(); };
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
