"""Reporting of the desktop program to the S7Trace web server (central registry of who runs the program and which PLCs
are scanned). Qt-free: a thread posts the state every few seconds; the answer (PLCs scanned by other people) is cached and
used for the warning before Start. A missing / unreachable server is never an error for the program."""
from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

from .sessions import parse_host

INTERVAL_S = 5.0
FRESH_S = 30.0                     # the cached scans are used for this long after the last answer


def defaults() -> dict:
    return {"enabled": False, "url": "", "token": "", "verify": True}


def normalize(d) -> dict:
    out = defaults()
    if isinstance(d, dict):
        for k, v in defaults().items():
            if isinstance(d.get(k), type(v)):
                out[k] = d[k]
    out["url"] = out["url"].strip().rstrip("/")
    return out


def post(cfg: dict, path: str, body: dict, timeout: float = 6.0) -> dict:
    """POST JSON to the server with the agent token; returns the answer or raises OSError / ValueError with a message."""
    url = cfg["url"] + path
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Adres serwera musi zaczynać się od http:// albo https://")
    req = urllib.request.Request(url, json.dumps(body).encode("utf-8"), {
        "Content-Type": "application/json", "X-S7Trace": "1", "X-S7Trace-Agent": cfg["token"]})
    ctx = None
    if url.lower().startswith("https://") and not cfg.get("verify", True):
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:
            msg = ""
        raise ValueError(msg or f"Serwer odpowiedział błędem {e.code}.") from None
    except urllib.error.URLError as e:
        raise ValueError(f"Brak połączenia z serwerem: {e.reason}") from None


class WebReporter:
    def __init__(self, get_payload: Callable[[], dict], cfg: dict, interval: float = INTERVAL_S):
        self.get_payload, self.cfg, self.interval = get_payload, normalize(cfg), interval
        self.status = "wyłączone"
        self._scans: list[dict] = []
        self._at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.cfg["enabled"] or not self.cfg["url"] or not self.cfg["token"]:
            self.status = "wyłączone"
            return
        self.status = "łączenie…"
        self._thread = threading.Thread(target=self._run, daemon=True, name="WebReporter")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.report_once()
            self._stop.wait(self.interval)

    def report_once(self) -> bool:
        try:
            ans = post(self.cfg, "/api/agent/report", self.get_payload())
            self._scans, self._at, self.status = list(ans.get("scans") or []), time.time(), "połączono"
            return True
        except (OSError, ValueError) as e:
            self.status = str(e) or type(e).__name__
            return False

    def others_scanning(self, ip: str, own_ids: tuple = ()) -> list[dict]:
        """Scans of the same PLC by programs on other computers (or by the server) - same shape as `sessions.others_scanning`."""
        if time.time() - self._at > FRESH_S:
            return []
        host = parse_host(ip)[0].lower()
        return [{"user": f"{s.get('user', '?')} ({s.get('computer', '')})".replace(" ()", ""), "title": s.get("title", ""),
                 "since": s.get("since"), "session": None}
                for s in self._scans if s.get("ip") == host and s.get("agent") not in own_ids]
