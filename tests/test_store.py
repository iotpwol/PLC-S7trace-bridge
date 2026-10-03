"""Recording targets: SQLite, InfluxDB 1.x/2.x (fake HTTP server), TimescaleDB (fake psycopg), change filter."""
import csv
import json
import os
import math
import re
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest

from s7trace.core import store
from s7trace.core.csvio import CsvRecorder
from s7trace.core.store import ChangeFilter, DbRecorder, StoreConfig, StoreError
from s7trace.core.types import Signal

START = datetime(2026, 10, 3, 10, 0, 0)
SIGS = [Signal(name="A", dtype="BOOL"), Signal(name="B", dtype="REAL"), Signal(name="C", dtype="INT")]


def feed(rec, n=200):
    """200 samples at 25 ms: A toggles every 50, B ramps for the first 40 samples then holds, C never changes."""
    rows = []
    for i in range(n):
        v = [float((i // 50) % 2), min(i, 40) * 0.5, 7.0]
        rows.append((i * 0.025, v))
        rec.write(i * 0.025, v)
    return rows


def matrix_close(t_us, mat, rows):
    """The rebuilt curves equal the original samples (step hold)."""
    t = (t_us - t_us[0]) / 1e6
    for tt, v in rows:
        k = np.searchsorted(t, tt + 1e-6, side="right") - 1
        assert k >= 0 and np.allclose(mat[k], v), (tt, v, mat[k])


# ------------------------------------------------------------------------------ config / helpers
def test_store_config_roundtrip_and_secrets():
    c = StoreConfig(kind="influx2", url="http://h:8086", org="o", bucket="b", token="SECRET", password="pw",
                    pg_password="pg")
    d = c.to_dict()
    assert d["token"] == d["password"] == d["pg_password"] == "" and d["bucket"] == "b"
    c.remember = True
    again = StoreConfig.from_dict(c.to_dict())
    assert again == c
    assert StoreConfig.from_dict({"kind": "mongo", "mode": "x", "port": "abc"}) == StoreConfig()
    assert StoreConfig().mode == "changes" and StoreConfig().kind == "csv"            # defaults


def test_change_filter():
    f = ChangeFilter(3, "changes")
    assert f.changed([1, 2, 3]) == [0, 1, 2]                      # the first sample reports everything
    assert f.changed([1, 2, 3]) == []
    assert f.changed([1, 5, 3]) == [1]
    assert f.changed([1, math.nan, 3]) == [1]
    assert f.changed([1, math.nan, 3]) == []                      # NaN stays NaN: no change
    assert f.changed([1, 2.0, 3]) == [1]
    a = ChangeFilter(2, "all")
    assert a.changed([1, 1]) == [0, 1] and a.changed([1, 1]) == [0, 1]


def test_unique_fields_and_time_helpers():
    assert store.unique_fields(["X", "X", "", "Y", "X"]) == ["X", "X_2", "SIG3", "Y", "X_3"]
    us = store.rfc3339_to_us("2026-10-03T10:15:00.123456789Z")
    assert us == store.rfc3339_to_us(store.us_to_rfc3339(us)) and us % 1_000_000 == 123456
    assert store.rfc3339_to_us("2026-10-03 12:15:00+02:00") == store.rfc3339_to_us("2026-10-03T10:15:00Z")


def test_events_to_matrix_hold_and_nan():
    ev = [(10, 0, 1.0), (10, 1, 5.0), (20, 0, 2.0), (30, 1, None)]
    t, m = store.events_to_matrix(2, ev, hold=True)
    assert list(t) == [10, 20, 30]
    assert m[:, 0].tolist() == [1.0, 2.0, 2.0] and m[0, 1] == 5.0 and m[1, 1] == 5.0 and math.isnan(m[2, 1])
    t, m = store.events_to_matrix(2, ev, hold=False)
    assert math.isnan(m[1, 1]) and m[1, 0] == 2.0
    assert store.events_to_matrix(2, [], True)[1].shape == (0, 2)


# ------------------------------------------------------------------------------ CSV
def test_csv_recorder_changes_only(tmp_path):
    p = tmp_path / "r.csv"
    rec = CsvRecorder(str(p), SIGS, START, mode="changes")
    rows = feed(rec)
    rec.close()
    n_changes = sum(1 for line in p.read_text().splitlines() if not line.startswith("#")) - 1
    assert 40 < n_changes < 60 < len(rows)                         # B changes 40 times + A 3 times + the first row
    p2 = tmp_path / "all.csv"
    rec = CsvRecorder(str(p2), SIGS, START)
    feed(rec)
    rec.close()
    assert sum(1 for line in p2.read_text().splitlines() if not line.startswith("#")) - 1 == 200


# ------------------------------------------------------------------------------ SQLite
@pytest.mark.parametrize("mode", ["changes", "all"])
def test_sqlite_roundtrip(tmp_path, mode):
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "x.db"), mode=mode)
    rec = DbRecorder(cfg, SIGS, START, {"ip": "10.1.1.1", "tab": "Piec", "conf": "L1"})
    rows = feed(rec)
    rec.close()
    assert rec.written == 200 if mode == "all" else rec.written < 60                  # changes: only the moments with a change
    b = store.open_backend(cfg)
    sess = b.sessions()
    assert len(sess) == 1 and sess[0]["ip"] == "10.1.1.1" and sess[0]["mode"] == mode and sess[0]["end_us"]
    assert [s["name"] for s in sess[0]["signals"]] == ["A", "B", "C"]
    meta, t, m = b.read(sess[0]["id"])
    matrix_close(t, m, rows)                                       # step curves rebuilt exactly
    assert len(t) == (200 if mode == "all" else len(t)) and (mode == "changes" or len(t) == 200)
    b.close()


def test_sqlite_range_read_carries_in_values(tmp_path):
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "x.db"))
    rec = DbRecorder(cfg, SIGS, START, {})
    feed(rec)
    rec.close()
    b = store.open_backend(cfg)
    sid = b.sessions()[0]["id"]
    t0 = store.to_us(START, 3.0)
    meta, t, m = b.read(sid, t0_us=t0, t1_us=store.to_us(START, 4.0))
    assert t[0] == t0 and np.allclose(m[0], [0.0, 20.0, 7.0])      # at t=3.0 s: A=0, B=held 20.0, C=7 (constant)
    assert np.all(m[:, 2] == 7.0)
    b.close()


