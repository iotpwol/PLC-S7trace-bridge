import math
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from s7trace.core import diagnostics as dg
from s7trace.core import planner
from s7trace.core.acq_process import ProcAcquirer
from s7trace.core.buffer import TraceBuffer
from s7trace.core.config import TabConfig
from s7trace.core.types import Signal
from s7trace.ui import theme as th
from s7trace.ui.diag_dialog import DiagDialog
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    th.apply_theme(a, th.DARK)
    return a


def feed(diag, lags, period=0.025, start=0.0):
    for i, lag in enumerate(lags):
        diag.add_sample(start + i * period, lag)


def test_plan_cost():
    sigs = [Signal(dtype="BOOL", db=1, byte=0, bit=0), Signal(dtype="BOOL", db=1, byte=0, bit=1),
            Signal(dtype="INT", db=1, byte=100)]
    b, r = dg.plan_cost(sigs, planner.MODE_SINGLE)
    assert r == 3
    b2, r2 = dg.plan_cost(sigs, planner.MODE_MULTI)
    assert r2 == 1 and 0 < b2 <= b                      # multi-read merges signals of the same byte


def test_latency_statistics_and_percentiles():
    d = dg.LinkDiag(cycle_ms=25, bytes_per_cycle=20, req_per_cycle=2)
    feed(d, [10.0] * 90 + [40.0] * 10)                      # 10% of reads exceed the 25 ms cycle
    s = d.snapshot()
    lg = s["lag"]
    assert lg["last"] == 40.0 and lg["min"] == 10.0 and lg["max"] == 40.0
    assert lg["avg"] == pytest.approx(13.0) and lg["std"] == pytest.approx(9.0)
    assert lg["p50"] == 10.0 and lg["p99"] == pytest.approx(40.0)
    assert s["overruns"] == 10 and s["overrun_pct"] == pytest.approx(10.0)
    assert s["period"]["avg"] == pytest.approx(25.0) and s["period"]["jitter"] == pytest.approx(0.0, abs=1e-6)
    assert s["rate"] == pytest.approx(40.0, rel=0.02) and s["rate10"] == pytest.approx(40.0, rel=0.02)
    assert s["bytes_per_s"] == pytest.approx(20 * 40.0, rel=0.02) and s["req_per_s"] == pytest.approx(80.0, rel=0.02)
    assert s["wire_bytes_per_s"] > s["bytes_per_s"]
    assert s["safe_cycle_ms"] == math.ceil(lg["p99"] * 1.25)
    assert s["hist"][dg.HIST_EDGES.index(10)] == 90 and s["hist"][dg.HIST_EDGES.index(20)] == 10


def test_windowed_averages_and_gaps():
    d = dg.LinkDiag(cycle_ms=100)
    feed(d, [5.0] * 100, period=1.0)                           # 100 s of 5 ms
    feed(d, [50.0] * 10, period=1.0, start=100.0)              # then 10 s of 50 ms
    s = d.snapshot()["lag"]
    assert s["avg10"] == pytest.approx(50.0, abs=5.5) and s["avg60"] < s["avg10"] and s["avg"] < s["avg60"]
    d.add_sample(111.0, None)                                   # connection-loss marker is not a latency sample
    d.add_sample(112.0, 7.0)
    snap = d.snapshot()
    assert snap["gap_rows"] == 1 and snap["n"] == 111
    assert len(d.dts) == 109                                    # no interval across the gap


def test_reconnect_downtime_and_availability():
    d = dg.LinkDiag()
    d.note_state("running")
    time.sleep(0.05)
    d.note_state("reconnecting")
    time.sleep(0.1)
    d.note_state("running")
    time.sleep(0.05)
    d.note_state("stopped")
    s = d.snapshot()
    assert 0.08 < s["down_s"] < 0.3 and 0 < s["availability"] < 100 and s["uptime_s"] >= s["down_s"]


def test_parse_ping_languages():
    assert dg.parse_ping("Reply from 10.0.0.1: bytes=32 time=12ms TTL=64") == 12.0
    assert dg.parse_ping("Odpowiedz z 10.0.0.1: bajtow=32 czas=3ms TTL=64") == 3.0
    assert dg.parse_ping("Odpowiedz z 10.0.0.1: bajtow=32 czas<1ms TTL=64") == 0.5
    assert dg.parse_ping("Reply from 10.0.0.9: Destination host unreachable.") is None
    assert dg.parse_ping("Request timed out.") is None
    assert dg.parse_ping("Upłynął limit czasu żądania.") is None


