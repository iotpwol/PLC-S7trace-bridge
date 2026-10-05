"use strict";
// S7Trace web mode: login, overview (connections / controllers / users), live chart (Server-Sent Events), accounts.
let LEGSTYLE = "legend";                                   // names of the signals on the chart: "legend" / "labels" (per account, see legendStyleSet)
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// one rule for the whole page (as in the program): data inside a sentence - numbers with units - is bold (core/richtext.py)
const boldNums = (s) => esc(s).replace(/(?<![\w.,:-])((?:[\u2265\u2264<>~\u00b1]\s?)?\d+(?:[.,]\d+)?(?:\s?(?:%|ms|\u00b5s|min|kb\/s|B\/s|kB|MB|Hz|s|B)(?![\w]))?)(?![\w]|[.,]\d)/g, "<b>$1</b>");
let me = null, view = "overview", pollTimer = null, stream = null, series = null;
const ROLE_RANK = { viewer: 0, operator: 1, admin: 2 };
const STATE_PL = { running: "praca", connecting: "łączenie", reconnecting: "ponawianie", stopped: "zatrzymane", error: "błąd" };

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-S7Trace": "1" },
                                         body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const d = await r.json().catch(() => ({}));
  if (r.status === 401) { me = null; showLogin(); throw new Error("login"); }
  if (!r.ok) throw new Error(d.error || ("Błąd " + r.status));
  return d;
}

function fmtAge(s) { s = Math.round(s); if (s < 60) return s + " s"; if (s < 3600) return Math.floor(s / 60) + " min"; return Math.floor(s / 3600) + " h " + Math.floor(s % 3600 / 60) + " min"; }
function fmtTime(us) { return us ? new Date(us / 1000).toLocaleString("pl-PL") : "–"; }

// ---------------------------------------------------------------- login
function show(name) {
  for (const id of ["login", "overview", "chart", "users", "editor", "targets", "recs", "markers"]) $(id).hidden = id !== name;
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.view === name));
}
async function showLogin() {
  stopStream(); clearInterval(pollTimer);
  $("nav").hidden = true; $("logout").hidden = true; $("who").textContent = "";
  const m = await fetch("/api/me").then((r) => r.json());
  $("login-title").textContent = m.first_run ? "Pierwsze uruchomienie – utwórz administratora" : "Logowanie";
  $("login-hint").textContent = m.first_run ? "Nie ma jeszcze żadnego konta. Podaj nazwę i hasło (min. 8 znaków) pierwszego administratora."
    : "Konto programu albo konto Windows / Active Directory (np. DOMENA\\jan).";
  $("l-submit").textContent = m.first_run ? "Utwórz i zaloguj" : "Zaloguj";
  $("l-sso").hidden = !m.sso || m.first_run;
  $("login-form").dataset.setup = m.first_run ? "1" : "";
  show("login");
}
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("l-error").textContent = "";
  try {
    await api($("login-form").dataset.setup ? "/api/setup" : "/api/login", { username: $("l-user").value, password: $("l-pass").value });
    $("l-pass").value = ""; await start();
  } catch (err) { $("l-error").textContent = err.message; }
});
$("l-sso").addEventListener("click", async () => {
  $("l-error").textContent = "";
  try {
    const r = await fetch("/api/sso", { headers: { "X-S7Trace": "1" } }), d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(r.status === 401 ? "Przeglądarka nie przesłała konta Windows (dodaj adres serwera do strefy „Intranet” albo zezwól na uwierzytelnianie zintegrowane)." : (d.error || "Błąd " + r.status));
    await start();
  } catch (err) { $("l-error").textContent = err.message; }
});
$("logout").addEventListener("click", async () => { if (!(await mkConfirmLeave())) return; mkdDiscard(); await api("/api/logout", {}); me = null; showLogin(); });

// ---------------------------------------------------------------- navigation
document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", async () => {
  if ((view === "chart" || view === "recs") && b.dataset.view !== view && !(await mkConfirmLeave())) return;   // unsaved markers: remind first
  go(b.dataset.view);
}));
function go(v) {
  view = v; show(v); stopStream();
  if (v === "overview") refreshOverview();
  if (v === "chart") openChart();
  if (v === "users") refreshUsers();
  if (v === "targets") refreshTargets();
  if (v === "recs") initRecs();
  if (v === "markers") refreshMarkers();
  if (v === "diag") initDiag();
}
async function start() {
  me = await api("/api/me");
  if (!me.user) return showLogin();
  mkLoadPrefs(); panelLoad(); statusLoad(); tableColorsLoad(); legendStyleLoad();
  $("who").textContent = `${me.user} (${me.role})`; $("logout").hidden = false; $("nav").hidden = false;
  $("nav-users").hidden = me.role !== "admin"; $("nav-targets").hidden = me.role !== "admin";
  $("new-conn").hidden = ROLE_RANK[me.role] < ROLE_RANK.operator;
  $("ws-hint").textContent = me.role === "admin" ? "Jako administrator widzisz połączenia wszystkich kont."
    : "Widzisz swoje połączenia (własna przestrzeń konta " + me.user + ") oraz wspólne połączenia serwera.";
  clearInterval(pollTimer);
  pollTimer = setInterval(() => { if (view === "overview") refreshOverview(); }, 3000);
  go(view === "login" ? "overview" : view);
}

// ---------------------------------------------------------------- overview
let overview = null;
async function refreshOverview() {
  try { overview = await api("/api/overview"); } catch (e) { return; }
  const canRun = ROLE_RANK[me.role] >= ROLE_RANK.operator;
  $("t-conn").tBodies[0].innerHTML = overview.connections.map((c) => {
    const d = c.device || {};
    const btn = [`<button onclick="openChart('${c.id}')">Podgląd</button>`];
    if (c.can_edit) btn.push(`<button onclick="openEditor('${c.id}')">Edytuj</button>`);
    if (canRun && c.can_run) btn.push(c.state === "stopped" ? `<button onclick="act('${c.id}','start')">Start</button>` : `<button onclick="act('${c.id}','stop')">Stop</button>`);
    return `<tr><td><b>${esc(c.name)}</b></td><td>${c.shared ? '<span class="muted">wspólne</span>' : esc(c.owner)}</td><td>${esc(c.ip)}</td><td>${c.rack} / ${c.slot}</td>
      <td><span class="dot ${esc(c.state)}"></span>${esc(STATE_PL[c.state] || c.state)}<div class="muted">${esc(c.message)}</div></td>
      <td>${esc([d.family, d.model, d.firmware].filter(Boolean).join(" · ") || "–")}</td><td>${esc(d.plc_name || "–")}</td>
      <td>${esc(d.module_name || "–")}</td><td>${esc(c.method)}</td><td>${esc(c.started_by || "–")}<div class="muted">${c.started_us ? fmtTime(c.started_us) : ""}</div></td>
      <td>${esc((c.viewers || []).join(", ") || "–")}</td>
      <td>${(c.others || []).length ? `<span class="error" title="Ten sterownik skanuje też program okienkowy">także: ${esc(c.others.join(", "))}</span>` : ""}</td><td>${btn.join(" ")}</td></tr>`;
  }).join("") || '<tr><td colspan="13" class="muted">Brak połączeń na serwerze.</td></tr>';
  $("t-agents").tBodies[0].innerHTML = (overview.agents || []).map((a) => `<tr><td><b>${esc(a.user)}</b></td><td>${esc(a.host)}</td><td>${esc(a.address)}</td>
    <td>${esc((a.started || "").replace("T", " "))}</td><td>${a.tabs.map((t) => `${esc(t.title)} · ${esc(t.ip)} · ${esc(STATE_PL[t.state] || t.state)}`).join("<br>") || "–"}</td></tr>`).join("")
    || '<tr><td colspan="5" class="muted">Żaden program okienkowy się nie zgłasza (token: zakładka Użytkownicy; w programie: Ustawienia → Serwer Web).</td></tr>';
  const byId = Object.fromEntries(overview.connections.map((c) => [c.id, c.name]));
  $("t-sess").tBodies[0].innerHTML = overview.sessions.map((s) => `<tr><td><b>${esc(s.username)}</b></td><td>${esc(s.kind)}</td><td>${esc(s.role)}</td>
    <td>${esc(s.address)}</td><td class="muted">${esc(s.agent)}</td><td>${fmtAge(s.login_s)} temu</td>
    <td>${s.active ? '<span class="dot running"></span>aktywny' : "bezczynny " + fmtAge(s.idle_s)}</td><td>${esc(byId[s.viewing] || "–")}</td></tr>`).join("");
}
window.act = async (id, what) => { try { await api(`/api/connections/${id}/${what}`, {}); } catch (e) { alert(e.message); } refreshOverview(); };

// ---------------------------------------------------------------- editor of a connection (own workspace of the account)
let editing = null;   // {id|null, opts, running}
const NEW_SIGNAL = (n) => ({ name: "SIG" + n, source: "DB", dtype: "BOOL", db: 1, byte: 0, bit: 0, share: 1, color: COLORS[(n - 1) % COLORS.length],
                             enabled: true, plot: true, comment: "", node: "" });
