"""'Reset' / 'Auto-Reset' button, a new Start that continues the chart with a gap, theme keys of the button."""
import time
from datetime import datetime, timedelta

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from s7trace.core import markers as mk, rec_marks as rmk
from s7trace.core.acq_process import ProcAcquirer
from s7trace.core.buffer import TraceBuffer
from s7trace.core.config import TabConfig
from s7trace.core.types import Signal
from s7trace.ui import reset_button as rb
from s7trace.ui import theme
from s7trace.ui.theme import apply_dark
from test_round5 import _tab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def test_countdown_labels():
    assert rb.countdown_label(0.2) == "Reset" and rb.countdown_label(0.99) == "Reset"
    assert [rb.countdown_label(h) for h in (1.0, 1.5, 2.05, 3.05, 3.99)] == ["Reset (3s)", "Reset (3s)", "Reset (2s)", "Reset (1s)", "Reset (1s)"]
    assert rb.countdown_label(4.0) == "Reset (0s)"


def test_click_hold_cancel_and_latch(app):
    b = rb.ResetButton()
    b.show()
    resets, autos = [], []
    b.resetRequested.connect(lambda: resets.append(1))
    b.autoChanged.connect(autos.append)
    QTest.mouseClick(b, Qt.LeftButton)                                    # a click: Reset
    assert resets == [1] and not b.auto and b.text() == "Reset" and not b.isChecked()
    QTest.mousePress(b, Qt.LeftButton)                                    # held 2 s: the count-down shows, releasing cancels
    b._t0 -= 2.05
    b._tick()
    assert b.text() == "Reset (2s)"
    QTest.mouseRelease(b, Qt.LeftButton)
    assert resets == [1] and not b.auto and b.text() == "Reset"
    QTest.mousePress(b, Qt.LeftButton)                                    # held 4 s: latches as Auto-Reset
    b._t0 -= 1.5
    b._tick()
    assert b.text() == "Reset (3s)"
    b._t0 -= 2.6
    b._tick()
    assert b.auto and b.isChecked() and b.text() == "Auto-Reset" and autos == [True]
    QTest.mouseRelease(b, Qt.LeftButton)
    assert b.auto and resets == [1]                                       # releasing after the latch does nothing more
    QTest.mouseClick(b, Qt.LeftButton)                                    # a click switches it off, and does NOT reset
    assert not b.auto and b.text() == "Reset" and autos == [True, False] and resets == [1]
    b.click()                                                             # the keyboard: the same as a click
    assert resets == [1, 1]
    b.set_auto(True)
    b.click()
    assert not b.auto and resets == [1, 1]
    b.close()


def test_the_button_sits_left_of_rec_and_has_its_own_colours(app):
    tab = _tab()
    tab.resize(1300, 800)
    tab.show()
    QApplication.processEvents()
    xs = [tab.btn_pause.x(), tab.btn_reset.x(), tab.btn_rec.x()]
    assert xs == sorted(xs) and abs(tab.btn_reset.geometry().center().y() - tab.btn_rec.geometry().center().y()) <= 3           # Pauza, Reset, REC in a row
    assert tab.btn_reset.geometry().right() < tab.btn_rec.x() < tab.btn_reset.geometry().right() + 20          # directly left of REC
    for k in ("reset_on_bg", "reset_on_text"):
        assert k in theme.COLOR_KEYS and k in theme.DARK and k in theme.LIGHT
    qss = theme.build_qss(theme.DARK)
    assert 'QPushButton[role="reset"][on="true"]' in qss and theme.DARK["reset_on_text"] in qss
    assert theme.DARK["reset_on_bg"] == theme.DARK["ctl_bg"]                # the background does not change, the text turns blue
    tab.shutdown()


def test_auto_reset_is_saved_with_the_tab(app):
    tab = _tab()
    assert tab.to_config().auto_reset is False
    tab.btn_reset.set_auto(True, emit=True)
    c = tab.to_config()
    assert c.auto_reset is True and TabConfig.from_dict(c.to_dict()).auto_reset is True
    tab2 = _tab()
    tab2.cfg.auto_reset = True
    tab2._load_cfg()
    assert tab2.btn_reset.auto and tab2.btn_reset.text() == "Auto-Reset"
    tab.shutdown()
    tab2.shutdown()


def filled(tab, upto=20.0):
    run = [Signal.from_dict(s.to_dict()) for s in tab.display_signals()]
    tab._run_signals = run
    t = np.round(np.arange(0, upto, 0.1), 3)
    tab.buffer.reset(len(run))
    tab.buffer.load(t, np.column_stack([np.sin(t) + i for i in range(len(run))]))
    return run


