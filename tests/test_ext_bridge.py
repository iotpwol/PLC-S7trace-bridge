"""Bridge to the external analyzer (core/ext_bridge.py): auth, streaming of the source tab, results coming back, wiring."""
import socket
import time

import pytest

from s7trace.core import ext_bridge as eb


def wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Client:
    """What the analyzer does: connect, authenticate, read lines."""

    def __init__(self, port, token="tok", name="test-analyzer"):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.sock.settimeout(0.2)
        self.buf = b""
        self.msgs = []
        if token is not None:
            self.send({"type": "auth", "proto": 1, "token": token, "name": name})

    def send(self, msg):
        self.sock.sendall(eb.encode(msg))

    def pump(self):
        try:
            chunk = self.sock.recv(65536)
        except socket.timeout:
            return
        except OSError:
            return
        self.buf += chunk
        *lines, self.buf = self.buf.split(b"\n")
        self.msgs += [m for m in map(eb.decode, lines) if m]

    def wait_for(self, kind, n=1, timeout=3.0):
        return wait(lambda: (self.pump(), sum(1 for m in self.msgs if m["type"] == kind) >= n)[1], timeout)

    def closed(self):
        try:
            return self.sock.recv(10) == b""
        except socket.timeout:
            return False
        except OSError:
            return True


@pytest.fixture
def bridge():
    b = eb.Bridge("tok", 0, app_version="9.9")
    assert b.start()
    yield b
    b.stop()


SIGS = [{"name": "A", "address": "DB1.DBD0", "dtype": "REAL"}, {"name": "B", "address": "DB1.DBX4.0", "dtype": "BOOL"}]


def test_normalize_clamps_and_defaults():
    assert eb.normalize(None) == eb.defaults() and eb.defaults()["enabled"] is False
    assert eb.normalize({"port": 80})["port"] == eb.DEFAULT_PORT
    assert eb.normalize({"port": "x"})["port"] == eb.DEFAULT_PORT
    assert eb.normalize({"enabled": 1, "port": 7800, "token": "t", "source": "L1"}) == \
        {"enabled": True, "port": 7800, "token": "t", "source": "L1"}


def test_empty_token_refuses_to_start():
    b = eb.Bridge("", 0)
    assert b.start() is False and "token" in b.error and not b.running


def test_port_in_use_is_reported_not_raised():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    try:
        b = eb.Bridge("tok", s.getsockname()[1])
        assert b.start() is False and "port" in b.error
    finally:
        s.close()


def test_wrong_token_and_wrong_proto_are_dropped(bridge):
    c = Client(bridge.port, token="nope")
    assert wait(c.closed) and bridge.peers == []
    c2 = Client(bridge.port, token=None)
    c2.send({"type": "auth", "proto": 2, "token": "tok"})
    assert wait(c2.closed)
    c3 = Client(bridge.port, token=None)
    c3.sock.sendall(b"garbage\n")
    assert wait(c3.closed)


def test_hello_meta_state_batch_in_order_with_nan(bridge):
    feed = bridge.feed()
    c = Client(bridge.port)
    assert c.wait_for("hello") and c.msgs[0]["proto"] == 1 and c.msgs[0]["version"] == "9.9"
    assert wait(lambda: len(bridge.peers) == 1)
    feed.meta(SIGS, 0.2, 123456, "Linia 1", "10.0.0.1")
    feed.state("running")
    feed.sample(0.0, [1.5, 1.0])
    feed.sample(0.2, [float("nan"), 0.0])
    assert c.wait_for("batch")
    kinds = [m["type"] for m in c.msgs]
    assert kinds[:3] == ["hello", "meta", "state"] and "batch" in kinds
    meta = next(m for m in c.msgs if m["type"] == "meta")
    assert meta["signals"] == SIGS and meta["cycle_s"] == 0.2 and meta["start_us"] == 123456 and meta["name"] == "Linia 1"
    rows = [r for m in c.msgs if m["type"] == "batch" for r in m["v"]]
    assert rows == [[1.5, 1.0], [None, 0.0]]
    ts = [t for m in c.msgs if m["type"] == "batch" for t in m["t"]]
    assert ts == [0.0, 0.2]


def test_late_client_gets_the_current_meta_and_state(bridge):
    feed = bridge.feed()
    feed.meta(SIGS, 0.5)
    feed.state("running")
    c = Client(bridge.port)
    assert c.wait_for("state")
    assert [m["type"] for m in c.msgs[:3]] == ["hello", "meta", "state"] and c.msgs[2]["state"] == "running"


def test_gap_travels_with_the_state(bridge):
    feed = bridge.feed()
    c = Client(bridge.port)
    assert c.wait_for("hello") and wait(lambda: bridge.peers)
    feed.meta(SIGS, 0.2)
    feed.state("stopped", (10.0, 55.0))
    assert c.wait_for("state")
    assert next(m for m in c.msgs if m["type"] == "state")["gap"] == [10.0, 55.0]


def test_samples_are_dropped_without_a_peer_or_a_meta(bridge):
    feed = bridge.feed()
    feed.sample(0.0, [1, 2])                                  # no meta, no peer
    feed.meta(SIGS, 0.2)
    feed.sample(0.1, [1, 2])                                  # meta, still no peer
    assert len(bridge._outbox) == 0


