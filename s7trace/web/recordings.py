"""Recordings stored in databases, for the browser: the list ("Przegląd nagrań"), reading a recording (thinned for a chart),
CSV export, title / notes / tags, the trash. Qt-free; the same backends as the desktop program (`core/store.py`).

Sources a user may open:
  sqlite        the SQLite file of the user's own account (every recording written to the target "sqlite")
  shared        the SQLite file of the shared connections (visible to everybody)
  acct:<folder> the file of another account (administrators only)
  <target name> a database target defined by an administrator
Who sees / changes what: in the own file everything; in the shared file and in database targets the administrator sees and
changes everything, the others see their own recordings (or all, when the target is set to "all") and change their own."""
from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime

import numpy as np

from ..core import store as st
from ..core.csvio import write_csv
from ..core.types import Signal
from . import files

DB_NAME = "recordings.db"
MAX_POINTS = 6000
DAY_US = 86_400_000_000


class RecError(ValueError):
    """A message that may be shown to the user as it is."""


class Source:
    def __init__(self, sid: str, label: str, cfg: st.StoreConfig, base: str, scope: str, kind: str):
        self.id, self.label, self.cfg, self.base, self.scope, self.kind = sid, label, cfg, base, scope, kind


def _same(a: str, b: str) -> bool:
    return (a or "").lower() == (b or "").lower()