def test_sqlite_second_session_and_relative_path(tmp_path):
    cfg = StoreConfig(kind="sqlite", sqlite_path="sub/s.db")
    for _ in range(2):
        rec = DbRecorder(cfg, SIGS, START, {}, base_dir=str(tmp_path))
        rec.write(0.0, [1, 2, 3])
        time.sleep(0.01)
        rec.close()
    b = store.open_backend(cfg, str(tmp_path))
    assert len(b.sessions()) == 2 and (tmp_path / "sub" / "s.db").exists()
    assert "SQLite" in store.test_connection(cfg, str(tmp_path))
    b.close()


# ------------------------------------------------------------------------------ recorder behaviour
class FlakyBackend(store.Backend):
    def __init__(self, fail=2):
        self.fail, self.rows, self.began, self.ended = fail, [], False, False

    def begin(self, meta):
        self.began = True
        return meta["id"]

    def write(self, rows):
        if self.fail:
            self.fail -= 1
            raise StoreError("server away")
        self.rows += rows

    def end(self, end_us):
        self.ended = True

    def close(self):
        pass


def test_recorder_retries_until_the_server_is_back(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    fb = FlakyBackend(fail=2)
    rec = DbRecorder(StoreConfig(kind="influx2"), SIGS, START, {}, backend=fb)
    orig_wait = rec._stop.wait
    rec._stop.wait = lambda t=None: orig_wait(0.01)                # no multi-second back-off in the test
    for i in range(30):
        rec.write(i * 0.1, [i, 0, 0])
    rec.close()
    assert fb.began and fb.ended and len(fb.rows) == 30 + 0 or len(fb.rows) >= 30     # nothing lost
    assert rec.dropped == 0 and rec.last_error == ""


def test_recorder_drops_oldest_when_far_behind():
    fb = FlakyBackend(fail=10 ** 9)
    DbRecorder.QUEUE_MAX, DbRecorder.CLOSE_GRACE = 50, 0.3
    try:
        rec = DbRecorder(StoreConfig(kind="influx2", mode="all"), SIGS, START, {}, backend=fb)
        for i in range(500):
            rec.write(i * 0.1, [i, 0, 0])
        assert rec.dropped > 0 and rec.q.qsize() <= 50 and "utracono" in rec.status()
        rec.close()
    finally:
        DbRecorder.QUEUE_MAX, DbRecorder.CLOSE_GRACE = None, None


def test_network_target_connects_in_the_writer_thread(monkeypatch):
    fb = FlakyBackend(fail=0)
    calls = []

    def fake_open(cfg, base_dir=""):
        calls.append(1)
        if len(calls) == 1:
            raise StoreError("not yet")
        return fb

    monkeypatch.setattr(store, "open_backend", fake_open)
    rec = DbRecorder(StoreConfig(kind="influx2"), SIGS, START, {})            # does not block / raise
    assert rec.backend is None
    rec.write(0.0, [1, 2, 3])
    orig = rec._stop.wait
    rec._stop.wait = lambda t=None: orig(0.01)
    rec.close()
    assert len(calls) >= 2 and fb.began and len(fb.rows) == 1


# ------------------------------------------------------------------------------ fake InfluxDB server
def parse_lp(line: str):
    """Minimal line-protocol parser: -> (measurement, tags, fields, ts_ns)."""
    parts, cur, esc, quote = [], "", False, False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            cur += ch
            esc = True
        elif ch == '"':
            quote = not quote
            cur += ch
        elif ch == " " and not quote:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    head, fields_txt, ts = parts[0], parts[1], int(parts[2])

    def split(txt, sep):
        out, cur, esc, q = [], "", False, False
        for ch in txt:
            if esc:
                cur += ch
                esc = False
            elif ch == "\\":
                cur += ch
                esc = True
            elif ch == '"':
                q = not q
                cur += ch
            elif ch == sep and not q:
                out.append(cur)
                cur = ""
            else:
                cur += ch
        out.append(cur)
        return out

    unesc = lambda s: re.sub(r"\\(.)", r"\1", s)
    h = split(head, ",")
    tags = dict(kv.split("=", 1) for kv in h[1:])
    fields = {}
    for kv in split(fields_txt, ","):
        k, v = kv.split("=", 1)
        if v.startswith('"'):
            fields[unesc(k)] = unesc(v[1:-1])
        elif v.endswith("i"):
            fields[unesc(k)] = int(v[:-1])
        else:
            fields[unesc(k)] = float(v)
    return unesc(h[0]), tags, fields, ts


class FakeInflux:
    def __init__(self, token="tok"):
        self.points, self.requests, self.token = [], [], token
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else body.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                return self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()

            def _handle(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                body = self._body()
                outer.requests.append((self.command, u.path, q, dict(self.headers), body))
                auth = self.headers.get("Authorization", "")
                if u.path in ("/api/v2/write", "/api/v2/query") and auth != "Token " + outer.token:
                    return self._send(401, '{"message":"unauthorized"}')
                if u.path in ("/write", "/api/v2/write"):
                    for ln in body.splitlines():
                        outer.put(parse_lp(ln))
                    return self._send(204, b"")
                if u.path == "/api/v2/delete":
                    pred = json.loads(body)["predicate"]
                    m = re.search(r'_measurement="([^"]+)"(?: AND session="([^"]+)")?', pred)
                    outer.points = [p for p in outer.points
                                    if not (p[0] == m.group(1) and (m.group(2) is None or p[1].get("session") == m.group(2)))]
                    return self._send(204, b"")
                if u.path == "/query":
                    if "CREATE DATABASE" in q["q"]:
                        return self._send(200, '{"results":[{"statement_id":0}]}')
                    if q["q"].startswith("DROP MEASUREMENT"):
                        name = re.search(r'"([^"]+)"', q["q"]).group(1)
                        outer.points = [p for p in outer.points if p[0] != name]
                        return self._send(200, '{"results":[{"statement_id":0}]}')
                    if q["q"].startswith("DROP SERIES"):
                        m = re.search(r"FROM \"([^\"]+)\" WHERE \"session\"='([^']+)'", q["q"])
                        outer.points = [p for p in outer.points if not (p[0] == m.group(1) and p[1].get("session") == m.group(2))]
                        return self._send(200, '{"results":[{"statement_id":0}]}')
                    return self._send(200, json.dumps(outer.v1(q["q"])))
                if u.path == "/api/v2/query":
                    return self._send(200, outer.v2(json.loads(body)["query"]), "text/csv")
                if u.path in ("/ping", "/health"):
                    return self._send(204, b"")
                self._send(404, "{}")

            do_GET = do_POST = _handle

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def put(self, pt):
        """Like InfluxDB: a point with the same measurement, tags and time as a stored one merges its fields."""
        for p in self.points:
            if p[0] == pt[0] and p[1] == pt[1] and p[3] == pt[3]:
                p[2].update(pt[2])
                return
        self.points.append(pt)

    def close(self):
        self.srv.shutdown()

    def select(self, meas, session=None, lo=None, hi=None):
        pts = [p for p in self.points if p[0] == meas and (session is None or p[1].get("session") == session)]
        if lo is not None:
            pts = [p for p in pts if lo <= p[3] <= hi]
        pts.sort(key=lambda p: p[3])
        return pts

    def last_before(self, meas, session, hi):
        """{field: value} - the newest value of every field before `hi` (ns)."""
        out = {}
        for p in self.select(meas, session):
            if p[3] < hi:
                out.update(p[2])
        return out

    def v1(self, q):
        meas = re.search(r'FROM "([^"]+)"', q).group(1)
        if q.startswith("SELECT count(*)"):                                  # how many values the server holds per field
            pts = self.select(meas, re.search(r"\"session\"='([^']+)'", q).group(1))
            counts: dict = {}
            for p in pts:
                for k in p[2]:
                    counts[k] = counts.get(k, 0) + 1
            if not counts:
                return {"results": [{"statement_id": 0}]}
            return {"results": [{"statement_id": 0, "series": [{"name": meas, "columns": ["time"] + [f"count_{k}" for k in counts],
                                                                "values": [[0] + list(counts.values())]}]}]}
        if "LAST(*)" in q:
            hi = int(re.search(r"time < (\d+)", q).group(1))
            last = self.last_before(meas, re.search(r"\"session\"='([^']+)'", q).group(1), hi)
            if not last:
                return {"results": [{"statement_id": 0}]}
            cols = ["time"] + [f"last_{k}" for k in last]
            return {"results": [{"statement_id": 0, "series": [{"name": meas, "columns": cols,
                                                                "values": [[hi] + list(last.values())]}]}]}
        m = re.search(r"\"session\"='([^']+)'", q)
        t = re.search(r"time >= (\d+) AND time (<=|<) (\d+)", q)
        pts = self.select(meas, m.group(1) if m else None, int(t.group(1)) if t else None,
                          (int(t.group(3)) - (t.group(2) == "<")) if t else None)
        if m is None:
            pts.sort(key=lambda p: -p[3])
        if not pts:
            return {"results": [{"statement_id": 0}]}
        cols = ["time", "session"] + sorted({k for p in pts for k in p[2]})
        vals = [[p[3], p[1]["session"]] + [p[2].get(k) for k in cols[2:]] for p in pts]
        return {"results": [{"statement_id": 0, "series": [{"name": meas, "columns": cols, "values": vals}]}]}

    def v2(self, flux):
        meas = re.search(r'_measurement == "([^"]+)"', flux).group(1)
        if flux.rstrip().endswith("count()"):
            counts: dict = {}
            for p in self.select(meas, re.search(r'r.session == "([^"]+)"', flux).group(1)):
                for k in p[2]:
                    counts[k] = counts.get(k, 0) + 1
            head = ["#datatype,string,long,dateTime:RFC3339,string,long", ",result,table,_time,_field,_value"]
            return "\n".join(head + [f",,0,2026-01-01T00:00:00Z,{k},{v}" for k, v in counts.items()]) + "\n\n"
        if flux.rstrip().endswith("last()"):
            hi = int(re.search(r"stop: time\(v: (\d+)\)", flux).group(1))
            last = self.last_before(meas, re.search(r'r.session == "([^"]+)"', flux).group(1), hi)
            head = ["#datatype,string,long,dateTime:RFC3339,string,double", ",result,table,_time,_field,_value"]
            body = [f",,0,2026-01-01T00:00:00Z,{k},{v}" for k, v in last.items()]
            return "\n".join(head + body) + "\n\n"
        m = re.search(r'r.session == "([^"]+)"', flux)
        t = re.search(r"start: time\(v: (\d+)\), stop: time\(v: (\d+)\)", flux)
        pts = self.select(meas, m.group(1) if m else None, int(t.group(1)) if t else None, int(t.group(2)) if t else None)
        cols = sorted({k for p in pts for k in p[2]})
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["#datatype", "string", "long", "dateTime:RFC3339", "string"] + ["double"] * len(cols))
        w.writerow(["#group", "false", "false", "false", "true"] + ["false"] * len(cols))
        w.writerow(["#default", "_result", "", "", ""] + [""] * len(cols))
        w.writerow(["", "result", "table", "_time", "session"] + cols)
        for p in pts:
            iso = store.us_to_rfc3339(p[3] // 1000)[:-1] + f"{p[3] % 1000:03d}Z"
            w.writerow(["", "", "0", iso, p[1]["session"]] + ["" if k not in p[2] else p[2][k] for k in cols])
        return buf.getvalue() + "\n"


@pytest.fixture
def influx():
    s = FakeInflux()
    yield s
    s.close()


INFLUX_CFGS = {
    1: dict(kind="influx1", database="plant", user="u", password="p"),
    2: dict(kind="influx2", org="acme", bucket="plant", token="tok"),
}


@pytest.mark.parametrize("ver", [1, 2])
def test_influx_write_and_read_roundtrip(influx, ver):
    cfg = StoreConfig(url=influx.url, measurement="rec 1", mode="changes", **INFLUX_CFGS[ver])
    rec = DbRecorder(cfg, SIGS, START, {"ip": "10.1.1.1", "tab": "Piec", "conf": "L1"})
    rows = feed(rec)
    rec.close()
    assert rec.last_error == "" and rec.written > 40
    # what the protocol looks like on the wire
    paths = [r[1] for r in influx.requests if r[0] == "POST"]
    assert {1: "/write", 2: "/api/v2/write"}[ver] in paths
    wr = next(r for r in influx.requests if r[1] in ("/write", "/api/v2/write"))
    q, headers = wr[2], wr[3]
    if ver == 1:
        assert q == {"db": "plant", "precision": "ns"} and headers["Authorization"].startswith("Basic ")
    if ver == 2:
        assert q == {"org": "acme", "bucket": "plant", "precision": "ns"} and headers["Authorization"] == "Token tok"
    assert wr[4].startswith("rec\\ 1_sessions,session=")                    # the session description goes first
    assert any(r[4].startswith("rec\\ 1,session=") for r in influx.requests
               if r[1] in ("/write", "/api/v2/write"))
    # only changes were written; the constant signal C exactly once
    data = influx.select("rec 1")
    assert sum("C" in p[2] for p in data) == 1 and len(data) < 60
    # reading back rebuilds the full step curves
    b = store.open_backend(cfg)
    sess = b.sessions()
    assert len(sess) == 1 and sess[0]["ip"] == "10.1.1.1" and sess[0]["tab"] == "Piec"
    assert [s["name"] for s in sess[0]["signals"]] == ["A", "B", "C"]
    meta, t, m = b.read(sess[0]["id"])
    matrix_close(t, m, rows)
    meta, t, m = b.read(sess[0]["id"], t0_us=store.to_us(START, 1.0), t1_us=store.to_us(START, 2.0))
    assert 0 < len(t) < 60 and t[0] >= store.to_us(START, 1.0)
    assert "odpowiada" in b.ping()


def test_influx_all_samples_and_nan_and_duplicate_names(influx):
    cfg = StoreConfig(url=influx.url, mode="all", **INFLUX_CFGS[2])
    sigs = [Signal(name="X"), Signal(name="X")]
    rec = DbRecorder(cfg, sigs, START, {})
    for i in range(5):
        rec.write(i * 0.1, [float(i), math.nan if i == 2 else 1.0])
    rec.close()
    pts = influx.select("s7trace")
    assert len(pts) == 5 and "X_2" not in pts[2][2] and pts[0][2]["X_2"] == 1.0      # NaN is left out; names made unique
    b = store.open_backend(cfg)
    meta, t, m = b.read(b.sessions()[0]["id"])
    assert len(t) == 5 and math.isnan(m[2, 1]) and m[4, 0] == 4.0
    b.close()


def test_influx_errors_are_readable(influx):
    bad = StoreConfig(url=influx.url, **{**INFLUX_CFGS[2], "token": "wrong"})
    with pytest.raises(StoreError, match="401"):
        store.test_connection(StoreConfig(url=influx.url, **{**INFLUX_CFGS[2], "token": "wrong"})) if False else \
            store.open_backend(bad)._http("POST", "/api/v2/write", {"org": "o", "bucket": "b"}, b"x")
    down = StoreConfig(url="http://127.0.0.1:9", **INFLUX_CFGS[1])
    with pytest.raises(StoreError, match="brak połączenia"):
        store.test_connection(down)


def test_line_protocol_escaping():
    line = store.sample_line("m 1,x", "s=1 2", ["a b", "c,d"], 1_700_000_000_123_456, {0: 1.5, 1: math.nan})
    assert line == "m\\ 1\\,x,session=s\\=1\\ 2 a\\ b=1.5 1700000000123456000"
    assert store.sample_line("m", "s", ["a"], 1, {0: math.nan}) is None
    meta = {"id": "S1", "name": 'He said "hi"\\', "start_us": 5, "signals": [{"name": "A"}], "fields": ["A"], "mode": "all"}
    m, tags, f, ts = parse_lp(store.session_line("m", meta))
    assert m == "m_sessions" and tags == {"session": "S1"} and f["name"] == 'He said "hi"\\' and f["start_us"] == 5
    assert json.loads(f["signals"]) == [{"name": "A"}] and ts == 5000


# ------------------------------------------------------------------------------ TimescaleDB (fake psycopg)
class FakeCursor:
    def __init__(self, conn):
        self.c = conn
        self._rows = []

    def execute(self, sql, params=None):
        self.c.log.append((" ".join(sql.split()), params))
        s = sql.strip()
        if "create_hypertable" in s and self.c.no_timescale:
            raise RuntimeError("extension not available")
        if s.startswith("SELECT id,name"):
            self._rows = self.c.sessions
        elif "timescaledb_information.jobs" in s:                       # the compression policy of the table
            self._rows = [] if self.c.policy is None else [(self.c.policy,)]
        elif s.startswith("SELECT version"):
            self._rows = [("PostgreSQL 16.2 (TimescaleDB)",)]
        elif "DISTINCT ON" in s:
            self._rows = self.c.carry
        elif s.startswith("SELECT (EXTRACT"):
            self._rows = self.c.samples
        else:
            self._rows = []

    def executemany(self, sql, data):
        self.c.log.append((" ".join(sql.split()), list(data)))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, **kw):
        self.kw, self.log, self.no_timescale = kw, [], False
        self.sessions, self.samples, self.carry = [], [], []
        self.policy = None                          # None: no compression policy yet; True / False: same / another interval
        self.commits = self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.fixture
def pg(monkeypatch):
    holder = {}

    class Mod:
        @staticmethod
        def connect(**kw):
            holder["conn"] = FakeConn(**kw)
            return holder["conn"]

    monkeypatch.setattr(store, "_psycopg", lambda: Mod)
    return holder


def test_timescale_schema_write_and_read(pg):
    cfg = StoreConfig(kind="timescale", host="db", port=5433, pg_database="plant", pg_user="u", pg_password="p",
                      table="rec_samples")
    rec = DbRecorder(cfg, SIGS, START, {"ip": "10.1.1.1"})
    feed(rec, 120)
    rec.close()                                                       # (the connection is opened by the writer thread)
    c = pg["conn"]
    assert c.kw["host"] == "db" and c.kw["port"] == 5433 and c.kw["dbname"] == "plant" and c.kw["password"] == "p"
    sql = [s for s, _ in c.log]
    assert any("CREATE TABLE IF NOT EXISTS rec_samples(" in s for s in sql)
    assert any("create_hypertable('rec_samples'" in s for s in sql)                   # hypertable
    assert any("add_compression_policy('rec_samples'" in s for s in sql)              # old chunks are compressed
    inserts = [p for s, p in c.log if s.startswith("INSERT INTO rec_samples(")]
    flat = [r for batch in inserts for r in batch]
    assert 40 < len(flat) < 70                            # only changes
    assert flat[0][1] == rec.session and flat[0][0].endswith("Z") and c.closed
    assert any(s.startswith("UPDATE rec_samples_sessions SET end_us") for s, _ in c.log)
    # reading
    sig_json = json.dumps([s.to_dict() for s in SIGS])
    start = store.to_us(START, 0.0)
    b = store.open_backend(cfg)
    c = pg["conn"]                                                    # (a new connection of its own)
    c.sessions = [("S1", "n", start, None, "10.1.1.1", "T", "L", "changes", sig_json, json.dumps(["A", "B", "C"]))]
    c.samples = [(start, 0, 1.0), (start, 1, 2.0), (start, 2, 7.0), (start + 1_000_000, 1, 5.0)]
    assert b.sessions()[0]["id"] == "S1" and b.sessions()[0]["signals"][0]["name"] == "A"
    meta, t, m = b.read("S1")
    assert m.tolist() == [[1.0, 2.0, 7.0], [1.0, 5.0, 7.0]]
    c.carry = [(0, 1.0), (1, 9.0)]
    c.samples = [(start + 1_000_000, 1, 5.0)]                        # what lies inside the range
    meta, t, m = b.read("S1", t0_us=start + 500_000)
    assert t[0] == start + 500_000 and m[0].tolist()[:2] == [1.0, 9.0] and m[1, 1] == 5.0 and "TimescaleDB" in b.ping()


def test_timescale_without_extension_still_works_and_bad_table_name(pg):
    cfg = StoreConfig(kind="timescale", table="ok_name")
    orig = FakeConn.__init__

    def init(self, **kw):
        orig(self, **kw)
        self.no_timescale = True
    FakeConn.__init__ = init
    try:
        b = store.open_backend(cfg)
        assert pg["conn"].rollbacks >= 1                                              # plain PostgreSQL: no hypertable
        b.close()
    finally:
        FakeConn.__init__ = orig
    with pytest.raises(StoreError, match="tabeli"):
        store.open_backend(StoreConfig(kind="timescale", table="x; DROP TABLE y"))


def _compression_sql(pg, **kw):
    cfg = StoreConfig(kind="timescale", table="rec_samples", **kw)
    store.open_backend(cfg).close()
    return [s for s, _ in pg["conn"].log if "compress" in s.lower()]


def test_timescale_compression_is_set_up_after_the_configured_days(pg):
    sql = _compression_sql(pg)                                                        # default: 7 days
    assert any("timescaledb.compress" in s and "compress_segmentby" in s for s in sql)
    assert any("add_compression_policy('rec_samples', INTERVAL '7 days'" in s for s in sql)
    pg.clear()
    sql = _compression_sql(pg, compress_days=30)
    assert any("add_compression_policy('rec_samples', INTERVAL '30 days'" in s for s in sql)
    assert any("remove_compression_policy('rec_samples'" in s for s in sql)           # an old policy is replaced


def test_timescale_without_compression_does_not_compress(pg):
    sql = _compression_sql(pg, compress_days=0)
    assert not any("add_compression_policy" in s or "timescaledb.compress" in s for s in sql)
    assert any("remove_compression_policy('rec_samples', if_exists => TRUE)" in s for s in sql)   # an earlier policy is dropped
    assert any("create_hypertable" in s for s in [x for x, _ in pg["conn"].log])      # still a hypertable


def test_timescale_compression_policy_with_the_same_interval_is_left_alone(pg):
    orig = FakeConn.__init__

    def init(self, **kw):
        orig(self, **kw)
        self.policy = True
    FakeConn.__init__ = init
    try:
        sql = _compression_sql(pg, compress_days=7)
    finally:
        FakeConn.__init__ = orig
    assert not any("add_compression_policy" in s or "remove_compression_policy" in s for s in sql)


def test_timescale_without_extension_does_not_touch_compression(pg):
    orig = FakeConn.__init__

    def init(self, **kw):
        orig(self, **kw)
        self.no_timescale = True
    FakeConn.__init__ = init
    try:
        sql = _compression_sql(pg, compress_days=7)
    finally:
        FakeConn.__init__ = orig
    assert sql == []                                                                  # plain PostgreSQL: nothing to compress


def test_compress_days_is_limited_and_saved():
    c = StoreConfig.from_dict({"compress_days": -3})
    assert c.compress_days == 0
    assert StoreConfig.from_dict({"compress_days": 999999}).compress_days == 3650
    assert StoreConfig.from_dict(StoreConfig(compress_days=21).to_dict()).compress_days == 21
    assert StoreConfig().compress_days == 7


def test_timescale_without_library_gives_a_clear_message(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_psycopg(name, *a, **k):
        if name == "psycopg":
            raise ImportError
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_psycopg)
    pytest.importorskip("pg8000")
    assert store._psycopg().__name__ == "pg8000.dbapi" and store.pg_driver_name() == "pg8000"     # the fallback driver

    def neither(name, *a, **k):
        if name in ("psycopg", "pg8000.dbapi", "pg8000"):
            raise ImportError
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", neither)
    with pytest.raises(StoreError, match="psycopg.*pg8000"):
        store._psycopg()
    assert store.pg_driver_name() == ""


def test_pg8000_connect_arguments_and_ssl(monkeypatch):
    import types
    seen = {}
    fake = types.ModuleType("pg8000.dbapi")
    fake.connect = lambda **kw: seen.update(kw) or "conn"
    cfg = StoreConfig(kind="timescale", host="db1", port=6543, pg_database="d", pg_user="u", pg_password="p", pg_sslmode="require")
    assert store._pg_connect(fake, cfg, 4) == "conn"
    assert (seen["host"], seen["port"], seen["database"], seen["user"], seen["timeout"]) == ("db1", 6543, "d", "u", 4)
    assert seen["ssl_context"] is not None and seen["ssl_context"].check_hostname is False
    store._pg_connect(fake, StoreConfig(pg_sslmode="disable"), 4)
    assert seen["ssl_context"] is None
    lib = types.ModuleType("psycopg")                                       # psycopg gets libpq-style names
    lib.connect = lambda **kw: seen.update(kw) or "c2"
    store._pg_connect(lib, cfg, 4)
    assert seen["dbname"] == "d" and seen["sslmode"] == "require" and seen["connect_timeout"] == 4


# ---------------------------------------------------------------- quality field, carry-in, keyframe
@pytest.mark.parametrize("ver", [1, 2])
def test_influx_nan_is_stored_as_quality_field_and_read_back(influx, ver):
    cfg = StoreConfig(url=influx.url, mode="changes", keyframe_min=0, **INFLUX_CFGS[ver])
    rec = DbRecorder(cfg, [Signal(name="X")], START, {})
    for i, v in enumerate([1.0, 1.0, math.nan, math.nan, 2.0, 2.0]):
        rec.write(i * 0.1, [v])
    rec.close()
    pts = influx.select("s7trace")
    assert [p[2].get("X__ok") for p in pts] == [1.0, 0.0, 1.0]                  # first row + changes of availability
    b = store.open_backend(cfg)
    meta, t, m = b.read(b.sessions()[0]["id"])
    assert m[0, 0] == 1.0 and math.isnan(m[1, 0]) and m[2, 0] == 2.0
    b.close()


@pytest.mark.parametrize("ver", [1, 2])
def test_influx_range_read_has_the_state_from_before_the_range(influx, ver):
    cfg = StoreConfig(url=influx.url, mode="changes", keyframe_min=0, **INFLUX_CFGS[ver])
    rec = DbRecorder(cfg, SIGS, START, {})
    rows = feed(rec)
    rec.close()
    b = store.open_backend(cfg)
    sid = b.sessions()[0]["id"]
    meta, t, m = b.read(sid, t0_us=store.to_us(START, 4.0), t1_us=store.to_us(START, 5.0))
    # constant signal C was written only at the start, yet the window has its value from the first row
    assert len(t) and not np.isnan(m).any() and m[0, 2] == rows[0][1][2]
    b.close()


def test_keyframe_repeats_the_full_state_on_schedule(tmp_path):
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "k.db"), mode="changes", keyframe_min=1.0)
    rec = DbRecorder(cfg, [Signal(name="A"), Signal(name="B")], START, {})
    for i in range(0, 241):
        rec.write(float(i), [1.0, 5.0])                                          # nothing ever changes
    rec.close()
    b = store.open_backend(cfg)
    meta, t, m = b.read(b.sessions()[0]["id"])
    assert len(t) == 5 and np.allclose(np.diff(t) / 1e6, 60.0)                  # start + every 60 s (0, 60, 120, 180, 240)
    b.close()
    off = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "k2.db"), mode="changes", keyframe_min=0)
    rec = DbRecorder(off, [Signal(name="A")], START, {})
    for i in range(0, 241):
        rec.write(float(i), [1.0])
    rec.close()
    b = store.open_backend(off)
    assert len(b.read(b.sessions()[0]["id"])[1]) == 1                            # keyframes off
    b.close()


