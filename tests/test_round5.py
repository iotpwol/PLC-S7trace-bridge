"""Round 5: foldable side panel / overview strip, status bar width, IP drop-down restore, legend menu, app icon."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QSizePolicy

from s7trace.core.config import TabConfig
from s7trace.core.types import Signal
from s7trace.ui import appicon
from s7trace.ui.fold_splitter import FoldHandle
from s7trace.ui.main_window import MainWindow
from s7trace.ui.theme import apply_dark
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def _tab(ip="10.1.2.3"):
    c = TabConfig(ip=ip, conf_name="L1")
    c.signals = [Signal(name=n, dtype="REAL", db=1, byte=i * 4, color=col)
                 for i, (n, col) in enumerate(zip("AB", ("#ffb347", "#4eb8f0")))]
    tab = TraceTab(c, lambda: [])
    tab.resize(1500, 800)
    tab.show()
    QApplication.processEvents()
    t = np.arange(0, 20, 0.05)
    tab.buffer.reset(2)
    tab.buffer.load(t, np.column_stack([np.sin(t), np.cos(t)]))
    tab.plot.set_follow(False)
    tab.plot.set_view(0, 20)
    tab.plot.refresh(force=True)
    return tab


# --------------------------------------------------------------------- foldable panels
def test_left_panel_folds_with_button_and_double_click(app):
    tab = _tab()
    sp = tab.split_h
    wide = sp.sizes()[0]
    assert wide >= 200 and not sp.collapsed
    handle = sp.handle(1)
    assert isinstance(handle, FoldHandle)
    QTest.mouseClick(handle.btn, Qt.LeftButton)                         # the small button at the top of the bar
    QApplication.processEvents()
    assert sp.collapsed and sp.sizes()[0] == 0 and tab.ui_state["left_collapsed"] is True
    assert sp.sizes()[1] >= tab.width() - 40                            # the chart took the room
    QTest.mouseClick(handle.btn, Qt.LeftButton)
    QApplication.processEvents()
    assert not sp.collapsed and abs(sp.sizes()[0] - wide) <= 3          # back at the old width
    QTest.mouseDClick(handle, Qt.LeftButton, pos=QPoint(handle.width() // 2, 200))   # double click on the blue bar
    QApplication.processEvents()
    assert sp.collapsed and sp.sizes()[0] == 0
    QTest.mouseDClick(handle, Qt.LeftButton, pos=QPoint(handle.width() // 2, 200))
    QApplication.processEvents()
    assert not sp.collapsed and sp.sizes()[0] >= 200
    tab.shutdown()


def test_folded_panel_dragged_open_unfolds(app):
    tab = _tab()
    sp = tab.split_h
    sp.set_collapsed(True)
    sp.moveSplitter(260, 1)                                             # the user drags the bar out
    sp.splitterMoved.emit(260, 1)
    QApplication.processEvents()
    assert not sp.collapsed and sp.sizes()[0] >= 200                    # minimum width is restored with the panel
    tab.shutdown()


def test_overview_strip_folds_down(app):
    tab = _tab()
    sp = tab.plot.split
    assert sp.sizes()[1] >= 48
    QTest.mouseClick(sp.handle(1).btn, Qt.LeftButton)
    QApplication.processEvents()
    assert sp.collapsed and tab.plot.overview_height() == 0 and tab.ui_state["overview_collapsed"] is True
    assert tab.ui_state["overview_h"] >= 48                              # the remembered height is not overwritten by 0
    QTest.mouseDClick(sp.handle(1), Qt.LeftButton, pos=QPoint(300, sp.handle(1).height() // 2))
    QApplication.processEvents()
    assert not sp.collapsed and tab.plot.overview_height() >= 48
    tab.shutdown()


def test_fold_state_is_shared_between_tabs_and_restored(app, tmp_path, monkeypatch):
    cfg = str(tmp_path / "c.json")
    w = MainWindow(config_file=cfg)
    w.resize(1500, 900)
    w.show()
    t0 = w.tabs.widget(0)
    t1 = w.new_tab()
    w.tabs.setCurrentIndex(0)
    QApplication.processEvents()
    t0.split_h.set_collapsed(True)
    t0.plot.split.set_collapsed(True)
    QApplication.processEvents()
    w.tabs.setCurrentIndex(1)
    QApplication.processEvents()
    assert t1.split_h.collapsed and t1.plot.split.collapsed              # the other tab follows
    t1.split_h.set_collapsed(False)
    QApplication.processEvents()
    assert not t0.split_h.collapsed and t0.split_h.sizes()[0] >= 200
    t1.split_h.set_collapsed(True)
    w.close()
    w2 = MainWindow(config_file=cfg)                                    # restored after a restart
    w2.resize(1500, 900)
    w2.show()
    QApplication.processEvents()
    assert w2.tabs.currentWidget().split_h.collapsed and w2.tabs.currentWidget().split_h.sizes()[0] == 0
    w2.tabs.currentWidget().split_h.set_collapsed(False)
    assert w2.tabs.currentWidget().split_h.sizes()[0] >= 200
    w2.close()


# --------------------------------------------------------------------- status bar
def test_long_status_text_does_not_widen_the_window(app):
    tab = _tab()
    assert tab.lbl_status.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
    before = (tab.minimumSizeHint().width(), tab.split_h.sizes()[0], tab.width())
    tab.status_msg = "Wyeksportowano okno do C:/Users/x/Documents/S7Trace/snapshots/" + "d" * 600 + ".csv"
    tab._update_status()
    QApplication.processEvents()
    assert (tab.minimumSizeHint().width(), tab.split_h.sizes()[0], tab.width()) == before
    assert "d" * 600 in tab.lbl_status.toolTip()                         # the whole text stays readable in the tooltip
    tab.shutdown()


# --------------------------------------------------------------------- IP drop-down
def test_ip_dropdown_keeps_the_address_when_nothing_is_chosen(app):
    from s7trace.core import ip_history
    ip_history.add("172.16.0.5")
    tab = _tab("")
    e = tab.ed_ip
    empty = e.displayText()
    assert e.lineEdit().placeholderText() == "192 . 168 . 0 . 1"
    e.showPopup()
    assert e.displayText() == empty and e.text() == ""                  # empty before -> empty (dots only) after opening
    e.hidePopup()
    assert e.text() == "" and e.displayText() == empty
    e.setText("10.12.91.1")
    e.showPopup()
    assert e.text() == "10.12.91.1" and e.displayText() == "10  . 12  . 91  . 1  "
    e.hidePopup()
    assert e.text() == "10.12.91.1"
    e.showPopup()
    e.activated.emit(0)                                                 # an item chosen -> its address is used
    e.hidePopup()
    assert e.text() == "172.16.0.5"
    tab.shutdown()


# --------------------------------------------------------------------- legend menu
def test_right_click_on_legend_opens_menu(app, monkeypatch):
    seen = []
    monkeypatch.setattr(TraceTab, "_legend_menu", lambda self, pos: seen.append(self._build_legend_menu()))
    tab = _tab()
    hidden = []
    tab.legendHideRequested.connect(lambda: hidden.append(1))
    p = tab.plot
    c = p.legend.sceneBoundingRect().center()
    pos = p.glw.mapFromScene(c)
    QTest.mouseClick(p.glw.viewport(), Qt.RightButton, pos=pos)
    QApplication.processEvents()
    assert len(seen) == 1
    menu = seen[0]
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Sygnały…", "Położenie legendy (ta karta)", "Ukryj legendę"]
    corners = next(a for a in menu.actions() if a.menu()).menu()
    next(a for a in corners.actions() if a.text() == "Prawy dolny róg").trigger()
    assert tab.cfg.legend_pos == [1.0, 1.0]
    next(a for a in menu.actions() if a.text() == "Ukryj legendę").trigger()
    assert hidden == [1]
    QTest.mouseClick(p.glw.viewport(), Qt.RightButton, pos=QPoint(400, 300))      # elsewhere on the chart: no menu
    assert len(seen) == 1
    tab.shutdown()


def test_hide_legend_from_menu_hides_it_in_every_tab(app, tmp_path, monkeypatch):
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    t2 = w.new_tab()
    w.tabs.widget(0).legendHideRequested.emit()
    assert not w.act_legend.isChecked() and w.ui["legend"] is False
    assert not w.tabs.widget(0).plot.legend.isVisible() and not t2.plot.legend.isVisible()
    w.close()


# --------------------------------------------------------------------- application icon
def test_icon_and_ico_file(app, tmp_path):
    img = appicon.draw_icon(64)
    assert img.width() == 64 and img.pixelColor(32, 40).alpha() > 0 and img.pixelColor(0, 0).alpha() == 0   # rounded tile
    ico = appicon.ico_bytes()
    assert ico[:4] == b"\x00\x00\x01\x00" and int.from_bytes(ico[4:6], "little") == len(appicon.SIZES)
    first = int.from_bytes(ico[14:18], "little")                         # first entry: size and offset of its PNG
    off = int.from_bytes(ico[18:22], "little")
    assert ico[off:off + 8] == b"\x89PNG\r\n\x1a\n" and first > 100
    assert not app_icon_is_null()
    p = tmp_path / "x" / "s7trace.ico"
    assert appicon.write_ico(str(p)) and p.stat().st_size == len(ico)
    assert appicon.APP_ID and appicon.APP_NAME == "S7Trace"


def app_icon_is_null() -> bool:
    return appicon.app_icon().isNull()
