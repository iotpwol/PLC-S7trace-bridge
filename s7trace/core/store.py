"""Recording targets and readers for the REC button: CSV file, SQLite, InfluxDB 1.x / 2.x, TimescaleDB.

Model: a *session* = one REC run (start time, address, tab, signal definitions, mode). The recorded samples are
events (time, signal, value). Mode "changes" (default) stores a value only when it differs from the previous one
(plus the first value of every signal), mode "all" stores every sample. Reading rebuilds the step curves: in mode
"changes" every signal keeps its last value until the next event.

Writers run in their own thread (batched, with retries) so a slow database never delays the GUI or the PLC cycle.
Pure Python (no Qt). Optional libraries are imported lazily: `psycopg` (TimescaleDB); SQLite and the InfluxDB
HTTP APIs need nothing extra."""
from __future__ import annotations

import dataclasses
import getpass
import json
import math
import os
import platform
import queue
import re
import sqlite3
import threading
import time
import uuid
from base64 import b64encode
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from urllib import error as urlerror
from urllib import parse, request

import numpy as np

KINDS = ["csv", "sqlite", "influx1", "influx2", "timescale"]
KIND_LABEL = {"csv": "Plik CSV", "sqlite": "SQLite", "influx1": "InfluxDB 1.x", "influx2": "InfluxDB 2.x",
              "timescale": "TimescaleDB"}
MODES = ["changes", "all"]
TITLE_ASK = ["start", "during", "end", "off"]          # when the program asks for the name of a recording
TITLE_ASK_LABEL = {"start": "Na początku: pytanie, potem nagrywanie", "during": "W trakcie: nagrywanie rusza, pytanie obok",
                   "end": "Na końcu: pytanie przy zatrzymaniu REC", "off": "Nie pytaj"}
VIEW_SCOPES = ["mine", "all"]
MODE_LABEL = {"changes": "Tylko zmiany stanu", "all": "Każda próbka"}
MAX_READ_ROWS = 5_000_000


class StoreError(Exception):
    """A readable message for the user (connection refused, bad credentials, missing library ...)."""


class _TooBig(StoreError):
    """A query result above MAX_READ_ROWS (the caller may retry in slices)."""


@dataclass
class StoreConfig:
    kind: str = "csv"
    mode: str = "changes"                   # default: only changes of state
    sqlite_path: str = "s7trace.db"         # relative = in the user's S7Trace folder in Documents
    url: str = "http://localhost:8086"      # InfluxDB
    database: str = "s7trace"               # InfluxDB 1.x
    org: str = ""                           # InfluxDB 2.x
    bucket: str = "s7trace"                 # InfluxDB 2.x
    user: str = ""                          # InfluxDB 1.x
    password: str = ""
    token: str = ""                         # InfluxDB 2.x
    measurement: str = "s7trace"
    host: str = "localhost"                 # TimescaleDB (PostgreSQL)
    port: int = 5432
    pg_database: str = "s7trace"
    pg_user: str = "postgres"
    pg_password: str = ""
    pg_sslmode: str = "prefer"
    table: str = "s7_samples"
    remember: bool = False                  # keep passwords / tokens in the saved configuration
    # ---- time / reliability parameters (all editable in the database settings; see PARAMS)
    keyframe_min: float = 10.0              # mode "changes": full state of all signals every N minutes (0 = off)
    batch_s: float = 0.5                    # how often collected samples are sent to the database
    retry_max_s: float = 15.0               # longest pause between retries while the server is away
    test_timeout_s: float = 3.0             # connection test when REC is pressed
    http_timeout_s: float = 15.0            # one InfluxDB request / one PostgreSQL connect
    close_grace_s: float = 10.0             # on Stop: how long to keep delivering what is still queued
    queue_max: int = 300000                 # entries kept in memory when the server is far behind
    spool_mb: int = 500                     # disk buffer while the server is away (0 = off)
    rotate_mb: int = 0                      # SQLite: start a new file above this size (0 = never)
    rotate_daily: bool = False              # SQLite: a new file every day
    compress_days: int = 7                  # TimescaleDB: compress data older than this (0 = no compression)
    read_max_points: int = 200000           # reading: downsample above this many points per signal
    # ---- recordings: names, users, trash (all editable in the database settings, tab "Nagrania i użytkownicy")
    title_ask: str = "during"               # when to ask for the title: start / during / end / off
    trash_days: int = 30                    # deleted recordings stay in the trash this long (0 = delete at once)
    retention_days: int = 0                 # own recordings older than this go to the trash (0 = never)
    view_scope: str = "mine"                # the overview shows: mine / all recordings
    delete_others: bool = False             # allow deleting / editing recordings of other users
    sqlite_shared: bool = False             # relative SQLite path: shared folder (ProgramData) instead of the user's

    SECRETS = ("password", "token", "pg_password")
    NETWORK = ("influx1", "influx2", "timescale")

    def to_dict(self) -> dict:
        d = asdict(self)
        if not self.remember:
            for k in self.SECRETS:
                d[k] = ""
        return d

    @classmethod
    def from_dict(cls, d) -> "StoreConfig":
        c = cls()
        if isinstance(d, dict):
            for f in fields(cls):
                cur, val = getattr(c, f.name), d.get(f.name)
                if f.name not in d or isinstance(val, bool) != isinstance(cur, bool):
                    continue
                if isinstance(cur, (int, float)) and not isinstance(cur, bool) and isinstance(val, (int, float)):
                    val = type(cur)(val)                       # 3 -> 3.0 for the float parameters
                    if f.name in PARAMS:
                        lo, hi = PARAMS[f.name][1:3]
                        val = type(cur)(min(max(val, lo), hi))
                    setattr(c, f.name, val)
                elif isinstance(val, type(cur)):
                    setattr(c, f.name, val)
        if c.kind not in KINDS:
            c.kind = "csv"
        if c.mode not in MODES:
            c.mode = "changes"
        if c.title_ask not in TITLE_ASK:
            c.title_ask = "during"
        if c.view_scope not in VIEW_SCOPES:
            c.view_scope = "mine"
        return c

    def describe(self) -> str:
        k = self.kind
        if k == "sqlite":
            return f"SQLite {self.sqlite_path}"
        if k == "influx1":
            return f"InfluxDB 1.x {self.url} / {self.database}"
        if k == "influx2":
            return f"InfluxDB 2.x {self.url} / {self.bucket}"
        if k == "timescale":
            return f"TimescaleDB {self.host}:{self.port} / {self.pg_database}"
        return "CSV"


