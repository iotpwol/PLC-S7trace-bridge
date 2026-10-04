"""Web mode, stage 2b: file templates and folders, recording targets, trigger and REC of hosted connections
(against the snap7 simulator) and the matching HTTP endpoints."""
import csv
import os
import time

import pytest

from s7trace.core.config import TabConfig
from s7trace.core.store import StoreConfig, open_backend
from s7trace.core.types import Signal
from s7trace.web import auth, editing, files
from s7trace.web.hosted import HostManager
from s7trace.web.server import App, WebServer
from s7trace.web.targets import TargetError, Targets
from tests.test_web import Client, _admin, _user, _wait

PORT = 11107


@pytest.fixture(scope="module")
def sim():
    from s7trace.sim import Simulator
    s = Simulator(PORT)
    s.start()
    time.sleep(0.5)
    yield s
    s.stop()


def _cfg(window=2.0):
    c = TabConfig()
    c.name, c.ip, c.rack, c.slot, c.cycle_ms, c.window_s = "Sim", f"127.0.0.1:{PORT}", 0, 2, 25, window
    c.signals = [Signal(name="b0", dtype="BOOL", db=1, byte=100, bit=0), Signal(name="b1", dtype="BOOL", db=1, byte=100, bit=1)]
    return c


@pytest.fixture
def mgr(tmp_path):
    return HostManager(str(tmp_path / "ws"), files_root=str(tmp_path / "files"), data_dir=str(tmp_path),
                       targets=Targets(str(tmp_path / "t.json")))


# ---------------------------------------------------------------- files
def test_file_templates_and_paths(tmp_path):
    root = str(tmp_path)
    assert files.check_template("REC_{confname}_{date}") == "REC_{confname}_{date}"
    for bad in ("../x", "a/b", "a\\b", "x{evil}", "{date", "a:b", "x" * 130):
        with pytest.raises(ValueError):
            files.check_template(bad)
    p1 = files.new_path(root, "Ola", "rec", "n_{ip}_{tab}", confname="c", ip="10.0.0.1:102", tab="Linia 1")
    assert p1.endswith("n_10.0.0.1_102_Linia_1.csv") and os.path.dirname(p1).endswith(os.path.join("u_ola", "rec"))
    open(p1, "w").close()
    assert files.new_path(root, "Ola", "rec", "n_{ip}_{tab}", confname="c", ip="10.0.0.1:102", tab="Linia 1").endswith("_1.csv")
    assert os.path.join("_shared", "snapshots") in files.new_path(root, "", "snapshots", "", confname="", ip="1", tab="t")
    assert [f["name"] for f in files.listing(root, "ola")] == [os.path.basename(p1)]
    assert files.listing(root, "jan") == []
    name = os.path.basename(p1)
    assert files.resolve(root, "ola", "rec", name) == p1
    for k, n in (("rec", "../" + name), ("x", name), ("rec", ""), ("rec", ".hidden"), ("snapshots", name)):
        assert files.resolve(root, "ola", k, n) is None
    assert files.resolve(root, "jan", "rec", name) is None              # other accounts' files are out of reach


# ---------------------------------------------------------------- targets
def test_targets_secrets_and_validation(tmp_path):
    t = Targets(str(tmp_path / "t.json"))
    t.put("Główna", {"kind": "timescale", "host": "db1", "pg_user": "u", "pg_password": "tajne", "pg_database": "x"})
    pub = t.public("Główna", admin=False)
    assert pub == {"name": "Główna", "kind": "timescale", "label": "TimescaleDB db1:5432 / x"}
    adm = t.public("Główna", admin=True)
    assert "pg_password" not in adm["fields"] and adm["secrets_set"]["pg_password"] is True and adm["fields"]["host"] == "db1"
    assert t.get("Główna").pg_password == "tajne"
    t.put("Główna", {"host": "db2", "pg_password": ""})                      # an empty secret keeps the stored one
    assert t.get("Główna").pg_password == "tajne" and t.get("Główna").host == "db2"
    assert Targets(str(tmp_path / "t.json")).names() == ["Główna"]           # persisted
    for name, f in (("csv", {"kind": "sqlite"}), ("", {"kind": "sqlite"}), ("x/y", {"kind": "sqlite"}), ("ok", {"kind": "csv"}),
                    ("ok", {"kind": "nope"})):
        with pytest.raises(TargetError):
            t.put(name, f)
    t.delete("Główna")
    assert t.names() == []


