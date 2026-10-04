"""Registry of the running S7Trace instances on this computer: who has the program open and which PLC scans run.

Every instance keeps one small JSON file in a folder shared by all Windows accounts
(%ProgramData%\\S7Trace\\sessions, or C:\\Users\\Public\\S7Trace\\sessions when that is not writable) and refreshes it
every few seconds. A file that is not refreshed any more (closed / killed program) is treated as a closed session.
Only this computer is covered; sessions on other computers need a shared network place (Web-mode topic)."""
from __future__ import annotations

import getpass
import json
import os
import socket
import time
import uuid
from datetime import datetime
from typing import Callable

from .acquisition import parse_host

HEARTBEAT_S = 2.0
STALE_S = 10.0                 # no refresh for this long = the program is gone
PURGE_S = 300.0                # stale files are removed after this
SCANNING = ("connecting", "running", "reconnecting")


def _candidates() -> list[str]:
    out = []
    for var, sub in (("PROGRAMDATA", "S7Trace"), ("PUBLIC", "S7Trace")):
        base = os.environ.get(var)
        if base:
            out.append(os.path.join(base, sub, "sessions"))
    return out


def _grant_everyone(path: str) -> None:
    """Lets every local user write into the folder (best effort; the creator may be an ordinary user)."""
    if os.name != "nt":
        return
    try:
        import subprocess
        subprocess.run(["icacls", path, "/grant", "*S-1-5-32-545:(OI)(CI)M", "/Q"], capture_output=True, timeout=10,
                       creationflags=0x08000000)                          # CREATE_NO_WINDOW
    except Exception:
        pass


def sessions_dir() -> str | None:
    for d in _candidates():
        try:
            fresh = not os.path.isdir(d)
            os.makedirs(d, exist_ok=True)
            if fresh:
                _grant_everyone(os.path.dirname(d))
                _grant_everyone(d)
            probe = os.path.join(d, f".w{uuid.uuid4().hex[:8]}")
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            return d
        except OSError:
            continue
    return None


def windows_session_id() -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        sid = ctypes.c_ulong()
        if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid)):
            return int(sid.value)
    except Exception:
        pass
    return None


def user_name() -> str:
    try:
        name = getpass.getuser()
    except Exception:
        name = os.environ.get("USERNAME", "?")
    dom = os.environ.get("USERDOMAIN", "")
    return f"{dom}\\{name}" if dom and dom.upper() != socket.gethostname().upper() else name


class Registry:
    """The session file of this program instance. `get_tabs()` returns a list of dicts
    {"title", "ip", "state", "since" (ISO time of the connection or None)}."""

    def __init__(self, get_tabs: Callable[[], list[dict]]):
        self.get_tabs = get_tabs
        self.id = uuid.uuid4().hex
        self.started = datetime.now().isoformat(timespec="seconds")
        self.dir = sessions_dir()
        self.host = socket.gethostname()
        self.user = user_name()
        self.sid = windows_session_id()
        self._path = os.path.join(self.dir, f"{self.id}.json") if self.dir else None

    def publish(self) -> None:
        if not self._path:
            return
        data = {"id": self.id, "user": self.user, "host": self.host, "pid": os.getpid(), "session": self.sid,
                "started": self.started, "updated": time.time(), "tabs": self.get_tabs()}
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError:
            pass                                                           # a missing registry is never an error

    def close(self) -> None:
        if self._path:
            try:
                os.remove(self._path)
            except OSError:
                pass

    def sessions(self) -> list[dict]:
        """All live sessions (this one included, flagged "me"), oldest first."""
        out = []
        if not self.dir:
            return out
        now = time.time()
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for n in names:
            if not n.endswith(".json"):
                continue
            p = os.path.join(self.dir, n)
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                age = now - float(d.get("updated", 0))
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(d, dict):
                continue
            if age > PURGE_S:
                try:
                    os.remove(p)
                except OSError:
                    pass
                continue
            if age > STALE_S and d.get("id") != self.id:
                continue
            d["me"] = d.get("id") == self.id
            out.append(d)
        out.sort(key=lambda d: d.get("started", ""))
        return out

    def others_scanning(self, ip: str) -> list[dict]:
        """Other sessions that scan the same PLC address right now: [{"user", "title", "since", "session"}]."""
        host = parse_host(ip)[0]
        found = []
        for s in self.sessions():
            if s["me"]:
                continue
            for t in s.get("tabs", []):
                if t.get("state") in SCANNING and t.get("ip") and parse_host(t["ip"])[0] == host:
                    found.append({"user": s.get("user", "?"), "title": t.get("title", ""), "since": t.get("since"),
                                  "session": s.get("session")})
        return found


REGISTRY: Registry | None = None          # set by the main window; None = no registry (tests, no writable folder)


REMOTE = None                             # a core.web_agent.WebReporter when the program reports to the web server


def others_scanning(ip: str) -> list[dict]:
    """Other programs (this computer's registry) and, when reporting to the web server, programs on other computers and the
    server itself that scan the same PLC."""
    out = REGISTRY.others_scanning(ip) if REGISTRY else []
    if REMOTE is not None:
        own = tuple(s["id"] for s in REGISTRY.sessions()) if REGISTRY else ()
        out = out + REMOTE.others_scanning(ip, own)
    return out
