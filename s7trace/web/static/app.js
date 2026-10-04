"use strict";
// S7Trace web mode: login, overview (connections / controllers / users), live chart (Server-Sent Events), accounts.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
}
async function start() {
  me = await api("/api/me");
  if (!me.user) return showLogin();
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
  else d = { name: "", ip: "192.168.0.1", rack: 0, slot: 2, cycle_ms: 25, window_s: 200, conn_type: "auto", mode: null, state: "stopped",
             signals: [NEW_SIGNAL(1)], options: (await api("/api/options")).options };
  editing = { id, opts: d.options, running: d.state !== "stopped" };
  $("e-title").textContent = id ? `Edycja połączenia: ${d.name || d.ip}` : "Nowe połączenie";
  $("e-note").textContent = editing.running ? "Połączenie jest uruchomione – zmiana adresu, cyklu i sygnałów wymaga jego zatrzymania (nazwa i okno czasu – nie)." : "";
  for (const el of $("e-form").querySelectorAll("input,select,button[type=button]")) if (!["e-cancel", "e-delete"].includes(el.id)) el.disabled = false;
  $("e-name").value = d.name; $("e-ip").value = d.ip; $("e-rack").value = d.rack; $("e-slot").value = d.slot;
  $("e-cycle").value = d.cycle_ms; $("e-window").value = d.window_s;
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
$("e-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("e-error").textContent = "";
  const body = { name: $("e-name").value, window_s: +$("e-window").value,
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
let markTimer = null, searchNames = "", userFrozen = false;
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
  stopStream(); frozen = null; frozenKey = null; lastDesc = null; userFrozen = false; $("c-live").hidden = true;
  const id = $("c-conn").value; if (!id) return;
  conn = (overview?.connections || []).find((c) => c.id === id) || null;
  $("c-filelist").hidden = true;
  series = { t: [], values: [], names: [], colors: [], start_us: 0 };
  const sec = +$("c-sec").value;
  MK.live.marks = []; MK.live.hi = new Set(); clearInterval(markTimer); markTimer = setInterval(() => { if (view === "chart") loadLiveMarks(); }, 2000);
  stream = new EventSource(`/api/connections/${id}/stream?seconds=${sec}`);
  stream.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.reset) { series = { t: d.t, values: d.values, names: d.names, colors: d.colors, start_us: d.start_us }; }   // (identical colours: palette below)
    else { series.t.push(...d.t); d.values.forEach((col, k) => (series.values[k] ||= []).push(...col)); }
    if (d.start_us) series.start_us = d.start_us;
    if (d.names?.length && d.names.join("\u0001") !== searchNames) { searchNames = d.names.join("\u0001"); $("c-search-box")._rebuild?.(); }
    if (d.names?.length) { series.names = d.names; series.colors = new Set(d.colors).size < d.colors.length ? d.colors.map((_, k) => COLORS[k % COLORS.length]) : d.colors; }
    if (d.description) { lastDesc = d.description; describeChart(d.description); }
    const cut = (series.t.at(-1) ?? 0) - sec;
    while (series.t.length && series.t[0] < cut) { series.t.shift(); series.values.forEach((c) => c.shift()); }
    draw();
  };
}
const TRIG_PL = { off: "wyłączony", armed: "uzbrojony", post: "zbieranie próbek po wyzwoleniu…", hold: "WSTRZYMANY (zamrożone okno)" };
function describeChart(d) {
  $("c-state").textContent = `${STATE_PL[d.state] || d.state} – ${d.message || ""}`;
  const t = d.trigger, r = d.rec, canRun = !!conn?.can_run;
  $("c-trig").textContent = t.enabled ? `Trigger (${t.signal}): ${TRIG_PL[t.state] || t.state}${t.note ? " · " + t.note : ""}` : "";
  $("c-rearm").hidden = !(canRun && t.state === "hold");
  $("c-rec").hidden = !canRun; $("c-title").hidden = !canRun || r.active || r.target === "csv";
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
  try { await api(`/api/connections/${id}/rec`, on ? { action: "stop" } : { action: "start", title: $("c-title").value }); } catch (e) { alert(e.message); }
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
$("c-conn").addEventListener("change", connectStream); $("c-sec").addEventListener("change", connectStream);
let drawPending = false;
function draw() { if (drawPending) return; drawPending = true; requestAnimationFrame(() => { drawPending = false; paint(); }); }
function paint() {
  const ds = frozen || series, sec = +$("c-sec").value, t1 = frozen ? frozen.x1 : (ds.t.at(-1) ?? 0), t0 = frozen ? frozen.x0 : t1 - sec;
  drawChart($("canvas"), ds, t0, t1, { mk: MK.live, markers: (lastDesc?.trigger?.events || []).map((e) => e.t), left: frozen ? "okno zamrożone triggerem" : `-${sec} s`,
    right: frozen ? "" : "teraz", empty: "Brak danych – uruchom połączenie (Start) na stronie Przegląd.", legend: $("c-legend") });
}
// one lane per signal, scaled to its own min..max of the shown range; steps (the value holds until the next change)
function drawChart(cv, ds, t0, t1, o) {
  const g = cv.getContext("2d"), W = cv.width, H = cv.height, pad = { l: 60, r: 10, t: 8, b: 24 }, n = ds.names.length;
  g.fillStyle = "#000"; g.fillRect(0, 0, W, H); g.font = "12px sans-serif"; g.strokeStyle = "#333"; g.fillStyle = "#aaa";
  cv._geo = null;
  if (!n || !ds.t.length) { g.fillText(o.empty || "Brak danych.", 70, 30); return; }
  const colors = new Set(ds.colors).size < ds.colors.length ? ds.colors.map((_, k) => COLORS[k % COLORS.length]) : ds.colors;
  const bandH = (H - pad.t - pad.b) / n, X = (t) => pad.l + (t - t0) / ((t1 - t0) || 1) * (W - pad.l - pad.r), lanes = [];
  for (let k = 0; k < n; k++) {
    const col = ds.values[k] || [], top = pad.t + k * bandH, bot = top + bandH - 4, c = colors[k] || COLORS[k % COLORS.length];
    lanes.push({ top, bot });
    const fin = col.filter((x, i) => x !== null && ds.t[i] >= t0 && ds.t[i] <= t1), lo = Math.min(...fin), hi = Math.max(...fin), span = hi - lo || 1;
    g.strokeStyle = "#333"; g.strokeRect(pad.l, top, W - pad.l - pad.r, bandH - 4);
    g.fillStyle = "#aaa"; g.fillText(Number.isFinite(hi) ? hi.toPrecision(4) : "", 4, top + 12); g.fillText(Number.isFinite(lo) ? lo.toPrecision(4) : "", 4, bot);
    g.fillStyle = c; g.fillText(ds.names[k], pad.l + 6, top + 14);
    g.strokeStyle = c; g.lineWidth = 1.2; g.beginPath(); let pen = false, py = 0;
    for (let i = 0; i < ds.t.length; i++) {
      const v = col[i]; if (v === null || v === undefined) { pen = false; continue; }
      const x = X(ds.t[i]), y = bot - (v - lo) / span * (bot - top - 6) - 3;
      if (!pen) { g.moveTo(x, y); pen = true; } else { g.lineTo(x, py); g.lineTo(x, y); }
      py = y;
    }
    if (o.hold && pen) g.lineTo(X(t1), py);          // a recording of changes: the last value holds to the end of the range
    g.stroke();
  }
  cv._geo = { t0, t1, pad, W, H };
  if (o.mk) mkPaint(g, cv, o.mk, cv._geo, lanes);                                    // markers (bookmarks) over the curves
  g.strokeStyle = "#ff4d4d"; g.fillStyle = "#ff4d4d"; g.lineWidth = 1; g.setLineDash([5, 4]);
  for (const t of o.markers || []) { if (t < t0 || t > t1) continue; const x = X(t); g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, H - pad.b); g.stroke(); g.fillText("T", x + 3, H - pad.b - 4); }
  g.setLineDash([]); g.fillStyle = "#aaa"; g.fillText(o.left || "", pad.l, H - 6);
  if (o.right) { const w = g.measureText(o.right).width; g.fillText(o.right, W - pad.r - w, H - 6); }
  if (o.legend) o.legend.innerHTML = ds.names.map((nm, k) => `<span><i style="background:${colors[k] || COLORS[k % COLORS.length]}"></i>${esc(nm)}</span>`).join("");
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
function fillRecs() {
  const q = $("rv-q").value.trim().toLowerCase(), trash = $("rv-trash").checked;
  const rows = rv.list.filter((r) => !q || [r.title, r.tags, r.notes, r.owner, r.computer, r.name, r.ip, r.conf, ...r.signals].join(" ").toLowerCase().includes(q));
  $("t-recs").tBodies[0].innerHTML = rows.map((r) => `<tr><td><b>${esc(r.title || r.conf || r.id)}</b>${r.notes ? `<div class="muted">${esc(r.notes)}</div>` : ""}</td>
    <td>${new Date(r.start_us / 1000).toLocaleString("pl-PL")}</td><td>${r.recording ? "nagrywanie…" : fmtDur(r.start_us, r.end_us)}</td><td>${esc(r.owner)}</td>
    <td class="muted">${esc(r.computer)}</td><td>${esc([r.name || r.tab, r.ip].filter(Boolean).join(" · "))}</td><td class="muted">${esc(r.signals.join(", "))}</td><td>${esc(r.tags)}</td>
    <td><button onclick="loadRec('${esc(r.id)}')">Wczytaj</button> <a href="/api/recordings/csv?source=${enc($("rv-src").value)}&id=${enc(r.id)}" download>CSV</a>
    ${r.can_modify ? `<button onclick="editRec('${esc(r.id)}')">Opis</button> ` + (trash ? `<button onclick="recAct('${esc(r.id)}','restore')">Przywróć</button> <button onclick="recAct('${esc(r.id)}','purge')">Usuń trwale</button>`
      : `<button onclick="recAct('${esc(r.id)}','trash')">${rv.trashDays > 0 ? "Do kosza" : "Usuń"}</button>`) : ""}</td></tr>`).join("")
    || `<tr><td colspan="9" class="muted">${trash ? "Kosz jest pusty." : "Brak nagrań w tym źródle (nagrania powstają przyciskiem REC przy celu „sqlite” albo celu z listy administratora)."}</td></tr>`;
}
$("rv-src").addEventListener("change", () => { $("rv-view").hidden = true; refreshRecs(); });
$("rv-refresh").addEventListener("click", refreshRecs); $("rv-trash").addEventListener("change", refreshRecs); $("rv-q").addEventListener("input", fillRecs);
window.recAct = async (id, action) => {
  const text = { trash: rv.trashDays > 0 ? `Przenieść nagranie do kosza (do ${rv.trashDays} dni można je przywrócić)?` : "Usunąć nagranie? Tej operacji nie można cofnąć.",
                 purge: "Usunąć TRWALE to nagranie? Tej operacji nie można cofnąć." }[action];
  if (text && !confirm(text)) return;
  try { await api("/api/recordings", { source: $("rv-src").value, id, action }); } catch (e) { alert(e.message); }
  if (rv.cur === id) $("rv-view").hidden = true; refreshRecs();
};
let editingRec = null;
window.editRec = (id) => { const r = rv.list.find((x) => x.id === id); editingRec = id; $("rv-title").value = r.title; $("rv-notes").value = r.notes; $("rv-tags").value = r.tags; $("rv-edit").hidden = false; $("rv-title").focus(); };
$("rv-cancel").addEventListener("click", () => { $("rv-edit").hidden = true; });
$("rv-save").addEventListener("click", async () => {
  try { await api("/api/recordings", { source: $("rv-src").value, id: editingRec, action: "update", fields: { title: $("rv-title").value, notes: $("rv-notes").value, tags: $("rv-tags").value } }); }
  catch (e) { alert(e.message); } refreshRecs();
});
window.loadRec = async (id, from, to) => {
  const r = rv.list.find((x) => x.id === id) || {}, qs = `source=${enc($("rv-src").value)}&id=${enc(id)}` + (from != null ? `&from=${from}&to=${to}` : "");
  $("rv-msg").textContent = "Wczytuję…";
  try { rv.data = await api(`/api/recordings/data?${qs}&points=${Math.min(6000, $("rv-canvas").width * 2)}`); } catch (e) { $("rv-msg").textContent = "Błąd: " + e.message; return; }
  $("rv-msg").textContent = ""; rv.cur = id; rv.from = from ?? null; rv.to = to ?? null;
  $("rv-view").hidden = false; $("rv-name").textContent = (r.title || rv.data.title || id) + " ";
  $("rv-info").textContent = ` ${rv.data.rows} wierszy` + (rv.data.shown < rv.data.rows ? `, na wykresie ${rv.data.shown} (min/maks)` : "") + (rv.data.mode === "changes" ? " · zapis zmian" : "");
  $("rv-csv").href = `/api/recordings/csv?${qs}`; $("rv-search-box")._rebuild?.(); await loadRecMarks(); drawRec(); $("rv-view").scrollIntoView({ behavior: "smooth" });
};
function recRange() { const d = rv.data, end = Math.max(d.t.length ? d.t.at(-1) : 0, d.end_us ? (d.end_us - d.start_us) / 1e6 : 0); return [rv.from ?? (d.t[0] ?? 0), rv.to ?? end]; }
function drawRec() {
  const d = rv.data, [t0, t1] = recRange(), at = (t) => new Date(d.start_us / 1000 + t * 1000).toLocaleString("pl-PL");
  drawChart($("rv-canvas"), d, t0, t1, { mk: MK.rec, hold: d.mode === "changes", left: at(t0), right: at(t1), empty: "Brak danych w tym zakresie.", legend: $("rv-legend") });
}
$("rv-all").addEventListener("click", () => { if (rv.cur) loadRec(rv.cur); });

// ---------------------------------------------------------------- markers on the two charts
const canMark = () => ROLE_RANK[me?.role] >= ROLE_RANK.operator;
MK.live = { cv: $("canvas"), kind: "live", marks: [], srv: [], pred: (m) => m.conn === $("c-conn").value, hi: new Set(), hiGroup: "", place: null, drag: null, ds: () => frozen || series, startUs: () => (frozen || series).start_us || 0,
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
  await loadMarks(MK.live, `conn=${encodeURIComponent(id)}&from=${Math.round(ds.start_us + t0 * 1e6)}&to=${Math.round(ds.start_us + t1 * 1e6)}&limit=500`);
  draw();
}
async function loadRecMarks() { if (rv.cur) await loadMarks(MK.rec, "rec=" + encodeURIComponent($("rv-src").value + "|" + rv.cur) + "&limit=1000"); else { MK.rec.srv = []; MK.rec.marks = mkdOverlay([], MK.rec.pred); } }
function showUserFrozen(d, x0, x1) {
  const colors = new Set(d.colors).size < d.colors.length ? d.colors.map((_, k) => COLORS[k % COLORS.length]) : d.colors;
  frozen = { ...d, colors, x0, x1, trig: null }; userFrozen = true; $("c-live").hidden = false; loadLiveMarks(); draw();
}
$("c-live").addEventListener("click", () => { userFrozen = false; frozen = null; frozenKey = null; $("c-live").hidden = true; loadLiveMarks(); draw(); });
$("c-addmark").addEventListener("click", () => { const ds = frozen || series; if (!ds.start_us || !canMark()) return alert(canMark() ? "Brak danych – uruchom połączenie." : "Rola „podgląd” nie zakłada znaczników.");
  mkAdd(MK.live, mkBlank(Math.round(ds.start_us + (ds.t.at(-1) ?? 0) * 1e6))); });
mkAttach(MK.live); mkAttach(MK.rec); initMarkersView();
mkSearchPanel($("c-search-box"), { names: () => series?.names || [], run: (b) => api("/api/search", { conn: $("c-conn").value, ...b }),
  pick: async (h) => { const pad = Math.max(h.duration * 0.3, 10), f = h.t0 - pad, t = h.t1 + pad, d = await api(`/api/connections/${$("c-conn").value}/series?from=${f}&to=${t}`);
    if (!d.t.length) return alert("Ten moment jest poza danymi, które połączenie trzyma w pamięci."); showUserFrozen(d, f, t); },
  mark: (h, sigs, ev) => mkAdd(MK.live, mkBlank(h.t0_us, { title: "Wynik wyszukiwania", signals: sigs, ...(!ev && h.t1_us > h.t0_us ? { kind: "range", end_us: h.t1_us } : {}) })) });
mkSearchPanel($("rv-search-box"), { names: () => rv.data?.names || [], run: (b) => api("/api/search", { source: $("rv-src").value, id: rv.cur, ...b }),
  pick: (h) => { const pad = Math.max(h.duration * 0.3, 20); loadRec(rv.cur, Math.max(0, h.t0 - pad), h.t1 + pad); },
  mark: (h, sigs, ev) => mkAdd(MK.rec, mkBlank(h.t0_us, { title: "Wynik wyszukiwania", signals: sigs, ...(!ev && h.t1_us > h.t0_us ? { kind: "range", end_us: h.t1_us } : {}) })) });
(() => {   // zoom: drag a range on the chart
  const cv = $("rv-canvas"); let x0 = null;
  const tAt = (ev) => { const b = cv.getBoundingClientRect(), px = (ev.clientX - b.left) / b.width * cv.width, [a, z] = recRange();
    return a + Math.min(Math.max((px - 60) / (cv.width - 70), 0), 1) * (z - a); };
  cv.addEventListener("mousedown", (e) => { if (rv.data) x0 = tAt(e); });
  window.addEventListener("mouseup", (e) => { if (x0 === null) return; const t = tAt(e), a = Math.min(x0, t), z = Math.max(x0, t); x0 = null; if (z - a > 0.05 && rv.cur) loadRec(rv.cur, a, z); });
})();

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
