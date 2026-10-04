"""Unsaved marker changes.

A marker put on a chart (or edited / deleted there) is only a DRAFT until the user presses 'Zapisz znaczniki': the draft keeps
new, changed and deleted markers in memory on top of the saved ones (`MarkerStore`) and shows them together; `commit` writes
everything in one transaction. Qt-free; the desktop tab and its markers window use it, the browser keeps the same model in
JavaScript (web/static/markers.js) and sends one batch to the server.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from . import markers as mk

FIELD_LABELS = {"title": "tytuł", "description": "opis", "notes": "uwagi", "color": "kolor", "priority": "priorytet",
                "kind": "rodzaj", "at_us": "czas", "end_us": "czas", "signals": "przebiegi", "group_name": "grupa",
                "line_width": "grubość linii", "line_style": "rodzaj linii", "opacity": "przezroczystość",
                "show_label": "nazwa na wykresie"}
EDITABLE = tuple(FIELD_LABELS)                 # what a user can change (author, dates, connection, recording are not)
BIG = 1_000_000


@dataclass
class Change:
    state: str                                 # "new" / "edited" / "deleted"
    marker: mk.Marker                          # the marker as it will be saved (for 'deleted': as it is now)
    before: mk.Marker | None = None            # the saved version ('edited', 'deleted')
    fields: list = dataclasses.field(default_factory=list)      # 'edited': names of what changed, e.g. ['tytuł', 'czas']


def _changed(a: mk.Marker, b: mk.Marker) -> list[str]:
    """Editable fields of b that differ from a (internal names)."""
    return [f for f in EDITABLE if getattr(a, f) != getattr(b, f)]


class MarkerDraft:
    def __init__(self, store: mk.MarkerStore):
        self.store = store
        self.new: dict[int, mk.Marker] = {}          # temporary negative ids
        self.edited: dict[int, mk.Marker] = {}       # saved id -> the marker with the user's changes
        self.deleted: dict[int, mk.Marker] = {}      # saved id -> the saved marker
        self._orig: dict[int, mk.Marker] = {}        # saved id -> the saved marker an edit started from
        self._seq = 0
        self.version = 0                             # bumped by every change of the draft (cheap redraw check)

    # ---- state
    def count(self) -> int:
        return len(self.new) + len(self.edited) + len(self.deleted)

    def dirty(self) -> bool:
        return self.count() > 0

    def state(self, mid: int) -> str:
        if mid in self.new:
            return "new"
        if mid in self.deleted:
            return "deleted"
        return "edited" if mid in self.edited else ""

    def get(self, mid: int, with_deleted: bool = False) -> mk.Marker | None:
        if mid in self.new:
            return self.new[mid]
        if mid in self.deleted:
            return self.deleted[mid] if with_deleted else None
        if mid in self.edited:
            return self.edited[mid]
        return self.store.get(mid) if mid > 0 else None

    # ---- changing (nothing is written to the store)
    def add(self, at_us: int, author: str = "", computer: str = "", **fields) -> mk.Marker:
        m = mk.build_marker(at_us, author, computer, **fields)
        self._seq += 1
        m.id = -self._seq
        self.new[m.id] = m
        self.version += 1
        return m

    def update(self, mid: int, fields: dict, by: str = "") -> mk.Marker:
        """Changes fields of a saved or a new marker (KeyError when it does not exist). A change that restores the saved state
        removes the edit."""
        f = mk.clean_fields(fields, partial=True)
        cur = self.get(mid)
        if cur is None:
            raise KeyError(mid)
        merged = mk._fix_range(dict(f), cur) if {"kind", "at_us", "end_us"} & set(f) else dict(f)
        f = {**f, **{k: merged[k] for k in ("kind", "at_us", "end_us") if k in merged}}
        m = dataclasses.replace(cur, **f, modified_us=mk.now_us(), modified_by=by[:mk.LIMITS["author"]])
        if mid < 0:
            self.new[mid] = m
        else:
            base = self._orig.setdefault(mid, cur if mid not in self.edited else self._orig.get(mid, cur))
            if not _changed(base, m):
                self.edited.pop(mid, None)
                self._orig.pop(mid, None)
            else:
                self.edited[mid] = m
        self.version += 1
        return m

    def changed_fields(self, mid: int) -> set[str]:
        """Internal names of the fields of a saved marker that differ from the saved version (empty for new / untouched ones)."""
        m, base = self.edited.get(mid), self._orig.get(mid)
        return set(_changed(base, m)) if m is not None and base is not None else set()

    def delete(self, mid: int) -> bool:
        """A new marker disappears; a saved one is listed for deletion until the draft is saved. False = nothing to delete."""
        if mid in self.new:
            del self.new[mid]
        elif mid > 0 and mid not in self.deleted:
            saved = self._orig.get(mid) or self.store.get(mid)
            if saved is None:
                return False
            self.edited.pop(mid, None)
            self._orig.pop(mid, None)
            self.deleted[mid] = saved
        else:
            return False
        self.version += 1
        return True

    def revert(self, mid: int) -> None:
        """Takes back what was done with this marker in the draft (new -> gone, edited / deleted -> as saved)."""
        self.new.pop(mid, None)
        self.edited.pop(mid, None)
        self.deleted.pop(mid, None)
        self._orig.pop(mid, None)
        self.version += 1

    def discard(self) -> None:
        self.new.clear()
        self.edited.clear()
        self.deleted.clear()
        self._orig.clear()
        self.version += 1

    # ---- reading (saved markers + the draft)
    def search(self, with_deleted: bool = False, order: str = "at", limit: int = 1000, **crit) -> list[mk.Marker]:
        """Like MarkerStore.search, but with the unsaved changes applied: new markers are included, edited ones appear as
        edited, deleted ones are left out (with_deleted: kept, see state())."""
        res = {m.id: m for m in self.store.search(order="at", limit=BIG, **crit)}
        for mid in self.deleted:
            res.pop(mid, None)
        for mid, m in self.edited.items():
            if mk.matches(m, **crit):
                res[mid] = m
            else:
                res.pop(mid, None)
        for mid, m in self.new.items():
            if mk.matches(m, **crit):
                res[mid] = m
        if with_deleted:
            for mid, m in self.deleted.items():
                if mk.matches(m, **crit):
                    res[mid] = m
        key = {"modified": lambda m: (-m.modified_us, -m.id), "priority": lambda m: (-m.priority, m.at_us, m.id)}.get(
            order, lambda m: (m.at_us, m.id))
        return sorted(res.values(), key=key)[:max(int(limit), 1)]

    def groups(self, visible_to=None) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for m in self.search(visible_to=visible_to, limit=BIG):
            if m.group_name:
                counts[m.group_name] = counts.get(m.group_name, 0) + 1
        return sorted(counts.items(), key=lambda kv: kv[0].casefold())

    # ---- saving
    def changes(self) -> list[Change]:
        """What 'Zapisz znaczniki' is going to do: new markers, then edited (with the names of the changed fields), then deleted."""
        out = [Change("new", m) for m in sorted(self.new.values(), key=lambda m: (m.at_us, m.id))]
        for mid, m in sorted(self.edited.items(), key=lambda kv: (kv[1].at_us, kv[0])):
            base = self._orig[mid]
            labels = list(dict.fromkeys(FIELD_LABELS[f] for f in _changed(base, m)))
            out.append(Change("edited", m, base, labels))
        out += [Change("deleted", m, m) for _i, m in sorted(self.deleted.items(), key=lambda kv: (kv[1].at_us, kv[0]))]
        return out

    def commit(self, by: str = "", computer: str = "") -> dict:
        """Writes the whole draft in one transaction and empties it. Returns the report of MarkerStore.apply (+ 'new_ids':
        temporary id -> saved id). On an error nothing is written and the draft stays as it is."""
        adds = [{"at_us": m.at_us, "kind": m.kind, "end_us": m.end_us, "signals": m.signals, "group_name": m.group_name,
                 "line_width": m.line_width, "line_style": m.line_style, "opacity": m.opacity, "show_label": m.show_label, "title": m.title,
                 "description": m.description, "notes": m.notes, "color": m.color, "priority": m.priority, "conn": m.conn,
                 "rec_id": m.rec_id} for m in self.new.values()]
        updates = [(mid, {f: getattr(m, f) for f in _changed(self._orig[mid], m)}) for mid, m in self.edited.items()]
        rep = self.store.apply(adds, updates, list(self.deleted), by=by, computer=computer)
        rep["new_ids"] = dict(zip(self.new, rep["added"]))
        self.discard()
        return rep
