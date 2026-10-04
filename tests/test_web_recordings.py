"""Web mode: the recordings browser (sources, visibility rules, reading, CSV, properties, trash)."""
import os
from datetime import datetime

import pytest

from s7trace.core import store as st
from s7trace.core.types import Signal
from s7trace.web import auth, files
from s7trace.web.server import App, WebServer
from tests.test_web import _admin, _user


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    s = WebServer(App(str(tmp_path / "web")), "127.0.0.1", 0)
    s.start()
    yield s
    s.stop()


def _record(folder_or_cfg, owner, title, n=300, mode="all", base=""):
    """Writes a finished recording (signals A = ramp, B = square) into a SQLite file; returns its id."""
    cfg = folder_or_cfg if isinstance(folder_or_cfg, st.StoreConfig) else \
        st.StoreConfig(kind="sqlite", mode=mode, sqlite_path=os.path.join(folder_or_cfg, "recordings.db"))
    cfg.mode = mode
    sigs = [Signal(name="A", dtype="INT", color="#ff0000"), Signal(name="B", dtype="BOOL", color="#00ff00")]
    rec = st.DbRecorder(cfg, sigs, datetime(2026, 10, 4, 12, 0, 0), {"title": title, "owner": owner, "computer": "Web 1.2.3.4",
                                                                      "name": "Linia", "ip": "10.0.0.5"}, base_dir=base)
    for i in range(n):
        rec.write(i * 0.1, [float(i), float((i // 20) % 2)])
    rec.close()
    return rec.session


def test_own_file_list_read_csv_edit_trash(srv):
    root = srv.app.hosts.files_root
    ola = _user(srv, "ola")
    assert ola.get("/api/recordings?source=sqlite")[1]["recordings"] == []           # nothing recorded: no file is created
    assert not os.path.exists(os.path.join(root, "u_ola"))
    sid = _record(files.account_dir(root, "ola"), "ola", "Pierwsze")
    srcs = ola.get("/api/recordings/sources")[1]["sources"]
    assert [s["id"] for s in srcs] == ["sqlite"]
    (r,) = ola.get("/api/recordings?source=sqlite")[1]["recordings"]
    assert r["id"] == sid and r["title"] == "Pierwsze" and r["owner"] == "ola" and r["signals"] == ["A", "B"]
    assert r["can_modify"] and r["entries"] == 600 and r["computer"] == "Web 1.2.3.4" and r["ip"] == "10.0.0.5"
    # reading: thinned for the chart, a range, the original colours
    st_, d = ola.get(f"/api/recordings/data?source=sqlite&id={sid}&points=60")
    assert st_ == 200 and d["names"] == ["A", "B"] and d["colors"] == ["#ff0000", "#00ff00"] and d["rows"] == 300
    assert 2 <= len(d["t"]) <= 70 and d["t"][0] == 0.0 and d["values"][0][-1] == 299.0 and d["shown"] == len(d["t"])
    d2 = ola.get(f"/api/recordings/data?source=sqlite&id={sid}&from=5&to=10&points=1000")[1]
    assert d2["t"][0] >= 5 - 1e-6 and d2["t"][-1] <= 10 + 1e-6 and len(d2["t"]) > 40
    # CSV: every row
    st_, data = ola.get(f"/api/recordings/csv?source=sqlite&id={sid}")
    text = data.decode()
    assert st_ == 200 and text.startswith("# s7trace v1") and text.count("\n") >= 300 and "time_s,timestamp,A,B" in text
    assert ola.get("/api/recordings/csv?source=sqlite&id=nie-ma")[0] == 400
    # properties, trash, restore, purge
    assert ola.post("/api/recordings", {"source": "sqlite", "id": sid, "action": "update",
                                        "fields": {"title": "Nowy tytuł", "notes": "n", "tags": "x,y", "owner": "hacker"}})[0] == 200
    r = ola.get("/api/recordings?source=sqlite")[1]["recordings"][0]
    assert (r["title"], r["notes"], r["tags"], r["owner"]) == ("Nowy tytuł", "n", "x,y", "ola")     # the owner is not editable
    assert ola.post("/api/recordings", {"source": "sqlite", "id": sid, "action": "purge"})[0] == 400  # not in the trash
    assert ola.post("/api/recordings", {"source": "sqlite", "id": sid, "action": "trash"})[0] == 200
    assert ola.get("/api/recordings?source=sqlite")[1]["recordings"] == []
    (t,) = ola.get("/api/recordings?source=sqlite&trash=1")[1]["recordings"]
    assert t["deleted_us"]
    assert ola.post("/api/recordings", {"source": "sqlite", "id": sid, "action": "restore"})[0] == 200
    assert len(ola.get("/api/recordings?source=sqlite")[1]["recordings"]) == 1
    ola.post("/api/recordings", {"source": "sqlite", "id": sid, "action": "trash"})
    assert ola.post("/api/recordings", {"source": "sqlite", "id": sid, "action": "purge"})[0] == 200
    assert ola.get("/api/recordings?source=sqlite&trash=1")[1]["recordings"] == []
    assert ola.post("/api/recordings", {"source": "sqlite", "id": sid, "action": "zzz"})[0] == 400


def test_accounts_are_separate_admin_sees_all(srv):
    root = srv.app.hosts.files_root
    adm = _admin(srv)
    ola, jan = _user(srv, "ola"), _user(srv, "jan")
    sid = _record(files.account_dir(root, "ola"), "ola", "Ola 1")
    assert jan.get("/api/recordings?source=sqlite")[1]["recordings"] == []
    assert jan.get(f"/api/recordings/data?source=sqlite&id={sid}")[0] == 400           # not in jan's file
    assert jan.get("/api/recordings?source=acct:u_ola")[0] == 400                      # other accounts: administrators only
    assert [s["id"] for s in adm.get("/api/recordings/sources")[1]["sources"]] == ["sqlite", "acct:u_ola"]
    (r,) = adm.get("/api/recordings?source=acct:u_ola")[1]["recordings"]
    assert r["id"] == sid and r["can_modify"]
    assert adm.get(f"/api/recordings/data?source=acct:u_ola&id={sid}")[0] == 200
    assert adm.post("/api/recordings", {"source": "acct:u_ola", "id": sid, "action": "update", "fields": {"title": "Admin"}})[0] == 200
    assert ola.get("/api/recordings?source=sqlite")[1]["recordings"][0]["title"] == "Admin"


def test_shared_file_and_viewer(srv):
    root = srv.app.hosts.files_root
    _record(files.account_dir(root, ""), "ola", "Wspólne ola")
    sid2 = _record(files.account_dir(root, ""), "jan", "Wspólne jan")
    ola, kasia = _user(srv, "ola"), _user(srv, "kasia", "viewer")
    assert "shared" in [s["id"] for s in ola.get("/api/recordings/sources")[1]["sources"]]
    rows = {r["title"]: r for r in ola.get("/api/recordings?source=shared")[1]["recordings"]}
    assert set(rows) == {"Wspólne ola", "Wspólne jan"}                                  # everybody sees the shared file
    assert rows["Wspólne ola"]["can_modify"] and not rows["Wspólne jan"]["can_modify"]  # but changes only own recordings
    assert ola.post("/api/recordings", {"source": "shared", "id": sid2, "action": "trash"})[0] == 400
    k = kasia.get("/api/recordings?source=shared")[1]["recordings"]
    assert len(k) == 2 and not any(r["can_modify"] for r in k)                          # a viewer reads only
    assert kasia.post("/api/recordings", {"source": "shared", "id": sid2, "action": "trash"})[0] == 403


def test_database_target_scope_rules(srv, tmp_path):
    adm = _admin(srv)
    adm.post("/api/targets", {"action": "add", "name": "Wspolna", "fields": {"kind": "sqlite", "sqlite_path": "wspolna.db",
                                                                               "view_scope": "mine"}})
    cfg = srv.app.targets.get("Wspolna")
    base = os.path.join(srv.app.data_dir, "dbs")
    cfg.sqlite_path = os.path.join(base, "wspolna.db")
    sid_o = _record(cfg, "ola", "Moje ola")
    sid_j = _record(cfg, "jan", "Moje jan")
    ola = _user(srv, "ola")
    assert "Wspolna" in [s["id"] for s in ola.get("/api/recordings/sources")[1]["sources"]]
    assert [r["title"] for r in ola.get("/api/recordings?source=Wspolna")[1]["recordings"]] == ["Moje ola"]   # view_scope "mine"
    assert ola.get(f"/api/recordings/data?source=Wspolna&id={sid_j}")[0] == 400                          # not visible = not readable
    assert sorted(r["title"] for r in adm.get("/api/recordings?source=Wspolna")[1]["recordings"]) == ["Moje jan", "Moje ola"]
    adm.post("/api/targets", {"action": "update", "name": "Wspolna", "fields": {"view_scope": "all"}})
    rows = {r["title"]: r for r in ola.get("/api/recordings?source=Wspolna")[1]["recordings"]}
    assert set(rows) == {"Moje ola", "Moje jan"} and rows["Moje ola"]["can_modify"] and not rows["Moje jan"]["can_modify"]
    assert ola.get(f"/api/recordings/data?source=Wspolna&id={sid_j}")[0] == 200
    assert ola.post("/api/recordings", {"source": "Wspolna", "id": sid_j, "action": "update", "fields": {"title": "x"}})[0] == 400
    adm.post("/api/targets", {"action": "update", "name": "Wspolna", "fields": {"delete_others": True}})
    assert ola.post("/api/recordings", {"source": "Wspolna", "id": sid_j, "action": "update", "fields": {"title": "x"}})[0] == 200
    assert ola.post("/api/recordings", {"source": "Wspolna", "id": sid_o, "action": "trash"})[0] == 200


def test_trash_and_retention_policies(srv):
    root = srv.app.hosts.files_root
    folder = files.account_dir(root, "ola")
    sid = _record(folder, "ola", "Stare")
    ola = _user(srv, "ola")
    # a recording in the trash for longer than trash_days is removed on the next listing (default 30 days)
    b = st.open_backend(st.StoreConfig(kind="sqlite", sqlite_path=os.path.join(folder, "recordings.db")))
    b.update_session(sid, {"deleted_us": int((__import__("time").time() - 40 * 86400) * 1e6)})
    b.close()
    assert ola.get("/api/recordings?source=sqlite&trash=1")[1]["recordings"] == []
    assert ola.get("/api/recordings?source=sqlite")[1]["recordings"] == []
    b = st.open_backend(st.StoreConfig(kind="sqlite", sqlite_path=os.path.join(folder, "recordings.db")))
    try:
        assert b.sessions() == []
    finally:
        b.close()
