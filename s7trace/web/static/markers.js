"use strict";
// S7Trace web mode: markers (bookmarks) on the charts, the list of markers and the value search.
// Loaded BEFORE app.js; uses its helpers ($, esc, api, fmtTime ...) only when called.
const MK_STYLES = { solid: [], dash: [8, 5], dot: [2, 4], dashdot: [8, 4, 2, 4] };
const MK_STYLE_PL = { solid: "ciągła", dash: "kreskowana", dot: "kropkowana", dashdot: "kreska-kropka" };
const MK_PRIO_PL = ["Niski", "Normalny", "Wysoki", "Krytyczny"];
const MK_PALETTE = ["#ff9f1c", "#ff4d4d", "#3fc380", "#4aa3ff", "#b07cff", "#ffd24a", "#2ec4b6", "#ffffff"];
// Line widths (Znaczniki -> Wygląd znaczników): saved on the server per account (/api/prefs), like the desktop program keeps them in
// its interface configuration.
const MK_LOOK_DEF = { width_all: 2, width_sel: 3, width_other: 1, width_hover: 4 };
const MK_LOOK_LIM = { width_all: [1, 12], width_sel: [1, 12], width_other: [1, 12], width_hover: [1, 16] };
let MKLOOK = { ...MK_LOOK_DEF };
const mkLookFrom = (raw) => { const o = { ...MK_LOOK_DEF }; for (const k of Object.keys(MK_LOOK_DEF)) if (Number.isFinite(+raw?.[k])) o[k] = Math.min(Math.max(Math.round(+raw[k]), MK_LOOK_LIM[k][0]), MK_LOOK_LIM[k][1]); return o; };
// after logging in: the account's settings come from the server (the same look in every browser)
async function mkLoadPrefs() { try { MKLOOK = mkLookFrom((await api("/api/prefs")).prefs.marker_look); for (const c of Object.values(MK)) if (c) c.redraw(); } catch (e) { /* defaults */ } }
// A marker with its own width (> 0) keeps it; 0 = from the settings. case: all / sel / other / hover
const mkWidthOf = (m, c) => { const own = m.line_width | 0; return c === "hover" ? Math.max(MKLOOK.width_hover, own + 1) : c === "other" ? MKLOOK.width_other : own || MKLOOK[c === "all" ? "width_all" : "width_sel"]; };
const mkStamp = (us) => { if (!us) return "–"; const d = new Date(us / 1000), p = (n, l = 2) => String(n).padStart(l, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`; };
const mkSpan = (m) => m.kind === "range" || m.kind === "delta";           // kinds that cover a time span (range / signal difference)
const mkInput = (us) => mkStamp(us).replace(" ", "T");              // value of <input type=datetime-local step=0.001>
const mkFromInput = (v, old) => { const ms = new Date(v).getTime(); return old && Math.floor(old / 1000) === ms ? old : ms * 1000; };
const mkDur = (s) => s < 1 ? Math.round(s * 1000) + " ms" : s < 120 ? s.toFixed(2) + " s" : s < 7200 ? Math.floor(s / 60) + " min " + Math.round(s % 60) + " s" : Math.floor(s / 3600) + " h " + Math.floor(s % 3600 / 60) + " min";

function mkTip(m) {   // the bubble: times in a monospaced table (digit under digit), changed fields highlighted yellow
  const st = mkdState(m.id), ch = new Set(st === "edited" && MKD.orig.get(m.id) ? mkdChanged(MKD.orig.get(m.id), m) : []);
  const hl = (t, ...f) => f.some((x) => ch.has(x)) ? `<span class="mk-chg">${t}</span>` : t;
  const rows = [hl(`<b>${esc(m.title || "(bez tytułu)")}</b>`, "title") + " " + hl(`<span style="color:${esc(m.color)}">■</span>`, "color")];
  if (st) rows.push(`<span style="color:#e0a030">✱ niezapisany (${st === "new" ? "nowy" : "zmieniony"}) – użyj „Zapisz znaczniki”</span>`);
  if (mkSpan(m)) rows.push(hl(`${m.kind === "delta" ? "Różnica sygnału" : "Zakres czasu"} (${mkDur((m.end_us - m.at_us) / 1e6)}):`, "kind", "at_us", "end_us") +
    `<table class="mk-t"><tr><td>Od:</td><td class="mono">${hl(mkStamp(m.at_us), "at_us", "kind")}</td></tr><tr><td>Do:</td><td class="mono">${hl(mkStamp(m.end_us), "end_us", "kind")}</td></tr></table>`);
  else rows.push(hl(`Czas: <span class="mono">${mkStamp(m.at_us)}</span>`, "at_us", "kind"));
  rows.push(hl(`Priorytet: ${MK_PRIO_PL[m.priority] || m.priority}`, "priority"));
  rows.push(hl(`Linia: ${m.line_width ? m.line_width + " px" : MKLOOK.width_all + " px (wg ustawień)"}, ${MK_STYLE_PL[m.line_style] || m.line_style}` + (m.kind === "range" ? `; przezroczystość obszaru ${100 - m.opacity} %` : ""), "line_width", "line_style", "opacity"));
  rows.push(hl("Dotyczy: " + (m.signals.length ? esc(m.signals.join(", ")) : "wszystkich przebiegów"), "signals"));
  if (m.group_name || ch.has("group_name")) rows.push(hl(`Grupa: <b>${esc(m.group_name) || "(brak)"}</b>`, "group_name"));
  if (m.show_label === 0 || ch.has("show_label")) rows.push(hl("Nazwa na wykresie: " + (m.show_label === 0 ? "ukryta" : "pokazywana"), "show_label"));
  if (m.description) rows.push(hl("<i>Opis:</i> " + esc(m.description).replace(/\n/g, "<br>"), "description")); else if (ch.has("description")) rows.push(hl("(opis usunięty)", "description"));
  if (m.notes) rows.push(hl("<i>Uwagi:</i> " + esc(m.notes).replace(/\n/g, "<br>"), "notes")); else if (ch.has("notes")) rows.push(hl("(uwagi usunięte)", "notes"));
  rows.push(`Autor: ${esc(m.author || "–")}`, `Założono: ${mkStamp(m.created_us).slice(0, 19)}`, `Zmodyfikował: ${esc(m.modified_by || "–")}`, `Zmieniono: ${mkStamp(m.modified_us).slice(0, 19)}`);
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
  if (!mkSpan(eff)) eff.end_us = 0; else if (eff.end_us < eff.at_us) [eff.at_us, eff.end_us] = [eff.end_us, eff.at_us];
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
  for (const m of [...MKD.added.values()].sort((a, b) => t(a) - t(b))) out.push({ state: "new", m, text: (m.kind === "range" ? "zakres czasu" : m.kind === "delta" ? "różnica sygnału" : "punkt") + (m.group_name ? `; grupa „${m.group_name}”` : "") });
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
      <td>${mkStamp(c.m.at_us)}${mkSpan(c.m) ? " → " + mkStamp(c.m.end_us) : ""}</td><td>${esc(c.text)}</td></tr>`).join("");
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
function mkLookOpen() {
  const dlg = $("mk-look"), keys = Object.keys(MK_LOOK_DEF), orig = { ...MKLOOK };
  for (const k of keys) { const el = $("mkw-" + k); el.min = MK_LOOK_LIM[k][0]; el.max = MK_LOOK_LIM[k][1]; el.value = MKLOOK[k]; }
  const apply = () => { for (const k of keys) { const v = Math.round(+$("mkw-" + k).value); if (Number.isFinite(v)) MKLOOK[k] = Math.min(Math.max(v, MK_LOOK_LIM[k][0]), MK_LOOK_LIM[k][1]); }
    for (const c of Object.values(MK)) if (c) c.redraw(); };
  for (const k of keys) $("mkw-" + k).oninput = apply;
  $("mkw-default").onclick = () => { for (const k of keys) $("mkw-" + k).value = MK_LOOK_DEF[k]; apply(); };
  $("mkw-cancel").onclick = () => { MKLOOK = { ...orig }; for (const c of Object.values(MK)) if (c) c.redraw(); dlg.close(); };
  $("mkw-ok").onclick = async () => { dlg.close(); try { MKLOOK = mkLookFrom((await api("/api/prefs", { marker_look: MKLOOK })).prefs.marker_look); } catch (e) { alert("Nie udało się zapisać ustawień na koncie: " + e.message); } };
  dlg.oncancel = () => { MKLOOK = { ...orig }; for (const c of Object.values(MK)) if (c) c.redraw(); };
  dlg.showModal();
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
    const sigsUi = () => {   // "Różnica sygnału" is for exactly ONE plot: the list is switched on and takes one tick
      const dl = $("mk-kind").value === "delta";
      if (dl) { $("mk-sel").checked = true; [...$("mk-sigs").querySelectorAll("input:checked")].slice(1).forEach((x) => { x.checked = false; }); }
      $("mk-all").disabled = ro || dl;
    };
    const kindUi = () => { const k = $("mk-kind").value; $("mk-to-l").hidden = k === "point"; $("mk-transp-l").hidden = k !== "range"; sigsUi(); };
    $("mk-sigs").onchange = (e) => { if ($("mk-kind").value === "delta" && e.target.checked) $("mk-sigs").querySelectorAll("input:checked").forEach((x) => { if (x !== e.target) x.checked = false; }); };
    kindUi(); $("mk-kind").onchange = kindUi;
    $("mk-transp").oninput = () => { $("mk-transp-v").textContent = $("mk-transp").value + " %"; };
    $("mk-info").innerHTML = m.id < 0 ? "Znacznik jest jeszcze niezapisany – zapisze go „Zapisz znaczniki”. Autor i daty ustawią się przy zapisie."
      : m.id ? `Założono: <b>${mkStamp(m.created_us).slice(0, 19)}</b>, autor: <b>${esc(m.author)}</b><br>Zmieniono: <b>${mkStamp(m.modified_us).slice(0, 19)}</b>, przez: <b>${esc(m.modified_by || "–")}</b>`
      : "Autor i daty założenia / modyfikacji zapiszą się automatycznie.";
    $("mk-title-h").textContent = ro ? "Znacznik (tylko odczyt)" : m.id ? "Edycja znacznika" : "Nowy znacznik";
    f.querySelectorAll("input,textarea,select").forEach((el) => { el.disabled = ro; });
    sigsUi();
    $("mk-save").hidden = ro; $("mk-delete").hidden = ro || !m.id; $("mk-error").textContent = "";
    const finish = (v) => { dlg.close(); resolve(v); };
    f.onsubmit = async (e) => {
      e.preventDefault();
      const r = $("mk-kind").value !== "point", body = { title: $("mk-title").value.trim(), description: $("mk-desc").value, notes: $("mk-notes").value,
        kind: $("mk-kind").value, at_us: mkFromInput($("mk-from").value, m.at_us), end_us: r ? mkFromInput($("mk-to").value, m.end_us) : 0,
        color: $("mk-color").value, priority: +$("mk-prio").value, line_width: +$("mk-width").value, line_style: $("mk-style").value,
        opacity: $("mk-kind").value === "range" ? 100 - +$("mk-transp").value : m.opacity, group_name: $("mk-group").value.trim(), show_label: $("mk-label").checked ? 1 : 0,
        signals: $("mk-sel").checked ? [...$("mk-sigs").querySelectorAll("input:checked")].map((x) => x.value) : [] };
      if (!Number.isFinite(body.at_us) || (r && !Number.isFinite(body.end_us))) { $("mk-error").textContent = "Podaj poprawny czas."; return; }
      if (body.kind === "delta" && body.signals.length !== 1) { $("mk-error").textContent = "Różnica sygnału dotyczy dokładnie jednego przebiegu – zaznacz go na liście „Wybrane przebiegi”."; return; }
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
    let x0 = (m.at_us - s0) / 1e6, x1 = mkSpan(m) ? (m.end_us - s0) / 1e6 : x0;
    if (ctx.drag && ctx.drag.m.id === m.id) { x0 = ctx.drag.x0; x1 = ctx.drag.x1; }
    return { m, x0, x1 };
  });
}
function mkPaint(g, cv, ctx, geo, lanes) {   // lanes: [{top, bot}] one per signal in order (same as drawChart)
  if (!ctx) return;
  const items = mkDrawable(ctx), names = ctx.ds().names, { t0, t1, pad, W, H } = geo, X = (t) => pad.l + (t - t0) / ((t1 - t0) || 1) * (W - pad.l - pad.r);
  const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${n >> 8 & 255},${n & 255},${a})`; };
  g.save(); g.font = "11px sans-serif";
  items.forEach((it, idx) => {
    const m = it.m, a = X(it.x0), b = X(it.x1), hiG = ctx.hi.has(m.id) || ctx.place === m.id, c = hiG ? "#ffffff" : m.color;
    if ((it.x1 < t0 && it.x0 < t0) || (it.x0 > t1 && it.x1 > t1)) return;
    const idxs = m.signals.length ? names.map((n, k) => m.signals.includes(n) ? k : -1).filter((k) => k >= 0) : null, hv = ctx.hover && ctx.hover.id === m.id ? ctx.hover.part : "";
    if (m.kind === "range") {
      g.fillStyle = rgba(c, hiG ? 0.4 : m.opacity / 100);
      if (idxs) idxs.forEach((k) => g.fillRect(a, lanes[k].top, b - a, lanes[k].bot - lanes[k].top)); else g.fillRect(a, pad.t, b - a, H - pad.t - pad.b);
    }
    for (const [x, part] of mkSpan(m) ? [[a, "x0"], [b, "x1"]] : [[a, "x0"]]) {
      const hov = hiG || hv === part;                                               // the line under the mouse: thicker, the marker's own colour
      g.setLineDash(hov ? [] : MK_STYLES[m.line_style] || []);
      g.strokeStyle = hov ? c : idxs ? rgba(c, 0.5) : c; g.lineWidth = hov ? mkWidthOf(m, "hover") : mkWidthOf(m, idxs ? "other" : "all");
      g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, H - pad.b); g.stroke();
      if (idxs) { g.setLineDash(MK_STYLES[m.line_style] || []); g.strokeStyle = c; g.lineWidth = hov ? mkWidthOf(m, "hover") : mkWidthOf(m, "sel");
        idxs.forEach((k) => { g.beginPath(); g.moveTo(x, lanes[k].top); g.lineTo(x, lanes[k].bot); g.stroke(); }); }
    }
    g.setLineDash([]); g.fillStyle = c;
    if (m.kind === "delta" && idxs && idxs.length === 1) mkPaintDelta(g, ctx, geo, lanes[idxs[0]], idxs[0], it, c, m);
    if (m.show_label !== 0 && m.title) g.fillText((mkdState(m.id) ? "✱ " : "") + m.title.slice(0, 28), a + 4, pad.t + 12 + (idx % 3) * 12);
  });
  g.restore();
}
function mkPaintDelta(g, ctx, geo, L, k, it, c, m) {   // 'Różnica sygnału': the level at both ends, an arrow between them and the difference of the values
  const ds = ctx.ds(), gn = (ds.gains || [])[k] || 1, of = geo.offsetMode ? (ds.offsets || [])[k] || 0 : 0, { pad, W } = geo, X = (t) => pad.l + (t - geo.t0) / ((geo.t1 - geo.t0) || 1) * (W - pad.l - pad.r);
  const at = (t) => {
    const ts = ds.t; if (!ts.length || t < ts[0]) return null;
    let lo = 0, hi = ts.length - 1; while (lo < hi) { const q = (lo + hi + 1) >> 1; if (ts[q] <= t) lo = q; else hi = q - 1; }
    const v = (ds.values[k] || [])[lo]; return v === null || v === undefined ? null : v;
  };
  const v0 = at(it.x0), v1 = at(it.x1); if (v0 === null || v1 === null || !L || !L.span) return;
  const a = X(it.x0), b = X(it.x1), Y = (v) => L.bot - (v * gn + of - L.lo) / L.span * (L.bot - L.top - 6) - 3, y0 = Y(v0), y1 = Y(v1), d = v1 - v0, num = (v) => +v.toPrecision(5);
  g.save(); g.strokeStyle = g.fillStyle = c;
  g.setLineDash([2, 3]); g.lineWidth = 1; g.beginPath(); g.moveTo(a, y0); g.lineTo(b, y0); g.stroke();
  g.setLineDash([]); g.lineWidth = Math.max(2, mkWidthOf(m, "sel")); g.beginPath(); g.moveTo(b, y0); g.lineTo(b, y1); g.stroke();
  g.fillRect(a - 3, y0 - 3, 6, 6); g.fillRect(b - 3, y1 - 3, 6, 6);
  const txt = `Δ = ${d > 0 ? "+" : ""}${num(d)}  (${num(v0)} → ${num(v1)})`, right = b > W - pad.r - 230;
  g.font = "12px sans-serif"; g.textAlign = right ? "right" : "left"; g.fillText(txt, b + (right ? -8 : 8), (y0 + y1) / 2 + 4);
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
  const cv = ctx.cv; ctx.unlocked = new Set();                                    // markers unlocked for dragging (menu: Zmień pozycję znacznika)
  cv.addEventListener("mousedown", (e) => {
    if (e.button !== 0 || !ctx.marks.length) return;
    if (ctx.place) return;
    const h = mkHit(ctx, e); if (!h || !ctx.canEdit(h.it.m) || !ctx.unlocked.has(h.it.m.id)) return;   // a locked marker: the drag pans the chart
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
    if (mkSpan(d.m)) body.end_us = Math.round(s0 + Math.max(d.x0, d.x1) * 1e6);
    mkdUpdate(d.m, body);
  });
  cv.addEventListener("mousemove", (e) => {
    if (ctx.drag) { mkBubble(""); return; }
    const h = ctx.marks.length ? mkHit(ctx, e) : null;
    cv.style.cursor = ctx.place ? "crosshair" : h && ctx.canEdit(h.it.m) && ctx.unlocked.has(h.it.m.id) ? (h.part === "body" ? "move" : "col-resize") : "";
    mkBubble(h ? mkTip(h.it.m) : "", e.clientX, e.clientY);
    const nh = h && h.part !== "body" ? { id: h.it.m.id, part: h.part } : null;           // a hovered line is drawn thicker
    if ((nh && nh.id) !== (ctx.hover && ctx.hover.id) || (nh && nh.part) !== (ctx.hover && ctx.hover.part)) { ctx.hover = nh; ctx.redraw(); }
  });
  cv.addEventListener("mouseleave", () => { mkBubble(""); if (ctx.hover) { ctx.hover = null; ctx.redraw(); } });
  cv.addEventListener("dblclick", async (e) => {      // double click on a marker = its edit window (details when it may not be edited)
    const h = ctx.marks.length ? mkHit(ctx, e) : null; if (!h) return;
    mkBubble(""); await mkOpenDialog(h.it.m, { names: ctx.ds().names, groups: await mkGroups(), readonly: !ctx.canEdit(h.it.m) });
  });
  cv.addEventListener("click", async (e) => {
    if (!ctx.place || !cv._geo) return;
    const m = ctx.marks.find((x) => x.id === ctx.place); ctx.place = null; cv.style.cursor = "";
    if (!m) return;
    const s0 = ctx.startUs(), t = mkTimeAt(ctx, mkPx(ctx, e)), at = Math.round(s0 + t * 1e6), half = mkSpan(m) ? Math.round((m.end_us - m.at_us) / 2) : 0;
    const body = { at_us: at - half }; if (mkSpan(m)) body.end_us = at + (m.end_us - m.at_us - half);
    mkdUpdate(m, body);
  });
  cv.addEventListener("contextmenu", (e) => {
    e.preventDefault(); mkBubble("");
    if (ctx.place) { ctx.place = null; cv.style.cursor = ""; ctx.redraw(); return; }
    const h = ctx.marks.length ? mkHit(ctx, e) : null;
    if (h) return mkMarkerMenu(ctx, h.it.m, e.clientX, e.clientY);
    if (!ctx.canAdd() || !cv._geo) return;
    const s0 = ctx.startUs(), t = mkTimeAt(ctx, mkPx(ctx, e)), at = Math.round(s0 + t * 1e6), w = Math.max((cv._geo.t1 - cv._geo.t0) * 0.1, 0.5);
    const r0 = cv.getBoundingClientRect(), py = (e.clientY - r0.top) * cv.height / r0.height, names = ctx.ds().names, g0 = cv._geo;      // the plot under the click
    const sig = names[g0.offsetMode ? 0 : Math.max(0, g0.lanes.findIndex((l) => py >= l.top && py <= l.bot))];
    mkMenu(e.clientX, e.clientY, [
      { label: "Dodaj znacznik (punkt) tutaj…", fn: () => mkAdd(ctx, mkBlank(at)) },
      { label: "Dodaj znacznik zakresu czasu tutaj…", fn: () => mkAdd(ctx, mkBlank(at, { kind: "range", end_us: Math.round(at + w * 1e6) })) },
      ...(sig ? [{ label: "Dodaj znacznik różnicy poziomu…", fn: () => mkAdd(ctx, mkBlank(at, { kind: "delta", end_us: Math.round(at + w * 1e6), signals: [sig] })) }] : []),
      ...(ctx.hi.size ? ["-", { label: "Wyłącz podświetlenie grupy", fn: () => { ctx.hi = new Set(); ctx.hiGroup = ""; ctx.redraw(); } }] : []),
      "-", { label: mkdCount() ? `Zapisz znaczniki (${mkdCount()})…` : "Zapisz znaczniki (brak zmian)", fn: () => mkSave() },
      { label: "Lista znaczników…", fn: () => mkOpenList(ctx) },
      { label: "Szukaj w danych…", fn: () => mkOpenSearch(ctx) },
      ...(ctx.kind === "live" ? [{ label: (ctx.showAll ? "✓ " : "") + "Pokaż też znaczniki z innych połączeń", fn: () => { ctx.showAll = !ctx.showAll; ctx.reload(); } }] : []),
      { label: "Wygląd znaczników (grubość linii)…", fn: mkLookOpen }]);
  });
}
async function mkAdd(ctx, m) {   // the marker joins the draft (see above); nothing is sent to the server yet
  await mkOpenDialog({ ...m, ...ctx.target() }, { names: ctx.ds().names, groups: await mkGroups() });
}
function mkMarkerMenu(ctx, m, x, y) {
  const ed = ctx.canEdit(m), items = [];
  items.push({ label: ed ? "Edytuj znacznik…" : "Szczegóły znacznika…", fn: async () => { await mkOpenDialog(m, { names: ctx.ds().names, groups: await mkGroups(), readonly: !ed }); } });
  if (ed) items.push({ label: (ctx.unlocked.has(m.id) ? "✓ " : "") + "Zmień pozycję znacznika", fn: () => { (ctx.unlocked.has(m.id) ? ctx.unlocked.delete(m.id) : ctx.unlocked.add(m.id)); ctx.redraw(); } });
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
  const last = mkSpan(m) ? m.end_us : m.at_us, pad = Math.max((last - m.at_us) * 0.3, 20e6);
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
  if (f.conn && m.conn !== f.conn) return false;
  if (f.q && !f.q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w))) return false;
  if (f.priority !== "" && m.priority !== +f.priority) return false;
  if (f.group !== "*" && (m.group_name || "").toLowerCase() !== f.group.toLowerCase()) return false;
  if (f.author && (m.author || "").toLowerCase() !== f.author.toLowerCase()) return false;
  if (f.from && f.to && ((mkSpan(m) ? m.end_us : m.at_us) < f.from || m.at_us > f.to)) return false;
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
  if (v("mkl-scope") === "conn" && $("c-conn").value) qs.set("conn", $("c-conn").value);
  qs.set("order", v("mkl-order")); qs.set("limit", 1000);
  let d; try { d = await api("/api/markers?" + qs); } catch (e) { $("mkl-msg").textContent = "Błąd: " + e.message; return; }
  const flt = { conn: v("mkl-scope") === "conn" ? $("c-conn").value : "", q: v("mkl-q"), priority: v("mkl-prio"), group: v("mkl-group"), author: v("mkl-author"),
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
    <td>${m.kind === "range" ? "Zakres (" + mkDur((m.end_us - m.at_us) / 1e6) + ")" : m.kind === "delta" ? "Różnica sygnału (" + mkDur((m.end_us - m.at_us) / 1e6) + ")" : "Punkt"}</td><td>${MK_PRIO_PL[m.priority] || m.priority}</td><td>${esc(m.signals.join(", ") || "wszystkie")}</td>
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
  for (const id of ["mkl-prio", "mkl-group", "mkl-author", "mkl-scope", "mkl-order", "mkl-range", "mkl-from", "mkl-to"]) $(id).addEventListener("change", refreshMarkers);
  let tm = null; $("mkl-q").addEventListener("input", () => { clearTimeout(tm); tm = setTimeout(refreshMarkers, 250); });
  $("mkl-refresh").addEventListener("click", refreshMarkers);
  $("mkl-group-btn").addEventListener("click", () => { if (mkSel.size) mkGroupDialog(null, mkList.filter((m) => mkSel.has(m.id))); else alert("Zaznacz znaczniki (pola po lewej)."); });
  $("mkl-ungroup-btn").addEventListener("click", () => { if (!mkSel.size) return alert("Zaznacz znaczniki (pola po lewej)."); for (const m of mkList.filter((x) => mkSel.has(x.id))) mkdUpdate(m, { group_name: "" }); });
  $("mkl-save").addEventListener("click", () => mkSave());
  $("mkl-look").addEventListener("click", mkLookOpen);
  const now = Date.now(); $("mkl-to").value = mkInput(now * 1000); $("mkl-from").value = mkInput((now - 86400e3) * 1000);
}

// ---------------------------------------------------------------- list / search from the chart, keyboard shortcuts
function mkOpenList(ctx) {   // opened from a chart: the scope is that chart's connection (like the program), from the menu: every connection
  $("mkl-scope").value = ctx && ctx.kind === "live" ? "conn" : "";
  go("markers");
}
function mkOpenSearch(ctx) {
  const d = ctx && ctx.kind === "rec" ? $("rv-search") : $("c-search"); d.open = true; d.scrollIntoView({ block: "center" });
  d.querySelector("select, input")?.focus();
}
// Ctrl+M list, Ctrl+Shift+M add a marker now, Ctrl+Shift+S save markers, Ctrl+F search in the data (only while a chart is shown)
window.addEventListener("keydown", (e) => {
  if (!e.ctrlKey || e.altKey || !me?.user || document.querySelector("dialog[open]")) return;
  const k = e.key.toLowerCase(), live = view === "chart", chart = live || view === "recs";
  if (k === "m" && !e.shiftKey && (chart || view === "markers")) { e.preventDefault(); mkOpenList(live ? MK.live : null); }
  else if (k === "m" && e.shiftKey && live) { e.preventDefault(); $("c-addmark").click(); }
  else if (k === "s" && e.shiftKey && (chart || view === "markers")) { e.preventDefault(); mkSave(); }
  else if (k === "f" && !e.shiftKey && chart) { e.preventDefault(); mkOpenSearch(live ? MK.live : MK.rec); }
});

// ---------------------------------------------------------------- search panel (values of signals): live connection and recordings
const MK_OPS = { "==": "jest równe", "!=": "jest różne od", ">": "jest większe niż", ">=": "jest ≥", "<": "jest mniejsze niż", "<=": "jest ≤", between: "jest w przedziale",
  outside: "jest poza przedziałem", changes: "zmienia wartość", rises: "rośnie (zbocze narastające)", falls: "maleje (zbocze opadające)", nan: "brak wartości" };
const MK_OPS_N = { between: 2, outside: 2, changes: 0, rises: 0, falls: 0, nan: 0 };
const MK_EVENTS = ["changes", "rises", "falls"];
// box: container; cfg = {names(): [...], run(body) -> result, pick(hit), mark(hit, signals, event)}
function mkSearchPanel(box, cfg) {
  box.innerHTML = `<div class="inline sr-goto"><span>Przejdź do daty i godziny:</span><input class="sr-when" type="datetime-local" step="0.001"><button class="sr-gobtn">Przejdź</button><span class="sr-gmsg muted"></span></div>
    <div class="sr-rows"></div><div class="inline"><label>Trwa co najmniej [s] <input class="sr-min" type="number" min="0" step="any" value="0" style="width:90px"></label>
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
  box.querySelector(".sr-when").value = mkInput(Date.now() * 1000);
  box.querySelector(".sr-gobtn").onclick = async () => {
    const us = mkFromInput(box.querySelector(".sr-when").value), gm = box.querySelector(".sr-gmsg"), s0 = cfg.startUs();
    if (!us || !s0) { gm.textContent = "Brak danych."; return; }
    gm.textContent = ""; try { const ok = await cfg.pick({ t0: (us - s0) / 1e6, t1: (us - s0) / 1e6, duration: 0, t0_us: us, t1_us: us }, true); gm.textContent = ok === false ? "Tego momentu nie ma w danych." : "Pokazano " + mkStamp(us) + "."; }
    catch (err) { gm.textContent = "Błąd: " + err.message; }
  };
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