# ---------------------------------------------------------------- editing: trigger and REC
def test_edit_trigger_and_rec():
    cfg, web = _cfg(), {}
    ch = editing.apply(cfg, {"trigger": {"enabled": True, "signal": "b0", "mode": ">", "a": 0.5, "pretrigger": 0.5,
                                         "action": "Pauza + zapis CSV", "filename": "t_{date}"},
                             "rec": {"target": "sqlite", "mode": "all", "filename": "r_{time}"}}, True, web)
    assert ch == ["trigger", "rec"] and cfg.trigger.enabled and cfg.trigger.signal == "b0" and cfg.trigger.filename == "t_{date}"
    assert web["rec_target"] == "sqlite" and cfg.store.mode == "all" and cfg.rec_filename == "r_{time}"   # allowed while running
    v = editing.view(cfg, web, ["Baza"])
    assert v["trigger"]["action"] == "Pauza + zapis CSV" and v["rec"]["target"] == "sqlite"
    assert v["options"]["rec_targets"] == ["csv", "sqlite", "Baza"]
    for bad in ({"trigger": {"signal": "nie ma"}}, {"trigger": {"mode": "?"}}, {"trigger": {"action": "x"}},
                {"trigger": {"a": "x"}}, {"trigger": {"pretrigger": -1}}, {"trigger": {"filename": "../x"}},
                {"trigger": {"enabled": True, "signal": ""}}, {"rec": {"target": "Baza2"}}, {"rec": {"mode": "?"}},
                {"rec": {"filename": "a/b"}}, {"trigger": 5}):
        with pytest.raises(editing.EditError):
            editing.apply(cfg, bad, False, web, targets=["Baza"])
    with pytest.raises(editing.EditError, match="nagrywanie"):
        editing.apply(cfg, {"rec": {"mode": "changes"}}, False, web, recording=True)
    assert cfg.store.mode == "all"                                           # nothing from the rejected patches


# ---------------------------------------------------------------- hosted: trigger and REC
def _run(mgr, cfg, owner="ola", web=None):
    h = mgr.add(cfg, owner, web)
    h.start(owner)
    assert _wait(lambda: h.state == "running" and len(h.buffer) > 5)
    return h


def test_trigger_pause_and_csv(sim, mgr):
    sim.db1[100] = 0
    cfg = _cfg(2.0)
    cfg.trigger.enabled, cfg.trigger.signal, cfg.trigger.mode, cfg.trigger.a = True, "b0", ">", 0.5
    cfg.trigger.pretrigger, cfg.trigger.action = 0.5, "Pauza + zapis CSV"
    cfg.conf_name = "konf"
    h = _run(mgr, cfg)
    try:
        assert h.trig_state == "armed" and h.describe()["trigger"]["state"] == "armed"
        time.sleep(0.5)
        sim.db1[100] = 1                                                     # the condition becomes true
        assert _wait(lambda: h.trig_state == "hold", 8)
        info = h.trigger_info()
        assert info["x1"] - info["x0"] == pytest.approx(2.0) and len(info["events"]) == 1
        name = info["events"][0]["file"]
        path = files.resolve(mgr.files_root, "ola", "snapshots", name)
        assert path and "konf" in name
        with open(path, encoding="utf-8") as f:
            rows = [r for r in csv.reader(l for l in f if not l.startswith("#"))]
        assert rows[0][2:] == ["b0", "b1"] and len(rows) > 5 and rows[-1][2] == "1"
        assert h.series(span=(info["x0"], info["x1"]))["t"]                  # the frozen window can be fetched
        sim.db1[100] = 0
        h.rearm()
        assert h.trig_state == "armed"
        time.sleep(0.5)
        sim.db1[100] = 1
        assert _wait(lambda: len(h.trig_events) == 2, 8)                     # fires again after re-arming
    finally:
        h.shutdown()
    assert h.trig_state == "off"


def test_trigger_marker_only_rearms(sim, mgr):
    sim.db1[100] = 0
    cfg = _cfg(1.0)
    cfg.trigger.enabled, cfg.trigger.signal, cfg.trigger.mode, cfg.trigger.a = True, "b0", "rising edge", 0.5
    cfg.trigger.action = "Zapis CSV"
    h = _run(mgr, cfg)
    try:
        time.sleep(0.4)
        sim.db1[100] = 1
        assert _wait(lambda: len(h.trig_events) == 1, 8)
        assert h.trig_state == "armed"                                       # no pause: armed again at once
        assert files.listing(mgr.files_root, "ola")[0]["kind"] == "snapshots"
    finally:
        sim.db1[100] = 0
        h.shutdown()


