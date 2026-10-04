"""Desktop programs that report to the server (a central registry of who runs S7Trace and which PLCs are scanned).
The program sends its tabs every few seconds with an agent token created by an administrator; the answer lists the PLCs
that other people scan, which the program shows as a warning before Start."""
from __future__ import annotations

import threading
import time

from ..core.sessions import SCANNING

STALE_S = 20.0
MAX_TABS = 50


def host_of(ip: str) -> str:
    """The address without a port, lower case (192.168.0.1:102 -> 192.168.0.1)."""
    ip = (ip or "").strip().lower()
    return ip.rsplit(":", 1)[0] if ip.count(":") == 1 else ip


def _s(v, n=100) -> str:
    return str(v if v is not None else "")[:n]


class Agents:
    def __init__(self):
        self.items: dict[str, dict] = {}
        self._lock = threading.RLock()

    def report(self, d: dict, address: str, token_name: str) -> None:
        aid = _s(d.get("id"), 64)
        if not aid:
            raise ValueError("Brak identyfikatora programu.")
        tabs = []
        for t in (d.get("tabs") or [])[:MAX_TABS]:
            if isinstance(t, dict):
                tabs.append({"title": _s(t.get("title")), "ip": _s(t.get("ip"), 60), "state": _s(t.get("state"), 20),
                             "since": _s(t.get("since"), 40) or None})
        now = time.time()
        with self._lock:
            old = self.items.get(aid, {})
            self.items[aid] = {"id": aid, "user": _s(d.get("user")), "host": _s(d.get("host")), "pid": d.get("pid") if isinstance(d.get("pid"), int) else 0,
                               "started": _s(d.get("started"), 40), "version": _s(d.get("version"), 40), "address": address,
                               "token": token_name, "tabs": tabs, "seen": now, "first": old.get("first", now)}
            for k in [k for k, v in self.items.items() if now - v["seen"] > 300]:
                del self.items[k]

    def listing(self) -> list[dict]:
        now = time.time()
        with self._lock:
            return [{**v, "age_s": now - v["seen"], "live": now - v["seen"] <= STALE_S}
                    for v in sorted(self.items.values(), key=lambda v: v["first"])]

    def scans(self, exclude: str = "") -> list[dict]:
        """Every PLC scanned by a reporting program right now: {"ip", "user", "computer", "title", "since", "kind", "agent"}."""
        out = []
        for a in self.listing():
            if not a["live"] or a["id"] == exclude:
                continue
            for t in a["tabs"]:
                if t["state"] in SCANNING and t["ip"]:
                    out.append({"ip": host_of(t["ip"]), "user": a["user"], "computer": a["host"], "title": t["title"],
                                "since": t["since"], "kind": "desktop", "agent": a["id"]})
        return out