def test_ping_probe_statistics_and_loss():
    seq = iter([10.0, 12.0, None, 11.0, None, None, 13.0])
    p = dg.PingProbe("1.2.3.4", interval=0.01, runner=lambda h: next(seq, None))
    p.start()
    deadline = time.time() + 3
    while p.snapshot()["sent"] < 7 and time.time() < deadline:
        time.sleep(0.02)
    p.stop()
    p.join(1)
    s = p.snapshot()
    assert s["sent"] >= 7
    first = dg.PingProbe("x", runner=None)
    for r in [10.0, 12.0, None, 11.0, None, None, 13.0]:
        first.record(r)
    s = first.snapshot()
    assert (s["sent"], s["recv"], s["lost"]) == (7, 4, 3) and s["loss_pct"] == pytest.approx(300 / 7)
    assert s["min"] == 10.0 and s["max"] == 13.0 and s["avg"] == pytest.approx(11.5) and s["last"] == 13.0
    assert s["consec_lost"] == 0 and s["jitter"] == pytest.approx((2 + 1 + 2) / 3)
    first.record(None)
    assert first.snapshot()["consec_lost"] == 1


def test_ping_probe_reports_missing_ping_command():
    def boom(host):
        raise RuntimeError("polecenie ping niedostępne")

    p = dg.PingProbe("1.2.3.4", interval=0.01, runner=boom)
    p.start()
    time.sleep(0.15)
    p.stop()
    assert "ping" in p.snapshot()["error"] and p.snapshot()["loss_pct"] == 100.0


def test_tcp_probe_open_and_closed():
    import socket
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    ok, ms, err = dg.tcp_probe("127.0.0.1", srv.getsockname()[1])
    assert ok and ms >= 0 and not err
    port = srv.getsockname()[1]
    srv.close()
    ok, ms, err = dg.tcp_probe("127.0.0.1", port, timeout=0.5)
    assert not ok and err


def test_verdict_and_report():
    d = dg.LinkDiag(cycle_ms=25)
    assert dg.verdict(d.snapshot())[0] == "Brak danych"
    feed(d, [10.0] * 200)
    rating, notes = dg.verdict(d.snapshot(), {"sent": 100, "recv": 100, "lost": 0, "loss_pct": 0.0, "avg": 3.0})
    assert rating == "Bardzo dobre" and "Brak zastrzeżeń" in notes[0]
    d2 = dg.LinkDiag(cycle_ms=10)
    feed(d2, [30.0] * 100)
    s2 = d2.snapshot()
    s2["missed"], s2["errors"], s2["reconnects"], s2["last_error"] = 40, 2, 2, "timeout"
    s2["missed_pct"] = 28.0
    rating, notes = dg.verdict(s2, {"sent": 50, "recv": 45, "lost": 5, "loss_pct": 10.0, "avg": 80.0})
    assert rating == "Słabe" and any("Pominięte cykle" in n for n in notes) and any("utracono 5 z 50" in n for n in notes)
    txt = dg.format_report(s2, {"sent": 50, "recv": 45, "lost": 5, "loss_pct": 10.0, "last": 4.0, "avg": 80.0, "min": 3.0,
                                "max": 200.0, "jitter": 9.0}, "10.0.0.1", "Linia 1")
    assert "Ocena łącza: Słabe" in txt and "Ping ICMP" in txt and "10.0.0.1" in txt


# ----------------------------------------------------- end-to-end with the simulator
@pytest.fixture(scope="module")
def sim():
    from s7trace.sim import Simulator
    s = Simulator(11106)
    s.start()
    time.sleep(0.5)
    yield s
    s.stop()


