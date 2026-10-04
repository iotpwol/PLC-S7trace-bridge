"""Connections hosted by the web server: a headless version of one tab (no GUI) - acquisition in a child process,
a trace buffer, the state and the data of the controller. Loaded from an S7Trace configuration file (TabConfig)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime

import numpy as np

from ..core.acq_process import ProcAcquirer
from ..core.buffer import TraceBuffer
from ..core.config import TabConfig, load_app_config
from ..core.csvio import CsvRecorder, write_csv
from ..core.drivers import CONN_LABEL, family_of
from ..core.store import DbRecorder, StoreConfig
from ..core.trigger import TriggerEngine
from ..core.types import Signal
from . import files

MAX_SERIES_POINTS = 4000


class HostedConnection:
    """One connection (a tab of the desktop program) running on the server."""

    def __init__(self, cid: str, cfg: TabConfig, owner: str = "", web: dict | None = None, mgr=None):
        self.id, self.cfg, self.owner, self.mgr = cid, cfg, owner, mgr
        self.web = {"rec_target": "csv", **(web or {})}       # settings that exist only in the web mode (saved with the connection)
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
        self.start_wall = datetime.now()
        # trigger (the same state machine as in a tab: off / armed / post / hold)
        self.engine = TriggerEngine(cfg.trigger)
        self.trig_state, self.trig_note = "off", ""
        self.trig_t = self.trig_win = self.trig_post_end = 0.0
        self.trig_x0 = self.trig_x1 = None
        self.trig_events: list[dict] = []
        self._trig_idx: int | None = None
        # REC
        self.recorder = None
        self.rec_info: dict = {}
        self.rec_by, self.rec_started_us, self.rec_error, self.rec_label, self.rec_target = "", 0, "", "", ""
        self._rec_lock = threading.RLock()

    # ---- description (shown on the overview page)
    @property
    def name(self) -> str:
        return self.cfg.name.strip() or self.cfg.ip or self.id

    # ---- who may do what: the owner and the administrators; a connection without an owner is shared (operators run it)
    def can_view(self, user: str, role: str) -> bool:
        return role == "admin" or not self.owner or self.owner.lower() == user.lower()

    def can_edit(self, user: str, role: str) -> bool:
        return role == "admin" or (role in ("operator",) and self.owner.lower() == user.lower() and bool(self.owner))

    def can_run(self, user: str, role: str) -> bool:
        return role in ("operator", "admin") and self.can_view(user, role)

    def describe(self, user: str = "", role: str = "") -> dict:
        info = (self.device or {}).get("info") or {}
        return {"id": self.id, "name": self.name, "ip": self.cfg.ip, "rack": self.cfg.rack, "slot": self.cfg.slot,
                "cycle_ms": self.cfg.cycle_ms, "state": self.state, "message": self.message,
                "method": CONN_LABEL.get(self.method, self.method or "automatycznie"),
                "signals": [s.name for s in self.signals] or [s.name for s in self.cfg.signals if s.enabled],
                "owner": self.owner, "started_by": self.started_by, "started_us": self.started_us,
                "samples": len(self.buffer),
                "device": {k: v for k, v in info.items() if isinstance(v, (str, int, float)) and v != ""},
                "shared": not self.owner, "can_edit": self.can_edit(user, role), "can_run": self.can_run(user, role),
                "trigger": self.trigger_info(), "rec": self.rec_describe()}

    def trigger_info(self) -> dict:
        tc = self.cfg.trigger
        return {"enabled": tc.enabled, "state": self.trig_state, "signal": tc.signal, "action": tc.action, "note": self.trig_note,
                "t": self.trig_t, "x0": self.trig_x0, "x1": self.trig_x1, "events": list(self.trig_events)}

    def rec_describe(self) -> dict:
        rec = self.recorder
        err = self.rec_error or (getattr(rec, "last_error", "") if rec is not None else "")
        return {"active": rec is not None, "target": self.web.get("rec_target", "csv"), "mode": self.cfg.store.mode,
                "label": self.rec_label, "title": self.rec_info.get("title", ""), "by": self.rec_by,
                "started_us": self.rec_started_us, "error": err,
                "written": getattr(rec, "written", None), "dropped": getattr(rec, "dropped", 0)}

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
                on_info=self._on_info, on_sample=self._on_sample)
            self.state, self.message = "connecting", f"Łączenie z {c.ip}…"
            self.started_us, self.started_by = int(time.time() * 1e6), user
            self.reload_trigger()                                 # (also raises the version)
            self.acq.start()

    def stop(self) -> None:
        with self._lock:
            acq = self.acq
        if acq is not None and self.state != "stopped":
            acq.stop()

    def shutdown(self, wait: float = 5.0) -> None:
        self.rec_stop()
        self.stop()
        if self.acq is not None:
            self.acq.join(wait)

    def _on_state(self, state: str, message: str) -> None:
        with self._lock:
            if state == "running" and self.state in ("connecting", "stopped"):
                self.start_wall = datetime.now()
            self.state, self.message = state, message
            self.version += 1
        if state in ("stopped", "error"):
            self.trig_state = "off"
            self.rec_stop()

    # ---- trigger
    def reload_trigger(self) -> None:
        """Re-reads the trigger settings (after Start and after an edit): the state machine starts again."""
        tc = self.cfg.trigger
        self.engine = TriggerEngine(tc)
        names = [s.name for s in self.signals]
        self._trig_idx = names.index(tc.signal) if tc.signal in names else None
        running = self.acq is not None and self.state != "stopped"
        self.trig_state = "armed" if (tc.enabled and self._trig_idx is not None and running) else "off"
        self.trig_x0 = self.trig_x1 = None
        self.version += 1

    def rearm(self) -> None:
        if self.trig_state == "hold":
            self.engine.reset()
            self.trig_state, self.trig_x0, self.trig_x1 = "armed", None, None
            self.version += 1

    def _on_sample(self, t: float, vals) -> None:
        """Runs in the reader thread of the acquisition: REC first, then the trigger."""
        rec = self.recorder
        if rec is not None:
            try:
                rec.write(t, vals)
            except Exception as e:                            # (e.g. disk full) REC goes on trying; the error is shown
                self.rec_error = str(e) or type(e).__name__
        if self.trig_state in ("armed", "post"):
            self._trigger(t, vals)

    def _trigger(self, t: float, vals) -> None:
        tc = self.cfg.trigger
        i = self._trig_idx
        if self.trig_state == "armed" and tc.enabled and i is not None and i < len(vals) and self.engine.feed(vals[i]):
            self.trig_t, self.trig_win = t, max(float(self.cfg.window_s), 0.1)
            pre = min(tc.pretrigger, self.trig_win)
            self.trig_post_end = t + max(self.trig_win - pre, 0.0)
            self.trig_state = "post"
            self.version += 1
        if self.trig_state == "post" and t >= self.trig_post_end:
            self._trigger_action()

    def _trigger_action(self) -> None:
        tc = self.cfg.trigger
        pre = min(tc.pretrigger, self.trig_win)
        x0 = self.trig_t - pre
        x1 = x0 + self.trig_win
        note, name = "", ""
        if "CSV" in tc.action:
            try:
                t, v = self.buffer.snapshot(x0, x1)
                m = (t >= x0) & (t <= x1)
                if not m.any():
                    raise ValueError("brak próbek w zakresie")
                path = files.new_path(self.mgr.files_root if self.mgr else "", self.owner, "snapshots", tc.filename,
                                      confname=self.cfg.conf_name or self.name, ip=self.cfg.ip, tab=self.name)
                write_csv(path, self.signals, t[m], v[m], self.start_wall)
                name = os.path.basename(path)
                note = f"Zapisano {name}"
            except Exception as e:
                note = f"Błąd zapisu CSV: {e}"
        if "Pauza" in tc.action:
            self.trig_state, self.trig_x0, self.trig_x1 = "hold", x0, x1
            note = note or "Wstrzymano (Wznów = ponowne uzbrojenie)."
        else:
            self.engine.reset()
            self.trig_state = "armed"
        self.trig_note = note
        self.trig_events = (self.trig_events + [{"t": self.trig_t, "x0": x0, "x1": x1, "file": name,
                                                  "us": int(time.time() * 1e6)}])[-20:]
        self.version += 1

    # ---- REC
    def _store_for(self, target: str) -> tuple[StoreConfig, str]:
        """The StoreConfig and the base folder for the chosen target (CSV is handled elsewhere)."""
        mode = self.cfg.store.mode
        if target == "sqlite":
            root = self.mgr.files_root if self.mgr else ""
            return StoreConfig(kind="sqlite", mode=mode, sqlite_path="recordings.db"), files.account_dir(root, self.owner)
        c = self.mgr.targets.get(target) if self.mgr and self.mgr.targets else None
        if c is None:
            raise ValueError(f"Nie ma celu zapisu „{target}” – wybierz inny w ustawieniach połączenia.")
        c.mode = mode
        if c.kind == "sqlite":
            return c, os.path.join(self.mgr.data_dir, "dbs")
        return c, self.mgr.data_dir

    def rec_start(self, user: str, info: dict | None = None, address: str = "") -> None:
        info = {k: str(v)[:500] for k, v in (info or {}).items() if k in ("title", "notes", "tags")}
        with self._rec_lock:
            if self.recorder is not None:
                raise ValueError("Nagrywanie już trwa.")
            if self.state != "running":
                raise ValueError("Nagrywanie wymaga działającego połączenia (stan: praca).")
            target, c = self.web.get("rec_target", "csv"), self.cfg
            try:
                rec, label = self._make_recorder(target, c, user, info, address)
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(f"Nie można rozpocząć nagrywania: {e}") from None
            self.recorder, self.rec_info, self.rec_by = rec, info, user
            self.rec_started_us, self.rec_error, self.rec_label, self.rec_target = int(time.time() * 1e6), "", label, target
            self.version += 1

    def _make_recorder(self, target: str, c: TabConfig, user: str, info: dict, address: str):
        if target == "csv":
            path = files.new_path(self.mgr.files_root if self.mgr else "", self.owner, "rec", c.rec_filename,
                                  confname=c.conf_name or self.name, ip=c.ip, tab=self.name)
            rec = CsvRecorder(path, self.signals, self.start_wall, c.store.mode)
            label = os.path.basename(path)
        else:
            scfg, base = self._store_for(target)
            rec = DbRecorder(scfg, self.signals, self.start_wall,
                             {"name": self.name, "ip": c.ip, "tab": self.name, "conf": c.conf_name or self.name,
                              "owner": user, "computer": ("Web " + address).strip(), **info}, base_dir=base)
            label = f"{target}: {rec.path}"
        return rec, label

    def rec_info_update(self, info: dict) -> None:
        info = {k: str(v)[:500] for k, v in (info or {}).items() if k in ("title", "notes", "tags")}
        with self._rec_lock:
            rec = self.recorder
            if rec is None:
                raise ValueError("Nagrywanie nie trwa.")
            if isinstance(rec, DbRecorder):
                rec.update_info(**info)
            self.rec_info.update(info)
            self.version += 1

    def rec_stop(self) -> None:
        with self._rec_lock:
            rec, self.recorder = self.recorder, None
        if rec is not None:
            try:
                rec.close()
            except Exception as e:
                self.rec_error = str(e)
            self.version += 1

    def _on_info(self, d: dict) -> None:
        with self._lock:
            self.device = d
            self.version += 1

    # ---- data
    def series(self, seconds: float = 60.0, max_points: int = MAX_SERIES_POINTS, since: float | None = None,
               span: tuple[float, float] | None = None) -> dict:
        """The last `seconds` (or everything after time `since`, or the time range `span`) as JSON-ready lists,
        thinned to `max_points`."""
        n = len(self.signals)
        last = self.buffer.last_time() if len(self.buffer) else 0.0
        x0 = since if since is not None else last - seconds
        x1 = last + 1e-9
        if span is not None:
            x0, x1 = span
        t, v = self.buffer.snapshot(x0, x1) if len(self.buffer) else (np.zeros(0), np.zeros((0, n)))
        if since is not None and len(t):
            keep = t > since
            t, v = t[keep], v[keep]
        if len(t) > max_points:
            idx = np.linspace(0, len(t) - 1, max_points).astype(int)
            t, v = t[idx], v[idx]
        cols = [[None if x != x else float(x) for x in v[:, k]] for k in range(n)] if len(t) else [[] for _ in range(n)]
        return {"t": [float(x) for x in t], "names": [s.name for s in self.signals], "values": cols,
                "colors": [s.color for s in self.signals], "last": float(last), "state": self.state,
                "start_us": int(self.start_wall.timestamp() * 1e6)}


class HostManager:
    """All connections of the server. Every account has its own workspace (its connections, saved in `store_dir`);
    connections without an owner are shared by everybody. `--config` files add shared connections."""

    SHARED = "_shared"
    MAX_PER_USER = 30

    def __init__(self, store_dir: str | None = None, files_root: str = "", targets=None, data_dir: str = ""):
        self.items: dict[str, HostedConnection] = {}
        self._lock = threading.RLock()
        self.store_dir = store_dir
        self.files_root, self.targets, self.data_dir = files_root, targets, data_dir     # (App fills in what is missing)
        if store_dir:
            os.makedirs(store_dir, exist_ok=True)
            self._load()

    # ---- persistence: one JSON file per owner
    def _file(self, owner: str) -> str:
        name = self.SHARED if not owner else "u_" + re.sub(r"[^A-Za-z0-9_.@-]", "_", owner.lower())
        return os.path.join(self.store_dir or "", name + ".json")

    def _load(self) -> None:
        for fn in sorted(os.listdir(self.store_dir)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.store_dir, fn), encoding="utf-8") as f:
                    d = json.load(f)
                owner = "" if fn == self.SHARED + ".json" else str(d.get("owner", ""))
                for c in d.get("connections", []):
                    cid = str(c["id"])
                    self.items[cid] = HostedConnection(cid, TabConfig.from_dict(c["cfg"]), owner, c.get("web"), self)
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def save(self, owner: str) -> None:
        if not self.store_dir:
            return
        with self._lock:
            rows = [{"id": h.id, "cfg": h.cfg.to_dict(), "web": h.web} for h in self.items.values() if h.owner == owner]
            path = self._file(owner)
            if not rows:
                if os.path.isfile(path):
                    os.remove(path)
                return
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"owner": owner, "connections": rows}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)

    # ---- items
    def _new_id(self) -> str:
        n = max([int(k[1:]) for k in self.items if re.fullmatch(r"c\d+", k)] or [0]) + 1
        return f"c{n}"

    def load_config(self, path: str, owner: str = "") -> list[str]:
        """Adds the tabs of an S7Trace configuration file (skipping those already present with the same name / address)."""
        cfg = load_app_config(path)
        ids = []
        for d in cfg.get("tabs") or []:
            tc = TabConfig.from_dict(d)
            with self._lock:
                if any(h.owner == owner and (h.cfg.name, h.cfg.ip, h.cfg.rack, h.cfg.slot) == (tc.name, tc.ip, tc.rack, tc.slot)
                       for h in self.items.values()):
                    continue
                ids.append(self.add(tc, owner).id)
        return ids

    def add(self, cfg: TabConfig, owner: str = "", web: dict | None = None) -> HostedConnection:
        with self._lock:
            if owner and sum(1 for h in self.items.values() if h.owner == owner) >= self.MAX_PER_USER:
                raise ValueError(f"Najwyżej {self.MAX_PER_USER} połączeń na konto.")
            cid = self._new_id()
            self.items[cid] = HostedConnection(cid, cfg, owner, web, self)
            self.save(owner)
            return self.items[cid]

    def remove(self, cid: str) -> None:
        with self._lock:
            h = self.items.get(cid)
            if h is None:
                return
            if h.state != "stopped":
                raise ValueError("Zatrzymaj połączenie przed usunięciem.")
            del self.items[cid]
            self.save(h.owner)

    def get(self, cid: str) -> HostedConnection | None:
        with self._lock:
            return self.items.get(cid)

    def all(self) -> list[HostedConnection]:
        with self._lock:
            return list(self.items.values())

    def visible(self, user: str, role: str) -> list[HostedConnection]:
        return [h for h in self.all() if h.can_view(user, role)]

    def shutdown(self) -> None:
        for c in self.all():
            c.shutdown()
