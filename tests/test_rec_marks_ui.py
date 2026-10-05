"""REC marks on the chart (desktop): Start / Stop REC lines, Manual REC areas, the Save dialog, moving a Start REC (the ghost)."""
import time
from datetime import datetime

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from s7trace.core import marker_look, rec_marks as rmk, store
from s7trace.core.store import StoreConfig
from s7trace.core.types import Signal
from s7trace.ui.markers_ui import PendingDialog, TabMarkers
from s7trace.ui.theme import apply_dark
from test_round5 import _tab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def us(tab, t):
    return store.to_us(tab.start_wall, t)


def db_tab(tmp_path, mode="changes"):
    """A running-looking tab with 20 s of data (10 Hz... 20 Hz) that records into a SQLite file."""
    tab = _tab()
    tab.start_wall = datetime(2026, 10, 5, 12, 0, 0)
    tab._run_signals = [Signal.from_dict(s.to_dict()) for s in tab.cfg.signals]
    tab.cfg.store = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "rec.db"), mode=mode, keyframe_min=0)
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("sqlite"))
    tab.cb_rmode.setCurrentIndex(tab.cb_rmode.findData(mode))
    tab.state = "running"
    return tab


def feed(tab, t0, t1):
    """Samples of the chart / the recorder in [t0, t1) (the data of _tab: sin / cos of the time)."""
    for t in np.arange(t0, t1, 0.05):
        tab.buffer.append(float(t), [float(np.sin(t)), float(np.cos(t))])
        if tab.recorder:
            tab.recorder.write(float(t), [float(np.sin(t)), float(np.cos(t))])


