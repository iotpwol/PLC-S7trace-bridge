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