$("new-conn").addEventListener("click", () => openEditor(null));
$("e-cancel").addEventListener("click", () => go("overview"));
function fillSelect(sel, items, cur) {
  sel.innerHTML = items.map((i) => { const [v, t] = Array.isArray(i) ? i : [i, i]; return `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(t)}</option>`; }).join("");
}
window.openEditor = async (id) => {
  view = "editor"; show("editor"); stopStream(); $("e-error").textContent = "";
  let d;
  if (id) d = await api(`/api/connections/${id}/config`);
  else d = { name: "", ip: "192.168.0.1", rack: 0, slot: 2, cycle_ms: 25, window_s: 200, y_layout: "lanes", auto_y: true, y_min: 0, y_max: 10, show_points: false, conn_type: "auto", mode: null, state: "stopped",
             signals: [NEW_SIGNAL(1)], options: (await api("/api/options")).options };
  editing = { id, opts: d.options, running: d.state !== "stopped" };
  $("e-title").textContent = id ? `Edycja połączenia: ${d.name || d.ip}` : "Nowe połączenie";
  $("e-note").textContent = editing.running ? "Połączenie jest uruchomione – zmiana adresu, cyklu i sygnałów wymaga jego zatrzymania (nazwa i okno czasu – nie)." : "";
  for (const el of $("e-form").querySelectorAll("input,select,button[type=button]")) if (!["e-cancel", "e-delete"].includes(el.id)) el.disabled = false;
  $("e-name").value = d.name; $("e-ip").value = d.ip; $("e-rack").value = d.rack; $("e-slot").value = d.slot;
  $("e-cycle").value = d.cycle_ms; $("e-window").value = d.window_s;
  showDevice(d);
  $("e-ylayout").value = d.y_layout || "lanes"; $("e-autoy").checked = d.auto_y !== false; $("e-ymin").value = d.y_min ?? 0; $("e-ymax").value = d.y_max ?? 10; $("e-points").checked = !!d.show_points; $("e-legend").value = d.legend_mode || "name"; $("e-taxis").value = d.time_axis || "rel"; cxOffSet($("e-toff-s"), $("e-toff-d"), $("e-toff-t"), d.time_offset || 0);
  fillSelect($("e-type"), d.options.conn_types, d.conn_type); fillSelect($("e-mode"), d.options.modes, d.mode || d.options.modes[0]);
  $("e-delete").hidden = !id;
  $("e-sig").tBodies[0].innerHTML = ""; d.signals.forEach(addSigRow);
  const tr = d.trigger || { enabled: false, signal: "", mode: "==", a: 0, b: 0, hysteresis: 0, pretrigger: 0, action: "Pauza", filename: "" };
  const rc = d.rec || { target: "csv", mode: "changes", filename: "" };
  $("t-enabled").checked = tr.enabled; $("t-a").value = tr.a; $("t-b").value = tr.b; $("t-h").value = tr.hysteresis; $("t-pre").value = tr.pretrigger;
  fillSelect($("t-mode"), d.options.trigger_modes, tr.mode); fillSelect($("t-action"), d.options.trigger_actions, tr.action);
  $("t-file").value = tr.filename; trigSignals(tr.signal);
  fillSelect($("r-target"), d.options.rec_targets, rc.target); $("r-mode").value = rc.mode; $("r-file").value = rc.filename;
  editing.recording = !!d.recording;
  if (editing.running) for (const el of $("e-form").querySelectorAll("input,select,button[type=button]"))
    if (!["e-name", "e-window", "e-cancel"].includes(el.id) && !el.closest("#e-trig") && !el.closest("#e-rec")) el.disabled = true;
  if (editing.recording) for (const el of $("e-rec").querySelectorAll("input,select")) el.disabled = true;
  if (editing.recording) $("e-note").textContent += " Nagrywanie trwa – ustawienia REC są zablokowane.";
};
function addSigRow(sg) {
  const o = editing.opts, tr = document.createElement("tr");
  const num = (k, mn, mx, st = 1) => `<input data-k="${k}" type="number" min="${mn}" max="${mx}" step="${st}" value="${sg[k] ?? 0}">`;
  tr.innerHTML = `<td><input data-k="name" maxlength="64" value="${esc(sg.name)}"></td>
    <td><select data-k="source">${o.sources.map((x) => `<option ${x === sg.source ? "selected" : ""}>${x}</option>`).join("")}</select></td>
    <td><select data-k="dtype">${o.dtypes.map((x) => `<option ${x === sg.dtype ? "selected" : ""}>${x}</option>`).join("")}</select></td>
    <td>${num("db", 0, 65535)}</td><td>${num("byte", 0, 65535)}</td><td>${num("bit", 0, 7)}</td>
    <td><input data-k="node" maxlength="500" value="${esc(sg.node)}"></td><td>${num("share", 0.1, 100, 0.1)}</td>
    <td><input data-k="color" type="color" value="${esc(sg.color)}"></td>
    <td><input data-k="enabled" type="checkbox" ${sg.enabled ? "checked" : ""}></td><td><input data-k="plot" type="checkbox" ${sg.plot ? "checked" : ""}></td>
    <td><input data-k="comment" maxlength="200" value="${esc(sg.comment)}"></td><td><button type="button" class="del">✕</button></td>`;
  tr._orig = sg;                                              // fields not shown here (gain, offset, format) stay as they were
  tr.querySelector(".del").onclick = () => tr.remove();
  $("e-sig").tBodies[0].appendChild(tr);
}
let detected = null;
$("e-detect").addEventListener("click", async () => {
  $("e-detmsg").textContent = "Rozpoznaję sterownik… (do kilkunastu sekund)"; $("e-report").hidden = true; $("e-apply").hidden = true;
  try {
    const d = await api("/api/detect", { ip: $("e-ip").value, rack: +$("e-rack").value, slot: +$("e-slot").value, conn_type: $("e-type").value });
    detected = d; $("e-report").textContent = d.report; $("e-report").hidden = false;
    $("e-detmsg").textContent = d.recommended ? `Zalecana metoda: ${d.recommended}.` : "Żadna metoda nie zadziałała – patrz raport.";
    $("e-apply").hidden = !d.recommended;
  } catch (err) { $("e-detmsg").textContent = ""; $("e-error").textContent = err.message; }
});
$("e-apply").addEventListener("click", () => {
  if (!detected?.recommended) return;
  $("e-type").value = detected.recommended; $("e-rack").value = detected.rack; $("e-slot").value = detected.slot;
  if (!$("e-name").value && detected.info?.plc_name) $("e-name").value = detected.info.plc_name;
  $("e-detmsg").textContent = "Zastosowano (sposób połączenia, rack, slot). Zapisz połączenie, aby zachować.";
});
function trigSignals(cur) {
  const names = [...$("e-sig").tBodies[0].rows].map((tr) => tr.querySelector("[data-k=name]").value).filter(Boolean);
  if (cur === undefined) cur = $("t-signal").value;
  fillSelect($("t-signal"), ["", ...names], cur);
}
$("t-signal").addEventListener("focus", () => trigSignals());
$("t-signal").addEventListener("mousedown", () => trigSignals());
$("e-add").addEventListener("click", () => addSigRow(NEW_SIGNAL($("e-sig").tBodies[0].rows.length + 1)));
function collectSignals() {
  return [...$("e-sig").tBodies[0].rows].map((tr) => {
    const o = { ...(tr._orig || {}) };
    tr.querySelectorAll("[data-k]").forEach((el) => { o[el.dataset.k] = el.type === "checkbox" ? el.checked : el.type === "number" ? +el.value : el.value; });
    return o;
  });
}
function showDevice(d) {            // one row per datum (each can be hidden by a right click); values are bold
  const rows = d.device_rows || [];
  $("e-device").innerHTML = rows.length
    ? rows.map(([k, v]) => `<tr data-row="${esc(k)}"><th>${esc(k)}</th><td><b>${esc(v)}</b></td></tr>`).join("") + '<tr id="e-plcrow" data-row="Czas PLC"><th>Czas PLC</th><td><b></b></td></tr>'
    : '<tr><td class="muted">Brak danych sterownika – pobierz je przyciskiem poniżej albo pojawią się po pierwszym połączeniu.</td></tr>';
  plcErr = d.plc_error || "";
  plcClockInit(d);
  panelApplyHidden();
}
$("e-readdev").addEventListener("click", async () => {
  if (!editing?.id) { $("e-devmsg").textContent = " Najpierw zapisz połączenie."; return; }
  $("e-readdev").disabled = true; $("e-devmsg").textContent = " Łączenie i odczyt danych sterownika…";
  try { const d = await api(`/api/connections/${editing.id}/read-device`, {}); showDevice(d); $("e-rack").value = d.rack; $("e-slot").value = d.slot; $("e-devmsg").textContent = d.note ? " " + d.note : ""; }
  catch (e) { $("e-devmsg").textContent = " " + e.message; }
  $("e-readdev").disabled = !!editing?.running;
});
// the clock of the PLC in the device table: read once at the connection, then the server's clock + the difference, refreshed every second;
// a clock a day or more off is announced and can be aligned with the offset of the time axis
let plcClock = null, plcErr = "";
function plcClockInit(d) {
  plcClock = d.plc_diff === null || d.plc_diff === undefined ? null : { diff: +d.plc_diff, base: +d.server_now, tz: +d.server_tz || 0, t0: performance.now() };
  const note = $("e-plcnote"); note.hidden = true; note.innerHTML = "";
  if (plcClock && Math.abs(plcClock.diff) >= 86400) {
    note.hidden = false; note.innerHTML = `Zegar PLC różni się od zegara serwera o <b>${cxOffFmt(plcClock.diff)}</b>. <button type="button" id="e-plcalign">Wyrównaj oś „Czas PLC” do serwera</button>`;
    $("e-plcalign").onclick = () => cxOffSet($("e-toff-s"), $("e-toff-d"), $("e-toff-t"), -plcClock.diff);
  }
  plcClockTick();
}
function plcClockTick() {
  const row = $("e-plcrow"); if (!row) return; const b = row.querySelector("td b");
  if (!plcClock) { b.textContent = "nie odczytano"; row.title = "Nie udało się odczytać zegara sterownika" + (plcErr ? ": " + plcErr : "."); return; }
  const ms = Math.round((plcClock.base + plcClock.diff + plcClock.tz + (performance.now() - plcClock.t0) / 1000) * 1000), t = new Date(ms), p = (n) => String(n).padStart(2, "0");
  b.textContent = `${t.getUTCFullYear()}-${p(t.getUTCMonth() + 1)}-${p(t.getUTCDate())}\u00a0\u00a0${p(t.getUTCHours())}:${p(t.getUTCMinutes())}:${p(t.getUTCSeconds())}`;
  row.title = "Zegar sterownika: czytany raz przy połączeniu, dalej liczony z zegara serwera i różnicy.";
}
setInterval(plcClockTick, 1000);
$("e-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("e-error").textContent = "";
  const toff = cxOffGet($("e-toff-s"), $("e-toff-d"), $("e-toff-t")) ?? 0;
  if (Number.isNaN(toff)) { $("e-error").textContent = "Offset osi: godzina w postaci HH:MM:SS.mmm, data = liczba dób."; return; }
  const body = { name: $("e-name").value, window_s: +$("e-window").value, y_layout: $("e-ylayout").value, auto_y: $("e-autoy").checked,
    y_min: +$("e-ymin").value, y_max: +$("e-ymax").value, show_points: $("e-points").checked, legend_mode: $("e-legend").value, time_axis: $("e-taxis").value, time_offset: toff,
    trigger: { enabled: $("t-enabled").checked, signal: $("t-signal").value, mode: $("t-mode").value, a: +$("t-a").value, b: +$("t-b").value,
               hysteresis: +$("t-h").value, pretrigger: +$("t-pre").value, action: $("t-action").value, filename: $("t-file").value } };
  if (!editing.recording) body.rec = { target: $("r-target").value, mode: $("r-mode").value, filename: $("r-file").value };
  if (!editing.running) Object.assign(body, { ip: $("e-ip").value, rack: +$("e-rack").value, slot: +$("e-slot").value, cycle_ms: +$("e-cycle").value,
    conn_type: $("e-type").value, mode: $("e-mode").value, signals: collectSignals() });
  try { await api(editing.id ? `/api/connections/${editing.id}/config` : "/api/connections", body); go("overview"); }
  catch (err) { $("e-error").textContent = err.message; }
});
$("e-delete").addEventListener("click", async () => {
  if (!confirm("Usunąć to połączenie razem z jego konfiguracją?")) return;
  try { await api(`/api/connections/${editing.id}/delete`, {}); go("overview"); } catch (err) { $("e-error").textContent = err.message; }
});

