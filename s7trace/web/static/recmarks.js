// REC marks on the live chart (the same as in the desktop program):
//  * "Start REC (n)" / "Stop REC (n)" lines - the server tells when each recording started / stopped (lastDesc.rec.marks);
//  * "Manual REC" areas - put on the collected data by the viewer ("Manual Start REC" / "Manual Stop REC" in the chart menu), kept in this page
//    until they are saved as recordings of their own (right click -> "Zapis Manual REC (n)" or the "Zapisz znaczniki" window);
//  * the pulsing ghost of a Start REC that is being moved ("Przesuń Start REC" -> drag -> "Zmień Start REC").
// The look (on / off, colour, width, line style, area opacity) is MKLOOK.rec_* (Znaczniki -> Wygląd znaczników, kept per account).
const RECM = { manual: new Map(), run: new Map(), ghost: null, drag: null, pulse: 0, unlocked: new Set(), timer: null };
const recmConn = () => $("c-conn")?.value || "";
const recmList = () => { const id = recmConn(); if (!RECM.manual.has(id)) RECM.manual.set(id, []); return RECM.manual.get(id); };
const recmAuto = () => lastDesc?.rec?.marks || [];
const recmGaps = () => lastDesc?.rec?.gaps || [];
const recmUnsavedCount = () => recmList().filter((m) => m.b !== null && !m.saved).length;     // the areas of the chart that is shown
const recmPendingList = () => { const ds = frozen || series; return recmList().filter((m) => m.b !== null && !m.saved).map((m) => ({ n: m.n, a: recmClock(ds, m.a), b: recmClock(ds, m.b), dur: (m.b - m.a).toFixed(1) })); };
const recmDiscard = () => { RECM.manual.set(recmConn(), recmList().filter((m) => m.saved)); recmNotify(); };
const recmClock = (ds, t) => { const d = new Date(((ds.start_us || 0) / 1e6 + t) * 1000), p = (n, l = 2) => String(n).padStart(l, "0"); return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`; };
const recmNotify = () => { if (typeof mkdNotify === "function") mkdNotify(); else MK.live.redraw(); };

function recmRun(ds) {   // a new run of the connection (another start time): the areas of the previous one are gone, like in the program
  const id = recmConn(), cur = RECM.run.get(id);
  if (cur !== undefined && cur !== ds.start_us && ds.start_us) { RECM.manual.set(id, []); RECM.ghost = null; recmNotify(); }
  if (ds.start_us) RECM.run.set(id, ds.start_us);
}
function recmPaint(g, cv, ds, geo) {   // called by drawChart after the markers
  const { t0, t1, pad, W, H } = geo, X = (t) => cxX(geo, t);
  const col = MKLOOK.rec_color, lw = MKLOOK.rec_width, dash = MK_STYLES[MKLOOK.rec_style] || [], top = pad.t, bot = H - pad.b;
  const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${n >> 8 & 255},${n & 255},${a})`; };
  recmRun(ds); cv._recHits = [];
  g.save(); g.font = "11px sans-serif";
  const vline = (x, c, w, d) => { g.setLineDash(d); g.strokeStyle = c; g.lineWidth = w; g.beginPath(); g.moveTo(x, top); g.lineTo(x, bot); g.stroke(); g.setLineDash([]); };
  const label = (text, x, c, row, left) => { g.fillStyle = c; g.textAlign = left ? "right" : "left"; g.fillText(text, x + (left ? -4 : 4), top + 12 + row * 12); };
  const vis = (x) => x >= pad.l - 1 && x <= W - pad.r + 1;
  if (MKLOOK.rec_show) for (const gp of recmGaps()) {                    // Stop / Start of the reading: the chart has a gap between them (cut out: one mark at the junction)
    for (const [t, text] of geo.gm ? [[gp.t0, `Stop / Start odczytu (${gp.n})`]] : [[gp.t0, `Stop odczytu (${gp.n})`], [gp.t1, `Start odczytu (${gp.n})`]]) { const xs = X(t); if (vis(xs)) { vline(xs, col, lw, MK_STYLES.dot || [2, 3]); label(text, xs, col, 0, t === gp.t0); } }
  }
  if (MKLOOK.rec_show) for (const a of recmAuto()) {
    if (a.t1 !== null && a.t1 !== undefined && a.t1 > a.t0) {            // the recorded stretch: a translucent area under the two lines (like a Manual REC area)
      const x0 = Math.max(X(a.t0), pad.l), x1 = Math.min(X(a.t1), W - pad.r);
      if (x1 > x0) { g.fillStyle = rgba(col, MKLOOK.rec_opacity / 100); g.fillRect(x0, top, x1 - x0, bot - top); }
    }
    const xs = X(a.t0);
    if (vis(xs)) { vline(xs, col, lw, dash); label(`Start REC (${a.n})`, xs, col, 0, false); cv._recHits.push({ kind: "start", n: a.n, a, px: xs }); }
    if (a.t1 !== null && a.t1 !== undefined) { const xe = X(a.t1);
      if (vis(xe)) { vline(xe, col, lw, dash); label(`Stop REC (${a.n})`, xe, col, 0, false); cv._recHits.push({ kind: "stop", n: a.n, a, px: xe }); } }
  }
  for (const m of recmList()) {
    const xa = (RECM.drag && RECM.drag.kind === "manual" && RECM.drag.n === m.n) ? X(RECM.drag.a) : X(m.a), xb = m.b === null ? null : (RECM.drag && RECM.drag.kind === "manual" && RECM.drag.n === m.n) ? X(RECM.drag.b) : X(m.b);
    const hi = RECM.unlocked.has(m.n);
    if (xb !== null) { g.fillStyle = rgba(col, MKLOOK.rec_opacity / 100); g.fillRect(xa, top, xb - xa, bot - top); }
    vline(xa, col, lw, MK_STYLES.dash); label(`Manual Start REC (${m.n})`, xa, col, 1, false);
    if (xb !== null) { vline(xb, col, lw, MK_STYLES.dash); label(`Manual Stop REC (${m.n})`, xb, col, 1, true); }
    if (hi) { g.fillStyle = "#fff"; g.fillText("↔", xa + 4, top + 38); }
    cv._recHits.push({ kind: "manual", n: m.n, m, pxa: xa, pxb: xb });
  }
  if (RECM.ghost) {                                                     // the twin of a Start REC that is being moved: pulses between the colour and white
    const t = RECM.drag && RECM.drag.kind === "ghost" ? RECM.drag.a : RECM.ghost.t, xg = X(t), c = RECM.pulse ? "#ffffff" : col;
    vline(xg, c, lw + 1, [6, 4]); label(RECM.ghost.kind === "manual" ? `Manual Start REC (${RECM.ghost.n}) – nowa pozycja` : `Start REC (${RECM.ghost.n}) – nowy początek`, xg, c, 2, false);
    cv._recHits.push({ kind: "ghost", n: RECM.ghost.n, px: xg });
  }
  g.restore();
}
function recmHit(cv, ev) {
  const hits = cv._recHits; if (!hits || !hits.length || !cv._geo) return null;
  const r = cv.getBoundingClientRect(), px = (ev.clientX - r.left) * cv.width / r.width;
  const near = (x) => x !== null && x !== undefined && Math.abs(px - x) <= 6;
  for (const h of hits) if (h.kind === "ghost" && near(h.px)) return { ...h, part: "line", px };
  for (const h of hits) if ((h.kind === "start" || h.kind === "stop") && near(h.px)) return { ...h, part: "line", px };
  for (const h of hits) if (h.kind === "manual") {
    if (near(h.pxa)) return { ...h, part: "a", px }; if (near(h.pxb)) return { ...h, part: "b", px };
    if (h.pxb !== null && px > h.pxa && px < h.pxb) return { ...h, part: "body", px };
  }
  return null;
}
function recmTip(h, ds) {
  const e = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  if (h.kind === "start") return `<b>Start REC (${h.n})</b><br>${recmClock(ds, h.a.t0)}${h.a.t1 == null ? "<br>nagrywanie trwa" : ""}`;
  if (h.kind === "stop") return `<b>Stop REC (${h.n})</b><br>${recmClock(ds, h.a.t1)}<br>czas nagrywania ${(h.a.t1 - h.a.t0).toFixed(1)} s`;
  if (h.kind === "ghost") return RECM.ghost.kind === "manual" ? `<b>Manual Start REC (${h.n}) – nowa pozycja</b><br>${recmClock(ds, RECM.ghost.t)}<br>prawy przycisk → „Przenieś … tutaj” / „Anuluj przenoszenie”`
    : `<b>Start REC (${h.n}) – nowy początek</b><br>${recmClock(ds, RECM.ghost.t)}<br>prawy przycisk → „Zmień Start REC”`;
  const m = h.m; if (m.b === null) return `<b>Manual Start REC (${m.n})</b><br>${recmClock(ds, m.a)}<br>czekam na „Manual Stop REC”`;
  return `<b>Manual REC (${m.n})</b><br>od ${recmClock(ds, m.a)}<br>do ${recmClock(ds, m.b)}<br>czas ${(m.b - m.a).toFixed(1)} s<br>` + (m.saved ? `<i>zapisano: ${e(m.saved)}</i>` : "niezapisany – prawy przycisk → „Zapis Manual REC”");
}

