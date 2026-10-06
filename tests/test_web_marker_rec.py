"""Web mode: every marker of a live connection knows the recording it belongs to; markers follow Manual REC / a moved Start REC;
the list has the 'Zapis' column and the filters the front end needs."""
import numpy as np
import pytest

from s7trace.core import store
from s7trace.web import auth
from s7trace.web.server import App, WebServer
from tests.test_web import _user
from tests.test_web_rec_marks import WALL, feed, fill, us


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    s = WebServer(App(str(tmp_path / "web")), "127.0.0.1", 0)
    s.start()
    yield s
    s.stop()


def conn(srv, cli, target="sqlite"):
    body = {"name": "L", "ip": "10.0.0.1", "signals": [{"name": "A", "dtype": "REAL", "db": 1, "byte": 0}], "rec": {"target": target, "mode": "changes"}}
    st, d = cli.post("/api/connections", body)
    assert st == 200
    h = srv.app.hosts.get(d["id"])
    fill(h)
    return h


def add(cli, h, t):
    st, d = cli.post("/api/markers", {"action": "add", "at_us": us(t), "conn": h.id, "title": f"m{t}"})
    assert st == 200
    return d["marker"]


def get(cli, mid):
    return next(m for m in cli.get("/api/markers")[1]["markers"] if m["id"] == mid)


def test_marker_gets_the_recording_of_its_time(srv):
    ola = _user(srv, "ola")
    h = conn(srv, ola)
    before = add(ola, h, 5.0)
    assert before["rec_id"] == "" and before["buffered"] is True            # chart buffer only (the connection holds its data)
    h.rec_start("ola")
    feed(h, 20.0, 24.0)
    during = add(ola, h, 22.0)
    sid = h.recorder.session
    assert during["rec_id"] == f"sqlite|{sid}"
    h.rec_stop()
    after, outside = add(ola, h, 23.0), add(ola, h, 10.0)
    assert after["rec_id"] == f"sqlite|{sid}" and outside["rec_id"] == ""
    # the batch of the draft does the same, and a marker that brings its own recording keeps it
    st, d = ola.post("/api/markers", {"action": "batch", "adds": [{"tmp": -1, "at_us": us(21.0), "conn": h.id},
                                                                   {"tmp": -2, "at_us": us(21.0), "conn": h.id, "rec_id": "sqlite|X"}],
                                      "updates": [], "deletes": []})
    assert st == 200
    assert get(ola, d["new_ids"]["-1"])["rec_id"] == f"sqlite|{sid}" and get(ola, d["new_ids"]["-2"])["rec_id"] == "sqlite|X"
    h.shutdown()


def test_csv_recording_is_named_by_its_file(srv):
    ola = _user(srv, "ola")
    h = conn(srv, ola, "csv")
    h.rec_start("ola")
    feed(h, 20.0, 22.0)
    m = add(ola, h, 21.0)
    assert m["rec_id"].startswith("csv|") and m["rec_id"].endswith(".csv")
    h.rec_stop()
    h.shutdown()


def test_manual_rec_and_moved_start_pull_markers_along(srv):
    ola = _user(srv, "ola")
    h = conn(srv, ola)
    inside, outside = add(ola, h, 8.0), add(ola, h, 15.0)
    cid = h.id
    assert ola.post(f"/api/connections/{cid}/rec-range", {"a": 5, "b": 12, "title": "Manual REC (1)"})[0] == 200
    r = get(ola, inside["id"])["rec_id"]
    assert r.startswith("sqlite|") and get(ola, outside["id"])["rec_id"] == ""
    h.rec_start("ola")
    feed(h, 20.0, 23.0)
    sid = h.recorder.session
    mid = add(ola, h, 14.0)
    assert mid["rec_id"] == ""                                                # before the recording started
    st, res = ola.post(f"/api/connections/{cid}/rec-start", {"n": 1, "t": 13.0})   # earlier: 13 s .. the old start now belong to it
    assert st == 200 and res["earlier"] and "link" not in res
    assert get(ola, mid["id"])["rec_id"] == f"sqlite|{sid}"
    st, res = ola.post(f"/api/connections/{cid}/rec-start", {"n": 1, "t": 18.0})   # later: what was cut off is only in the buffer again
    assert st == 200 and not res["earlier"]
    assert get(ola, mid["id"])["rec_id"] == ""
    h.rec_stop()
    h.shutdown()


def test_listing_has_the_buffer_only_filter(srv):
    ola = _user(srv, "ola")
    h = conn(srv, ola)
    a = add(ola, h, 3.0)
    ola.post("/api/markers", {"action": "add", "at_us": us(4.0), "conn": h.id, "rec_id": "sqlite|ABC"})
    ids = [m["id"] for m in ola.get("/api/markers?norec=1")[1]["markers"]]
    assert ids == [a["id"]]
    h.buffer.reset(1)                                                          # the chart data are gone (e.g. the server was restarted)
    assert get(ola, a["id"])["buffered"] is False
    h.shutdown()


def test_front_end_asks_before_losing_markers(srv):
    ola = _user(srv, "ola")
    txt = lambda p: (lambda b: b if isinstance(b, str) else b.decode("utf-8"))(ola.get(p)[1])
    page, js, app = txt("/"), txt("/static/markers.js"), txt("/static/app.js")
    assert 'id="mkl-rec"' in page and 'id="mkl-orph"' in page and "<th>Zapis</th>" in page
    assert "mkAskBuffer" in js and "mkAskRecording" in js and "mkDeleteOrphans" in js and "mkRecLabel" in js
    assert "mkAskBuffer(id," in app and "mkAskRecording(" in app