# ---------------------------------------------------------------------------------------------- helpers
# Time / reliability parameters: name -> (label, min, max, unit, description). One place for the limits, the dialog and the docs.
PARAMS = {
    "keyframe_min": ("Pełny stan co", 0, 1440, "min",
                     "Tylko w trybie „tylko zmiany”: co tyle minut zapisywany jest aktualny stan WSZYSTKICH sygnałów, "
                     "nawet jeśli nic się nie zmieniło. Dzięki temu odczyt zakresu czasu (np. godziny 14–15) zaczyna się od "
                     "pełnego stanu i działa szybko, a przerwa w zapisie (np. awaria komputera) różni się od „nic się nie "
                     "zmieniało”. Mniejsza wartość = więcej danych, ale krótsze zapytania. 0 = wyłączone."),
    "batch_s": ("Wysyłka paczek co", 0.05, 60, "s",
                "Co ile sekund zebrane próbki są wysyłane do bazy jedną paczką. Mniej = świeższe dane w bazie, więcej "
                "zapytań; więcej = wydajniej przy bardzo wielu sygnałach."),
    "retry_max_s": ("Najdłuższa przerwa między próbami", 1, 600, "s",
                    "Gdy serwer nie odpowiada, program ponawia wysyłkę z coraz dłuższą przerwą (1 s, 2 s, 4 s…) – to jest "
                    "górna granica tej przerwy. Dane w tym czasie czekają w kolejce."),
    "test_timeout_s": ("Limit testu połączenia (REC)", 0.5, 60, "s",
                       "Po naciśnięciu REC program sprawdza w tle, czy baza odpowiada. Tyle sekund czeka na odpowiedź, zanim "
                       "wyświetli komunikat z przyczyną. Nagrywanie rusza od razu – dane czekają w kolejce."),
    "http_timeout_s": ("Limit odpowiedzi serwera", 1, 300, "s",
                       "Jak długo program czeka na odpowiedź serwera przy zapisie i odczycie (jedno zapytanie HTTP "
                       "InfluxDB / jedno łączenie z PostgreSQL). Dla wolnych łączy (VPN) warto zwiększyć."),
    "close_grace_s": ("Dosyłanie po zatrzymaniu REC", 0, 600, "s",
                      "Po Stop program przez tyle sekund próbuje jeszcze dostarczyć dane z kolejki. Po tym czasie "
                      "porzuca to, co się nie wysłało (jeśli włączono bufor na dysku – dane zostają w buforze)."),
    "queue_max": ("Kolejka w pamięci", 1000, 50_000_000, "wpisów",
                  "Ile zmian może czekać w pamięci, gdy serwer jest niedostępny. Po przekroczeniu najstarsze są tracone "
                  "(chyba że włączony jest bufor na dysku)."),
    "spool_mb": ("Bufor na dysku – limit", 0, 100_000, "MB",
                 "Gdy serwer jest niedostępny, dane trafiają do lokalnego pliku (kolejka na dysku) i są dosyłane po "
                 "powrocie serwera – także po ponownym uruchomieniu programu. 0 = bufor wyłączony (tylko pamięć). "
                 "Po przekroczeniu limitu najstarsze dane są tracone."),
    "rotate_mb": ("SQLite: nowy plik po", 0, 1_000_000, "MB",
                  "Tylko SQLite: gdy plik bazy przekroczy ten rozmiar, kolejne nagrania trafiają do nowego pliku "
                  "(nazwa_2.db, nazwa_3.db…). 0 = bez limitu rozmiaru."),
    "compress_days": ("Kompresja danych starszych niż", 0, 3650, "dni",
                      "Tylko TimescaleDB (z rozszerzeniem timescaledb): dane starsze niż tyle dni są kompresowane przez serwer "
                      "(zwykle kilka razy mniej miejsca). Skompresowanych nagrań nie da się usunąć w starszych wersjach TimescaleDB "
                      "(poniżej 2.11), a w nowszych usuwanie jest wolniejsze. 0 = bez kompresji: najprostsze usuwanie, ale tabela "
                      "zajmuje pełny rozmiar. Zmiana działa od następnego połączenia z bazą; to, co już skompresowano, zostaje "
                      "skompresowane."),
    "trash_days": ("Kosz: przechowuj", 0, 3650, "dni",
                   "Usunięte nagranie trafia do kosza (jest ukryte, ale można je przywrócić) i po tylu dniach znika na stałe. "
                   "0 = bez kosza: usunięcie jest od razu trwałe."),
    "retention_days": ("Automatyczne czyszczenie: nagrania starsze niż", 0, 36500, "dni",
                       "Własne nagrania starsze niż tyle dni są przenoszone do kosza (przy otwarciu okna „Przegląd nagrań”). "
                       "0 = wyłączone."),
    "read_max_points": ("Odczyt: maks. punktów na sygnał", 1000, 50_000_000, "pkt",
                        "Przy wczytywaniu bardzo długiego zakresu program, jeśli danych jest więcej niż tyle, zmniejsza je "
                        "(dla każdego przedziału zachowuje wartość minimalną i maksymalną, więc szpilki nie znikają)."),
}


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME", "")


def shared_data_dir() -> str | None:
    """Folder for SQLite files shared by every Windows user of this computer (ProgramData/S7Trace/data, fallback
    Public/S7Trace/data); None when neither can be created."""
    for var in ("PROGRAMDATA", "PUBLIC"):
        base = os.environ.get(var)
        if not base:
            continue
        d = os.path.join(base, "S7Trace", "data")
        try:
            fresh = not os.path.isdir(d)
            os.makedirs(d, exist_ok=True)
            if fresh:
                from . import sessions as _s
                _s._grant_everyone(os.path.dirname(d))
                _s._grant_everyone(d)
            return d
        except OSError:
            continue
    return None


def effective_base(cfg: "StoreConfig", base_dir: str = "") -> str:
    """Folder a relative SQLite path is resolved against: the shared one (option) or the user's own."""
    if cfg.kind == "sqlite" and cfg.sqlite_shared:
        return shared_data_dir() or base_dir
    return base_dir


def norm_session(d: dict) -> dict:
    """Types and defaults of a session description, whatever the backend returned."""
    out = dict(d)

    def num(v, cast, default=None):
        try:
            return cast(float(v)) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default
    out["start_us"] = num(out.get("start_us"), int, 0)
    out["end_us"] = num(out.get("end_us"), int)
    dl = num(out.get("deleted_us"), int)
    out["deleted_us"] = dl if dl else None                     # 0 / empty = not deleted
    out["keyframe_min"] = num(out.get("keyframe_min"), float, 0.0)
    for k in ("name", "title", "notes", "tags", "owner", "computer", "ip", "tab", "conf", "mode"):
        v = out.get(k)
        out[k] = "" if v is None else str(v)
    return out


def new_session_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def unique_fields(names: list[str]) -> list[str]:
    """Field names of the signals: never empty, never duplicated (a second 'X' becomes 'X_2')."""
    out, seen = [], {}
    for i, n in enumerate(names):
        base = (n or "").strip() or f"SIG{i + 1}"
        k = seen.get(base, 0) + 1
        seen[base] = k
        out.append(base if k == 1 else f"{base}_{k}")
    return out


def to_us(start_wall: datetime, t: float) -> int:
    return int(round((start_wall.timestamp() + t) * 1e6))


class ChangeFilter:
    """Which signals changed since the previous sample (NaN equals NaN). The first sample reports all."""

    def __init__(self, n: int, mode: str):
        self.mode, self.n = mode, n
        self.prev: list[float] | None = None

    def changed(self, values, force: bool = False) -> list[int]:
        """`force` (keyframe) reports every signal even though nothing changed."""
        vals = list(values[: self.n]) + [math.nan] * max(self.n - len(values), 0)
        if self.mode == "all" or self.prev is None or force:
            self.prev = vals
            return list(range(self.n))
        out = [i for i, (a, b) in enumerate(zip(vals, self.prev)) if not (a == b or (a != a and b != b))]
        self.prev = vals
        return out


def events_to_matrix(n: int, events, hold: bool):
    """events: iterable of (t_us, signal_index, value). Returns (t_us array, matrix [rows, n]); with `hold` every
    signal keeps its last event value until its next event (mode 'changes'), otherwise gaps stay NaN."""
    ev = list(events)
    if not ev:
        return np.zeros(0, dtype=np.int64), np.zeros((0, n))
    ts = np.fromiter((e[0] for e in ev), dtype=np.int64, count=len(ev))
    sg = np.fromiter((e[1] for e in ev), dtype=np.int64, count=len(ev))
    vl = np.fromiter((math.nan if e[2] is None else e[2] for e in ev), dtype=float, count=len(ev))
    uniq, row = np.unique(ts, return_inverse=True)
    mat = np.full((len(uniq), n), np.nan)
    has = np.zeros((len(uniq), n), dtype=bool)
    ok = (sg >= 0) & (sg < n)
    mat[row[ok], sg[ok]] = vl[ok]
    has[row[ok], sg[ok]] = True
    if hold:
        pos = np.arange(len(uniq))[:, None]
        last = np.maximum.accumulate(np.where(has, pos, -1), axis=0)
        cols = np.arange(n)[None, :]
        mat = np.where(last >= 0, mat[np.maximum(last, 0), cols], np.nan)
    return uniq, mat


