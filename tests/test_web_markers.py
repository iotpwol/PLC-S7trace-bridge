"""Web mode: markers (visibility, ranges, signals, groups, styles) and the value search in a connection / a recording."""
import os
from datetime import datetime
from urllib.parse import quote

import numpy as np
import pytest

from s7trace.core import store as st
from s7trace.core.config import TabConfig
from s7trace.core.types import Signal
from s7trace.web import auth, files
from s7trace.web.server import App, WebServer
from tests.test_web import Client, _admin, _user

START = datetime(2026, 10, 4, 12, 0, 0)
BASE = int(START.timestamp() * 1e6)


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    s = WebServer(App(str(tmp_path / "web")), "127.0.0.1", 0)
    s.start()
    yield s
    s.stop()


def _host(srv, owner="", name="Linia"):
    """A hosted connection (not started) that holds 100 s of samples: A = ramp 0..99, B = 1 between 30 and 50 s."""
    cfg = TabConfig(ip="10.0.0.5", name=name)
    cfg.signals = [Signal(name="A", dtype="INT"), Signal(name="B", dtype="BOOL")]
    h = srv.app.hosts.add(cfg, owner=owner)
    h.signals = [Signal.from_dict(s.to_dict()) for s in cfg.signals]
    t = np.arange(0, 100, 0.5)
    h.buffer.reset(2)
    h.buffer.load(t, np.column_stack([t, ((t >= 30) & (t < 50)).astype(float)]))
    h.start_wall = START
    return h


def test_marker_visibility_and_rules(srv):
    adm = _admin(srv)
    ola, jan = _user(srv, "ola"), _user(srv, "jan")
    view = _user(srv, "gosc", "viewer")
    mine = _host(srv, owner="ola")
    shared = _host(srv, owner="", name="Wspólne")
    code, d = ola.post("/api/markers", {"action": "add", "at_us": BASE + 5_000_000, "title": "Alarm", "conn": mine.id,
                                         "description": "opis", "notes": "uwagi", "color": "#ff0000", "priority": 3})
    assert code == 200
    m = d["marker"]
    assert m["author"] == "ola" and m["can_edit"] and m["conn_name"] == "Linia" and m["created_us"] == m["modified_us"]
    assert m["kind"] == "point" and m["signals"] == [] and m["priority"] == 3 and m["color"] == "#ff0000"
    ids = lambda c, qs="": [x["id"] for x in c.get("/api/markers" + qs)[1]["markers"]]
    assert ids(ola) == [m["id"]] and ids(adm) == [m["id"]] and ids(jan) == []             # a private connection: its author + admin
    assert jan.post("/api/markers", {"action": "add", "at_us": BASE, "conn": mine.id})[0] == 400   # not jan's connection
    assert view.post("/api/markers", {"action": "add", "at_us": BASE})[0] == 403                    # viewers only read
    # a marker on a shared connection is visible to everybody who may view it, changed only by its author / admin
    code, d = ola.post("/api/markers", {"action": "add", "at_us": BASE + 9_000_000, "title": "Wspólny", "conn": shared.id})
    sid = d["marker"]["id"]
    assert ids(jan) == [sid] and ids(view) == [sid] and set(ids(ola)) == {m["id"], sid}
    jm = jan.get("/api/markers")[1]["markers"][0]
    assert jm["can_edit"] is False
    assert jan.post("/api/markers", {"action": "update", "id": sid, "title": "x"})[0] == 400
    assert jan.post("/api/markers", {"action": "delete", "id": sid})[0] == 400
    assert adm.post("/api/markers", {"action": "update", "id": sid, "title": "Admin"})[0] == 200
    got = ola.post("/api/markers", {"action": "update", "id": sid, "title": "Nowy", "notes": "n", "priority": 0})[1]["marker"]
    assert got["title"] == "Nowy" and got["modified_by"] == "ola" and got["modified_us"] >= got["created_us"]
    assert ola.post("/api/markers", {"action": "update", "id": m["id"], "author": "jan", "conn": shared.id, "rec_id": "z",
                                     "title": "t"})[1]["marker"]["author"] == "ola"              # author / connection are not editable
    assert ola.get("/api/markers")[1]["markers"][1]["conn"] in ("", shared.id, mine.id)
    assert ola.post("/api/markers", {"action": "delete", "id": m["id"]})[0] == 200
    assert ids(ola) == [sid]
    assert ola.post("/api/markers", {"action": "delete", "id": 9999})[0] == 400
    assert ola.post("/api/markers", {"action": "zzz"})[0] == 400
    assert Client(srv).get("/api/markers")[0] == 401


