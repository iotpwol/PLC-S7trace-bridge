import json
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from s7trace.core.config import TabConfig
from s7trace.core.naming import suggest_config_name
from s7trace.core.types import Signal
from s7trace.ui import theme as th
from s7trace.ui.help_dialog import HELP_DIR, HelpDialog, sections
from s7trace.ui.main_window import MainWindow
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    th.apply_theme(a, th.DARK)
    yield a
    th.apply_theme(a, th.DARK)


def rows(*names):
    return [Signal(name=n, dtype="BOOL", db=1, byte=160, bit=i, offset_y=round(-1.1 * i, 3))
            for i, n in enumerate(names)]


def _win(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return MainWindow(config_file=str(tmp_path / "c.json"))


def test_suggest_config_name(tmp_path):
    d = str(tmp_path)
    assert suggest_config_name(d, "") == "s7trace_signals"
    (tmp_path / "s7trace_signals.json").write_text("{}")
    assert suggest_config_name(d, "") == "s7trace_signals_001"
    (tmp_path / "s7trace_signals_001.json").write_text("{}")
    assert suggest_config_name(d, "") == "s7trace_signals_002"
    (tmp_path / "L1_Oven_output_Signals.json").write_text("{}")
    assert suggest_config_name(d, "L1_Oven_output_Signals") == "L1_Oven_output_Signals_001"
    (tmp_path / "L1_Oven_output_Signals_001.json").write_text("{}")
    assert suggest_config_name(d, "L1_Oven_output_Signals_001") == "L1_Oven_output_Signals_002"
    assert suggest_config_name(d, "Nowa") == "Nowa"                       # a free name stays as it is


def test_load_config_only_checks_current_tab(app, tmp_path, monkeypatch):
    w = _win(tmp_path, monkeypatch)
    t0 = w.tabs.widget(0)
    t1 = w.new_tab()
    cfg = TabConfig(ip="10.9.8.7")
    cfg.signals = rows("X1", "X2")
    p = tmp_path / "L1_Oven.json"
    p.write_text(json.dumps({"tabs": [cfg.to_dict()]}))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(p), "")))
    t0.state = "running"                                   # a connection on ANOTHER tab does not matter
    w.tabs.setCurrentIndex(1)
    w.load_config_from()
    assert t1.ed_ip.text() == "10.9.8.7" and [s.name for s in t1.cfg.signals] == ["X1", "X2"]
    assert t1.cfg.conf_name == "L1_Oven" and t0.state == "running"
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    t1.state = "running"                                   # the CURRENT tab running blocks loading
    w.load_config_from()
    assert shown and "bieżącej karcie" in shown[0]
    t0.state = t1.state = "stopped"
    w.close()


def test_save_config_suggests_numbered_name(app, tmp_path, monkeypatch):
    w = _win(tmp_path, monkeypatch)
    got = []

    def fake(parent, title, start, flt):
        got.append(os.path.basename(start))
        return start, ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake))
    w.save_config_as()                                     # first save: the default name
    w.save_config_as()                                     # the file exists now -> _001 is suggested
    assert got == ["s7trace_signals.json", "s7trace_signals_001.json"]
    assert w.tabs.currentWidget().cfg.conf_name == "s7trace_signals_001"
    saved = json.loads((tmp_path / "S7Trace" / "konfiguracje" / "s7trace_signals.json").read_text())
    assert len(saved["tabs"]) == 1                          # only the current tab is saved
    w.close()


def test_confname_placeholder_and_prompt(app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tab = TraceTab(TabConfig(), lambda: [])
    asked = []
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (asked.append(1) or "Piec_1", True)))
    p = tab._file_name("snap_{confname}_{tab}.csv", "snapshot")
    assert os.path.basename(p).startswith("snap_Piec_1_") and tab.cfg.conf_name == "Piec_1" and len(asked) == 1
    tab.cfg.conf_name = ""
    tab._noname_asked = False
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))     # the user cancels
    assert os.path.basename(tab._file_name("x_{confname}.csv", "snapshot")) == "x_no_name.csv"
    assert "{nope}" in tab._file_name("x_{nope}.csv", "snapshot")        # unknown placeholders do not crash
    tab.shutdown()


def test_control_buttons_state_colours_and_rec_blink(app):
    tab = TraceTab(TabConfig(), lambda: [])
    prop = lambda b: bool(b.property("on"))
    assert prop(tab.btn_stop) and not prop(tab.btn_start)            # stopped: Stop is "on"
    tab.state = "running"
    tab._set_buttons()
    assert prop(tab.btn_start) and not prop(tab.btn_stop)
    for b in (tab.btn_pause, tab.btn_rec):
        b.setChecked(True)
        assert prop(b)
        b.setChecked(False)
        assert not prop(b)
    tab.apply_ctl_theme({"rec_dot": "#ff0000", "rec_blink_hz": 2.0})
    assert tab.blink.interval() == 250
    tab.btn_rec.setChecked(True)
    tab._blink_tick(reset=True)
    a = tab.btn_rec.icon().cacheKey()
    tab._blink_tick()
    assert tab.btn_rec.icon().cacheKey() != a                        # the dot blinks
    tab.btn_rec.setChecked(False)
    tab._blink_tick(reset=True)
    assert tab.btn_rec.icon().cacheKey() == tab._icon_idle.cacheKey()           # REC off: dot in the text colour
    qss = th.build_qss(th.DARK)
    assert 'QPushButton[role="rec"][on="true"]' in qss and th.DARK["rec_on_bg"] in qss
    tab.state = "stopped"
    tab.shutdown()