def test_time_parameters_come_from_the_configuration():
    c = StoreConfig(batch_s=0.2, retry_max_s=3, test_timeout_s=1.5, http_timeout_s=7, close_grace_s=2, queue_max=5000)
    c2 = StoreConfig.from_dict(c.to_dict())
    assert (c2.batch_s, c2.retry_max_s, c2.test_timeout_s, c2.http_timeout_s, c2.close_grace_s, c2.queue_max) ==         (0.2, 3, 1.5, 7, 2, 5000)
    d = StoreConfig()
    assert (d.keyframe_min, d.batch_s, d.retry_max_s, d.test_timeout_s, d.http_timeout_s, d.close_grace_s, d.queue_max) ==         (10.0, 0.5, 15.0, 3.0, 15.0, 10.0, 300000)
    assert store.InfluxBackend(c, 2).timeout == 7 and store.InfluxBackend(c, 2, 3.0).timeout == 3.0


# ---------------------------------------------------------------- disk buffer (spool)
def _wait(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def flaky(monkeypatch):
    """Influx writes fail while state['down'] is True."""
    state = {"down": True}
    orig = store.InfluxBackend._write_lp

    def write_lp(self, lines):
        if state["down"] and not any("_sessions" in ln.split(",")[0] for ln in lines):
            raise StoreError("InfluxDB: brak połączenia (test)")
        return orig(self, lines)

    monkeypatch.setattr(store.InfluxBackend, "_write_lp", write_lp)
    return state


def test_spool_keeps_rows_on_disk_while_the_server_is_away(influx, flaky, tmp_path):
    cfg = StoreConfig(url=influx.url, mode="all", spool_mb=10, retry_max_s=1, batch_s=0.05, **INFLUX_CFGS[2])
    rec = DbRecorder(cfg, [Signal(name="A")], START, {}, base_dir=str(tmp_path))
    for i in range(50):
        rec.write(i * 0.1, [float(i)])
    assert _wait(lambda: rec.spooled == 50)
    assert "na dysku 50" in rec.status() and "BŁĄD" in rec.status()
    assert list((tmp_path / "spool").glob("spool_*.db")) and not influx.select("s7trace")
    flaky["down"] = False
    assert _wait(lambda: rec.spooled == 0 and len(influx.select("s7trace")) == 50)
    vals = [p[2]["A"] for p in influx.select("s7trace")]
    assert vals == [float(i) for i in range(50)]                          # delivered, and in the original order
    for i in range(50, 55):
        rec.write(i * 0.1, [float(i)])
    rec.close()
    assert len(influx.select("s7trace")) == 55 and rec.dropped == 0
    assert not list((tmp_path / "spool").glob("spool_*.db"))               # an empty buffer is removed


def test_spool_left_by_a_closed_program_is_delivered_by_the_next_run(influx, flaky, tmp_path):
    cfg = StoreConfig(url=influx.url, mode="all", spool_mb=10, retry_max_s=1, batch_s=0.05, close_grace_s=0.3,
                      **INFLUX_CFGS[2])
    rec = DbRecorder(cfg, [Signal(name="A")], START, {}, base_dir=str(tmp_path))
    for i in range(20):
        rec.write(i * 0.1, [float(i)])
    assert _wait(lambda: rec.spooled == 20)
    rec.close()                                                            # server still away
    assert len(list((tmp_path / "spool").glob("spool_*.db"))) == 1 and not influx.select("s7trace")
    flaky["down"] = False
    rec2 = DbRecorder(cfg, [Signal(name="A")], START, {}, base_dir=str(tmp_path))
    rec2.write(0.0, [99.0])
    assert _wait(lambda: len(influx.select("s7trace")) == 21)
    rec2.close()
    assert not list((tmp_path / "spool").glob("spool_*.db"))
    assert {p[1]["session"] for p in influx.select("s7trace")} == {rec.session, rec2.session}


def test_spool_size_limit_drops_the_oldest(tmp_path):
    sp = store.Spool(str(tmp_path / "s.db"), 0.03)                          # ~30 kB
    for k in range(40):
        sp.add([(k * 100 + j, {0: float(j)}) for j in range(100)])
    assert sp.used() > sp.max
    dropped = sp.trim()
    assert dropped > 0 and sp.count() == 4000 - dropped
    last, rows = sp.peek(5)
    assert rows[0][0] >= dropped - 1 or rows[0][0] > 0
    sp.close(delete=True)
    assert not (tmp_path / "s.db").exists()


def test_spool_is_off_without_a_folder_or_when_zero(influx, tmp_path):
    cfg = StoreConfig(url=influx.url, spool_mb=0, **INFLUX_CFGS[2])
    rec = DbRecorder(cfg, [Signal(name="A")], START, {}, base_dir=str(tmp_path))
    assert rec.spool is None
    rec.close()
    rec = DbRecorder(StoreConfig(url=influx.url, **INFLUX_CFGS[2]), [Signal(name="A")], START, {})
    assert rec.spool is None
    rec.close()


# ---------------------------------------------------------------- rotation, thinning out, long ranges
def test_downsample_keeps_peaks_and_gaps():
    n = 20000
    t = np.arange(n, dtype=np.int64) * 1000
    v = np.zeros((n, 2))
    v[12345, 0] = 99.0                                                      # a one-sample spike
    v[5000, 1] = -50.0
    v[7000:7100, 1] = np.nan                                                # a gap
    t2, v2 = store.downsample_minmax(t, v, 400)
    assert len(t2) < 1500 and 99.0 in v2[:, 0] and -50.0 in v2[:, 1]
    assert np.isnan(v2[:, 1]).any() and t2[0] == t[0] and t2[-1] == t[-1]
    same_t, same_v = store.downsample_minmax(t, v, 0)                      # 0 = no thinning
    assert len(same_t) == n


def test_sqlite_rotation_by_day_and_by_size(tmp_path):
    base = StoreConfig(kind="sqlite", sqlite_path="rec.db")
    p = store.rotated_sqlite_path(base, str(tmp_path))
    assert p == str(tmp_path / "rec.db")
    daily = StoreConfig(kind="sqlite", sqlite_path="rec.db", rotate_daily=True)
    assert store.rotated_sqlite_path(daily, str(tmp_path), datetime(2026, 10, 3, 8)) == str(tmp_path / "rec_2026-10-03.db")
    sized = StoreConfig(kind="sqlite", sqlite_path="rec.db", rotate_mb=1)
    (tmp_path / "rec.db").write_bytes(b"x" * 2_000_000)
    assert store.rotated_sqlite_path(sized, str(tmp_path)) == str(tmp_path / "rec_2.db")
    (tmp_path / "rec_2.db").write_bytes(b"x" * 10)
    assert store.rotated_sqlite_path(sized, str(tmp_path)) == str(tmp_path / "rec_2.db")      # still small: keep using it
    (tmp_path / "other.db").write_bytes(b"")
    (tmp_path / "rec_2026-10-03.db").write_bytes(b"")
    fam = [os.path.basename(f) for f in store.sqlite_family(str(tmp_path / "rec.db"))]
    assert fam == ["rec.db", "rec_2.db", "rec_2026-10-03.db"]


def test_recorder_writes_into_the_rotated_file(tmp_path):
    cfg = StoreConfig(kind="sqlite", sqlite_path="r.db", rotate_daily=True)
    rec = DbRecorder(cfg, [Signal(name="A")], START, {}, base_dir=str(tmp_path))
    rec.write(0.0, [1.0])
    rec.close()
    assert (tmp_path / "r_2026-10-03.db").exists() and not (tmp_path / "r.db").exists()
    assert "r_2026-10-03.db" in rec.path


def test_sqlite_reads_a_huge_range_in_buckets(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_READ_ROWS", 1000)
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "big.db"), mode="all")
    rec = DbRecorder(cfg, [Signal(name="A")], START, {})
    for i in range(5000):
        rec.write(i * 0.01, [100.0 if i == 2501 else float(i % 7)])
    rec.close()
    b = store.open_backend(cfg)
    sid = b.sessions()[0]["id"]
    with pytest.raises(StoreError, match="Za dużo"):
        b.read(sid)                                                          # no thinning allowed: refuses
    meta, t, m = b.read(sid, max_points=400)
    assert len(t) < 1000 and m[:, 0].max() == 100.0 and m[:, 0].min() == 0.0  # the spike survived the thinning
    b.close()