def test_rec_csv(sim, mgr):
    sim.db1[100] = 1
    cfg = _cfg()
    cfg.store.mode = "all"
    h = _run(mgr, cfg)
    try:
        with pytest.raises(ValueError):
            h.rec_info_update({"title": "x"})                                # no recording yet
        h.rec_start("ola", {"title": "ignored for csv"}, "10.0.0.7")
        d = h.describe()["rec"]
        assert d["active"] and d["target"] == "csv" and d["label"].endswith(".csv") and d["by"] == "ola"
        with pytest.raises(ValueError, match="już trwa"):
            h.rec_start("ola")
        time.sleep(1.0)
        h.rec_stop()
    finally:
        h.shutdown()
    path = files.resolve(mgr.files_root, "ola", "rec", d["label"])
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.reader(l for l in f if not l.startswith("#"))]
    assert rows[0][:4] == ["time_s", "timestamp", "b0", "b1"] and len(rows) > 10 and rows[5][2] == "1"
    assert not h.describe()["rec"]["active"]


def test_rec_needs_running_and_stops_with_connection(sim, mgr):
    cfg = _cfg()
    h = mgr.add(cfg, "ola")
    with pytest.raises(ValueError, match="działającego"):
        h.rec_start("ola")
    h.start("ola")
    assert _wait(lambda: h.state == "running")
    h.rec_start("ola")
    h.stop()
    assert _wait(lambda: h.state == "stopped" and h.recorder is None, 10)    # REC ends with the connection
    h.shutdown()


def test_rec_sqlite_target_with_owner_metadata(sim, mgr):
    sim.db1[100] = 3
    cfg = _cfg()
    h = _run(mgr, cfg, web={"rec_target": "sqlite"})
    try:
        h.rec_start("ola", {"title": "Próba", "tags": "a,b"}, "10.0.0.7")
        time.sleep(1.0)
        h.rec_info_update({"notes": "uwagi"})
        h.rec_stop()
    finally:
        h.shutdown()
    db = os.path.join(mgr.files_root, "u_ola", "recordings.db")
    assert os.path.isfile(db)
    b = open_backend(StoreConfig(kind="sqlite", sqlite_path=db))
    try:
        (s,) = b.sessions()
        assert s["title"] == "Próba" and s["owner"] == "ola" and s["computer"] == "Web 10.0.0.7" and s["notes"] == "uwagi"
        meta, t, m = b.read(s["id"])
        assert len(t) >= 1 and list(m[-1]) == [1.0, 1.0]            # mode "changes": one row for constant values
        assert s["device"]["info"]["model"] == "CPU 315-2 PN/DP" and s["device"]["info"]["serial"].startswith("S C-")   # tied to the PLC
    finally:
        b.close()


def test_rec_unknown_target_is_reported(sim, mgr):
    h = _run(mgr, _cfg(), web={"rec_target": "Nie ma"})
    try:
        with pytest.raises(ValueError, match="Nie ma celu"):
            h.rec_start("ola")
        assert h.recorder is None
    finally:
        h.shutdown()


# ---------------------------------------------------------------- HTTP
@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    s = WebServer(App(str(tmp_path / "web")), "127.0.0.1", 0)
    s.start()
    yield s
    s.stop()


