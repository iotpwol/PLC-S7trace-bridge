"""Web mode, stage 3: the connection wizard, desktop programs reporting to the server, single sign-on with the Windows account."""
import http.client
import json
import os
import sys
import time

import pytest

from s7trace.core import sessions, web_agent
from s7trace.web import auth, sso
from s7trace.web.server import App, WebServer
from tests.test_web import Client, _admin, _user

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
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)
    s = WebServer(App(str(tmp_path / "web")), "127.0.0.1", 0)
    s.start()
    yield s
    s.stop()


# ---------------------------------------------------------------- wizard
def test_wizard_detects_s7(srv, sim):
    ola = _user(srv, "ola")
    st, d = ola.post("/api/detect", {"ip": f"127.0.0.1:{PORT}", "rack": 0, "slot": 2, "conn_type": "s7"})
    assert st == 200 and d["recommended"] == "s7" and d["methods"]["s7"]["ok"]
    assert any(s["key"] == "s7" and s["status"] == "ok" for s in d["steps"]) and "Raport kreatora" in d["report"]
    assert d["info"] and (d["rack"], d["slot"]) == (0, 2)
    st, d = ola.post("/api/detect", {"ip": "127.0.0.1:1", "rack": 0, "slot": 2, "conn_type": "s7"})
    assert st == 200 and d["recommended"] is None and d["advice"]                       # nothing listens there
    for bad in ({"ip": "a b", "rack": 0, "slot": 2}, {"ip": "1.2.3.4", "rack": 9, "slot": 2}, {"ip": "1.2.3.4", "rack": 0, "slot": 2, "conn_type": "x"}):
        assert ola.post("/api/detect", bad)[0] == 400
    assert _user(srv, "kasia", "viewer").post("/api/detect", {"ip": "1.2.3.4", "rack": 0, "slot": 2})[0] == 403


# ---------------------------------------------------------------- desktop programs report to the server
def _agent(srv, token, body, csrf=True):
    c = http.client.HTTPConnection(*srv.server_address, timeout=10)
    h = {"Content-Type": "application/json", "X-S7Trace-Agent": token}
    if csrf:
        h["X-S7Trace"] = "1"
    c.request("POST", "/api/agent/report", json.dumps(body), h)
    r = c.getresponse()
    data = json.loads(r.read())
    c.close()
    return r.status, data


def test_agent_tokens_and_reports(srv, sim):
    adm = _admin(srv)
    ola = _user(srv, "ola")
    assert ola.get("/api/agent-tokens")[0] == 403 and ola.post("/api/agent-tokens", {"action": "add", "name": "x"})[0] == 403
    st, d = adm.post("/api/agent-tokens", {"action": "add", "name": "Hala 1"})
    token = d["token"]
    assert st == 200 and len(token) > 30 and adm.post("/api/agent-tokens", {"action": "add", "name": "hala 1"})[0] == 400
    assert [t["name"] for t in adm.get("/api/agent-tokens")[1]["tokens"]] == ["Hala 1"] and token not in str(adm.get("/api/agent-tokens")[1])
    body = {"id": "A1", "user": "jan", "host": "PC-JAN", "pid": 1, "started": "2026-10-04T10:00:00",
            "tabs": [{"title": "Linia", "ip": "10.1.1.5:102", "state": "running", "since": "2026-10-04T10:01:00"},
                     {"title": "Stoi", "ip": "10.1.1.6", "state": "stopped", "since": None}]}
    assert _agent(srv, "zly-token", body)[0] == 401 and _agent(srv, token, body, csrf=False)[0] == 403
    assert _agent(srv, token, {**body, "id": ""})[0] == 400
    st, ans = _agent(srv, token, body)
    assert st == 200 and ans["scans"] == []                                           # nobody else scans
    st, ans = _agent(srv, token, {**body, "id": "A2", "user": "ola", "host": "PC-OLA", "tabs": []})
    assert [(s["ip"], s["user"], s["computer"], s["title"]) for s in ans["scans"]] == [("10.1.1.5", "jan", "PC-JAN", "Linia")]
    ov = adm.get("/api/overview")[1]
    assert sorted(a["host"] for a in ov["agents"]) == ["PC-JAN", "PC-OLA"] and ov["agents"][0]["tabs"][0]["ip"] == "10.1.1.5:102"
    assert "token" not in ov["agents"][0]
    # a hosted connection to the same PLC shows who else scans it, and the server's own scans are reported back to programs
    srv.app.hosts.add(__import__("s7trace.core.config", fromlist=["TabConfig"]).TabConfig(ip="10.1.1.5"), "")
    assert adm.get("/api/overview")[1]["connections"][0]["others"] == ["jan (PC-JAN)"]
    adm.post("/api/agent-tokens", {"action": "delete", "name": "Hala 1"})
    assert _agent(srv, token, body)[0] == 401                                          # a deleted token stops working


