"""HTTP server of the web mode (standard library only): login with cookie sessions, the overview of users / connections /
controllers, a live chart over Server-Sent Events and the administration of accounts.

    python -m s7trace.web --config <S7Trace config.json> [--host 0.0.0.0] [--port 8080] [--data <folder>] [--tls]
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .auth import KIND_LABEL, ROLE_LABEL, AuthError, UserStore, role_allows
from .hosted import HostManager

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
        self.hosts = hosts or HostManager()
        self.started = time.time()


class Handler(BaseHTTPRequestHandler):
    server_version = "S7TraceWeb"
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
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/me":
                s = self.app.sessions.get(self._token())
                return self._json({"user": s["username"], "role": s["role"], "kind": s["kind"]} if s else {"user": None,
                                  "first_run": self.app.users.count() == 0})
            if path == "/api/overview":
                return self._overview()
            if path == "/api/users":
                return self._users_list()
            if path.startswith("/api/connections/"):
                return self._connection_get(path.split("/")[3:], q)
            self._error(404, "Nie ma takiej strony.")
        except (BrokenPipeError, ConnectionResetError):
            pass

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
        hosts = [h.describe() for h in self.app.hosts.all()]
        viewers: dict[str, list[str]] = {}
        for w in self.app.sessions.listing():
            if w["viewing"]:
                viewers.setdefault(w["viewing"], []).append(w["username"])
        for h in hosts:
            h["viewers"] = sorted(set(viewers.get(h["id"], [])))
        self._json({"now": time.time(), "uptime_s": time.time() - self.app.started, "connections": hosts,
                    "sessions": self.app.sessions.listing(), "me": {"user": s["username"], "role": s["role"]}})

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
        if host is None:
            return self._error(404, "Nie ma takiego połączenia.")
        what = parts[1] if len(parts) > 1 else ""
        if what == "series":
            return self._json(host.series(float(q.get("seconds", 60)), since=float(q["since"]) if "since" in q else None))
        if what == "stream":
            return self._stream(host, s, float(q.get("seconds", 60)))
        self._json(host.describe())

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
            if path.startswith("/api/connections/"):
                return self._connection_post(path.split("/")[3:])
            if path == "/api/users":
                return self._users_post(d)
            self._error(404, "Nie ma takiej operacji.")
        except AuthError as e:
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

    def _connection_post(self, parts: list[str]):
        s = self._session("operator")
        if s is None:
            return
        host = self.app.hosts.get(parts[0]) if parts else None
        if host is None:
            return self._error(404, "Nie ma takiego połączenia.")
        action = parts[1] if len(parts) > 1 else ""
        if action == "start":
            host.start(s["username"])
        elif action == "stop":
            host.stop()
        else:
            return self._error(404, "Nie ma takiej operacji.")
        self._json(host.describe())

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
