"""Web mode: Start / Stop REC lines in the series, 'Zapis Manual REC' (a range of the chart becomes a recording), 'Zmień Start REC'."""
import os
from datetime import datetime

import numpy as np
import pytest

from s7trace.core import store
from s7trace.core.config import TabConfig
from s7trace.core.store import StoreConfig, open_backend
from s7trace.core.types import Signal
from s7trace.web import auth
from s7trace.web.hosted import HostManager
from s7trace.web.server import App, WebServer
from s7trace.web.targets import Targets
from tests.test_web import _user

WALL = datetime(2026, 10, 5, 12, 0, 0)


@pytest.fixture
def mgr(tmp_path):
    return HostManager(str(tmp_path / "ws"), files_root=str(tmp_path / "files"), data_dir=str(tmp_path), targets=Targets(str(tmp_path / "t.json")))


def fill(h, upto=20.0):
    h.signals = [Signal(name="A", dtype="REAL"), Signal(name="B", dtype="REAL")]
    h.start_wall = WALL
    t = np.round(np.arange(0, upto, 0.1), 3)
    h.buffer.reset(2)
    h.buffer.load(t, np.column_stack([np.sin(t), np.cos(t)]))
    h.state = "running"


def hosted(mgr, target="sqlite"):
    cfg = TabConfig()
    cfg.name, cfg.ip = "Sim", "10.0.0.1"
    cfg.signals = [Signal(name="A", dtype="REAL", db=1, byte=0), Signal(name="B", dtype="REAL", db=1, byte=4)]
    h = mgr.add(cfg, "ola", web={"rec_target": target})
    fill(h)
    return h


def feed(h, t0, t1):
    for t in np.arange(t0, t1, 0.1):
        vals = [float(np.sin(t)), float(np.cos(t))]
        h.buffer.append(float(t), vals)
        if h.recorder is not None:
            h.recorder.write(float(t), vals)


def us(t):
    return store.to_us(WALL, t)


def read_all(mgr, owner="ola"):
    db = os.path.join(mgr.files_root, f"u_{owner}", "recordings.db")
    b = open_backend(StoreConfig(kind="sqlite", sqlite_path=db))
    try:
        return [(s, *b.read(s["id"])[1:]) for s in b.sessions()]
    finally:
        b.close()


def test_series_lists_the_start_and_stop_rec_lines(mgr):
    h = hosted(mgr)
    assert h.series()["rec"] == []
    h.rec_start("ola")
    feed(h, 20.0, 21.0)
    h.rec_stop()
    h.rec_start("ola")
    rec = h.series()["rec"]
    assert [r["n"] for r in rec] == [1, 2] and rec[0]["t1"] is not None and rec[1]["t1"] is None and rec[0]["db"] is True
    assert abs(rec[0]["t0"] - 19.9) < 1e-6
    h.rec_stop()
    h.shutdown()
    h.rec_marks.reset()
    assert h.series()["rec"] == []


def test_manual_rec_area_becomes_a_recording(mgr):
    h = hosted(mgr)
    where = h.rec_save_range("ola", 5.0, 12.0, "Manual REC (1)", "10.0.0.7")
    assert where.startswith("sqlite:")
    ((s, t, m),) = read_all(mgr)
    assert s["title"] == "Manual REC (1)" and s["owner"] == "ola" and s["computer"] == "Web 10.0.0.7" and s["start_us"] == us(5.0)
    assert t[0] == us(5.0) and t[-1] <= us(12.0) and len(t) > 60
    with pytest.raises(ValueError, match="nie ma zebranych"):
        h.rec_save_range("ola", 100.0, 120.0)
    csv_h = hosted(mgr, "csv")
    name = csv_h.rec_save_range("ola", 2.0, 4.0, "x")
    assert name.endswith(".csv") and os.path.isfile(os.path.join(mgr.files_root, "u_ola", "rec", name))
    h.shutdown()
    csv_h.shutdown()