// ---------------------------------------------------------------- live chart
const COLORS = ["#ffb347", "#4eb8f0", "#7bd88f", "#ff7b7b", "#c792ea", "#f1fa8c", "#8be9fd", "#ffa7d1"];
let markTimer = null, searchNames = "", userFrozen = false, liveView = null;   // liveView: {x0, x1} the viewer zoomed / panned to (seconds of the series)
function stopStream() { if (stream) { stream.close(); stream = null; } clearInterval(markTimer); }
window.openChart = async (id) => {
  if (view !== "chart") { view = "chart"; show("chart"); }
  stopStream();
  const o = overview || await api("/api/overview"); overview = o;
  $("c-conn").innerHTML = o.connections.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.ip)})</option>`).join("");
  if (id) $("c-conn").value = id;
  connectStream();
};
function openChart() { window.openChart(); }
let frozen = null, frozenKey = null, conn = null, lastDesc = null;
function connectStream() {
  stopStream(); frozen = null; frozenKey = null; lastDesc = null; userFrozen = false; liveView = null; $("c-live").hidden = true;
  const id = $("c-conn").value; connPrev = id; if (!id) return;
  conn = (overview?.connections || []).find((c) => c.id === id) || null;
  $("c-filelist").hidden = true;
  series = { t: [], values: [], names: [], colors: [], start_us: 0 };
  const sec = +$("c-sec").value;
  MK.live.marks = []; MK.live.hi = new Set(); clearInterval(markTimer); markTimer = setInterval(() => { if (view === "chart") loadLiveMarks(); }, 2000);
  stream = new EventSource(`/api/connections/${id}/stream?seconds=${sec}`);
  stream.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.reset) { series = { t: d.t, values: d.values, names: d.names, colors: d.colors, start_us: d.start_us, shares: d.shares, gains: d.gains, dtypes: d.dtypes, offsets: d.offsets, layout: d.layout, addresses: d.addresses, tips: d.tips, plc_diff: d.plc_diff, tz_offset: d.tz_offset }; }   // (identical colours: palette below)
    else { series.t.push(...d.t); d.values.forEach((col, k) => (series.values[k] ||= []).push(...col)); }
    if (d.start_us) series.start_us = d.start_us;
    if (d.plc_diff !== undefined) series.plc_diff = d.plc_diff;
    if (d.tz_offset !== undefined) series.tz_offset = d.tz_offset;
    if (d.names?.length && d.names.join("\u0001") !== searchNames) { searchNames = d.names.join("\u0001"); $("c-search-box")._rebuild?.(); }
    if (d.shares) { series.shares = d.shares; series.gains = d.gains; series.dtypes = d.dtypes; series.offsets = d.offsets; series.layout = d.layout; series.addresses = d.addresses; series.tips = d.tips; }
    if (d.names?.length) { series.names = d.names; series.colors = new Set(d.colors).size < d.colors.length ? d.colors.map((_, k) => COLORS[k % COLORS.length]) : d.colors; }
    if (d.description) { lastDesc = d.description; describeChart(d.description); }
    const cut = liveView ? -Infinity : (series.t.at(-1) ?? 0) - sec;          // a zoomed / panned view keeps what the page has collected
    while (series.t.length && (series.t[0] < cut || series.t.length > 60000)) { series.t.shift(); series.values.forEach((c) => c.shift()); }
    draw();
  };
}
const TRIG_PL = { off: "wyłączony", armed: "uzbrojony", post: "zbieranie próbek po wyzwoleniu…", hold: "WSTRZYMANY (zamrożone okno)" };
function describeChart(d) {
  $("c-state").textContent = `${STATE_PL[d.state] || d.state} – ${d.message || ""}`;
  const t = d.trigger, r = d.rec, canRun = !!conn?.can_run;
  $("c-trig").textContent = t.enabled ? `Trigger (${t.signal}): ${TRIG_PL[t.state] || t.state}${t.note ? " · " + t.note : ""}` : "";
  $("c-rearm").hidden = !(canRun && t.state === "hold");
  $("c-rec").hidden = !canRun; $("c-title").hidden = $("c-desc").hidden = !canRun || r.active || r.target === "csv";
  $("c-rec").textContent = r.active ? "■ Stop REC" : "● REC"; $("c-rec").classList.toggle("rec-on", r.active);
  $("c-recinfo").textContent = r.active ? `REC → ${r.label}${r.by ? " (" + r.by + ")" : ""}${r.error ? " · BŁĄD: " + r.error : ""}` : (r.error ? "REC: " + r.error : "");
  if (t.state === "hold" && t.x0 !== null) {
    const key = `${t.x0}`;
    if (frozenKey !== key) { frozenKey = key; fetch(`/api/connections/${$("c-conn").value}/series?from=${t.x0}&to=${t.x1}`).then((r2) => r2.json())
      .then((f) => { if (frozenKey === key) { frozen = { ...f, x0: t.x0, x1: t.x1, trig: t.t }; if (!f.colors?.length) frozen.colors = series.colors;
        frozen.colors = new Set(f.colors).size < f.colors.length ? f.colors.map((_, k) => COLORS[k % COLORS.length]) : f.colors; draw(); } }); }
  } else if (!userFrozen) { frozen = null; frozenKey = null; }
}
$("c-rearm").addEventListener("click", async () => { try { await api(`/api/connections/${$("c-conn").value}/trigger`, { action: "rearm" }); } catch (e) { alert(e.message); } });
$("c-rec").addEventListener("click", async () => {
  const id = $("c-conn").value, on = lastDesc?.rec?.active;
  try { await api(`/api/connections/${id}/rec`, on ? { action: "stop" } : { action: "start", title: $("c-title").value, description: $("c-desc").value }); } catch (e) { alert(e.message); }
});
$("c-title").addEventListener("change", async () => { if (lastDesc?.rec?.active) try { await api(`/api/connections/${$("c-conn").value}/rec`, { action: "info", title: $("c-title").value }); } catch (e) { /* ignored */ } });
$("c-files").addEventListener("click", async () => {
  const box = $("c-filelist"), id = $("c-conn").value; if (!box.hidden) { box.hidden = true; return; }
  const d = await api(`/api/connections/${id}/files`);
  const canDel = !!conn?.can_edit;
  box.innerHTML = d.files.length ? d.files.map((f) => `<div><a href="/api/connections/${id}/files/${f.kind}/${encodeURIComponent(f.name)}" download>${esc(f.name)}</a>
    <span class="muted">${f.kind === "rec" ? "REC" : "trigger"} · ${(f.size / 1024).toFixed(1)} kB · ${new Date(f.modified * 1000).toLocaleString("pl-PL")}</span>
    ${canDel ? `<button onclick="delFile('${id}','${f.kind}','${esc(f.name)}')">Usuń</button>` : ""}</div>`).join("") : '<span class="muted">Brak plików (trigger z zapisem CSV i REC do CSV zapisują tu pliki).</span>';
  box.hidden = false;
});
window.delFile = async (id, kind, name) => { if (!confirm("Usunąć plik " + name + "?")) return;
  try { await api(`/api/connections/${id}/files`, { kind, name }); } catch (e) { alert(e.message); } $("c-filelist").hidden = true; $("c-files").click(); };
let connPrev = "";
$("c-conn").addEventListener("change", async () => { if (!(await mkConfirmLeave())) { $("c-conn").value = connPrev; return; } connectStream(); }); $("c-sec").addEventListener("change", connectStream);
let drawPending = false;
function draw() { if (drawPending) return; drawPending = true; requestAnimationFrame(() => { drawPending = false; paint(); }); }
function liveRange() {
  const ds = frozen || series, sec = +$("c-sec").value;
  if (frozen) return [frozen.x0, frozen.x1];
  if (liveView) return [liveView.x0, liveView.x1];
  const t1 = ds.t.at(-1) ?? 0; return [t1 - sec, t1];
}
function paint() {
  const ds = frozen || series, sec = +$("c-sec").value, [t0, t1] = liveRange();
  drawChart($("canvas"), ds, t0, t1, { ...cxOpts($("canvas"), ds), mk: MK.live, markers: (lastDesc?.trigger?.events || []).map((e) => e.t), left: frozen ? "okno zamrożone triggerem" : `-${sec} s`,
    right: frozen ? "" : liveView ? "" : "teraz", empty: "Brak danych – uruchom połączenie (Start) na stronie Przegląd.", legend: $("c-legend") });
  cxOverview($("canvas"));
}
// one lane per signal, scaled to its own min..max of the shown range; steps (the value holds until the next change).
// o.layout "offset": one common area, value x gain + offset on one Y axis (auto min..max of all signals or o.yMin..o.yMax); o.points: sample points.
function drawChart(cv, ds, t0, t1, o) {
  const g = cv.getContext("2d"), W = cv.width, H = cv.height, pad = { l: 60, r: 10, t: 8, b: o.clock ? 40 : 24 }, n = ds.names.length;
  g.fillStyle = "#000"; g.fillRect(0, 0, W, H); g.font = "12px sans-serif"; g.strokeStyle = "#333"; g.fillStyle = "#aaa";
  cv._geo = null; cv._ds = ds;
  if (!n || !ds.t.length) { g.fillText(o.empty || "Brak danych.", 70, 30); return; }
  const colors = new Set(ds.colors).size < ds.colors.length ? ds.colors.map((_, k) => COLORS[k % COLORS.length]) : ds.colors;
  const sh = ds.names.map((_, k) => Math.max(+(ds.shares || [])[k] || 1, 0.01)), shSum = sh.reduce((a, b) => a + b, 0);   // lane height ~ Share (as in the program)
  const X = (t) => pad.l + (t - t0) / ((t1 - t0) || 1) * (W - pad.l - pad.r), lanes = [], offsetMode = o.layout === "offset", num = (v) => String(+v.toPrecision(5));
  const gains = ds.gains || [], offs = ds.offsets || [], inRange = (i) => ds.t[i] >= t0 && ds.t[i] <= t1;
  // values as drawn: x gain (+ offset in the offset layout), like the program
  const cols = ds.names.map((_, k) => { const gn = gains[k] || 1, of = offsetMode ? (offs[k] || 0) : 0; return (ds.values[k] || []).map((x) => x === null || x === undefined ? null : x * gn + of); });
  let gLo = 0, gHi = 1;
  if (offsetMode) {
    if (o.autoY === false) { gLo = +o.yMin; gHi = +o.yMax; }
    else { let a = Infinity, b = -Infinity; cols.forEach((c) => c.forEach((x, i) => { if (x !== null && inRange(i)) { if (x < a) a = x; if (x > b) b = x; } })); if (Number.isFinite(a)) { gLo = a; gHi = b; } }
    if (!(gHi > gLo)) { gLo -= 0.5; gHi = gLo + 1; }
  }
  const area = { top: pad.t, bot: H - pad.b - 4 };
  let yy = pad.t;
  if (offsetMode) {                                                                  // one frame, one neutral axis
    g.strokeStyle = "#333"; g.strokeRect(pad.l, area.top, W - pad.l - pad.r, area.bot - area.top); g.fillStyle = "#aaa";
    for (const f of [0, 0.25, 0.5, 0.75, 1]) g.fillText(num(gLo + f * (gHi - gLo)), 4, area.bot - f * (area.bot - area.top - 6) - 3 + (f === 1 ? 10 : f === 0 ? -1 : 4));
  }
  for (let k = 0; k < n; k++) {
    const bandH = (H - pad.t - pad.b) * sh[k] / shSum, top = offsetMode ? area.top : yy, bot = offsetMode ? area.bot : top + bandH - 4, c = colors[k] || COLORS[k % COLORS.length];
    yy += bandH;
    const gn = gains[k] || 1, isBool = (ds.dtypes || [])[k] === "BOOL", col = cols[k];
    const fin = col.filter((x, i) => x !== null && inRange(i));
    const lo = offsetMode ? gLo : isBool ? Math.min(0, gn) : Math.min(...fin), hi = offsetMode ? gHi : isBool ? Math.max(0, gn) : Math.max(...fin), span = hi - lo || 1;   // BOOL: a fixed scale 0..gain
    lanes.push({ top, bot, lo, hi, span, name: ds.names[k], color: c });
    if (!offsetMode) {
      g.strokeStyle = "#333"; g.strokeRect(pad.l, top, W - pad.l - pad.r, bandH - 4);
      const lh = bot - top, ly = (f) => bot - f * (bot - top - 6) - 3;
      g.fillStyle = c;                                                                // labels in the colour of their lane: MIN on its lower edge, MAX on the upper one
      if (Number.isFinite(lo) && Number.isFinite(hi)) {
        if (hi === lo) { if (lh >= 14) g.fillText(num(lo), 4, (top + bot) / 2 + 4); }
        else if (lh >= 26) {
          g.fillText(num(hi), 4, top + 10); g.fillText(num(lo), 4, bot - 1);
          for (const f of isBool ? [] : lh >= 140 ? [0.25, 0.5, 0.75] : lh >= 70 ? [0.5] : []) g.fillText(num(Math.abs(lo + f * (hi - lo)) < span * 1e-6 ? 0 : lo + f * (hi - lo)), 4, ly(f) + 4);
        }
      }
    }
    if (LEGSTYLE !== "labels") { g.fillStyle = c; g.fillText(ds.names[k], pad.l + 6, top + 14 + (offsetMode ? 14 * k : 0)); }
    g.strokeStyle = c; g.lineWidth = 1.2; g.beginPath(); let pen = false, py = 0;
    let medY = null;
    const pts = [];
    for (let i = 0; i < ds.t.length; i++) {
      const v = col[i]; if (v === null || v === undefined) { pen = false; continue; }
      const x = X(ds.t[i]), y = bot - (v - lo) / span * (bot - top - 6) - 3;
      if (!pen) { g.moveTo(x, y); pen = true; } else { g.lineTo(x, py); g.lineTo(x, y); }
      py = y;
      if (o.points && inRange(i)) pts.push(x, y);
    }
    if (offsetMode) { const ys = fin.map((v) => bot - (v - lo) / span * (bot - top - 6) - 3).sort((a, b) => a - b); if (ys.length) medY = ys[ys.length >> 1]; }
    lanes[k].tagY = offsetMode ? medY : (top + bot) / 2;
    if (o.hold && pen) g.lineTo(X(t1), py);          // a recording of changes: the last value holds to the end of the range
    g.stroke();
    if (o.points && pts.length <= 6000) { g.fillStyle = c; for (let i = 0; i < pts.length; i += 2) g.fillRect(pts[i] - 2, pts[i + 1] - 2, 4, 4); }   // "Punkty": at most 3000 shown
  }
  cv._geo = { t0, t1, pad, W, H, lanes, offsetMode };
  cv._tags = [];
  if (LEGSTYLE === "labels") cxTags(g, cv, ds, lanes, colors, pad, H);                // a translucent box with the name beside every signal, right of the Y axis
  if (o.mk) mkPaint(g, cv, o.mk, cv._geo, lanes);                                    // markers (bookmarks) over the curves
  g.strokeStyle = "#ff4d4d"; g.fillStyle = "#ff4d4d"; g.lineWidth = 1; g.setLineDash([5, 4]);
  for (const t of o.markers || []) { if (t < t0 || t > t1) continue; const x = X(t); g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, H - pad.b); g.stroke(); g.fillText("T", x + 3, H - pad.b - 4); }
  g.setLineDash([]); g.fillStyle = "#aaa";
  if (o.clock) cxAxis(g, cv._geo, o.clock);                                           // a clock axis (server / PLC time) replaces the "-200 s ... teraz" labels
  else { g.fillText(o.left || "", pad.l, H - 6); if (o.right) { const w = g.measureText(o.right).width; g.fillText(o.right, W - pad.r - w, H - 6); } }
  if (cv._cx) cxPaint(g, cv);                                                        // cursors V1/V2, H1/H2 and their read-out
  if (o.legend && LEGSTYLE === "labels") o.legend.innerHTML = "";                     // the names are on the chart: no list under it
  else if (o.legend) o.legend.innerHTML = ds.names.map((nm, k) => { const last = [...(ds.values[k] || [])].reverse().find((x) => x !== null && x !== undefined), tip = (ds.tips?.[k] || "Nazwa: " + nm) + "\nAktualna wartość: " +(last === undefined ? "—" : +(+last).toPrecision(8));
    return `<span title="${esc(tip)}"><i style="background:${colors[k] || COLORS[k % COLORS.length]}"></i>${esc(cxLegend(cv, ds, k))}</span>`; }).join("");
}

// ---------------------------------------------------------------- recordings stored in databases
let rv = { list: [], cur: null, data: null, from: null, to: null, trashDays: 30 };
const enc = encodeURIComponent;
const fmtDur = (a, b) => { if (!b) return "trwa / nie zamknięte"; const s = Math.max(0, Math.round((b - a) / 1e6)); return s < 60 ? s + " s" : s < 3600 ? Math.floor(s / 60) + " min " + (s % 60) + " s" : Math.floor(s / 3600) + " h " + Math.floor(s % 3600 / 60) + " min"; };
async function initRecs() {
  const d = await api("/api/recordings/sources"), cur = $("rv-src").value;
  $("rv-src").innerHTML = d.sources.map((x) => `<option value="${esc(x.id)}">${esc(x.label)}</option>`).join("");
  if (cur && d.sources.some((x) => x.id === cur)) $("rv-src").value = cur;
  refreshRecs();
}
async function refreshRecs() {
  $("rv-msg").textContent = "Czytam…"; $("rv-edit").hidden = true;
  try {
    const d = await api(`/api/recordings?source=${enc($("rv-src").value)}&trash=${$("rv-trash").checked ? 1 : 0}`);
    rv.list = d.recordings; rv.trashDays = d.trash_days; $("rv-msg").textContent = "";
  } catch (e) { rv.list = []; $("rv-msg").textContent = "Błąd: " + e.message; }
  fillRecs();
}
const devTip = (d) => (d?.lines || []).map((l) => l[0] + ": " + l[1]).join("\n");
function fillRecs() {
  const q = $("rv-q").value.trim().toLowerCase(), trash = $("rv-trash").checked;
  const rows = rv.list.filter((r) => !q || [r.title, r.description, r.tags, r.notes, r.owner, r.computer, r.name, r.ip, r.conf, ...r.signals, ...r.device.lines.map((l) => l[1])].join(" ").toLowerCase().includes(q));
  $("t-recs").tBodies[0].innerHTML = rows.map((r) => `<tr><td><b>${esc(r.title || r.conf || r.id)}</b>${r.description ? `<div>${esc(r.description)}</div>` : ""}${r.notes ? `<div class="muted">${esc(r.notes)}</div>` : ""}</td>
    <td>${new Date(r.start_us / 1000).toLocaleString("pl-PL")}</td><td>${r.recording ? "nagrywanie…" : fmtDur(r.start_us, r.end_us)}</td><td>${esc(r.owner)}</td>
    <td class="muted">${esc(r.computer)}</td><td>${esc([r.name || r.tab, r.ip].filter(Boolean).join(" · "))}</td><td title="${esc(devTip(r.device))}">${esc(r.device.title)}${r.device.serial ? `<div class="muted">${esc(r.device.serial)}</div>` : ""}</td><td class="muted">${esc(r.signals.join(", "))}</td><td>${esc(r.tags)}</td>
    <td><button onclick="loadRec('${esc(r.id)}')">Wczytaj</button> <a href="/api/recordings/csv?source=${enc($("rv-src").value)}&id=${enc(r.id)}" download>CSV</a>
    ${r.can_modify ? `<button onclick="editRec('${esc(r.id)}')">Opis</button> ` + (trash ? `<button onclick="recAct('${esc(r.id)}','restore')">Przywróć</button> <button onclick="recAct('${esc(r.id)}','purge')">Usuń trwale</button>`
      : `<button onclick="recAct('${esc(r.id)}','trash')">${rv.trashDays > 0 ? "Do kosza" : "Usuń"}</button>`) : ""}</td></tr>`).join("")
    || `<tr><td colspan="10" class="muted">${trash ? "Kosz jest pusty." : "Brak nagrań w tym źródle (nagrania powstają przyciskiem REC przy celu „sqlite” albo celu z listy administratora)."}</td></tr>`;
}
$("rv-src").addEventListener("change", async () => { if (rv.cur && !(await mkConfirmLeave())) { return; } $("rv-view").hidden = true; refreshRecs(); });
$("rv-refresh").addEventListener("click", refreshRecs); $("rv-trash").addEventListener("change", refreshRecs); $("rv-q").addEventListener("input", fillRecs);
window.recAct = async (id, action) => {
  const text = { trash: rv.trashDays > 0 ? `Przenieść nagranie do kosza (do ${rv.trashDays} dni można je przywrócić)?` : "Usunąć nagranie? Tej operacji nie można cofnąć.",
                 purge: "Usunąć TRWALE to nagranie? Tej operacji nie można cofnąć." }[action];
  if (text && !confirm(text)) return;
  try { await api("/api/recordings", { source: $("rv-src").value, id, action }); } catch (e) { alert(e.message); }
  if (rv.cur === id) $("rv-view").hidden = true; refreshRecs();
};
let editingRec = null;
window.editRec = (id) => { const r = rv.list.find((x) => x.id === id); editingRec = id; $("rv-title").value = r.title; $("rv-desc").value = r.description || ""; $("rv-notes").value = r.notes; $("rv-tags").value = r.tags; $("rv-edit").hidden = false; $("rv-title").focus(); };
$("rv-cancel").addEventListener("click", () => { $("rv-edit").hidden = true; });
$("rv-save").addEventListener("click", async () => {
  try { await api("/api/recordings", { source: $("rv-src").value, id: editingRec, action: "update", fields: { title: $("rv-title").value, description: $("rv-desc").value, notes: $("rv-notes").value, tags: $("rv-tags").value } }); }
  catch (e) { alert(e.message); } refreshRecs();
});
window.loadRec = async (id, from, to, quiet) => {
  if (id !== rv.cur && rv.cur && !quiet && !(await mkConfirmLeave())) return;          // unsaved markers of the recording on screen: remind first
  const r = rv.list.find((x) => x.id === id) || {}, qs = `source=${enc($("rv-src").value)}&id=${enc(id)}` + (from != null ? `&from=${from}&to=${to}` : "");
  if (!quiet) $("rv-msg").textContent = "Wczytuję…";
  const sameRec = rv.cur === id;
  try { rv.data = await api(`/api/recordings/data?${qs}&points=${Math.min(6000, $("rv-canvas").width * 2)}`); } catch (e) { $("rv-msg").textContent = "Błąd: " + e.message; return; }
  $("rv-msg").textContent = ""; rv.cur = id; rv.from = from ?? null; rv.to = to ?? null;
  if (from == null && !(quiet && sameRec && rv.full)) { rv.ov = rv.data; rv.full = null; rv.full = recRange(); }          // the whole recording: the overview strip and the zoom limits
  if (!sameRec && from != null) { rv.full = null; rv.ov = null; }
  $("rv-view").hidden = false; $("rv-name").textContent = (r.title || rv.data.title || id) + " ";
  $("rv-info").textContent = ` ${rv.data.rows} wierszy` + (rv.data.shown < rv.data.rows ? `, na wykresie ${rv.data.shown} (min/maks)` : "") + (rv.data.mode === "changes" ? " · zapis zmian" : "");
  const dv = rv.data.device || r.device; $("rv-dev").textContent = dv?.title ? " · sterownik: " + dv.title + (dv.serial ? " (SN " + dv.serial + ")" : "") : ""; $("rv-dev").title = devTip(dv);
  $("rv-csv").href = `/api/recordings/csv?${qs}`; if (!quiet) $("rv-search-box")._rebuild?.(); await loadRecMarks(); drawRec(); if (!quiet) $("rv-view").scrollIntoView({ behavior: "smooth" });
};
function recRange() { const d = rv.data, end = Math.max(d.t.length ? d.t.at(-1) : 0, d.end_us ? (d.end_us - d.start_us) / 1e6 : 0); return [rv.from ?? (d.t[0] ?? 0), rv.to ?? end]; }
function drawRec() {
  const d = rv.data, [t0, t1] = recRange(), at = (t) => new Date(d.start_us / 1000 + t * 1000).toLocaleString("pl-PL");
  drawChart($("rv-canvas"), d, t0, t1, { ...cxOpts($("rv-canvas"), d), mk: MK.rec, hold: d.mode === "changes", left: at(t0), right: at(t1), empty: "Brak danych w tym zakresie.", legend: $("rv-legend") });
  cxOverview($("rv-canvas"));
}
$("rv-all").addEventListener("click", () => { if (rv.cur) loadRec(rv.cur); });

// ---------------------------------------------------------------- markers on the two charts
const canMark = () => ROLE_RANK[me?.role] >= ROLE_RANK.operator;
MK.live = { cv: $("canvas"), kind: "live", marks: [], srv: [], showAll: false, pred: (m) => MK.live.showAll ? !!m.conn : m.conn === $("c-conn").value, hi: new Set(), hiGroup: "", place: null, drag: null, ds: () => frozen || series, startUs: () => (frozen || series).start_us || 0,
  target: () => ({ conn: $("c-conn").value }), canAdd: () => canMark() && !!$("c-conn").value, canEdit: (m) => m.can_edit, redraw: () => { if (view === "chart" && (frozen || series)) draw(); }, reload: async () => { await loadLiveMarks(); } };
MK.rec = { cv: $("rv-canvas"), kind: "rec", marks: [], srv: [], pred: (m) => !!rv.cur && m.rec_id === $("rv-src").value + "|" + rv.cur, hi: new Set(), hiGroup: "", place: null, drag: null, ds: () => rv.data || { names: [] }, startUs: () => rv.data?.start_us || 0,
  target: () => ({ rec_id: $("rv-src").value + "|" + rv.cur }), canAdd: () => canMark() && !!rv.data, canEdit: (m) => m.can_edit, redraw: () => { if (view === "recs" && rv.data) drawRec(); }, reload: async () => { await loadRecMarks(); MK.rec.redraw(); } };
async function loadMarks(ctx, qs) {
  try { ctx.srv = (await api("/api/markers?" + qs)).markers; } catch (e) { ctx.srv = []; }
  ctx.marks = mkdOverlay(ctx.srv, ctx.pred);
  if (ctx.hiGroup) ctx.hi = new Set(ctx.marks.filter((m) => m.group_name === ctx.hiGroup).map((m) => m.id));
}
async function loadLiveMarks() {
  const id = $("c-conn").value, ds = frozen || series; if (!id || !ds.start_us) return;
  const last = ds.t.at(-1) ?? 0, sec = +$("c-sec").value, t0 = frozen ? frozen.x0 : last - sec, t1 = frozen ? frozen.x1 : last;
  await loadMarks(MK.live, (MK.live.showAll ? "conns=1" : `conn=${encodeURIComponent(id)}`) + `&from=${Math.round(ds.start_us + t0 * 1e6)}&to=${Math.round(ds.start_us + t1 * 1e6)}&limit=500`);
  draw();
}
async function loadRecMarks() { if (rv.cur) await loadMarks(MK.rec, "rec=" + encodeURIComponent($("rv-src").value + "|" + rv.cur) + "&limit=1000"); else { MK.rec.srv = []; MK.rec.marks = mkdOverlay([], MK.rec.pred); } }
function showUserFrozen(d, x0, x1) {
  const colors = new Set(d.colors).size < d.colors.length ? d.colors.map((_, k) => COLORS[k % COLORS.length]) : d.colors;
  frozen = { ...d, colors, x0, x1, trig: null }; userFrozen = true; $("c-live").hidden = false; loadLiveMarks(); draw();
}
$("c-live").addEventListener("click", () => { userFrozen = false; liveView = null; frozen = null; frozenKey = null; $("c-live").hidden = true; loadLiveMarks(); draw(); });
$("c-addmark").addEventListener("click", () => { const ds = frozen || series; if (!ds.start_us || !canMark()) return alert(canMark() ? "Brak danych – uruchom połączenie." : "Rola „podgląd” nie zakłada znaczników.");
  mkAdd(MK.live, mkBlank(Math.round(ds.start_us + (ds.t.at(-1) ?? 0) * 1e6))); });
mkAttach(MK.live); mkAttach(MK.rec); initMarkersView();
mkSearchPanel($("c-search-box"), { names: () => series?.names || [], startUs: () => (frozen || series).start_us || 0, run: (b) => api("/api/search", { conn: $("c-conn").value, ...b }),
  pick: async (h, quiet) => { const pad = Math.max(h.duration * 0.3, 10), f = h.t0 - pad, t = h.t1 + pad, d = await api(`/api/connections/${$("c-conn").value}/series?from=${f}&to=${t}`);
    if (!d.t.length) { if (quiet) return false; return alert("Ten moment jest poza danymi, które połączenie trzyma w pamięci."); } showUserFrozen(d, f, t); },
  mark: (h, sigs, ev) => mkAdd(MK.live, mkBlank(h.t0_us, { title: "Wynik wyszukiwania", signals: sigs, ...(!ev && h.t1_us > h.t0_us ? { kind: "range", end_us: h.t1_us } : {}) })) });
mkSearchPanel($("rv-search-box"), { names: () => rv.data?.names || [], startUs: () => rv.data?.start_us || 0, run: (b) => api("/api/search", { source: $("rv-src").value, id: rv.cur, ...b }),
  pick: (h, quiet) => { const end = rv.full ? rv.full[1] : 0; if (quiet && (h.t0 < 0 || (end && h.t0 > end))) return false; const pad = Math.max(h.duration * 0.3, 20); loadRec(rv.cur, Math.max(0, h.t0 - pad), h.t1 + pad); },
  mark: (h, sigs, ev) => mkAdd(MK.rec, mkBlank(h.t0_us, { title: "Wynik wyszukiwania", signals: sigs, ...(!ev && h.t1_us > h.t0_us ? { kind: "range", end_us: h.t1_us } : {}) })) });
// chart tools (cursors, zoom / pan with the mouse, overview strip, points, layout) of both charts: chartx.js
let liveRefresh = null;
cxAttach($("canvas"), { range: liveRange, busy: () => !!(MK.live.place || MK.live.drag),
  limits: () => { const ds = frozen || series; return [ds.t[0] ?? 0, Math.max(ds.t.at(-1) ?? 0, (ds.t[0] ?? 0) + 0.1)]; },
  setRange: (a, b) => { if (frozen) { frozen.x0 = a; frozen.x1 = b; } else { liveView = { x0: a, x1: b }; $("c-live").hidden = false; }
    draw(); clearTimeout(liveRefresh); liveRefresh = setTimeout(loadLiveMarks, 250); },
  redraw: draw, overview: { cv: $("ov-live"), ds: () => frozen || series } });
cxToolbar($("c-tools"), $("canvas"));
let recReload = null;
cxAttach($("rv-canvas"), { range: () => recRange(), busy: () => !!(MK.rec.place || MK.rec.drag),
  limits: () => rv.full || recRange(),
  setRange: (a, b) => { if (!rv.cur) return; rv.from = a; rv.to = b; drawRec(); clearTimeout(recReload);
    recReload = setTimeout(() => { const [lo, hi] = rv.full || [a, b]; if (a <= lo + 1e-6 && b >= hi - 1e-6) loadRec(rv.cur, undefined, undefined, true); else loadRec(rv.cur, a, b, true); }, 220); },
  redraw: () => rv.data && drawRec(), overview: { cv: $("ov-rec"), ds: () => rv.ov || rv.data } });
cxToolbar($("rv-tools"), $("rv-canvas"));

// ---------------------------------------------------------------- diagnostics (the counterpart of the program's Diagnostyka menu)
const DG_COLOR = { "Bardzo dobre": "#2fbf4a", "Dobre": "#7fcf3a", "Przeciętne": "#e0b020", "Słabe": "#e04040", "Brak połączenia": "#e04040", "Brak danych": "#8a8a8a" };
const DG_SCORE = { "Bardzo dobre": 10, "Dobre": 8, "Przeciętne": 5, "Słabe": 2, "Brak połączenia": 0, "Brak danych": 0 };
const dgF = (v, d = 1) => (typeof v === "number" && isFinite(v) ? v.toFixed(d) : "—");
const dgHms = (sec) => { sec = Math.floor(sec || 0); return `${Math.floor(sec / 3600)}:${String(Math.floor(sec % 3600 / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`; };
let dgTimer = null, dgBusy = false, dgPing = null;       // dgPing: the last ping result stays visible while the view refreshes
async function initDiag() {
  const o = overview || await api("/api/overview"); overview = o; const cur = $("dg-conn").value;
  $("dg-conn").innerHTML = o.connections.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.ip)})</option>`).join("");
  if (cur && o.connections.some((c) => c.id === cur)) $("dg-conn").value = cur; else if ($("c-conn").value) $("dg-conn").value = $("c-conn").value;
  await refreshDiag();
  clearInterval(dgTimer); dgTimer = setInterval(() => { if (view === "diag" && $("dg-auto").checked) refreshDiag(); }, 2000);
}
async function refreshDiag(ping) {
  const id = $("dg-conn").value; if (!id || dgBusy) { if (!id) $("dg-body").innerHTML = '<p class="muted">Brak połączeń.</p>'; return; }
  dgBusy = true;
  try { const d = await api(`/api/connections/${id}/diag` + (ping ? "?ping=1" : "")); if (ping) dgPing = { id, ms: d.ping_ms, at: new Date() };
    renderDiag(d); $("dg-msg").textContent = ""; }
  catch (e) { $("dg-msg").textContent = "Błąd: " + e.message; }
  dgBusy = false;
}
function renderDiag(d) {
  const L = d.link, col = DG_COLOR[d.rating] || "#8a8a8a", seg = DG_SCORE[d.rating] ?? 0;
  const bar = Array.from({ length: 10 }, (_, i) => `<i style="background:${col};opacity:${i < seg ? 1 : 0.25}"></i>`).join("");
  const keys = [["last", "Chwilowo"], ["avg10", "Śr. 10 s"], ["avg60", "Śr. 60 s"], ["avg", "Śr. całość"], ["min", "Min"], ["max", "Max"], ["std", "Odch. std."], ["p95", "P95"], ["p99", "P99"]];
  const row = (title, o, extra) => `<tr><th>${title}</th>${keys.map(([k]) => `<td>${dgF(o?.[k])}</td>`).join("")}${extra || ""}</tr>`;
  let h = `<div class="dg-rate"><b style="color:${col}">${esc(d.rating)}</b> <span class="dg-bar">${bar}</span> <span class="muted">${esc(d.name)} · ${esc(d.ip)} · ${esc(d.state)}${d.message ? " · " + esc(d.message) : ""} · metoda: ${esc(d.method)}</span></div>`;
  h += "<ul>" + d.notes.map((n) => `<li>${boldNums(n)}</li>`).join("") + "</ul>";
  if (dgPing && dgPing.id === d.id) h += `<p>Ping ICMP sterownika (z serwera, ${dgPing.at.toLocaleTimeString("pl-PL")}): <b>${dgPing.ms === null ? "brak odpowiedzi" : dgPing.ms + " ms"}</b></p>`;
  if (L) {
    h += `<h3>Czasy [ms]</h3><table class="dg"><thead><tr><th></th>${keys.map(([, t]) => `<th>${t}</th>`).join("")}</tr></thead><tbody>${row("Czas odczytu", L.lag)}${row("Okres próbkowania", L.period)}</tbody></table>`;
    h += `<h3>Odczyt</h3><table class="dg"><tbody>
      <tr><th>Cykl ustawiony</th><td>${dgF(L.cycle_ms, 0)} ms</td><th>Częstotliwość oczekiwana</th><td>${dgF(L.expected_rate)} Hz</td><th>Rzeczywista (10 s / całość)</th><td>${dgF(L.rate10)} / ${dgF(L.rate)} Hz</td><th>Maks. możliwa</th><td>${dgF(L.max_rate)} Hz</td></tr>
      <tr><th>Próbki</th><td>${L.samples}</td><th>Pominięte cykle</th><td>${L.missed} (${dgF(L.missed_pct, 2)}%)</td><th>Odczyty dłuższe niż cykl</th><td>${L.overruns} (${dgF(L.overrun_pct, 2)}%)</td><th>Zalecany cykl</th><td>≥ ${L.safe_cycle_ms} ms</td></tr>
      <tr><th>Błędy odczytu</th><td>${L.errors}</td><th>Ponowne połączenia</th><td>${L.reconnects}</td><th>Czas przerw / dostępność</th><td>${dgF(L.down_s)} s / ${dgF(L.availability, 2)}%</td><th>Czas pracy</th><td>${dgHms(L.uptime_s)}</td></tr>
      <tr><th>Dane na cykl</th><td>${L.bytes_per_cycle} B w ${L.req_per_cycle} żądaniach</td><th>Przepustowość</th><td>${dgF(L.bytes_per_s, 0)} B/s, ${dgF(L.req_per_s)} żądań/s</td><th>Ruch w sieci (szacunek)</th><td>${dgF(L.wire_bytes_per_s * 8 / 1000)} kb/s</td><th>Ostatni błąd</th><td>${esc(L.last_error || "—")}</td></tr></tbody></table>`;
  }
  h += `<h3>Sterownik</h3>` + (d.device.length ? `<table class="dg"><tbody>${d.device.map(([a, b]) => `<tr><th>${esc(a)}</th><td>${esc(b)}</td></tr>`).join("")}</tbody></table>`
    : '<p class="muted">Brak danych sterownika – pojawią się po pierwszym połączeniu.</p>');
  if (d.plc_time) h += `<p>Czas sterownika (w chwili połączenia): <b>${esc(d.plc_time.time)}</b>${d.plc_time.utc ? " (UTC)" : ""}, różnica do zegara serwera <b>${esc(d.plc_time.diff_text)}</b>.</p>`;
  h += `<h3>Kto jeszcze odczytuje ten sterownik</h3>` + (d.others.length ? "<ul>" + d.others.map((x) => `<li>${esc(x)}</li>`).join("") + "</ul>" : '<p class="muted">Nikt inny (wśród programów okienkowych zgłaszających się do serwera i połączeń tego serwera).</p>');
  if (me.role === "admin") h += `<h3>Zaległe bufory zapisu (dysk serwera)</h3>` + (d.spools.length ? `<table class="dg"><thead><tr><th>Bufor</th><th>Cel</th><th>Nagranie</th><th>Wpisów</th><th>Rozmiar</th></tr></thead><tbody>${d.spools.map((x) =>
    `<tr><td>${esc(x.name)}</td><td>${esc(x.target)}</td><td>${esc(x.title)}</td><td>${x.rows}</td><td>${(x.size / 1024).toFixed(0)} KB</td></tr>`).join("")}</tbody></table><p class="muted">Dane zostaną dosłane przy następnym nagraniu do tej samej bazy.</p>`
    : '<p class="muted">Brak – wszystko dostarczone.</p>');
  $("dg-body").innerHTML = h;
}
$("dg-conn").addEventListener("change", () => refreshDiag()); $("dg-refresh").addEventListener("click", () => refreshDiag()); $("dg-ping").addEventListener("click", () => refreshDiag(true));

// ---------------------------------------------------------------- recording targets (administrator)
let targets = [];
async function refreshTargets() {
  targets = (await api("/api/targets")).targets;
  $("t-targets").tBodies[0].innerHTML = targets.map((t) => `<tr><td><b>${esc(t.name)}</b></td><td>${esc(t.kind)}</td><td>${esc(t.label)}</td>
    <td>${Object.entries(t.secrets_set || {}).filter(([, v]) => v).map(([k]) => k).join(", ") || "–"}</td>
    <td><button onclick="editTarget('${esc(t.name)}')">Edytuj</button> <button onclick="testTarget('${esc(t.name)}')">Test</button>
    <button onclick="delTarget('${esc(t.name)}')">Usuń</button></td></tr>`).join("") || '<tr><td colspan="5" class="muted">Brak celów – użytkownicy mogą nagrywać do CSV i do SQLite w folderze konta.</td></tr>';
  showKind();
}
function showKind() { const k = $("g-kind").value; document.querySelectorAll("#g-form [data-k]").forEach((l) => { l.hidden = !l.dataset.k.split(" ").includes(k); }); }
$("g-kind").addEventListener("change", showKind);
window.editTarget = (name) => { const t = targets.find((x) => x.name === name); $("g-title").textContent = "Edycja celu: " + name; $("g-name").value = name; $("g-name").readOnly = true;
  $("g-kind").value = t.kind; showKind(); document.querySelectorAll("#g-form [data-f]").forEach((el) => { const v = t.fields[el.dataset.f]; if (v !== undefined) { if (el.type === "checkbox") el.checked = !!v; else el.value = v; } if (el.type === "password") el.value = ""; }); };
$("g-new").addEventListener("click", () => { $("g-title").textContent = "Nowy cel"; $("g-name").value = ""; $("g-name").readOnly = false; $("g-form").reset(); showKind(); });
$("g-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("g-msg").textContent = "";
  const fields = { kind: $("g-kind").value };
  document.querySelectorAll("#g-form [data-f]").forEach((el) => { if (!el.closest("label").hidden) fields[el.dataset.f] = el.type === "number" ? +el.value : el.type === "checkbox" ? el.checked : el.value; });
  try { await api("/api/targets", { action: "update", name: $("g-name").value, fields }); $("g-msg").textContent = "Zapisano."; refreshTargets(); } catch (err) { $("g-msg").textContent = err.message; }
});
window.testTarget = async (name) => { const d = await api("/api/targets", { action: "test", name }); alert((d.ok ? "OK: " : "Błąd: ") + d.message); };
window.delTarget = async (name) => { if (confirm("Usunąć cel " + name + "?")) { await api("/api/targets", { action: "delete", name }); refreshTargets(); } };

