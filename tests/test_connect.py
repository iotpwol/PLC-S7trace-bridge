import json
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from s7trace.core import detect, drivers, planner
from s7trace.core.acq_process import ProcAcquirer
from s7trace.core.buffer import TraceBuffer
from s7trace.core.config import TabConfig
from s7trace.core.types import Signal, address_key
from s7trace.ui import theme as th
from s7trace.ui.main_window import MainWindow
from s7trace.ui.signals_dialog import CI, SignalsDialog
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    th.apply_theme(a, th.DARK)
    yield a
    th.apply_theme(a, th.DARK)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ------------------------------------------------------------------ Modbus mock server
class ModbusServer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        self.regs = {0: 1234, 1: 0xFFFE, 2: 0x4048, 3: 0xF5C3, 10: 0b101}      # 3.14 REAL in regs 2..3 (big-endian words)
        self.coils = {5: 1, 6: 0}
        self.start()

    def run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(c,), daemon=True).start()

    def handle(self, c):
        try:
            while True:
                h = c.recv(12)
                if len(h) < 12:
                    return
                tid, _, _, unit, fc, addr, qty = struct.unpack(">HHHBBHH", h)
                if fc in (3, 4):
                    if addr + qty - 1 > 20 and addr != 0:
                        body = bytes([fc | 0x80, 2])
                    else:
                        vals = [self.regs.get(addr + i, 0) for i in range(qty)]
                        body = bytes([fc, qty * 2]) + b"".join(struct.pack(">H", v) for v in vals)
                else:
                    body = bytes([fc, 1, self.coils.get(addr, 0)])
                c.sendall(struct.pack(">HHHB", tid, 0, len(body) + 1, unit) + body)
        except OSError:
            pass

    def close(self):
        self.srv.close()


@pytest.fixture(scope="module")
def mb():
    s = ModbusServer()
    yield s
    s.close()


def test_modbus_driver_reads_registers_and_coils(mb):
    opts = {**drivers.conn_defaults(), "modbus_port": mb.port}
    d = drivers.ModbusDriver(opts)
    d.connect("127.0.0.1")
    sigs = [Signal(source="MBH", dtype="UINT", byte=0), Signal(source="MBH", dtype="INT", byte=1),
            Signal(source="MBH", dtype="REAL", byte=2), Signal(source="MBC", dtype="BOOL", byte=5),
            Signal(source="MBH", dtype="BOOL", byte=10, bit=2), Signal(source="MBH", dtype="BOOL", byte=10, bit=1)]
    assert d.read(sigs) == [1234.0, -2.0, pytest.approx(3.14, abs=1e-4), 1.0, 1.0, 0.0]
    d.disconnect()
    d2 = drivers.ModbusDriver({**opts, "modbus_wordswap": True})
    d2.connect("127.0.0.1")
    got = d2.read([Signal(source="MBH", dtype="UDINT", byte=0)])[0]
    assert got == struct.unpack(">I", struct.pack(">HH", 0xFFFE, 1234))[0]          # words 0,1 swapped
    d2.disconnect()
    d3 = drivers.ModbusDriver(opts)
    d3.connect("127.0.0.1")
    with pytest.raises(drivers.DriverError, match="wyjątek Modbus 2"):
        d3.read([Signal(source="MBH", dtype="UINT", byte=500)])
    d3.disconnect()


def test_process_acquirer_with_modbus_driver(mb):
    sigs = [Signal(name="r0", source="MBH", dtype="UINT", byte=0), Signal(name="c5", source="MBC", dtype="BOOL", byte=5)]
    buf = TraceBuffer(2)
    opts = {**drivers.conn_defaults(), "modbus_port": mb.port}
    a = ProcAcquirer("127.0.0.1", 0, 2, 25, sigs, planner.MODE_BLOCKS, buf, driver={"type": "modbus", "opts": opts})
    a.start()
    time.sleep(2.5)
    a.stop()
    a.join(8)
    t, v = buf.snapshot()
    assert len(buf) > 10 and list(v[-1]) == [1234.0, 1.0]
    s = a.diag.snapshot()
    assert s["req_per_cycle"] == 2 and s["errors"] == 0 and s["lag"]["avg"] > 0


