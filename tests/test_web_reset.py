"""Web mode: a new Start continues the chart with a gap, 'Auto-Reset' makes every Start begin a new chart, the 'Reset' endpoint."""
import time

import numpy as np
import pytest

from s7trace.core.config import TabConfig
from s7trace.core.types import Signal
from s7trace.web import auth, editing
from s7trace.web.hosted import HostManager
from s7trace.web.server import App, WebServer
from s7trace.web.targets import Targets
from tests.test_web import _user, _wait
from tests.test_web_rec_marks import fill

PORT = 11108


@pytest.fixture(scope="module")
def sim():
    from s7trace.sim import Simulator
    s = Simulator(PORT)
    s.start()
    time.sleep(0.5)
    yield s
    s.stop()


@pytest.fixture
def mgr(tmp_path):
    return HostManager(str(tmp_path / "ws"), files_root=str(tmp_path / "files"), data_dir=str(tmp_path), targets=Targets(str(tmp_path / "t.json")))


def test_start_stop_start_continues_with_a_gap_and_auto_reset_starts_over(sim, mgr):
    c = TabConfig()
    c.name, c.ip, c.rack, c.slot, c.cycle_ms = "Sim", f"127.0.0.1:{PORT}", 0, 2, 25
    c.signals = [Signal(name="b0", dtype="BOOL", db=1, byte=100, bit=0)]
    sim.db1[100] = 1
    h = mgr.add(c, "ola")
    try:
        h.start("ola")
        assert _wait(lambda: h.state == "running" and len(h.buffer) > 20)
        wall = h.start_wall
        h.stop()
        assert _wait(lambda: h.state == "stopped")
        n1, last1 = len(h.buffer), h.buffer.last_time()
        time.sleep(1.2)
        h.start("ola")                                                       # Auto-Reset is off: the chart goes on
        assert _wait(lambda: h.state == "running" and len(h.buffer) > n1 + 20)
        assert h.start_wall == wall
        t, v = h.buffer.snapshot()
        assert np.isnan(v[:, 0]).any() and np.all(np.diff(t) >= 0)
        first_new = t[n1:][~np.isnan(v[n1:, 0])][0]
        assert 1.2 <= first_new - last1 < 6.0
        h.stop()
        assert _wait(lambda: h.state == "stopped")
        h.cfg.auto_reset = True                                              # Auto-Reset: the next Start begins a new chart
        h.start("ola")
        assert _wait(lambda: h.state == "running" and len(h.buffer) > 5)
        assert h.start_wall > wall and h.buffer.first_time() < 1.0 and not np.isnan(h.buffer.snapshot()[1]).any()
        h.stop()
        assert _wait(lambda: h.state == "stopped")
    finally:
        h.shutdown()


def test_reset_while_running_keeps_the_time_axis_and_stopped_starts_afresh(mgr):
    c = TabConfig()
    c.name, c.ip = "Sim", "10.0.0.1"
    c.signals = [Signal(name="A", dtype="REAL", db=1, byte=0), Signal(name="B", dtype="REAL", db=1, byte=4)]
    h = mgr.add(c, "ola")
    fill(h)                                                                  # running, 20 s of data
    wall = h.start_wall
    h.reset_chart()
    assert len(h.buffer) == 0 and h.start_wall == wall and h.signals
    fill(h)
    h.state = "stopped"
    h.reset_chart()
    assert len(h.buffer) == 0 and h.start_wall > wall
    assert not h.can_continue([s for s in h.cfg.signals])                    # nothing to continue
    fill(h)
    h.state = "stopped"
    h.cfg.auto_reset = True
    assert not h.can_continue(list(h.signals))
    h.cfg.auto_reset = False
    assert h.can_continue(list(h.signals))
    run2 = [Signal.from_dict(x.to_dict()) for x in h.signals]
    run2[0].byte += 2                                                        # another address: another column
    assert not h.can_continue(run2)
    h.shutdown()


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    s = WebServer(App(str(tmp_path / "web")), "127.0.0.1", 0)
    s.start()
    yield s
    s.stop()


def test_http_reset_and_auto_reset_and_colours(srv):
    ola, viewer = _user(srv, "ola"), _user(srv, "gosc", "viewer")
    st, d = ola.post("/api/connections", {"name": "L", "ip": "10.0.0.1", "signals": [{"name": "A", "dtype": "REAL", "db": 1, "byte": 0}]})
    assert st == 200
    cid = d["id"]
    h = srv.app.hosts.get(cid)
    assert ola.get(f"/api/connections/{cid}")[1]["auto_reset"] is False
    assert ola.post(f"/api/connections/{cid}/reset", {"auto": True})[0] == 200
    assert ola.get(f"/api/connections/{cid}")[1]["auto_reset"] is True and h.cfg.auto_reset is True
    assert srv.app.hosts.get(cid).cfg.auto_reset is True
    assert ola.post(f"/api/connections/{cid}/reset", {"auto": False})[0] == 200 and h.cfg.auto_reset is False
    fill(h)
    assert viewer.post(f"/api/connections/{cid}/reset", {})[0] in (403, 404)
    assert len(h.buffer) > 0
    assert ola.post(f"/api/connections/{cid}/reset", {})[0] == 200 and len(h.buffer) == 0
    # the connection editor changes the setting too
    assert editing.apply(h.cfg, {"auto_reset": True}, running=False) == ["auto_reset"] and h.cfg.auto_reset is True
    # colours of the engaged button: kept per account with the table colours
    st, p = ola.post("/api/prefs", {"table": {"reset_on_bg": "#112233", "reset_on_text": "#44AAFF", "border": "bad"}})
    assert st == 200 and p["prefs"]["table"]["reset_on_bg"] == "#112233" and p["prefs"]["table"]["reset_on_text"] == "#44aaff"
    assert p["prefs"]["table"]["border"] == ""
    txt = lambda path: (lambda b: b if isinstance(b, str) else b.decode("utf-8"))(ola.get(path)[1])
    assert 'id="c-reset"' in txt("/") and "resetClick" in txt("/static/app.js") and "#c-reset.on" in txt("/static/style.css")