def test_ranges_signals_styles_validation(srv):
    ola = _user(srv, "ola")
    h = _host(srv, owner="ola")
    ok = ola.post("/api/markers", {"action": "add", "kind": "range", "at_us": BASE + 20_000_000, "end_us": BASE + 10_000_000,
                                   "signals": ["A", "A"], "title": "Zakres", "line_width": 5, "line_style": "dash", "opacity": 60,
                                   "group_name": "Zdarzenie", "conn": h.id})
    assert ok[0] == 200
    m = ok[1]["marker"]
    assert (m["at_us"], m["end_us"]) == (BASE + 10_000_000, BASE + 20_000_000) and m["signals"] == ["A"]
    assert (m["line_width"], m["line_style"], m["opacity"], m["group_name"]) == (5, "dash", 60, "Zdarzenie")
    for bad in ({"kind": "range"}, {"kind": "x"}, {"color": "red"}, {"priority": 7}, {"line_width": 99}, {"line_style": "?"},
                {"opacity": 500}, {"signals": "A"}, {"title": "x" * 300}, {"at_us": 5}, {"conn": "nie-ma"}):
        code, d = ola.post("/api/markers", {"action": "add", "at_us": BASE, **bad})
        assert code == 400 and d["error"], bad
    assert ola.post("/api/markers", {"action": "add", "title": "bez czasu"})[0] == 400
    # an update that moves the start past the end keeps the range ordered
    u = ola.post("/api/markers", {"action": "update", "id": m["id"], "at_us": BASE + 30_000_000})[1]["marker"]
    assert (u["at_us"], u["end_us"]) == (BASE + 20_000_000, BASE + 30_000_000)
    u = ola.post("/api/markers", {"action": "update", "id": m["id"], "kind": "point"})[1]["marker"]
    assert u["kind"] == "point" and u["end_us"] == 0


