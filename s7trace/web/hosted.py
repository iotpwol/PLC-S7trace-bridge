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
from ..core import rec_ops, store as store_mod
from ..core.rec_marks import RecMarks
from ..core import diagnostics as dg
from ..core.config import TabConfig, load_app_config
from ..core.csvio import CsvRecorder, write_csv
from ..core.drivers import CONN_LABEL, family_of
from ..core.store import DbRecorder, StoreConfig, device_lines, device_summary
from ..core.trigger import TriggerEngine
from ..core.types import Signal, fmt_diff, signal_tip_static
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
        self._continued = False                               # this run continues the chart of the previous one (no reset, a gap in between)
        self.last_link = ("", 0, 0)                            # (rec_id, from_us, to_us) of the last Manual REC saved
        self.rec_marks = RecMarks()                           # Start / Stop REC of this run (the chart draws them; Manual REC areas live in the browser)

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
                "method": self.method_text(),
                "signals": [s.name for s in self.signals] or [s.name for s in self.cfg.signals if s.enabled],
                "owner": self.owner, "started_by": self.started_by, "started_us": self.started_us,
                "samples": len(self.buffer),
                "device": {k: v for k, v in info.items() if isinstance(v, (str, int, float)) and v != ""},
                "shared": not self.owner, "can_edit": self.can_edit(user, role), "can_run": self.can_run(user, role),
                "trigger": self.trigger_info(), "rec": self.rec_describe(), "auto_reset": bool(self.cfg.auto_reset)}

    def diag(self) -> dict:
        """What the Diagnostics view shows: link quality (the same numbers as 'Diagnostyka połączenia' of the program), the controller data
        and its clock, the state of the connection."""
        acq = self.acq
        snap = acq.diag.snapshot() if acq is not None and getattr(acq, "diag", None) is not None else None
        rating, notes = dg.verdict(snap) if snap else ("Brak danych", ["Połączenie nie pracuje – uruchom je (Start) na stronie Przegląd."])
        dev = self.device or {}
        plc_t = dev.get("plc_time")
        plc = None
        if isinstance(plc_t, datetime):
            ref = datetime.utcnow() if dev.get("plc_time_utc") else datetime.now()
            plc = {"time": plc_t.strftime("%Y-%m-%d %H:%M:%S"), "utc": bool(dev.get("plc_time_utc")),
                   "diff_s": round((plc_t - ref).total_seconds(), 1), "diff_text": fmt_diff((plc_t - ref).total_seconds())}
        return {"id": self.id, "name": self.name, "ip": self.cfg.ip, "state": self.state, "message": self.message,
                "method": self.method_text(), "cycle_ms": self.cfg.cycle_ms,
                "started_us": self.started_us, "samples": len(self.buffer), "rating": rating, "notes": notes,
                "link": _jsonable(snap) if snap else None, "device": device_lines(device_summary(self.device, self.cfg.ip)), "plc_time": plc}

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
                "written": getattr(rec, "written", None), "dropped": getattr(rec, "dropped", 0),
                "marks": [{"n": a["n"], "t0": a["t0"], "t1": a["t1"], "db": bool(a["sid"])} for a in self.rec_marks.auto]}   # Start / Stop REC lines

    # ---- control
    def method_text(self) -> str:
        """The method shown to the user; in automatic mode, once started: 'Auto: <the method that was picked>'."""
        if not self.method:
            return CONN_LABEL.get(self.cfg.conn_type, "automatycznie")
        label = CONN_LABEL.get(self.method, self.method)
        return f"Auto: {label}" if self.cfg.conn_type == "auto" and self.state != "stopped" else label

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
            cont = self.can_continue(run)
            self.signals = [Signal.from_dict(s.to_dict()) for s in run]
            if not cont:
                self.buffer.reset(len(run))
                self.rec_marks.reset()
            self._continued = cont
            c = self.cfg
            self.acq = ProcAcquirer(
                c.ip, c.rack, c.slot, c.cycle_ms, self.signals, c.mode, self.buffer,
                on_state=self._on_state, driver={"type": self.method, "opts": dict(c.conn)} if self.method != "s7" else None,
                on_info=self._on_info, on_sample=self._on_sample,
                anchor_ts=self.start_wall.timestamp() if cont else None)
            self.state, self.message = "connecting", f"Łączenie z {c.ip}…"
            self.started_us, self.started_by = int(time.time() * 1e6), user
            self.reload_trigger()                                 # (also raises the version)
            self.acq.start()

    @staticmethod
    def _sig_key(s: Signal) -> tuple:
        return (s.name, s.source, s.dtype, s.db, s.byte, s.bit, s.node)

    def can_continue(self, run: list[Signal]) -> bool:
        """A new Start keeps the chart (with a gap in it) unless 'Auto-Reset' is on, there is nothing to continue or the signals changed."""
        return (not self.cfg.auto_reset and len(self.buffer) > 0 and bool(self.signals)
                and [self._sig_key(s) for s in run] == [self._sig_key(s) for s in self.signals])

    def reset_chart(self) -> None:
        """'Reset': clears the buffer. A running connection keeps its time axis (REC and markers keep their times), a stopped one starts afresh."""
        with self._lock:
            self.buffer.reset()
            if self.recorder is None:
                self.rec_marks.reset()
            if self.state == "stopped":
                self.start_wall = datetime.now()
            self.version += 1

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
            if state == "running" and self.state in ("connecting", "stopped") and not self._continued:
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
        info = {k: str(v)[:500] for k, v in (info or {}).items() if k in ("title", "description", "notes", "tags")}
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
            n = self.rec_marks.started(self.buffer.last_time() if len(self.buffer) else 0.0, rec.session if isinstance(rec, DbRecorder) else "",
                                       "" if isinstance(rec, DbRecorder) else os.path.basename(getattr(rec, "path", "") or ""))
            self.rec_marks.span(n)["target"] = target
            self.version += 1

    def _make_recorder(self, target: str, c: TabConfig, user: str, info: dict, address: str):
        if target == "csv":
            path = files.new_path(self.mgr.files_root if self.mgr else "", self.owner, "rec", c.rec_filename,
                                  confname=c.conf_name or self.name, ip=c.ip, tab=self.name)
            rec = CsvRecorder(path, self.signals, self.start_wall, c.store.mode, device_summary(self.device, c.ip))
            label = os.path.basename(path)
        else:
            scfg, base = self._store_for(target)
            rec = DbRecorder(scfg, self.signals, self.start_wall,
                             {"name": self.name, "ip": c.ip, "tab": self.name, "conf": c.conf_name or self.name,
                              "owner": user, "computer": ("Web " + address).strip(),
                              "device": device_summary(self.device, c.ip), **info}, base_dir=base,
                             t0=self.buffer.last_time() if len(self.buffer) else 0.0)
            label = f"{target}: {rec.path}"
        return rec, label

    # ---- REC marks: a Manual REC area saved as a recording, a Start REC moved
    def _meta_for(self, user: str, address: str, title: str, notes: str = "") -> dict:
        c = self.cfg
        return {"name": self.name, "ip": c.ip, "tab": self.name, "conf": c.conf_name or self.name, "owner": user,
                "computer": ("Web " + address).strip(), "device": device_summary(self.device, c.ip), "title": title, "notes": notes}

    def rec_source(self, target: str | None = None) -> str:
        """The id of the recordings source (web/recordings.py) the target writes to; CSV files are 'csv'."""
        target = target or self.web.get("rec_target", "csv")
        if target == "sqlite":
            return "sqlite" if self.owner else "shared"
        return target

    def rec_ref(self, target: str, sid: str) -> str:
        """The `rec_id` of a marker that belongs to a recording: '<source>|<recording id>' (CSV: 'csv|<file name>')."""
        return f"{self.rec_source(target)}|{sid}" if sid else ""

    def rec_id_at(self, at_us: int) -> str:
        """The recording a marker made at this time (us since epoch) of this connection belongs to; '' = the chart buffer only."""
        t = at_us / 1e6 - self.start_wall.timestamp()
        for a in self.rec_marks.auto:
            if a["t0"] <= t <= (a["t1"] if a["t1"] is not None else float("inf")):
                if a["sid"]:
                    return self.rec_ref(a.get("target") or "", a["sid"])
                if a.get("file"):
                    return "csv|" + a["file"]
        return ""

    def rec_save_range(self, user: str, a: float, b: float, title: str = "", address: str = "") -> str:
        """'Zapis Manual REC': the buffered data of [a, b] become a recording of their own in the connection's REC target.
        Returns where it went (text)."""
        buf = self.buffer
        if len(buf) == 0:
            raise ValueError("Brak danych na wykresie.")
        a, b = max(float(a), buf.first_time()), min(float(b), buf.last_time())
        t, v = buf.snapshot(a, b)
        if b <= a or not ((t >= a) & (t <= b)).any():
            raise ValueError("W zaznaczonym obszarze nie ma zebranych próbek.")
        target, c = self.web.get("rec_target", "csv"), self.cfg
        meta = self._meta_for(user, address, (title or "Manual REC")[:200], f"Ręcznie zaznaczony obszar wykresu: {a:.2f} – {b:.2f} s od startu")
        try:
            if target == "csv":
                path = files.new_path(self.mgr.files_root if self.mgr else "", self.owner, "rec", c.rec_filename,
                                      confname=c.conf_name or self.name, ip=c.ip, tab=self.name)
                where, _ = rec_ops.save_range_recording(c.store, self.signals, self.start_wall, t, v, a, b, meta, "", path)
                self.last_link = ("csv|" + os.path.basename(where), store_mod.to_us(self.start_wall, a), store_mod.to_us(self.start_wall, b))
                return os.path.basename(where)
            scfg, base = self._store_for(target)
            where, sid = rec_ops.save_range_recording(scfg, self.signals, self.start_wall, t, v, a, b, meta, base)
            self.last_link = (self.rec_ref(target, sid), store_mod.to_us(self.start_wall, a), store_mod.to_us(self.start_wall, b))
            return f"{target}: {where}"
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Nie udało się zapisać: {e}") from None

    def rec_move_start(self, n: int, new_t: float) -> dict:
        """'Zmień Start REC (n)': fills the recording in from the buffer (earlier) or deletes what is older (later); databases only."""
        span = self.rec_marks.span(int(n))
        if span is None:
            raise ValueError("Nie ma takiego nagrania w tym przebiegu.")
        if not span["sid"]:
            raise ValueError("Nagranie do pliku CSV: przesuwanie początku działa tylko dla baz danych (SQLite, InfluxDB, TimescaleDB).")
        target = span.get("target") or self.web.get("rec_target", "csv")
        scfg, base = self._store_for(target)
        key_s = max(scfg.keyframe_min, 0.0) * 60.0 if scfg.mode == "changes" else 0.0
        plan = rec_ops.plan_move(self.buffer, self.start_wall, span, float(new_t), scfg.mode, key_s, len(self.signals))
        sid, rows, new_us = span["sid"], plan["rows"], plan["new_us"]
        rec = self.recorder
        if span["t1"] is None and isinstance(rec, DbRecorder) and rec.session == sid:        # running: the writer thread does it in step
            done, res = threading.Event(), []

            def job(be):
                meta = next((x for x in be.sessions() if x["id"] == sid), None)
                if meta is None:
                    raise store_mod.StoreError("Nie znaleziono nagrania w bazie.")
                rec_ops.move_start(be, meta, new_us, rows)

            rec.submit(job, lambda err: (res.append(err), done.set()))
            if not done.wait(30.0):
                raise ValueError("Baza nie odpowiada – zmiana zostanie wykonana, gdy wróci połączenie z bazą.")
            if res[0]:
                raise ValueError(res[0])
        else:
            use = scfg
            if scfg.kind == "sqlite":
                use = __import__("dataclasses").replace(scfg, sqlite_path=store_mod.rotated_sqlite_path(scfg, base, self.start_wall))
            be = store_mod.open_backend(use, base)
            try:
                meta = next((x for x in be.sessions() if x["id"] == sid), None)
                if meta is None:
                    raise ValueError("Nie znaleziono nagrania w bazie.")
                rec_ops.move_start(be, meta, new_us, rows)
            finally:
                be.close()
        old = span["t0"]
        self.rec_marks.set_start(int(n), plan["first"])
        self.version += 1
        lo, hi = sorted((old, plan["first"]))
        return {"t0": plan["first"], "earlier": plan["earlier"], "clamped": plan["clamped"],
                "link": {"rec_id": self.rec_ref(target, sid), "a_us": store_mod.to_us(self.start_wall, lo), "b_us": store_mod.to_us(self.start_wall, hi)}}

    def rec_info_update(self, info: dict) -> None:
        info = {k: str(v)[:500] for k, v in (info or {}).items() if k in ("title", "description", "notes", "tags")}
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
            self.rec_marks.stopped(self.buffer.last_time() if len(self.buffer) else 0.0)
            try:
                rec.close()
            except Exception as e:
                self.rec_error = str(e)
            self.version += 1

    def _on_info(self, d: dict) -> None:
        with self._lock:
            self.device = d
            self.version += 1
        rec = self.recorder
        if isinstance(rec, DbRecorder):                          # the recording carries the data of the PLC it was made on
            rec.update_device(device_summary(d, self.cfg.ip))

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
                "colors": [s.color for s in self.signals], "shares": [float(s.share) for s in self.signals],
                "gains": [float(s.gain) for s in self.signals], "dtypes": [s.dtype for s in self.signals],
                "offsets": [float(s.offset_y) for s in self.signals],
                "addresses": [s.address for s in self.signals], "tips": [signal_tip_static(s) for s in self.signals],
                "layout": {"legend_mode": self.cfg.legend_mode, "time_axis": self.cfg.time_axis, "time_offset": self.cfg.time_offset, "y_layout": self.cfg.y_layout, "auto_y": self.cfg.auto_y, "y_min": self.cfg.y_min,
                           "y_max": self.cfg.y_max, "show_points": self.cfg.show_points},
                "rec": [{"n": a["n"], "t0": a["t0"], "t1": a["t1"], "db": bool(a["sid"])} for a in self.rec_marks.auto],     # Start / Stop REC lines
                "last": float(last), "state": self.state,
                "plc_diff": (self.device or {}).get("time_diff_local"),            # PLC clock minus the server's [s] (axis "Czas PLC")
                "tz_offset": time.localtime().tm_gmtoff,                            # the server's zone: the clock axes show the SERVER's local time
                "start_us": int(self.start_wall.timestamp() * 1e6)}


def _jsonable(v):
    """numpy numbers / NaN / tuples of a statistics snapshot -> plain JSON values."""
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    return v


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
