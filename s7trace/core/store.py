"""Recording targets and readers for the REC button: CSV file, SQLite, InfluxDB 1.x / 2.x / 3.x, TimescaleDB.

Model: a *session* = one REC run (start time, address, tab, signal definitions, mode). The recorded samples are
events (time, signal, value). Mode "changes" (default) stores a value only when it differs from the previous one
(plus the first value of every signal), mode "all" stores every sample. Reading rebuilds the step curves: in mode
"changes" every signal keeps its last value until the next event.

Writers run in their own thread (batched, with retries) so a slow database never delays the GUI or the PLC cycle.
Pure Python (no Qt). Optional libraries are imported lazily: `psycopg` (TimescaleDB); SQLite and the InfluxDB
HTTP APIs need nothing extra."""
from __future__ import annotations

import dataclasses
import json
import math
import os
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

KINDS = ["csv", "sqlite", "influx1", "influx2", "influx3", "timescale"]
KIND_LABEL = {"csv": "Plik CSV", "sqlite": "SQLite", "influx1": "InfluxDB 1.x", "influx2": "InfluxDB 2.x",
              "influx3": "InfluxDB 3.x", "timescale": "TimescaleDB"}
MODES = ["changes", "all"]
MODE_LABEL = {"changes": "Tylko zmiany stanu", "all": "Każda próbka"}
MAX_READ_ROWS = 5_000_000


class StoreError(Exception):
    """A readable message for the user (connection refused, bad credentials, missing library ...)."""


