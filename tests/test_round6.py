"""Round 6: thin hover-only resize bars (colour / always visible), narrow settings panel, draggable multi-line status bar,
header + scroll + screen fit of the settings windows, opening a recording from a database into a tab, tab tooltips."""
import time
from datetime import datetime

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from s7trace.core import store
from s7trace.core.config import TabConfig
from s7trace.core.store import DbRecorder, StoreConfig
from s7trace.core.types import Signal
from s7trace.ui import theme as th
from s7trace.ui.fold_splitter import HANDLE, FoldHandle
from s7trace.ui.interface_dialog import InterfaceDialog
from s7trace.ui.main_window import MainWindow
from s7trace.ui.pan_label import PanLabel
from s7trace.ui.store_dialog import RecInfoDialog, StoreDialog, StoreImportDialog
from s7trace.ui.theme import apply_dark
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def _tab(ip="10.1.2.3", name=""):
    c = TabConfig(ip=ip, conf_name="L1", name=name)
    c.signals = [Signal(name=n, dtype="REAL", db=1, byte=i * 4, color=col)
                 for i, (n, col) in enumerate(zip("AB", ("#ffb347", "#4eb8f0")))]
    tab = TraceTab(c, lambda: [])
    tab.resize(1500, 800)
    tab.show()
    QApplication.processEvents()
    return tab


# ------------------------------------------------------------------------------------------------ resize bars
def test_resize_bars_are_thin_and_visible_only_under_the_mouse(app):
    tab = _tab()
    for sp in (tab.split_h, tab.plot.split):
        h = sp.handle(1)
        assert isinstance(h, FoldHandle) and sp.handleWidth() == HANDLE <= 4        # was 14 (4x thinner)
        assert not h._visible_bar()                                                  # nothing is drawn at rest
        h.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
        assert h._visible_bar()
        h.leaveEvent(QEvent(QEvent.Leave))
        assert not h._visible_bar()
    tab.shutdown()


def test_bar_colour_and_permanent_visibility_come_from_the_theme(app):
    tab = _tab()
    tab.apply_ctl_theme({**th.DARK, "bar": "#ff0000", "bar_always": True})
    h = tab.split_h.handle(1)
    assert h._visible_bar() and tab.split_h.bar_color == "#ff0000" and tab.plot.split.bar_always
    img = h.grab().toImage()
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    assert c.red() > 150 and c.green() < 80 and c.blue() < 80                         # the chosen colour is what is painted
    tab.apply_ctl_theme({**th.DARK, "bar_always": False})
    assert not h._visible_bar()
    tab.shutdown()


def test_interface_dialog_has_the_bar_and_status_settings(app):
    got = {}
    d = InterfaceDialog(th.DARK, lambda t: got.update(t), None)
    assert {"bar", "status_bg", "status_text"} <= set(d._buttons)                    # colour pickers
    d.chk_bar.setChecked(True)
    d.status_lines.setValue(3)
    assert got["bar_always"] is True and got["status_lines"] == 3
    n = th.normalize({**th.DARK, "profile": "custom", "bar_always": True, "status_lines": 99, "status_bg": "#102030"})
    assert n["status_lines"] == 10 and n["bar_always"] is True and n["status_bg"] == "#102030"
    assert th.normalize({"status_lines": "x"})["status_lines"] == 1
    d.close()


# ------------------------------------------------------------------------------------------------ settings panel
def test_left_panel_is_never_narrower_than_its_content(app):
    tab = _tab()
    sc = tab._left_scroll
    need = sc.widget().minimumSizeHint().width()
    assert tab._left_min >= need and tab.split_h.sizes()[0] >= need                  # no hidden fields at the start
    tab.split_h.set_sizes_for(120)
    QApplication.processEvents()
    assert tab.split_h.sizes()[0] >= need
    tab.shutdown()