def test_reporter_and_warning_before_start(srv):
    adm = _admin(srv)
    token = adm.post("/api/agent-tokens", {"action": "add", "name": "t"})[1]["token"]
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    other = web_agent.WebReporter(lambda: {"id": "OTHER", "user": "jan", "host": "PC-JAN", "started": "x",
                                           "tabs": [{"title": "Linia", "ip": "10.2.2.2:102", "state": "running", "since": "2026-10-04T10:00:00"}]},
                                  {"enabled": True, "url": url, "token": token})
    mine = web_agent.WebReporter(lambda: {"id": "MINE", "user": "ola", "host": "PC-OLA", "started": "x", "tabs": []},
                                 {"enabled": True, "url": url, "token": token})
    assert other.report_once() and other.status == "połączono" and mine.report_once()
    (w,) = mine.others_scanning("10.2.2.2")
    assert w == {"user": "jan (PC-JAN)", "title": "Linia", "since": "2026-10-04T10:00:00", "session": None}
    assert mine.others_scanning("10.2.2.3") == [] and mine.others_scanning("10.2.2.2", ("OTHER",)) == []   # (the same program, seen locally)
    # the warning of the desktop program (sessions.others_scanning) includes the remote scans
    sessions.REMOTE = mine
    try:
        assert [o["user"] for o in sessions.others_scanning("10.2.2.2:102")] == ["jan (PC-JAN)"]
    finally:
        sessions.REMOTE = None
    bad = web_agent.WebReporter(lambda: {"id": "X"}, {"enabled": True, "url": url, "token": "zly"})
    assert not bad.report_once() and "token" in bad.status.lower()
    off = web_agent.WebReporter(lambda: {}, {"enabled": False, "url": url, "token": token})
    off.start()
    assert off.status == "wyłączone"
    assert web_agent.normalize({"url": " http://x/ ", "enabled": "yes"})["url"] == "http://x" and web_agent.normalize(None)["verify"] is True
    mine._at = time.time() - 100                                                        # an old answer is not used
    assert mine.others_scanning("10.2.2.2") == []


# ---------------------------------------------------------------- single sign-on (Windows only)
pytestmark_win = pytest.mark.skipif(sys.platform != "win32", reason="SSPI exists only on Windows")


def _whoami() -> str:
    return f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"


def _negotiate(client: Client, srv, headers=None, user_agent="t"):
    """Runs the browser's side of the exchange on ONE connection; returns (status, body, cookie)."""
    c = http.client.HTTPConnection(*srv.server_address, timeout=15)
    neg = sso.NegotiateClient("HTTP/localhost")
    try:
        token, status, data, cookie = None, 0, {}, ""
        for _ in range(6):
            h = {"X-S7Trace": "1", "User-Agent": user_agent, **(headers or {})}
            if token is not None:
                h["Authorization"] = "Negotiate " + sso.b64(token)
            c.request("GET", "/api/sso", headers=h)
            r = c.getresponse()
            data = json.loads(r.read())
            status, cookie = r.status, r.getheader("Set-Cookie") or ""
            www = r.getheader("WWW-Authenticate") or ""
            if status != 401:
                return status, data, cookie
            import base64
            challenge = base64.b64decode(www.split(" ", 1)[1]) if " " in www else None
            _done, token = neg.step(challenge)
        return status, data, cookie
    finally:
        neg.close()
        c.close()


@pytest.mark.skipif(sys.platform != "win32", reason="SSPI exists only on Windows")
def test_sso_login_with_current_windows_account(srv):
    adm = _admin(srv)
    c = Client(srv)
    assert c.get("/api/me")[1]["sso"] is False and c.get("/api/sso")[0] == 404         # off by default
    srv.app.sso = True
    assert Client(srv).get("/api/me")[1]["sso"] is True
    # no credentials: a Negotiate challenge (the browser then sends them); no header against CSRF: refused
    cc = http.client.HTTPConnection(*srv.server_address, timeout=10)
    cc.request("GET", "/api/sso", headers={"X-S7Trace": "1"})
    r = cc.getresponse()
    r.read()
    assert r.status == 401 and r.getheader("WWW-Authenticate") == "Negotiate"
    cc.request("GET", "/api/sso")
    r = cc.getresponse()
    r.read()
    assert r.status == 403
    cc.close()
    # the account is not registered yet
    st, d, _ = _negotiate(c, srv)
    assert st == 403 and "nie jest zarejestrowane" in d["error"] and _whoami().lower().split("\\")[1] in d["error"].lower()
    # registered by an administrator -> a session with the role of that account
    assert adm.post("/api/users", {"action": "add", "username": _whoami(), "kind": "windows", "role": "operator"})[0] == 200
    st, d, cookie = _negotiate(c, srv)
    assert st == 200 and d["role"] == "operator" and d["user"].lower() == _whoami().lower()
    c.cookie = cookie.split(";")[0]
    me = c.get("/api/me")[1]
    assert me["user"].lower() == _whoami().lower() and me["kind"] == "windows"
    assert any(s["username"].lower() == _whoami().lower() and s["kind"] for s in adm.get("/api/overview")[1]["sessions"])
    # a blocked account cannot sign in
    adm.post("/api/users", {"action": "disable", "username": _whoami(), "disabled": True})
    assert _negotiate(Client(srv), srv)[0] == 403
    # a local account registered under its bare name (COMPUTER\user -> user) is accepted too
    if _whoami().split("\\")[0].lower() == os.environ.get("COMPUTERNAME", "").lower():
        adm.post("/api/users", {"action": "delete", "username": _whoami()})
        adm.post("/api/users", {"action": "add", "username": os.environ["USERNAME"], "kind": "windows", "role": "viewer"})
        assert _negotiate(Client(srv), srv)[0] == 200


def test_sso_account_matching():
    users = {"DOM\\jan": {"username": "DOM\\jan"}, "ola": {"username": "ola"}}
    assert sso.match_account("DOM\\jan", users.get) == users["DOM\\jan"]
    assert sso.match_account("OTHER\\jan", users.get) is None
    os.environ["COMPUTERNAME"], old = "PC1", os.environ.get("COMPUTERNAME")
    try:
        assert sso.match_account("pc1\\ola", users.get) == users["ola"] and sso.match_account("PC2\\ola", users.get) is None
    finally:
        if old is None:
            del os.environ["COMPUTERNAME"]
        else:
            os.environ["COMPUTERNAME"] = old