// ---------------------------------------------------------------- accounts
async function refreshTokens() {
  const d = await api("/api/agent-tokens");
  $("t-tokens").tBodies[0].innerHTML = d.tokens.map((t) => `<tr><td><b>${esc(t.name)}</b></td><td>${fmtTime(t.created_us)}</td><td>${fmtTime(t.last_us)}</td>
    <td><button onclick="delToken('${esc(t.name)}')">Usuń</button></td></tr>`).join("") || '<tr><td colspan="4" class="muted">Brak tokenów.</td></tr>';
}
window.delToken = async (name) => { if (confirm("Usunąć token „" + name + "”? Program, który go używa, przestanie się zgłaszać.")) { await api("/api/agent-tokens", { action: "delete", name }); refreshTokens(); } };
$("k-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("k-error").textContent = "";
  try { const d = await api("/api/agent-tokens", { action: "add", name: $("k-name").value }); $("k-name").value = "";
    prompt("Token programu (pokazany tylko raz – skopiuj i wklej w programie: Ustawienia → Serwer Web):", d.token); refreshTokens(); }
  catch (err) { $("k-error").textContent = err.message; }
});
async function refreshUsers() {
  refreshTokens();
  const d = await api("/api/users");
  $("t-users").tBodies[0].innerHTML = d.users.map((u) => `<tr><td><b>${esc(u.username)}</b></td><td>${esc(u.kind_label)}</td><td>
    <select onchange="userAct('role','${esc(u.username)}',{role:this.value})">${["viewer", "operator", "admin"].map((r) =>
      `<option value="${r}" ${u.role === r ? "selected" : ""}>${{ viewer: "podgląd", operator: "operator", admin: "administrator" }[r]}</option>`).join("")}</select></td>
    <td>${fmtTime(u.last_login_us)}</td><td>${u.disabled ? "zablokowane" : "aktywne"}</td><td>
    <button onclick="userAct('disable','${esc(u.username)}',{disabled:${!u.disabled}})">${u.disabled ? "Odblokuj" : "Zablokuj"}</button>
    ${u.kind === "local" ? `<button onclick="resetPw('${esc(u.username)}')">Nowe hasło</button>` : ""}
    <button onclick="if(confirm('Usunąć konto?'))userAct('delete','${esc(u.username)}',{})">Usuń</button></td></tr>`).join("");
}
window.userAct = async (action, username, extra) => { try { await api("/api/users", { action, username, ...extra }); } catch (e) { alert(e.message); } refreshUsers(); };
window.resetPw = (u) => { const p = prompt(`Nowe hasło dla ${u} (min. 8 znaków):`); if (p) userAct("password", u, { password: p }); };
$("u-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("u-error").textContent = "";
  try { await api("/api/users", { action: "add", username: $("u-name").value, kind: $("u-kind").value, password: $("u-pass").value, role: $("u-role").value });
    $("u-name").value = $("u-pass").value = ""; refreshUsers(); } catch (err) { $("u-error").textContent = err.message; }
});
$("u-kind").addEventListener("change", () => { $("u-pass").hidden = $("u-kind").value === "windows"; });