# ------------------------------------------------------------------------------------------------ status bar
def _drag(w, x0, x1, y0=5, y1=5):
    QTest.mousePress(w, Qt.LeftButton, pos=QPoint(x0, y0))
    QTest.mouseMove(w, QPoint((x0 + x1) // 2, y1))
    QTest.mouseMove(w, QPoint(x1, y1))
    QTest.mouseRelease(w, Qt.LeftButton, pos=QPoint(x1, y1))


def test_status_text_that_does_not_fit_is_dragged_between_two_stops(app):
    w = PanLabel()
    w.resize(200, 20)
    w.show()
    w.setText("<b>" + "x" * 5 + "</b>")
    assert w.overflow() == 0 and w.text_pos() > 100                                   # fits: right aligned
    w.setText("<b>" + "Długi komunikat statusu " * 12 + "</b>")
    tw = w._lbl.sizeHint().width()
    assert w.overflow() > 0 and w.text_pos() == 0                                     # starts at the left edge
    _drag(w, 150, 10)                                                                 # drag left: shows the end
    assert 0 > w.text_pos() > 200 - tw
    for _ in range(40):
        _drag(w, 190, 1)
    assert w.text_pos() == 200 - tw                                                   # right end of the text at the right edge
    for _ in range(60):
        _drag(w, 1, 190)
    assert w.text_pos() == 0                                                          # left end at the left edge, no further
    w.close()


def test_status_bar_is_as_high_as_its_text_up_to_the_chosen_number_of_lines(app):
    w = PanLabel()
    w.resize(300, 20)
    w.show()
    w.set_max_lines(3)
    w.setText("krótki")
    one = w.height()
    w.setText("raz dwa trzy cztery pięć sześć siedem osiem dziewięć " * 2)        # ~2 lines at 300 px
    two = w.height()
    assert one < two < one * 3 and w.lines_shown() == 2
    w.setText("raz dwa trzy cztery pięć sześć siedem osiem dziewięć " * 12)            # far more than 3 lines
    assert w.height() <= one * 3 + 4 and w.lines_shown() == 3 and w.overflow() > 0   # capped; the rest is dragged up / down
    y0 = w.text_pos()
    _drag(w, 5, 5, 60, 5)
    assert w.text_pos() < y0
    w.set_max_lines(1)
    assert w.height() <= one + 2 and w.text_pos() == 0
    w.close()


def test_status_bar_takes_its_colours_and_lines_from_the_theme(app):
    tab = _tab()
    tab.apply_ctl_theme({**th.DARK, "status_bg": "#102030", "status_text": "#aabbcc", "status_lines": 4})
    assert "#102030" in tab.lbl_status.styleSheet() and "#aabbcc" in tab.lbl_status.styleSheet()
    assert tab.lbl_status.max_lines() == 4
    tab.shutdown()


# ------------------------------------------------------------------------------------------------ settings windows
def test_settings_windows_have_a_header_and_fit_the_screen(app):
    d = StoreDialog(StoreConfig(), "sqlite")
    d.resize(6000, 6000)                                                              # far larger than any screen
    d.show()
    QApplication.processEvents()
    kit = d._kit
    assert "Ustawienia zapisu: SQLite" in kit["header"].lbl_title.text() and len(kit["header"].lbl_text.text()) > 30
    av = d.screen().availableGeometry()
    assert d.width() <= av.width() and d.height() <= av.height()                      # shrunk; the content scrolls
    assert kit["scroll"].widget() is kit["body"]
    d.close()
    r = RecInfoDialog("t", "n", "g", "msg", "OK", "Anuluj")
    r.show()
    assert r._kit["header"].lbl_title.text() == "Nazwa nagrania" and r._kit["footer"] is not None   # buttons stay outside
    r.close()
    i = InterfaceDialog(th.DARK, lambda t: None, None)
    i.show()
    assert i._kit["header"].lbl_title.text().startswith("Interfejs")
    i.close()


# ------------------------------------------------------------------------------------------------ opening recordings
def _make_db(tmp_path, title="Piec 1", notes="próba"):
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "rec.db"), mode="all", batch_s=0.05)
    rec = DbRecorder(cfg, [Signal(name="A"), Signal(name="B")], datetime.now(),
                     {"title": title, "notes": notes, "tags": "x", "conf": "L1", "tab": "T"}, base_dir=str(tmp_path))
    for i in range(40):
        rec.write(i * 0.05, [float(i % 5), 1.0])
    rec.close()
    return cfg


@pytest.fixture
def pick_first(monkeypatch):
    def fake_exec(self):
        self.refresh()
        self.table.selectRow(0)
        self.load()
        return QDialog.Accepted if self.result else QDialog.Rejected
    monkeypatch.setattr(StoreImportDialog, "exec", fake_exec)