def test_http_trigger_rec_files(srv, sim):
    sim.db1[100] = 0
    ola, jan = _user(srv, "ola"), _user(srv, "jan")
    body = {"name": "L", "ip": f"127.0.0.1:{PORT}", "slot": 2, "cycle_ms": 25, "window_s": 2,
            "signals": [{"name": "b0", "dtype": "BOOL", "db": 1, "byte": 100, "bit": 0}],
            "trigger": {"enabled": True, "signal": "b0", "mode": ">", "a": 0.5, "pretrigger": 0.2, "action": "Zapis CSV"},
            "rec": {"target": "csv", "mode": "all"}}
    st, d = ola.post("/api/connections", body)
    assert st == 200 and d["trigger"]["enabled"] and d["rec"]["mode"] == "all"
    cid = d["id"]
    assert ola.post("/api/connections", {**body, "rec": {"target": "Baza"}})[0] == 400
    try:
        assert ola.post(f"/api/connections/{cid}/rec", {"action": "start"})[0] == 400        # not running yet
        assert ola.post(f"/api/connections/{cid}/start")[0] == 200
        assert _wait(lambda: ola.get(f"/api/connections/{cid}")[1]["state"] == "running")
        assert ola.get(f"/api/connections/{cid}")[1]["trigger"]["state"] == "armed"
        assert jan.post(f"/api/connections/{cid}/rec", {"action": "start"})[0] == 404       # someone else's connection
        assert ola.post(f"/api/connections/{cid}/rec", {"action": "start"})[0] == 200
        assert ola.post(f"/api/connections/{cid}/config", {"rec": {"mode": "changes"}})[0] == 400   # not while recording
        assert ola.post(f"/api/connections/{cid}/rec", {"action": "start"})[0] == 400        # already recording
        assert ola.post(f"/api/connections/{cid}/rec", {"action": "zzz"})[0] == 400
        time.sleep(0.4)
        sim.db1[100] = 1
        assert _wait(lambda: ola.get(f"/api/connections/{cid}")[1]["trigger"]["events"], 8)
        # changing the trigger while running restarts the state machine
        st, d = ola.post(f"/api/connections/{cid}/config", {"trigger": {"enabled": False}})
        assert st == 200 and d["trigger"]["state"] == "off"
        assert ola.post(f"/api/connections/{cid}/trigger", {"action": "rearm"})[0] == 200
        assert ola.post(f"/api/connections/{cid}/trigger", {"action": "x"})[0] == 400
        time.sleep(0.5)
        assert ola.post(f"/api/connections/{cid}/rec", {"action": "stop"})[1]["rec"]["active"] is False
        # the files of the account: listing, download, deletion; nobody else gets them
        lst = ola.get(f"/api/connections/{cid}/files")[1]["files"]
        kinds = sorted(f["kind"] for f in lst)
        assert kinds == ["rec", "snapshots"]
        rec = next(f for f in lst if f["kind"] == "rec")
        st, data = ola.get(f"/api/connections/{cid}/files/rec/{rec['name']}")
        assert st == 200 and b"# s7trace v1" in data
        assert jan.get(f"/api/connections/{cid}/files")[0] == 404
        assert ola.get(f"/api/connections/{cid}/files/rec/..%2F..%2Fweb_users.db")[0] == 404
        assert ola.post(f"/api/connections/{cid}/files", {"kind": "rec", "name": rec["name"]})[0] == 200
        assert [f["kind"] for f in ola.get(f"/api/connections/{cid}/files")[1]["files"]] == ["snapshots"]
        assert ola.post(f"/api/connections/{cid}/files", {"kind": "rec", "name": "nie.csv"})[0] == 404
    finally:
        sim.db1[100] = 0
        ola.post(f"/api/connections/{cid}/stop")
        _wait(lambda: ola.get(f"/api/connections/{cid}")[1]["state"] == "stopped")


def test_http_targets(srv):
    adm = _admin(srv)
    ola = _user(srv, "ola")
    assert ola.post("/api/targets", {"action": "add", "name": "B", "fields": {"kind": "sqlite"}})[0] == 403
    assert adm.post("/api/targets", {"action": "add", "name": "Baza", "fields": {
        "kind": "timescale", "host": "127.0.0.1", "port": 1, "pg_password": "tajne", "test_timeout_s": 1}})[0] == 200
    assert adm.post("/api/targets", {"action": "add", "name": "csv", "fields": {"kind": "sqlite"}})[0] == 400
    row = ola.get("/api/targets")[1]["targets"]
    assert row == [{"name": "Baza", "kind": "timescale", "label": "TimescaleDB 127.0.0.1:1 / s7trace"}]   # no secrets, no fields
    arow = adm.get("/api/targets")[1]["targets"][0]
    assert arow["secrets_set"]["pg_password"] is True and "tajne" not in str(arow)
    assert "Baza" in ola.get("/api/options")[1]["options"]["rec_targets"]
    st, d = adm.post("/api/targets", {"action": "test", "name": "Baza"})
    assert st == 200 and d["ok"] is False and d["message"]                  # nothing listens on the port
    assert adm.post("/api/targets", {"action": "test", "name": "Nie ma"})[0] == 404
    assert adm.post("/api/targets", {"action": "delete", "name": "Baza"})[0] == 200
    assert ola.get("/api/targets")[1]["targets"] == []


