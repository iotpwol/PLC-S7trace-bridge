"""HTTP server of the web mode (standard library only): login with cookie sessions, the overview of users / connections /
controllers, a live chart over Server-Sent Events and the administration of accounts.

    python -m s7trace.web --config <S7Trace config.json> [--host 0.0.0.0] [--port 8080] [--data <folder>] [--tls]
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import secrets
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .auth import KIND_LABEL, ROLE_LABEL, AuthError, UserStore, role_allows
from ..core import diagnostics as dg
from ..core import store as st
from ..core.config import TabConfig
from ..core.detect import read_device_s7
from .. import version
from ..core import help_texts, panel_cfg, sysinfo
from . import editing
from . import files
from . import sso
from .agents import Agents, host_of
from .hosted import HostManager
from .markers_api import MarkerService, search_connection
from .prefs import Prefs
from .recordings import Library, RecError
from .targets import TargetError, Targets

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SESSION_IDLE_S = 8 * 3600
COOKIE = "s7trace_session"
CSRF_HEADER = "X-S7Trace"                                  # every POST must carry it (a form from another site cannot)


class WebSessions:
    """The logged-in browsers: who, from which address, since when - shown to administrators and operators."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self._lock = threading.RLock()

    def create(self, user: dict, address: str, agent: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self.items[token] = {"username": user["username"], "role": user["role"], "kind": user["kind"], "address": address,
                                 "agent": agent[:120], "login": now, "seen": now, "viewing": ""}
        return token

    def get(self, token: str | None) -> dict | None:
        now = time.time()
        with self._lock:
            s = self.items.get(token or "")
            if s is None or now - s["seen"] > SESSION_IDLE_S:
                self.items.pop(token or "", None)
                return None
            s["seen"] = now
            return s

    def drop(self, token: str) -> None:
        with self._lock:
            self.items.pop(token, None)

    def drop_user(self, username: str) -> None:
        with self._lock:
            for k in [k for k, v in self.items.items() if v["username"].lower() == username.lower()]:
                del self.items[k]

    def listing(self, active_s: float = 90.0) -> list[dict]:
        now = time.time()
        with self._lock:
            return [{"id": k[:8], "username": v["username"], "role": ROLE_LABEL.get(v["role"], v["role"]),
                     "kind": KIND_LABEL.get(v["kind"], v["kind"]), "address": v["address"], "agent": v["agent"],
                     "login_s": now - v["login"], "idle_s": now - v["seen"], "viewing": v["viewing"],
                     "active": now - v["seen"] < active_s} for k, v in self.items.items()]


class App:
    """The state shared by all requests."""

    def __init__(self, data_dir: str, hosts: HostManager | None = None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.users = UserStore(os.path.join(data_dir, "web_users.db"))
        self.sessions = WebSessions()
        self.targets = Targets(os.path.join(data_dir, "web_targets.json"))
        self.hosts = hosts or HostManager(os.path.join(data_dir, "workspaces"))
        h = self.hosts                                              # where the connections write files / find the targets
        h.files_root, h.data_dir = h.files_root or os.path.join(data_dir, "files"), h.data_dir or data_dir
        h.targets = h.targets or self.targets
        self.library = Library(h.files_root, h.data_dir, h.targets)
        self.markers = MarkerService(os.path.join(data_dir, "web_markers.db"), h)      # bookmarks on charts (per author)
        self.prefs = Prefs(os.path.join(data_dir, "prefs"))        # interface settings per account (look of the marker lines)
        self.agents = Agents()                                      # desktop programs that report to the server
        self.sso = False                                            # single sign-on with the Windows account (--sso)
        self.started = time.time()
        self.detect_busy: set[str] = set()                          # sessions with a wizard run in progress

    def server_scans(self) -> list[dict]:
        """PLCs scanned by the connections hosted on this server right now."""
        return [{"ip": host_of(h.cfg.ip), "user": h.started_by or h.owner, "computer": "serwer Web", "title": h.name,
                 "since": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(h.started_us / 1e6)) if h.started_us else None,
                 "kind": "server", "agent": h.id} for h in self.hosts.all() if h.state in ("connecting", "running", "reconnecting")]


class Handler(BaseHTTPRequestHandler):
    server_version = "S7TraceWeb"
    _neg = None                                                # the SSPI exchange of this connection (NTLM needs the same connection)
    protocol_version = "HTTP/1.1"
    app: App

    def log_message(self, fmt, *args):                         # quiet (the overview page is the log of who is there)
        pass

    # ---- helpers
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200, headers: dict | None = None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), headers=headers)

    def _error(self, code: int, message: str):
        self._json({"error": message}, code)

    def _token(self) -> str | None:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def _session(self, need: str = "viewer") -> dict | None:
        s = self.app.sessions.get(self._token())
        if s is None:
            self._error(401, "Zaloguj się.")
            return None
        if not role_allows(s["role"], need):
            self._error(403, "Brak uprawnień do tej operacji.")
            return None
        return s

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100_000:
            raise AuthError("Za duże żądanie.")
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise AuthError("Niepoprawne dane (JSON).") from None
        return d if isinstance(d, dict) else {}

    # ---- GET
    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/me":
                s = self.app.sessions.get(self._token())
                return self._json({"user": s["username"], "role": s["role"], "kind": s["kind"]} if s else {"user": None,
                                  "first_run": self.app.users.count() == 0, "sso": self.app.sso})
            if path == "/api/help":
                return self._json({"help": help_texts.HELP})
            if path == "/api/sysinfo":                                    # the 'System' tab under the chart: the server computer
                if self._session("viewer") is not None:
                    now = datetime.now()
                    cpu = sysinfo.cpu_percent()
                    app = sysinfo.app_cpu_percent()                         # this server (+ its acquisition processes)
                    self._json({"time": now.strftime("%Y-%m-%d  %H:%M:%S"), "os": sysinfo.os_name(), "cpu": None if cpu is None else round(cpu, 1),
                                "app_cpu": None if app is None else round(app, 1)})
                return
            if path == "/api/version":
                return self._json({"author": version.AUTHOR, "version": version.VERSION, "date": version.DATE})
            if path == "/api/sso":
                return self._sso()
            if path == "/api/overview":
                return self._overview()
            if path == "/api/options":                                   # lists for the editor of a new connection
                if self._session("viewer") is not None:
                    self._json({"options": editing.view(TabConfig(), None, self.app.targets.names())["options"]})
                return
            if path.startswith("/api/recordings"):
                return self._recordings_get(path, q)
            if path == "/api/prefs":
                s = self._session("viewer")
                if s is not None:
                    self._json({"prefs": self.app.prefs.get(s["username"])})
                return
            if path == "/api/markers":
                s = self._session("viewer")
                if s is not None:
                    self._json(self.app.markers.listing(s["username"], s["role"], q))
                return
            if path == "/api/targets":                                   # recording targets: names for users, details for admins
                s = self._session("viewer")
                if s is not None:
                    self._json({"targets": self.app.targets.listing(s["role"] == "admin")})
                return
            if path == "/api/users":
                return self._users_list()
            if path == "/api/agent-tokens":
                if self._session("admin") is not None:
                    self._json({"tokens": self.app.users.list_agent_tokens()})
                return
            if path.startswith("/api/connections/"):
                return self._connection_get(path.split("/")[3:], q)
            self._error(404, "Nie ma takiej strony.")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as e:                                   # RecError, a bad number in the query ...
            self._error(400, str(e))

    def _static(self, name: str):
        full = os.path.normpath(os.path.join(STATIC, name))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._error(404, "Nie ma takiego pliku.")
        with open(full, "rb") as f:
            self._send(200, f.read(), (mimetypes.guess_type(full)[0] or "application/octet-stream") + "; charset=utf-8")

    def _overview(self):
        s = self._session("viewer")
        if s is None:
            return
        hosts = [h.describe(s["username"], s["role"]) for h in self.app.hosts.visible(s["username"], s["role"])]
        viewers: dict[str, list[str]] = {}
        for w in self.app.sessions.listing():
            if w["viewing"]:
                viewers.setdefault(w["viewing"], []).append(w["username"])
        for h in hosts:
            h["viewers"] = sorted(set(viewers.get(h["id"], [])))
        agents = self.app.agents.listing()
        scans = self.app.agents.scans()
        for h, c in zip(hosts, self.app.hosts.visible(s["username"], s["role"])):
            host = host_of(c.cfg.ip)                                  # the same PLC scanned by a desktop program elsewhere
            h["others"] = [f"{x['user']} ({x['computer']})" for x in scans if x["ip"] == host]
        self._json({"now": time.time(), "uptime_s": time.time() - self.app.started, "connections": hosts,
                    "sessions": self.app.sessions.listing(), "me": {"user": s["username"], "role": s["role"]},
                    "agents": [{k: v for k, v in a.items() if k not in ("token", "seen")} for a in agents if a["live"]]})

    def _users_list(self):
        if self._session("admin") is None:
            return
        self._json({"users": [{**u, "role_label": ROLE_LABEL[u["role"]], "kind_label": KIND_LABEL[u["kind"]]}
                              for u in self.app.users.list()]})

    def _connection_get(self, parts: list[str], q: dict):
        s = self._session("viewer")
        if s is None:
            return
        host = self.app.hosts.get(parts[0]) if parts else None
        if host is None or not host.can_view(s["username"], s["role"]):
            return self._error(404, "Nie ma takiego połączenia.")
        what = parts[1] if len(parts) > 1 else ""
        if what == "config":
            if not host.can_edit(s["username"], s["role"]):
                return self._error(403, "Brak uprawnień do edycji tego połączenia.")
            return self._json(self._config_payload(host))
        if what == "series":
            span = (float(q["from"]), float(q["to"])) if "from" in q and "to" in q else None
            return self._json(host.series(float(q.get("seconds", 60)), since=float(q["since"]) if "since" in q else None,
                                          span=span))
        if what == "diag":
            return self._diag(host, s, q)
        if what == "files":
            return self._files(host, parts[2:])
        if what == "stream":
            return self._stream(host, s, float(q.get("seconds", 60)))
        self._json(host.describe(s["username"], s["role"]))

    def _diag(self, host, session, q: dict):
        """Diagnostics of a connection: link quality, the controller, who else scans the same PLC, (admin) leftover disk buffers of
        recordings and, on request (?ping=1), one ICMP ping of the controller."""
        d = host.diag()
        addr = host_of(host.cfg.ip)
        others = [f"{x['user']} ({x['computer']})" for x in self.app.agents.scans() if x["ip"] == addr]
        others += [f"{x['user']} ({x['computer']}: {x['title']})" for x in self.app.server_scans() if x["ip"] == addr and x["agent"] != host.id]
        d["others"] = others
        if q.get("ping"):
            rtt = dg.system_ping(addr)
            d["ping_ms"] = None if rtt is None else round(rtt, 1)
        d["spools"] = []
        if session["role"] == "admin" and self.app.hosts.data_dir:
            d["spools"] = [{"name": x["name"], "target": x["target"], "rows": x["rows"], "size": x["size"],
                            "title": (x["meta"] or {}).get("title", "") if isinstance(x["meta"], dict) else ""}
                           for x in st.scan_spools(self.app.hosts.data_dir)]
        self._json(d)

    def _stream(self, host, session, seconds: float):
        """Server-Sent Events: the last `seconds` at once, then the new samples about ten times per second."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        session["viewing"] = host.id
        try:
            data = host.series(seconds)
            last = data["last"] if data["t"] else None
            first = True
            ver = -1
            while not getattr(self.server, "stopping", False):
                if first:
                    payload, first = {"reset": True, **data}, False
                else:
                    payload = {"reset": False, **host.series(seconds, since=last)}
                if payload["t"]:
                    last = payload["t"][-1]
                payload["description"] = host.describe() if host.version != ver else None
                ver = host.version
                self.wfile.write(b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n")
                self.wfile.flush()
                self.app.sessions.get(self._token())                # keeps the login alive while the chart is open
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            if session.get("viewing") == host.id:
                session["viewing"] = ""

    # ---- POST
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if self.headers.get(CSRF_HEADER) != "1":
                return self._error(403, "Brak nagłówka zabezpieczającego.")
            d = self._body()
            if path == "/api/agent/report":                           # a desktop program (token instead of a login)
                return self._agent_report(d)
            if path == "/api/login":
                return self._login(d)
            if path == "/api/logout":
                self.app.sessions.drop(self._token() or "")
                return self._json({"ok": True}, headers={"Set-Cookie": f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict"})
            if path == "/api/setup":                                  # the first administrator, only while there are no accounts
                if self.app.users.count():
                    return self._error(403, "Konta już istnieją.")
                self.app.users.add(str(d.get("username", "")), "admin", "local", str(d.get("password", "")))
                return self._login(d)
            if path == "/api/connections":
                return self._connection_create(d)
            if path.startswith("/api/connections/"):
                return self._connection_post(path.split("/")[3:], d)
            if path == "/api/users":
                return self._users_post(d)
            if path == "/api/targets":
                return self._targets_post(d)
            if path == "/api/agent-tokens":
                return self._agent_tokens_post(d)
            if path == "/api/detect":
                return self._detect(d)
            if path == "/api/recordings":
                return self._recordings_post(d)
            if path == "/api/prefs":
                s = self._session("viewer")
                if s is not None:
                    self._json({"prefs": self.app.prefs.update(s["username"], d)})
                return
            if path == "/api/markers":
                return self._markers_post(d)
            if path == "/api/search":
                return self._search(d)
            self._error(404, "Nie ma takiej operacji.")
        except (AuthError, TargetError) as e:
            self._error(400, str(e))
        except ValueError as e:
            self._error(400, str(e))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _login(self, d: dict):
        address = self.client_address[0]
        user = self.app.users.authenticate(str(d.get("username", "")), str(d.get("password", "")), address)
        token = self.app.sessions.create(user, address, self.headers.get("User-Agent") or "")
        secure = "; Secure" if getattr(self.server, "tls", False) else ""
        self._json({"user": user["username"], "role": user["role"]},
                   headers={"Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict{secure}"})

    def _connection_create(self, d: dict):
        s = self._session("operator")
        if s is None:
            return
        cfg = TabConfig()
        patch = {k: v for k, v in d.items() if k in ("name", "ip", "rack", "slot", "cycle_ms", "conn_type", "conn", "mode",
                                                   "window_s", "signals", "trigger", "rec", "y_layout", "auto_y", "y_min", "y_max",
                                                   "show_points", "legend_mode", "time_axis", "time_offset")}
        try:
            web = {}
            editing.apply(cfg, patch, running=False, web=web, targets=self.app.targets.names())
            host = self.app.hosts.add(cfg, s["username"], web)
        except editing.EditError as e:
            return self._error(400, str(e))
        self._json(host.describe(s["username"], s["role"]))

    @staticmethod
    def _device_rows(host) -> list:
        """[row name, value] of the controller box (the same rows and names as the program's 'Sterownik' box)."""
        info = (host.device or {}).get("info") or {}
        if not info or (host.device or {}).get("method") == "other":
            return []
        return [[k, str(info.get(key) or "—")] for k, key in panel_cfg.DEVICE_KEYS]

    def _config_payload(self, host) -> dict:
        return {**editing.view(host.cfg, host.web, self.app.targets.names()), "state": host.state,
                "recording": host.recorder is not None,
                "device": st.device_lines(st.device_summary(host.device, host.cfg.ip)),
                "device_rows": self._device_rows(host),
                "plc_error": (host.device or {}).get("time_error", ""),
                "plc_diff": (host.device or {}).get("time_diff_local"),      # PLC clock - server clock [s], read at the connection
                "server_now": time.time(), "server_tz": time.localtime().tm_gmtoff}

    def _connection_post(self, parts: list[str], d: dict):
        s = self._session("operator")
        if s is None:
            return
        user, role = s["username"], s["role"]
        host = self.app.hosts.get(parts[0]) if parts else None
        if host is None or not host.can_view(user, role):
            return self._error(404, "Nie ma takiego połączenia.")
        action = parts[1] if len(parts) > 1 else ""
        if action in ("start", "stop"):
            if not host.can_run(user, role):
                return self._error(403, "Brak uprawnień do tego połączenia.")
            host.start(user) if action == "start" else host.stop()
        elif action in ("config", "delete"):
            if not host.can_edit(user, role):
                return self._error(403, "Brak uprawnień do edycji tego połączenia.")
            try:
                if action == "delete":
                    self.app.hosts.remove(host.id)
                    return self._json({"ok": True})
                changed = editing.apply(host.cfg, d, running=host.state != "stopped", web=host.web,
                                        recording=host.recorder is not None, targets=self.app.targets.names())
            except editing.EditError as e:
                return self._error(400, str(e))
            self.app.hosts.save(host.owner)
            if "trigger" in changed:
                host.reload_trigger()
            host.version += 1
        elif action == "read-device":                  # 'Pobierz dane sterownika': only the controller data + its clock, no acquisition
            if not host.can_run(user, role):
                return self._error(403, "Brak uprawnień do tego połączenia.")
            if host.state != "stopped":
                return self._error(400, "Połączenie pracuje – dane sterownika odświeżają się przy każdym połączeniu.")
            if host.cfg.conn_type not in ("auto", "s7"):
                return self._error(400, "Dane sterownika można pobrać tylko dla połączenia S7comm.")
            try:
                dev = read_device_s7(host.cfg.ip, host.cfg.rack, host.cfg.slot)
            except Exception as e:
                return self._error(502, f"Nie udało się pobrać danych sterownika: {e}")
            note = ""
            if (dev.get("rack"), dev.get("slot")) != (host.cfg.rack, host.cfg.slot):        # another pair worked: it becomes the setting
                note = f"Sterownik odpowiedział na rack/slot {dev['rack']}/{dev['slot']} (było {host.cfg.rack}/{host.cfg.slot}) – ustawiono nowe wartości."
                host.cfg.rack, host.cfg.slot = int(dev["rack"]), int(dev["slot"])
                self.app.hosts.save(host.owner)
                host.version += 1
            host._on_info(dev)
            return self._json({**self._config_payload(host), "note": note})
        elif action == "trigger":
            if not host.can_run(user, role):
                return self._error(403, "Brak uprawnień do tego połączenia.")
            if d.get("action") != "rearm":
                return self._error(400, "Nieznana operacja wyzwalacza.")
            host.rearm()
        elif action == "rec":
            if not host.can_run(user, role):
                return self._error(403, "Brak uprawnień do tego połączenia.")
            what = d.get("action")
            if what == "start":
                host.rec_start(user, d, self.client_address[0])
            elif what == "stop":
                host.rec_stop()
            elif what == "info":
                host.rec_info_update(d)
            else:
                return self._error(400, "Nieznana operacja REC.")
        elif action == "files":
            if not host.can_edit(user, role):
                return self._error(403, "Brak uprawnień do plików tego połączenia.")
            path = files.resolve(self.app.hosts.files_root, host.owner, str(d.get("kind", "")), str(d.get("name", "")))
            if path is None:
                return self._error(404, "Nie ma takiego pliku.")
            os.remove(path)
            return self._json({"ok": True})
        else:
            return self._error(404, "Nie ma takiej operacji.")
        self._json(host.describe(user, role))

    def _files(self, host, rest: list[str]):
        """The CSV files (trigger snapshots and recordings) of the account that owns the connection."""
        root = self.app.hosts.files_root
        rest = [unquote(x) for x in rest]
        if not rest:
            return self._json({"files": files.listing(root, host.owner)})
        path = files.resolve(root, host.owner, rest[0], rest[1] if len(rest) > 1 else "")
        if path is None:
            return self._error(404, "Nie ma takiego pliku.")
        with open(path, "rb") as f:
            body = f.read()
        name = os.path.basename(path).replace('"', "_")
        self._send(200, body, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="{name}"'})

    # ---- recordings stored in databases ("Przegląd nagrań" in the browser)
    def _recordings_get(self, path: str, q: dict):
        s = self._session("viewer")
        if s is None:
            return
        user, role, lib = s["username"], s["role"], self.app.library
        if path == "/api/recordings/sources":
            return self._json({"sources": [{"id": x.id, "label": x.label, "kind": x.kind} for x in lib.sources(user, role)]})
        src = lib.resolve(q.get("source", "sqlite"), user, role)
        num = lambda k: float(q[k]) if k in q and q[k] != "" else None
        if path == "/api/recordings":
            return self._json({"recordings": lib.listing(src, user, role, q.get("trash") == "1"),
                               "trash_days": src.cfg.trash_days})
        if path == "/api/recordings/data":
            return self._json(lib.read(src, q.get("id", ""), user, role, num("from"), num("to"),
                                       min(int(q.get("points", 6000)), 20000)))
        if path == "/api/recordings/csv":
            name, data = lib.csv_bytes(src, q.get("id", ""), user, role, num("from"), num("to"))
            return self._send(200, data, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="{name}"'})
        self._error(404, "Nie ma takiej strony.")

    def _markers_post(self, d: dict):
        s = self._session("operator")
        if s is None:
            return
        try:
            self._json(self.app.markers.change(s["username"], s["role"], d, self.client_address[0]))
        except KeyError:
            self._error(404, "Nie ma takiego znacznika.")

    def _search(self, d: dict):
        """Value search in the memory of a connection ({conn}) or in a recording of a database ({source, id})."""
        s = self._session("viewer")
        if s is None:
            return
        user, role = s["username"], s["role"]
        if d.get("conn"):
            host = self.app.hosts.get(str(d["conn"]))
            if host is None or not host.can_view(user, role):
                return self._error(404, "Nie ma takiego połączenia.")
            return self._json(search_connection(host, d))
        lib = self.app.library
        src = lib.resolve(str(d.get("source", "sqlite")), user, role)
        self._json(lib.search(src, str(d.get("id", "")), user, role, d))

    def _recordings_post(self, d: dict):
        s = self._session("operator")
        if s is None:
            return
        lib = self.app.library
        src = lib.resolve(str(d.get("source", "sqlite")), s["username"], s["role"])
        lib.change(src, str(d.get("id", "")), s["username"], s["role"], str(d.get("action", "")), d.get("fields"))
        self._json({"ok": True})

    def finish(self):
        if self._neg is not None:
            try:
                self._neg.close()
            except Exception:
                pass
            self._neg = None
        super().finish()

    def _sso(self):
        """Negotiate (Kerberos / NTLM) with the Windows account of the browser user; the account must be registered."""
        if not self.app.sso:
            return self._error(404, "Logowanie kontem Windows (SSO) jest wyłączone na tym serwerze.")
        if self.headers.get(CSRF_HEADER) != "1":
            return self._error(403, "Brak nagłówka zabezpieczającego.")
        auth = self.headers.get("Authorization") or ""
        if not auth.lower().startswith("negotiate "):
            if self._neg is not None:
                self._neg.close()
                self._neg = None
            return self._send(401, json.dumps({"error": "Przeglądarka nie przesłała konta Windows."}).encode(),
                              headers={"WWW-Authenticate": "Negotiate"})
        try:
            token = base64.b64decode(auth[10:].strip(), validate=True)
        except ValueError:
            return self._error(400, "Niepoprawny token.")
        if self._neg is None:
            self._neg = sso.Negotiate()
        status, out, name = self._neg.step(token)
        back = {"WWW-Authenticate": "Negotiate " + sso.b64(out)} if out else {}
        if status == "continue":
            return self._send(401, json.dumps({"error": "Negocjacja…"}).encode(), headers=back or {"WWW-Authenticate": "Negotiate"})
        self._neg.close()
        self._neg = None
        if status != "ok" or not name:
            return self._send(403, json.dumps({"error": "Uwierzytelnienie kontem Windows nie powiodło się."}).encode(), headers=back)

        def lookup(n):
            u = self.app.users.get(n)
            return u if u and u["kind"] == "windows" and not u["disabled"] else None
        acc = sso.match_account(name, lookup)
        if acc is None:
            return self._send(403, json.dumps({"error": f"Konto Windows {name} nie jest zarejestrowane w S7Trace Web – "
                                                        "poproś administratora o dodanie go (rodzaj: konto Windows / AD)."},
                                              ensure_ascii=False).encode(), headers=back)
        self.app.users.mark_login(acc["username"])
        token = self.app.sessions.create(acc, self.client_address[0], self.headers.get("User-Agent") or "")
        secure = "; Secure" if getattr(self.server, "tls", False) else ""
        self._json({"user": acc["username"], "role": acc["role"]},
                   headers={**back, "Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict{secure}"})

    def _agent_report(self, d: dict):
        name = self.app.users.check_agent_token(self.headers.get("X-S7Trace-Agent") or "")
        if name is None:
            return self._error(401, "Nieprawidłowy token programu.")
        self.app.agents.report(d, self.client_address[0], name)
        aid = str(d.get("id", ""))[:64]
        self._json({"scans": self.app.agents.scans(exclude=aid) + self.app.server_scans(), "server_time": time.time()})

    def _agent_tokens_post(self, d: dict):
        if self._session("admin") is None:
            return
        act, name = d.get("action"), str(d.get("name", ""))
        if act == "add":
            return self._json({"ok": True, "token": self.app.users.add_agent_token(name)})      # shown once, never stored in clear
        if act == "delete":
            self.app.users.delete_agent_token(name)
            return self._json({"ok": True})
        raise AuthError("Nieznana operacja.")

    def _detect(self, d: dict):
        """The connection wizard: probes the address (S7 / OPC UA / Web API / Modbus) from the server and recommends a method."""
        s = self._session("operator")
        if s is None:
            return
        from ..core import detect
        from ..core.config import conn_defaults
        ip = str(d.get("ip", "")).strip()
        if not editing._HOST.fullmatch(ip):
            raise AuthError("Adres IP: dozwolone cyfry, litery, kropki i dwukropek (port).")
        rack, slot = editing._num(d, "rack", 0, 7, "Rack"), editing._num(d, "slot", 0, 31, "Slot")
        kind = d.get("conn_type", "auto")
        if kind not in editing.CONN_KINDS:
            raise AuthError("Nieznany sposób połączenia.")
        opts = {k: v for k, v in (d.get("conn") or {}).items() if k in conn_defaults() and k not in ("cert", "key")}
        key = s["username"].lower()
        if key in self.app.detect_busy:
            raise AuthError("Poprzednie rozpoznawanie jeszcze trwa.")
        self.app.detect_busy.add(key)
        try:
            res = detect.run_detection(ip, opts, rack, slot, None if kind == "auto" else [kind], bool(d.get("first")))
        finally:
            self.app.detect_busy.discard(key)
        self._json({"steps": [{"key": x.key, "title": x.title, "status": x.status, "detail": x.detail, "ms": round(x.ms, 1)} for x in res.steps],
                    "methods": res.methods, "recommended": res.recommended, "advice": res.advice,
                    "info": {k: v for k, v in res.info.items() if isinstance(v, (str, int, float))}, "rack": res.rack, "slot": res.slot,
                    "report": detect.format_result(res)})

    def _targets_post(self, d: dict):
        if self._session("admin") is None:
            return
        act, name = d.get("action"), str(d.get("name", ""))
        if act in ("add", "update"):
            self.app.targets.put(name, d.get("fields") or {})
        elif act == "delete":
            self.app.targets.delete(name)
        elif act == "test":
            from ..core.store import test_connection
            c = self.app.targets.get(name)
            if c is None:
                return self._error(404, "Nie ma takiego celu.")
            base = os.path.join(self.app.data_dir, "dbs") if c.kind == "sqlite" else self.app.data_dir
            try:
                return self._json({"ok": True, "message": test_connection(c, base, c.test_timeout_s)})
            except Exception as e:
                return self._json({"ok": False, "message": str(e) or type(e).__name__})
        else:
            raise AuthError("Nieznana operacja.")
        self._json({"ok": True})

    def _users_post(self, d: dict):
        if self._session("admin") is None:
            return
        act, name = d.get("action"), str(d.get("username", ""))
        users = self.app.users
        if act == "add":
            users.add(name, str(d.get("role", "viewer")), str(d.get("kind", "local")), str(d.get("password", "")),
                      str(d.get("display", "")))
        elif act == "role":
            users.set_role(name, str(d.get("role", "")))
        elif act == "disable":
            users.set_disabled(name, bool(d.get("disabled", True)))
            if d.get("disabled", True):
                self.app.sessions.drop_user(name)
        elif act == "password":
            users.set_password(name, str(d.get("password", "")))
            self.app.sessions.drop_user(name)
        elif act == "delete":
            users.delete(name)
            self.app.sessions.drop_user(name)
        else:
            raise AuthError("Nieznana operacja.")
        self._json({"ok": True})


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, app: App, host: str = "127.0.0.1", port: int = 8080, tls: tuple[str, str] | None = None):
        handler = type("BoundHandler", (Handler,), {"app": app})
        super().__init__((host, port), handler)
        self.app, self.stopping, self.tls = app, False, bool(tls)
        if tls:
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*tls)
            self.socket = ctx.wrap_socket(self.socket, server_side=True)

    def handle_error(self, request, client_address):
        """A browser that closes the page / a TLS probe is no news (the default prints a traceback to the console)."""
        import sys
        if not isinstance(sys.exc_info()[1], (ConnectionError, OSError, TimeoutError)):
            super().handle_error(request, client_address)

    @property
    def url(self) -> str:
        return f"{'https' if self.tls else 'http'}://{self.server_address[0]}:{self.server_address[1]}"

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.serve_forever, name="s7trace-web", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self.stopping = True
        self.shutdown()
        self.server_close()
        self.app.hosts.shutdown()
        self.app.users.close()