def test_listing_filters_and_groups(srv):
    adm = _admin(srv)
    ola, jan = _user(srv, "ola"), _user(srv, "jan")
    a = _host(srv, owner="ola", name="A")
    b = _host(srv, owner="jan", name="B")
    add = lambda c, **k: c.post("/api/markers", {"action": "add", **k})[1]["marker"]
    m1 = add(ola, at_us=BASE + 1_000_000, title="Pompa start", conn=a.id, color="#00ff00", priority=2)
    m2 = add(ola, at_us=BASE + 2_000_000, title="Pompa stop", conn=a.id, group_name="Pompa")
    m3 = add(ola, at_us=BASE + 90_000_000, title="Inne", rec_id="sqlite|r1", notes="Łódź")
    m4 = add(jan, at_us=BASE + 3_000_000, title="Jana", conn=b.id)
    L = lambda c, qs: [x["id"] for x in c.get("/api/markers?" + quote(qs, safe="=&|%"))[1]["markers"]]
    assert L(ola, "") == [m1["id"], m2["id"], m3["id"]]
    assert L(ola, "q=pompa") == [m1["id"], m2["id"]] and L(ola, "q=ŁÓDŹ") == [m3["id"]]
    assert L(ola, f"conn={a.id}") == [m1["id"], m2["id"]] and L(ola, "rec=sqlite|r1") == [m3["id"]]
    assert L(ola, "group=Pompa") == [m2["id"]] and L(ola, "group=") == [m1["id"], m3["id"]]
    assert L(ola, f"from={BASE + 1_500_000}&to={BASE + 3_000_000}") == [m2["id"]]
    assert L(ola, "priority=2") == [m1["id"]] and L(ola, "color=%2300ff00") == [m1["id"]]
    assert L(adm, "author=jan") == [m4["id"]] and len(L(adm, "")) == 4
    assert L(jan, "") == [m4["id"]]
    d = ola.get("/api/markers")[1]
    assert d["groups"] == [{"name": "Pompa", "count": 1}] and d["authors"] == ["ola"]
    # groups: put markers together, rename (only own markers), leave the group
    assert ola.post("/api/markers", {"action": "group", "ids": [m1["id"], m3["id"]], "group": "Pompa"})[1]["changed"] == 2
    assert ola.get("/api/markers")[1]["groups"] == [{"name": "Pompa", "count": 3}]
    assert jan.post("/api/markers", {"action": "group", "ids": [m1["id"]], "group": "X"})[0] == 400      # not jan's marker
    assert ola.post("/api/markers", {"action": "group", "ids": [], "group": "X"})[0] == 400
    assert ola.post("/api/markers", {"action": "rename_group", "old": "Pompa", "new": "Awaria pompy"})[1]["changed"] == 3
    assert L(ola, "group=Awaria pompy") == [m1["id"], m2["id"], m3["id"]]
    assert ola.post("/api/markers", {"action": "group", "ids": [m2["id"]], "group": ""})[1]["changed"] == 1
    assert L(ola, "group=Awaria pompy") == [m1["id"], m3["id"]]


def test_search_in_connection_memory(srv):
    ola, jan = _user(srv, "ola"), _user(srv, "jan")
    view = _user(srv, "gosc", "viewer")
    h = _host(srv, owner="ola")
    q = lambda c, **k: c.post("/api/search", {"conn": h.id, **k})
    code, d = q(ola, conds=[{"signal": "B", "op": "==", "a": 1}])
    assert code == 200 and len(d["hits"]) == 1 and d["names"] == ["B"] and d["start_us"] == BASE
    hit = d["hits"][0]
    assert hit["t0"] == 30.0 and abs(hit["duration"] - 20.0) < 0.6 and hit["t0_us"] == BASE + 30_000_000 and hit["values"] == [1.0]
    code, d = q(ola, conds=[{"signal": "A", "op": ">=", "a": 70}, {"signal": "B", "op": "==", "a": 0}])
    assert len(d["hits"]) == 1 and d["hits"][0]["t0"] == 70.0 and d["hits"][0]["vmax"] == 99.5
    code, d = q(ola, conds=[{"signal": "B", "op": "changes"}])
    assert [x["t0"] for x in d["hits"]] == [30.0, 50.0]
    code, d = q(ola, conds=[{"signal": "A", "op": "between", "a": 10, "b": 12}], **{"from": 11, "to": 100})
    assert len(d["hits"]) == 1 and d["hits"][0]["t0"] == 11.0
    code, d = q(ola, conds=[{"signal": "B", "op": "==", "a": 1}], min_duration=60)
    assert d["hits"] == []
    for bad in ([], [{"signal": "Z", "op": "=="}], [{"signal": "A", "op": "??"}], [{"signal": "A", "a": "x"}], "A", [1],
                [{"signal": "A", "op": "==", "a": 1}] * 6):
        assert q(ola, conds=bad)[0] == 400, bad
    assert q(jan, conds=[{"signal": "A", "op": ">", "a": 1}])[0] == 404                       # a private connection of ola
    shared = _host(srv, owner="", name="Wspólne")
    assert view.post("/api/search", {"conn": shared.id, "conds": [{"signal": "A", "op": ">", "a": 90}]})[0] == 200
    assert Client(srv).post("/api/search", {"conn": h.id, "conds": []})[0] == 401