def test_recording_opens_in_an_empty_tab_without_asking_and_names_the_tab(app, tmp_path, pick_first, monkeypatch):
    cfg = _make_db(tmp_path)
    tab = _tab()
    tab.buffer.reset(0)
    tab.cfg.store = StoreConfig(kind="sqlite", sqlite_path=cfg.sqlite_path)
    asked = []
    monkeypatch.setattr(TraceTab, "_ask_target", lambda self, active: asked.append(active) or "")
    tab.import_db()
    assert not asked and len(tab.buffer) > 3 and tab.title() == "Piec 1"             # the tab takes the recording's name
    assert tab.loaded["meta"]["title"] == "Piec 1"
    tab.shutdown()


def test_recording_asks_where_to_open_when_the_tab_has_data(app, tmp_path, pick_first, monkeypatch):
    cfg = _make_db(tmp_path)
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    tab = w.tabs.widget(0)
    tab.buffer.reset(1)
    tab.buffer.append(0.0, [1.0])
    tab.cfg.store = StoreConfig(kind="sqlite", sqlite_path=cfg.sqlite_path)
    answers, asked = ["new", "", "here"], []
    monkeypatch.setattr(TraceTab, "_ask_target", lambda self, active: asked.append(active) or answers.pop(0))
    n0 = w.tabs.count()
    tab.import_db()                                                                    # "new": a second tab with the recording
    assert asked == [False] and w.tabs.count() == n0 + 1
    t2 = w.tabs.widget(w.tabs.count() - 1)
    assert t2.title() == "Piec 1" and len(t2.buffer) > 3 and len(tab.buffer) == 1
    tab.import_db()                                                                    # cancel: nothing changes
    assert w.tabs.count() == n0 + 1 and len(tab.buffer) == 1
    tab.import_db()                                                                    # "here": replaces the data of this tab
    assert len(tab.buffer) > 3 and tab.title() == "Piec 1"
    w.close()


def test_recording_with_an_active_connection_opens_only_in_a_new_tab(app, tmp_path, pick_first, monkeypatch):
    cfg = _make_db(tmp_path)
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    tab = w.tabs.widget(0)
    tab.state = "running"                                                              # (a live connection)
    tab.cfg.store = StoreConfig(kind="sqlite", sqlite_path=cfg.sqlite_path)
    asked = []
    monkeypatch.setattr(TraceTab, "_ask_target", lambda self, active: asked.append(active) or "new")
    n0 = w.tabs.count()
    tab.import_db()
    assert asked == [True] and w.tabs.count() == n0 + 1
    assert tab.loaded is None and w.tabs.widget(w.tabs.count() - 1).loaded is not None   # the running tab is untouched
    monkeypatch.setattr(TraceTab, "_ask_target", lambda self, active: "")
    tab.import_db()
    assert w.tabs.count() == n0 + 1                                                    # declined: nothing opened
    tab.state = "stopped"
    w.close()


# ------------------------------------------------------------------------------------------------ tab tooltips
def test_tab_tooltips_list_the_connection_the_recording_and_the_database(app, tmp_path, pick_first):
    cfg = _make_db(tmp_path)
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    tab = w.tabs.widget(0)
    tab.cfg.store = StoreConfig(kind="sqlite", sqlite_path=cfg.sqlite_path, keyframe_min=5.0)
    tab.ed_ip.setText("10.9.8.7")
    live = tab.tooltip_html()
    assert "Połączenie ze sterownikiem" in live and "10.9.8.7" in live and "Baza danych (zapis REC)" in live
    assert "SQLite" in live and "rec.db" in live and "Pełny stan co" in live and "5 min" in live
    tab.buffer.reset(0)
    tab.import_db()
    shown = tab.tooltip_html()
    assert "Przebieg wczytany z bazy danych" in shown and "Piec 1" in shown and "próba" in shown
    assert "Baza danych, z której wczytano" in shown and "rec.db" in shown and "Sygnały" in shown
    bar = w.tabs.tabBar()
    ev = QHelpEvent(QEvent.ToolTip, bar.tabRect(0).center(), bar.mapToGlobal(bar.tabRect(0).center()))
    assert w.eventFilter(bar, ev) is True                                              # the window answers the hover itself
    w.close()