// ---- the actions
function recmPlace(t) {
  const list = recmList(), open = list.find((m) => m.b === null);
  if (!open) { list.push({ n: Math.max(0, ...list.map((m) => m.n)) + 1, a: t, b: null, saved: "" }); }
  else if (t === open.a) { alert("Start i Stop obszaru Manual REC muszą leżeć w różnych chwilach."); return; }
  else { [open.a, open.b] = t < open.a ? [t, open.a] : [open.a, t]; }
  recmNotify();
}
function recmRemove(n) { const id = recmConn(); RECM.manual.set(id, recmList().filter((m) => m.n !== n)); RECM.unlocked.delete(n); recmNotify(); }
async function recmSave(n) {   // 'Zapis Manual REC (n)': the server writes that range of its buffer as a recording of its own
  const m = recmList().find((x) => x.n === n); if (!m || m.b === null) { alert("Ten obszar nie ma jeszcze końca – dodaj „Manual Stop REC”."); return false; }
  if (m.saved === "zapisuję…") { alert(`Manual REC (${n}) jest właśnie zapisywany.`); return false; }
  // saved already and not moved since (moving clears 'saved'): the same data would become a second, identical recording
  if (m.saved && !confirm(`Manual REC (${n}) został już zapisany jako nagranie:\n${m.saved}\n\nTen sam obszar nie zmienił się od zapisu. Czy zapisać dokładnie to samo nagranie jeszcze raz?`)) return false;
  const prev = m.saved; m.saved = "zapisuję…"; recmNotify();
  try { const d = await api(`/api/connections/${recmConn()}/rec-range`, { a: m.a, b: m.b, title: `Manual REC (${n})` }); m.saved = d.where; m.rec = d.rec_id ? { rec_id: d.rec_id, at_us: d.a_us, end_us: d.b_us, kind: "range" } : null; recmNotify(); return true; }
  catch (err) { m.saved = prev; recmNotify(); alert(`Nie udało się zapisać Manual REC (${n}):\n` + err.message); return false; }
}
function recmGhostStart(n) {
  const a = recmAuto().find((x) => x.n === n); if (!a) return;
  if (!liveView && !frozen) { const [x0, x1] = liveRange(); liveView = { x0, x1 }; $("c-live").hidden = false; }      // the view stops scrolling (like Pauza in the program)
  RECM.ghost = { n, t: a.t0, kind: "start" }; if (!RECM.timer) RECM.timer = setInterval(() => { if (RECM.ghost) { RECM.pulse ^= 1; MK.live.redraw(); } }, 380);
  MK.live.redraw();
}
function recmGhostManual(n) {   // 'Przenieś Manual REC (n)': a pulsing twin of its Start line; drag it, right click -> 'Przenieś … tutaj' / cancel
  const m = recmList().find((x) => x.n === n); if (!m) return;
  if (!liveView && !frozen) { const [x0, x1] = liveRange(); liveView = { x0, x1 }; $("c-live").hidden = false; }
  RECM.ghost = { n, t: m.a, kind: "manual" }; if (!RECM.timer) RECM.timer = setInterval(() => { if (RECM.ghost) { RECM.pulse ^= 1; MK.live.redraw(); } }, 380);
  MK.live.redraw();
}
function recmGhostMove() {   // the Manual REC area itself moves (nothing is written yet)
  const g = RECM.ghost, m = g && recmList().find((x) => x.n === g.n); RECM.ghost = null;
  if (m) { [m.a, m.b] = m.b === null ? [g.t, null] : g.t <= m.b ? [g.t, m.b] : [m.b, g.t]; m.saved = ""; m.rec = null; recmNotify(); }
  MK.live.redraw();
}
function recmGhostCancel() { RECM.ghost = null; MK.live.redraw(); }
async function recmGhostApply() {
  const g = RECM.ghost; if (!g) return;
  if (g.kind === "manual") return recmGhostMove();
  const a = recmAuto().find((x) => x.n === g.n); if (!a) { RECM.ghost = null; return; }
  const earlier = g.t < a.t0, ds = frozen || series;
  const ask = earlier ? `Przesunąć Start REC (${g.n}) wcześniej (${recmClock(ds, a.t0)} → ${recmClock(ds, g.t)})?\n\nDo nagrania w bazie zostanie dopisane ${(a.t0 - g.t).toFixed(1)} s danych z bufora serwera.`
    : `Przesunąć Start REC (${g.n}) później (${recmClock(ds, a.t0)} → ${recmClock(ds, g.t)})?\n\nDane tego nagrania sprzed nowego początku (${(g.t - a.t0).toFixed(1)} s) zostaną USUNIĘTE z bazy – tego nie da się cofnąć.`;
  if (!confirm(ask)) return;
  try { const d = await api(`/api/connections/${recmConn()}/rec-start`, { n: g.n, t: g.t }); RECM.ghost = null; a.t0 = d.t0; MK.live.redraw();
    if (d.clamped) alert("Bufor serwera sięgał tylko do wybranego miejsca – nagranie uzupełniono od początku bufora."); }
  catch (err) { alert("Nie udało się zmienić Start REC:\n" + err.message); }
}
function recmMenu(h, x, y) {
  const items = [];
  if (h.kind === "start") {
    if (h.a.db) items.push({ label: `Przesuń Start REC (${h.n})…`, fn: () => recmGhostStart(h.n) });
    else items.push({ label: "Przesuwanie niedostępne: nagranie do pliku CSV (tylko bazy danych)", fn: () => {} });
  } else if (h.kind === "stop") items.push({ label: `Stop REC (${h.n}) – ${recmClock(frozen || series, h.a.t1)}`, fn: () => {} });
  else if (h.kind === "ghost" && RECM.ghost && RECM.ghost.kind === "manual") items.push({ label: `Przenieś Manual Start REC (${h.n}) tutaj`, fn: recmGhostMove }, "-", { label: "Anuluj przenoszenie (usuń pulsujący znacznik)", fn: recmGhostCancel });
  else if (h.kind === "ghost") items.push({ label: `Zmień Start REC (${h.n})`, fn: recmGhostApply }, { label: "Anuluj przesuwanie", fn: recmGhostCancel });
  else {
    const m = h.m;
    items.push({ label: `Zapis Manual REC (${m.n})`, fn: () => recmSave(m.n) });
    items.push({ label: (RECM.unlocked.has(m.n) ? "✓ " : "") + "Zmień pozycję (przeciągnij brzegi / obszar)", fn: () => { RECM.unlocked.has(m.n) ? RECM.unlocked.delete(m.n) : RECM.unlocked.add(m.n); MK.live.redraw(); } },
      { label: `Przenieś Manual REC (${m.n})`, fn: () => recmGhostManual(m.n) }, { label: `Usuń Manual REC (${m.n})`, fn: () => recmRemove(m.n) });
    if (m.saved) {
      items.push("-", { label: `zapisano: ${m.saved}`, fn: () => {} });
      if (m.rec && m.rec.rec_id && !m.rec.rec_id.startsWith("csv|")) items.push({ label: `Otwórz Manual REC (${m.n}): nagranie ${m.rec.rec_id.split("|")[1] || m.rec.rec_id}`, fn: () => gotoMarker(m.rec) });   // the recordings page, like a marker of a recording
    }
  }
  mkMenu(x, y, items);
}
function recmPlaces() {   // every REC mark that can be shown: [name, chart time], by time
  const out = [], ds = frozen || series;
  for (const a of recmAuto()) { out.push([`Start REC (${a.n})`, a.t0]); if (a.t1 !== null && a.t1 !== undefined) out.push([`Stop REC (${a.n})`, a.t1]); }
  for (const m of recmList()) { out.push([`Manual Start REC (${m.n})`, m.a]); if (m.b !== null) out.push([`Manual Stop REC (${m.n})`, m.b]); }
  for (const g of recmGaps()) out.push([`Stop odczytu (${g.n})`, g.t0], [`Start odczytu (${g.n})`, g.t1]);
  return out.sort((x, y) => x[1] - y[1]).map(([name, t]) => ({ label: `${name} – ${recmClock(ds, t)}`, fn: () => recmShow(t) }));
}
function recmShow(t) {   // 'Pokaż…': the view stops scrolling (like Pauza in the program) and moves to the mark
  const cv = $("canvas"), [x0, x1] = liveRange(), gm = cv?._geo?.gm || null, w = gmD(gm, x1) - gmD(gm, x0), dc = gmD(gm, t);          // (the width counts scanned time)
  if (cv && cv._cx && cv._cx.cfg.setRange) cv._cx.cfg.setRange(gmR(gm, dc - w / 2), gmR(gm, dc + w / 2, true));
  MK.live.redraw();
}
function recmChartItems(t) {   // the REC part of the menu of the empty chart
  const open = recmList().find((m) => m.b === null), ok = (frozen || series).t.length > 0;
  if (!ok) return [];
  return ["-", open ? { label: `Manual Stop REC (${open.n}) tutaj`, fn: () => recmPlace(t) } : { label: `Manual Start REC (${Math.max(0, ...recmList().map((m) => m.n)) + 1}) tutaj`, fn: () => recmPlace(t) },
    ...(open ? [{ label: `Przenieś Manual Start REC (${open.n})`, fn: () => recmGhostManual(open.n) }, { label: `Usuń Manual Start REC (${open.n})`, fn: () => recmRemove(open.n) }] : []),
    { label: "Pokaż…", sub: recmPlaces() }];
}
function recmAttach(cv) {   // before mkAttach: these handlers run first and take the mouse when it is over a REC mark
  cv.addEventListener("contextmenu", (e) => {
    if (typeof cxTagAt === "function" && cxTagAt(cv, e)) return;      // a name label over the area: its menu (chartx.js) comes first
    const h = recmHit(cv, e); if (!h) return;
    e.preventDefault(); e.stopImmediatePropagation(); mkBubble(""); recmMenu(h, e.clientX, e.clientY);
  }, true);
  cv.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    const h = recmHit(cv, e); if (!h) return;
    if (h.kind === "ghost") RECM.drag = { kind: "ghost", n: h.n, px0: h.px, o0: RECM.ghost.t, a: RECM.ghost.t };
    else if (h.kind === "manual" && RECM.unlocked.has(h.n)) RECM.drag = { kind: "manual", n: h.n, part: h.part, px0: h.px, o0: h.m.a, o1: h.m.b ?? h.m.a, a: h.m.a, b: h.m.b ?? h.m.a };
    else return;
    e.stopImmediatePropagation(); e.preventDefault();
  }, true);
  window.addEventListener("mousemove", (e) => {
    const d = RECM.drag; if (!d) return;
    const dt = mkTimeAt(MK.live, mkPx(MK.live, e)) - mkTimeAt(MK.live, d.px0);
    if (d.kind === "ghost") d.a = d.o0 + dt;
    else if (d.part === "a") d.a = d.o0 + dt; else if (d.part === "b") d.b = d.o1 + dt; else { d.a = d.o0 + dt; d.b = d.o1 + dt; }
    MK.live.redraw();
  });
  window.addEventListener("mouseup", () => {
    const d = RECM.drag; if (!d) return; RECM.drag = null;
    if (d.kind === "ghost") { if (RECM.ghost) RECM.ghost.t = d.a; }
    else { const m = recmList().find((x) => x.n === d.n); if (m) { const open = m.b === null; [m.a, m.b] = open ? [d.a, null] : d.a <= d.b ? [d.a, d.b] : [d.b, d.a]; m.saved = ""; } }
    recmNotify();
  });
}