start();


// ---------------------------------------------------------------- layout of the settings panel (the counterpart of the desktop one):
// groups fold on a title click, are moved by dragging the title up / down, single elements are hidden / shown by a right click;
// order / folds / hidden elements / bottom tab are kept per account on the server (the names of the elements = panel_cfg.WEB_ROWS)
const PANEL_GROUPS = ["Połączenie", "Sterownik", "Zakres okna wykresu", "Trigger", "Nagrywanie REC"];
const PANEL_ROWS = {
  "Połączenie": ["Nazwa", "Adres IP", "Rack", "Slot", "Cykl [ms]", "Sposób połączenia", "Tryb odczytu", "Kreator"],
  "Sterownik": ["Rodzina", "Model", "Numer katalogowy (MLFB)", "Firmware", "Numer seryjny", "Nazwa stacji", "Nazwa modułu", "Producent / copyright", "Stan CPU", "Długość PDU [B]", "Czas PLC", "Pobierz dane"],
  "Zakres okna wykresu": ["Okno czasu [s]", "Układ wykresu", "Auto Y", "Y min", "Y maks", "Punkty", "Legenda", "Oś czasu", "Offset osi"],
  "Trigger": ["Włączony", "Sygnał", "Warunek", "A", "B", "Histereza", "Przedtrigger [s]", "Akcja", "Nazwa pliku zapisu"],
  "Nagrywanie REC": ["Cel zapisu", "Tryb", "Nazwa pliku CSV"],
  "System": ["Godzina systemowa", "System operacyjny", "Obciążenie CPU", "w tym ten serwer"],
  "Sieć": ["Czas odczytu śr.", "Czas odczytu ost.", "Pominięte cykle", "Ping"],
};
const PANEL_DEFAULT_HIDDEN = { "Sterownik": ["Numer katalogowy (MLFB)", "Numer seryjny", "Producent / copyright", "Stan CPU", "Długość PDU [B]"] };
let PANEL = { order: PANEL_GROUPS.slice(), folds: {}, hidden: JSON.parse(JSON.stringify(PANEL_DEFAULT_HIDDEN)), info_tab: 0 }, panelSave = null;
function panelNormalize(raw) {
  raw = raw && typeof raw === "object" ? raw : {};
  const order = []; for (const g of raw.order || []) if (PANEL_GROUPS.includes(g) && !order.includes(g)) order.push(g);
  for (const g of PANEL_GROUPS) if (!order.includes(g)) order.push(g);
  const folds = {}; for (const g of PANEL_GROUPS) folds[g] = !!(raw.folds && raw.folds[g]);
  const hidden = {}; for (const g of Object.keys(PANEL_ROWS)) { const want = Array.isArray(raw.hidden?.[g]) ? raw.hidden[g] : (PANEL_DEFAULT_HIDDEN[g] || []); hidden[g] = PANEL_ROWS[g].filter((k) => want.includes(k)); }
  const t = Number(raw.info_tab); return { order, folds, hidden, info_tab: t === 1 ? 1 : 0 };
}
function panelFolds() { return [...document.querySelectorAll("#e-folds .fold")]; }
function panelApplyHidden() {
  panelFolds().forEach((f) => f.querySelectorAll("[data-row]").forEach((e) => e.classList.toggle("row-hidden", (PANEL.hidden[f.dataset.fold] || []).includes(e.dataset.row))));
}
function panelApply() {
  const box = $("e-folds"); if (!box) return;
  const by = {}; panelFolds().forEach((f) => { by[f.dataset.fold] = f; });
  PANEL.order.forEach((g) => { if (by[g]) box.appendChild(by[g]); });
  panelFolds().forEach((f) => f.classList.toggle("folded", !!PANEL.folds[f.dataset.fold]));
  panelApplyHidden();
  sideTab(PANEL.info_tab, true);
}
function panelCollect() {            // order and folds come from the page, the hidden elements are kept in PANEL.hidden
  PANEL = { ...PANEL, order: panelFolds().map((f) => f.dataset.fold), folds: Object.fromEntries(panelFolds().map((f) => [f.dataset.fold, f.classList.contains("folded")])) };
}
function panelPersist() {
  panelCollect(); clearTimeout(panelSave);
  panelSave = setTimeout(() => { api("/api/prefs", { panel: PANEL }).catch(() => {}); }, 400);
}
async function panelLoad() { try { PANEL = panelNormalize((await api("/api/prefs")).prefs.panel); } catch (e) { /* defaults */ } panelApply(); }
(() => {
  document.querySelectorAll("#e-folds .fold").forEach((f) => {
    const h = f.querySelector(".fold-h"); h.classList.add("grab"); h.title = "Kliknij: zwiń / rozwiń. Przeciągnij w górę lub w dół: zmień kolejność pól. Prawy przycisk: elementy pola.";
    let down = null, drag = false;
    h.addEventListener("pointerdown", (e) => { if (e.button !== 0) return; down = { x: e.clientX, y: e.clientY }; drag = false; h.setPointerCapture(e.pointerId); });
    h.addEventListener("pointermove", (e) => {
      if (!down) return;
      if (!drag && Math.abs(e.clientY - down.y) > 5) { drag = true; f.classList.add("dragging"); }
      if (!drag) return;
      const others = panelFolds().filter((x) => x !== f); let before = null;
      for (const o of others) { const r = o.getBoundingClientRect(); if (e.clientY < r.top + r.height / 2) { before = o; break; } }
      const box = $("e-folds");
      if (before) { if (f.nextElementSibling !== before) box.insertBefore(f, before); } else if (box.lastElementChild !== f) box.appendChild(f);
    });
    const end = (e) => {
      if (!down) return; const was = drag; down = null; drag = false; f.classList.remove("dragging");
      try { h.releasePointerCapture(e.pointerId); } catch (x) { /* already released */ }
      if (e.type === "pointercancel") return;
      if (!was) f.classList.toggle("folded");
      panelPersist();
    };
    h.addEventListener("pointerup", end); h.addEventListener("pointercancel", end);
  });
})();

