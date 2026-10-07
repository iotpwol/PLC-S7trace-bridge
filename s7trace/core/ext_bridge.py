"""Bridge to an external analyzer (S7SignalAnalyzer, separate project): S7Trace is the TCP server on 127.0.0.1, the
analyzer connects as a client, authenticates with a token and then receives the samples of ONE tab (the source tab).
Qt-free, OFF by default, nothing here touches acquisition: the GUI thread only appends to a deque (`Feed.sample`), a sender
thread batches ~10x per second. Without a connected analyzer samples are dropped at once.

Wire format = newline-delimited JSON, one object per line (the same as in the analyzer's docs/ARCHITECTURE.md, proto 1;
the few helpers below are copied on purpose, S7Trace must not import the analyzer):

  analyzer -> S7Trace  {"type":"auth","proto":1,"token":...,"name":...}  first line, then "score" / "event" / "status"
  S7Trace -> analyzer  hello {proto,app,version} | meta {signals:[{name,address,dtype}],cycle_s,start_us,name,ip}
                       | batch {t:[...],v:[[...]]} (null = NaN) | state {state,gap}
"""
from __future__ import annotations

import hmac
import json
import math
import secrets
import socket
import threading
import time
from collections import deque

PROTO = 1
DEFAULT_PORT = 7700
HOST = "127.0.0.1"
SEND_EVERY_S = 0.1
MAX_BATCH_ROWS = 500
MAX_OUTBOX = 200_000
AUTH_TIMEOUT_S = 5.0
INBOX_LEN = 2000


def new_token() -> str:
    return secrets.token_urlsafe(12)


def defaults() -> dict:
    return {"enabled": False, "port": DEFAULT_PORT, "token": "", "source": ""}