def test_http_diag_view(srv, sim):
    """Diagnostics of a connection: stopped = no link data; running = the same numbers as the program, the controller table, a ping."""
    ola, jan = _user(srv, "ola"), _user(srv, "jan")
    st, d = ola.post("/api/connections", {"name": "L", "ip": f"127.0.0.1:{PORT}", "slot": 2, "cycle_ms": 25, "window_s": 2,
                                          "signals": [{"name": "b0", "dtype": "BOOL", "db": 1, "byte": 100, "bit": 0}]})
    cid = d["id"]
    try:
        assert jan.get(f"/api/connections/{cid}/diag")[0] == 404                                   # someone else's connection
        st, dg = ola.get(f"/api/connections/{cid}/diag")
        assert st == 200 and dg["rating"] == "Brak danych" and dg["link"] is None and dg["device"] == [] and dg["spools"] == []
        assert ola.post(f"/api/connections/{cid}/start")[0] == 200
        assert _wait(lambda: ola.get(f"/api/connections/{cid}")[1]["state"] == "running")
        time.sleep(1.0)
        st, dg = ola.get(f"/api/connections/{cid}/diag?ping=1")
        assert st == 200 and dg["state"] == "running" and dg["link"]["samples"] > 5 and dg["link"]["lag"]["avg"] is not None
        assert dg["rating"] in ("Bardzo dobre", "Dobre", "Przeciętne", "Słabe") and dg["notes"]
        assert ["Model CPU", "CPU 315-2 PN/DP"] in dg["device"] and any(a == "Numer seryjny" for a, _ in dg["device"])
        assert "ping_ms" in dg and dg["others"] == []
    finally:
        ola.post(f"/api/connections/{cid}/stop")


def test_edit_chart_layout_and_series_fields(sim, mgr):
    cfg = _cfg()
    v = editing.view(cfg)
    assert v["y_layout"] == "lanes" and v["auto_y"] is True and v["show_points"] is False
    changed = editing.apply(cfg, {"y_layout": "offset", "auto_y": False, "y_min": -5, "y_max": 120, "show_points": True}, running=True)
    assert set(changed) == {"y_layout", "auto_y", "y_min", "y_max", "show_points"}          # the look of the chart: allowed while running
    assert (cfg.y_layout, cfg.auto_y, cfg.y_min, cfg.y_max, cfg.show_points) == ("offset", False, -5.0, 120.0, True)
    for bad in ({"y_layout": "x"}, {"y_min": "abc"}, {"y_max": 1e15}):
        with pytest.raises(editing.EditError):
            editing.apply(cfg, bad, running=False)
    cfg.signals[0].offset_y, cfg.signals[0].gain = 3.5, 2.0
    h = _run(mgr, cfg)
    try:
        s = h.series(5)
        assert s["offsets"] == [3.5, 0.0] and s["gains"] == [2.0, 1.0] and s["layout"]["y_layout"] == "offset" and s["layout"]["show_points"] is True
    finally:
        h.shutdown()


def test_http_help_version_and_legend_data(srv, sim):
    from s7trace import version
    ola = _user(srv, "ola")
    anon = Client(srv)
    assert anon.get("/api/version")[1]["version"] == version.VERSION and anon.get("/api/version")[1]["author"] == "PWOL79 & CLAUDE"
    h = anon.get("/api/help")[1]["help"]
    assert "cykl [ms]" in h and "Do czego służy" in h["start"] and "pobierz" in h
    st, d = ola.post("/api/connections", {"name": "L", "ip": f"127.0.0.1:{PORT}", "slot": 2, "cycle_ms": 25, "window_s": 2, "legend_mode": "address",
                                          "signals": [{"name": "b0", "dtype": "BOOL", "db": 1, "byte": 100, "bit": 0, "comment": "pierwszy"}]})
    assert st == 200
    cid = d["id"]
    try:
        assert ola.get(f"/api/connections/{cid}/config")[1]["legend_mode"] == "address"
        assert ola.get(f"/api/connections/{cid}/config")[1]["device"] == []
        assert ola.post(f"/api/connections/{cid}/start")[0] == 200
        assert _wait(lambda: ola.get(f"/api/connections/{cid}")[1]["state"] == "running")
        time.sleep(0.5)
        s = ola.get(f"/api/connections/{cid}/series?seconds=5")[1]
        assert s["addresses"] == ["DB1.DBX100.0"] and s["layout"]["legend_mode"] == "address"
        assert "Adres: DB1.DBX100.0" in s["tips"][0] and "Opis: pierwszy" in s["tips"][0] and "Aktualna wartość" not in s["tips"][0]
        assert any(a == "Model CPU" for a, _ in ola.get(f"/api/connections/{cid}/config")[1]["device"])
    finally:
        ola.post(f"/api/connections/{cid}/stop")