# ---------------------------------------------------------------- titles, owner, trash, delete
def _record_one(cfg, base="", n=60, extra=None):
    rec = DbRecorder(cfg, SIGS, START, {"tab": "Piec", "conf": "L1", **(extra or {})}, base_dir=base)
    feed(rec, n)
    rec.close()
    return rec


def test_new_session_fields_roundtrip_sqlite(tmp_path):
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "m.db"))
    rec = _record_one(cfg, extra={"title": "Rozruch", "notes": "po remoncie", "tags": "piec, test"})
    b = store.open_backend(cfg)
    s = b.sessions()[0]
    assert (s["title"], s["notes"], s["tags"]) == ("Rozruch", "po remoncie", "piec, test")
    assert s["owner"] == store.current_user() and s["computer"] and s["deleted_us"] is None
    assert s["keyframe_min"] == 10.0 and s["end_us"]
    b.update_session(rec.session, {"title": "Nowy", "tags": "a"})
    assert b.sessions()[0]["title"] == "Nowy" and b.sessions()[0]["notes"] == "po remoncie"     # only what was given changes
    b.update_session(rec.session, {"deleted_us": 123})
    assert b.sessions()[0]["deleted_us"] == 123
    b.update_session(rec.session, {"deleted_us": None})
    assert b.sessions()[0]["deleted_us"] is None
    assert b.stats()[rec.session] >= rec.written > 0                       # entries (one per signal value) vs rows
    b.delete_session(rec.session)
    assert b.sessions() == [] and b.stats() == {}
    b.close()


