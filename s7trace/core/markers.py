"""Markers (bookmarks) on the chart: a titled, described and coloured point in time that can be found again later.

Qt-free; used by the desktop program (one file per Windows account) and by the web server (one file for all accounts, every
marker carries its author). A marker is tied to an absolute time (microseconds since the epoch), so the same marker fits the
live chart, a recording read from a database and an imported CSV.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field

PRIORITIES = {0: "Niski", 1: "Normalny", 2: "Wysoki", 3: "Krytyczny"}
DEFAULT_PRIORITY = 1
DEFAULT_COLOR = "#ff9f1c"
PALETTE = {                                   # name -> colour: what the colour picker offers first
    "Pomarańczowy": "#ff9f1c", "Czerwony": "#ff4d4d", "Zielony": "#3fc380", "Niebieski": "#4aa3ff",
    "Fioletowy": "#b07cff", "Żółty": "#ffd24a", "Turkusowy": "#2ec4b6", "Biały": "#ffffff",
}
KINDS = {"point": "Punkt", "range": "Zakres czasu", "delta": "Różnica sygnału"}
SPAN_KINDS = ("range", "delta")                # kinds that cover a time span (at_us .. end_us)
LINE_STYLES = {"solid": "ciągła", "dash": "kreskowana", "dot": "kropkowana", "dashdot": "kreska-kropka"}
DEFAULT_OPACITY = 24                           # [%] of the area of a range marker
MAX_WIDTH = 8
MAX_SIGNALS = 200
LIMITS = {"group_name": 120, "title": 200, "description": 4000, "notes": 8000, "conn": 200, "rec_id": 80, "author": 120, "computer": 120}
COLS = ("id", "kind", "at_us", "end_us", "signals", "group_name", "line_width", "line_style", "opacity", "show_label", "title", "description", "notes", "color", "priority", "created_us",
        "modified_us", "author", "modified_by", "computer", "conn", "rec_id")


class MarkerError(ValueError):
    """A marker field is not acceptable (the message is meant for the user)."""


def now_us() -> int:
    return int(time.time() * 1e6)


def valid_color(c) -> bool:
    if not isinstance(c, str) or len(c) != 7 or c[0] != "#":
        return False
    try:
        int(c[1:], 16)
    except ValueError:
        return False
    return True


@dataclass
class Marker:
    id: int = 0
    kind: str = "point"            # "point" (one moment) / "range" (from at_us to end_us: a translucent area on the chart) /
                                   # "delta" (two moments of ONE signal: shows the difference of its values)
    at_us: int = 0                 # the point in time the marker sits at (start of a range)
    end_us: int = 0                # end of a range (0 for a point)
    signals: list = field(default_factory=list)   # names of the signals (plots) it refers to; empty = all of them
    group_name: str = ""           # markers with the same group name belong together (e.g. one event); empty = no group
    line_width: int = 0            # width of the line [px]; 0 = by priority (1 / 2 / 3 / 4)
    line_style: str = "solid"      # one of LINE_STYLES
    opacity: int = DEFAULT_OPACITY # [%] 0..100: how much the area of a range marker covers the chart
    show_label: int = 1            # 1 = the title is written next to the marker on the chart, 0 = hidden
    title: str = ""
    description: str = ""
    notes: str = ""                # 'Uwagi'
    color: str = DEFAULT_COLOR
    priority: int = DEFAULT_PRIORITY
    created_us: int = 0
    modified_us: int = 0
    author: str = ""               # who created it (Windows / web account)
    modified_by: str = ""          # who changed it last
    computer: str = ""
    conn: str = ""                 # the connection / tab the marker was set on (a filter, not a key)
    rec_id: str = ""               # the recording it was set in (empty = live data)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_row(cls, row) -> "Marker":
        d = dict(zip(COLS, row))
        try:
            d["signals"] = [str(x) for x in json.loads(d["signals"] or "[]")]
        except (TypeError, ValueError):
            d["signals"] = []
        return cls(**d)

    def width_px(self) -> int:
        return self.line_width or {0: 1, 1: 2, 2: 3, 3: 4}.get(self.priority, 2)

    @property
    def last_us(self) -> int:
        """The latest moment the marker covers."""
        return self.end_us if self.kind in SPAN_KINDS and self.end_us > self.at_us else self.at_us

    def applies_to(self, name: str) -> bool:
        return not self.signals or name in self.signals

    def blurb(self) -> str:
        return self.title or "(bez tytułu)"


def clean_fields(d: dict, partial: bool) -> dict:
    """Validated, trimmed values of the user-editable fields found in d (partial = only those present)."""
    out: dict = {}
    for k in ("title", "description", "notes", "conn", "rec_id", "group_name"):
        if k in d:
            v = d[k]
            if v is None:
                v = ""
            if not isinstance(v, str):
                raise MarkerError(f"Pole „{k}” musi być tekstem.")
            v = v.strip() if k in ("title", "conn", "rec_id", "group_name") else v.strip("\r\n ")
            if len(v) > LIMITS[k]:
                raise MarkerError(f"Pole „{k}” jest za długie (maks. {LIMITS[k]} znaków).")
            out[k] = v
    if "color" in d:
        c = (d["color"] or "").strip().lower() if isinstance(d["color"], str) else ""
        if not valid_color(c):
            raise MarkerError("Kolor musi mieć postać #rrggbb.")
        out["color"] = c
    if "priority" in d:
        try:
            p = int(d["priority"])
        except (TypeError, ValueError):
            raise MarkerError("Priorytet musi być liczbą 0–3.") from None
        if p not in PRIORITIES:
            raise MarkerError("Priorytet musi być liczbą 0–3.")
        out["priority"] = p
    if "at_us" in d:
        try:
            a = int(d["at_us"])
        except (TypeError, ValueError):
            raise MarkerError("Czas znacznika jest niepoprawny.") from None
        if not (946_684_800_000_000 <= a < 4_102_444_800_000_000):          # after 2000, before 2100
            raise MarkerError("Czas znacznika jest poza zakresem 2000–2100.")
        out["at_us"] = a
    if "line_width" in d:
        try:
            w = int(d["line_width"] or 0)
        except (TypeError, ValueError):
            raise MarkerError("Grubość linii musi być liczbą 0–8 (0 = wg priorytetu).") from None
        if not 0 <= w <= MAX_WIDTH:
            raise MarkerError("Grubość linii musi być liczbą 0–8 (0 = wg priorytetu).")
        out["line_width"] = w
    if "show_label" in d:
        if not isinstance(d["show_label"], (bool, int)) or d["show_label"] not in (0, 1, True, False):
            raise MarkerError("Pokazywanie nazwy: tak albo nie.")
        out["show_label"] = int(bool(d["show_label"]))
    if "line_style" in d:
        if d["line_style"] not in LINE_STYLES:
            raise MarkerError("Rodzaj linii: ciągła, kreskowana, kropkowana albo kreska-kropka.")
        out["line_style"] = d["line_style"]
    if "opacity" in d:
        try:
            o = int(d["opacity"])
        except (TypeError, ValueError):
            raise MarkerError("Przezroczystość musi być liczbą 0–100 (%).") from None
        if not 0 <= o <= 100:
            raise MarkerError("Przezroczystość musi być liczbą 0–100 (%).")
        out["opacity"] = o
    if "end_us" in d:
        try:
            e = int(d["end_us"] or 0)
        except (TypeError, ValueError):
            raise MarkerError("Czas końca zakresu jest niepoprawny.") from None
        if e and not (946_684_800_000_000 <= e < 4_102_444_800_000_000):
            raise MarkerError("Czas końca zakresu jest poza zakresem 2000–2100.")
        out["end_us"] = e
    if "kind" in d:
        if d["kind"] not in KINDS:
            raise MarkerError("Typ znacznika: punkt, zakres czasu albo różnica sygnału.")
        out["kind"] = d["kind"]
    if "signals" in d:
        sg = d["signals"]
        if sg is None:
            sg = []
        if not isinstance(sg, (list, tuple)) or not all(isinstance(x, str) for x in sg):
            raise MarkerError("Lista przebiegów musi być listą nazw.")
        if len(sg) > MAX_SIGNALS or any(len(x) > 64 for x in sg):
            raise MarkerError("Za dużo przebiegów albo za długa nazwa przebiegu.")
        out["signals"] = list(dict.fromkeys(x.strip() for x in sg if x.strip()))
    if not partial and "at_us" not in out:
        raise MarkerError("Brak czasu znacznika.")
    return out


def _fix_range(f: dict, cur: "Marker | None" = None) -> dict:
    """Consistency of kind / at_us / end_us after a change: a point has no end, a range has start < end (swapped when needed)."""
    kind = f.get("kind", cur.kind if cur else "point")
    at = f.get("at_us", cur.at_us if cur else 0)
    end = f.get("end_us", cur.end_us if cur else 0)
    if kind == "point":
        end = 0
    else:
        if not end or end == at:
            raise MarkerError("Zakres czasu wymaga dwóch różnych momentów (od / do)." if kind == "range"
                              else "Różnica sygnału wymaga dwóch różnych momentów (od / do).")
        if end < at:
            at, end = end, at
        if kind == "delta":
            sig = f.get("signals", cur.signals if cur else [])
            if len(sig) != 1:
                raise MarkerError("Różnica sygnału dotyczy dokładnie jednego przebiegu – wskaż go na liście „Wybrane przebiegi”.")
    f.update(kind=kind, at_us=at, end_us=end)
    return f


def build_marker(at_us: int, author: str = "", computer: str = "", **fields) -> "Marker":
    """A validated new marker (id 0): fields as in clean_fields; created / modified now, author and computer stamped."""
    f = _fix_range(clean_fields({"at_us": at_us, **fields}, partial=False))
    now = now_us()
    return Marker(kind=f["kind"], at_us=f["at_us"], end_us=f["end_us"], signals=f.get("signals", []),
                  group_name=f.get("group_name", ""), line_width=f.get("line_width", 0), line_style=f.get("line_style", "solid"),
                  opacity=f.get("opacity", DEFAULT_OPACITY), show_label=f.get("show_label", 1), title=f.get("title", ""), description=f.get("description", ""),
                  notes=f.get("notes", ""), color=f.get("color", DEFAULT_COLOR), priority=f.get("priority", DEFAULT_PRIORITY),
                  created_us=now, modified_us=now, author=author[:LIMITS["author"]], modified_by=author[:LIMITS["author"]],
                  computer=computer[:LIMITS["computer"]], conn=f.get("conn", ""), rec_id=f.get("rec_id", ""))


def matches(m: "Marker", text: str = "", t0_us=None, t1_us=None, colors=None, min_priority=None, priorities=None, conn=None,
            rec_id=None, authors=None, created_from=None, created_to=None, visible_to=None, group=None) -> bool:
    """The same selection as MarkerStore.search, for a marker held in memory (used to merge unsaved changes into a result)."""
    if t0_us is not None and m.last_us < t0_us:
        return False
    if t1_us is not None and m.at_us > t1_us:
        return False
    if created_from is not None and m.created_us < created_from:
        return False
    if created_to is not None and m.created_us > created_to:
        return False
    if min_priority is not None and m.priority < min_priority:
        return False
    if colors and m.color.lower() not in [c.lower() for c in colors]:
        return False
    if priorities and m.priority not in priorities:
        return False
    if authors and m.author not in authors:
        return False
    if visible_to is not None and not (m.author.casefold() == visible_to[0].casefold() or m.conn in visible_to[1]):
        return False
    if group is not None and m.group_name != group:
        return False
    if conn is not None and m.conn != conn:
        return False
    if rec_id is not None and m.rec_id != rec_id:
        return False
    hay = " ".join((m.title, m.description, m.notes, m.author, m.conn, " ".join(m.signals), m.group_name)).casefold()
    return all(w in hay for w in (text or "").casefold().split())


class MarkerStore:
    """SQLite file with the markers. Every call opens its own short connection, so it is safe from any thread and several
    programs (windows of one user, the web server) can share the file."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.version = 0                       # bumped by every change made through this object
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS markers (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL DEFAULT 'point',"
                       " at_us INTEGER NOT NULL, end_us INTEGER NOT NULL DEFAULT 0, signals TEXT NOT NULL DEFAULT '[]',"
                       " group_name TEXT NOT NULL DEFAULT '', line_width INTEGER NOT NULL DEFAULT 0,"
                       " line_style TEXT NOT NULL DEFAULT 'solid', opacity INTEGER NOT NULL DEFAULT 24, show_label INTEGER NOT NULL DEFAULT 1,"
                       " title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',"
                       " color TEXT NOT NULL DEFAULT '#ff9f1c', priority INTEGER NOT NULL DEFAULT 1,"
                       " created_us INTEGER NOT NULL, modified_us INTEGER NOT NULL, author TEXT NOT NULL DEFAULT '',"
                       " modified_by TEXT NOT NULL DEFAULT '', computer TEXT NOT NULL DEFAULT '',"
                       " conn TEXT NOT NULL DEFAULT '', rec_id TEXT NOT NULL DEFAULT '')")
            db.execute("CREATE INDEX IF NOT EXISTS markers_at ON markers(at_us)")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=5.0)
        db.create_function("cf", 1, lambda s: s.casefold() if isinstance(s, str) else "", deterministic=True)
        return _Conn(db)

    def data_version(self) -> int:
        """Changes when ANY program modified the file (size / modification time); cheap, for polling."""
        try:
            st = os.stat(self.path)
            return hash((st.st_mtime_ns, st.st_size))
        except OSError:
            return 0

    # ------------------------------------------------------------ writing
    @staticmethod
    def _insert(db, m: "Marker") -> int:
        cur = db.execute("INSERT INTO markers (kind,at_us,end_us,signals,group_name,line_width,line_style,opacity,show_label,title,description,notes,"
                         "color,priority,created_us,modified_us,author,modified_by,computer,conn,rec_id)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (m.kind, m.at_us, m.end_us, json.dumps(m.signals, ensure_ascii=False), m.group_name,
                          m.line_width, m.line_style, m.opacity, m.show_label, m.title, m.description, m.notes, m.color,
                          m.priority, m.created_us, m.modified_us, m.author, m.modified_by, m.computer, m.conn, m.rec_id))
        return cur.lastrowid

    @staticmethod
    def _update(db, marker_id: int, f: dict, by: str) -> bool:
        """f = validated fields (clean_fields); False when the marker does not exist."""
        row = db.execute(f"SELECT {','.join(COLS)} FROM markers WHERE id=?", (int(marker_id),)).fetchone()
        if row is None:
            return False
        if {"kind", "at_us", "end_us", "signals"} & set(f):
            f = _fix_range(f, Marker.from_row(row))
        f = dict(f)
        if "signals" in f:
            f["signals"] = json.dumps(f["signals"], ensure_ascii=False)
        f["modified_us"] = now_us()
        f["modified_by"] = by[:LIMITS["author"]]
        db.execute(f"UPDATE markers SET {','.join(f'{k}=?' for k in f)} WHERE id=?", (*f.values(), int(marker_id)))
        return True

    def add(self, at_us: int, author: str = "", computer: str = "", **fields) -> Marker:
        m = build_marker(at_us, author, computer, **fields)
        with self._lock, self._db() as db:
            m.id = self._insert(db, m)
            self.version += 1
        return m

    def update(self, marker_id: int, fields: dict, by: str = "") -> Marker:
        """Changes the given fields (title, description, notes, color, priority, at_us, ...) and stamps the modification
        time and the editor. Returns the new state; KeyError when the marker does not exist."""
        f = clean_fields(fields, partial=True)
        with self._lock, self._db() as db:
            if not self._update(db, marker_id, f, by):
                raise KeyError(marker_id)
            self.version += 1
        return self.get(marker_id)

    def delete(self, marker_id: int) -> bool:
        with self._lock, self._db() as db:
            n = db.execute("DELETE FROM markers WHERE id=?", (int(marker_id),)).rowcount
            self.version += 1
        return n > 0

    def apply(self, adds: list[dict], updates: list[tuple[int, dict]], deletes: list[int], by: str = "", computer: str = "") -> dict:
        """Many changes in ONE transaction (all or nothing): adds = [{at_us, ...fields}], updates = [(id, fields)], deletes = [id].
        Everything is validated first. Returns {"added": [new ids], "updated": n, "deleted": n, "missing": [ids not found]}."""
        built = [build_marker(a["at_us"], by, computer, **{k: v for k, v in a.items() if k != "at_us"}) for a in adds]
        cleaned = [(int(i), clean_fields(f, partial=True)) for i, f in updates]
        out = {"added": [], "updated": 0, "deleted": 0, "missing": []}
        with self._lock, self._db() as db:
            for m in built:
                out["added"].append(self._insert(db, m))
            for i, f in cleaned:
                if self._update(db, i, f, by):
                    out["updated"] += 1
                else:
                    out["missing"].append(i)
            for i in deletes:
                if db.execute("DELETE FROM markers WHERE id=?", (int(i),)).rowcount:
                    out["deleted"] += 1
                else:
                    out["missing"].append(int(i))
            self.version += 1
        return out

    # ------------------------------------------------------------ reading
    def get(self, marker_id: int) -> Marker | None:
        with self._db() as db:
            r = db.execute(f"SELECT {','.join(COLS)} FROM markers WHERE id=?", (int(marker_id),)).fetchone()
        return Marker.from_row(r) if r else None

    def search(self, text: str = "", t0_us: int | None = None, t1_us: int | None = None, colors=None,
               min_priority: int | None = None, priorities=None, conn: str | None = None, rec_id: str | None = None,
               authors=None, created_from: int | None = None, created_to: int | None = None,
               visible_to: tuple[str, list[str]] | None = None, group: str | None = None, order: str = "at", limit: int = 1000) -> list[Marker]:
        """Markers matching ALL given criteria. text = every word must occur in the title, description, notes, author,
        connection (case-insensitive, also for Polish letters); colors / priorities / authors = lists of allowed values;
        visible_to = (user, shared connections): only markers made by the user (case-insensitive) or set on one of the connections;
        order: 'at' (by time), 'modified' (newest change first), 'priority' (highest first)."""
        where, args = [], []
        if t0_us is not None:                      # a range marker counts when any part of it lies in [t0, t1]
            where.append("(CASE WHEN kind IN ('range','delta') AND end_us>at_us THEN end_us ELSE at_us END)>=?")
            args.append(int(t0_us))
        if t1_us is not None:
            where.append("at_us<=?")
            args.append(int(t1_us))
        if created_from is not None:
            where.append("created_us>=?")
            args.append(int(created_from))
        if created_to is not None:
            where.append("created_us<=?")
            args.append(int(created_to))
        if min_priority is not None:
            where.append("priority>=?")
            args.append(int(min_priority))
        for col, vals in (("color", colors), ("priority", priorities), ("author", authors)):
            if vals:
                vals = [v.lower() if col == "color" else v for v in vals]
                where.append(f"{col} IN ({','.join('?' * len(vals))})")
                args += list(vals)
        if visible_to is not None:
            user, conns = visible_to
            where.append("(cf(author)=?" + (f" OR conn IN ({','.join('?' * len(conns))})" if conns else "") + ")")
            args += [user.casefold(), *conns]
        if group is not None:                      # '' = markers that are in no group
            where.append("group_name=?")
            args.append(group)
        if conn is not None:
            where.append("conn=?")
            args.append(conn)
        if rec_id is not None:
            where.append("rec_id=?")
            args.append(rec_id)
        for w in (text or "").casefold().split():
            where.append("cf(title||' '||description||' '||notes||' '||author||' '||conn||' '||signals||' '||group_name) LIKE ? ESCAPE '\\'")
            args.append("%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        order_sql = {"at": "at_us, id", "modified": "modified_us DESC, id DESC",
                     "priority": "priority DESC, at_us, id"}.get(order, "at_us, id")
        sql = f"SELECT {','.join(COLS)} FROM markers"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order_sql} LIMIT ?"
        args.append(max(int(limit), 1))
        with self._db() as db:
            return [Marker.from_row(r) for r in db.execute(sql, args).fetchall()]

    def groups(self, visible_to: tuple[str, list[str]] | None = None) -> list[tuple[str, int]]:
        """(group name, number of markers) of the groups that exist, by name."""
        sql, args = "SELECT group_name, COUNT(*) FROM markers WHERE group_name<>''", []
        if visible_to is not None:
            user, conns = visible_to
            sql += " AND (cf(author)=?" + (f" OR conn IN ({','.join('?' * len(conns))})" if conns else "") + ")"
            args += [user.casefold(), *conns]
        with self._db() as db:
            return [(r[0], r[1]) for r in db.execute(sql + " GROUP BY group_name ORDER BY group_name COLLATE NOCASE", args)]

    def set_group(self, marker_ids: list[int], group: str, by: str = "") -> int:
        """Puts the markers into the group (empty name = takes them out of any group); returns how many were changed."""
        g = clean_fields({"group_name": group}, partial=True)["group_name"]
        n = 0
        with self._lock, self._db() as db:
            for mid in marker_ids:
                n += db.execute("UPDATE markers SET group_name=?, modified_us=?, modified_by=? WHERE id=?",
                                (g, now_us(), by[:LIMITS["author"]], int(mid))).rowcount
            self.version += 1
        return n

    def rename_group(self, old: str, new: str, by: str = "", only_ids: list[int] | None = None) -> int:
        """Renames a group (merging it into 'new' when that exists); only_ids limits it to those markers."""
        g = clean_fields({"group_name": new}, partial=True)["group_name"]
        with self._lock, self._db() as db:
            sql, args = "UPDATE markers SET group_name=?, modified_us=?, modified_by=? WHERE group_name=?", \
                [g, now_us(), by[:LIMITS["author"]], old]
            if only_ids is not None:
                sql += f" AND id IN ({','.join('?' * len(only_ids))})" if only_ids else " AND 0"
                args += [int(i) for i in only_ids]
            n = db.execute(sql, args).rowcount
            self.version += 1
        return n

    def count(self) -> int:
        with self._db() as db:
            return db.execute("SELECT COUNT(*) FROM markers").fetchone()[0]

    def authors(self) -> list[str]:
        with self._db() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT author FROM markers ORDER BY author") if r[0]]

    def conns(self) -> list[str]:
        with self._db() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT conn FROM markers ORDER BY conn") if r[0]]


class _Conn:
    """sqlite3 connection as a context manager that commits and closes (sqlite3's own only commits)."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, et, ev, tb):
        try:
            if et is None:
                self.db.commit()
        finally:
            self.db.close()
        return False


# --------------------------------------------------------------------------------------- the desktop program's store
def default_path() -> str:
    from .config import data_dir
    return os.path.join(data_dir(), "markers.db")


_STORES: dict[str, MarkerStore] = {}


def default_store() -> MarkerStore:
    """The markers of this Windows account (<Documents>\\S7Trace\\markers.db); one object per path."""
    p = default_path()
    st = _STORES.get(p)
    if st is None:
        st = _STORES[p] = MarkerStore(p)
    return st