def _record(folder, owner, n=3000):
    cfg = st.StoreConfig(kind="sqlite", mode="all", sqlite_path=os.path.join(folder, "recordings.db"))
    sigs = [Signal(name="A", dtype="INT"), Signal(name="B", dtype="BOOL")]
    rec = st.DbRecorder(cfg, sigs, START, {"title": "Nocna", "owner": owner}, base_dir="")
    for i in range(n):
        rec.write(float(i), [float(i % 100), 1.0 if 1000 <= i < 1500 else 0.0])
    rec.close()
    return rec.session


def test_search_in_a_recording(srv):
    root = srv.app.hosts.files_root
    ola, jan = _user(srv, "ola"), _user(srv, "jan")
    sid = _record(files.account_dir(root, "ola"), "ola")
    code, d = ola.post("/api/search", {"source": "sqlite", "id": sid, "conds": [{"signal": "B", "op": "==", "a": 1}]})
    assert code == 200 and len(d["hits"]) == 1 and d["start_us"] == BASE and d["timeout"] is False
    h = d["hits"][0]
    assert h["t0"] == 1000.0 and abs(h["duration"] - 500.0) < 1.5 and h["t0_us"] == BASE + 1_000_000_000
    code, d = ola.post("/api/search", {"source": "sqlite", "id": sid, "conds": [{"signal": "A", "op": "==", "a": 7}],
                                       "from": 100, "to": 400})
    assert [x["t0"] for x in d["hits"]] == [107.0, 207.0, 307.0]
    assert ola.post("/api/search", {"source": "sqlite", "id": "nie-ma", "conds": [{"signal": "A", "op": ">", "a": 1}]})[0] == 400
    assert ola.post("/api/search", {"source": "sqlite", "id": sid, "conds": [{"signal": "Zły", "op": ">", "a": 1}]})[0] == 400
    assert jan.post("/api/search", {"source": "sqlite", "id": sid, "conds": [{"signal": "A", "op": ">", "a": 1}]})[0] == 400   # not jan's file
    # a marker made on that recording is found with the recording filter
    m = ola.post("/api/markers", {"action": "add", "at_us": h["t0_us"], "end_us": h["t1_us"], "kind": "range", "signals": ["B"],
                                  "rec_id": f"sqlite|{sid}", "title": "Bieg"})[1]["marker"]
    assert [x["id"] for x in ola.get(f"/api/markers?rec=sqlite|{sid}")[1]["markers"]] == [m["id"]]


def test_series_carries_the_wall_clock_start(srv):
    ola = _user(srv, "ola")
    h = _host(srv, owner="ola")
    d = ola.get(f"/api/connections/{h.id}/series?seconds=30")[1]
    assert d["start_us"] == BASE


