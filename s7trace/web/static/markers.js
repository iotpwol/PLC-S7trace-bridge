"use strict";
// S7Trace web mode: markers (bookmarks) on the charts, the list of markers and the value search.
// Loaded BEFORE app.js; uses its helpers ($, esc, api, fmtTime ...) only when called.
const MK_STYLES = { solid: [], dash: [8, 5], dot: [2, 4], dashdot: [8, 4, 2, 4] };
const MK_STYLE_PL = { solid: "ciągła", dash: "kreskowana", dot: "kropkowana", dashdot: "kreska-kropka" };
const MK_PRIO_PL = ["Niski", "Normalny", "Wysoki", "Krytyczny"];
const MK_PALETTE = ["#ff9f1c", "#ff4d4d", "#3fc380", "#4aa3ff", "#b07cff", "#ffd24a", "#2ec4b6", "#ffffff"];
const mkWidth = (m) => m.line_width || [1, 2, 3, 4][m.priority] || 2;
const mkStamp = (us) => { if (!us) return "–"; const d = new Date(us / 1000), p = (n, l = 2) => String(n).padStart(l, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`; };
const mkInput = (us) => mkStamp(us).replace(" ", "T");              // value of <input type=datetime-local step=0.001>
const mkFromInput = (v, old) => { const ms = new Date(v).getTime(); return old && Math.floor(old / 1000) === ms ? old : ms * 1000; };
const mkDur = (s) => s < 1 ? Math.round(s * 1000) + " ms" : s < 120 ? s.toFixed(2) + " s" : s < 7200 ? Math.floor(s / 60) + " min " + Math.round(s % 60) + " s" : Math.floor(s / 3600) + " h " + Math.floor(s % 3600 / 60) + " min";

function mkTip(m) {
  const rows = [`<b>${esc(m.title || "(bez tytułu)")}</b> <span style="color:${esc(m.color)}">■</span>`,
    m.kind === "range" ? `Zakres: ${mkStamp(m.at_us)} → ${mkStamp(m.end_us)} (${mkDur((m.end_us - m.at_us) / 1e6)})` : `Czas: ${mkStamp(m.at_us)}`,
    `Priorytet: ${MK_PRIO_PL[m.priority] || m.priority}`, "Dotyczy: " + (m.signals.length ? esc(m.signals.join(", ")) : "wszystkich przebiegów"),
    `Linia: ${mkWidth(m)} px, ${MK_STYLE_PL[m.line_style] || m.line_style}` + (m.kind === "range" ? `; przezroczystość obszaru ${100 - m.opacity} %` : "")];
  if (m.group_name) rows.push(`Grupa: <b>${esc(m.group_name)}</b>`);
  if (m.description) rows.push(esc(m.description).replace(/\n/g, "<br>"));
  if (m.notes) rows.push("<i>Uwagi:</i> " + esc(m.notes).replace(/\n/g, "<br>"));
  const st = mkdState(m.id);
  if (st) rows.splice(1, 0, `<span style="color:#e0a030">✱ niezapisany (${st === "new" ? "nowy" : "zmieniony"}) – użyj „Zapisz znaczniki”</span>`);
  rows.push(`Autor: ${esc(m.author || "–")} · założono ${mkStamp(m.created_us).slice(0, 19)}`);
  rows.push(`Zmieniono: ${mkStamp(m.modified_us).slice(0, 19)}${m.modified_by ? " (" + esc(m.modified_by) + ")" : ""}`);
  return rows.join("<br>");
}


// ---------------------------------------------------------------- unsaved changes (the draft)
// A marker put on a chart (or edited / deleted there) is only a DRAFT in this page until "Zapisz znaczniki": the page keeps new,
// changed and deleted markers on top of what the server returns and sends everything in one batch (POST /api/markers, action batch).
const MKD_FIELDS = ["kind", "at_us", "end_us", "signals", "group_name", "line_width", "line_style", "opacity", "show_label", "title", "description", "notes", "color", "priority"];
const MKD_LABEL = { title: "tytuł", description: "opis", notes: "uwagi", color: "kolor", priority: "priorytet", kind: "rodzaj", at_us: "czas", end_us: "czas", signals: "przebiegi",
  group_name: "grupa", line_width: "grubość linii", line_style: "rodzaj linii", opacity: "przezroczystość", show_label: "nazwa na wykresie" };
const MKD = { added: new Map(), edited: new Map(), deleted: new Map(), orig: new Map(), seq: 0 };
const mkdCount = () => MKD.added.size + MKD.edited.size + MKD.deleted.size;
const mkdState = (id) => MKD.added.has(id) ? "new" : MKD.deleted.has(id) ? "deleted" : MKD.edited.has(id) ? "edited" : "";
const mkdChanged = (a, b) => MKD_FIELDS.filter((f) => JSON.stringify(a[f]) !== JSON.stringify(b[f]));
const MKD_PL = { new: "nowy", edited: "zmieniony", deleted: "do usunięcia" };
function mkdAdd(m) {
  const id = --MKD.seq, now = Date.now() * 1000, opt = m.conn && [...document.querySelectorAll("#c-conn option")].find((o) => o.value === m.conn);
  MKD.added.set(id, { ...m, id, author: me.user, modified_by: me.user, created_us: now, modified_us: now, can_edit: true,
    conn_name: opt ? opt.textContent.replace(/ \(.*\)$/, "") : "" });
  mkdNotify(); return MKD.added.get(id);
}
function mkdUpdate(m, f) {   // m = the marker as shown now (new or saved), f = the changed fields
  const eff = { ...m, ...f, modified_us: Date.now() * 1000, modified_by: me.user };
  if (eff.kind !== "range") eff.end_us = 0; else if (eff.end_us < eff.at_us) [eff.at_us, eff.end_us] = [eff.end_us, eff.at_us];
  if (m.id < 0) MKD.added.set(m.id, eff);
  else {
    const base = MKD.orig.get(m.id) || m;
    if (!mkdChanged(base, eff).length) { MKD.edited.delete(m.id); MKD.orig.delete(m.id); } else { MKD.orig.set(m.id, base); MKD.edited.set(m.id, eff); }
  }
  mkdNotify(); return eff;
}
function mkdDelete(m) {
  if (m.id < 0) MKD.added.delete(m.id); else { MKD.deleted.set(m.id, MKD.orig.get(m.id) || m); MKD.edited.delete(m.id); MKD.orig.delete(m.id); }
  mkdNotify();
}
function mkdRevert(id) { MKD.added.delete(id); MKD.edited.delete(id); MKD.deleted.delete(id); MKD.orig.delete(id); mkdNotify(); }
function mkdDiscard() { MKD.added.clear(); MKD.edited.clear(); MKD.deleted.clear(); MKD.orig.clear(); mkdNotify(); }
function mkdOverlay(list, pred) {   // the saved markers + the draft: deleted ones out, edited ones replaced, new ones in
  const out = [];
  for (const m of list || []) { if (MKD.deleted.has(m.id)) continue; const e = MKD.edited.get(m.id); if (e && !pred(e)) continue; out.push(e || m); }
  for (const m of MKD.added.values()) if (pred(m)) out.push(m);
  return out;
}
function mkdChanges() {   // what "Zapisz znaczniki" is going to do
  const t = (m) => m.at_us, out = [];
  for (const m of [...MKD.added.values()].sort((a, b) => t(a) - t(b))) out.push({ state: "new", m, text: (m.kind === "range" ? "zakres czasu" : "punkt") + (m.group_name ? `; grupa „${m.group_name}”` : "") });
  for (const m of [...MKD.edited.values()].sort((a, b) => t(a) - t(b))) out.push({ state: "edited", m, text: "zmieniono: " + [...new Set(mkdChanged(MKD.orig.get(m.id), m).map((f) => MKD_LABEL[f]))].join(", ") });
  for (const m of [...MKD.deleted.values()].sort((a, b) => t(a) - t(b))) out.push({ state: "deleted", m, text: "zostanie usunięty z serwera" });
  return out;
}
function mkdNotify() {   // everything that shows markers is redrawn from the draft
  const b = $("mk-pending"), n = mkdCount();
  if (b) { b.hidden = !n || !me; b.textContent = `Zapisz znaczniki (${n})`; }
  for (const c of Object.values(MK)) if (c) { c.marks = mkdOverlay(c.srv, c.pred); if (c.hiGroup) c.hi = new Set(c.marks.filter((m) => m.group_name === c.hiGroup).map((m) => m.id)); c.redraw(); }
  if (typeof view !== "undefined" && view === "markers" && $("t-mkl")) refreshMarkers();
}
async function mkdCommit() {
  const pick = (m, fs) => Object.fromEntries(fs.map((f) => [f, m[f]]));
  const adds = [...MKD.added.values()].map((m) => ({ tmp: m.id, at_us: m.at_us, conn: m.conn || "", rec_id: m.rec_id || "", ...pick(m, MKD_FIELDS.filter((f) => f !== "at_us")) }));
  const updates = [...MKD.edited.values()].map((m) => ({ id: m.id, ...pick(m, mkdChanged(MKD.orig.get(m.id), m)) }));
  const d = await api("/api/markers", { action: "batch", adds, updates, deletes: [...MKD.deleted.keys()] });
  mkdDiscard();
  for (const c of Object.values(MK)) if (c && c.reload) try { await c.reload(); } catch (e) { /* the data are saved; a chart that is not open reloads later */ }
  return d;
}
function mkPendingDialog(mode) {   // mode "save": Zapisz / Anuluj; "close": Zapisz / Odrzuć / Wróć. Resolves "save" (already written), "discard" or "cancel"
  return new Promise((resolve) => {
    const dlg = $("mk-pend"), ch = mkdChanges(), n = (s) => ch.filter((c) => c.state === s).length;
    $("mkp-h").textContent = mode === "save" ? "Zapisz znaczniki" : "Niezapisane znaczniki";
    $("mkp-intro").innerHTML = (mode === "save" ? "Do zapisania: " : "Są niezapisane znaczniki. Zapisać je, zanim opuścisz wykres? Razem: ") +
      `<b>${n("new")}</b> nowych, <b>${n("edited")}</b> zmienionych, <b>${n("deleted")}</b> do usunięcia.`;
    $("mkp-t").tBodies[0].innerHTML = ch.map((c) => `<tr class="mkp-${c.state}"><td>${MKD_PL[c.state]}</td><td><span style="color:${esc(c.m.color)}">■</span> ${c.state === "deleted" ? "<s>" : ""}${esc(c.m.title || "(bez tytułu)")}${c.state === "deleted" ? "</s>" : ""}</td>
      <td>${mkStamp(c.m.at_us)}${c.m.kind === "range" ? " → " + mkStamp(c.m.end_us) : ""}</td><td>${esc(c.text)}</td></tr>`).join("");
    $("mkp-error").textContent = ""; $("mkp-discard").hidden = mode !== "close"; $("mkp-cancel").textContent = mode === "save" ? "Anuluj" : "Wróć do wykresu";
    const done = (v) => { dlg.close(); resolve(v); };
    $("mkp-save").onclick = async () => { $("mkp-error").textContent = ""; try { await mkdCommit(); done("save"); } catch (err) { $("mkp-error").textContent = "Nie zapisano (nic nie zostało zmienione): " + err.message; } };
    $("mkp-discard").onclick = () => { mkdDiscard(); done("discard"); };
    $("mkp-cancel").onclick = () => done("cancel");
    dlg.oncancel = () => resolve("cancel");
    dlg.showModal();
  });
}
async function mkSave() {
  if (!mkdCount()) { alert("Nie ma niezapisanych znaczników."); return true; }
  return (await mkPendingDialog("save")) === "save";
}
async function mkConfirmLeave() { return !mkdCount() || (await mkPendingDialog("close")) !== "cancel"; }
window.addEventListener("beforeunload", (e) => { if (mkdCount()) { e.preventDefault(); e.returnValue = ""; } });
document.addEventListener("DOMContentLoaded", () => { const b = $("mk-pending"); if (b) b.addEventListener("click", () => mkSave()); });

// ---------------------------------------------------------------- small UI pieces: context menu, bubble
function mkMenu(x, y, items) {
  const box = $("ctx"); box.innerHTML = "";
  for (const it of items) {
    if (it === "-") { box.appendChild(document.createElement("hr")); continue; }
    const b = document.createElement("button"); b.textContent = it.label; b.onclick = () => { mkMenuClose(); it.fn(); }; box.appendChild(b);
  }
  box.hidden = false; box.style.left = Math.min(x, innerWidth - 260) + "px"; box.style.top = Math.min(y, innerHeight - box.offsetHeight - 8) + "px";
}
function mkMenuClose() { $("ctx").hidden = true; }
document.addEventListener("click", (e) => { if (!e.target.closest("#ctx")) mkMenuClose(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { mkMenuClose(); for (const c of Object.values(MK)) if (c) c.place = null; } });
function mkBubble(html, x, y) {
  const b = $("bubble"); if (!html) { b.hidden = true; return; }
  b.innerHTML = html; b.hidden = false; b.style.left = Math.min(x + 14, innerWidth - 340) + "px"; b.style.top = (y + 14) + "px";
}

// ---------------------------------------------------------------- the dialog of one marker
let mkDlgDone = null;
function mkOpenDialog(m, o) {   // m = marker (id 0 = new), o = {names: [signal names], groups: [...], readonly}
  return new Promise((resolve) => {
    const dlg = $("mk-dlg"), f = $("mk-form"), ro = !!o.readonly;
    $("mk-title").value = m.title || ""; $("mk-desc").value = m.description || ""; $("mk-notes").value = m.notes || "";
    $("mk-kind").value = m.kind; $("mk-from").value = mkInput(m.at_us); $("mk-to").value = mkInput(m.end_us || m.at_us);
    $("mk-color").value = m.color; $("mk-prio").value = m.priority; $("mk-width").value = m.line_width || 0; $("mk-style").value = m.line_style;
    $("mk-transp").value = 100 - m.opacity; $("mk-transp-v").textContent = (100 - m.opacity) + " %";
    $("mk-label").checked = m.show_label !== 0;
    $("mk-group").value = m.group_name || ""; $("mk-groups").innerHTML = (o.groups || []).map((g) => `<option value="${esc(g)}">`).join("");
    const names = [...new Set([...(o.names || []), ...m.signals])];
    $("mk-sigs").innerHTML = names.map((n) => `<label><input type="checkbox" value="${esc(n)}" ${m.signals.includes(n) ? "checked" : ""}> ${esc(n)}</label>`).join("") || '<span class="muted">(brak listy przebiegów)</span>';
    $("mk-all").checked = !m.signals.length; $("mk-sel").checked = !!m.signals.length;
    const kindUi = () => { const r = $("mk-kind").value === "range"; $("mk-to-l").hidden = !r; $("mk-transp-l").hidden = !r; };
    kindUi(); $("mk-kind").onchange = kindUi;
    $("mk-transp").oninput = () => { $("mk-transp-v").textContent = $("mk-transp").value + " %"; };
    $("mk-info").innerHTML = m.id < 0 ? "Znacznik jest jeszcze niezapisany – zapisze go „Zapisz znaczniki”. Autor i daty ustawią się przy zapisie."
      : m.id ? `Założono: <b>${mkStamp(m.created_us).slice(0, 19)}</b>, autor: <b>${esc(m.author)}</b><br>Zmieniono: <b>${mkStamp(m.modified_us).slice(0, 19)}</b>, przez: <b>${esc(m.modified_by || "–")}</b>`
      : "Autor i daty założenia / modyfikacji zapiszą się automatycznie.";
    $("mk-title-h").textContent = ro ? "Znacznik (tylko odczyt)" : m.id ? "Edycja znacznika" : "Nowy znacznik";
    f.querySelectorAll("input,textarea,select").forEach((el) => { el.disabled = ro; });
    $("mk-save").hidden = ro; $("mk-delete").hidden = ro || !m.id; $("mk-error").textContent = "";
    const finish = (v) => { dlg.close(); resolve(v); };
    f.onsubmit = async (e) => {
      e.preventDefault();
      const r = $("mk-kind").value === "range", body = { title: $("mk-title").value.trim(), description: $("mk-desc").value, notes: $("mk-notes").value,
        kind: $("mk-kind").value, at_us: mkFromInput($("mk-from").value, m.at_us), end_us: r ? mkFromInput($("mk-to").value, m.end_us) : 0,
        color: $("mk-color").value, priority: +$("mk-prio").value, line_width: +$("mk-width").value, line_style: $("mk-style").value,
        opacity: r ? 100 - +$("mk-transp").value : m.opacity, group_name: $("mk-group").value.trim(), show_label: $("mk-label").checked ? 1 : 0,
        signals: $("mk-sel").checked ? [...$("mk-sigs").querySelectorAll("input:checked")].map((x) => x.value) : [] };
      if (!Number.isFinite(body.at_us) || (r && !Number.isFinite(body.end_us))) { $("mk-error").textContent = "Podaj poprawny czas."; return; }
      finish(m.id ? mkdUpdate(m, body) : mkdAdd({ ...m, ...body }));
    };
    $("mk-cancel").onclick = () => finish(null);
    $("mk-delete").onclick = () => { mkdDelete(m); finish({ deleted: m.id }); };
    dlg.oncancel = () => resolve(null);
    dlg.showModal();
  });
}
const mkBlank = (at_us, extra) => ({ id: 0, kind: "point", at_us, end_us: 0, signals: [], group_name: "", line_width: 0, line_style: "solid", opacity: 24, show_label: 1,
  title: "", description: "", notes: "", color: MK_PALETTE[0], priority: 1, author: "", modified_by: "", conn: "", rec_id: "", ...extra });
async function mkGroups() {
  let names = []; try { names = (await api("/api/markers?limit=1")).groups.map((g) => g.name); } catch (e) { /* the draft names are still offered */ }
  for (const m of [...MKD.added.values(), ...MKD.edited.values()]) if (m.group_name && !names.includes(m.group_name)) names.push(m.group_name);
  return names;
}

// ---------------------------------------------------------------- charts: drawing + mouse interaction
// A context describes one chart: {cv, kind, marks, hi:Set, place, drag, ds(), startUs(), target(), canAdd(), redraw(), reload()}
const MK = { live: null, rec: null };
function mkDrawable(ctx) {   // marks with their times as seconds on the chart's own axis
  const s0 = ctx.startUs();
  return ctx.marks.map((m) => {
    let x0 = (m.at_us - s0) / 1e6, x1 = m.kind === "range" ? (m.end_us - s0) / 1e6 : x0;
    if (ctx.drag && ctx.drag.m.id === m.id) { x0 = ctx.drag.x0; x1 = ctx.drag.x1; }
    return { m, x0, x1 };
  });
}
function mkPaint(g, cv, ctx, geo, lanes) {   // lanes: [{top, bot}] one per signal in order (same as drawChart)
  if (!ctx) return;
  const items = mkDrawable(ctx), names = ctx.ds().names, { t0, t1, pad, W, H } = geo, X = (t) => pad.l + (t - t0) / ((t1 - t0) || 1) * (W - pad.l - pad.r);
  const col = (it) => ctx.hi.has(it.m.id) || (ctx.place === it.m.id) ? "#ffffff" : it.m.color;
  const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${n >> 8 & 255},${n & 255},${a})`; };
  g.save(); g.font = "11px sans-serif";
  items.forEach((it, idx) => {
    const m = it.m, a = X(it.x0), b = X(it.x1), c = col(it), w = ctx.hi.has(m.id) ? mkWidth(m) + 2 : mkWidth(m);
    if ((it.x1 < t0 && it.x0 < t0) || (it.x0 > t1 && it.x1 > t1)) return;
    const idxs = m.signals.length ? names.map((n, k) => m.signals.includes(n) ? k : -1).filter((k) => k >= 0) : null;
    const op = ctx.hi.has(m.id) ? 0.4 : m.opacity / 100;
    if (m.kind === "range") {
      g.fillStyle = rgba(c, op);
      if (idxs) idxs.forEach((k) => g.fillRect(a, lanes[k].top, b - a, lanes[k].bot - lanes[k].top)); else g.fillRect(a, pad.t, b - a, H - pad.t - pad.b);
    }
    g.strokeStyle = idxs ? rgba(c, 0.5) : c; g.lineWidth = idxs ? 1 : w; g.setLineDash(MK_STYLES[m.line_style] || []);
    for (const x of m.kind === "range" ? [a, b] : [a]) { g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, H - pad.b); g.stroke(); }
    if (idxs && m.kind === "point") { g.strokeStyle = c; g.lineWidth = w + 2; idxs.forEach((k) => { g.beginPath(); g.moveTo(a, lanes[k].top); g.lineTo(a, lanes[k].bot); g.stroke(); }); }
    g.setLineDash([]); g.fillStyle = c;
    if (m.show_label !== 0 && m.title) g.fillText((mkdState(m.id) ? "✱ " : "") + m.title.slice(0, 28), a + 4, pad.t + 12 + (idx % 3) * 12);
  });
  g.restore();
}
function mkHit(ctx, ev) {   // the marker (and its part) under the mouse
  const cv = ctx.cv, geo = cv._geo; if (!geo) return null;
  const r = cv.getBoundingClientRect(), px = (ev.clientX - r.left) * cv.width / r.width, X = (t) => geo.pad.l + (t - geo.t0) / ((geo.t1 - geo.t0) || 1) * (geo.W - geo.pad.l - geo.pad.r);
  let best = null;
  for (const it of mkDrawable(ctx).reverse()) {
    const a = X(it.x0), b = X(it.x1);
    if (it.m.kind === "point") { if (Math.abs(px - a) <= 6) return { it, part: "x0", px }; }
    else if (Math.abs(px - a) <= 6) return { it, part: "x0", px };
    else if (Math.abs(px - b) <= 6) return { it, part: "x1", px };
    else if (px > a && px < b && !best) best = { it, part: "body", px };
  }
  return best;
}
const mkTimeAt = (ctx, px) => { const g = ctx.cv._geo; return g.t0 + (px - g.pad.l) / (g.W - g.pad.l - g.pad.r) * (g.t1 - g.t0); };
const mkPx = (ctx, ev) => { const r = ctx.cv.getBoundingClientRect(); return (ev.clientX - r.left) * ctx.cv.width / r.width; };