def test_a_new_start_continues_the_chart_unless_auto_reset_or_other_signals(app):
    tab = _tab()
    run = filled(tab)
    assert tab._can_continue(run)
    run2 = [Signal.from_dict(s.to_dict()) for s in run]
    run2[0].color, run2[0].share = "#123456", 3.0                       # looks are not data
    assert tab._can_continue(run2)
    run2[0].byte += 2                                                    # another address: another column
    assert not tab._can_continue(run2)
    assert not tab._can_continue(run[:1])
    tab.btn_reset.set_auto(True)                                         # Auto-Reset: every Start begins a new chart
    assert not tab._can_continue(run)
    tab.btn_reset.set_auto(False)
    tab.loaded = {"meta": {}}                                            # a loaded recording is not continued
    assert not tab._can_continue(run)
    tab.loaded = None
    tab.buffer.reset(len(run))
    assert not tab._can_continue(run)                                    # nothing to continue
    tab.shutdown()


def test_reset_clears_the_chart_and_asks_about_buffer_markers(app, tmp_path, monkeypatch):
    tab = _tab()
    tab.mk._store = mk.MarkerStore(str(tmp_path / "m.db"))
    run = filled(tab)
    tab.mk.store.add(int(tab.start_wall.timestamp() * 1e6) + 3_000_000, conn=tab.mk.key())      # exists only for this buffer
    seen = []

    def ex(self):
        seen.append(self.text())
        next(b for b in self.buttons() if b.text().startswith("Anuluj")).click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", ex)
    tab.reset_chart()                                                    # the user backs out
    assert len(tab.buffer) > 0 and seen and "Reset" in seen[-1]

    def ex2(self):
        next(b for b in self.buttons() if b.text().startswith("Usuń")).click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", ex2)
    before = tab.start_wall
    tab.reset_chart()
    assert len(tab.buffer) == 0 and tab.mk.store.count() == 0 and tab._run_signals == []
    assert tab.start_wall > before and tab.loaded is None                # stopped: a fresh chart
    tab.reset_chart()
    assert "pusty" in tab.status_msg
    # while the connection runs the time axis goes on
    run = filled(tab)
    tab.state, wall = "running", tab.start_wall
    tab.reset_chart()
    assert len(tab.buffer) == 0 and tab.start_wall == wall and tab._run_signals != []
    tab.state = "stopped"
    tab.shutdown()


def test_continuing_run_keeps_the_time_axis_and_marks_the_gap():
    """The times of the samples of a continued run are shifted by the pause; one NaN row sits in the gap."""
    buf = TraceBuffer(2)
    t = np.round(np.arange(0, 20.0, 0.1), 3)
    buf.load(t, np.column_stack([t, t]))
    start_wall = datetime.now() - timedelta(seconds=30)               # the first run began 30 s ago, it ended at 20 s: a 10 s pause
    acq = ProcAcquirer("127.0.0.1", 0, 1, 100, [Signal(name="A"), Signal(name="B")], "all", buf, anchor_ts=start_wall.timestamp())
    got = []
    acq.on_sample = lambda tt, v: got.append(tt)
    acq._reader.start()
    child = acq._child_conn
    child.send(("state", "running", "ok", time.perf_counter()))
    child.send(("batch", [(0.1, [1.0, 2.0]), (0.2, [1.0, 2.5])], {}))
    child.send(("state", "stopped", "", 0.0))
    acq._reader.join(5)
    tt, vv = buf.snapshot()
    assert abs(acq.time_offset - 30.0) < 0.5
    k = len(t)
    assert len(tt) == k + 4 and np.isnan(vv[k]).all() and np.isnan(vv[k + 1]).all()           # the break between the runs: NaN right after the old data ...
    assert abs(tt[k] - (tt[k - 1] + 0.001)) < 1e-9 and abs(tt[k + 1] - 30.0) < 0.5             # ... (the old value is not held across the pause) and where the new run begins
    assert abs(tt[k + 2] - 30.1) < 0.5 and abs(got[0] - tt[k + 2]) < 1e-9
    assert tt[k - 1] < tt[k] < tt[k + 1] < tt[k + 2]
    assert acq.gap is not None and abs(acq.gap[0] - tt[k - 1]) < 1e-9 and abs(acq.gap[1] - tt[k + 1]) < 1e-9     # the owner draws Stop / Start from it
    # a new chart (no anchor): times as before
    buf2 = TraceBuffer(2)
    acq2 = ProcAcquirer("127.0.0.1", 0, 1, 100, [Signal(name="A"), Signal(name="B")], "all", buf2)
    acq2._reader.start()
    acq2._child_conn.send(("state", "running", "ok", time.perf_counter()))
    acq2._child_conn.send(("batch", [(0.1, [1.0, 2.0])], {}))
    acq2._child_conn.send(("state", "stopped", "", 0.0))
    acq2._reader.join(5)
    assert acq2.time_offset == 0.0 and list(buf2.snapshot()[0]) == [0.1]


# ----------------------------------------------------------------------------------- the whole thing against the simulator
@pytest.fixture(scope="module")
def sim():
    from s7trace.sim import Simulator
    s = Simulator(11107)
    s.start()
    time.sleep(0.5)
    yield s
    s.stop()