// right click on the name of an element hides it; right click on the title of a group lists its elements (check list) and folds it
function ctxMenu(x, y, items) {                                       // items: [label, fn | null, checked | undefined, children?] | "-" | [text] (a heading); children = a submenu
  document.querySelectorAll(".ctx-menu").forEach((m) => m.remove());
  const open = [];                                                     // the menu and its open submenus
  const build = (its, px, py, level) => {
    open.splice(level).forEach((m) => m.remove());
    const m = document.createElement("div"); m.className = "ctx-menu"; open[level] = m;
    its.forEach((it) => {
      if (it === "-") { m.appendChild(document.createElement("hr")); return; }
      const d = document.createElement("div"); const [label, fn, checked, kids] = it;
      d.textContent = (checked === undefined ? "" : checked ? "✓ " : " ") + label + (kids ? "   ▸" : "");
      if (kids) {
        d.className = "sub";
        const show = () => { const r = d.getBoundingClientRect(); build(kids, r.right - 2, r.top - 4, level + 1); };
        d.addEventListener("mouseenter", show); d.addEventListener("click", show);
      } else {
        if (!fn) d.className = fn === undefined ? "head" : "off"; else d.addEventListener("click", () => { open.forEach((q) => q.remove()); fn(); });
        d.addEventListener("mouseenter", () => open.splice(level + 1).forEach((q) => q.remove()));
      }
      m.appendChild(d);
    });
    document.body.appendChild(m);
    m.style.left = Math.max(2, Math.min(px, innerWidth - m.offsetWidth - 4)) + "px"; m.style.top = Math.max(2, Math.min(py, innerHeight - m.offsetHeight - 4)) + "px";
  };
  build(items, x, y, 0);
  const close = (e) => { if (!open.some((m) => m.contains(e.target))) { open.forEach((m) => m.remove()); removeEventListener("pointerdown", close, true); } };
  addEventListener("pointerdown", close, true);
}
// status bar (chart page): right click = most lines, colours, justification; the same settings as the desktop status bar, kept per account
let STATUS = { lines: 1, bg: "", text: "", align: "right" }, statusSave = null;
function statusApply() {
  const e = $("c-state"); if (!e) return;
  e.classList.toggle("multi", STATUS.lines > 1);
  e.style.maxHeight = STATUS.lines > 1 ? `calc(${STATUS.lines} * 1.35em + 6px)` : "";
  e.style.textAlign = STATUS.align; e.style.background = STATUS.bg || ""; e.style.color = STATUS.text || "";
}
function statusPersist() { statusApply(); clearTimeout(statusSave); statusSave = setTimeout(() => { api("/api/prefs", { status: STATUS }).catch(() => {}); }, 400); }
async function statusLoad() { try { STATUS = { ...STATUS, ...(await api("/api/prefs")).prefs.status }; } catch (e) { /* defaults */ } statusApply(); }
function statusPickColor(key, cur) {
  const i = document.createElement("input"); i.type = "color"; i.value = cur || (key === "bg" ? "#2b2b2b" : "#d0d0d0"); i.style.cssText = "position:fixed;left:-100px;top:0";
  document.body.appendChild(i); i.addEventListener("change", () => { STATUS[key] = i.value; statusPersist(); }); i.addEventListener("blur", () => setTimeout(() => i.remove(), 300)); i.click();
}
$("c-state").addEventListener("contextmenu", (e) => {
  e.preventDefault();
  ctxMenu(e.clientX, e.clientY, [
    ["Maksymalna liczba wierszy w pasku", null, undefined, [1, 2, 3, 4, 5, 6, 8, 10].map((n) => [`${n}`, () => { STATUS.lines = n; statusPersist(); }, STATUS.lines === n])], "-",
    ["Kolor tła paska…", () => statusPickColor("bg", STATUS.bg)], ["Kolor tekstu paska…", () => statusPickColor("text", STATUS.text)],
    ["Kolory domyślne (jak strona)", STATUS.bg || STATUS.text ? () => { STATUS.bg = STATUS.text = ""; statusPersist(); } : null], "-",
    ["Justowanie tekstu", null, undefined, [["do lewej", () => { STATUS.align = "left"; statusPersist(); }, STATUS.align === "left"],
      ["do prawej", () => { STATUS.align = "right"; statusPersist(); }, STATUS.align === "right"]]]]);
});
function panelSetRow(group, key, show) {
  const h = (PANEL.hidden[group] || []).filter((k) => k !== key); if (!show) h.push(key);
  PANEL.hidden[group] = PANEL_ROWS[group].filter((k) => h.includes(k));
  panelApplyHidden(); sideRefresh(true); panelPersist();
}
function panelRowItems(group) {
  const hid = PANEL.hidden[group] || [];
  const items = PANEL_ROWS[group].map((k) => [k === "Pobierz dane" ? "Pobierz dane sterownika (przycisk)" : k, () => panelSetRow(group, k, hid.includes(k)), !hid.includes(k)]);
  return [...items, "-", ["Pokaż wszystkie elementy", hid.length ? () => { PANEL.hidden[group] = []; panelApplyHidden(); sideRefresh(true); panelPersist(); } : null]];
}
const panelDeviceItem = (group) => (group === "Sterownik" ? [["Pobierz dane sterownika", () => $("e-readdev").click()], "-"] : []);
$("e-folds").addEventListener("contextmenu", (e) => {
  const f = e.target.closest(".fold"); if (!f) return;
  const g = f.dataset.fold, row = e.target.closest("[data-row]");
  if (e.target.closest(".fold-h")) {
    e.preventDefault();
    ctxMenu(e.clientX, e.clientY, [[f.classList.contains("folded") ? "Rozwiń pole" : "Zwiń pole", () => { f.classList.toggle("folded"); panelPersist(); }], "-", ...panelDeviceItem(g), [`Elementy pola „${g}”`], ...panelRowItems(g)]);
  } else if (row && (e.target.closest("label") === row || row.tagName !== "LABEL") && !e.target.closest("input,select,textarea")) {
    e.preventDefault();
    ctxMenu(e.clientX, e.clientY, [[`Ukryj „${row.dataset.row}”`, () => panelSetRow(g, row.dataset.row, false)], "-", ...panelDeviceItem(g), [`Elementy pola „${g}”`], ...panelRowItems(g)]);
  }
});


