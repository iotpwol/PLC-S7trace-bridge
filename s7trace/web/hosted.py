"""Connections hosted by the web server: a headless version of one tab (no GUI) - acquisition in a child process,
a trace buffer, the state and the data of the controller. Loaded from an S7Trace configuration file (TabConfig)."""
from __future__ import annotations

import threading
import time

import numpy as np

from ..core.acq_process import ProcAcquirer
from ..core.buffer import TraceBuffer
from ..core.config import TabConfig, load_app_config
from ..core.drivers import CONN_LABEL, family_of
from ..core.types import Signal

MAX_SERIES_POINTS = 4000


class HostedConnection:
    """One connection (a tab of the desktop program) running on the server."""

    def __init__(self, cid: str, cfg: TabConfig, owner: str = ""):
        self.id, self.cfg, self.owner = cid, cfg, owner
        self.buffer = TraceBuffer(0)
        self.signals: list[Signal] = []
        self.acq: ProcAcquirer | None = None
        self.state, self.message = "stopped", ""
        self.device: dict | None = None
        self.method = ""
        self.started_us = 0
        self.started_by = ""
        self._lock = threading.RLock()
        self.version = 0                                      # grows with every state / data change (for the SSE stream)

    # ---- description (shown on the overview page)
    @property
    def name(self) -> str:
        return self.cfg.name.strip() or self.cfg.ip or self.id

    def describe(self) -> dict:
        info = (self.device or {}).get("info") or {}
        return {"id": self.id, "name": self.name, "ip": self.cfg.ip, "rack": self.cfg.rack, "slot": self.cfg.slot,
                "cycle_ms": self.cfg.cycle_ms, "state": self.state, "message": self.message,
                "method": CONN_LABEL.get(self.method, self.method or "automatycznie"),
                "signals": [s.name for s in self.signals] or [s.name for s in self.cfg.signals if s.enabled],
                "owner": self.owner, "started_by": self.started_by, "started_us": self.started_us,
                "samples": len(self.buffer),
                "device": {k: v for k, v in info.items() if isinstance(v, (str, int, float)) and v != ""}}

    # ---- control
    def _pick_method(self, run: list[Signal]) -> str:
        kind = self.cfg.conn_type
        return (family_of(run) or "s7") if kind == "auto" else kind

    def start(self, user: str = "") -> None:
        with self._lock:
            if self.state != "stopped":
                return
            run = [s for s in self.cfg.signals if s.enabled]
            if not run:
                raise ValueError("Brak sygnałów do pobierania w tej konfiguracji.")
            self.method = self._pick_method(run)
            self.signals = [Signal.from_dict(s.to_dict()) for s in run]
            self.buffer.reset(len(run))
            c = self.cfg
            self.acq = ProcAcquirer(
                c.ip, c.rack, c.slot, c.cycle_ms, self.signals, c.mode, self.buffer,
                on_state=self._on_state, driver={"type": self.method, "opts": dict(c.conn)} if self.method != "s7" else None,
                on_info=self._on_info)
            self.state, self.message = "connecting", f"Łączenie z {c.ip}…"
            self.started_us, self.started_by = int(time.time() * 1e6), user
            self.version += 1
            self.acq.start()

    def stop(self) -> None:
        with self._lock:
            acq = self.acq
        if acq is not None and self.state != "stopped":
            acq.stop()

    def shutdown(self, wait: float = 5.0) -> None:
        self.stop()
        if self.acq is not None:
            self.acq.join(wait)

    def _on_state(self, state: str, message: str) -> None:
        with self._lock:
            self.state, self.message = state, message
            self.version += 1

    def _on_info(self, d: dict) -> None:
        with self._lock:
            self.device = d
            self.version += 1

    # ---- data
    def series(self, seconds: float = 60.0, max_points: int = MAX_SERIES_POINTS, since: float | None = None) -> dict:
        """The last `seconds` (or everything after time `since`) as JSON-ready lists, thinned to `max_points`."""
        n = len(self.signals)
        last = self.buffer.last_time() if len(self.buffer) else 0.0
        x0 = since if since is not None else last - seconds
        t, v = self.buffer.snapshot(x0, last + 1e-9) if len(self.buffer) else (np.zeros(0), np.zeros((0, n)))
        if since is not None and len(t):
            keep = t > since
            t, v = t[keep], v[keep]
        if len(t) > max_points:
            idx = np.linspace(0, len(t) - 1, max_points).astype(int)
            t, v = t[idx], v[idx]
        cols = [[None if x != x else float(x) for x in v[:, k]] for k in range(n)] if len(t) else [[] for _ in range(n)]
        return {"t": [float(x) for x in t], "names": [s.name for s in self.signals], "values": cols,
                "colors": [s.color for s in self.signals], "last": float(last), "state": self.state}


class HostManager:
    """All connections of the server. They come from an S7Trace configuration file (every tab = one connection)."""

    def __init__(self):
        self.items: dict[str, HostedConnection] = {}
        self._lock = threading.RLock()

    def load_config(self, path: str, owner: str = "") -> list[str]:
        cfg = load_app_config(path)
        ids = []
        for i, d in enumerate(cfg.get("tabs") or []):
            tc = TabConfig.from_dict(d)
            cid = f"c{len(self.items) + 1}"
            with self._lock:
                self.items[cid] = HostedConnection(cid, tc, owner)
            ids.append(cid)
        return ids

    def add(self, cfg: TabConfig, owner: str = "") -> HostedConnection:
        with self._lock:
            cid = f"c{len(self.items) + 1}"
            self.items[cid] = HostedConnection(cid, cfg, owner)
            return self.items[cid]

    def get(self, cid: str) -> HostedConnection | None:
        with self._lock:
            return self.items.get(cid)

    def all(self) -> list[HostedConnection]:
        with self._lock:
            return list(self.items.values())

    def shutdown(self) -> None:
        for c in self.all():
            c.shutdown()