def test_large_stream_is_split_into_batches(bridge):
    feed = bridge.feed()
    c = Client(bridge.port)
    assert wait(lambda: bridge.peers)
    feed.meta(SIGS, 0.2)
    for i in range(1300):
        feed.sample(i * 0.2, [float(i), 0.0])
    assert wait(lambda: (c.pump(), sum(len(m["t"]) for m in c.msgs if m["type"] == "batch") == 1300)[1])
    assert max(len(m["t"]) for m in c.msgs if m["type"] == "batch") <= eb.MAX_BATCH_ROWS


def test_results_from_the_analyzer_are_kept(bridge):
    seen = []
    bridge.on_message = lambda m: (seen.append(m["type"]), 1 / 0)[0]          # a broken callback must not break the link
    c = Client(bridge.port)
    assert wait(lambda: bridge.peers)
    c.send({"type": "status", "text": "Uczenie", "ready": False})
    c.send({"type": "event", "id": 1, "open": True, "t0": 1.0, "t1": 2.0, "level": "warn", "text": "x", "signals": [], "segment": "S"})
    c.send({"type": "event", "id": 1, "open": False, "t0": 1.0, "t1": 3.0, "level": "alarm", "text": "x", "signals": ["A"], "segment": "S"})
    c.send({"type": "score", "t": [1.0], "v": [2.0], "threshold": 1.0, "segment": "S"})
    c.send({"type": "bogus"})
    assert wait(lambda: len(bridge.inbox) == 4)
    assert bridge.last_status["text"] == "Uczenie" and bridge.events_final == 1 and seen == ["status", "event", "event", "score"]
    assert bridge.info()["clients"] == ["test-analyzer"] and bridge.info()["events"] == 1


def test_disconnect_removes_the_peer_and_new_one_can_join(bridge):
    c = Client(bridge.port)
    assert wait(lambda: len(bridge.peers) == 1)
    c.sock.close()
    assert wait(lambda: len(bridge.peers) == 0)
    c2 = Client(bridge.port)
    assert wait(lambda: len(bridge.peers) == 1) and c2.wait_for("hello")


def test_stop_closes_everything_and_null_feed_is_harmless():
    b = eb.Bridge("tok", 0)
    assert b.start()
    c = Client(b.port)
    assert wait(lambda: b.peers)
    b.stop()
    assert not b.running and b.peers == [] and wait(c.closed)
    eb.NULL.meta([], 0.1)
    eb.NULL.sample(0, [])
    eb.NULL.state("running")


# ------------------------------------------------------------------ wiring in the window
@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    from s7trace.ui.theme import apply_dark
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_only_the_source_tab_feeds_the_bridge(app, tmp_path):
    from s7trace.core.config import TabConfig
    from s7trace.core.types import Signal
    from s7trace.ui.main_window import MainWindow
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    try:
        assert w.bridge is None and w.analyzer_cfg["enabled"] is False
        cfg = TabConfig(name="Linia A", ip="10.1.2.3:1102")
        cfg.signals = [Signal(name="A", dtype="REAL", db=1, byte=0)]
        a = w.new_tab(cfg)
        b = w.new_tab(TabConfig(name="Linia B", ip="10.1.2.4:1102"))
        port = free_port()
        w.analyzer_cfg = eb.normalize({"enabled": True, "port": port, "token": "tok", "source": "Linia A"})
        w._start_bridge()
        assert w.bridge.running and a.ext is not eb.NULL and b.ext is eb.NULL
        c = Client(port)
        assert wait(lambda: w.bridge.peers)
        a._run_signals = list(cfg.signals)                       # as if Start had been pressed
        a.state = "running"
        a.send_ext_meta()
        a._pending.append((0.0, [1.25]))
        b._pending.append((0.0, [9.0]))
        a._drain()
        b._drain()
        assert c.wait_for("batch")
        meta = next(m for m in c.msgs if m["type"] == "meta")
        assert meta["signals"][0]["name"] == "A" and meta["name"] == "Linia A" and meta["cycle_s"] == cfg.cycle_ms / 1000
        assert [r for m in c.msgs if m["type"] == "batch" for r in m["v"]] == [[1.25]]
        a._on_state("stopped", "Zatrzymano")
        assert c.wait_for("state", 2) and c.msgs[-1]["state"] == "stopped"
        w.analyzer_cfg = {**w.analyzer_cfg, "source": "Linia B"}                 # the source moves to the other tab
        w._start_bridge()
        assert a.ext is eb.NULL and b.ext is not eb.NULL
        assert w._config_dict()["ui"]["analyzer"]["source"] == "Linia B"
        w.analyzer_cfg = {**w.analyzer_cfg, "enabled": False}
        w._start_bridge()
        assert w.bridge is None and a.ext is eb.NULL and b.ext is eb.NULL
    finally:
        if w.bridge is not None:
            w.bridge.stop()
        w.close()


def test_dialog_roundtrip_and_status_text(app):
    from s7trace.ui.analyzer_dialog import AnalyzerDialog
    info = {"running": True, "error": "", "port": 7700, "clients": ["s7analyzer"], "status": {"text": "Monitorowanie"}, "events": 3}
    d = AnalyzerDialog({"enabled": True, "port": 7801, "token": "abc", "source": "B"}, ["A", "B"], lambda: info)
    assert d.result_cfg() == {"enabled": True, "port": 7801, "token": "abc", "source": "B"}
    assert "s7analyzer" in d.lbl.text() and "Monitorowanie" in d.lbl.text()
    info.update(running=False, error="port zajęty")
    d._refresh()
    assert "port zajęty" in d.lbl.text()
    d2 = AnalyzerDialog({}, ["A"], lambda: info)
    assert d2.result_cfg()["token"]                                # a token is generated for the first use
    d.close()
    d2.close()