// ---------------------------------------------------------------- 'System' / 'Sieć' tabs under the chart (the counterpart of the tabs at the bottom of the program's left panel)
let sideTimer = null, sideBusy = false, sideLast = null;
function sideTab(n, silent) {
  PANEL.info_tab = n === 1 ? 1 : 0;
  document.querySelectorAll("#c-side .side-tabs button").forEach((b) => b.classList.toggle("on", Number(b.dataset.tab) === PANEL.info_tab));
  if (!silent) { panelPersist(); sideRefresh(); }
}
document.querySelectorAll("#c-side .side-tabs button").forEach((b) => b.addEventListener("click", () => sideTab(Number(b.dataset.tab))));
function sideRender() {                        // rows that are not hidden; each row can be hidden by a right click
  if (!sideLast) return;
  const group = sideLast.group, hid = PANEL.hidden[group] || [];
  $("c-side-body").innerHTML = sideLast.rows
    ? "<table>" + sideLast.rows.filter(([k]) => !hid.includes(k)).map(([k, v]) => `<tr data-row="${esc(k)}"><td>${esc(k)}:</td><td><b>${esc(String(v))}</b></td></tr>`).join("") + "</table>"
    : '<i class="muted">Brak połączenia ze sterownikiem – parametry sieci pojawią się po Start.</i>';
}
async function sideRefresh(redrawOnly) {
  if (view !== "chart" || (sideBusy && !redrawOnly)) return;
  if (redrawOnly) { sideRender(); return; }
  sideBusy = true;
  try {
    if (PANEL.info_tab === 0) {
      const d = await api("/api/sysinfo");
      sideLast = { group: "System", rows: [["Godzina systemowa", d.time], ["System operacyjny", d.os || "—"], ["Obciążenie CPU", d.cpu === null ? "—" : d.cpu.toFixed(0) + " %"],
        ["w tym ten serwer", d.app_cpu === null || d.app_cpu === undefined ? "—" : d.app_cpu.toFixed(1) + " %"]] };
    } else {
      const id = $("c-conn").value; const d = id ? await api(`/api/connections/${id}/diag?ping=1`) : null; const L = d && d.link;
      sideLast = { group: "Sieć", rows: L ? [["Czas odczytu śr.", `${dgF(L.lag?.avg)} ms (n=${L.samples})`], ["Czas odczytu ost.", `${dgF(L.lag?.last)} ms`],
        ["Pominięte cykle", `${L.missed} (${dgF(L.missed_pct)}%)`], ["Ping", d.ping_ms === null || d.ping_ms === undefined ? "brak odpowiedzi" : d.ping_ms + " ms"]] : null };
    }
    sideRender();
  } catch (e) { /* the next tick tries again */ }
  sideBusy = false;
}
$("c-side").addEventListener("contextmenu", (e) => {
  const g = PANEL.info_tab === 1 ? "Sieć" : "System", row = e.target.closest("tr[data-row]"); e.preventDefault();
  ctxMenu(e.clientX, e.clientY, [...(row ? [[`Ukryj „${row.dataset.row}”`, () => panelSetRow(g, row.dataset.row, false)], "-"] : []), [`Elementy: ${g}`], ...panelRowItems(g)]);
});
sideTimer = setInterval(() => { if (view === "chart") sideRefresh(); }, 1500);