def test_batch_save_is_one_transaction_and_checks_rights(srv):
    ola, jan = _user(srv, "ola"), _user(srv, "jan")
    view = _user(srv, "gosc", "viewer")
    mine = _host(srv, owner="ola")
    shared = _host(srv, owner="", name="Wspólne")
    keep = ola.post("/api/markers", {"action": "add", "at_us": BASE + 1_000_000, "title": "stary", "conn": mine.id})[1]["marker"]
    gone = ola.post("/api/markers", {"action": "add", "at_us": BASE + 2_000_000, "title": "do usuniecia", "conn": mine.id})[1]["marker"]
    other = jan.post("/api/markers", {"action": "add", "at_us": BASE, "title": "janowy"})[1]["marker"]
    ids = lambda c: sorted(x["title"] for x in c.get("/api/markers")[1]["markers"])
    body = {"action": "batch", "adds": [{"tmp": -1, "at_us": BASE + 5_000_000, "title": "nowy 1", "conn": mine.id, "show_label": 0},
                                         {"tmp": -2, "at_us": BASE + 6_000_000, "kind": "range", "end_us": BASE + 9_000_000, "title": "nowy 2"}],
            "updates": [{"id": keep["id"], "title": "zmieniony", "show_label": 0}], "deletes": [gone["id"]]}
    # one change the account may not make cancels the whole batch
    bad = dict(body, deletes=[gone["id"], other["id"]])
    code, d = ola.post("/api/markers", bad)
    assert code == 400 and ids(ola) == ["do usuniecia", "stary"]
    bad = dict(body, adds=body["adds"] + [{"tmp": -3, "at_us": BASE, "conn": "nie-ma"}])
    assert ola.post("/api/markers", bad)[0] == 400 and ids(ola) == ["do usuniecia", "stary"]
    bad = dict(body, adds=body["adds"] + [{"tmp": -3, "at_us": BASE, "color": "zly"}])             # fails inside the transaction
    assert ola.post("/api/markers", bad)[0] == 400 and ids(ola) == ["do usuniecia", "stary"]
    assert view.post("/api/markers", {"action": "batch", "adds": [{"at_us": BASE}]})[0] == 403
    code, d = ola.post("/api/markers", body)
    assert code == 200 and d["updated"] == 1 and d["deleted"] == 1 and len(d["added"]) == 2 and set(d["new_ids"]) == {"-1", "-2"}
    assert ids(ola) == ["nowy 1", "nowy 2", "zmieniony"]
    got = {x["id"]: x for x in ola.get("/api/markers")[1]["markers"]}
    n1, n2 = got[d["new_ids"]["-1"]], got[d["new_ids"]["-2"]]
    assert n1["author"] == "ola" and n1["show_label"] == 0 and n2["kind"] == "range" and got[keep["id"]]["show_label"] == 0
    assert ola.post("/api/markers", {"action": "batch"})[1]["updated"] == 0                      # nothing to do
    assert ola.post("/api/markers", {"action": "batch", "adds": [{"at_us": BASE}] * 501})[0] == 400
    assert ola.post("/api/markers", {"action": "batch", "adds": "x"})[0] == 400
    assert ids(jan) == ["janowy"] and shared  # untouched


def test_series_carries_share_gain_and_type_for_the_lanes(srv):
    h = _host(srv)
    d = h.series(60)
    assert d["shares"] == [1.0, 1.0] and d["gains"] == [1.0, 1.0] and d["dtypes"] == ["INT", "BOOL"]


def test_web_recording_starts_when_rec_is_pressed(srv):
    h = _host(srv)                                                      # 100 s of samples are already in the buffer
    from s7trace.core import store as stm
    cfg = stm.StoreConfig(kind="sqlite", sqlite_path=os.path.join(srv.app.hosts.files_root, "r.db"), mode="changes")
    rec = stm.DbRecorder(cfg, h.signals, h.start_wall, {"title": "t"}, base_dir=srv.app.hosts.files_root, t0=h.buffer.last_time())
    rec.write(h.buffer.last_time() + 5.0, [1.0, 0.0])
    rec.close()
    b = stm.open_backend(cfg, srv.app.hosts.files_root)
    (s,) = b.sessions()
    b.close()
    assert abs((s["end_us"] - s["start_us"]) / 1e6 - 5.0) < 0.01


def test_marker_look_is_kept_per_account_on_the_server(srv):
    ola, ala = _user(srv, "ola"), _user(srv, "ala")
    assert ola.get("/api/prefs")[1]["prefs"]["marker_look"] == {"width_all": 2, "width_sel": 3, "width_other": 1, "width_hover": 4}
    st_, d = ola.post("/api/prefs", {"marker_look": {"width_all": 5, "width_sel": 99, "width_other": "x", "width_hover": 9}})
    assert st_ == 200 and d["prefs"]["marker_look"] == {"width_all": 5, "width_sel": 12, "width_other": 1, "width_hover": 9}   # validated
    assert ola.get("/api/prefs")[1]["prefs"]["marker_look"]["width_all"] == 5
    assert ala.get("/api/prefs")[1]["prefs"]["marker_look"]["width_all"] == 2          # another account is not affected
    assert os.path.isfile(os.path.join(srv.app.data_dir, "prefs", "u_ola.json"))