function mkAttach(ctx) {
  const cv = ctx.cv;
  cv.addEventListener("mousedown", (e) => {
    if (e.button !== 0 || !ctx.marks.length) return;
    if (ctx.place) return;
    const h = mkHit(ctx, e); if (!h || !ctx.canEdit(h.it.m)) return;
    e.stopImmediatePropagation(); e.preventDefault();
    ctx.drag = { m: h.it.m, part: h.part, px0: h.px, x0: h.it.x0, x1: h.it.x1, o0: h.it.x0, o1: h.it.x1, moved: false };
  }, true);
  window.addEventListener("mousemove", (e) => {
    const d = ctx.drag; if (!d) return;
    const dt = mkTimeAt(ctx, mkPx(ctx, e)) - mkTimeAt(ctx, d.px0);
    if (Math.abs(mkPx(ctx, e) - d.px0) > 2) d.moved = true;
    if (d.m.kind === "point") { d.x0 = d.x1 = d.o0 + dt; }
    else if (d.part === "x0") { d.x0 = d.o0 + dt; }
    else if (d.part === "x1") { d.x1 = d.o1 + dt; }
    else { d.x0 = d.o0 + dt; d.x1 = d.o1 + dt; }
    ctx.redraw();
  });
  window.addEventListener("mouseup", async () => {
    const d = ctx.drag; if (!d) return; ctx.drag = null;
    if (!d.moved) { ctx.redraw(); return; }
    const s0 = ctx.startUs(), body = { at_us: Math.round(s0 + Math.min(d.x0, d.x1) * 1e6) };
    if (d.m.kind === "range") body.end_us = Math.round(s0 + Math.max(d.x0, d.x1) * 1e6);
    mkdUpdate(d.m, body);
  });
  cv.addEventListener("mousemove", (e) => {
    if (ctx.drag) { mkBubble(""); return; }
    const h = ctx.marks.length ? mkHit(ctx, e) : null;
    cv.style.cursor = ctx.place ? "crosshair" : h && ctx.canEdit(h.it.m) ? (h.part === "body" ? "move" : "col-resize") : "";
    mkBubble(h ? mkTip(h.it.m) : "", e.clientX, e.clientY);
  });
  cv.addEventListener("mouseleave", () => mkBubble(""));
  cv.addEventListener("click", async (e) => {
    if (!ctx.place || !cv._geo) return;
    const m = ctx.marks.find((x) => x.id === ctx.place); ctx.place = null; cv.style.cursor = "";
    if (!m) return;
    const s0 = ctx.startUs(), t = mkTimeAt(ctx, mkPx(ctx, e)), at = Math.round(s0 + t * 1e6), half = m.kind === "range" ? Math.round((m.end_us - m.at_us) / 2) : 0;
    const body = { at_us: at - half }; if (m.kind === "range") body.end_us = at + (m.end_us - m.at_us - half);
    mkdUpdate(m, body);
  });
  cv.addEventListener("contextmenu", (e) => {
    e.preventDefault(); mkBubble("");
    if (ctx.place) { ctx.place = null; cv.style.cursor = ""; ctx.redraw(); return; }
    const h = ctx.marks.length ? mkHit(ctx, e) : null;
    if (h) return mkMarkerMenu(ctx, h.it.m, e.clientX, e.clientY);
    if (!ctx.canAdd() || !cv._geo) return;
    const s0 = ctx.startUs(), t = mkTimeAt(ctx, mkPx(ctx, e)), at = Math.round(s0 + t * 1e6), w = Math.max((cv._geo.t1 - cv._geo.t0) * 0.1, 0.5);
    mkMenu(e.clientX, e.clientY, [
      { label: "Dodaj znacznik (punkt) tutaj…", fn: () => mkAdd(ctx, mkBlank(at)) },
      { label: "Dodaj znacznik zakresu czasu tutaj…", fn: () => mkAdd(ctx, mkBlank(at, { kind: "range", end_us: Math.round(at + w * 1e6) })) },
      ...(ctx.hi.size ? ["-", { label: "Wyłącz podświetlenie grupy", fn: () => { ctx.hi = new Set(); ctx.hiGroup = ""; ctx.redraw(); } }] : []),
      "-", { label: mkdCount() ? `Zapisz znaczniki (${mkdCount()})…` : "Zapisz znaczniki (brak zmian)", fn: () => mkSave() }]);
  });
}
async function mkAdd(ctx, m) {   // the marker joins the draft (see above); nothing is sent to the server yet
  await mkOpenDialog({ ...m, ...ctx.target() }, { names: ctx.ds().names, groups: await mkGroups() });
}
function mkMarkerMenu(ctx, m, x, y) {
  const ed = ctx.canEdit(m), items = [];
  items.push({ label: ed ? "Edytuj znacznik…" : "Szczegóły znacznika…", fn: async () => { await mkOpenDialog(m, { names: ctx.ds().names, groups: await mkGroups(), readonly: !ed }); } });
  if (ed) items.push({ label: "Zmień pozycję znacznika", fn: () => { ctx.place = m.id; ctx.cv.style.cursor = "crosshair"; ctx.redraw(); } });
  if (ed) items.push({ label: m.show_label === 0 ? "Pokaż nazwę znacznika na wykresie" : "Ukryj nazwę znacznika na wykresie", fn: () => mkdUpdate(m, { show_label: m.show_label === 0 ? 1 : 0 }) });
  if (ed) items.push({ label: m.group_name ? "Przenieś do innej grupy…" : "Dodaj do grupy…", fn: () => mkGroupDialog(ctx, [m]) });
  if (m.group_name) {
    if (ed) items.push({ label: `Usuń z grupy „${m.group_name}”`, fn: () => mkdUpdate(m, { group_name: "" }) });
    items.push("-", { label: "Podświetl całą grupę", fn: () => { ctx.hiGroup = m.group_name; ctx.hi = new Set(ctx.marks.filter((k) => k.group_name === m.group_name).map((k) => k.id)); ctx.redraw(); } },
      { label: "Przejdź do następnego znacznika grupy", fn: () => mkStep(ctx, m, 1) }, { label: "Przejdź do poprzedniego znacznika grupy", fn: () => mkStep(ctx, m, -1) });
    if (ed) items.push({ label: "Zmień nazwę grupy…", fn: () => mkRenameGroup(m.group_name) });
  }
  if (mkdState(m.id)) items.push("-", { label: "Cofnij zmiany tego znacznika (niezapisane)", fn: () => mkdRevert(m.id) });
  if (ed) items.push("-", { label: "Usuń znacznik", fn: () => mkdDelete(m) });
  if (mkdCount()) items.push("-", { label: `Zapisz znaczniki (${mkdCount()})…`, fn: () => mkSave() });
  mkMenu(x, y, items);
}
async function mkGroupDialog(ctx, ms) {   // ms = marker objects
  const names = await mkGroups(), n = prompt("Grupa znaczników – wpisz nazwę nowej albo istniejącej" + (names.length ? " (istniejące: " + names.join(", ") + ")" : "") + ":");
  if (!n || !n.trim()) return;
  if (ctx) ctx.hiGroup = n.trim();
  for (const m of ms) mkdUpdate(m, { group_name: n.trim() });
}
async function mkRenameGroup(old) {
  const n = prompt(`Nowa nazwa grupy „${old}”:`, old); if (!n || !n.trim() || n.trim() === old) return;
  const list = mkdOverlay((await api("/api/markers?group=" + encodeURIComponent(old) + "&limit=2000")).markers, (m) => (m.group_name || "").toLowerCase() === old.toLowerCase());
  for (const m of list) if (m.can_edit) mkdUpdate(m, { group_name: n.trim() });
  for (const c of Object.values(MK)) if (c && c.hiGroup === old) c.hiGroup = n.trim();
}
async function mkStep(ctx, m, dir) {
  const list = mkdOverlay((await api("/api/markers?group=" + encodeURIComponent(m.group_name) + "&limit=2000")).markers, (x) => x.group_name === m.group_name).sort((a, b) => a.at_us - b.at_us || a.id - b.id);
  const i = list.findIndex((x) => x.id === m.id), t = list[i + dir];
  if (!t) { alert("To " + (dir > 0 ? "ostatni" : "pierwszy") + ` znacznik grupy „${m.group_name}”.`); return; }
  gotoMarker(t);
}
// A marker from the list / a group: opens the chart that holds it.
async function gotoMarker(m) {
  const last = m.kind === "range" ? m.end_us : m.at_us, pad = Math.max((last - m.at_us) * 0.3, 20e6);
  if (m.rec_id) {
    const [src, id] = m.rec_id.split("|");
    go("recs"); await initRecs();
    if (![...$("rv-src").options].some((o) => o.value === src)) { alert("Źródło nagrania nie jest dostępne dla tego konta."); return; }
    $("rv-src").value = src; await refreshRecs();
    const r = rv.list.find((x) => x.id === id); if (!r) { alert("Tego nagrania nie ma już w bazie (albo jest w koszu)."); return; }
    await loadRec(id, Math.max(0, (m.at_us - r.start_us - pad) / 1e6), (last - r.start_us + pad) / 1e6);
    return;
  }
  if (!m.conn) { alert("Ten znacznik nie jest związany z połączeniem ani nagraniem."); return; }
  go("chart"); await openChart(m.conn);
  const s = await api(`/api/connections/${m.conn}/series?seconds=1`), s0 = s.start_us, f = (m.at_us - pad - s0) / 1e6, t = (last + pad - s0) / 1e6;
  const d = await api(`/api/connections/${m.conn}/series?from=${f}&to=${t}`);
  if (!d.t.length || d.t.at(-1) < (m.at_us - s0) / 1e6 - 1) { alert("Ten moment jest poza danymi, które połączenie trzyma w pamięci (tylko dane z bieżącego uruchomienia)."); return; }
  showUserFrozen(d, f, t);
}