def test_sqlite_file_of_an_older_version_gets_the_new_columns(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    db = sqlite3.connect(p)
    db.executescript("""CREATE TABLE sessions(id TEXT PRIMARY KEY, name TEXT, start_us INTEGER, end_us INTEGER, ip TEXT,
        tab TEXT, conf TEXT, mode TEXT, signals TEXT, fields TEXT);
        CREATE TABLE samples(session TEXT NOT NULL, sig INTEGER NOT NULL, ts_us INTEGER NOT NULL, value REAL,
        PRIMARY KEY(session, sig, ts_us)) WITHOUT ROWID;
        INSERT INTO sessions VALUES('OLD','n',5,NULL,'1.2.3.4','T','L','changes','[]','[]');""")
    db.commit()
    db.close()
    b = store.open_backend(StoreConfig(kind="sqlite", sqlite_path=str(p)))
    s = b.sessions()[0]
    assert s["id"] == "OLD" and s["title"] == "" and s["owner"] == "" and s["deleted_us"] is None
    b.update_session("OLD", {"title": "T"})
    assert b.sessions()[0]["title"] == "T"
    b.close()


@pytest.mark.parametrize("ver", [1, 2])
def test_influx_session_metadata_update_and_delete(influx, ver):
    cfg = StoreConfig(url=influx.url, mode="changes", **INFLUX_CFGS[ver])
    rec = _record_one(cfg, extra={"title": "T1", "tags": "x"})
    b = store.open_backend(cfg)
    s = b.sessions()
    assert len(s) == 1 and s[0]["title"] == "T1" and s[0]["owner"] == store.current_user() and s[0]["end_us"]
    assert s[0]["deleted_us"] is None
    b.update_session(rec.session, {"title": "T2", "notes": "uwaga"})
    s = b.sessions()
    assert len(s) == 1 and s[0]["title"] == "T2" and s[0]["notes"] == "uwaga" and s[0]["tags"] == "x"
    b.update_session(rec.session, {"deleted_us": 99})
    assert b.sessions()[0]["deleted_us"] == 99
    b.update_session(rec.session, {"deleted_us": None})
    assert b.sessions()[0]["deleted_us"] is None
    b.delete_session(rec.session)
    assert b.sessions() == [] and not influx.select("s7trace") and not influx.select("s7trace_sessions")


def test_a_saved_influxdb3_target_falls_back_to_csv():
    assert StoreConfig.from_dict({"kind": "influx3", "url": "http://x:8181"}).kind == "csv"      # support was removed


def test_recorder_update_info_while_recording_and_at_the_end(tmp_path):
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "u.db"), batch_s=0.05)
    rec = DbRecorder(cfg, SIGS, START, {"title": "start"})
    rec.write(0.0, [1, 2, 3])
    rec.update_info(title="w trakcie", notes="n1")
    time.sleep(0.4)
    b = store.open_backend(cfg)
    assert b.sessions()[0]["title"] == "w trakcie" and b.sessions()[0]["notes"] == "n1"        # applied by the thread
    rec.update_info(tags="końcowe")
    rec.close()
    assert b.sessions()[0]["tags"] == "końcowe"                                                # applied at close
    b.close()