def test_theme_new_defaults_and_blink_hz(app):
    assert th.DARK["tab_selected"] == "#1e66c8" and th.DARK["tab_selected_text"] == "#ffe600"
    assert "QTabBar::tab:selected" in th.build_qss(th.DARK)
    assert th.normalize({"rec_blink_hz": 99})["rec_blink_hz"] == 5.0
    assert th.normalize({"rec_blink_hz": "x"})["rec_blink_hz"] == 0.5


def test_tabs_wide_enough_for_full_names(app, tmp_path, monkeypatch):
    w = _win(tmp_path, monkeypatch)
    w.resize(1500, 800)
    w.show()
    QApplication.processEvents()
    w.tabs.widget(0).rename("Linia pieca numer jeden")
    w.new_tab().rename("Chłodnia - sterownik 12")
    QApplication.processEvents()
    bar = w.tabs.bar
    need = sum(bar.tabSizeHint(i).width() for i in range(bar.count()))
    assert bar.width() >= need                                       # full names fit
    assert w._corner.width() >= bar.width()
    last = w.menuBar().actions()[-1]
    assert w._corner.geometry().left() > w.menuBar().actionGeometry(last).right()
    for i in range(12):
        w.new_tab().rename(f"Bardzo długa nazwa karty {i}")
    QApplication.processEvents()
    assert w._corner.geometry().left() > w.menuBar().actionGeometry(last).right()   # never covers the menus
    w.close()


def test_tab_dot_icon_and_tooltip(app, tmp_path, monkeypatch):
    w = _win(tmp_path, monkeypatch)
    w._tab_state(w.tabs.widget(0), "running")
    assert not w.tabs.bar.tabIcon(0).isNull() and "praca" in w.tabs.bar.tabToolTip(0)
    assert "●" not in w.tabs.bar.tabText(0)
    w.close()


def test_splitters_remembered_and_synced(app, tmp_path, monkeypatch):
    w = _win(tmp_path, monkeypatch)
    w.resize(1500, 900)
    w.show()
    t0 = w.tabs.widget(0)
    t1 = w.new_tab()
    w.tabs.setCurrentIndex(0)
    QApplication.processEvents()
    t0.split_h.setSizes([400, 1000])
    t0.split_h.splitterMoved.emit(400, 1)                            # the user dragged the bar
    t0.plot.split.setSizes([600, 160])
    t0.plot.split.splitterMoved.emit(600, 1)
    assert w.ui["left_width"] == t0.split_h.sizes()[0] and w.ui["overview_h"] == t0.plot.overview_height()
    w.tabs.setCurrentIndex(1)
    QApplication.processEvents()
    assert abs(t1.split_h.sizes()[0] - w.ui["left_width"]) <= 3      # the other tab follows
    assert abs(t1.plot.overview_height() - w.ui["overview_h"]) <= 3
    left = w.ui["left_width"]
    w.close()
    w2 = MainWindow(config_file=str(tmp_path / "c.json"))             # restored after a restart
    w2.resize(1500, 900)
    w2.show()
    QApplication.processEvents()
    assert w2.ui["left_width"] == left
    assert abs(w2.tabs.currentWidget().split_h.sizes()[0] - left) <= 3
    w2.close()


def test_legend_position_menu_and_drag(app, tmp_path, monkeypatch):
    """The legend position is kept per tab (and saved in that tab's configuration)."""
    w = _win(tmp_path, monkeypatch)
    w.show()
    QApplication.processEvents()
    t = w.tabs.widget(0)
    t2 = w.new_tab()
    w.tabs.setCurrentIndex(0)
    w.set_legend_pos(1, 1)                                           # menu: the CURRENT tab only
    assert t.plot.legend_pos == (1.0, 1.0) and t.cfg.legend_pos == [1.0, 1.0]
    assert t2.plot.legend_pos == (0.0, 0.0) and t2.cfg.legend_pos == [0.0, 0.0]
    t2.plot._legend_dropped(0.4, 0.25)                               # dropped after dragging on the second tab
    assert t2.cfg.legend_pos == [0.4, 0.25] and t2.plot.legend_pos == (0.4, 0.25)
    assert t.plot.legend_pos == (1.0, 1.0)
    w.close()
    w2 = MainWindow(config_file=str(tmp_path / "c.json"))
    assert w2.tabs.widget(0).plot.legend_pos == (1.0, 1.0)
    assert w2.tabs.widget(1).plot.legend_pos == (0.4, 0.25)
    w2.close()


def test_help_dialog_content_and_images(app):
    secs = sections()
    assert len(secs) >= 15
    imgs = set(re.findall(r'src="(img/[^"]+)"', "".join(h for _, h in secs)))
    assert len(imgs) >= 12 and all(os.path.exists(os.path.join(HELP_DIR, i)) for i in imgs)
    d = HelpDialog()
    assert d.toc.count() == len(secs)
    d.search.setText("Skoryguj wszystkie")
    d._find()
    assert "Sygnały" in d.toc.currentItem().text()
    d.toc.setCurrentRow(0)
    assert "Szybki start" in d.view.toPlainText()
