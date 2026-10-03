"""tools/diagnoza_timescale.py - the TimescaleDB self-test shipped in the portable package.

Always run: the offline steps and the report of an unreachable server (hints). Run against a real PostgreSQL /
TimescaleDB only when S7T_PG_PORT is set (S7T_PG_HOST, S7T_PG_DB, S7T_PG_USER, S7T_PG_PASSWORD optional)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import diagnoza_timescale as dt  # noqa: E402


def test_offline_steps_and_report_files(tmp_path):
    rep = str(tmp_path / "r")
    rc = dt.main(["--no-server", "--report", rep])
    txt = open(rep + ".txt", encoding="utf-8").read()
    data = json.load(open(rep + ".json", encoding="utf-8"))
    assert rc == 0 and "Wszystko dziala" in txt
    assert {s["step"] for s in data["steps"]} >= {"Windows i Python", "Kod programu (store.py)"}
    assert any("psycopg" in s["step"] for s in data["steps"]) and data["python"]


def test_unreachable_server_is_reported_with_a_hint_and_no_password(tmp_path):
    rep = str(tmp_path / "r")
    rc = dt.main(["--host", "127.0.0.1", "--port", "9", "--db", "d", "--user", "u", "--password", "SEKRET123",
                  "--sslmode", "disable", "--report", rep])
    txt = open(rep + ".txt", encoding="utf-8").read() + open(rep + ".json", encoding="utf-8").read()
    assert rc == 1 and "BLAD" in txt and "wskazowka" in txt and "SEKRET123" not in txt


def test_hints_pick_the_right_advice():
    assert "pg_hba" in dt.hint_for('FATAL: no pg_hba.conf entry for host "10.0.0.7"')
    assert "haslo" in dt.hint_for("password authentication failed for user x").lower()
    assert "DNS" in dt.hint_for("getaddrinfo failed")
    assert dt.hint_for("something unknown") == ""


def test_expected_data_and_matrix_check():
    import numpy as np
    rows = dt.expected_rows(300)
    t = np.array([int(r[0] * 1e6) for r in rows], dtype=np.int64)
    m = np.array([r[1] for r in rows])
    assert dt.check_matrix(t, m, rows) == 0
    m2 = m.copy()
    m2[150, 1] += 1
    assert dt.check_matrix(t, m2, rows) == 1                                   # a changed sample is detected
    assert np.isnan(m[110, 3]) and not np.isnan(m[10, 3])                       # the NaN gap is part of the data


@pytest.mark.skipif(not os.environ.get("S7T_PG_PORT"), reason="needs a real PostgreSQL (set S7T_PG_PORT)")
def test_full_cycle_against_a_real_server(tmp_path):
    rep = str(tmp_path / "r")
    rc = dt.main(["--host", os.environ.get("S7T_PG_HOST", "127.0.0.1"), "--port", os.environ["S7T_PG_PORT"],
                  "--db", os.environ.get("S7T_PG_DB", "postgres"), "--user", os.environ.get("S7T_PG_USER", "postgres"),
                  "--password", os.environ.get("S7T_PG_PASSWORD", ""), "--sslmode", "disable", "--events", "8000",
                  "--report", rep])
    assert rc == 0, open(rep + ".txt", encoding="utf-8").read()[-3000:]


# ---- the compression step: it needs the timescaledb extension, so here it runs against scripted stand-ins (this only
# ---- proves that the test logic itself is sound; the real server is what the user's run of Test-TimescaleDB.bat checks)
class _Cur:
    def __init__(self, conn):
        self.c, self.rows = conn, []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.rows = []
        if "FROM pg_extension" in s:
            self.rows = [("2.14.2",)]
        elif "timescaledb_information.hypertables" in s:
            self.rows = [(1,)]
        elif "timescaledb_information.jobs" in s:
            self.rows = [] if self.c.state.get("days") is None else [(float(self.c.state["days"]),)]
        elif "pg_total_relation_size" in s:
            self.rows = [(1000,)]
        elif "compress_chunk" in s:
            self.rows = [("_c1",), ("_c2",)]
        elif "timescaledb_information.chunks" in s:
            self.rows = [(2, 2 if self.c.state.get("compressed", True) else 0)]
        elif "hypertable_compression_stats" in s:
            self.rows = [(100_000_000, 10_000_000)]

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Conn:
    def __init__(self, state):
        self.state = state

    def cursor(self):
        return _Cur(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _Stub:
    """A recording store that keeps what is written in memory (one dict per instance of the program's backend)."""
    data: dict = {}

    def __init__(self, delete_fails=False):
        self.delete_fails = delete_fails

    def begin(self, meta):
        self.sid = meta["id"]
        _Stub.data[self.sid] = []

    def write(self, rows):
        _Stub.data[self.sid] += list(rows)

    def end(self, end_us):
        pass

    def close(self):
        pass

    def read(self, sid, lo=None, hi=None, max_points=0):
        import numpy as np
        pts = [p for p in _Stub.data[sid] if (lo is None or p[0] >= lo) and (hi is None or p[0] <= hi)]
        t = np.array([p[0] for p in pts], dtype=np.int64)
        m = np.array([[p[1][0], p[1][1], p[1][2]] for p in pts])
        return {}, t, m

    def sessions(self):
        return [{"id": k} for k in _Stub.data]

    def stats(self):
        return {k: 3 * len(v) for k, v in _Stub.data.items()}

    def delete_session(self, sid):
        if self.delete_fails:
            raise RuntimeError("cannot delete from compressed chunk")
        del _Stub.data[sid]


def _run_compression_step(monkeypatch, tmp_path, compress_days=7, delete_fails=False, compressed=True):
    from s7trace.core import store
    from s7trace.core.store import StoreConfig
    state = {"compressed": compressed}
    cfg = StoreConfig(kind="timescale", table="selftest_t", compress_days=compress_days)

    def fake_open(c, base_dir=""):
        state["days"] = c.compress_days or None                  # what the real backend does to the policy
        return _Stub(delete_fails)
    monkeypatch.setattr(store, "open_backend", fake_open)
    monkeypatch.setattr(store, "_pg_connect", lambda mod, c, t: _Conn(state))
    _Stub.data = {}
    dt.STEPS.clear()
    with dt.Step("kompresja") as s:
        dt.compression_check(s, "fake", None, cfg, str(tmp_path), _sigs())
    return dt.STEPS[-1], state


def _sigs():
    from s7trace.core.types import Signal
    return [Signal(name="A", dtype="BOOL"), Signal(name="B", dtype="REAL"), Signal(name="C", dtype="INT")]


def test_compression_step_logic_passes_with_a_cooperating_server(monkeypatch, tmp_path):
    rec, state = _run_compression_step(monkeypatch, tmp_path, compress_days=7)
    assert rec["ok"], rec["error"]
    assert any("skompresowano fragmentow: 2" in n for n in rec["info"]) and any("10.0 MB" in n or "100.0 MB" in n for n in rec["info"])
    assert any("usuwanie: OK" in n for n in rec["info"]) and state["days"] == 7            # ends with the configured value
    _, state0 = _run_compression_step(monkeypatch, tmp_path, compress_days=0)
    assert state0["days"] is None


def test_compression_step_reports_a_failing_delete_and_a_missing_compression(monkeypatch, tmp_path):
    rec, _ = _run_compression_step(monkeypatch, tmp_path, delete_fails=True)
    assert not rec["ok"] and "USUWANIE ze skompresowanych" in rec["error"] and "2.11" in rec["error"]
    rec, _ = _run_compression_step(monkeypatch, tmp_path, compressed=False)
    assert not rec["ok"] and "zaden fragment" in rec["error"]            # the server did not compress anything