def test_process_acquirer_collects_diagnostics(sim):
    sigs = [Signal(name="b0", dtype="BOOL", db=1, byte=100, bit=0), Signal(name="i", dtype="INT", db=1, byte=110)]
    buf = TraceBuffer(2)
    a = ProcAcquirer("127.0.0.1:11106", 0, 2, 25, sigs, planner.MODE_BLOCKS, buf)
    a.start()
    time.sleep(2.5)
    a.stop()
    a.join(8)
    s = a.diag.snapshot()
    assert s["n"] > 20 and s["lag"]["avg"] > 0 and s["lag"]["p99"] >= s["lag"]["p50"]
    assert s["samples"] == a.stats.samples and s["connect_ms"] > 0 and s["errors"] == 0 and s["reconnects"] == 0
    assert s["bytes_per_cycle"] > 0 and s["req_per_cycle"] >= 1 and s["rate"] > 10
    assert s["state"] == "stopped" and s["availability"] > 99
    assert dg.verdict(s)[0] in ("Bardzo dobre", "Dobre", "Przeciętne")


# ------------------------------------------------------------------ dialog
def test_dialog_without_connection_and_with_data(app, tmp_path, monkeypatch):
    tab = TraceTab(TabConfig(ip="10.1.2.3"), lambda: [])
    tab.ui_state["diag_ping"] = False
    dlg = DiagDialog(tab)
    assert dlg.lbl_rating.text() == "Brak danych"
    assert "Brak danych diagnostycznych" in dlg.report()

    class FakeAcq:
        t0 = time.perf_counter() - 30
        diag = dg.LinkDiag(cycle_ms=25, bytes_per_cycle=10, req_per_cycle=1)

    feed(FakeAcq.diag, [12.0, 14.0, 13.0] * 40, period=0.05)
    FakeAcq.diag.note_state("running")
    tab.acq = FakeAcq()
    tab.ping_probe = dg.PingProbe("10.1.2.3", runner=lambda h: 3.0)
    for r in (3.0, 4.0, None, 3.0):
        tab.ping_probe.record(r)
    dlg.refresh()
    assert dlg.lbl_rating.text() in ("Dobre", "Przeciętne", "Słabe") or dlg.lbl_rating.text() == "Bardzo dobre"
    assert dlg.t_lat.item(0, 0).text() == "13.0" and dlg.t_lat.item(2, 0).text() == "3.0"      # last lag / last ping
    assert dlg.t_rel.item(dlg.rel_names.index("Ping: utracone"), 0).text() == "1"
    assert dlg.t_rel.item(dlg.rel_names.index("Ping: utrata pakietów [%]"), 0).text() == "25.00"
    assert dlg.t_thr.item(0, 0).text() == "25"
    assert "Ocena łącza" in dlg.report()
    dlg.btn_reset.click()
    assert FakeAcq.diag.snapshot()["n"] == 0 and tab.ping_probe.snapshot()["sent"] == 0
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    monkeypatch.setattr(dg, "tcp_probe", lambda h, p, timeout=2.0: (False, 12.0, "refused"))
    monkeypatch.setattr("s7trace.ui.diag_dialog.dg.tcp_probe", dg.tcp_probe)
    dlg.btn_port.click()
    assert shown and "10.1.2.3:102" in shown[0]
    tab.acq = None
    dlg.close()
    assert tab.diag_dlg is None
    tab.shutdown()


def test_tab_ping_follows_checkbox_and_status(app, monkeypatch):
    started = []

    class FakeProbe:
        def __init__(self, host, *a, **k):
            self.host = host
            started.append(host)

        def start(self): pass
        def stop(self): self.dead = True
        def is_alive(self): return not getattr(self, "dead", False)
        def snapshot(self):
            return {"sent": 10, "recv": 9, "lost": 1, "loss_pct": 10.0, "last": 4.0, "avg": 4.0, "min": 3.0, "max": 5.0,
                    "jitter": 1.0, "consec_lost": 0, "error": ""}

    monkeypatch.setattr("s7trace.ui.trace_tab.PingProbe", FakeProbe)
    tab = TraceTab(TabConfig(ip="10.4.5.6:1102"), lambda: [])
    tab.set_ping(True)
    tab.set_ping(True)                                       # same host: no second probe
    assert started == ["10.4.5.6"]
    assert "Ping: 4 ms, utrata 10.0%" in tab._ping_text()
    tab.set_ping(False)
    assert tab._ping_text() == ""
    tab.ed_ip.setText("10.4.5")                              # invalid IP -> no probe
    tab.set_ping(True)
    assert started == ["10.4.5.6"]
    tab.shutdown()