def pump(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def titles(tab):
    return sorted(c["data"]["title"] for mid, c in tab.plot.mitems.items() if rmk.is_rec(mid))


def test_start_and_stop_rec_lines_are_numbered(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.btn_rec.setChecked(True)                                    # REC pressed while the connection runs
    app.processEvents()
    assert tab.recorder is not None and titles(tab) == ["Start REC (1)"]
    feed(tab, 20.0, 22.0)
    tab.btn_rec.setChecked(False)
    app.processEvents()
    assert titles(tab) == ["Start REC (1)", "Stop REC (1)"]
    it = tab.plot.mitems[rmk.pid(rmk.AUTO_START, 1)]["data"]
    assert it["color"] == "#ff8c1a" and it["width"] == 2 and abs(it["x0"] - 19.95) < 1e-6        # at the moment REC was pressed
    tab.btn_rec.setChecked(True)
    app.processEvents()
    assert titles(tab) == ["Start REC (1)", "Start REC (2)", "Stop REC (1)"]
    # the look: another colour / width, and the whole thing can be switched off
    tab.apply_marker_look({"rec_color": "#00ff00", "rec_width": 5, "rec_style": "dash"})
    assert tab.plot.mitems[rmk.pid(rmk.AUTO_START, 2)]["data"]["color"] == "#00ff00"
    assert tab.plot.mitems[rmk.pid(rmk.AUTO_START, 2)]["data"]["width"] == 5
    tab.apply_marker_look({"rec_show": 0})
    assert titles(tab) == []
    tab.apply_marker_look({})
    assert len(titles(tab)) == 3
    tab.btn_rec.setChecked(False)
    tab.mk.rec.new_run()                                             # a new connection run: back to 1
    assert titles(tab) == []
    tab.shutdown()


def test_rec_marks_are_not_markers_of_the_draft(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.btn_rec.setChecked(True)
    app.processEvents()
    assert tab.mk.pending() == 0 and not tab.mk.draft.dirty()          # the lines are drawn, nothing waits to be saved
    assert tab.mk.confirm_close()                                       # closing the tab does not ask about them
    tab.btn_rec.setChecked(False)
    tab.shutdown()


def test_manual_rec_area_is_put_menu_and_saved_as_a_recording(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    menus = []
    monkeypatch.setattr(TabMarkers, "_run_menu", staticmethod(lambda menu, pos: menus.append(menu)))
    tab.mk.chart_menu(5.0, None)
    texts = [a.text() for a in menus[-1].actions() if not a.isSeparator()]
    assert "Manual Start REC (1) tutaj" in texts
    next(a for a in menus[-1].actions() if a.text() == "Manual Start REC (1) tutaj").trigger()
    assert titles(tab) == ["Manual Start REC (1)"] and tab.mk.pending() == 0         # only a start: nothing to save yet
    tab.mk.chart_menu(12.0, None)
    texts = [a.text() for a in menus[-1].actions() if not a.isSeparator()]
    assert "Manual Stop REC (1) tutaj" in texts and "Manual Start REC (2) tutaj" not in texts
    next(a for a in menus[-1].actions() if a.text() == "Manual Stop REC (1) tutaj").trigger()
    mid = rmk.pid(rmk.MANUAL, 1)
    cur = tab.plot.mitems[mid]["data"]
    assert cur["kind"] == "range" and (cur["x0"], cur["x1"]) == (5.0, 12.0) and cur["title2"] == "Manual Stop REC (1)"
    assert tab.mk.pending() == 1 and tab.btn_msave.isEnabled() and "(1)" in tab.btn_msave.text()    # 'Zapisz znaczniki (1)'
    tab.mk.marker_menu(mid, None)                                                    # right click on the area
    acts = {a.text(): a for a in menus[-1].actions() if not a.isSeparator()}
    assert "Zapis Manual REC (1)" in acts and acts["Zapis Manual REC (1)"].isEnabled() and "Usuń Manual REC (1)" in acts
    acts["Zapis Manual REC (1)"].trigger()
    assert pump(lambda: tab.mk.rec.m.manual_get(1)["saved"] not in ("", "zapisuję…"))
    assert tab.mk.pending() == 0 and "nagranie" in tab.mk.rec.m.manual_get(1)["saved"]
    b = store.open_backend(tab.cfg.store, str(tmp_path))
    sess = b.sessions()
    assert len(sess) == 1 and sess[0]["title"] == "Manual REC (1)" and sess[0]["start_us"] == us(tab, 5.0)
    meta, t, v = b.read(sess[0]["id"])
    b.close()
    assert t[0] == us(tab, 5.0) and t[-1] <= us(tab, 12.0) and len(t) > 100
    k = np.searchsorted(t, us(tab, 8.0))
    assert abs(v[k, 0] - np.sin(8.0)) < 0.06 and abs(v[k, 1] - np.cos(8.0)) < 0.06
    tab.shutdown()


def test_save_dialog_lists_manual_areas_and_lets_the_user_choose(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    for t in (2.0, 4.0, 6.0, 9.0):
        tab.mk.rec.place(t)
    assert tab.mk.pending() == 2
    d = PendingDialog([], "save", tab, tab.mk.rec.manual_rows())
    assert d.mtable is not None and d.mtable.rowCount() == 2 and d.selected_manual() == [1, 2]
    from PySide6.QtCore import Qt
    d.mtable.item(0, 0).setCheckState(Qt.Unchecked)
    assert d.selected_manual() == [2]
    d.close()
    shown = []

    def fake_ask(self):
        shown.append(self.selected_manual())
        self.mtable.item(0, 0).setCheckState(Qt.Unchecked)           # the user unticks the first one
        shown.append(self.selected_manual())
        return "save"
    monkeypatch.setattr(PendingDialog, "ask", fake_ask)
    assert tab.mk.save()                                              # the 'Zapisz znaczniki' button
    assert shown == [[1, 2], [2]]
    assert pump(lambda: tab.mk.rec.m.manual_get(2)["saved"] not in ("", "zapisuję…"))
    assert tab.mk.rec.m.manual_get(1)["saved"] == "" and tab.mk.pending() == 1       # the unticked one still waits
    tab.shutdown()


def _ghost_ready(tab, new_t):
    tab.mk.rec.begin_ghost(1)
    assert tab.plot.ghost is not None and tab.btn_pause.isChecked() is (tab.state in ("running", "reconnecting"))
    tab.plot.ghost.setValue(new_t)                                   # the user drags the pulsing twin
    tab.mk.rec._ghost_moved(new_t)


def test_move_start_rec_earlier_through_the_ghost(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes))
    tab.btn_rec.setChecked(True)                                    # REC pressed at 19.95
    app.processEvents()
    feed(tab, 20.0, 24.0)                                           # keeps running: the recorder gets the move as a job
    _ghost_ready(tab, 8.0)
    menus = []
    monkeypatch.setattr(TabMarkers, "_run_menu", staticmethod(lambda menu, pos: menus.append(menu)))
    tab.mk.rec._ghost_menu(None)
    assert [a.text() for a in menus[-1].actions()] == ["Zmień Start REC (1)", "Anuluj przesuwanie"]
    menus[-1].actions()[0].trigger()
    assert tab.plot.ghost is None and asked and "wcześniej" in asked[0] and "dopisane" in asked[0]
    assert pump(lambda: abs(tab.mk.rec.m.span(1)["t0"] - 8.0) < 0.06)
    assert titles(tab) == ["Start REC (1)"] and abs(tab.plot.mitems[rmk.pid(rmk.AUTO_START, 1)]["data"]["x0"] - 8.0) < 0.06
    tab.btn_rec.setChecked(False)
    app.processEvents()
    b = store.open_backend(tab.cfg.store, str(tmp_path))
    meta, t, v = b.read(b.sessions()[0]["id"])
    b.close()
    assert abs(meta["start_us"] - us(tab, 8.0)) < 60_000 and abs(t[0] - us(tab, 8.0)) < 60_000 and t[-1] >= us(tab, 23.0)
    k = np.searchsorted(t, us(tab, 12.0))
    assert abs(v[k, 0] - np.sin(12.0)) < 0.06                          # the part before the automatic start is in the recording now
    tab.shutdown()


def test_move_start_rec_later_deletes_the_older_data(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes))
    tab.buffer.reset(2)
    tab.btn_rec.setChecked(True)
    app.processEvents()
    feed(tab, 0.0, 20.0)                                            # recording from 0 (the buffer was empty when REC was pressed)
    tab.btn_rec.setChecked(False)                                   # a finished recording: the move works on a fresh connection
    app.processEvents()
    assert tab.recorder is None
    tab.mk.rec.begin_ghost(1)
    tab.plot.ghost.setValue(10.0)
    tab.mk.rec._ghost_moved(10.0)
    tab.mk.rec.apply_ghost()
    assert asked and "USUNIĘTE" in asked[0]
    assert pump(lambda: abs(tab.mk.rec.m.span(1)["t0"] - 10.0) < 0.06)
    b = store.open_backend(tab.cfg.store, str(tmp_path))
    meta, t, v = b.read(b.sessions()[0]["id"])
    b.close()
    assert abs(t[0] - us(tab, 10.0)) < 60_000 and t[-1] >= us(tab, 19.0)
    assert abs(v[0, 0] - np.sin(10.0)) < 0.06                          # the state at the new start is kept
    tab.shutdown()


def test_move_start_is_refused_for_a_csv_recording_and_can_be_cancelled(app, tmp_path):
    tab = _tab()
    tab.start_wall = datetime(2026, 10, 5, 12, 0, 0)
    tab._run_signals = [Signal.from_dict(s.to_dict()) for s in tab.cfg.signals]
    tab.cfg.rec_folder = str(tmp_path)
    tab.state = "running"
    tab.btn_rec.setChecked(True)
    app.processEvents()
    assert tab.recorder is not None and not tab.mk.rec.m.span(1)["sid"]
    ok, why = tab.mk.rec.can_move(1)
    assert not ok and "CSV" in why
    tab.btn_rec.setChecked(False)
    tab.mk.rec.begin_ghost(1)                                         # (the menu item is disabled; the ghost API still cancels cleanly)
    tab.mk.rec.cancel_ghost()
    assert tab.plot.ghost is None and tab.mk.rec.m.ghost is None
    tab.shutdown()
