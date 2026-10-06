"""Markers and the value search for the browser (see core/markers.py and core/search.py for what they are).

Who sees / changes what:
  * a marker is visible to its author, to administrators and - when it was set on a SHARED connection of the server - to
    everybody who may view that connection;
  * it can be changed or deleted by its author and by administrators;
  * only operators and administrators create markers (viewers only read).
Times are microseconds since the epoch; a marker made on a live connection carries the connection id in `conn`, a marker made
on a recording of a database carries `<source>|<recording id>` in `rec_id`."""
from __future__ import annotations

import math

import numpy as np

from ..core import markers as mk
from ..core import search as sr

EDITABLE = ("kind", "at_us", "end_us", "signals", "group_name", "line_width", "line_style", "opacity", "show_label", "title",
            "description", "notes", "color", "priority")
MAX_PER_AUTHOR = 20000
MAX_CONDS = 5
MAX_BATCH = 500


def _same(a: str, b: str) -> bool:
    return (a or "").casefold() == (b or "").casefold()


class MarkerService:
    def __init__(self, path: str, hosts):
        self.store = mk.MarkerStore(path)
        self.hosts = hosts

    # ---- rules
    def shared_ids(self) -> list[str]:
        return [h.id for h in self.hosts.all() if not h.owner]

    def can_see(self, m: mk.Marker, user: str, role: str) -> bool:
        return role == "admin" or _same(m.author, user) or (m.conn != "" and m.conn in self.shared_ids())

    def can_edit(self, m: mk.Marker, user: str, role: str) -> bool:
        return role in ("operator", "admin") and (role == "admin" or _same(m.author, user))

    def _visible_to(self, user: str, role: str):
        return None if role == "admin" else (user, self.shared_ids())

    def _dict(self, m: mk.Marker, user: str, role: str) -> dict:
        h = self.hosts.get(m.conn) if m.conn else None
        return {**m.to_dict(), "can_edit": self.can_edit(m, user, role), "conn_name": h.name if h is not None else "",
                "buffered": bool(h is not None and len(h.buffer))}      # the connection still holds its chart data in memory

    # ---- reading
    def listing(self, user: str, role: str, q: dict) -> dict:
        def num(k):
            return int(float(q[k])) if q.get(k, "") != "" else None
        vis = self._visible_to(user, role)
        rows = self.store.search(
            q.get("q", ""), num("from"), num("to"), colors=[q["color"]] if q.get("color") else None,
            priorities=[int(q["priority"])] if q.get("priority", "") != "" else None,
            authors=[q["author"]] if q.get("author") else None, visible_to=vis,
            group=q.get("group") if "group" in q else None, conn=q.get("conn") if q.get("conn") else None,
            rec_id=q.get("rec") if q.get("rec") else None, order=q.get("order", "at"),
            limit=min(max(num("limit") or 500, 1), 2000))
        if q.get("conns"):                                              # markers of connections (not of recordings): 'show also other connections'
            rows = [m for m in rows if m.conn]
        if q.get("norec"):                                              # only the chart buffer: they belong to no recording
            rows = [m for m in rows if m.conn and not m.rec_id]
        return {"markers": [self._dict(m, user, role) for m in rows],
                "groups": [{"name": g, "count": n} for g, n in self.store.groups(vis)],
                "authors": sorted({m.author for m in self.store.search(visible_to=vis, limit=2000) if m.author})}

    def _stamp_rec(self, f: dict) -> None:
        """A marker put on a live connection gets the recording that covers its time (empty = the chart buffer only)."""
        conn = str(f.get("conn") or "")
        h = self.hosts.get(conn) if conn else None
        if h is not None and not f.get("rec_id") and "at_us" in f:
            try:
                f["rec_id"] = h.rec_id_at(int(f["at_us"]))
            except (TypeError, ValueError):
                pass

    def link_range(self, conn: str, rec_id: str, a_us: int, b_us: int, unlink: bool = False) -> int:
        """A recording of the connection now holds (or no longer holds, `unlink`) the time [a, b]: its markers follow."""
        if not rec_id:
            return 0
        if unlink:
            return self.store.unlink_recording(rec_id, a_us, b_us)
        return self.store.link_recording(rec_id, a_us, b_us, conn=conn)

    # ---- changing
    def _get(self, mid, user: str, role: str, edit: bool = True) -> mk.Marker:
        try:
            m = self.store.get(int(mid))
        except (TypeError, ValueError):
            m = None
        if m is None or not self.can_see(m, user, role):
            raise mk.MarkerError("Nie ma takiego znacznika.")
        if edit and not self.can_edit(m, user, role):
            raise mk.MarkerError("Znacznik może zmieniać tylko jego autor albo administrator.")
        return m

    def _batch(self, user: str, role: str, d: dict, address: str) -> dict:
        """'Zapisz znaczniki' of the browser: new + changed + deleted markers in ONE transaction. Every right is checked before
        anything is written, so one refused change cancels the whole batch. adds may carry `tmp` (the id the page used);
        the answer maps it to the saved id."""
        adds, ups, dels = d.get("adds") or [], d.get("updates") or [], d.get("deletes") or []
        if not all(isinstance(x, list) for x in (adds, ups, dels)) or len(adds) + len(ups) + len(dels) > MAX_BATCH:
            raise mk.MarkerError(f"Za dużo zmian naraz (najwyżej {MAX_BATCH}).")
        if not (adds or ups or dels):
            return {"ok": True, "added": [], "new_ids": {}, "updated": 0, "deleted": 0, "missing": []}
        if adds and role not in ("operator", "admin"):
            raise mk.MarkerError("Znaczniki zakładają operatorzy i administratorzy.")
        if adds and len(self.store.search(authors=[user], limit=MAX_PER_AUTHOR + 1)) + len(adds) > MAX_PER_AUTHOR:
            raise mk.MarkerError("Za dużo znaczników tego konta – usuń niepotrzebne.")
        clean_adds, tmps = [], []
        for a in adds:
            if not isinstance(a, dict) or "at_us" not in a:
                raise mk.MarkerError("Brak czasu znacznika.")
            conn = str(a.get("conn") or "")
            if conn:
                h = self.hosts.get(conn)
                if h is None or not h.can_view(user, role):
                    raise mk.MarkerError("Nie ma takiego połączenia.")
            clean_adds.append({k: a[k] for k in EDITABLE + ("at_us", "conn", "rec_id") if k in a})
            self._stamp_rec(clean_adds[-1])
            tmps.append(a.get("tmp"))
        updates = []
        for u in ups:
            if not isinstance(u, dict):
                raise mk.MarkerError("Niepoprawna zmiana znacznika.")
            m = self._get(u.get("id"), user, role)
            updates.append((m.id, {k: u[k] for k in EDITABLE if k in u}))
        deletes = [self._get(i, user, role).id for i in dels]
        rep = self.store.apply(clean_adds, updates, deletes, by=user, computer=address)
        rep["new_ids"] = {str(t): i for t, i in zip(tmps, rep["added"]) if t is not None}
        rep["ok"] = True
        return rep

    def change(self, user: str, role: str, d: dict, address: str = "") -> dict:
        action = str(d.get("action", ""))
        st = self.store
        if action == "add":
            f = {k: d[k] for k in EDITABLE + ("conn", "rec_id") if k in d}
            if "at_us" not in f:
                raise mk.MarkerError("Brak czasu znacznika.")
            conn = str(f.get("conn") or "")
            if conn:
                h = self.hosts.get(conn)
                if h is None or not h.can_view(user, role):
                    raise mk.MarkerError("Nie ma takiego połączenia.")
            if len(st.search(authors=[user], limit=MAX_PER_AUTHOR + 1)) > MAX_PER_AUTHOR:
                raise mk.MarkerError("Za dużo znaczników tego konta – usuń niepotrzebne.")
            self._stamp_rec(f)
            at = f.pop("at_us")
            m = st.add(at, author=user, computer=address, **f)
            return {"ok": True, "marker": self._dict(m, user, role)}
        if action == "update":
            m = self._get(d.get("id"), user, role)
            f = {k: d[k] for k in EDITABLE if k in d}
            return {"ok": True, "marker": self._dict(st.update(m.id, f, by=user), user, role)}
        if action == "delete":
            m = self._get(d.get("id"), user, role)
            st.delete(m.id)
            return {"ok": True}
        if action == "batch":
            return self._batch(user, role, d, address)
        if action == "group":
            ids = d.get("ids")
            if not isinstance(ids, list) or not ids or len(ids) > 2000:
                raise mk.MarkerError("Zaznacz znaczniki do zgrupowania.")
            marks = [self._get(i, user, role) for i in ids]
            n = st.set_group([m.id for m in marks], str(d.get("group", "")), by=user)
            return {"ok": True, "changed": n}
        if action == "rename_group":
            old = str(d.get("old", ""))
            mine = [m.id for m in st.search(group=old, visible_to=self._visible_to(user, role), limit=2000)
                    if self.can_edit(m, user, role)]
            return {"ok": True, "changed": st.rename_group(old, str(d.get("new", "")), by=user, only_ids=mine)}
        raise mk.MarkerError("Nieznana operacja na znacznikach.")