// ---------------------------------------------------------------- "O programie" and the help mode ("?": the element under the mouse is described)
$("about-btn").addEventListener("click", async () => {
  try { const v = await (await fetch("/api/version")).json(); $("about-text").textContent = `S7Trace — rejestrator przebiegów z PLC Siemens S7\n(tryb Web)\n\nAutor: ${v.author}\nWersja: ${v.version}\nData: ${v.date}`; } catch (e) { $("about-text").textContent = "Brak danych o wersji."; }
  $("about").showModal();
});
$("about-ok").addEventListener("click", () => $("about").close());
fetch("/api/version").then((r) => r.json()).then((v) => { document.querySelector(".brand").title = `Wersja ${v.version} (${v.date}), autor: ${v.author}`; }).catch(() => {});
(() => {
  let HELP = null, on = false;
  const norm = (t) => { t = (t || "").replace(/&/g, "").replace(/ /g, " ").trim().toLowerCase(); while (t && ":….?".includes(t.at(-1))) t = t.slice(0, -1).trimEnd(); return t.split(/\s+/).join(" "); };
  const own = (el) => [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ").trim() || el.textContent.trim();
  const caption = (el) => {
    if (el.dataset?.help) return el.dataset.help;
    if (el.matches?.("button,summary,h2,h3,th,legend")) return el.textContent;
    const lab = el.closest?.("label"); if (lab) return own(lab);
    if (el.id && document.querySelector(`label[for="${el.id}"]`)) return document.querySelector(`label[for="${el.id}"]`).textContent;
    if (el.matches?.("td")) { const t = el.closest("table"), th = t?.tHead?.rows[0]?.cells[el.cellIndex]; if (th) return th.textContent; }
    return "";
  };
  const resolve = (el) => {
    for (let e = el, d = 0; e && d < 6; e = e.parentElement, d++) {
      const cap = caption(e), t = cap && HELP[norm(cap)];
      if (t) return t;
      if (e.title && !e.matches("body,main,section")) return "Opis: " + e.title;
    }
    const e = el.closest?.("button") ? "Przycisk" : el.matches?.("input,select,textarea") ? "Pole" : "Element";
    return `${e}${(caption(el) || "").trim() ? " „" + caption(el).trim() + "”" : ""}.\nPo najechaniu na element z opisem widać, do czego służy.`;
  };
  const show = (e) => {
    const b = $("helpbubble"), t = resolve(e.target); if (!t) { b.hidden = true; return; }
    b.innerHTML = t.split("\n").map((l) => { const i = l.indexOf(": "); return i > 0 && i < 24 ? `<b>${esc(l.slice(0, i))}:</b> ${esc(l.slice(i + 2))}` : esc(l); }).join("<br>");
    b.hidden = false; b.style.left = Math.min(e.clientX + 14, innerWidth - 440) + "px"; b.style.top = Math.min(e.clientY + 18, innerHeight - b.offsetHeight - 8) + "px";
  };
  const set = async (v) => {
    on = v; $("help-btn").classList.toggle("on", on); document.body.classList.toggle("helpmode", on); $("helpbubble").hidden = true;
    if (on && !HELP) { try { HELP = (await (await fetch("/api/help")).json()).help; } catch (e) { HELP = {}; } }
  };
  $("help-btn").addEventListener("click", () => set(!on));
  document.addEventListener("mouseover", (e) => { if (on && HELP && e.target !== $("help-btn")) show(e); });
  document.addEventListener("mousemove", (e) => { if (on && HELP && !$("helpbubble").hidden) { const b = $("helpbubble"); b.style.left = Math.min(e.clientX + 14, innerWidth - 440) + "px"; b.style.top = Math.min(e.clientY + 18, innerHeight - b.offsetHeight - 8) + "px"; } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && on) set(false); if (e.key === "F1" && e.shiftKey) { e.preventDefault(); set(!on); } });
})();

// column widths of the list tables are set by dragging the right border of a header cell (as in the program's tables)
function tableResizable(table) {
  if (!table || table.dataset.rs) return; table.dataset.rs = "1";
  const ths = [...table.querySelectorAll("thead th")];
  ths.slice(0, -1).forEach((th) => {
    const h = document.createElement("span"); h.className = "col-rs"; th.appendChild(h);
    h.addEventListener("pointerdown", (e) => {
      e.preventDefault(); e.stopPropagation(); h.setPointerCapture(e.pointerId); h.classList.add("on");
      if (table.style.tableLayout !== "fixed") { ths.forEach((t) => { t.style.width = t.offsetWidth + "px"; }); table.style.tableLayout = "fixed"; }
      const x0 = e.clientX, w0 = th.offsetWidth;
      const move = (ev) => { th.style.width = Math.max(30, w0 + ev.clientX - x0) + "px"; };
      const up = () => { h.classList.remove("on"); h.removeEventListener("pointermove", move); h.removeEventListener("pointerup", up); };
      h.addEventListener("pointermove", move); h.addEventListener("pointerup", up);
    });
    h.addEventListener("click", (e) => e.stopPropagation());                       // a drag must not sort / click the header
  });
}
["t-conn", "t-agents", "t-sess", "e-sig", "t-recs", "t-mkl", "t-targets", "t-users", "t-tokens", "mkp-t"].forEach((id) => tableResizable(document.getElementById(id)));

// colours of the tables (header, odd / even rows, frame): the same seven settings as the desktop interface configuration, kept per account
const TABLE_COLORS = [["header_bg", "Kolor tła nagłówka tabeli", "--tb-head-bg"], ["header_text", "Kolor czcionki nagłówka tabeli", "--tb-head-text"],
  ["odd_bg", "Kolor tła wierszy nieparzystych", "--tb-odd-bg"], ["odd_text", "Kolor czcionki wierszy nieparzystych", "--tb-odd-text"],
  ["even_bg", "Kolor tła wierszy parzystych", "--tb-even-bg"], ["even_text", "Kolor czcionki wierszy parzystych", "--tb-even-text"],
  ["border", "Kolor ramki tabeli", "--tb-border"]];
// names of the signals on the chart: 'legend' (list under the chart) or 'labels' (a boxed name at every signal); per account, like the desktop interface configuration
let legSave = null;
function legendStyleApply() { document.querySelectorAll("[data-x=lst]").forEach((s) => { s.value = LEGSTYLE; }); }
function legendStyleSet(v) {
  LEGSTYLE = v === "labels" ? "labels" : "legend"; legendStyleApply();
  clearTimeout(legSave); legSave = setTimeout(() => { api("/api/prefs", { legend_style: LEGSTYLE }).catch(() => {}); }, 400);
  if (typeof draw === "function") draw(); if (typeof rv !== "undefined" && rv.data) drawRec();
}
async function legendStyleLoad() { try { LEGSTYLE = (await api("/api/prefs")).prefs.legend_style === "labels" ? "labels" : "legend"; } catch (e) { /* default */ } legendStyleApply(); if (typeof draw === "function") draw(); }
let TBL = {}, tblSave = null;
function tableColorsApply() { for (const [k, , v] of TABLE_COLORS) { if (TBL[k]) document.documentElement.style.setProperty(v, TBL[k]); else document.documentElement.style.removeProperty(v); } }
function tableColorsPersist() { tableColorsApply(); clearTimeout(tblSave); tblSave = setTimeout(() => { api("/api/prefs", { table: TBL }).catch(() => {}); }, 400); }
async function tableColorsLoad() { try { TBL = { ...((await api("/api/prefs")).prefs.table || {}) }; } catch (e) { /* defaults */ } tableColorsApply(); }
function rgbHex(c) { const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(c || ""); return m ? "#" + [m[1], m[2], m[3]].map((x) => (+x).toString(16).padStart(2, "0")).join("") : "#808080"; }
function tableColorsDialog() {
  const box = $("ui-rows"); box.innerHTML = "";
  const th = document.querySelector("th"), td = document.querySelector("td") || th;
  const dflt = { header_bg: rgbHex(th && getComputedStyle(th).backgroundColor), header_text: rgbHex(th && getComputedStyle(th).color), odd_bg: rgbHex(getComputedStyle(document.body).backgroundColor),
    odd_text: rgbHex(td && getComputedStyle(td).color), even_bg: "#2f2f2f", even_text: rgbHex(td && getComputedStyle(td).color), border: "#454545" };
  for (const [k, label] of TABLE_COLORS) {
    const r = document.createElement("div"); r.className = "urow";
    const l = document.createElement("label"); l.textContent = label; const i = document.createElement("input"); i.type = "color"; i.value = TBL[k] || dflt[k];
    i.addEventListener("input", () => { TBL[k] = i.value; tableColorsPersist(); });
    r.append(l, i); box.appendChild(r);
  }
  if (!$("ui-dlg").open) $("ui-dlg").showModal();
}
$("ui-btn").addEventListener("click", tableColorsDialog);
$("ui-close").addEventListener("click", () => $("ui-dlg").close());
$("ui-reset").addEventListener("click", () => { TBL = {}; tableColorsPersist(); tableColorsDialog(); });

// a click on a header sorts the table (ascending, then descending; numbers and times in the text compare as numbers); a re-render keeps the sort
function naturalKey(t) { return String(t).toLowerCase().split(/(\d+(?:[.,]\d+)?)/).map((p, i) => (i % 2 ? [0, parseFloat(p.replace(",", "."))] : [1, p])); }
function naturalCmp(a, b) {
  const ka = naturalKey(a), kb = naturalKey(b);
  for (let i = 0; i < Math.min(ka.length, kb.length); i++) {
    const [ta, va] = ka[i], [tb, vb] = kb[i];
    if (ta !== tb) return ta - tb;
    if (va !== vb) return va < vb ? -1 : 1;
  }
  return ka.length - kb.length;
}
function tableSortable(table) {
  if (!table || table.dataset.srt) return; table.dataset.srt = "1";
  const body = table.tBodies[0]; if (!body) return;
  const ths = [...table.querySelectorAll("thead th")];
  let col = -1, dir = 1, busy = false, mo = null;
  const apply = () => {
    if (col < 0 || busy) return; busy = true;
    const rows = [...body.rows].filter((r) => r.cells.length > col);
    rows.sort((a, b) => dir * naturalCmp(a.cells[col].textContent.trim(), b.cells[col].textContent.trim())).forEach((r) => body.appendChild(r));
    if (mo) mo.takeRecords();                           // our own re-ordering must not trigger another sort
    busy = false;
  };
  ths.forEach((th, i) => {
    if (!th.textContent.trim()) return;
    th.style.cursor = "pointer"; th.title = (th.title ? th.title + " – " : "") + "Kliknij: sortuj";
    th.addEventListener("click", () => {
      dir = col === i ? -dir : 1; col = i;
      ths.forEach((t) => t.classList.remove("s-asc", "s-desc")); th.classList.add(dir > 0 ? "s-asc" : "s-desc"); apply();
    });
  });
  mo = new MutationObserver(() => { if (!busy) apply(); }); mo.observe(body, { childList: true });
}
["t-conn", "t-agents", "t-sess", "t-recs", "t-mkl", "t-targets", "t-users", "t-tokens", "mkp-t"].forEach((id) => tableSortable(document.getElementById(id)));