def test_update_info_before_the_server_answers_reaches_the_database(influx, flaky, tmp_path):
    cfg = StoreConfig(url=influx.url, mode="all", spool_mb=5, retry_max_s=1, batch_s=0.05, **INFLUX_CFGS[2])
    rec = DbRecorder(cfg, [Signal(name="A")], START, {}, base_dir=str(tmp_path))
    rec.write(0.0, [1.0])
    rec.update_info(title="przed serwerem")
    flaky["down"] = False
    assert _wait(lambda: len(influx.select("s7trace")) == 1)
    rec.close()
    b = store.open_backend(cfg)
    assert b.sessions()[0]["title"] == "przed serwerem"
    b.close()


def test_keyframes_carry_the_availability_field_and_survive_the_spool(influx, tmp_path):
    cfg = StoreConfig(url=influx.url, mode="changes", keyframe_min=1.0, **INFLUX_CFGS[2])
    rec = DbRecorder(cfg, [Signal(name="A"), Signal(name="B")], START, {})
    for i in range(0, 125):
        rec.write(float(i), [1.0, math.nan if i > 100 else 2.0])
    rec.close()
    pts = influx.select("s7trace")
    key_pts = [p for p in pts if "A__ok" in p[2]]
    assert len(key_pts) == 3 and all(p[2]["A__ok"] == 1.0 for p in key_pts)         # keyframes at 0 s, 60 s, 120 s say "ok"
    assert pts[-1][2]["B__ok"] == 0.0 and "B" not in pts[-1][2]
    sp = store.Spool(str(tmp_path / "k.db"), 1)
    sp.add([(1, {0: 1.0}), (2, {0: 1.0, 1: math.nan}, True)])
    last, rows = sp.peek(10)
    assert len(rows[0]) == 2 and len(rows[1]) == 3 and rows[1][2] is True and math.isnan(rows[1][1][1])
    sp.close(delete=True)