@dataclass
class StoreConfig:
    kind: str = "csv"
    mode: str = "changes"                   # default: only changes of state
    sqlite_path: str = "s7trace.db"         # relative = in the user's S7Trace folder in Documents
    url: str = "http://localhost:8086"      # InfluxDB
    database: str = "s7trace"               # InfluxDB 1.x / 3.x
    org: str = ""                           # InfluxDB 2.x
    bucket: str = "s7trace"                 # InfluxDB 2.x
    user: str = ""                          # InfluxDB 1.x
    password: str = ""
    token: str = ""                         # InfluxDB 2.x / 3.x
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
    read_max_points: int = 200000           # reading: downsample above this many points per signal

    SECRETS = ("password", "token", "pg_password")
    NETWORK = ("influx1", "influx2", "influx3", "timescale")

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
        return c

    def describe(self) -> str:
        k = self.kind
        if k == "sqlite":
            return f"SQLite {self.sqlite_path}"
        if k == "influx1":
            return f"InfluxDB 1.x {self.url} / {self.database}"
        if k == "influx2":
            return f"InfluxDB 2.x {self.url} / {self.bucket}"
        if k == "influx3":
            return f"InfluxDB 3.x {self.url} / {self.database}"
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
    "read_max_points": ("Odczyt: maks. punktów na sygnał", 1000, 50_000_000, "pkt",
                        "Przy wczytywaniu bardzo długiego zakresu program, jeśli danych jest więcej niż tyle, zmniejsza je "
                        "(dla każdego przedziału zachowuje wartość minimalną i maksymalną, więc szpilki nie znikają)."),
}


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
    p = p if os.path.isabs(p) else os.path.join(base_dir, p)
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
        self.db.commit()
        self.sid = ""

    def begin(self, meta):
        self.sid = meta.get("id") or new_session_id()
        m = _meta_json(meta)
        self.db.execute("INSERT OR REPLACE INTO sessions(id,name,start_us,end_us,ip,tab,conf,mode,signals,fields)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (self.sid, m.get("name", ""), m["start_us"], None, m.get("ip", ""), m.get("tab", ""),
                         m.get("conf", ""), m.get("mode", "changes"), m["signals"], m["fields"]))
        self.db.commit()
        return self.sid

    def write(self, rows):
        data = [(self.sid, i, t, None if (v != v) else float(v)) for t, d in rows for i, v in d.items()]
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
        cur = self.db.execute("SELECT id,name,start_us,end_us,ip,tab,conf,mode,signals,fields FROM sessions"
                              " ORDER BY start_us DESC")
        keys = ("id", "name", "start_us", "end_us", "ip", "tab", "conf", "mode", "signals", "fields")
        return [_meta_back(dict(zip(keys, r))) for r in cur.fetchall()]

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
            b = t1_us if t1_us is not None else int(meta.get("end_us") or time.time() * 1e6)
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
         f"signals={_esc_str(m['signals'])}", f"fields={_esc_str(m['fields'])}"]
    return (f"{_esc_meas(measurement + '_sessions')},session={_esc_key(meta['id'])} {','.join(f)} "
            f"{int(m['start_us']) * 1000}")


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
        elif self.v == 3 and c.token:
            h["Authorization"] = f"Bearer {c.token}"
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
            elif self.v == 2:
                self._http("POST", "/api/v2/write", {"org": c.org, "bucket": c.bucket, "precision": "ns"}, body)
            else:
                self._http("POST", "/api/v3/write_lp", {"db": c.database, "precision": "nanosecond"}, body)

    # -- write
    def begin(self, meta):
        self.sid = meta.get("id") or new_session_id()
        meta = {**meta, "id": self.sid}
        self.fields = meta.get("fields", [])
        if self.v == 1:
            try:
                self._http("POST", "/query", {"q": f'CREATE DATABASE "{self.cfg.database}"'})
            except StoreError:
                pass                                              # may lack the privilege: the database may exist
        self._write_lp([session_line(self.meas, meta)])
        return self.sid

    def write(self, rows):
        lines = []
        for t, d in rows:
            ok = {}
            for i, v in d.items():
                valid = v == v
                if valid != self._valid.get(i, True):              # availability changed: remember it in `<name>__ok`
                    ok[i] = 1.0 if valid else 0.0
                self._valid[i] = valid
            ln = sample_line(self.meas, self.sid, self.fields, t, d, ok)
            if ln:
                lines.append(ln)
        if lines:
            self._write_lp(lines)

    def end(self, end_us):
        pass

    def close(self):
        pass

    # -- read
    def _query(self, v1: str, flux: str, sql: str):
        c = self.cfg
        if self.v == 1:
            raw = self._http("GET", "/query", {"db": c.database, "q": v1, "epoch": "ns"})
            return json.loads(raw)
        if self.v == 2:
            body = json.dumps({"query": flux, "type": "flux"}).encode()
            raw = self._http("POST", "/api/v2/query", {"org": c.org}, body,
                             {"Content-Type": "application/json", "Accept": "application/csv"})
            return parse_flux_csv(raw.decode("utf-8"))
        body = json.dumps({"db": c.database, "q": sql, "format": "json"}).encode()
        raw = self._http("POST", "/api/v3/query_sql", None, body, {"Content-Type": "application/json"})
        return json.loads(raw)

    def sessions(self):
        m, b = self.meas + "_sessions", self.cfg.bucket
        res = self._query(f'SELECT * FROM "{m}" ORDER BY time DESC',
                          f'from(bucket: "{b}") |> range(start: -3650d) |> filter(fn: (r) => r._measurement == "{m}")'
                          ' |> pivot(rowKey: ["_time", "session"], columnKey: ["_field"], valueColumn: "_value")',
                          f'SELECT * FROM "{m}" ORDER BY time DESC')
        out = []
        for r in self._rows(res):
            d = _meta_back({**r, "id": r.get("session")})
            d["start_us"] = int(float(d.get("start_us") or 0))
            d["end_us"] = None
            out.append(d)
        out.sort(key=lambda s: -s["start_us"])
        return out

    def _rows(self, res) -> list[dict]:
        """Rows (dicts, 'time' in epoch microseconds) of a query result of any version."""
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

    def read(self, session_id, t0_us=None, t1_us=None, max_points=0):
        meta = next((s for s in self.sessions() if s["id"] == session_id), None)
        if meta is None:
            raise StoreError("Nie znaleziono nagrania w bazie.")
        m, b = self.meas, self.cfg.bucket
        lo = t0_us if t0_us is not None else meta["start_us"]
        hi = t1_us if t1_us is not None else int(time.time() * 1e6) + 86_400_000_000
        sess = session_id.replace("'", "")
        v1 = (f"SELECT * FROM \"{m}\" WHERE \"session\"='{sess}' AND time >= {lo * 1000} AND time <= {hi * 1000}"
              f" ORDER BY time ASC LIMIT {MAX_READ_ROWS + 1}")
        flux = (f'from(bucket: "{b}") |> range(start: time(v: {lo * 1000}), stop: time(v: {hi * 1000 + 1}))'
                f' |> filter(fn: (r) => r._measurement == "{m}" and r.session == "{sess}")'
                ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")')
        sql = (f"SELECT * FROM \"{m}\" WHERE session = '{sess}' AND time >= '{us_to_rfc3339(lo)}'"
               f" AND time <= '{us_to_rfc3339(hi)}' ORDER BY time ASC LIMIT {MAX_READ_ROWS + 1}")
        rows = self._rows(self._query(v1, flux, sql))
        if len(rows) > MAX_READ_ROWS:
            raise StoreError("Za dużo danych do wczytania naraz – wybierz węższy zakres czasu.")
        fields_ = meta.get("fields") or unique_fields([s.get("name", "") for s in meta["signals"]])
        index = {f: i for i, f in enumerate(fields_)}
        events = []
        for r in rows:
            events += self._row_events(r, index)
        if t0_us is not None and meta["mode"] == "changes":      # carry-in: what every signal had before the range
            events += [(t0_us, i, v) for i, v in self._carry_in(meta, sess, t0_us, index).items()]
        t, v = events_to_matrix(len(fields_), events, meta["mode"] == "changes")
        return meta, t, v

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
        """The last value of every signal before `t0_us` (None = it was not readable then)."""
        m, b, lo = self.meas, self.cfg.bucket, t0_us
        start = int(meta["start_us"]) * 1000
        v1 = f'SELECT LAST(*) FROM "{m}" WHERE "session"=\'{sess}\' AND time < {lo * 1000}'
        flux = (f'from(bucket: "{b}") |> range(start: time(v: {start}), stop: time(v: {lo * 1000})) '
                f'|> filter(fn: (r) => r._measurement == "{m}" and r.session == "{sess}") |> last()')
        sql = (f"SELECT * FROM \"{m}\" WHERE session = '{sess}' AND time < '{us_to_rfc3339(lo)}' "
               "ORDER BY time DESC LIMIT 5000")
        try:
            res = self._query(v1, flux, sql)
        except StoreError:
            return {}
        last: dict[str, float] = {}
        if self.v == 2:                                            # long format: one row per field
            for r in res:
                if r.get("_field") and r.get("_value") not in (None, ""):
                    last[r["_field"]] = float(r["_value"])
        elif self.v == 1:                                          # LAST(*) -> columns "last_<field>"
            for r in self._rows(res):
                for k, val in r.items():
                    if k.startswith("last_") and val is not None:
                        last[k[5:]] = float(val)
        else:                                                      # newest rows first: the first value of a column wins
            for r in self._rows(res):
                for k, val in r.items():
                    if k not in last and val not in (None, "") and k not in ("time", "session"):
                        last[k] = val
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
        elif self.v == 2:
            self._http("GET", "/health")
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
        cur.execute(f"CREATE TABLE IF NOT EXISTS {self.t}(time timestamptz NOT NULL, session text NOT NULL,"
                    " sig integer NOT NULL, value double precision)")
        c.commit()
        try:                                                      # a plain PostgreSQL works too, just without hypertables
            cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            cur.execute(f"SELECT create_hypertable('{self.t}', 'time', if_not_exists => TRUE)")
            c.commit()
            cur.execute(f"ALTER TABLE {self.t} SET (timescaledb.compress, timescaledb.compress_segmentby = 'session, sig')")
            cur.execute(f"SELECT add_compression_policy('{self.t}', INTERVAL '7 days', if_not_exists => TRUE)")
            c.commit()
        except Exception:
            c.rollback()
        cur.execute(f"CREATE INDEX IF NOT EXISTS {self.t}_sess_idx ON {self.t}(session, sig, time DESC)")
        c.commit()

    def begin(self, meta):
        self.sid = meta.get("id") or new_session_id()
        m = _meta_json(meta)
        cur = self.conn.cursor()
        cur.execute(f"INSERT INTO {self.ts}(id,name,start_us,end_us,ip,tab,conf,mode,signals,fields)"
                    " VALUES(%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                    (self.sid, m.get("name", ""), m["start_us"], m.get("ip", ""), m.get("tab", ""), m.get("conf", ""),
                     m.get("mode", "changes"), m["signals"], m["fields"]))
        self.conn.commit()
        return self.sid

    def write(self, rows):
        data = [(us_to_rfc3339(t), self.sid, i, None if v != v else float(v)) for t, d in rows for i, v in d.items()]
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
        cur.execute(f"SELECT id,name,start_us,end_us,ip,tab,conf,mode,signals,fields FROM {self.ts} ORDER BY start_us DESC")
        keys = ("id", "name", "start_us", "end_us", "ip", "tab", "conf", "mode", "signals", "fields")
        return [_meta_back(dict(zip(keys, r))) for r in cur.fetchall()]

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
        return SqliteBackend(p if os.path.isabs(p) else os.path.join(base_dir, p))
    if k in ("influx1", "influx2", "influx3"):
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
                            [(t, json.dumps({str(i): v for i, v in d.items()})) for t, d in rows])
        self.db.commit()

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM q").fetchone()[0]

    def peek(self, n: int) -> tuple[int, list]:
        """(last id, rows) of the oldest `n` rows; delete them with remove(last id) once delivered."""
        cur = self.db.execute("SELECT id,t,d FROM q ORDER BY id LIMIT ?", (n,)).fetchall()
        rows = [(t, {int(k): (math.nan if v is None else v) for k, v in json.loads(d).items()}) for _, t, d in cur]
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
                "mode": cfg.mode, "signals": [s.to_dict() for s in signals], "fields": self.fields}
        self._meta, self._base_dir, self.session = meta, base_dir, meta["id"]
        self.backend = backend
        if self.backend is None and cfg.kind == "sqlite":        # local file: a wrong path is reported at once
            self.backend = open_backend(cfg, base_dir)
        if self.backend is not None:
            self.backend.begin(meta)                             # network targets connect in the writer thread (retries)
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
            except (sqlite3.Error, OSError):
                self.spool = None                                # no disk buffer: memory only
        self._stop = threading.Event()
        self._last_us = meta["start_us"]
        self._deadline = float("inf")
        self.thread = threading.Thread(target=self._run_spool if self.spool else self._run, daemon=True,
                                       name="StoreWriter")
        self.thread.start()

    def write(self, t: float, values) -> None:
        key = self._key_s > 0 and t >= self._next_key
        if key:                                                  # keyframe: the full state again (starting point for range reads)
            self._next_key = t + self._key_s
        idx = self.filter.changed(values, force=key)
        if not idx:
            return
        us = to_us(self.start_wall, t)
        self._last_us = us
        row = (us, {i: (values[i] if i < len(values) else math.nan) for i in idx})
        try:
            self.q.put_nowait(row)
        except queue.Full:
            try:
                self.q.get_nowait()                              # the database is far behind: drop the oldest
            except queue.Empty:
                pass
            self.dropped += 1
            self.q.put_nowait(row)

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
        folder = os.path.dirname(self.spool.path)
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not (name.startswith("spool_") and name.endswith(".db")) or path == self.spool.path:
                continue
            old = None
            try:
                old = Spool(path, 0)
                meta, target = old.get_meta()
                if target != self.cfg.describe() or not meta.get("id"):
                    old.close()
                    continue
                if old.count():
                    b = open_backend(self.cfg, self._base_dir)
                    b.begin(meta)
                    while old.count():
                        last, rows = old.peek(20000)
                        b.write(rows)
                        old.remove(last)
                        self.written += len(rows)
                    b.close()
                old.close(delete=True)
            except Exception:
                if old is not None:
                    old.close()                                  # still unreachable: next run tries again

    def _run_spool(self) -> None:
        sp = self.spool
        backoff, next_try, recovered = 1.0, 0.0, False
        while True:
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
        if self.backend is not None:
            try:
                self.backend.end(self._last_us)
            except Exception:
                pass
            self.backend.close()
        if self.spool is not None:
            self.spool.close(delete=not self.spooled)            # an empty buffer is removed; a full one waits for the next run