def _pump(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_stop_and_start_continues_the_chart_with_a_gap_and_auto_reset_starts_over(app, sim):
    from s7trace.ui.trace_tab import TraceTab
    sim.db1[100] = 1
    c = TabConfig(ip="127.0.0.1:11107", rack=0, slot=2, cycle_ms=25, conf_name="L", name="L", conn_type="s7")
    c.signals = [Signal(name="b0", dtype="BOOL", db=1, byte=100, bit=0)]
    tab = TraceTab(c, lambda: [])
    tab.show()
    try:
        tab.start()
        assert _pump(lambda: tab.state == "running" and len(tab.buffer) > 20)
        wall = tab.start_wall
        tab.stop()
        assert _pump(lambda: tab.state == "stopped")
        n1, last1 = len(tab.buffer), tab.buffer.last_time()
        t_stop = datetime.now()
        time.sleep(1.2)                                                      # the pause
        tab.start()                                                          # Auto-Reset is off: the chart goes on
        assert _pump(lambda: tab.state == "running" and len(tab.buffer) > n1 + 20)
        assert tab.start_wall == wall                                        # the same time axis
        t, v = tab.buffer.snapshot()
        gap = np.where(np.isnan(v[:, 0]))[0]
        bad = np.where(np.diff(t) < 0)[0]
        assert len(gap) >= 1 and not len(bad), (gap, bad, [(i, t[i-1:i+3].tolist(), v[i-1:i+3, 0].tolist()) for i in bad[:3]], n1, last1)
        first_new = t[n1:][~np.isnan(v[n1:, 0])][0]
        assert first_new - last1 >= 1.2                                      # the break is as long as the pause (+ the connect time)
        assert first_new - last1 < 6.0
        assert len(tab.mk.rec.m.gaps) == 1                                   # 'Stop odczytu (1)' / 'Start odczytu (1)' marks
        g = tab.mk.rec.m.gaps[0]
        assert abs(g["t0"] - last1) < 1e-6 and g["t1"] - g["t0"] >= 1.2
        titles = sorted(c["data"]["title"] for mid, c in tab.plot.mitems.items() if rmk.is_rec(mid) and not c["data"].get("passive"))
        assert titles == ["Start odczytu (1)", "Stop odczytu (1)"]
        tab.stop()
        assert _pump(lambda: tab.state == "stopped")
        tab.btn_reset.set_auto(True, emit=True)                              # Auto-Reset: the next Start begins a new chart
        tab.start()
        assert _pump(lambda: tab.state == "running" and len(tab.buffer) > 5)
        assert tab.start_wall > wall and tab.buffer.first_time() < 1.0 and not np.isnan(tab.buffer.snapshot()[1]).any()
        # Reset while running clears the buffer, the connection goes on and the time axis too
        tab.btn_reset.set_auto(False, emit=True)
        before = tab.buffer.last_time()
        answers = []
        tab._ask_reset = lambda: answers.pop(0)
        answers.append(None)                                                 # the user backs out: nothing is cleared
        tab.reset_chart()
        assert len(tab.buffer) > 5 and tab.buffer.last_time() >= before
        answers.append("keep")                                               # clear, the time axis goes on
        tab.reset_chart()
        assert _pump(lambda: len(tab.buffer) > 3)
        assert tab.buffer.first_time() >= before - 0.2
        wall2 = tab.start_wall
        answers.append("axis")                                               # clear and start the time axis from 0
        tab.reset_chart()
        assert tab.start_wall > wall2
        assert _pump(lambda: len(tab.buffer) > 3)
        assert tab.buffer.first_time() < 1.0 and tab.buffer.last_time() < 5.0
        tab.stop()
        assert _pump(lambda: tab.state == "stopped")
    finally:
        tab.shutdown()


def test_reset_while_running_asks_and_rec_keeps_the_axis(app, monkeypatch):
    """The dialog of 'Reset' during a reading: clear + restart the axis / clear only / cancel; with REC running there is no 'restart' button."""
    from s7trace.ui.trace_tab import TraceTab
    tab = _tab()
    seen = []

    class Box:
        def __init__(self, *a, **k):
            self.btns, self.text = [], a[2] if len(a) > 2 else ""
            seen.append(self)

        def addButton(self, text, role):
            self.btns.append(text)
            return text

        def setDefaultButton(self, b):
            pass

        def exec(self):
            pass

        def clickedButton(self):
            return self.pick(self.btns)
    monkeypatch.setattr("s7trace.ui.trace_tab.QMessageBox", Box)
    Box.Question = Box.AcceptRole = Box.RejectRole = 0
    Box.pick = staticmethod(lambda b: b[0])
    assert tab._ask_reset() == "axis" and seen[-1].btns == ["Wyczyść i zeruj oś czasu", "Wyczyść (oś czasu biegnie dalej)", "Anuluj"]
    Box.pick = staticmethod(lambda b: b[1])
    assert tab._ask_reset() == "keep"
    Box.pick = staticmethod(lambda b: b[2])
    assert tab._ask_reset() is None
    tab.recorder = object()                                                  # REC runs: the axis must go on
    Box.pick = staticmethod(lambda b: b[0])
    assert tab._ask_reset() == "keep" and "Wyczyść i zeruj oś czasu" not in seen[-1].btns and "REC trwa" in seen[-1].text
    tab.recorder = None