def test_move_start_rec_running_and_finished(mgr):
    h = hosted(mgr)
    h.rec_start("ola")                                         # REC pressed at 19.9
    feed(h, 20.0, 23.0)
    r = h.rec_move_start(1, 8.0)                               # earlier, while recording
    assert abs(r["t0"] - 8.0) < 0.11 and r["earlier"]
    assert abs(h.rec_marks.span(1)["t0"] - 8.0) < 0.11
    h.rec_stop()
    ((s, t, m),) = read_all(mgr)
    assert abs(t[0] - us(8.0)) < 110_000 and t[-1] >= us(22.8)
    k = np.searchsorted(t, us(12.0))
    assert abs(m[k, 0] - np.sin(12.0)) < 0.11
    r = h.rec_move_start(1, 15.0)                              # later, on the finished recording
    assert not r["earlier"]
    ((s, t, m),) = read_all(mgr)
    assert abs(t[0] - us(15.0)) < 110_000 and t[-1] >= us(22.8) and abs(m[0, 0] - np.sin(15.0)) < 0.11
    with pytest.raises(ValueError, match="Nie ma takiego"):
        h.rec_move_start(7, 3.0)
    with pytest.raises(ValueError, match="przed końcem"):
        h.rec_move_start(1, 40.0)
    h.shutdown()


def test_move_start_is_refused_for_csv(mgr):
    h = hosted(mgr, "csv")
    h.rec_start("ola")
    feed(h, 20.0, 21.0)
    with pytest.raises(ValueError, match="CSV"):
        h.rec_move_start(1, 8.0)
    h.shutdown()


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    s = WebServer(App(str(tmp_path / "web")), "127.0.0.1", 0)
    s.start()
    yield s
    s.stop()


def test_http_rec_range_and_start(srv):
    ola, jan = _user(srv, "ola"), _user(srv, "jan")
    body = {"name": "L", "ip": "10.0.0.1", "signals": [{"name": "A", "dtype": "REAL", "db": 1, "byte": 0}], "rec": {"target": "sqlite", "mode": "changes"}}
    st, d = ola.post("/api/connections", body)
    assert st == 200
    cid = d["id"]
    h = srv.app.hosts.get(cid)
    fill(h)
    assert ola.post(f"/api/connections/{cid}/rec-range", {"a": 3, "b": 9, "title": "Manual REC (1)"})[0] == 200
    assert jan.post(f"/api/connections/{cid}/rec-range", {"a": 3, "b": 9})[0] == 404             # someone else's connection
    st, res = ola.post(f"/api/connections/{cid}/rec-range", {"a": "x", "b": 9})
    assert st == 400
    assert ola.post(f"/api/connections/{cid}/rec-range", {"a": 500, "b": 900})[0] == 400
    assert ola.post(f"/api/connections/{cid}/rec-start", {"n": 1, "t": 2})[0] == 400              # there is no recording 1
    h.rec_start("ola")
    feed(h, 20.0, 21.0)
    st, res = ola.post(f"/api/connections/{cid}/rec-start", {"n": 1, "t": 6.0})
    assert st == 200 and res["earlier"] and abs(res["t0"] - 6.0) < 0.11
    rec = ola.get(f"/api/connections/{cid}/series?seconds=60")[1]["rec"]
    assert rec[0]["n"] == 1 and abs(rec[0]["t0"] - 6.0) < 0.11
    h.rec_stop()
    h.shutdown()


def test_rec_look_is_kept_per_account_and_the_page_loads_the_script(srv):
    ola, ala = _user(srv, "ola"), _user(srv, "ala")
    look = ola.get("/api/prefs")[1]["prefs"]["marker_look"]
    assert look["rec_show"] == 1 and look["rec_color"] == "#ff8c1a" and look["rec_width"] == 2 and look["rec_style"] == "solid" and look["rec_opacity"] == 24
    st, d = ola.post("/api/prefs", {"marker_look": {"rec_show": 0, "rec_color": "#00FF00", "rec_width": 40, "rec_style": "dash", "rec_opacity": 50}})
    assert st == 200 and d["prefs"]["marker_look"]["rec_show"] == 0 and d["prefs"]["marker_look"]["rec_color"] == "#00ff00"
    assert d["prefs"]["marker_look"]["rec_width"] == 12 and d["prefs"]["marker_look"]["rec_style"] == "dash"        # limited / validated
    assert ala.get("/api/prefs")[1]["prefs"]["marker_look"]["rec_show"] == 1                                         # another account is not affected
    bad = ola.post("/api/prefs", {"marker_look": {"rec_color": "red", "rec_style": "wavy"}})[1]["prefs"]["marker_look"]
    assert bad["rec_color"] == "#ff8c1a" and bad["rec_style"] == "solid"
    st, body = ola.get("/static/recmarks.js")
    assert st == 200 and "recmPaint" in (body if isinstance(body, str) else body.decode("utf-8"))
    st, page = ola.get("/")
    assert "/static/recmarks.js" in (page if isinstance(page, str) else page.decode("utf-8"))