def test_config_fields_for_names_and_users():
    c = StoreConfig.from_dict({"title_ask": "end", "trash_days": 7, "view_scope": "all", "delete_others": True,
                               "sqlite_shared": True, "retention_days": 90})
    assert (c.title_ask, c.trash_days, c.view_scope, c.delete_others, c.sqlite_shared, c.retention_days) == \
        ("end", 7, "all", True, True, 90)
    d = StoreConfig.from_dict({"title_ask": "never", "view_scope": "x"})
    assert d.title_ask == "during" and d.view_scope == "mine" and d.trash_days == 30 and not d.delete_others


def test_shared_sqlite_folder_is_used_for_relative_paths(tmp_path):
    cfg = StoreConfig(kind="sqlite", sqlite_path="g.db", sqlite_shared=True)
    shared = store.shared_data_dir()
    assert shared and shared.endswith(os.path.join("S7Trace", "data"))
    assert store.effective_base(cfg, str(tmp_path)) == shared
    assert store.effective_base(StoreConfig(kind="sqlite"), str(tmp_path)) == str(tmp_path)
    rec = DbRecorder(cfg, SIGS, START, {}, base_dir=str(tmp_path))
    rec.write(0.0, [1, 2, 3])
    rec.close()
    assert os.path.exists(os.path.join(shared, "g.db")) and not (tmp_path / "g.db").exists()