// ---------------------------------------------------------------- the list of markers (view "Znaczniki")
let mkList = [], mkSel = new Set();
function mkMatches(m, f) {   // the filters of the list view applied to a draft marker
  const hay = [m.title, m.description, m.notes, m.author, m.group_name, m.conn_name, ...(m.signals || [])].join(" ").toLowerCase();
  if (f.q && !f.q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w))) return false;
  if (f.priority !== "" && m.priority !== +f.priority) return false;
  if (f.group !== "*" && (m.group_name || "").toLowerCase() !== f.group.toLowerCase()) return false;
  if (f.author && (m.author || "").toLowerCase() !== f.author.toLowerCase()) return false;
  if (f.from && f.to && ((m.kind === "range" ? m.end_us : m.at_us) < f.from || m.at_us > f.to)) return false;
  return true;
}
async function refreshMarkers() {
  const qs = new URLSearchParams();
  const v = (id) => $(id).value;
  if (v("mkl-q")) qs.set("q", v("mkl-q"));
  if (v("mkl-prio") !== "") qs.set("priority", v("mkl-prio"));
  if (v("mkl-group") !== "*") qs.set("group", v("mkl-group"));
  if (v("mkl-author")) qs.set("author", v("mkl-author"));
  if ($("mkl-range").checked && v("mkl-from") && v("mkl-to")) { qs.set("from", mkFromInput(v("mkl-from"))); qs.set("to", mkFromInput(v("mkl-to"))); }
  qs.set("order", v("mkl-order")); qs.set("limit", 1000);
  let d; try { d = await api("/api/markers?" + qs); } catch (e) { $("mkl-msg").textContent = "Błąd: " + e.message; return; }
  const flt = { q: v("mkl-q"), priority: v("mkl-prio"), group: v("mkl-group"), author: v("mkl-author"),
    from: $("mkl-range").checked && v("mkl-from") && v("mkl-to") ? mkFromInput(v("mkl-from")) : 0, to: $("mkl-range").checked && v("mkl-to") ? mkFromInput(v("mkl-to")) : 0 };
  const rows = d.markers.map((m) => MKD.deleted.has(m.id) ? m : MKD.edited.has(m.id) ? (mkMatches(MKD.edited.get(m.id), flt) ? MKD.edited.get(m.id) : null) : m).filter(Boolean);
  for (const m of MKD.added.values()) if (mkMatches(m, flt)) rows.push(m);
  const ord = v("mkl-order"); rows.sort(ord === "modified" ? (a, b) => b.modified_us - a.modified_us : ord === "priority" ? (a, b) => b.priority - a.priority || a.at_us - b.at_us : (a, b) => a.at_us - b.at_us || a.id - b.id);
  mkList = rows; mkSel = new Set([...mkSel].filter((id) => mkList.some((m) => m.id === id)));
  for (const m of MKD.added.values()) for (const k of [m.group_name]) if (k && !d.groups.some((x) => x.name === k)) d.groups.push({ name: k, count: 1 });
  const g = v("mkl-group"), a = v("mkl-author");
  $("mkl-group").innerHTML = `<option value="*">Grupa: każda</option><option value="">(bez grupy)</option>` + d.groups.map((x) => `<option value="${esc(x.name)}">${esc(x.name)} (${x.count})</option>`).join("");
  $("mkl-group").value = [...$("mkl-group").options].some((o) => o.value === g) ? g : "*";
  $("mkl-author").innerHTML = `<option value="">Autor: każdy</option>` + d.authors.map((x) => `<option>${esc(x)}</option>`).join("");
  $("mkl-author").value = a;
  $("mkl-author").hidden = me.role !== "admin" && d.authors.length < 2;
  $("t-mkl").tBodies[0].innerHTML = mkList.map((m) => { const st = mkdState(m.id); return `<tr data-id="${m.id}" class="${st ? "mkp-" + st : ""}"><td><input type="checkbox" ${mkSel.has(m.id) ? "checked" : ""} ${m.can_edit && st !== "deleted" ? "" : "disabled"}></td>
    <td>${mkStamp(m.at_us)}</td><td><span style="color:${esc(m.color)}">■</span> <b>${st === "deleted" ? "<s>" : ""}${esc(m.title || "(bez tytułu)")}${st === "deleted" ? "</s>" : ""}</b>${st ? ` <span class="mk-state">✱ ${MKD_PL[st]}</span>` : ""}${m.description ? `<div class="muted">${esc(m.description)}</div>` : ""}</td>
    <td>${m.kind === "range" ? "Zakres (" + mkDur((m.end_us - m.at_us) / 1e6) + ")" : "Punkt"}</td><td>${MK_PRIO_PL[m.priority] || m.priority}</td><td>${esc(m.signals.join(", ") || "wszystkie")}</td>
    <td>${esc(m.group_name)}</td><td>${esc(m.author)}</td><td>${esc(m.conn_name || (m.rec_id ? "nagranie" : ""))}</td><td class="muted">${mkStamp(m.modified_us).slice(0, 19)}</td>
    <td>${m.id > 0 || !m.rec_id ? '<button data-act="go">Pokaż</button> ' : ""}<button data-act="edit">${m.can_edit && st !== "deleted" ? "Edytuj" : "Szczegóły"}</button> ${st ? '<button data-act="undo">Cofnij zmianę</button> ' : ""}${m.can_edit && st !== "deleted" ? '<button data-act="del">Usuń</button>' : ""}</td></tr>`; }).join("")
    || '<tr><td colspan="11" class="muted">Brak znaczników. Dodasz je prawym przyciskiem myszy na wykresie (Podgląd na żywo albo Nagrania).</td></tr>';
  $("mkl-msg").textContent = `Znaczników: ${mkList.length}` + (mkdCount() ? ` · niezapisanych zmian: ${mkdCount()} (przycisk „Zapisz znaczniki” u góry)` : "");
}
function initMarkersView() {
  const tb = $("t-mkl").tBodies[0];
  tb.addEventListener("click", async (e) => {
    const tr = e.target.closest("tr"); if (!tr) return; const m = mkList.find((x) => x.id === +tr.dataset.id); if (!m) return;
    if (e.target.matches("input[type=checkbox]")) { e.target.checked ? mkSel.add(m.id) : mkSel.delete(m.id); return; }
    const act = e.target.dataset.act;
    if (act === "go") gotoMarker(m);
    if (act === "edit") await mkOpenDialog(m, { names: [], groups: await mkGroups(), readonly: !m.can_edit || mkdState(m.id) === "deleted" });
    if (act === "del") mkdDelete(m);
    if (act === "undo") mkdRevert(m.id);
  });
  for (const id of ["mkl-prio", "mkl-group", "mkl-author", "mkl-order", "mkl-range", "mkl-from", "mkl-to"]) $(id).addEventListener("change", refreshMarkers);
  let tm = null; $("mkl-q").addEventListener("input", () => { clearTimeout(tm); tm = setTimeout(refreshMarkers, 250); });
  $("mkl-refresh").addEventListener("click", refreshMarkers);
  $("mkl-group-btn").addEventListener("click", () => { if (mkSel.size) mkGroupDialog(null, mkList.filter((m) => mkSel.has(m.id))); else alert("Zaznacz znaczniki (pola po lewej)."); });
  $("mkl-ungroup-btn").addEventListener("click", () => { if (!mkSel.size) return alert("Zaznacz znaczniki (pola po lewej)."); for (const m of mkList.filter((x) => mkSel.has(x.id))) mkdUpdate(m, { group_name: "" }); });
  $("mkl-save").addEventListener("click", () => mkSave());
  const now = Date.now(); $("mkl-to").value = mkInput(now * 1000); $("mkl-from").value = mkInput((now - 86400e3) * 1000);
}