# ---------------------------------------------------------------------- Web API mock
class WebApi(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        vals = {'"DB_Piec".Temp': 21.5, '"DB_Piec".Run': True}

        def one(r):
            if r["method"] == "Api.Version":
                return {"jsonrpc": "2.0", "id": r["id"], "result": "2.1"}
            if r["method"] == "Api.Login":
                ok = r["params"]["password"] == "tajne"
                return ({"jsonrpc": "2.0", "id": r["id"], "result": {"token": "T1"}} if ok else
                        {"jsonrpc": "2.0", "id": r["id"], "error": {"code": 2, "message": "zle haslo"}})
            if r["method"] == "PlcProgram.Read":
                return {"jsonrpc": "2.0", "id": r["id"], "result": vals[r["params"]["var"]]}
            return {"jsonrpc": "2.0", "id": r["id"], "error": {"code": 1, "message": "nieznana metoda"}}

        out = [one(r) for r in req] if isinstance(req, list) else one(req)
        body = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def web():
    srv = HTTPServer(("127.0.0.1", 0), WebApi)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def test_webapi_driver_login_and_batch_read(web):
    o = {**drivers.conn_defaults(), "web_https": False, "web_port": web, "username": "u", "password": "tajne"}
    d = drivers.WebApiDriver(o)
    d.connect("127.0.0.1")
    assert d.token == "T1"
    assert d.read([Signal(source="WEB", node='"DB_Piec".Temp'), Signal(source="WEB", node='"DB_Piec".Run')]) == [21.5, 1.0]
    d.disconnect()
    bad = drivers.WebApiDriver({**o, "password": "zle"})
    with pytest.raises(drivers.DriverError, match="zle haslo"):
        bad.connect("127.0.0.1")


# ---------------------------------------------------------------------------- OPC UA
@pytest.fixture(scope="module")
def opc():
    pytest.importorskip("asyncua")
    from asyncua.sync import Server
    port = free_port()
    srv = Server()
    srv.set_endpoint(f"opc.tcp://127.0.0.1:{port}")
    srv.start()
    idx = srv.register_namespace("urn:s7trace:test")
    obj = srv.nodes.objects.add_object(idx, "DB_Piec")
    nodes = {"Temp": obj.add_variable(idx, "Temp", 21.5), "Run": obj.add_variable(idx, "Run", True),
             "Cnt": obj.add_variable(idx, "Cnt", 7)}
    yield port, nodes
    srv.stop()


def test_opcua_driver_probe_and_browser(app, opc):
    port, nodes = opc
    o = {**drivers.conn_defaults(), "opcua_port": port}
    d = drivers.OpcUaDriver(o)
    d.connect("127.0.0.1")
    ids = [nodes[k].nodeid.to_string() for k in ("Temp", "Run", "Cnt")]
    assert d.read([Signal(source="OPC", node=i) for i in ids]) == [21.5, 1.0, 7.0]
    d.disconnect()
    res = detect.DetectResult(host="127.0.0.1")
    st = detect.probe_opcua("127.0.0.1", o, res)
    assert st.status == "ok" and res.methods["opcua"]["ok"] and "None" in " ".join(res.info["opcua_policies"])
    assert res.plc_time is not None and abs(res.time_diff_utc) < 5            # server clock vs ours
    from s7trace.ui.opc_browser import OpcBrowser
    b = OpcBrowser("127.0.0.1", o)
    root = b.tree.invisibleRootItem()
    db = next(root.child(i) for i in range(root.childCount()) if root.child(i).text(0) == "DB_Piec")
    b._expand(db)
    assert {db.child(i).text(0) for i in range(db.childCount())} == {"Temp", "Run", "Cnt"}
    for i in range(db.childCount()):
        db.child(i).setSelected(True)
    got = {s.name: s for s in b.signals()}
    assert got["Temp"].dtype == "LREAL" and got["Run"].dtype == "BOOL" and got["Cnt"].dtype == "LREAL"   # Double, Boolean, Int64
    assert all(s.source == "OPC" and s.node for s in got.values())
    b.client.disconnect()
    b.client = None


def test_process_acquirer_with_opcua_driver(opc):
    port, nodes = opc
    sigs = [Signal(name="t", source="OPC", dtype="REAL", node=nodes["Temp"].nodeid.to_string())]
    buf = TraceBuffer(1)
    a = ProcAcquirer("127.0.0.1", 0, 2, 100, sigs, planner.MODE_BLOCKS, buf,
                     driver={"type": "opcua", "opts": {**drivers.conn_defaults(), "opcua_port": port}})
    a.start()
    time.sleep(3.0)
    a.stop()
    a.join(8)
    assert len(buf) > 5 and buf.last_row()[0] == 21.5


def test_client_certificate_generation(tmp_path):
    cert, key = drivers.generate_client_cert(str(tmp_path))
    assert os.path.getsize(cert) > 300 and open(key).read().startswith("-----BEGIN")


# ---------------------------------------------------------------- detection logic
def test_detect_against_s7_simulator_and_time_diff():
    from s7trace.sim import Simulator
    s = Simulator(11111)
    s.start()
    time.sleep(0.5)
    try:
        seen = []
        res = detect.run_detection("127.0.0.1:11111", rack=0, slot=2, stop_at_first=True, ping_runner=lambda h: 0.4,
                                   progress=seen.append)
    finally:
        s.stop()
    assert res.recommended == "s7" and res.methods["s7"]["ok"] and [x.key for x in seen][0] == "ping"
    assert res.info["family"] == "S7-300" and res.info["order_code"].startswith("6ES7") and res.info["firmware"].startswith("V")
    assert res.info["serial"] and res.info["state"] and res.info["s7_access"] == "ok"
    assert res.plc_time is not None and min(abs(res.time_diff_local), abs(res.time_diff_utc)) < 5
    assert "opcua" not in res.methods or not res.methods["opcua"]["ok"]
    assert "S7-300" in detect.format_result(res) and "Czas sterownika" in detect.format_result(res)


def test_recommend_orders_and_advice():
    def result(**methods):
        r = detect.DetectResult(host="h")
        r.methods = {k: {"ok": v, "note": ""} for k, v in methods.items()}
        return r

    r = result(s7=True, opcua=True)
    detect.recommend(r)
    assert r.recommended == "s7"                                    # order: S7comm first
    r = result(s7=False, opcua=True, modbus=True)
    r.info = {"s7_access": "denied", "family": "S7-1500"}
    detect.recommend(r)
    assert r.recommended == "opcua" and any("PUT/GET" in a for a in r.advice)
    r = result(s7=False, opcua=False, webapi=False, modbus=True)
    detect.recommend(r)
    assert r.recommended == "modbus"
    r = result(s7=False, opcua=False)
    r.info = {"s7_access": "range", "family": "S7-1500"}
    detect.recommend(r)
    assert r.recommended is None and any("Sugerowana metoda" in a for a in r.advice)
    assert any("Optimized" in a for a in r.advice)
    r = result(s7=False)
    r.steps = [detect.Step("ping", "p", "fail"), detect.Step("port-s7", "p", "fail")]
    detect.recommend(r)
    assert any("adres IP" in a for a in r.advice)
    assert detect._family("CPU 1511-1 PN", "6ES7 511-1AK02-0AB0") == "S7-1500"
    assert detect._family("CPU 1214C", "6ES7 214-1AG40-0XB0") == "S7-1200"
    assert detect._classify("CPU : Function not available") == "denied"
    assert detect._classify("CPU : Address out of range") == "range"


def test_run_detection_closed_ports_gives_advice():
    p = free_port()
    res = detect.run_detection(f"127.0.0.1:{p}", {"opcua_port": free_port(), "web_port": free_port(),
                                                  "modbus_port": free_port()}, ping_runner=lambda h: None)
    assert res.recommended is None and res.advice and not any(m["ok"] for m in res.methods.values())
    assert all(res.step(f"port-{m}").status == "fail" for m in detect.ORDER)


# ------------------------------------------------------------------- signals / config
def test_extended_sources_roundtrip_and_keys():
    s = Signal(name="a", source="OPC", node='ns=3;s="DB".x', dtype="REAL")
    assert Signal.from_dict(s.to_dict()).node == s.node and s.address == s.node
    assert Signal(source="MBH", dtype="INT", byte=12).address == "MBH12"
    assert address_key(s) != address_key(Signal(source="OPC", node="other", dtype="REAL"))
    assert address_key(Signal(source="MBC", dtype="BOOL", byte=3, bit=5)) == address_key(Signal(source="MBC", dtype="BOOL", byte=3, bit=0))
    assert drivers.family_of([Signal(source="DB"), Signal(source="M")]) == "s7"
    assert drivers.family_of([Signal(source="DB"), Signal(source="OPC")]) is None
    assert drivers.family_of([Signal(source="OPC", enabled=False), Signal(source="MBH")]) == "modbus"
    assert Signal.from_dict({"source": "BAD"}).source == "DB"


def test_password_saved_only_when_asked():
    c = TabConfig(conn_type="opcua")
    c.conn.update(username="u", password="sekret")
    assert TabConfig.from_dict(c.to_dict()).conn["password"] == "" and c.to_dict()["conn"]["username"] == "u"
    c.conn["remember_password"] = True
    again = TabConfig.from_dict(c.to_dict())
    assert again.conn["password"] == "sekret" and again.conn_type == "opcua"
    assert TabConfig.from_dict({}).conn_type == "auto"


# ---------------------------------------------------------------------------------- UI
def test_signals_dialog_node_column_and_enable_logic(app):
    s = [Signal(name="O", source="OPC", node='ns=3;s="X"', dtype="REAL"), Signal(name="D", source="DB", dtype="INT", byte=4),
         Signal(name="M", source="MBH", dtype="UINT", byte=7)]
    d = SignalsDialog(s, False, lambda: [], opc_browse=lambda: [Signal(name="N", source="OPC", node="ns=2;i=5")])
    assert "node" in CI and d._cell(0, "node").isEnabled() and not d._cell(0, "byte").isEnabled()
    assert not d._cell(1, "node").isEnabled() and d._cell(1, "byte").isEnabled()
    assert d._cell(2, "db").isEnabled() and not d._cell(2, "node").isEnabled()
    got = d.signals()
    assert got[0].node == 'ns=3;s="X"' and got[0].source == "OPC"
    assert "ns=3" in d.row_tooltip(0)
    d._from_opc()
    assert d.signals()[-1].node == "ns=2;i=5" and d.btn_opc.isEnabled()
    d._cell(1, "source").setCurrentText("OPC")
    assert d._cell(1, "node").isEnabled() and not d._cell(1, "byte").isEnabled()
    assert not SignalsDialog(s, False, lambda: []).btn_opc.isEnabled()


def test_resolve_method_manual_and_mixed_sources(app, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    tab = TraceTab(TabConfig(conn_type="s7"), lambda: [])
    ok = [Signal(source="DB"), Signal(source="M")]
    assert tab._resolve_method(ok) == "s7"
    assert tab._resolve_method([Signal(source="DB"), Signal(source="OPC", node="x")]) is None and "różnych metod" in shown[-1]
    assert tab._resolve_method([Signal(source="OPC", node="x")]) is None and "Wybrana metoda" in shown[-1]
    tab.cfg.conn_type = "opcua"
    assert tab._resolve_method([Signal(source="OPC", node="x")]) == "opcua"
    assert tab._resolve_method([]) == "opcua"
    tab.shutdown()


def test_resolve_method_auto_uses_wizard_result(app, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    tab = TraceTab(TabConfig(conn_type="auto", slot=2), lambda: [])
    from s7trace.ui import wizard_dialog as wd

    def fake(methods_ok, rack=0, slot=1):
        def run_detection(host, opts, rack_, slot_, methods=None, stop_at_first=False, progress=None, cancel=None):
            r = detect.DetectResult(host="h", rack=rack, slot=slot)
            r.methods = {m: {"ok": True, "note": ""} for m in methods_ok}
            detect.recommend(r)
            return r
        monkeypatch.setattr(wd.detect, "run_detection", run_detection)

    fake(["s7"])
    assert tab._resolve_method([Signal(source="DB")]) == "s7" and tab.sp_slot.value() == 1       # slot that worked
    fake(["opcua"])
    assert tab._resolve_method([Signal(source="DB")]) is None
    assert "OPC UA" in shown[-1] and "nie działa" in shown[-1]                                    # tells what to change
    assert tab._resolve_method([Signal(source="OPC", node="x")]) == "opcua"
    tab.shutdown()


def test_connection_dialog_saves_settings_and_menu(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from s7trace.ui.conn_dialog import ConnectionDialog
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    names = [a.text() for a in w.menuBar().actions()]
    assert names == ["&Plik", "&Widok", "&Diagnostyka", "&Znaczniki", "&Ustawienia", "&Pomoc"]
    st = next(a for a in w.menuBar().actions() if a.text() == "&Ustawienia").menu()
    texts = [a.text() for a in st.actions()]
    assert any("Metoda połączenia" in t for t in texts) and any("Kreator" in t for t in texts)
    assert any("Interfejs" in t for t in texts) and not any("Informacje o sterowniku" in t for t in texts)   # (these are in Diagnostyka)
    wv = next(a for a in w.menuBar().actions() if a.text() == "&Widok").menu()
    assert not any("Interfejs" in a.text() for a in wv.actions())
    tab = w.tabs.currentWidget()
    dlg = ConnectionDialog(tab)
    dlg.cb_type.setCurrentIndex(dlg.cb_type.findData("opcua"))
    dlg.sp_opc.setValue(4841)
    dlg.chk_anon.setChecked(False)
    dlg.ed_user.setText("operator")
    dlg.ed_pass.setText("haslo")
    dlg.chk_remember.setChecked(True)
    assert dlg.g_opc.isVisibleTo(dlg) and not dlg.g_mb.isVisibleTo(dlg) and dlg.g_login.isVisibleTo(dlg)
    dlg._ok()
    c = tab.cfg
    assert c.conn_type == "opcua" and c.conn["opcua_port"] == 4841 and c.conn["username"] == "operator"
    assert c.conn["password"] == "haslo" and tab.lbl_method.text() == "OPC UA"
    w.close()
    w2 = MainWindow(config_file=str(tmp_path / "c.json"))
    assert w2.tabs.widget(0).cfg.conn_type == "opcua" and w2.tabs.widget(0).cfg.conn["opcua_port"] == 4841
    w2.close()


def test_wizard_dialog_report_and_use(app, monkeypatch):
    from s7trace.ui import wizard_dialog as wd
    tab = TraceTab(TabConfig(), lambda: [])

    def run_detection(host, opts, rack, slot, methods=None, stop_at_first=False, progress=None, cancel=None):
        r = detect.DetectResult(host="10.0.0.5")
        for st in (detect.Step("ping", "Ping ICMP", "ok", "1 ms"), detect.Step("s7", "S7comm", "warn", "PUT/GET?"),
                   detect.Step("opcua", "OPC UA", "ok", "działa")):
            r.steps.append(st)
            progress(st)
        r.methods = {"s7": {"ok": False, "note": ""}, "opcua": {"ok": True, "note": ""}}
        r.info = {"model": "CPU 1511-1 PN", "order_code": "6ES7 511-1AK02-0AB0", "firmware": "V2.9.2",
                  "serial": "S C-ABC", "state": "S7CpuStatusRun", "opcua_policies": ["None"], "s7_access": "denied"}
        r.plc_time = __import__("datetime").datetime(2026, 10, 1, 12, 0, 0)
        r.time_diff_local, r.time_diff_utc = 3.2, -7196.8
        detect.recommend(r)
        return r

    monkeypatch.setattr(wd.detect, "run_detection", run_detection)
    dlg = wd.WizardDialog(tab)
    dlg.worker.wait(5000)
    QApplication.processEvents()
    assert dlg.t_steps.rowCount() == 3 and dlg.method == "opcua" and dlg.btn_use.isEnabled()
    assert "OPC UA" in dlg.lbl.text()
    info = {dlg.t_info.item(r, 0).text(): dlg.t_info.item(r, 1).text() for r in range(dlg.t_info.rowCount())}
    assert info["Numer katalogowy (MLFB)"] == "6ES7 511-1AK02-0AB0" and info["Wersja firmware"] == "V2.9.2"
    assert "PUT/GET" in info["S7comm: odczyt pamięci bezwzględnej"]
    assert "+3.2 s" in dlg.lbl_time.text() and "-7196.8" in dlg.lbl_time.text()
    assert "OGRANICZENIA SYSTEMOWE" in dlg.txt_limits.toPlainText() and "PUT/GET" in dlg.txt_limits.toPlainText()
    dlg._use()
    assert tab.cfg.conn_type == "opcua"
    tab.shutdown()


def test_help_has_connection_sections(app):
    from s7trace.ui.help_dialog import HelpDialog, sections
    titles = [t for t, _ in sections()]
    assert any("Metody połączenia" in t for t in titles) and any("Ograniczenia" in t for t in titles)
    d = HelpDialog(topic="Ograniczenia")
    assert "Ograniczenia" in d.toc.currentItem().text() and "PUT/GET" in d.view.toPlainText()