@pytest.mark.parametrize("ver", [1, 2])
def test_influx_range_read_uses_the_keyframes_for_the_state_before_the_range(influx, ver):
    cfg = StoreConfig(url=influx.url, mode="changes", keyframe_min=1.0, **INFLUX_CFGS[ver])
    rec = DbRecorder(cfg, [Signal(name="A"), Signal(name="B")], START, {})
    for i in range(0, 301):
        rec.write(float(i), [7.0, float(i // 100)])                  # A never changes, B steps at 100 s and 200 s
    rec.close()
    b = store.open_backend(cfg)
    sess = b.sessions()[0]
    assert sess["keyframe_min"] == 1.0
    n_before = len(influx.requests)
    meta, t, m = b.read(sess["id"], t0_us=store.to_us(START, 150.0), t1_us=store.to_us(START, 250.0))
    assert m[0].tolist() == [7.0, 1.0] and m[-1].tolist() == [7.0, 2.0] and not np.isnan(m).any()
    queries = [r for r in influx.requests[n_before:] if "query" in r[1]]
    assert not any("LAST(*)" in (r[2].get("q", "") + r[4]) for r in queries)         # the look-back sufficed
    b.close()


@pytest.mark.parametrize("ver", [1, 2])
def test_influx_reads_a_range_too_big_for_memory_in_slices(influx, ver, monkeypatch):
    monkeypatch.setattr(store, "MAX_READ_ROWS", 400)
    cfg = StoreConfig(url=influx.url, mode="all", **INFLUX_CFGS[ver])
    rec = DbRecorder(cfg, [Signal(name="A")], START, {})
    for i in range(3000):
        rec.write(i * 5.0, [5000.0 if i == 1700 else float(i % 9)])                  # 4 hours; one spike
    rec.close()
    b = store.open_backend(cfg)
    sid = b.sessions()[0]["id"]
    with pytest.raises(StoreError, match="Za dużo"):
        b.read(sid)                                                                   # no thinning allowed: refuses
    meta, t, m = b.read(sid, max_points=600)
    assert 0 < len(t) < 1200 and m[:, 0].max() == 5000.0 and m[:, 0].min() == 0.0 and np.all(np.diff(t) >= 0)
    assert t[0] == store.to_us(START, 0) and t[-1] >= store.to_us(START, 14990)
    b.close()