class Library:
    def __init__(self, files_root: str, data_dir: str, targets):
        self.files_root, self.data_dir, self.targets = files_root, data_dir, targets

    # ---- sources
    def _sqlite(self, sid: str, label: str, folder: str, scope: str) -> Source:
        cfg = st.StoreConfig(kind="sqlite", sqlite_path=os.path.join(folder, DB_NAME))
        return Source(sid, label, cfg, folder, scope, "sqlite")

    def sources(self, user: str, role: str) -> list[Source]:
        out = [self._sqlite("sqlite", "Moje nagrania (SQLite konta)", files.account_dir(self.files_root, user), "own")]
        shared = files.account_dir(self.files_root, "")
        if os.path.isfile(os.path.join(shared, DB_NAME)):
            out.append(self._sqlite("shared", "Wspólne połączenia (SQLite)", shared, "shared"))
        if role == "admin":
            try:
                for d in sorted(os.listdir(self.files_root or "")):
                    p = os.path.join(self.files_root, d)
                    if d.startswith("u_") and os.path.isfile(os.path.join(p, DB_NAME)) and \
                            p != files.account_dir(self.files_root, user):
                        out.append(self._sqlite("acct:" + d, f"Konto {d[2:]} (SQLite)", p, "admin"))
            except OSError:
                pass
        for name in (self.targets.names() if self.targets else []):
            c = self.targets.get(name)
            if c is not None:
                base = os.path.join(self.data_dir, "dbs") if c.kind == "sqlite" else self.data_dir
                out.append(Source(name, f"{name} ({c.describe()})", c, base, "target", c.kind))
        return out

    def resolve(self, sid: str, user: str, role: str) -> Source:
        for s in self.sources(user, role):
            if s.id == sid:
                return s
        raise RecError("Nie ma takiego źródła nagrań albo brak dostępu.")

    # ---- rules
    def visible(self, src: Source, s: dict, user: str, role: str) -> bool:
        if role == "admin" or src.scope in ("own", "shared"):
            return True
        return src.cfg.view_scope == "all" or _same(s["owner"], user) or s["owner"] == ""

    def can_modify(self, src: Source, s: dict, user: str, role: str) -> bool:
        if s["id"] in st._ACTIVE_SESSIONS:                   # being written right now
            return False
        if role == "viewer":
            return False
        if role == "admin" or src.scope == "own":
            return True
        return _same(s["owner"], user) or s["owner"] == "" or (src.scope == "target" and src.cfg.delete_others)

    def _open(self, src: Source):
        if src.kind == "sqlite" and src.scope != "target" and not os.path.isfile(src.cfg.sqlite_path):
            raise RecError("Nie znaleziono nagrania w bazie.")        # (opening would create an empty file)
        try:
            return st.open_backend(src.cfg, src.base, src.cfg.test_timeout_s * 3 if src.kind != "sqlite" else None)
        except Exception as e:
            raise RecError(f"Nie można połączyć z bazą: {e}") from None

    # ---- list
    def listing(self, src: Source, user: str, role: str, trash: bool = False) -> list[dict]:
        if src.kind == "sqlite" and src.scope != "target" and not os.path.isfile(src.cfg.sqlite_path):
            return []                                        # nothing recorded yet (do not create an empty file)
        b = self._open(src)
        try:
            try:
                sessions = b.sessions()
                counts = b.stats()
            except Exception as e:
                raise RecError(f"Odczyt listy nagrań nie udał się: {e}") from None
            now = int(time.time() * 1e6)
            out = []
            for s in sessions:
                if not self.visible(src, s, user, role):
                    continue
                mod = self.can_modify(src, s, user, role)
                if s["deleted_us"]:                          # the trash empties itself after `trash_days`
                    if mod and src.cfg.trash_days > 0 and now - s["deleted_us"] > src.cfg.trash_days * DAY_US:
                        self._try(b.delete_session, s["id"])
                        continue
                elif src.cfg.retention_days > 0 and _same(s["owner"], user) and mod \
                        and now - s["start_us"] > src.cfg.retention_days * DAY_US:
                    if src.cfg.trash_days > 0:
                        self._try(b.update_session, s["id"], {"deleted_us": now})
                        s["deleted_us"] = now
                    else:
                        self._try(b.delete_session, s["id"])
                        continue
                if bool(s["deleted_us"]) != trash:
                    continue
                names = [d.get("name", "") for d in s.get("signals", []) if isinstance(d, dict)]
                out.append({"id": s["id"], "title": s["title"], "notes": s["notes"], "tags": s["tags"], "owner": s["owner"],
                            "computer": s["computer"], "name": s["name"], "ip": s["ip"], "tab": s["tab"], "conf": s["conf"],
                            "mode": s["mode"], "start_us": s["start_us"], "end_us": s["end_us"], "deleted_us": s["deleted_us"],
                            "signals": names, "entries": counts.get(s["id"]), "can_modify": mod,
                            "recording": s["id"] in st._ACTIVE_SESSIONS})
            return out
        finally:
            b.close()

    @staticmethod
    def _try(fn, *a):
        try:
            fn(*a)
        except Exception:
            pass

    def _session(self, b, sid: str) -> dict:
        s = next((x for x in b.sessions() if x["id"] == sid), None)
        if s is None:
            raise RecError("Nie znaleziono nagrania w bazie.")
        return s

    # ---- read
    def read(self, src: Source, sid: str, user: str, role: str, t0: float | None = None, t1: float | None = None,
             max_points: int = MAX_POINTS) -> dict:
        """The recording (or its time range, in seconds from its start) as JSON-ready lists, thinned to ~max_points."""
        b = self._open(src)
        try:
            meta = self._session(b, sid)
            if not self.visible(src, meta, user, role):
                raise RecError("Brak dostępu do tego nagrania.")
            a = int(meta["start_us"] + t0 * 1e6) if t0 is not None else None
            z = int(meta["start_us"] + t1 * 1e6) if t1 is not None else None
            try:
                meta, t, v = b.read(sid, a, z, max_points)
            except st.StoreError as e:
                raise RecError(str(e)) from None
            except Exception as e:
                raise RecError(f"Odczyt nagrania nie udał się: {e}") from None
        finally:
            b.close()
        n0 = len(t)
        t, v = st.downsample_minmax(t, v, max_points)
        sigs = [d for d in meta.get("signals", []) if isinstance(d, dict)]
        k = len(sigs)
        ts = ((t - meta["start_us"]) / 1e6) if n0 else np.zeros(0)
        cols = [[None if x != x else float(x) for x in v[:, i]] for i in range(k)] if len(t) else [[] for _ in range(k)]
        return {"t": [float(x) for x in ts], "values": cols, "names": [d.get("name", f"SIG{i + 1}") for i, d in enumerate(sigs)],
                "colors": [d.get("color", "#ffb347") for d in sigs], "start_us": meta["start_us"], "end_us": meta["end_us"],
                "title": meta["title"], "rows": n0, "shown": len(t), "mode": meta["mode"]}

    def search(self, src: Source, sid: str, user: str, role: str, d: dict, max_s: float = 60.0) -> dict:
        """Where the signals of a recording had the given values (all conditions at once); times in seconds from its start.
        The search is cut off after max_s seconds (the hits found so far are returned, 'timeout' is set)."""
        import threading

        from ..core import search as sr
        from .markers_api import hit_dict, parse_conds
        b = self._open(src)
        cancel = threading.Event()
        timer = threading.Timer(max_s, cancel.set)
        try:
            meta = self._session(b, sid)
            if not self.visible(src, meta, user, role):
                raise RecError("Brak dostępu do tego nagrania.")
            names = [x.get("name", "") for x in meta.get("signals", []) if isinstance(x, dict)]
            conds = parse_conds(d.get("conds"), names)
            start = int(meta["start_us"])
            end = sr.session_end_us(b, meta)
            lo = start + int(float(d["from"]) * 1e6) if d.get("from") not in (None, "") else start
            hi = start + int(float(d["to"]) * 1e6) if d.get("to") not in (None, "") else end
            timer.start()
            try:
                hits, _m = sr.search_backend(b, sid, conds, lo, hi, min_duration=max(float(d.get("min_duration") or 0), 0.0),
                                             cancel=cancel)
            except st.StoreError as e:
                raise RecError(str(e)) from None
        finally:
            timer.cancel()
            b.close()
        return {"hits": [hit_dict(h, start, True) for h in hits], "names": [names[c.signal] for c in conds], "start_us": start,
                "truncated": len(hits) >= sr.MAX_HITS, "timeout": cancel.is_set()}

    def csv_bytes(self, src: Source, sid: str, user: str, role: str, t0=None, t1=None) -> tuple[str, bytes]:
        """(file name, CSV with every row of the recording or of its time range)."""
        b = self._open(src)
        try:
            meta = self._session(b, sid)
            if not self.visible(src, meta, user, role):
                raise RecError("Brak dostępu do tego nagrania.")
            a = int(meta["start_us"] + t0 * 1e6) if t0 is not None else None
            z = int(meta["start_us"] + t1 * 1e6) if t1 is not None else None
            try:
                meta, t, v = b.read(sid, a, z, 0)
            except Exception as e:
                raise RecError(str(e)) from None
        finally:
            b.close()
        if len(t) == 0:
            raise RecError("W wybranym zakresie nie ma danych.")
        sigs = [Signal.from_dict(d) for d in meta.get("signals", []) if isinstance(d, dict)]
        start = datetime.fromtimestamp(meta["start_us"] / 1e6)
        fd, tmp = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            write_csv(tmp, sigs, (t - meta["start_us"]) / 1e6, v, start)
            with open(tmp, "rb") as f:
                data = f.read()
        finally:
            os.remove(tmp)
        return f"nagranie_{start:%Y%m%d_%H%M%S}.csv", data

    # ---- change
    def change(self, src: Source, sid: str, user: str, role: str, action: str, fields: dict | None = None) -> None:
        b = self._open(src)
        try:
            s = self._session(b, sid)
            if not self.visible(src, s, user, role) or not self.can_modify(src, s, user, role):
                raise RecError("Brak uprawnień do zmiany tego nagrania (albo nagrywanie jeszcze trwa).")
            try:
                if action == "update":
                    f = {k: str((fields or {}).get(k, ""))[:500 if k != "title" else 200] for k in ("title", "notes", "tags")
                         if k in (fields or {})}
                    if f:
                        b.update_session(sid, f)
                elif action == "trash":
                    if src.cfg.trash_days > 0:
                        b.update_session(sid, {"deleted_us": int(time.time() * 1e6)})
                    else:
                        b.delete_session(sid)
                elif action == "restore":
                    b.update_session(sid, {"deleted_us": None})
                elif action == "purge":
                    if not s["deleted_us"]:
                        raise RecError("Trwale można usunąć tylko nagranie z kosza.")
                    b.delete_session(sid)
                else:
                    raise RecError("Nieznana operacja.")
            except RecError:
                raise
            except NotImplementedError:
                raise RecError("Ta baza nie obsługuje tej operacji.") from None
            except Exception as e:
                raise RecError(f"Operacja nie udała się: {e}") from None
        finally:
            b.close()
