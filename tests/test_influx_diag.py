"""tools/diagnoza_influx.py - the InfluxDB self-test shipped in the portable package, run against the fake server
(the real InfluxDB 1.x / 2.x is what the user's own run of Test-InfluxDB.bat checks)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import diagnoza_influx as di  # noqa: E402
from test_store import influx  # noqa: E402,F401  (the fake server fixture)


def _args(influx, ver, rep, *extra):
    base = ["--version", str(ver), "--url", influx.url, "--report", rep, "--events", "4000"]
    if ver == 1:
        base += ["--db", "plant", "--user", "u", "--password", "SEKRET123"]
    else:
        base += ["--org", "acme", "--bucket", "plant", "--token", "tok"]
    return base + list(extra)


@pytest.mark.parametrize("ver", [1, 2])
def test_selftest_passes_against_the_fake_server_and_cleans_up(influx, tmp_path, ver):
    rep = str(tmp_path / "r")
    rc = di.main(_args(influx, ver, rep))
    txt = open(rep + ".txt", encoding="utf-8").read() + open(rep + ".json", encoding="utf-8").read()
    assert rc == 0, txt[-3000:]
    assert "USUWANIE nagrania" in txt and "Wszystko dziala" in txt and "SEKRET123" not in txt
    assert not [p for p in influx.points if p[0].startswith("s7trace_selftest_")]          # the test data are removed


def test_selftest_keep_leaves_the_data(influx, tmp_path):
    rc = di.main(_args(influx, 2, str(tmp_path / "r"), "--keep"))
    assert rc == 0 and any(p[0].startswith("s7trace_selftest_") for p in influx.points)


def test_unreachable_server_is_reported_with_a_hint(tmp_path):
    rep = str(tmp_path / "r")
    rc = di.main(["--version", "2", "--url", "http://127.0.0.1:9", "--org", "o", "--bucket", "b", "--token", "SEKRET123",
                  "--report", rep])
    txt = open(rep + ".txt", encoding="utf-8").read() + open(rep + ".json", encoding="utf-8").read()
    assert rc == 1 and "BLAD" in txt and "SEKRET123" not in txt


def test_wrong_token_is_reported_with_a_hint(influx, tmp_path):
    rep = str(tmp_path / "r")
    rc = di.main(["--version", "2", "--url", influx.url, "--org", "acme", "--bucket", "plant", "--token", "bad", "--report", rep])
    txt = open(rep + ".txt", encoding="utf-8").read()
    assert rc == 1 and "wskazowka" in txt and "token" in txt.lower()


def test_hints():
    assert "token" in di.hint_for("InfluxDB: HTTP 401 Unauthorized").lower()
    assert "administratorem" in di.hint_for("HTTP 403 Forbidden")
    assert di.hint_for("whatever") == ""
