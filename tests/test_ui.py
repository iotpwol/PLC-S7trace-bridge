import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from s7trace.core.config import TabConfig
from s7trace.core.csvio import write_csv
from s7trace.core.symbols import Symbol
from s7trace.core.trigger import TriggerConfig
from s7trace.core.types import Signal
from s7trace.ui.main_window import MainWindow
from s7trace.ui.signals_dialog import SignalsDialog
from s7trace.ui.theme import apply_dark
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def make_cfg():
    c = TabConfig(ip="10.1.2.3", rack=0, slot=1, cycle_ms=40, window_s=60, auto_y=False, y_layout="offset",
                  y_min=-3, y_max=4)
    c.signals = [Signal(name="A", dtype="BOOL", db=2, byte=5, bit=3, color="#123456", offset_y=-1.1),
                 Signal(name="B", dtype="REAL", db=2, byte=8, gain=0.5)]
    c.trigger = TriggerConfig(enabled=True, signal="B", mode="between", a=1, b=5, hysteresis=0.2,
                              pretrigger=2, action="Zapis CSV", folder="x", filename="f_{tab}.csv")
    return c


def test_tab_config_roundtrip(app):
    tab = TraceTab(make_cfg(), lambda: [])
    out = tab.to_config().to_dict()
    again = TabConfig.from_dict(out)
    assert again.to_dict() == make_cfg().to_dict()
    assert tab.sp_tb.isEnabled()               # B enabled for 'between'
    assert not tab.sp_ymin.isEnabled() is False  # auto Y off -> manual fields enabled
    tab.shutdown()


def test_signals_dialog_roundtrip_and_lock(app):
    from s7trace.ui.signals_dialog import CI
    sigs = make_cfg().signals
    d = SignalsDialog(sigs, False, lambda: [Symbol("Sym", "M", "INT", 0, 10)])
    got = d.signals()
    assert [s.to_dict() for s in got] == [s.to_dict() for s in sigs]
    d._add()
    assert len(d.signals()) == 3 and d.signals()[2].name == "C"      # B -> C
    d._remove()
    assert len(d.signals()) == 2
    locked = SignalsDialog(sigs, True, lambda: [])
    assert locked.btn_add.isEnabled()                                # adding is allowed while running
    assert not locked.table.cellWidget(0, CI["byte"]).isEnabled()    # byte locked
    assert locked.table.cellWidget(0, CI["offset"]).isEnabled()      # offset editable
    assert locked.table.cellWidget(0, CI["plot"]).isEnabled()        # chart checkbox editable


def test_import_csv_into_tab(app, tmp_path, monkeypatch):
    sigs = make_cfg().signals
    t = np.arange(0, 10, 0.1)
    v = np.column_stack([(t % 2 > 1).astype(float), np.sin(t)])
    p = str(tmp_path / "in.csv")
    write_csv(p, sigs, t, v)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (p, "")))
    tab = TraceTab(TabConfig(), lambda: [])
    tab.import_csv()
    assert len(tab.buffer) == len(t)
    assert [s.name for s in tab.cfg.signals] == ["A", "B"]
    assert tab.cb_tsig.count() == 2
    x0, x1 = tab.plot.view_range()
    assert x0 == pytest.approx(0) and x1 == pytest.approx(9.9)
    tab.plot.refresh(True)
    tab.shutdown()


def test_main_window_persists(app, tmp_path):
    cf = str(tmp_path / "cfg.json")
    w = MainWindow(config_file=cf)
    w.tabs.widget(0).ed_ip.setText("1.2.3.4")
    w.new_tab(make_cfg())
    assert w.tabs.count() == 2
    w.close()
    w2 = MainWindow(config_file=cf)
    assert w2.tabs.count() == 2
    assert w2.tabs.widget(0).ed_ip.text() == "1.2.3.4"
    assert w2.tabs.widget(1).cfg.trigger.mode == "between"
    w2.close()
