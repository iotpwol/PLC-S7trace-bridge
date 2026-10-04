"""Web mode: accounts (hashing, lockout, last admin), the HTTP server (login, roles, CSRF header, overview, users CRUD,
SSE stream) and a hosted connection against the snap7 simulator."""
import http.client
import os
import json
import time

import pytest

from s7trace.core.config import TabConfig
from s7trace.core.types import Signal
from s7trace.web import auth
from s7trace.web.auth import AuthError, UserStore
from s7trace.web.hosted import HostManager
from s7trace.web.server import App, WebServer


@pytest.fixture(scope="module")
def sim():
    from s7trace.sim import Simulator
    s = Simulator(11106)
    s.start()
    time.sleep(0.5)
    yield s
    s.stop()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)                        # fast hashing in tests
    s = UserStore(str(tmp_path / "u.db"))
    yield s
    s.close()


# ---------------------------------------------------------------- accounts
def test_password_hash_roundtrip(monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    salt, h = auth.hash_password("tajne-haslo")
    assert auth.check_password("tajne-haslo", salt, h) and not auth.check_password("inne", salt, h)
    assert auth.hash_password("tajne-haslo")[0] != salt                  # random salt
    assert not auth.check_password("x", "zz", h)                         # broken salt does not raise


def test_roles_order():
    assert auth.role_allows("admin", "operator") and auth.role_allows("operator", "viewer")
    assert not auth.role_allows("viewer", "operator") and not auth.role_allows("?", "viewer")


def test_user_store_basics(store):
    store.add("jan", "viewer", password="haslo1234")
    with pytest.raises(AuthError):
        store.add("JAN", "viewer", password="haslo1234")                 # case-insensitive duplicates
    with pytest.raises(AuthError):
        store.add("ola", "viewer", password="krotkie")                   # < 8 characters
    with pytest.raises(AuthError):
        store.add("bad name!", "viewer", password="haslo1234")
    assert store.authenticate("Jan", "haslo1234")["username"] == "jan"
    with pytest.raises(AuthError):
        store.authenticate("jan", "zle-haslo")
    with pytest.raises(AuthError):
        store.authenticate("nikt", "haslo1234")
    store.set_password("jan", "nowehaslo1")
    assert store.authenticate("jan", "nowehaslo1")
    store.set_disabled("jan", True)
    with pytest.raises(AuthError):
        store.authenticate("jan", "nowehaslo1")


def test_lockout_after_failures(store):
    store.add("jan", "viewer", password="haslo1234")
    for _ in range(auth.MAX_FAILS):
        with pytest.raises(AuthError):
            store.authenticate("jan", "zle", "10.0.0.5")
    with pytest.raises(AuthError, match="Za dużo"):
        store.authenticate("jan", "haslo1234", "10.0.0.5")               # even the right password is refused for a while
    assert store.authenticate("jan", "haslo1234", "10.0.0.6")            # another address is not locked


def test_last_admin_protected(store):
    store.add("a", "admin", password="haslo1234")
    for call in (lambda: store.set_role("a", "viewer"), lambda: store.set_disabled("a", True), lambda: store.delete("a")):
        with pytest.raises(AuthError):
            call()
    store.add("b", "admin", password="haslo1234")
    store.set_role("a", "viewer")                                        # fine while another admin remains
    assert store.get("a")["role"] == "viewer"


def test_windows_account_uses_windows_check(store):
    store.add("DOM\\jan", "operator", kind="windows")
    seen = []
    store.windows_check = lambda u, p: seen.append((u, p)) or p == "ok"
    assert store.authenticate("dom\\jan", "ok")["kind"] == "windows"
    with pytest.raises(AuthError):
        store.authenticate("DOM\\jan", "bad")
    assert seen[0] == ("DOM\\jan", "ok")
    with pytest.raises(AuthError):
        store.set_password("DOM\\jan", "haslo1234")                      # no local password for a Windows account


# ---------------------------------------------------------------- server
class Client:
    def __init__(self, srv):
        self.host, self.port, self.cookie = srv.server_address[0], srv.server_address[1], ""

    def call(self, method, path, body=None, csrf=True):
        c = http.client.HTTPConnection(self.host, self.port, timeout=10)
        h = {"Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        if csrf:
            h["X-S7Trace"] = "1"
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cookie = sc.split(";")[0] if not sc.split(";")[0].endswith("=") else ""
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body or {}, **kw)


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    app = App(str(tmp_path / "web"), HostManager(str(tmp_path / "web" / "workspaces")))
    s = WebServer(app, "127.0.0.1", 0)
    s.start()
    yield s
    s.stop()


def _admin(srv):
    c = Client(srv)
    assert c.post("/api/setup", {"username": "admin", "password": "haslo1234"})[0] == 200
    return c


def test_static_pages(srv):
    c = Client(srv)
    st, body = c.get("/")
    assert st == 200 and b"S7Trace" in body
    assert c.get("/static/app.js")[0] == 200 and c.get("/static/style.css")[0] == 200
    assert c.get("/static/../server.py")[0] == 404 and c.get("/static/nie-ma.js")[0] == 404


def test_first_run_setup_and_login(srv):
    c = Client(srv)
    assert c.get("/api/me")[1] == {"user": None, "first_run": True, "sso": False}
    assert c.get("/api/overview")[0] == 401
    c = _admin(srv)
    assert c.get("/api/me")[1]["role"] == "admin"
    assert Client(srv).post("/api/setup", {"username": "x", "password": "haslo1234"})[0] == 403    # only the first time
    other = Client(srv)
    assert other.get("/api/me")[1] == {"user": None, "first_run": False, "sso": False}
    assert other.post("/api/login", {"username": "admin", "password": "zle"})[0] == 400
    assert other.post("/api/login", {"username": "admin", "password": "haslo1234"})[0] == 200
    other.post("/api/logout")
    assert other.get("/api/overview")[0] == 401


def test_csrf_header_required(srv):
    c = Client(srv)
    st, d = c.post("/api/setup", {"username": "admin", "password": "haslo1234"}, csrf=False)
    assert st == 403 and srv.app.users.count() == 0


def test_users_admin_and_roles(srv):
    adm = _admin(srv)
    assert adm.post("/api/users", {"action": "add", "username": "ola", "kind": "local", "password": "haslo1234",
                                   "role": "viewer"})[0] == 200
    assert adm.post("/api/users", {"action": "add", "username": "DOM\\jan", "kind": "windows", "role": "operator"})[0] == 200
    names = [u["username"] for u in adm.get("/api/users")[1]["users"]]
    assert names == sorted(names, key=str.lower) and {"admin", "ola", "DOM\\jan"} <= set(names)
    ola = Client(srv)
    assert ola.post("/api/login", {"username": "ola", "password": "haslo1234"})[0] == 200
    assert ola.get("/api/users")[0] == 403                               # viewer is no administrator
    assert ola.post("/api/connections/c1/start")[0] == 403               # nor an operator
    assert adm.post("/api/users", {"action": "role", "username": "ola", "role": "operator"})[0] == 200
    assert adm.post("/api/users", {"action": "disable", "username": "ola", "disabled": True})[0] == 200
    assert ola.get("/api/overview")[0] == 401                            # blocking drops the sessions
    assert adm.post("/api/users", {"action": "delete", "username": "admin"})[0] == 400     # the last administrator
    assert adm.post("/api/users", {"action": "nonsense", "username": "x"})[0] == 400


def test_overview_lists_sessions(srv):
    adm = _admin(srv)
    ola_store = srv.app.users
    ola_store.add("ola", "viewer", password="haslo1234")
    ola = Client(srv)
    ola.post("/api/login", {"username": "ola", "password": "haslo1234"})
    d = adm.get("/api/overview")[1]
    users = {s["username"]: s for s in d["sessions"]}
    assert set(users) == {"admin", "ola"} and users["ola"]["address"] == "127.0.0.1" and users["ola"]["kind"]
    assert d["connections"] == [] and d["me"]["user"] == "admin"


# ---------------------------------------------------------------- hosted connections + stream
def _cfg(port):
    c = TabConfig()
    c.name, c.ip, c.rack, c.slot, c.cycle_ms = "Sim", f"127.0.0.1:{port}", 0, 2, 25
    c.signals = [Signal(name="b0", dtype="BOOL", db=1, byte=100, bit=0), Signal(name="b1", dtype="BOOL", db=1, byte=100, bit=1)]
    return c


def _wait(cond, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_hosted_start_stop_and_series(sim):
    sim.db1[100] = 0b00000011
    h = HostManager().add(_cfg(11106))
    d = h.describe()
    assert d["state"] == "stopped" and d["name"] == "Sim" and d["signals"] == ["b0", "b1"]
    h.start("ola")
    try:
        assert _wait(lambda: h.state == "running" and len(h.buffer) > 10)
        d = h.describe()
        assert d["started_by"] == "ola" and d["samples"] > 10 and d["method"]
        s = h.series(5)
        assert s["names"] == ["b0", "b1"] and len(s["t"]) == len(s["values"][0]) > 5 and s["values"][0][-1] == 1.0
        later = h.series(5, since=s["t"][-1])
        assert all(t > s["t"][-1] for t in later["t"])
        assert len(h.series(5, max_points=7)["t"]) <= 7
        h.start("ktos")                                                  # a second Start is ignored
        assert h.started_by == "ola"
    finally:
        h.shutdown()
    assert h.state == "stopped"


def test_hosted_start_without_signals():
    c = _cfg(1)
    c.signals = []
    with pytest.raises(ValueError):
        HostManager().add(c).start()


def test_server_start_stop_and_stream(tmp_path, sim, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    sim.db1[100] = 0b00000001
    hosts = HostManager()
    hosts.add(_cfg(11106), owner="serwer")
    s = WebServer(App(str(tmp_path / "web"), hosts), "127.0.0.1", 0)
    s.start()
    try:
        adm = _admin(s)
        st, d = adm.post("/api/connections/c1/start")
        assert st == 200 and d["started_by"] == "admin"
        assert adm.post("/api/connections/c9/start")[0] == 404
        assert _wait(lambda: adm.get("/api/connections/c1")[1]["samples"] > 10)
        assert _wait(lambda: adm.get("/api/overview")[1]["connections"][0]["state"] == "running")
        # SSE: the first message resets the chart, the next ones carry new samples; the session shows what it watches
        c = http.client.HTTPConnection(*s.server_address, timeout=10)
        c.request("GET", "/api/connections/c1/stream?seconds=5", headers={"Cookie": adm.cookie})
        r = c.getresponse()
        assert r.status == 200 and r.getheader("Content-Type") == "text/event-stream"
        msgs = []
        while len(msgs) < 3:
            line = r.fp.readline().decode()
            if line.startswith("data: "):
                msgs.append(json.loads(line[6:]))
        assert msgs[0]["reset"] is True and msgs[0]["names"] == ["b0", "b1"] and msgs[0]["description"]["name"] == "Sim"
        assert msgs[1]["reset"] is False
        ov = adm.get("/api/overview")[1]
        assert ov["connections"][0]["viewers"] == ["admin"] and ov["sessions"][0]["viewing"] == "c1"
        r.close()
        c.close()                                                        # the browser leaves the page
        assert _wait(lambda: adm.get("/api/overview")[1]["connections"][0]["viewers"] == [], 8)
        assert adm.post("/api/connections/c1/stop")[0] == 200
        assert _wait(lambda: adm.get("/api/connections/c1")[1]["state"] == "stopped")
    finally:
        s.stop()


def test_device_info_in_overview(srv):
    h = srv.app.hosts.add(_cfg(1))
    h._on_info({"info": {"module_name": "CPU 1214C", "plc_name": "Linia1", "serial": "S Q", "skip": [1, 2], "empty": ""}})
    adm = _admin(srv)
    dev = adm.get("/api/overview")[1]["connections"][0]["device"]
    assert dev == {"module_name": "CPU 1214C", "plc_name": "Linia1", "serial": "S Q"}


def test_self_signed_cert_and_cli_adduser(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    from s7trace.web.__main__ import main, self_signed_cert
    cert, key = self_signed_cert(str(tmp_path))
    assert self_signed_cert(str(tmp_path)) == (cert, key)                # reused
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "haslo1234")
    assert main(["--data", str(tmp_path / "d"), "--add-user", "boss"]) == 0
    assert UserStore(str(tmp_path / "d" / "web_users.db")).get("boss")["role"] == "admin"


# ---------------------------------------------------------------- own workspace of every account + editing
def _user(srv, name, role="operator"):
    srv.app.users.add(name, role, password="haslo1234")
    c = Client(srv)
    assert c.post("/api/login", {"username": name, "password": "haslo1234"})[0] == 200
    return c


NEW = {"name": "Linia 1", "ip": "10.0.0.5", "rack": 0, "slot": 1, "cycle_ms": 50,
       "signals": [{"name": "A", "dtype": "INT", "db": 2, "byte": 4}, {"name": "B", "dtype": "BOOL", "byte": 0, "bit": 3}]}


def test_edit_validation():
    from s7trace.web import editing
    cfg = TabConfig()
    assert editing.apply(cfg, NEW, running=False) == ["name", "ip", "rack", "slot", "cycle_ms", "signals"]
    assert [s.name for s in cfg.signals] == ["A", "B"] and cfg.signals[0].dtype == "INT" and cfg.signals[1].bit == 3
    assert cfg.signals[0].color != cfg.signals[1].color                  # distinct default colours
    for bad in ({"rack": 9}, {"slot": "x"}, {"cycle_ms": 1}, {"ip": "a b"}, {"ip": ""}, {"conn_type": "zzz"}, {"mode": "?"},
                {"signals": []}, {"signals": [{"name": "x", "dtype": "NOPE"}]}, {"signals": [{"name": ""}]},
                {"signals": [{"name": "a"}, {"name": "A"}]}, {"signals": [{"name": "a", "bit": 8}]},
                {"signals": [{"name": "a", "color": "red"}]}, {"signals": [{"name": "a", "source": "XX"}]},
                {"signals": "no"}, {"name": 5}):
        with pytest.raises(editing.EditError):
            editing.apply(cfg, bad, running=False)
    assert cfg.rack == 0 and cfg.slot == 1                               # nothing from a rejected patch is applied
    with pytest.raises(editing.EditError, match="Zatrzymaj"):
        editing.apply(cfg, {"ip": "1.1.1.1"}, running=True)
    assert editing.apply(cfg, {"name": "Nowa", "window_s": 30}, running=True) == ["name", "window_s"]
    editing.apply(cfg, {"conn": {"username": "u", "password": "tajne", "cert": "C:/x", "evil": 1}}, running=False)
    assert cfg.conn["username"] == "u" and cfg.conn["password"] == "tajne" and cfg.conn["cert"] == "" and "evil" not in cfg.conn
    editing.apply(cfg, {"conn": {"password": ""}}, running=False)         # an empty field keeps the stored password
    assert cfg.conn["password"] == "tajne"
    v = editing.view(cfg)
    assert "password" not in v["conn"] and v["conn"]["has_password"] is True


def test_workspace_per_account(srv, tmp_path):
    adm = _admin(srv)
    ola, jan = _user(srv, "ola"), _user(srv, "DOM\\jan")
    srv.app.hosts.add(_cfg(1))                                           # shared (no owner)
    st, d = ola.post("/api/connections", NEW)
    assert st == 200 and d["owner"] == "ola" and d["can_edit"] and d["state"] == "stopped" and d["signals"] == ["A", "B"]
    cid = d["id"]
    names = lambda c: sorted(x["name"] for x in c.get("/api/overview")[1]["connections"])
    assert names(ola) == ["Linia 1", "Sim"] and names(jan) == ["Sim"]    # own + shared; the other account sees only shared
    assert names(adm) == ["Linia 1", "Sim"]                              # the administrator sees everything
    assert jan.get(f"/api/connections/{cid}")[0] == 404 and jan.get(f"/api/connections/{cid}/config")[0] == 404
    assert jan.post(f"/api/connections/{cid}/start")[0] == 404 and jan.post(f"/api/connections/{cid}/config", {"name": "x"})[0] == 404
    assert jan.post(f"/api/connections/{cid}/delete")[0] == 404
    cfg = ola.get(f"/api/connections/{cid}/config")[1]
    assert cfg["ip"] == "10.0.0.5" and cfg["signals"][0]["name"] == "A" and "sources" in cfg["options"]
    # editing: validated, saved, the others stay untouched
    assert ola.post(f"/api/connections/{cid}/config", {"ip": "999 x"})[0] == 400
    st, d = ola.post(f"/api/connections/{cid}/config", {"name": "Linia 2", "cycle_ms": 100,
                                                          "signals": [{"name": "Z", "dtype": "REAL", "byte": 8}]})
    assert st == 200 and d["name"] == "Linia 2" and d["signals"] == ["Z"] and d["cycle_ms"] == 100
    # the shared connection: everybody (operator) may run it, only the administrator edits it
    assert jan.get("/api/connections/c1/config")[0] == 403 and jan.post("/api/connections/c1/config", {"name": "x"})[0] == 403
    assert adm.get("/api/connections/c1/config")[0] == 200
    assert jan.post("/api/connections", {"name": "x", "ip": "1.2.3.4", "cycle_ms": 2})[0] == 400    # invalid new connection
    # a viewer cannot create anything
    viewer = _user(srv, "kasia", "viewer")
    assert viewer.post("/api/connections", NEW)[0] == 403 and viewer.get("/api/options")[0] == 200
    # persisted per account and restored by a new manager
    ws = srv.app.hosts.store_dir
    assert sorted(os.listdir(ws)) == ["_shared.json", "u_ola.json"]
    again = HostManager(ws)
    h = again.get(cid)
    assert h.owner == "ola" and h.cfg.name == "Linia 2" and h.cfg.signals[0].name == "Z" and again.get("c1").owner == ""
    assert again.add(TabConfig(), "ola").id != cid                       # ids stay unique after a restart
    # deleting
    assert ola.post(f"/api/connections/{cid}/delete")[0] == 200 and ola.get(f"/api/connections/{cid}")[0] == 404
    assert "u_ola.json" not in os.listdir(ws)


def test_workspace_limits_and_running(srv, sim):
    sim.db1[100] = 1
    ola = _user(srv, "ola")
    d = ola.post("/api/connections", {**NEW, "ip": "127.0.0.1:11106", "slot": 2,
                                      "signals": [{"name": "b0", "dtype": "BOOL", "db": 1, "byte": 100, "bit": 0}]})[1]
    cid = d["id"]
    try:
        assert ola.post(f"/api/connections/{cid}/start")[0] == 200
        assert _wait(lambda: ola.get(f"/api/connections/{cid}")[1]["state"] == "running")
        st, err = ola.post(f"/api/connections/{cid}/config", {"ip": "1.1.1.1"})
        assert st == 400 and "Zatrzymaj" in err["error"]
        assert ola.post(f"/api/connections/{cid}/config", {"name": "Zmieniona"})[0] == 200    # a name may change while running
        assert ola.post(f"/api/connections/{cid}/delete")[0] == 400                          # but not the deletion
    finally:
        ola.post(f"/api/connections/{cid}/stop")
        _wait(lambda: ola.get(f"/api/connections/{cid}")[1]["state"] == "stopped")
    for _ in range(srv.app.hosts.MAX_PER_USER - 1):
        assert ola.post("/api/connections", NEW)[0] == 200
    assert ola.post("/api/connections", NEW)[0] == 400                   # per-account limit
