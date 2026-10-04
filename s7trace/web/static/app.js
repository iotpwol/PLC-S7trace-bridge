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
  for (const id of ["login", "overview", "chart", "users"]) $(id).hidden = id !== name;
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
$("logout").addEventListener("click", async () => { await api("/api/logout", {}); me = null; showLogin(); });

// ---------------------------------------------------------------- navigation
document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
function go(v) {
  view = v; show(v); stopStream();
  if (v === "overview") refreshOverview();
  if (v === "chart") openChart();
  if (v === "users") refreshUsers();
}
async function start() {
  me = await api("/api/me");
  if (!me.user) return showLogin();
  $("who").textContent = `${me.user} (${me.role})`; $("logout").hidden = false; $("nav").hidden = false;
  $("nav-users").hidden = me.role !== "admin";
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
    if (canRun) btn.push(c.state === "stopped" ? `<button onclick="act('${c.id}','start')">Start</button>` : `<button onclick="act('${c.id}','stop')">Stop</button>`);
    return `<tr><td><b>${esc(c.name)}</b></td><td>${esc(c.ip)}</td><td>${c.rack} / ${c.slot}</td>
      <td><span class="dot ${esc(c.state)}"></span>${esc(STATE_PL[c.state] || c.state)}<div class="muted">${esc(c.message)}</div></td>
      <td>${esc([d.family, d.model, d.firmware].filter(Boolean).join(" · ") || "–")}</td><td>${esc(d.plc_name || "–")}</td>
      <td>${esc(d.module_name || "–")}</td><td>${esc(c.method)}</td><td>${esc(c.started_by || "–")}<div class="muted">${c.started_us ? fmtTime(c.started_us) : ""}</div></td>
      <td>${esc((c.viewers || []).join(", ") || "–")}</td><td>${btn.join(" ")}</td></tr>`;
  }).join("") || '<tr><td colspan="11" class="muted">Brak połączeń na serwerze.</td></tr>';
  const byId = Object.fromEntries(overview.connections.map((c) => [c.id, c.name]));
  $("t-sess").tBodies[0].innerHTML = overview.sessions.map((s) => `<tr><td><b>${esc(s.username)}</b></td><td>${esc(s.kind)}</td><td>${esc(s.role)}</td>
    <td>${esc(s.address)}</td><td class="muted">${esc(s.agent)}</td><td>${fmtAge(s.login_s)} temu</td>
    <td>${s.active ? '<span class="dot running"></span>aktywny' : "bezczynny " + fmtAge(s.idle_s)}</td><td>${esc(byId[s.viewing] || "–")}</td></tr>`).join("");
}
window.act = async (id, what) => { try { await api(`/api/connections/${id}/${what}`, {}); } catch (e) { alert(e.message); } refreshOverview(); };

// ---------------------------------------------------------------- live chart
const COLORS = ["#ffb347", "#4eb8f0", "#7bd88f", "#ff7b7b", "#c792ea", "#f1fa8c", "#8be9fd", "#ffa7d1"];
function stopStream() { if (stream) { stream.close(); stream = null; } }
window.openChart = async (id) => {
  if (view !== "chart") { view = "chart"; show("chart"); }
  stopStream();
  const o = overview || await api("/api/overview"); overview = o;
  $("c-conn").innerHTML = o.connections.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.ip)})</option>`).join("");
  if (id) $("c-conn").value = id;
  connectStream();
};
function openChart() { window.openChart(); }
function connectStream() {
  stopStream();
  const id = $("c-conn").value; if (!id) return;
  series = { t: [], values: [], names: [], colors: [] };
  const sec = +$("c-sec").value;
  stream = new EventSource(`/api/connections/${id}/stream?seconds=${sec}`);
  stream.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.reset) { series = { t: d.t, values: d.values, names: d.names, colors: d.colors }; }   // (identical colours: palette below)
    else { series.t.push(...d.t); d.values.forEach((col, k) => (series.values[k] ||= []).push(...col)); }
    if (d.names?.length) { series.names = d.names; series.colors = new Set(d.colors).size < d.colors.length ? d.colors.map((_, k) => COLORS[k % COLORS.length]) : d.colors; }
    if (d.description) $("c-state").textContent = `${STATE_PL[d.description.state] || d.description.state} – ${d.description.message || ""}`;
    const cut = (series.t.at(-1) ?? 0) - sec;
    while (series.t.length && series.t[0] < cut) { series.t.shift(); series.values.forEach((c) => c.shift()); }
    draw();
  };
}
$("c-conn").addEventListener("change", connectStream); $("c-sec").addEventListener("change", connectStream);
let drawPending = false;
function draw() { if (drawPending) return; drawPending = true; requestAnimationFrame(() => { drawPending = false; paint(); }); }
function paint() {
  const cv = $("canvas"), g = cv.getContext("2d"), W = cv.width, H = cv.height, pad = { l: 60, r: 10, t: 8, b: 24 };
  g.fillStyle = "#000"; g.fillRect(0, 0, W, H); g.font = "12px sans-serif"; g.strokeStyle = "#333"; g.fillStyle = "#aaa";
  const n = series.names.length; if (!n || !series.t.length) { g.fillText("Brak danych – uruchom połączenie (Start) na stronie Przegląd.", 70, 30); return; }
  const t1 = series.t.at(-1), t0 = t1 - +$("c-sec").value, bandH = (H - pad.t - pad.b) / n, X = (t) => pad.l + (t - t0) / (t1 - t0) * (W - pad.l - pad.r);
  for (let k = 0; k < n; k++) {
    const col = series.values[k] || [], top = pad.t + k * bandH, bot = top + bandH - 4, c = series.colors[k] || COLORS[k % COLORS.length];
    const fin = col.filter((x) => x !== null), lo = Math.min(...fin), hi = Math.max(...fin), span = hi - lo || 1;
    g.strokeStyle = "#333"; g.strokeRect(pad.l, top, W - pad.l - pad.r, bandH - 4);
    g.fillStyle = "#aaa"; g.fillText(Number.isFinite(hi) ? hi.toPrecision(4) : "", 4, top + 12); g.fillText(Number.isFinite(lo) ? lo.toPrecision(4) : "", 4, bot);
    g.fillStyle = c; g.fillText(series.names[k], pad.l + 6, top + 14);
    g.strokeStyle = c; g.lineWidth = 1.2; g.beginPath(); let pen = false, py = 0;
    for (let i = 0; i < series.t.length; i++) {
      const v = col[i]; if (v === null || v === undefined) { pen = false; continue; }
      const x = X(series.t[i]), y = bot - (v - lo) / span * (bot - top - 6) - 3;
      if (!pen) { g.moveTo(x, y); pen = true; } else { g.lineTo(x, py); g.lineTo(x, y); }   // steps: the value holds until the next change
      py = y;
    }
    g.stroke();
  }
  g.fillStyle = "#aaa"; g.fillText(`-${$("c-sec").value} s`, pad.l, H - 6); g.fillText("teraz", W - pad.r - 34, H - 6);
  $("c-legend").innerHTML = series.names.map((nm, k) => `<span><i style="background:${series.colors[k] || COLORS[k % COLORS.length]}"></i>${esc(nm)}</span>`).join("");
}

// ---------------------------------------------------------------- accounts
async function refreshUsers() {
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