// ---------------------------------------------------------------- search panel (values of signals): live connection and recordings
const MK_OPS = { "==": "jest równe", "!=": "jest różne od", ">": "jest większe niż", ">=": "jest ≥", "<": "jest mniejsze niż", "<=": "jest ≤", between: "jest w przedziale",
  outside: "jest poza przedziałem", changes: "zmienia wartość", rises: "rośnie (zbocze narastające)", falls: "maleje (zbocze opadające)", nan: "brak wartości" };
const MK_OPS_N = { between: 2, outside: 2, changes: 0, rises: 0, falls: 0, nan: 0 };
const MK_EVENTS = ["changes", "rises", "falls"];
// box: container; cfg = {names(): [...], run(body) -> result, pick(hit), mark(hit, signals, event)}
function mkSearchPanel(box, cfg) {
  box.innerHTML = `<div class="sr-rows"></div><div class="inline"><label>Trwa co najmniej [s] <input class="sr-min" type="number" min="0" step="any" value="0" style="width:90px"></label>
    <button class="sr-go">Szukaj</button><span class="sr-msg muted"></span></div><table class="sr-res" hidden><thead><tr><th>Początek</th><th>Trwa</th><th>Wartości na początku</th><th>Min … maks</th><th></th></tr></thead><tbody></tbody></table>`;
  const rows = box.querySelector(".sr-rows"); let hits = [], used = [];
  const build = () => {
    const names = cfg.names(), keep = [...rows.children].map((r) => r.querySelector(".sr-sig").value);
    rows.innerHTML = "";
    for (let i = 0; i < 3; i++) {
      const r = document.createElement("div"); r.className = "inline sr-row";
      r.innerHTML = `<span>${i ? "oraz" : "Gdy"}</span><input type="checkbox" class="sr-on" ${i === 0 ? "checked" : ""}>
        <select class="sr-sig">${names.map((n) => `<option>${esc(n)}</option>`).join("")}</select>
        <select class="sr-op">${Object.entries(MK_OPS).map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select>
        <input class="sr-a" type="number" step="any" value="0" style="width:100px"><input class="sr-b" type="number" step="any" value="0" style="width:100px">
        <input class="sr-t" type="number" step="any" min="0" value="0" title="tolerancja (± dla == i !=)" style="width:70px">`;
      if (keep[i] && names.includes(keep[i])) r.querySelector(".sr-sig").value = keep[i];
      const upd = () => { const op = r.querySelector(".sr-op").value, n = op in MK_OPS_N ? MK_OPS_N[op] : 1;
        r.querySelector(".sr-a").disabled = n < 1; r.querySelector(".sr-b").disabled = n < 2; r.querySelector(".sr-t").disabled = !["==", "!="].includes(op); };
      r.querySelector(".sr-op").onchange = upd; upd(); rows.appendChild(r);
    }
  };
  build(); box._rebuild = build;
  box.querySelector(".sr-go").onclick = async () => {
    const conds = [...rows.children].filter((r) => r.querySelector(".sr-on").checked).map((r) => ({ signal: r.querySelector(".sr-sig").value, op: r.querySelector(".sr-op").value,
      a: +r.querySelector(".sr-a").value, b: +r.querySelector(".sr-b").value, tol: +r.querySelector(".sr-t").value }));
    const msg = box.querySelector(".sr-msg"); if (!conds.length) { msg.textContent = "Zaznacz co najmniej jeden warunek."; return; }
    msg.textContent = "Szukam…"; box.querySelector(".sr-go").disabled = true;
    try { const d = await cfg.run({ conds, min_duration: +box.querySelector(".sr-min").value }); hits = d.hits; used = [...new Set(d.names)];
      msg.textContent = `Znaleziono: ${hits.length}${d.truncated ? " (pierwsze 5000)" : ""}${d.timeout ? " – przerwano po limicie czasu, wynik niepełny" : ""}.`;
      const ev = conds.some((c) => MK_EVENTS.includes(c.op)), tb = box.querySelector(".sr-res");
      tb.hidden = !hits.length;
      tb.tBodies[0].innerHTML = hits.slice(0, 500).map((h, i) => `<tr><td>${mkStamp(h.t0_us)}</td><td>${ev ? "zdarzenie" : mkDur(h.duration)}</td>
        <td>${h.values.map((x, k) => esc(conds[k].signal) + "=" + (x === null ? "–" : +x.toPrecision(6))).join(", ")}</td>
        <td>${h.vmin === null ? "–" : +h.vmin.toPrecision(6) + " … " + +h.vmax.toPrecision(6)}</td>
        <td><button data-i="${i}" data-a="show">Pokaż</button> ${cfg.mark ? `<button data-i="${i}" data-a="mark">Dodaj znacznik…</button>` : ""}</td></tr>`).join("");
      tb.dataset.event = ev ? "1" : "";
    } catch (err) { msg.textContent = "Błąd: " + err.message; }
    box.querySelector(".sr-go").disabled = false;
  };
  box.querySelector(".sr-res").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-i]"); if (!b) return; const h = hits[+b.dataset.i], ev = !!box.querySelector(".sr-res").dataset.event;
    if (b.dataset.a === "show") cfg.pick(h); else cfg.mark(h, used, ev);
  });
}