def downsample_minmax(t: np.ndarray, v: np.ndarray, max_points: int):
    """Keeps about `max_points` rows of a long recording: for every part of the time axis the rows holding each signal's
    minimum and maximum (peaks do not vanish), the first and last row, and the rows where a signal becomes unreadable
    (NaN gap) or readable again."""
    n = len(t)
    if max_points <= 0 or n <= max_points:
        return t, v
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    nan = np.isnan(v)
    keep[1:] |= np.any(nan[1:] != nan[:-1], axis=1)
    edges = np.linspace(0, n, max(max_points // 2, 1) + 1).astype(np.int64)
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = v[a:b]
        ok = ~np.all(nan[a:b], axis=0)
        if ok.any():
            seg = seg[:, ok]
            keep[a + np.nanargmin(seg, axis=0)] = True
            keep[a + np.nanargmax(seg, axis=0)] = True
    return t[keep], v[keep]


def rotated_sqlite_path(cfg: "StoreConfig", base_dir: str = "", now: datetime | None = None) -> str:
    """The SQLite file a new recording goes to: the configured file, with the date added (rotate_daily) and/or a counter
    (_2, _3 … once a file is larger than rotate_mb). Without rotation it is simply the configured file."""
    p = cfg.sqlite_path or "s7trace.db"
    p = p if os.path.isabs(p) else os.path.join(effective_base(cfg, base_dir), p)
    stem, ext = os.path.splitext(p)
    if cfg.rotate_daily:
        stem += (now or datetime.now()).strftime("_%Y-%m-%d")
    if cfg.rotate_mb > 0:
        limit, k = cfg.rotate_mb * 1_000_000, 1
        while True:
            cand = stem + ext if k == 1 else f"{stem}_{k}{ext}"
            if not os.path.exists(cand) or os.path.getsize(cand) < limit:
                return cand
            k += 1
    return stem + ext


def sqlite_family(path: str) -> list[str]:
    """The configured SQLite file together with its rotated siblings (name_YYYY-MM-DD.db, name_2.db …)."""
    stem, ext = os.path.splitext(path)
    folder, base = os.path.split(stem)
    rx = re.compile(rf"^{re.escape(base)}(_\d{{4}}-\d\d-\d\d)?(_\d+)?{re.escape(ext)}$")
    try:
        names = [n for n in os.listdir(folder or ".") if rx.match(n)]
    except OSError:
        return [path]
    out = sorted(os.path.join(folder, n) for n in names)
    return out or [path]


def rfc3339_to_us(text: str) -> int:
    """'2026-10-03T10:15:00.123456789Z' (any number of fraction digits, optional zone) -> epoch microseconds."""
    m = re.match(r"(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:\.(\d+))?\s*(Z|[+-]\d\d:?\d\d)?$", str(text).strip())
    if not m:
        raise ValueError(f"bad time: {text}")
    d, t, frac, zone = m.groups()
    dt = datetime.fromisoformat(f"{d}T{t}+00:00" if zone in (None, "Z") else f"{d}T{t}{zone}")
    return int(dt.timestamp()) * 1_000_000 + int((frac or "0").ljust(6, "0")[:6])


def us_to_rfc3339(us: int) -> str:
    sec, frac = divmod(int(us), 1_000_000)
    return datetime.fromtimestamp(sec, tz=__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{frac:06d}Z"


# ---------------------------------------------------------------------------------------------- backends
class Backend:
    """begin() creates a session, write() stores a batch [(t_us, {signal_index: value})], end() closes it.
    sessions() lists the stored sessions, read() returns (meta, t_us, matrix) of one of them."""

    def begin(self, meta: dict) -> str: ...
    def write(self, rows: list) -> None: ...
    def end(self, end_us: int) -> None: ...
    def close(self) -> None: ...
    def sessions(self) -> list[dict]: ...
    def read(self, session_id: str, t0_us: int | None = None, t1_us: int | None = None, max_points: int = 0): ...
    def ping(self) -> str: ...


    def update_session(self, session_id: str, fields: dict) -> None:
        """Changes title / notes / tags / deleted_us / end_us of a stored recording."""
        raise NotImplementedError

    def delete_session(self, session_id: str) -> None:
        """Removes the recording (its data and its description) for good."""
        raise NotImplementedError

    def stats(self) -> dict:
        """{session id: number of stored entries}; backends that cannot tell cheaply return {}."""
        return {}


def _td(rows):
    """(time, {signal: value}, is_keyframe) of every row; a row is (t, d) or (t, d, True) for a keyframe."""
    for r in rows:
        yield r[0], r[1], len(r) > 2 and bool(r[2])


SESSION_COLS = ("id", "name", "start_us", "end_us", "ip", "tab", "conf", "mode", "signals", "fields",
                "title", "notes", "tags", "owner", "computer", "keyframe_min", "deleted_us")
EXTRA_COLS = {"title": "TEXT", "notes": "TEXT", "tags": "TEXT", "owner": "TEXT", "computer": "TEXT",
              "keyframe_min": "REAL", "deleted_us": "INTEGER"}
EDITABLE = ("title", "notes", "tags", "deleted_us", "end_us")


def _meta_json(meta: dict) -> dict:
    return {**meta, "signals": json.dumps(meta.get("signals", []), ensure_ascii=False),
            "fields": json.dumps(meta.get("fields", []), ensure_ascii=False)}


def _meta_back(d: dict) -> dict:
    out = dict(d)
    for k in ("signals", "fields"):
        v = out.get(k)
        if isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except ValueError:
                out[k] = []
    return out


class SqliteBackend(Backend):
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(
                id TEXT PRIMARY KEY, name TEXT, start_us INTEGER, end_us INTEGER, ip TEXT, tab TEXT, conf TEXT,
                mode TEXT, signals TEXT, fields TEXT);
            CREATE TABLE IF NOT EXISTS samples(
                session TEXT NOT NULL, sig INTEGER NOT NULL, ts_us INTEGER NOT NULL, value REAL,
                PRIMARY KEY(session, sig, ts_us)) WITHOUT ROWID;""")
        have = {r[1] for r in self.db.execute("PRAGMA table_info(sessions)")}
        for col, typ in EXTRA_COLS.items():                        # files written by an older version get the new columns
            if col not in have:
                self.db.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typ}")
        self.db.commit()
        self.sid = ""

    def begin(self, meta):
        self.sid = meta.get("id") or new_session_id()
        m = _meta_json(meta)
        self.db.execute("INSERT OR REPLACE INTO sessions(id,name,start_us,end_us,ip,tab,conf,mode,signals,fields,"
                        "title,notes,tags,owner,computer,keyframe_min,deleted_us) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (self.sid, m.get("name", ""), m["start_us"], None, m.get("ip", ""), m.get("tab", ""),
                         m.get("conf", ""), m.get("mode", "changes"), m["signals"], m["fields"], m.get("title", ""),
                         m.get("notes", ""), m.get("tags", ""), m.get("owner", ""), m.get("computer", ""),
                         m.get("keyframe_min", 0.0), None))
        self.db.commit()
        return self.sid

    def update_session(self, session_id, fields):
        sets = {k: v for k, v in fields.items() if k in EDITABLE}
        if sets:
            self.db.execute(f"UPDATE sessions SET {','.join(k + '=?' for k in sets)} WHERE id=?",
                            (*sets.values(), session_id))
            self.db.commit()

    def delete_session(self, session_id):
        self.db.execute("DELETE FROM samples WHERE session=?", (session_id,))
        self.db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        self.db.commit()
        try:                                                       # give the space back to the file system
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.execute("VACUUM")
        except sqlite3.Error:
            pass

    def stats(self):
        return dict(self.db.execute("SELECT session, COUNT(*) FROM samples GROUP BY session").fetchall())

    def write(self, rows):
        data = [(self.sid, i, t, None if (v != v) else float(v)) for t, d, _k in _td(rows) for i, v in d.items()]
        self.db.executemany("INSERT OR REPLACE INTO samples(session,sig,ts_us,value) VALUES(?,?,?,?)", data)
        self.db.commit()

    def end(self, end_us):
        self.db.execute("UPDATE sessions SET end_us=? WHERE id=?", (end_us, self.sid))
        self.db.commit()

    def close(self):
        try:
            self.db.close()
        except sqlite3.Error:
            pass

    def sessions(self):
        cur = self.db.execute(f"SELECT {','.join(SESSION_COLS)} FROM sessions ORDER BY start_us DESC")
        return [norm_session(_meta_back(dict(zip(SESSION_COLS, r)))) for r in cur.fetchall()]

    def read(self, session_id, t0_us=None, t1_us=None, max_points=0):
        meta = next((s for s in self.sessions() if s["id"] == session_id), None)
        if meta is None:
            raise StoreError("Nie znaleziono nagrania w bazie.")
        n = len(meta["signals"])
        lo = t0_us if t0_us is not None else -(1 << 62)
        hi = t1_us if t1_us is not None else (1 << 62)
        events = []
        big = self.db.execute("SELECT COUNT(*) FROM (SELECT 1 FROM samples WHERE session=? AND ts_us>=? AND ts_us<=? LIMIT ?)",
                              (session_id, lo, hi, MAX_READ_ROWS + 1)).fetchone()[0] > MAX_READ_ROWS
        if big and max_points > 0:                                # too much for memory: min / max of every time slice, in SQL
            a = t0_us if t0_us is not None else int(meta["start_us"])
            b = t1_us if t1_us is not None else meta.get("end_us")
            if b is None:                                        # a recording that was never closed properly
                b = self.db.execute("SELECT MAX(ts_us) FROM samples WHERE session=?", (session_id,)).fetchone()[0] or a
            w = max((b - a) // max(max_points // 2, 1) + 1, 1)
            if t0_us is not None and meta["mode"] == "changes":
                events += self._carry(session_id, lo, t0_us)
            for sig, k, vmin, vmax in self.db.execute(
                    "SELECT sig, (ts_us-?)/? AS k, MIN(value), MAX(value) FROM samples WHERE session=? AND ts_us>=? AND ts_us<=?"
                    " GROUP BY sig, k", (a, w, session_id, lo, hi)):
                events.append((a + k * w, sig, vmin))
                if vmax is not None and vmax != vmin:
                    events.append((a + k * w + w // 2, sig, vmax))
            events.sort(key=lambda e: e[0])
            t, v = events_to_matrix(n, events, meta["mode"] == "changes")
            return meta, t, v
        if t0_us is not None and meta["mode"] == "changes":       # carry-in: the value each signal had at t0
            events += self._carry(session_id, lo, t0_us)
        cur = self.db.execute("SELECT ts_us, sig, value FROM samples WHERE session=? AND ts_us>=? AND ts_us<=?"
                              " ORDER BY ts_us LIMIT ?", (session_id, lo, hi, MAX_READ_ROWS + 1))
        events += cur.fetchall()
        if len(events) > MAX_READ_ROWS:
            raise StoreError(f"Za dużo danych do wczytania naraz (> {MAX_READ_ROWS:,} wpisów) – wybierz węższy zakres czasu.")
        t, v = events_to_matrix(n, events, meta["mode"] == "changes")
        return meta, t, v

    def _carry(self, session_id: str, lo: int, at: int) -> list:
        return [(at, s, v) for s, v in self.db.execute(
            "SELECT sig, value FROM samples WHERE session=? AND ts_us<? AND ts_us=("
            " SELECT MAX(ts_us) FROM samples s2 WHERE s2.session=samples.session AND s2.sig=samples.sig"
            " AND s2.ts_us<?)", (session_id, lo, lo))]

    def ping(self):
        return f"SQLite {sqlite3.sqlite_version}: {self.path}"


# ---- InfluxDB (HTTP API, line protocol)
def _esc_key(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def _esc_meas(s: str) -> str:
    return str(s).replace(",", "\\,").replace(" ", "\\ ")


def _esc_str(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def sample_line(measurement: str, session: str, fields: list[str], t_us: int, d: dict, ok: dict | None = None) -> str | None:
    """One line-protocol point. Line protocol has no NaN, so a missing value is left out and the availability of the
    signal is written as its own field `<name>__ok` (0 = not readable, 1 = readable again) when it changes."""
    vals = [f"{_esc_key(fields[i])}={float(v)!r}" for i, v in d.items() if v == v and 0 <= i < len(fields)]
    vals += [f"{_esc_key(fields[i] + QUALITY)}={float(o)!r}" for i, o in (ok or {}).items() if 0 <= i < len(fields)]
    if not vals:
        return None
    return f"{_esc_meas(measurement)},session={_esc_key(session)} {','.join(vals)} {t_us * 1000}"


def session_line(measurement: str, meta: dict) -> str:
    m = _meta_json(meta)
    f = [f"name={_esc_str(m.get('name', ''))}", f"start_us={int(m['start_us'])}i", f"ip={_esc_str(m.get('ip', ''))}",
         f"tab={_esc_str(m.get('tab', ''))}", f"conf={_esc_str(m.get('conf', ''))}", f"mode={_esc_str(m.get('mode', ''))}",
         f"signals={_esc_str(m['signals'])}", f"fields={_esc_str(m['fields'])}",
         f"title={_esc_str(m.get('title', ''))}", f"notes={_esc_str(m.get('notes', ''))}", f"tags={_esc_str(m.get('tags', ''))}",
         f"owner={_esc_str(m.get('owner', ''))}", f"computer={_esc_str(m.get('computer', ''))}",
         f"keyframe_min={float(m.get('keyframe_min') or 0.0)!r}", "deleted_us=0i"]
    return (f"{_esc_meas(measurement + '_sessions')},session={_esc_key(meta['id'])} {','.join(f)} "
            f"{int(m['start_us']) * 1000}")


def session_update_line(measurement: str, session: str, start_us: int, fields: dict) -> str:
    """Rewrites some fields of the session point (same series and time: InfluxDB merges the fields)."""
    f = []
    for k, v in fields.items():
        if k in ("title", "notes", "tags"):
            f.append(f"{k}={_esc_str(v or '')}")
        elif k in ("deleted_us", "end_us"):
            f.append(f"{k}={int(v or 0)}i")
    return f"{_esc_meas(measurement + '_sessions')},session={_esc_key(session)} {','.join(f)} {int(start_us) * 1000}"


QUALITY = "__ok"


class InfluxBackend(Backend):
    def __init__(self, cfg: StoreConfig, version: int, timeout: float | None = None):
        self.cfg, self.v, self.timeout = cfg, version, timeout or cfg.http_timeout_s
        self._valid: dict[int, bool] = {}                          # last known availability per signal
        self.base = cfg.url.rstrip("/")
        self.meas = cfg.measurement or "s7trace"
        self.sid, self.fields = "", []

    # -- transport
    def _headers(self, extra=None) -> dict:
        h = dict(extra or {})
        c = self.cfg
        if self.v == 2 and c.token:
            h["Authorization"] = f"Token {c.token}"
        elif self.v == 1 and c.user:
            h["Authorization"] = "Basic " + b64encode(f"{c.user}:{c.password}".encode()).decode()
        return h

    def _http(self, method: str, path: str, query: dict | None = None, body: bytes | None = None, headers=None) -> bytes:
        url = self.base + path + ("?" + parse.urlencode(query) if query else "")
        req = request.Request(url, data=body, method=method, headers=self._headers(headers))
        try:
            with request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except urlerror.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise StoreError(f"InfluxDB: HTTP {e.code} {e.reason}. {detail}") from None
        except (urlerror.URLError, OSError) as e:
            raise StoreError(f"InfluxDB: brak połączenia z {self.base} ({getattr(e, 'reason', e)})") from None

    def _write_lp(self, lines: list[str]) -> None:
        c = self.cfg
        for i in range(0, len(lines), 5000):
            body = "\n".join(lines[i:i + 5000]).encode("utf-8")
            if self.v == 1:
                self._http("POST", "/write", {"db": c.database, "precision": "ns"}, body)
            else:
                self._http("POST", "/api/v2/write", {"org": c.org, "bucket": c.bucket, "precision": "ns"}, body)

    # -- write
    def begin(self, meta):
        self.sid = meta.get("id") or new_session_id()
        meta = {**meta, "id": self.sid}
        self.fields = meta.get("fields", [])
        self._start_us = int(meta["start_us"])
        if self.v == 1:
            try:
                self._http("POST", "/query", {"q": f'CREATE DATABASE "{self.cfg.database}"'})
            except StoreError:
                pass                                              # may lack the privilege: the database may exist
        self._write_lp([session_line(self.meas, meta)])
        return self.sid

    def write(self, rows):
        lines = []
        for t, d, key in _td(rows):
            ok = {}
            for i, v in d.items():
                valid = v == v
                if key or valid != self._valid.get(i, True):       # availability changed (or keyframe): `<name>__ok`
                    ok[i] = 1.0 if valid else 0.0
                self._valid[i] = valid
            ln = sample_line(self.meas, self.sid, self.fields, t, d, ok)
            if ln:
                lines.append(ln)
        if lines:
            self._write_lp(lines)

    def end(self, end_us):
        if self.sid and getattr(self, "_start_us", None):
            self._write_lp([session_update_line(self.meas, self.sid, self._start_us, {"end_us": end_us})])

    def close(self):
        pass

    def update_session(self, session_id, fields):
        meta = next((x for x in self.sessions() if x["id"] == session_id), None)
        if meta is None:
            raise StoreError("Nie znaleziono nagrania w bazie.")
        sets = {k: v for k, v in fields.items() if k in EDITABLE}
        if sets:
            self._write_lp([session_update_line(self.meas, session_id, meta["start_us"], sets)])

    def delete_session(self, session_id):
        c, sid = self.cfg, session_id.replace("'", "").replace('"', "")
        for m in (self.meas, self.meas + "_sessions"):
            if self.v == 1:
                self._http("POST", "/query", {"db": c.database, "q": f'DROP SERIES FROM "{m}" WHERE "session"=\'{sid}\''})
            else:
                body = json.dumps({"start": "1970-01-01T00:00:00Z", "stop": "2200-01-01T00:00:00Z",
                                   "predicate": f'_measurement="{m}" AND session="{sid}"'}).encode()
                self._http("POST", "/api/v2/delete", {"org": c.org, "bucket": c.bucket}, body,
                           {"Content-Type": "application/json"})

    # -- read
    def _query(self, v1: str, flux: str):
        c = self.cfg
        if self.v == 1:
            raw = self._http("GET", "/query", {"db": c.database, "q": v1, "epoch": "ns"})
            return json.loads(raw)
        body = json.dumps({"query": flux, "type": "flux"}).encode()
        raw = self._http("POST", "/api/v2/query", {"org": c.org}, body,
                         {"Content-Type": "application/json", "Accept": "application/csv"})
        return parse_flux_csv(raw.decode("utf-8"))

    def sessions(self):
        m, b = self.meas + "_sessions", self.cfg.bucket
        res = self._query(f'SELECT * FROM "{m}" ORDER BY time DESC',
                          f'from(bucket: "{b}") |> range(start: -3650d) |> filter(fn: (r) => r._measurement == "{m}")'
                          ' |> pivot(rowKey: ["_time", "session"], columnKey: ["_field"], valueColumn: "_value")')
        out = []
        for r in self._rows(res):
            out.append(norm_session(_meta_back({**r, "id": r.get("session")})))
        out.sort(key=lambda s: -s["start_us"])
        return out

    def _rows(self, res) -> list[dict]:
        """Rows (dicts, 'time' in epoch microseconds) of a query result of either version."""
        if self.v == 1:
            rows = []
            for r in res.get("results", []):
                if r.get("error"):
                    raise StoreError(f"InfluxDB: {r['error']}")
                for s in r.get("series", []) or []:
                    cols = s["columns"]
                    for vals in s["values"]:
                        d = dict(zip(cols, vals))
                        d["time"] = int(d["time"]) // 1000
                        if "session" not in d:
                            d["session"] = (s.get("tags") or {}).get("session")
                        rows.append(d)
            return rows
        rows = []
        for d in res:
            d = dict(d)
            t = d.get("time", d.get("_time"))
            d["time"] = rfc3339_to_us(t) if isinstance(t, str) else int(t) // 1000
            rows.append(d)
        return rows

    def _range_rows(self, sess: str, lo: int, hi: int) -> list[dict]:
        """The points of a recording between two times (inclusive), oldest first; _TooBig above MAX_READ_ROWS."""
        m, b = self.meas, self.cfg.bucket
        v1 = (f"SELECT * FROM \"{m}\" WHERE \"session\"='{sess}' AND time >= {lo * 1000} AND time <= {hi * 1000}"
              f" ORDER BY time ASC LIMIT {MAX_READ_ROWS + 1}")
        flux = (f'from(bucket: "{b}") |> range(start: time(v: {lo * 1000}), stop: time(v: {hi * 1000 + 1}))'
                f' |> filter(fn: (r) => r._measurement == "{m}" and r.session == "{sess}")'
                ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")')
        rows = self._rows(self._query(v1, flux))
        if len(rows) > MAX_READ_ROWS:
            raise _TooBig(f"Za dużo danych do wczytania naraz (> {MAX_READ_ROWS:,} wpisów) – wybierz węższy zakres czasu.")
        return rows

    def read(self, session_id, t0_us=None, t1_us=None, max_points=0):
        meta = next((s for s in self.sessions() if s["id"] == session_id), None)
        if meta is None:
            raise StoreError("Nie znaleziono nagrania w bazie.")
        lo = t0_us if t0_us is not None else meta["start_us"]
        hi = t1_us if t1_us is not None else int(meta.get("end_us") or time.time() * 1e6) + 86_400_000_000
        sess = session_id.replace("'", "")
        fields_ = meta.get("fields") or unique_fields([s.get("name", "") for s in meta["signals"]])
        index = {f: i for i, f in enumerate(fields_)}
        hold = meta["mode"] == "changes"
        state = self._carry_in(meta, sess, t0_us, index) if (t0_us is not None and hold) else {}
        try:
            rows = self._range_rows(sess, lo, hi)
        except _TooBig:
            if max_points <= 0:
                raise
            return self._read_sliced(meta, sess, lo, hi, index, hold, state, max_points)
        events = [(t0_us, i, v) for i, v in state.items()]       # the state before the range first, real points after it
        for r in rows:
            events += self._row_events(r, index)
        t, v = events_to_matrix(len(fields_), events, hold)
        return meta, t, v

    def _read_sliced(self, meta, sess, lo, hi, index, hold, state, max_points):
        """A range too big for memory: read it in slices, thin every slice out (min / max) and join the pieces. The state
        of the signals is carried from one slice to the next. Works on every InfluxDB version."""
        end = int(meta.get("end_us") or 0) or min(hi, int(time.time() * 1e6))
        hi = min(hi, end)
        span = max(hi - lo, 1)
        step = max(span // 48, 60_000_000)
        n = len(index)
        ts, vs = [], []
        a = lo
        while a <= hi:
            b = min(a + step, hi + 1)
            try:
                rows = self._range_rows(sess, a, b - 1)
            except _TooBig:
                raise StoreError("Za dużo danych w krótkim czasie – wybierz węższy zakres czasu.") from None
            events = [(a, i, v) for i, v in state.items()]
            for r in rows:
                events += self._row_events(r, index)
            t, v = events_to_matrix(n, events, hold)
            if len(t):
                state = {i: (None if v[-1, i] != v[-1, i] else float(v[-1, i])) for i in range(n)} if hold else {}
                t, v = downsample_minmax(t, v, max(int(max_points * (b - a) / span), 8))
                ts.append(t)
                vs.append(v)
            a = b
        if not ts:
            return meta, np.zeros(0, dtype=np.int64), np.zeros((0, n))
        return meta, np.concatenate(ts), np.vstack(vs)

    @staticmethod
    def _row_events(r: dict, index: dict) -> list:
        out = []
        for k, val in r.items():
            if val is None or val == "":
                continue
            if k in index:
                out.append((r["time"], index[k], float(val)))
            elif k.endswith(QUALITY) and k[: -len(QUALITY)] in index and float(val) == 0.0:
                out.append((r["time"], index[k[: -len(QUALITY)]], None))        # not readable -> gap (NaN)
        return out

    def _carry_in(self, meta: dict, sess: str, t0_us: int, index: dict) -> dict[int, float]:
        """The state of every signal at `t0_us` (None = it was not readable then). The keyframes (a full state every N
        minutes) make a short look-back enough, and it gives exact times; whatever it does not find comes from the
        slower 'last value before' query."""
        kf = float(meta.get("keyframe_min") or 0.0)
        got: dict[int, float | None] = {}
        if kf > 0:
            a = max(int(meta["start_us"]), t0_us - int(kf * 60e6 * 2) - 5_000_000)
            try:
                got = self._window_state(sess, a, t0_us, index)
            except StoreError:
                got = {}
        if len(got) < len(index):
            rest = self._carry_in_last(meta, sess, t0_us, index)
            for i, v in rest.items():
                got.setdefault(i, v)
        return got

    def _window_state(self, sess: str, a_us: int, b_us: int, index: dict) -> dict[int, float | None]:
        """Latest value per signal among the points in [a, b): a range query and a pass over its rows in time order."""
        m, bk = self.meas, self.cfg.bucket
        v1 = (f"SELECT * FROM \"{m}\" WHERE \"session\"='{sess}' AND time >= {a_us * 1000} AND time < {b_us * 1000}"
              " ORDER BY time ASC")
        flux = (f'from(bucket: "{bk}") |> range(start: time(v: {a_us * 1000}), stop: time(v: {b_us * 1000}))'
                f' |> filter(fn: (r) => r._measurement == "{m}" and r.session == "{sess}")'
                ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")')
        out: dict[int, float | None] = {}
        for r in sorted(self._rows(self._query(v1, flux)), key=lambda r: r["time"]):
            for _t, i, v in self._row_events(r, index):
                out[i] = v
        return out

    def _carry_in_last(self, meta: dict, sess: str, t0_us: int, index: dict) -> dict[int, float]:
        """The last value of every signal before `t0_us` (None = it was not readable then)."""
        m, b, lo = self.meas, self.cfg.bucket, t0_us
        start = int(meta["start_us"]) * 1000
        v1 = f'SELECT LAST(*) FROM "{m}" WHERE "session"=\'{sess}\' AND time < {lo * 1000}'
        flux = (f'from(bucket: "{b}") |> range(start: time(v: {start}), stop: time(v: {lo * 1000})) '
                f'|> filter(fn: (r) => r._measurement == "{m}" and r.session == "{sess}") |> last()')
        try:
            res = self._query(v1, flux)
        except StoreError:
            return {}
        last: dict[str, float] = {}
        if self.v == 2:                                            # long format: one row per field
            for r in res:
                if r.get("_field") and r.get("_value") not in (None, ""):
                    last[r["_field"]] = float(r["_value"])
        else:                                                      # v1: LAST(*) -> columns "last_<field>"
            for r in self._rows(res):
                for k, val in r.items():
                    if k.startswith("last_") and val is not None:
                        last[k[5:]] = float(val)
        out: dict[int, float | None] = {}
        for k, val in last.items():
            if k in index:
                out[index[k]] = float(val)
        for k, val in last.items():
            if k.endswith(QUALITY) and k[: -len(QUALITY)] in index and float(val) == 0.0:
                out[index[k[: -len(QUALITY)]]] = None
        return out

    def ping(self):
        if self.v == 1:
            self._http("GET", "/ping")
        else:
            self._http("GET", "/health")
        return f"InfluxDB {self.v}.x: {self.base} odpowiada"


def parse_flux_csv(text: str) -> list[dict]:
    """InfluxDB 2.x annotated CSV -> list of dicts (several tables may follow each other, each with a header)."""
    import csv
    rows, header = [], None
    for rec in csv.reader(text.splitlines()):
        if not rec or rec[0].startswith("#"):
            continue
        if rec[0] == "" and len(rec) > 1 and rec[1] == "result":
            header = rec
            continue
        if not any(rec):
            header = None
            continue
        if header is None or len(rec) != len(header):
            continue
        d = {h: v for h, v in zip(header, rec) if h not in ("", "result", "table")}
        if "error" in d and d.get("error"):
            raise StoreError(f"InfluxDB: {d['error']}")
        rows.append(d)
    return rows


# ---- TimescaleDB (PostgreSQL)
def _psycopg():
    """The PostgreSQL driver: psycopg 3 (needs the libpq DLL that comes with psycopg[binary]); when that cannot be
    imported - e.g. on an old Windows Server - the pure-Python pg8000 takes over."""
    try:
        import psycopg
        return psycopg
    except ImportError:
        pass
    try:
        import pg8000.dbapi
        return pg8000.dbapi
    except ImportError:
        raise StoreError("TimescaleDB wymaga biblioteki „psycopg” albo „pg8000” (pip install \"psycopg[binary]\" / "
                         "pip install pg8000). W wersji przenośnej są dołączone.") from None


def _pg_connect(pg, cfg: "StoreConfig", timeout: int):
    if getattr(pg, "__name__", "").startswith("pg8000"):
        ctx = None
        if cfg.pg_sslmode in ("require", "verify-ca", "verify-full"):
            import ssl
            ctx = ssl.create_default_context()
            if cfg.pg_sslmode == "require":                      # as libpq: encrypted, the certificate is not checked
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        return pg.connect(user=cfg.pg_user, host=cfg.host, port=cfg.port, database=cfg.pg_database,
                          password=cfg.pg_password, timeout=timeout, ssl_context=ctx)
    return pg.connect(host=cfg.host, port=cfg.port, dbname=cfg.pg_database, user=cfg.pg_user, password=cfg.pg_password,
                      sslmode=cfg.pg_sslmode, connect_timeout=timeout)


def pg_driver_name() -> str:
    try:
        return getattr(_psycopg(), "__name__", "psycopg").split(".")[0]
    except StoreError:
        return ""


class TimescaleBackend(Backend):
    def __init__(self, cfg: StoreConfig, timeout: float | None = None):
        self.cfg = cfg
        self.timeout = int(timeout or cfg.http_timeout_s)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cfg.table or ""):
            raise StoreError("Nazwa tabeli: tylko litery, cyfry i podkreślenia.")
        self.t, self.ts = cfg.table, cfg.table + "_sessions"
        pg = _psycopg()
        try:
            self.conn = _pg_connect(pg, cfg, self.timeout)
        except Exception as e:
            raise StoreError(f"TimescaleDB: brak połączenia ({str(e).strip()[:200]})") from None
        self._schema()
        self.sid = ""

    def _schema(self):
        c = self.conn
        cur = c.cursor()
        cur.execute(f"CREATE TABLE IF NOT EXISTS {self.ts}(id text PRIMARY KEY, name text, start_us bigint,"
                    " end_us bigint, ip text, tab text, conf text, mode text, signals text, fields text)")
        for col, typ in (("title", "text"), ("notes", "text"), ("tags", "text"), ("owner", "text"), ("computer", "text"),
                         ("keyframe_min", "double precision"), ("deleted_us", "bigint")):
            cur.execute(f"ALTER TABLE {self.ts} ADD COLUMN IF NOT EXISTS {col} {typ}")
        cur.execute(f"CREATE TABLE IF NOT EXISTS {self.t}(time timestamptz NOT NULL, session text NOT NULL,"
                    " sig integer NOT NULL, value double precision)")
        c.commit()
        try:                                                      # a plain PostgreSQL works too, just without hypertables
            cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            cur.execute(f"SELECT create_hypertable('{self.t}', 'time', if_not_exists => TRUE)")
            c.commit()
        except Exception:
            c.rollback()
        else:
            self._compression(cur)
        cur.execute(f"CREATE INDEX IF NOT EXISTS {self.t}_sess_idx ON {self.t}(session, sig, time DESC)")
        c.commit()

    def _compression(self, cur) -> None:
        """Compress chunks older than `compress_days` days (0 = none). Best effort: not every edition has compression."""
        c, n = self.conn, int(self.cfg.compress_days)
        try:
            if n > 0:
                cur.execute(f"ALTER TABLE {self.t} SET (timescaledb.compress, timescaledb.compress_segmentby = 'session, sig')")
                cur.execute("SELECT (config->>'compress_after')::interval = %s::interval FROM timescaledb_information.jobs "
                            "WHERE proc_name = 'policy_compression' AND hypertable_name = %s", (f"{n} days", self.t))
                row = cur.fetchone()
                if row is None or not row[0]:                     # no policy yet, or one with another interval: set it afresh
                    cur.execute(f"SELECT remove_compression_policy('{self.t}', if_exists => TRUE)")
                    cur.execute(f"SELECT add_compression_policy('{self.t}', INTERVAL '{n} days', if_not_exists => TRUE)")
            else:
                cur.execute(f"SELECT remove_compression_policy('{self.t}', if_exists => TRUE)")
            c.commit()
        except Exception:
            c.rollback()

    def begin(self, meta):
        self.sid = meta.get("id") or new_session_id()
        m = _meta_json(meta)
        cur = self.conn.cursor()
        cur.execute(f"INSERT INTO {self.ts}(id,name,start_us,end_us,ip,tab,conf,mode,signals,fields,title,notes,tags,owner,"
                    "computer,keyframe_min,deleted_us) VALUES(%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)"
                    " ON CONFLICT (id) DO NOTHING",
                    (self.sid, m.get("name", ""), m["start_us"], m.get("ip", ""), m.get("tab", ""), m.get("conf", ""),
                     m.get("mode", "changes"), m["signals"], m["fields"], m.get("title", ""), m.get("notes", ""),
                     m.get("tags", ""), m.get("owner", ""), m.get("computer", ""), m.get("keyframe_min", 0.0)))
        self.conn.commit()
        return self.sid

    def update_session(self, session_id, fields):
        sets = {k: v for k, v in fields.items() if k in EDITABLE}
        if sets:
            cur = self.conn.cursor()
            cur.execute(f"UPDATE {self.ts} SET {','.join(k + '=%s' for k in sets)} WHERE id=%s", (*sets.values(), session_id))
            self.conn.commit()

    def delete_session(self, session_id):
        cur = self.conn.cursor()
        try:
            cur.execute(f"DELETE FROM {self.t} WHERE session=%s", (session_id,))
            cur.execute(f"DELETE FROM {self.ts} WHERE id=%s", (session_id,))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise StoreError(f"TimescaleDB: nie można usunąć danych ({str(e).strip()[:200]}). Dane w skompresowanych "
                             "fragmentach wymagają nowszej wersji TimescaleDB (2.11+).") from None

    def stats(self):
        cur = self.conn.cursor()
        cur.execute(f"SELECT session, count(*) FROM {self.t} GROUP BY session")
        return {k: int(v) for k, v in cur.fetchall()}

    def write(self, rows):
        data = [(us_to_rfc3339(t), self.sid, i, None if v != v else float(v)) for t, d, _k in _td(rows) for i, v in d.items()]
        cur = self.conn.cursor()
        cur.executemany(f"INSERT INTO {self.t}(time,session,sig,value) VALUES(%s,%s,%s,%s)", data)
        self.conn.commit()

    def end(self, end_us):
        cur = self.conn.cursor()
        cur.execute(f"UPDATE {self.ts} SET end_us=%s WHERE id=%s", (end_us, self.sid))
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def sessions(self):
        cur = self.conn.cursor()
        cur.execute(f"SELECT {','.join(SESSION_COLS)} FROM {self.ts} ORDER BY start_us DESC")
        return [norm_session(_meta_back(dict(zip(SESSION_COLS, r)))) for r in cur.fetchall()]

    def read(self, session_id, t0_us=None, t1_us=None, max_points=0):
        meta = next((s for s in self.sessions() if s["id"] == session_id), None)
        if meta is None:
            raise StoreError("Nie znaleziono nagrania w bazie.")
        n = len(meta["signals"])
        lo = t0_us if t0_us is not None else meta["start_us"] - 1_000_000
        hi = t1_us if t1_us is not None else int(time.time() * 1e6) + 86_400_000_000
        cur = self.conn.cursor()
        events = []
        if t0_us is not None and meta["mode"] == "changes":
            cur.execute(f"SELECT DISTINCT ON (sig) sig, value FROM {self.t} WHERE session=%s AND time<%s::timestamptz"
                        " ORDER BY sig, time DESC", (session_id, us_to_rfc3339(lo)))
            events += [(lo, s, v) for s, v in cur.fetchall()]
        if max_points > 0:                                       # too much for memory: min / max of every time slice, in SQL
            cur.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM {self.t} WHERE session=%s AND time>=%s::timestamptz"
                        " AND time<=%s::timestamptz LIMIT %s) x",
                        (session_id, us_to_rfc3339(lo), us_to_rfc3339(hi), MAX_READ_ROWS + 1))
            if cur.fetchone()[0] > MAX_READ_ROWS:
                a = t0_us if t0_us is not None else int(meta["start_us"])
                b = t1_us if t1_us is not None else meta.get("end_us")
                if b is None:                                    # a recording that was never closed properly
                    cur.execute(f"SELECT (EXTRACT(EPOCH FROM max(time)) * 1000000)::bigint FROM {self.t} WHERE session=%s",
                                (session_id,))
                    b = int(cur.fetchone()[0] or a)
                w = max((b - a) // max(max_points // 2, 1) + 1, 1)
                cur.execute("SELECT sig, (EXTRACT(EPOCH FROM date_bin(%s::bigint * interval '1 microsecond', time,"
                            f" %s::timestamptz)) * 1000000)::bigint AS k, MIN(value), MAX(value) FROM {self.t}"
                            " WHERE session=%s AND time>=%s::timestamptz AND time<=%s::timestamptz GROUP BY sig, k",
                            (w, us_to_rfc3339(a), session_id, us_to_rfc3339(lo), us_to_rfc3339(hi)))
                for sig, k, vmin, vmax in cur.fetchall():
                    events.append((int(k), sig, vmin))
                    if vmax is not None and vmax != vmin:
                        events.append((int(k) + w // 2, sig, vmax))
                events.sort(key=lambda e: e[0])
                t, v = events_to_matrix(n, events, meta["mode"] == "changes")
                return meta, t, v
        cur.execute(f"SELECT (EXTRACT(EPOCH FROM time) * 1000000)::bigint, sig, value FROM {self.t}"
                    " WHERE session=%s AND time>=%s::timestamptz AND time<=%s::timestamptz ORDER BY time LIMIT %s",
                    (session_id, us_to_rfc3339(lo), us_to_rfc3339(hi), MAX_READ_ROWS + 1))
        events += cur.fetchall()
        if len(events) > MAX_READ_ROWS:
            raise StoreError(f"Za dużo danych do wczytania naraz (> {MAX_READ_ROWS:,} wpisów) – wybierz węższy zakres czasu.")
        t, v = events_to_matrix(n, events, meta["mode"] == "changes")
        return meta, t, v

    def ping(self):
        cur = self.conn.cursor()
        cur.execute("SELECT version()")
        return str(cur.fetchone()[0])[:80]


def open_backend(cfg: StoreConfig, base_dir: str = "", timeout: float | None = None) -> Backend:
    k = cfg.kind
    if k == "sqlite":
        p = cfg.sqlite_path or "s7trace.db"
        return SqliteBackend(p if os.path.isabs(p) else os.path.join(effective_base(cfg, base_dir), p))
    if k in ("influx1", "influx2"):
        return InfluxBackend(cfg, int(k[-1]), timeout)
    if k == "timescale":
        return TimescaleBackend(cfg, timeout)
    raise StoreError("Ten format nie jest bazą danych.")


def test_connection(cfg: StoreConfig, base_dir: str = "", timeout: float | None = None) -> str:
    """Returns a short success message or raises StoreError."""
    b = open_backend(cfg, base_dir, timeout)
    try:
        return b.ping()
    finally:
        b.close()


# ---------------------------------------------------------------------------------------------- recorder
class Spool:
    """Disk buffer of a network target: a small local SQLite queue (rows in the order they were taken) that is filled while
    the server is away and drained when it is back. The session description is stored too, so a file left behind by a
    program that was closed (or crashed) mid-outage can be delivered by the next run."""

    def __init__(self, path: str, max_mb: float):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path, self.max = path, int(max_mb * 1_000_000)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS q(id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER, d TEXT)")
        self.db.commit()

    def set_meta(self, meta: dict, target: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES('meta',?)", (json.dumps(meta),))
        self.db.execute("INSERT OR REPLACE INTO meta VALUES('target',?)", (target,))
        self.db.commit()

    def get_meta(self) -> tuple[dict, str]:
        r = dict(self.db.execute("SELECT k,v FROM meta").fetchall())
        return json.loads(r.get("meta") or "{}"), r.get("target", "")

    def add(self, rows) -> None:
        self.db.executemany("INSERT INTO q(t,d) VALUES(?,?)",
                            [(t, json.dumps({**{str(i): v for i, v in d.items()}, **({"k": 1} if key else {})}))
                             for t, d, key in _td(rows)])
        self.db.commit()

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM q").fetchone()[0]

    def peek(self, n: int) -> tuple[int, list]:
        """(last id, rows) of the oldest `n` rows; delete them with remove(last id) once delivered."""
        cur = self.db.execute("SELECT id,t,d FROM q ORDER BY id LIMIT ?", (n,)).fetchall()
        rows = []
        for _, t, d in cur:
            dd = json.loads(d)
            key = dd.pop("k", None)
            vals = {int(k): (math.nan if v is None else v) for k, v in dd.items()}
            rows.append((t, vals, True) if key else (t, vals))
        return (cur[-1][0] if cur else 0), rows

    def remove(self, upto_id: int) -> None:
        self.db.execute("DELETE FROM q WHERE id<=?", (upto_id,))
        self.db.commit()

    def used(self) -> int:
        """Bytes in use (free pages left by deleted rows do not count)."""
        pc, fl, ps = (self.db.execute(f"PRAGMA {k}").fetchone()[0] for k in ("page_count", "freelist_count", "page_size"))
        return (pc - fl) * ps

    def trim(self) -> int:
        """Over the size limit: the oldest ~20 % of the rows are dropped. Returns how many."""
        if self.max <= 0 or self.used() <= self.max:
            return 0
        n = self.count()
        cut = max(n // 5, 1)
        self.db.execute("DELETE FROM q WHERE id IN (SELECT id FROM q ORDER BY id LIMIT ?)", (cut,))
        self.db.commit()
        return cut

    def close(self, delete: bool = False) -> None:
        try:
            self.db.close()
        except Exception:
            pass
        if delete:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(self.path + suffix)
                except OSError:
                    pass


_ACTIVE_SPOOLS: set[str] = set()                           # buffers of the recordings running in this program
_ACTIVE_SESSIONS: set[str] = set()                         # ids of the recordings running in this program


def scan_spools(base_dir: str) -> list[dict]:
    """Disk buffers left behind by earlier recordings: [{path, name, meta, target, rows, size}] (buffers of recordings that
    are running now are not listed)."""
    folder = os.path.join(base_dir, "spool")
    out = []
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not (name.startswith("spool_") and name.endswith(".db")) or path in _ACTIVE_SPOOLS:
            continue
        sp = None
        try:
            sp = Spool(path, 0)
            meta, target = sp.get_meta()
            rows = sp.count()
            sp.close(delete=rows == 0)                           # an empty buffer is just litter
            if rows:
                out.append({"path": path, "name": name, "meta": meta, "target": target, "rows": rows,
                            "size": os.path.getsize(path)})
        except Exception:
            if sp is not None:
                sp.close()
    return out


def deliver_spool(cfg: StoreConfig, path: str, base_dir: str = "") -> int:
    """Sends a disk buffer to the database (oldest rows first) and deletes the file. Returns the number of rows.
    Raises when the server cannot be reached (the file stays)."""
    sp = Spool(path, 0)
    n = 0
    try:
        meta, _target = sp.get_meta()
        if not meta.get("id"):
            raise StoreError("Bufor nie zawiera opisu nagrania.")
        b = open_backend(cfg, base_dir)
        try:
            b.begin(meta)
            while sp.count():
                last, rows = sp.peek(20000)
                b.write(rows)
                sp.remove(last)
                n += len(rows)
        finally:
            b.close()
    except BaseException:
        sp.close()
        raise
    sp.close(delete=True)
    return n


def remove_spool(path: str) -> None:
    Spool(path, 0).close(delete=True)


class DbRecorder:
    """The recorder of a database target: same interface as CsvRecorder (write / close / path), but the work is
    done by a thread: batches every ~0.5 s, retries while the server is away, bounded memory."""

    QUEUE_MAX: int | None = None                 # (tests) overrides cfg.queue_max
    CLOSE_GRACE: float | None = None             # (tests) overrides cfg.close_grace_s

    def __init__(self, cfg: StoreConfig, signals, start_wall: datetime, meta_extra: dict, base_dir: str = "",
                 backend: Backend | None = None):
        if cfg.kind == "sqlite" and backend is None:
            cfg = dataclasses.replace(cfg, sqlite_path=rotated_sqlite_path(cfg, base_dir, start_wall))   # daily / by size
        self.cfg, self.start_wall = cfg, start_wall
        self.n = len(signals)
        self.filter = ChangeFilter(self.n, cfg.mode)
        self._key_s = max(cfg.keyframe_min, 0.0) * 60.0 if cfg.mode == "changes" else 0.0
        self._next_key = self._key_s
        self.fields = unique_fields([s.name for s in signals])
        meta = {"id": new_session_id(), "name": meta_extra.get("name", ""), "start_us": to_us(start_wall, 0.0),
                "ip": meta_extra.get("ip", ""), "tab": meta_extra.get("tab", ""), "conf": meta_extra.get("conf", ""),
                "title": meta_extra.get("title", ""), "notes": meta_extra.get("notes", ""), "tags": meta_extra.get("tags", ""),
                "owner": current_user(), "computer": platform.node(), "keyframe_min": self._key_s / 60.0,
                "mode": cfg.mode, "signals": [s.to_dict() for s in signals], "fields": self.fields}
        self._begun = False
        self._info: dict = {}
        self._info_dirty = False
        self._meta, self._base_dir, self.session = meta, base_dir, meta["id"]
        self.backend = backend
        if self.backend is None and cfg.kind == "sqlite":        # local file: a wrong path is reported at once
            self.backend = open_backend(cfg, base_dir)
        if self.backend is not None:
            self.backend.begin(meta)                             # network targets connect in the writer thread (retries)
            self._begun = True
        self.path = f"{cfg.describe()} (nagranie {self.session})"
        self.q: queue.Queue = queue.Queue(maxsize=self.QUEUE_MAX or max(int(cfg.queue_max), 1000))
        self.dropped = 0
        self.written = 0
        self.last_error = ""
        self.spool: Spool | None = None
        self.spooled = 0                                         # rows waiting in the disk buffer
        if base_dir and cfg.kind in StoreConfig.NETWORK and cfg.spool_mb > 0:
            try:
                self.spool = Spool(os.path.join(base_dir, "spool", f"spool_{self.session}.db"), cfg.spool_mb)
                self.spool.set_meta(meta, cfg.describe())
                _ACTIVE_SPOOLS.add(self.spool.path)
            except (sqlite3.Error, OSError):
                self.spool = None                                # no disk buffer: memory only
        self._stop = threading.Event()
        self._last_us = meta["start_us"]
        self._deadline = float("inf")
        self.thread = threading.Thread(target=self._run_spool if self.spool else self._run, daemon=True,
                                       name="StoreWriter")
        _ACTIVE_SESSIONS.add(self.session)
        self.thread.start()

    def write(self, t: float, values) -> None:
        key = (self._key_s > 0 and t >= self._next_key) or self.filter.prev is None      # the first row is a full state too
        if key:                                                  # keyframe: the full state again (starting point for range reads)
            self._next_key = t + self._key_s
        idx = self.filter.changed(values, force=key)
        if not idx:
            return
        us = to_us(self.start_wall, t)
        self._last_us = us
        row = (us, {i: (values[i] if i < len(values) else math.nan) for i in idx}) + ((True,) if key else ())
        try:
            self.q.put_nowait(row)
        except queue.Full:
            try:
                self.q.get_nowait()                              # the database is far behind: drop the oldest
            except queue.Empty:
                pass
            self.dropped += 1
            self.q.put_nowait(row)

    def update_info(self, title=None, notes=None, tags=None) -> None:
        """Title / notes / tags of the recording being written (from the GUI thread; applied by the writer thread)."""
        kw = {k: v for k, v in (("title", title), ("notes", notes), ("tags", tags)) if v is not None}
        if not kw:
            return
        self._meta.update(kw)                                    # also used when the connection has to be opened later
        self._info.update(kw)
        self._info_dirty = True
        if self.spool is not None:
            try:
                self.spool.set_meta(self._meta, self.cfg.describe())
            except sqlite3.Error:
                pass

    def _apply_info(self) -> None:
        if self._info_dirty and self._begun and self.backend is not None:
            try:
                self.backend.update_session(self.session, dict(self._info))
                self._info_dirty = False
            except Exception:
                pass                                             # the next turn tries again

    def _batch(self, block: bool) -> list:
        rows = []
        try:
            rows.append(self.q.get(timeout=max(self.cfg.batch_s, 0.05)) if block else self.q.get_nowait())
            while len(rows) < 20000:
                rows.append(self.q.get_nowait())
        except queue.Empty:
            pass
        return rows

    def _run(self) -> None:
        pending: list = []
        backoff = 1.0
        while True:
            self._apply_info()
            if not pending:
                pending = self._batch(block=not self._stop.is_set())
            if not pending:
                if self._stop.is_set():
                    return
                continue
            try:
                if self.backend is None:
                    self.backend = open_backend(self.cfg, self._base_dir)
                    self.backend.begin(self._meta)
                    self._begun = True
                self.backend.write(pending)
                self.written += len(pending)
                pending, self.last_error, backoff = [], "", 1.0
            except Exception as e:                               # server away / disk full: keep the batch and retry
                self.last_error = str(e)[:200]
                if self._stop.is_set():                          # closing: a few more tries, then give up
                    if time.time() > self._deadline:
                        return
                    time.sleep(0.3)
                else:
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, max(self.cfg.retry_max_s, 1.0))

    # -- writer with a disk buffer
    def _send(self, rows) -> None:
        if self.backend is None:
            self.backend = open_backend(self.cfg, self._base_dir)
            self.backend.begin(self._meta)
            self._begun = True
        self.backend.write(rows)
        self.written += len(rows)

    def _failed(self, e: Exception) -> None:
        self.last_error = str(e)[:200]

    def _drain(self, spool: Spool, limit: float) -> None:
        """Deliver the buffered rows oldest first; raises when the server is away again."""
        while self.spooled and time.time() < limit:
            last, rows = spool.peek(20000)
            if not rows:
                self.spooled = 0
                break
            self._send(rows)
            spool.remove(last)
            self.spooled = spool.count()

    def _recover(self) -> None:
        """Deliver the buffers that earlier runs left behind (closed or crashed while the server was away)."""
        for it in scan_spools(self._base_dir):
            if it["path"] == self.spool.path or it["target"] != self.cfg.describe() or not it["meta"].get("id"):
                continue
            try:
                self.written += deliver_spool(self.cfg, it["path"], self._base_dir)
            except Exception:
                pass                                             # still unreachable: next run tries again

    def _run_spool(self) -> None:
        sp = self.spool
        backoff, next_try, recovered = 1.0, 0.0, False
        while True:
            self._apply_info()
            rows = self._batch(block=not self._stop.is_set())
            stopping = self._stop.is_set()
            now = time.time()
            if stopping:
                next_try = 0.0                                   # closing: try on every turn until the deadline
            if rows and not self.spooled and now >= next_try:    # normal path: straight to the server
                try:
                    self._send(rows)
                    rows, self.last_error, backoff = [], "", 1.0
                except Exception as e:
                    self._failed(e)
                    next_try, backoff = now + backoff, min(backoff * 2, max(self.cfg.retry_max_s, 1.0))
            if rows:                                             # the server is away: keep the rows on disk, in order
                try:
                    sp.add(rows)
                    self.spooled = sp.count()
                    self.dropped += sp.trim()
                    self.spooled = sp.count()
                except sqlite3.Error as e:
                    self._failed(e)
                    self.dropped += len(rows)
            if self.spooled and time.time() >= next_try:
                try:
                    self._drain(sp, self._deadline if stopping else float("inf"))
                    if not self.spooled:
                        self.last_error, backoff = "", 1.0
                except Exception as e:
                    self._failed(e)
                    next_try, backoff = time.time() + backoff, min(backoff * 2, max(self.cfg.retry_max_s, 1.0))
            if not recovered and not self.last_error:
                recovered = True
                self._recover()
            if stopping:
                if self.q.empty() and not self.spooled:
                    return
                if time.time() > self._deadline:                 # leave the rest on disk for the next run
                    while True:
                        left = self._batch(block=False)
                        if not left:
                            break
                        sp.add(left)
                    self.spooled = sp.count()
                    return
                time.sleep(0.2)

    def status(self) -> str:
        s = f"zapisano {self.written}"
        if self.q.qsize():
            s += f", w kolejce {self.q.qsize()}"
        if self.spooled:
            s += f", na dysku {self.spooled}"
        if self.dropped:
            s += f", utracono {self.dropped}"
        if self.last_error:
            s += f" – BŁĄD: {self.last_error}"
        return s

    def close(self) -> None:
        grace = self.CLOSE_GRACE if self.CLOSE_GRACE is not None else self.cfg.close_grace_s
        self._deadline = time.time() + grace                     # a last chance to deliver what is queued
        self._stop.set()
        self.thread.join(max(15.0, grace + 5.0))
        _ACTIVE_SESSIONS.discard(self.session)
        self._apply_info()
        if self.backend is not None:
            try:
                self.backend.end(self._last_us)
            except Exception:
                pass
            self.backend.close()
        if self.spool is not None:
            _ACTIVE_SPOOLS.discard(self.spool.path)
            self.spool.close(delete=not self.spooled)            # an empty buffer is removed; a full one waits for the next run