# ------------------------------------------------------------------------------------------------------ value search
def parse_conds(raw, names: list[str]) -> list[sr.Cond]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CONDS:
        raise ValueError(f"Podaj od 1 do {MAX_CONDS} warunków.")
    out = []
    for r in raw:
        if not isinstance(r, dict):
            raise ValueError("Niepoprawny warunek.")
        name, op = str(r.get("signal", "")), str(r.get("op", "=="))
        if name not in names:
            raise ValueError(f"Nie ma sygnału „{name}”.")
        if op not in sr.OPS:
            raise ValueError("Nieznany operator.")
        nums = []
        for k in ("a", "b", "tol"):
            try:
                x = float(r.get(k) or 0)
            except (TypeError, ValueError):
                raise ValueError("Wartości warunku muszą być liczbami.") from None
            if not math.isfinite(x):
                raise ValueError("Wartości warunku muszą być liczbami.")
            nums.append(x)
        out.append(sr.Cond(names.index(name), op, nums[0], nums[1], max(nums[2], 0.0)))
    return out


def hit_dict(h: sr.Hit, start_us: float, absolute: bool) -> dict:
    """A hit for the browser: times in seconds from `start_us` and in absolute µs. absolute = the hit holds µs since the epoch
    (a database search), otherwise seconds from `start_us` (the samples of a live connection)."""
    t0, t1 = ((h.t0 - start_us) / 1e6, (h.t1 - start_us) / 1e6) if absolute else (h.t0, h.t1)
    return {"t0": t0, "t1": t1, "t0_us": int(start_us + t0 * 1e6), "t1_us": int(start_us + t1 * 1e6),
            "duration": max(t1 - t0, 0.0), "values": [None if x != x else x for x in h.values],
            "vmin": None if h.vmin != h.vmin else h.vmin, "vmax": None if h.vmax != h.vmax else h.vmax}


def search_connection(host, d: dict) -> dict:
    """Search in the samples a hosted connection holds in memory."""
    names = [s.name for s in host.signals] or [s.name for s in host.cfg.signals if s.enabled]
    conds = parse_conds(d.get("conds"), names)
    t, v = host.buffer.snapshot() if len(host.buffer) else (np.zeros(0), np.zeros((0, len(names))))
    if v.ndim == 2 and v.shape[1] < len(names):
        raise ValueError("Połączenie nie ma jeszcze danych.")
    start_us = host.start_wall.timestamp() * 1e6
    lo = float(d["from"]) if d.get("from") not in (None, "") else None
    hi = float(d["to"]) if d.get("to") not in (None, "") else None
    if len(t):
        m = np.ones(len(t), dtype=bool)
        if lo is not None:
            m &= t >= lo
        if hi is not None:
            m &= t <= hi
        t, v = t[m], v[m]
    hits = sr.find_hits(t, v, conds, min_duration=max(float(d.get("min_duration") or 0), 0.0))
    return {"hits": [hit_dict(h, start_us, False) for h in hits], "names": [names[c.signal] for c in conds],
            "start_us": int(start_us), "truncated": len(hits) >= sr.MAX_HITS, "samples": int(len(t))}