def normalize(d) -> dict:
    """Ustawienia -> Analizator: enabled / port / token / source (title of the tab whose data goes to the analyzer)."""
    d = d if isinstance(d, dict) else {}
    out = defaults()
    out["enabled"] = bool(d.get("enabled", False))
    try:
        port = int(d.get("port", DEFAULT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    out["port"] = port if 1024 <= port <= 65535 else DEFAULT_PORT
    out["token"] = str(d.get("token", "") or "")
    out["source"] = str(d.get("source", "") or "")
    return out


def _clean(v):
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def encode(msg: dict) -> bytes:
    return (json.dumps(_clean(msg), separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8", "replace")
    line = line.strip()
    if not line:
        return None
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    return msg if isinstance(msg, dict) and isinstance(msg.get("type"), str) else None


class _NullFeed:
    """What a tab holds while it is not the source: every call is a no-op."""

    def meta(self, *a, **k) -> None: ...
    def sample(self, t, vals) -> None: ...
    def state(self, state, gap=None) -> None: ...


NULL = _NullFeed()


class _Peer:
    def __init__(self, sock: socket.socket, name: str):
        self.sock, self.name = sock, name
        self.lock = threading.Lock()          # the serving thread and the sender thread both write to this socket
        self.alive = True

    def send(self, data: bytes) -> bool:
        try:
            with self.lock:
                self.sock.sendall(data)
            return True
        except OSError:
            self.close()
            return False

    def close(self) -> None:
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass


class Feed:
    """Handed to the source tab. Thread-safe, cheap."""

    def __init__(self, bridge: "Bridge"):
        self._b = bridge

    def meta(self, signals: list[dict], cycle_s: float, start_us: int = 0, name: str = "", ip: str = "") -> None:
        self._b._set_meta({"type": "meta", "signals": signals, "cycle_s": float(cycle_s), "start_us": int(start_us),
                           "name": name, "ip": ip})

    def sample(self, t: float, vals) -> None:
        b = self._b
        if b._meta is not None and b.peers:
            b._outbox.append(("s", t, vals))

    def state(self, state: str, gap=None) -> None:
        self._b._set_state({"type": "state", "state": state, "gap": list(gap) if gap else None})


class Bridge:
    def __init__(self, token: str, port: int = DEFAULT_PORT, host: str = HOST, app_version: str = ""):
        self.token, self.port, self.host, self.app_version = token, port, host, app_version
        self.error = ""
        self.peers: list[_Peer] = []
        self.inbox: deque = deque(maxlen=INBOX_LEN)          # event / score / status messages of the analyzer (newest last)
        self.last_status: dict | None = None
        self.events_final = 0
        self.on_message = None                               # optional callback(msg), called in the peer's thread
        self._meta: dict | None = None
        self._state: dict | None = None
        self._outbox: deque = deque(maxlen=MAX_OUTBOX)
        self._stop = threading.Event()
        self._server: socket.socket | None = None
        self._threads: list[threading.Thread] = []

    # ---- life cycle
    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> bool:
        if self._server is not None:
            return True
        if not self.token:                                   # an empty token would let anybody on this computer in
            self.error = "brak tokenu - most nie zostanie uruchomiony"
            return False
        self._stop.clear()
        try:
            srv = socket.socket()
            srv.bind((self.host, self.port))
            srv.listen(2)
        except OSError as e:
            self.error = f"nie można otworzyć portu {self.port}: {e}"
            return False
        self.error = ""
        self.port = srv.getsockname()[1]
        self._server = srv
        for target in (self._accept_loop, self._send_loop):
            th = threading.Thread(target=target, daemon=True, name="ext-bridge")
            th.start()
            self._threads.append(th)
        return True

    def stop(self) -> None:
        self._stop.set()
        srv, self._server = self._server, None
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass
        for p in list(self.peers):
            p.close()
        self.peers.clear()
        for th in self._threads:
            th.join(2.0)
        self._threads.clear()
        self._outbox.clear()

    def feed(self) -> Feed:
        return Feed(self)

    def info(self) -> dict:
        return {"running": self.running, "port": self.port, "error": self.error,
                "clients": [p.name for p in self.peers if p.alive], "status": self.last_status,
                "events": self.events_final}

    # ---- feeding side
    def _set_meta(self, msg: dict) -> None:
        self._meta, self._state = msg, None
        if self.peers:
            self._outbox.append(("m", msg))

    def _set_state(self, msg: dict) -> None:
        self._state = msg
        if self.peers:
            self._outbox.append(("m", msg))

    # ---- threads
    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            srv = self._server
            if srv is None:
                return
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve_peer, args=(conn,), daemon=True, name="ext-bridge-peer").start()

    def _serve_peer(self, conn: socket.socket) -> None:
        peer = None
        try:
            conn.settimeout(1.0)
            buf, deadline = b"", time.monotonic() + AUTH_TIMEOUT_S
            auth = None
            while auth is None and time.monotonic() < deadline and not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    first, _, buf = buf.partition(b"\n")
                    auth = decode(first) or {}
                    break
            if (not auth or auth.get("type") != "auth" or auth.get("proto") != PROTO
                    or not hmac.compare_digest(str(auth.get("token", "")).encode(), self.token.encode())):
                conn.close()
                return
            peer = _Peer(conn, str(auth.get("name") or "analizator"))
            ok = peer.send(encode({"type": "hello", "proto": PROTO, "app": "S7Trace", "version": self.app_version}))
            for m in (self._meta, self._state):
                ok = ok and (m is None or peer.send(encode(m)))
            if not ok:
                return
            self.peers.append(peer)
            while not self._stop.is_set() and peer.alive:
                for line in buf.split(b"\n")[:-1]:
                    self._incoming(decode(line))
                buf = buf.rsplit(b"\n", 1)[-1]
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
        except OSError:
            pass
        finally:
            if peer is not None:
                peer.close()
                if peer in self.peers:
                    self.peers.remove(peer)
            else:
                try:
                    conn.close()
                except OSError:
                    pass

    def _incoming(self, msg: dict | None) -> None:
        if msg is None or msg["type"] not in ("score", "event", "status"):
            return
        if msg["type"] == "status":
            self.last_status = msg
        elif msg["type"] == "event" and not msg.get("open"):
            self.events_final += 1
        self.inbox.append(msg)
        if self.on_message is not None:
            try:
                self.on_message(msg)
            except Exception:                                # a broken callback must not kill the connection
                pass

    def _send_loop(self) -> None:
        while not self._stop.wait(SEND_EVERY_S):
            items = []
            while self._outbox:
                try:
                    items.append(self._outbox.popleft())
                except IndexError:
                    break
            if not items:
                continue
            peers = [p for p in self.peers if p.alive]
            if not peers:
                continue
            for data in self._pack(items):
                for p in peers:
                    p.send(data)

    @staticmethod
    def _pack(items: list) -> list[bytes]:
        """Items in order; consecutive samples become batches."""
        out: list[bytes] = []
        ts: list = []
        rows: list = []

        def flush() -> None:
            if ts:
                out.append(encode({"type": "batch", "t": list(ts), "v": [list(r) for r in rows]}))
                ts.clear()
                rows.clear()

        for it in items:
            if it[0] == "s":
                ts.append(it[1])
                rows.append(it[2])
                if len(ts) >= MAX_BATCH_ROWS:
                    flush()
            else:
                flush()
                out.append(encode(it[1]))
        flush()
        return out
