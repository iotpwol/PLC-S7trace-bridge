"""Markers on the chart (unsaved drafts, saving, reminders), the markers window and the search window (desktop, offscreen)."""
import time
from datetime import datetime

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QToolTip

from s7trace.core import markers as mk
from s7trace.core import store
from s7trace.core.config import TabConfig
from s7trace.core.store import DbRecorder, StoreConfig
from s7trace.core.types import Signal
from s7trace.ui import markers_ui as mu
from s7trace.ui.theme import apply_dark
from s7trace.ui.trace_tab import TraceTab

START = datetime(2026, 10, 3, 10, 0, 0)


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


@pytest.fixture
def tab(app, tmp_path):
    c = TabConfig(ip="10.1.2.3", conf_name="L1", name="Linia 1")
    c.signals = [Signal(name="Temp", dtype="REAL", db=1, byte=0), Signal(name="Run", dtype="BOOL", db=1, byte=4)]
    t = TraceTab(c, lambda: [])
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.mk._store = mk.MarkerStore(str(tmp_path / "markers.db"))
    ts = np.arange(0, 600, 0.5)
    temp = 20 + 10 * np.sin(ts / 40)
    run = ((ts > 100) & (ts < 160)).astype(float)
    t.start_wall = START
    t.buffer.reset(2)
    t.buffer.load(ts, np.column_stack([temp, run]))
    t.plot.set_follow(False)
    t.plot.set_view(0, 300)
    t.plot.refresh(force=True)
    return t


def _accept(monkeypatch, **vals):
    def ex(self):
        if "title" in vals:
            self.ed_title.setText(vals["title"])
        if "desc" in vals:
            self.ed_desc.setPlainText(vals["desc"])
        if "notes" in vals:
            self.ed_notes.setPlainText(vals["notes"])
        if "prio" in vals:
            self.cb_prio.setCurrentIndex(self.cb_prio.findData(vals["prio"]))
        if "color" in vals:
            self.cb_color.set_color(vals["color"])
        if "kind" in vals:
            self.cb_kind.setCurrentIndex(self.cb_kind.findData(vals["kind"]))
        if "signals" in vals:
            self.rb_sel.setChecked(True)
            for i in range(self.lst.count()):
                self.lst.item(i).setCheckState(Qt.Checked if self.lst.item(i).text() in vals["signals"] else Qt.Unchecked)
        if "group" in vals:
            self.cb_group.setCurrentText(vals["group"])
        if "width" in vals:
            self.sp_width.setValue(vals["width"])
        if "style" in vals:
            self.cb_style.setCurrentIndex(self.cb_style.findData(vals["style"]))
        if "transp" in vals:
            self.sl_transp.setValue(vals["transp"])
        if "label" in vals:
            self.chk_label.setChecked(vals["label"])
        return True
    monkeypatch.setattr(mu.MarkerEditDialog, "exec", ex)


def _pending(monkeypatch, answer):
    """The window listing unsaved changes answers `answer` ('save' / 'discard' / 'cancel'); what it showed is collected."""
    shown = []

    def ask(self):
        shown.append({"title": self.windowTitle(), "text": self.lbl.text(),
                      "rows": [tuple(self.table.item(i, j).text() for j in range(4)) for i in range(self.table.rowCount())]})
        return answer
    monkeypatch.setattr(mu.PendingDialog, "ask", ask)
    return shown


def test_markers_are_drafts_until_saved(tab, monkeypatch):
    ctl = tab.mk
    _accept(monkeypatch, title="Start pompy", desc="ręczny start", notes="sprawdzić", prio=3, color="#ff0000")
    m = ctl.add_at_us(ctl.to_wall(120.0))
    assert m and m.id < 0 and m.author and m.conn == "Linia 1" and m.color == "#ff0000" and m.priority == 3
    assert abs(m.at_us - (START.timestamp() + 120) * 1e6) < 2
    assert ctl.store.count() == 0 and ctl.pending() == 1                     # nothing in the file yet
    assert list(tab.plot.mitems) == [m.id]                                    # but it is drawn
    assert abs(tab.plot.mitems[m.id]["main"].value() - 120.0) < 1e-3
    data = tab.plot.mitems[m.id]["data"]
    assert data["title"].startswith("*")                                      # marked as unsaved
    assert "Start pompy" in data["tip"] and "sprawdzić" in data["tip"] and "wszystkich przebiegów" in data["tip"] and "niezapisany" in data["tip"]
    assert tab.btn_msave.isEnabled() and tab.btn_msave.text() == "Zapisz znaczniki (1)"
    _accept(monkeypatch, title="Start pompy 2", prio=0)
    ctl.edit(m.id)
    got = ctl.draft.get(m.id)
    assert got.title == "Start pompy 2" and got.priority == 0 and got.description == "ręczny start" and ctl.pending() == 1
    tab.plot.markerMoved.emit(m.id, 130.0, 130.0)                             # dragged on the chart: still the draft
    assert abs(ctl.draft.get(m.id).at_us - (START.timestamp() + 130) * 1e6) < 2 and ctl.store.count() == 0
    shown = _pending(monkeypatch, "cancel")                                   # 'Zapisz znaczniki' lists what is going to be written
    assert ctl.save() is False and ctl.store.count() == 0 and ctl.pending() == 1
    assert shown[0]["title"] == "Zapisz znaczniki" and "<b>1</b> nowych" in shown[0]["text"]
    assert [r[:2] for r in shown[0]["rows"]] == [("nowy", "Start pompy 2")]
    _pending(monkeypatch, "save")
    assert ctl.save() is True
    assert ctl.pending() == 0 and ctl.store.count() == 1
    assert not tab.btn_msave.isEnabled() and tab.btn_msave.text() == "Zapisz znaczniki"
    (saved,) = ctl.store.search()
    assert saved.title == "Start pompy 2" and saved.author and saved.id > 0 and saved.conn == "Linia 1"
    assert list(tab.plot.mitems) == [saved.id] and not tab.plot.mitems[saved.id]["data"]["title"].startswith("*")
    seen = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: seen.append(a[2])))
    assert ctl.save() is True and seen == ["Nie ma niezapisanych znaczników."]       # nothing to save
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    ctl.delete(saved.id, ask=True)                                            # deleting is a draft change, too
    assert ctl.store.get(saved.id) is not None and tab.plot.mitems == {} and ctl.draft.state(saved.id) == "deleted"
    _pending(monkeypatch, "save")
    assert ctl.save() and ctl.store.get(saved.id) is None


def test_save_window_lists_new_edited_and_deleted(tab, monkeypatch):
    ctl, st = tab.mk, tab.mk.store
    a = st.add(ctl.to_wall(10.0), title="Zapisany A", conn="Linia 1")
    b = st.add(ctl.to_wall(20.0), title="Zapisany B", conn="Linia 1")
    _accept(monkeypatch, title="Zmieniony A", color="#00ff00")
    ctl.edit(a.id)
    ctl.delete(b.id)
    _accept(monkeypatch, title="Nowy C")
    ctl.add_at_us(ctl.to_wall(30.0))
    assert ctl.pending() == 3 and st.get(a.id).title == "Zapisany A" and st.get(b.id) is not None
    assert b.id not in tab.plot.mitems                                          # a marker to delete is gone from the chart
    shown = _pending(monkeypatch, "save")
    assert ctl.save()
    rows = shown[0]["rows"]
    assert [r[0] for r in rows] == ["nowy", "zmieniony", "do usunięcia"]
    assert rows[0][1] == "Nowy C" and "Zmieniony A" in rows[1][1] and "tytuł" in rows[1][3] and "kolor" in rows[1][3]
    assert "Zapisany B" in rows[2][1]
    assert "<b>1</b> nowych" in shown[0]["text"] and "<b>1</b> zmienionych" in shown[0]["text"] and "<b>1</b> do usunięcia" in shown[0]["text"]
    assert sorted(m.title for m in st.search()) == ["Nowy C", "Zmieniony A"] and st.get(b.id) is None


def test_reminder_when_the_chart_is_closed(tab, monkeypatch):
    ctl = tab.mk
    assert ctl.confirm_close() is True                                          # nothing unsaved: silent
    _accept(monkeypatch, title="Nie zapisany")
    ctl.add_at_us(ctl.to_wall(50.0))
    shown = _pending(monkeypatch, "cancel")
    assert ctl.confirm_close() is False and ctl.pending() == 1                  # 'Wróć do wykresu'
    assert shown[0]["title"] == "Niezapisane znaczniki" and shown[0]["rows"][0][:2] == ("nowy", "Nie zapisany")
    _pending(monkeypatch, "discard")
    assert ctl.confirm_close() is True and ctl.pending() == 0 and ctl.store.count() == 0 and tab.plot.mitems == {}
    _accept(monkeypatch, title="Zapisz mnie")
    ctl.add_at_us(ctl.to_wall(60.0))
    _pending(monkeypatch, "save")
    assert ctl.confirm_close() is True and ctl.store.count() == 1 and ctl.pending() == 0


def test_main_window_asks_before_closing_a_tab_and_the_program(app, monkeypatch, tmp_path):
    from PySide6.QtGui import QCloseEvent
    from s7trace.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    tab = w.tabs.widget(0)
    tab.mk._store = mk.MarkerStore(str(tmp_path / "w.db"))
    tab.start_wall = START
    _accept(monkeypatch, title="Roboczy")
    tab.mk.add_at_us(tab.mk.to_wall(5.0))
    assert tab.mk.pending() == 1
    shown = _pending(monkeypatch, "cancel")
    n = w.tabs.count()
    w.close_tab(0)
    assert w.tabs.count() == n and len(shown) == 1                              # the tab stays
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert not ev.isAccepted() and len(shown) == 2                              # ... and so does the program
    _pending(monkeypatch, "discard")
    w.close_tab(0)
    assert tab.mk.pending() == 0


def test_list_shows_state_and_undo(tab, monkeypatch):
    ctl, st = tab.mk, tab.mk.store
    a = st.add(ctl.to_wall(50.0), title="Zapisany", conn="Linia 1")
    ctl.sync(True)
    assert a.id in tab.plot.mitems
    ctl.delete(a.id)
    assert ctl.draft.state(a.id) == "deleted" and a.id not in tab.plot.mitems and st.get(a.id) is not None
    ctl.open_list()
    d = ctl.dlg
    assert d.table.rowCount() == 1 and "do usunięcia" in d.table.item(0, 9).text() and d.table.item(0, 1).font().strikeOut()
    assert d.btn_save.isEnabled() and "1" in d.btn_save.text()
    d.table.selectRow(0)
    d.undo()                                                                     # 'Cofnij zmianę'
    assert ctl.pending() == 0 and a.id in tab.plot.mitems and d.table.item(0, 9).text() == "zapisany"
    d.shutdown()


def test_search_in_list_sees_unsaved_markers(tab, monkeypatch):
    ctl = tab.mk
    ctl.store.add(ctl.to_wall(10.0), title="Zapisany pompa", conn="Linia 1")
    _accept(monkeypatch, title="Roboczy pompa")
    ctl.add_at_us(ctl.to_wall(20.0))
    ctl.open_list()
    d = ctl.dlg
    d.ed_text.setText("pompa")
    d._timer.stop()
    d.refresh()
    states = {d.table.item(i, 1).text(): d.table.item(i, 9).text() for i in range(d.table.rowCount())}
    assert states == {"Roboczy pompa": "* nowy", "Zapisany pompa": "zapisany"}
    _pending(monkeypatch, "save")
    d.btn_save.click()
    assert ctl.pending() == 0 and ctl.store.count() == 2
    d.shutdown()


def test_hide_and_show_the_name_of_a_marker(tab, monkeypatch):
    ctl = tab.mk
    m = ctl.store.add(ctl.to_wall(50.0), title="Widoczna nazwa", conn="Linia 1")
    ctl.sync(True)
    assert tab.plot.mitems[m.id]["data"]["title"] == "Widoczna nazwa"
    labels = []
    monkeypatch.setattr(ctl, "_run_menu", lambda menu, pos: labels.extend(x.text() for x in menu.actions()))
    ctl.marker_menu(m.id, None)
    assert "Ukryj nazwę znacznika na wykresie" in labels
    ctl.toggle_label(m.id)
    assert ctl.draft.get(m.id).show_label == 0 and ctl.pending() == 1
    assert tab.plot.mitems[m.id]["data"]["title"] == ""                           # no label drawn; the bubble still has the title
    assert "Widoczna nazwa" in tab.plot.mitems[m.id]["data"]["tip"]
    labels.clear()
    ctl.marker_menu(m.id, None)
    assert "Pokaż nazwę znacznika na wykresie" in labels and "Cofnij zmiany tego znacznika (niezapisane)" in labels
    ctl.toggle_label(m.id)                                                        # back to the saved state: no change left
    assert ctl.pending() == 0 and tab.plot.mitems[m.id]["data"]["title"] == "Widoczna nazwa"
    _accept(monkeypatch, label=False)                                             # the same as a checkbox in the editor
    ctl.edit(m.id)
    assert ctl.draft.get(m.id).show_label == 0
    ctl.draft.discard()


def test_visible_range_and_connection_filter(tab):
    ctl, st = tab.mk, tab.mk.store
    inside = st.add(ctl.to_wall(50.0), title="w", conn="Linia 1")
    other = st.add(ctl.to_wall(60.0), title="inne połączenie", conn="Linia 2")
    free = st.add(ctl.to_wall(70.0), title="bez połączenia")
    outside = st.add(ctl.to_wall(500.0), title="poza widokiem", conn="Linia 1")
    ctl.sync(True)
    assert set(tab.plot.mitems) == {inside.id, free.id}
    ctl._set_show_all(True)
    assert set(tab.plot.mitems) == {inside.id, other.id, free.id}
    tab.plot.set_view(400, 600)
    tab.plot.refresh(force=True)
    ctl.sync()
    assert set(tab.plot.mitems) == {outside.id}


def test_goto_pauses_live_view_and_centres(tab):
    ctl = tab.mk
    tab.state = "running"
    assert ctl.goto_us(ctl.to_wall(200.0))
    assert tab.btn_pause.isChecked()
    x0, x1 = tab.plot.view_range()
    assert x0 < 200 < x1 and abs((x0 + x1) / 2 - 200) < 1.0
    assert not ctl.goto_us(ctl.to_wall(5000.0))                    # outside the data
    tab.state = "stopped"


def test_markers_dialog_search_and_buttons(tab, monkeypatch):
    ctl, st = tab.mk, tab.mk.store
    st.add(ctl.to_wall(10.0), author="jan", title="Alarm temperatury", notes="Łódź", priority=3, conn="Linia 1", color="#ff4d4d")
    st.add(ctl.to_wall(20.0), author="ola", title="Start", priority=1, conn="Linia 1")
    st.add(ctl.to_wall(30.0), author="jan", title="Inne", conn="Linia 2")
    ctl.open_list()
    d = ctl.dlg
    assert d.table.rowCount() == 2                                  # this connection only
    d.cb_scope.setCurrentIndex(d.cb_scope.findData("all"))
    assert d.table.rowCount() == 3
    d.ed_text.setText("łódź")
    d._timer.stop()
    d.refresh()
    assert d.table.rowCount() == 1 and d.table.item(0, 1).text() == "Alarm temperatury"
    d.ed_text.setText("")
    d._timer.stop()
    d.cb_prio.setCurrentIndex(d.cb_prio.findData(1))
    assert {d.table.item(i, 1).text() for i in range(d.table.rowCount())} == {"Start", "Inne"}     # priority 1 (normal)
    d.cb_prio.setCurrentIndex(0)
    d.table.selectRow(0)
    assert "Alarm" in d.detail.toPlainText() or "Start" in d.detail.toPlainText()
    d.go()
    assert tab.btn_pause.isChecked() is False                       # stopped tab: nothing to pause
    x0, x1 = tab.plot.view_range()
    assert x0 <= 10 <= x1
    d.shutdown()


def test_search_in_tab_data(tab, monkeypatch):
    ctl = tab.mk
    ctl.open_search()
    d = ctl.search_dlg
    assert [d.rows[0].sig.itemText(i) for i in range(2)] == ["Temp", "Run"]
    r = d.rows[0]
    r.sig.setCurrentIndex(1)
    r.op.setCurrentIndex(r.op.findData("=="))
    r.a.setValue(1)
    d.run()
    assert len(d.hits) == 1 and d.table.rowCount() == 1
    h = d.hits[0]
    assert abs(h.t0 - (START.timestamp() + 100.5) * 1e6) < 2 and abs(h.duration / 1e6 - 59.0) < 0.6
    assert "Run=1" in d.table.item(0, 2).text()
    d.table.selectRow(0)
    d.go()
    x0, x1 = tab.plot.view_range()
    assert x0 < 100.5 < x1
    _accept(monkeypatch)
    d.mark()
    (got,) = ctl.draft.search()                                                    # a draft marker until it is saved
    assert got.id < 0 and got.title == "Wynik wyszukiwania" and "Run" in got.description and ctl.store.count() == 0
    ctl.draft.discard()
    # two conditions at once: Temp > 28 while Run = 0 -> no run happens at the temperature maximum
    d.rows[0].a.setValue(0)
    d.rows[1].on.setChecked(True)
    d.rows[1].sig.setCurrentIndex(0)
    d.rows[1].op.setCurrentIndex(d.rows[1].op.findData(">"))
    d.rows[1].a.setValue(29.5)
    d.run()
    assert len(d.hits) >= 1
    d.rows[1].on.setChecked(False)
    d.rows[0].op.setCurrentIndex(d.rows[0].op.findData("changes"))
    d.rows[0].sig.setCurrentIndex(1)
    d.run()
    assert len(d.hits) == 2                                          # the signal rises and falls once
    d.sp_min.setValue(0)
    d.dt_go.setDateTime(mu.qdt(ctl.to_wall(250.0)))
    d.goto_time()
    x0, x1 = tab.plot.view_range()
    assert x0 < 250 < x1
    d.shutdown()


def _make_recording(path, start=START, n=3600):
    cfg = StoreConfig(kind="sqlite", sqlite_path=path, mode="all")
    sigs = [Signal(name="Temp", dtype="REAL"), Signal(name="Run", dtype="BOOL")]
    rec = DbRecorder(cfg, sigs, start, {"tab": "Linia 1", "conf": "L1", "title": "Nocna zmiana"})
    for i in range(n):
        rec.write(float(i), [20.0 + (i % 50), 1.0 if 1000 <= i < 1500 else 0.0])
    rec.close()
    return cfg


def test_search_in_database_recording_and_open_it(tab, tmp_path, monkeypatch):
    cfg = _make_recording(str(tmp_path / "rec.db"))
    tab.buffer.reset(2)                                               # an empty tab: the recording opens here
    tab.cfg.store = cfg
    ctl = tab.mk
    ctl.open_search()
    d = ctl.search_dlg
    d.rb_db.setChecked(True)
    assert d.cb_rec.count() == 1 and "Nocna zmiana" in d.cb_rec.itemText(0)
    assert [d.rows[0].sig.itemText(i) for i in range(2)] == ["Temp", "Run"]
    d.rows[0].sig.setCurrentIndex(1)
    d.rows[0].a.setValue(1)
    d.run()
    deadline = time.time() + 15
    while not d.btn_search.isEnabled() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    assert len(d.hits) == 1 and d.table.rowCount() == 1
    assert abs((d.hits[0].t0 - START.timestamp() * 1e6) / 1e6 - 1000) < 1 and abs(d.hits[0].duration / 1e6 - 500) < 2
    d.table.selectRow(0)
    d.go()                                                            # opens the part of the recording around the hit
    assert len(tab.buffer) > 0 and tab.loaded["meta"]["title"] == "Nocna zmiana"
    assert ctl.rec_id() == tab.loaded["meta"]["id"]
    x0, x1 = tab.plot.view_range()
    t0 = ctl.to_rel(int(d.hits[0].t0))
    assert x0 <= t0 <= x1
    _accept(monkeypatch, title="Początek biegu")                      # a marker made on a recording remembers its id
    d.mark()
    (m,) = ctl.draft.search()
    assert m.rec_id == ctl.rec_id() and m.title == "Początek biegu"
    ctl.draft.discard()
    d.shutdown()


def test_marker_of_a_recording_reopens_it(tab, tmp_path):
    cfg = _make_recording(str(tmp_path / "rec.db"))
    tab.cfg.store = cfg
    tab.buffer.reset(2)
    ctl = tab.mk
    from s7trace.core import search as sr
    sess = sr.list_sessions(cfg, str(tmp_path))[0]
    m = ctl.store.add(int(sess["start_us"] + 2000 * 1_000_000), title="x", rec_id=sess["id"], conn="Linia 1")
    ctl.open_list()
    ctl.dlg.cb_scope.setCurrentIndex(ctl.dlg.cb_scope.findData("all"))
    ctl.dlg.select(m.id)
    ctl.dlg.go()
    assert len(tab.buffer) > 0 and tab.loaded["meta"]["id"] == sess["id"]
    assert tab.plot.view_range()[0] <= ctl.to_rel(m.at_us) <= tab.plot.view_range()[1]
    ctl.dlg.shutdown()


def test_csv_import_keeps_wall_time(tab, tmp_path):
    from s7trace.core.csvio import csv_start_wall, write_csv
    p = tmp_path / "x.csv"
    sigs = [Signal(name="A"), Signal(name="B")]
    write_csv(str(p), sigs, np.array([5.0, 6.0]), np.array([[1.0, 2.0], [3.0, 4.0]]), datetime(2026, 1, 2, 3, 4, 5))
    assert csv_start_wall(str(p)) == datetime(2026, 1, 2, 3, 4, 5)
    assert csv_start_wall(str(tmp_path / "missing.csv")) is None


def test_range_marker_drawn_as_translucent_area_and_dragged(tab, monkeypatch):
    ctl = tab.mk
    _accept(monkeypatch, title="Zakres", kind="range", color="#3fc380")
    m = ctl.add_at_us(ctl.to_wall(100.0), end_us=ctl.to_wall(160.0))
    assert m.kind == "range" and abs((m.end_us - m.at_us) / 1e6 - 60) < 0.01
    cur = tab.plot.mitems[m.id]
    reg = cur["main"]
    assert tuple(round(x, 3) for x in reg.getRegion()) == (100.0, 160.0)
    assert reg.brush.color().alpha() > 0 and reg.brush.color().name() == "#3fc380"      # coloured but translucent
    tab.plot.markerMoved.emit(m.id, 110.0, 170.0)                                        # the area dragged / an edge moved
    got = ctl.draft.get(m.id)
    assert abs(got.at_us - (START.timestamp() + 110) * 1e6) < 2 and abs(got.end_us - (START.timestamp() + 170) * 1e6) < 2
    assert tuple(round(x, 3) for x in tab.plot.mitems[m.id]["main"].getRegion()) == (110.0, 170.0)
    tip = tab.plot.mitems[m.id]["data"]["tip"]
    assert "Od:" in tip and "Do:" in tip and "Zakres czasu" in tip
    # the V1 / V2 cursors offer a range marker in the chart menu
    tab.plot.set_v_mode(True)
    tab.plot._add_marker(tab.plot.vmarks, 20.0, 90)
    tab.plot._add_marker(tab.plot.vmarks, 40.0, 90)
    labels = []
    monkeypatch.setattr(ctl, "_run_menu", lambda menu, pos: labels.extend(x.text() for x in menu.actions()))
    ctl.chart_menu(50.0, None)
    assert any("V1" in t for t in labels) and any("zakresu czasu" in t for t in labels) and "Zapisz znaczniki (1)…" in labels


def test_line_width_style_and_area_transparency(tab, monkeypatch):
    from PySide6.QtCore import Qt as QtC
    ctl = tab.mk
    _accept(monkeypatch, title="Punkt", width=6, style="dot", color="#ff0000")
    p = ctl.add_at_us(ctl.to_wall(50.0))
    assert (p.line_width, p.line_style) == (6, "dot")
    pen = tab.plot.mitems[p.id]["main"].pen
    assert pen.width() == 6 and pen.style() == QtC.DotLine
    _accept(monkeypatch, title="Zakres", kind="range", transp=90, color="#0000ff", style="dashdot", width=0)
    r = ctl.add_at_us(ctl.to_wall(100.0), end_us=ctl.to_wall(150.0))
    assert r.opacity == 10 and r.line_width == 0 and r.width_px() == 2                     # 0 = by priority (normal = 2 px)
    reg = tab.plot.mitems[r.id]["main"]
    assert abs(reg.brush.color().alphaF() - 0.10) < 0.01                                   # 90 % transparent
    assert reg.lines[0].pen.style() == QtC.DashDotLine
    _accept(monkeypatch, transp=10)                                                         # nearly opaque
    ctl.edit(r.id)
    assert ctl.draft.get(r.id).opacity == 90
    assert abs(tab.plot.mitems[r.id]["main"].brush.color().alphaF() - 0.90) < 0.01
    tip = tab.plot.mitems[r.id]["data"]["tip"]
    assert "przezroczystość obszaru 10 %" in tip
    d = mu.MarkerEditDialog(ctl.draft.get(p.id), False, tab, [])
    assert not d.w_transp.isVisibleTo(d)                                                    # a point has no area to make transparent
    d.cb_kind.setCurrentIndex(d.cb_kind.findData("range"))
    assert d.w_transp.isVisibleTo(d)


def test_marker_for_chosen_plots_only(tab, monkeypatch):
    ctl = tab.mk
    tab.plot.set_signals([Signal(name="Temp", dtype="REAL", color="#ffb347"), Signal(name="Run", dtype="BOOL", color="#4eb8f0")])
    tab.plot.set_y_layout("lanes")
    tab.plot.refresh(force=True)
    _accept(monkeypatch, title="Tylko temperatura", kind="range", signals=["Temp"])
    m = ctl.add_at_us(ctl.to_wall(100.0), end_us=ctl.to_wall(160.0))
    assert m.signals == ["Temp"]
    cur = tab.plot.mitems[m.id]
    assert len(cur["extras"]) == 3                                             # in the lane of Temp only: the area + 2 edge bars
    geo = tab.plot.lane_geometry()
    r = cur["extras"][0].rect()
    assert abs(r.height() - (geo[0][1] - geo[0][0])) < 1e-9
    _accept(monkeypatch, signals=["Temp", "Run"])                              # the assignment can be changed in the editor
    ctl.edit(m.id)
    assert ctl.draft.get(m.id).signals == ["Temp", "Run"] and len(tab.plot.mitems[m.id]["extras"]) == 6
    _accept(monkeypatch)
    d = mu.MarkerEditDialog(ctl.draft.get(m.id), False, tab, ["Temp", "Run"])
    d.rb_all.setChecked(True)                                                   # ... also back to 'all plots'
    assert d.values()["signals"] == []
    ctl.draft.update(m.id, d.values())
    ctl.sync(True)
    assert tab.plot.mitems[m.id]["extras"] == []


def test_move_position_from_the_menu(tab, monkeypatch):
    ctl = tab.mk
    p = ctl.store.add(ctl.to_wall(100.0), title="p", conn="Linia 1")
    r = ctl.store.add(ctl.to_wall(200.0), end_us=ctl.to_wall(220.0), kind="range", title="r", conn="Linia 1")
    ctl.sync(True)
    ctl.start_move(p.id)
    assert tab.plot.place_marker == p.id and tab.plot.mhi == {p.id}               # highlighted
    assert tab.plot.mitems[p.id]["main"].pen.color().name() == "#ffffff"
    tab.plot.end_marker_placement()
    assert tab.plot.place_marker is None and tab.plot.mhi == set()
    ctl.placed(p.id, 150.0)                                                       # what the click on the chart does
    assert abs(ctl.draft.get(p.id).at_us - (START.timestamp() + 150) * 1e6) < 2
    assert abs(ctl.store.get(p.id).at_us - ctl.to_wall(100.0)) < 2                # the file is untouched until the save
    ctl.placed(r.id, 50.0)                                                        # a range keeps its length, centred on the click
    g = ctl.draft.get(r.id)
    assert abs((g.end_us - g.at_us) / 1e6 - 20) < 0.01 and abs((g.at_us + g.end_us) / 2 - (START.timestamp() + 50) * 1e6) < 5


def test_groups_from_menu_and_dialog(tab, monkeypatch):
    ctl, st = tab.mk, tab.mk.store
    a = st.add(ctl.to_wall(10.0), title="a", conn="Linia 1")
    b = st.add(ctl.to_wall(40.0), title="b", conn="Linia 1")
    c = st.add(ctl.to_wall(70.0), title="c", conn="Linia 1")
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a_, **k: ("Awaria pompy", True)))
    ctl.add_to_group([a.id, b.id])
    dr = ctl.draft
    assert dr.get(a.id).group_name == "Awaria pompy" and dr.get(b.id).group_name == "Awaria pompy" and dr.get(c.id).group_name == ""
    assert st.get(a.id).group_name == "" and ctl.pending() == 2                   # drafts only
    assert dr.groups() == [("Awaria pompy", 2)]
    assert ctl.hi_group == "Awaria pompy" and tab.plot.mhi == {a.id, b.id}        # the group is highlighted
    assert "Awaria pompy" in tab.plot.mitems[a.id]["data"]["tip"]
    ctl.step_in_group(a.id, 1)                                                     # next marker of the group
    x0, x1 = tab.plot.view_range()
    assert x0 < 40 < x1
    ctl.highlight_group("")
    assert tab.plot.mhi == set()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a_, **k: ("Awaria nr 1", True)))
    ctl.rename_group("Awaria pompy")
    assert dr.get(b.id).group_name == "Awaria nr 1"
    ctl.leave_group([b.id])
    assert dr.get(b.id).group_name == "" and dr.get(a.id).group_name == "Awaria nr 1"
    ctl.open_list()
    d = ctl.dlg
    d.cb_scope.setCurrentIndex(d.cb_scope.findData("all"))
    assert any(d.cb_group.itemText(i).startswith("Awaria nr 1 (1)") for i in range(d.cb_group.count()))
    d.cb_group.setCurrentIndex(d.cb_group.findData("Awaria nr 1"))
    assert d.table.rowCount() == 1
    d.cb_group.setCurrentIndex(d.cb_group.findData(""))                            # markers without a group
    assert d.table.rowCount() == 2
    d.cb_group.setCurrentIndex(0)
    d.table.selectAll()
    assert sorted(d._selected_ids()) == sorted([a.id, b.id, c.id])
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a_, **k: ("Wspólna", True)))
    d.btn_grp.click()                                                              # 'Grupuj zaznaczone…'
    assert {dr.get(i).group_name for i in (a.id, b.id, c.id)} == {"Wspólna"}
    _pending(monkeypatch, "save")
    assert ctl.save() and {st.get(i).group_name for i in (a.id, b.id, c.id)} == {"Wspólna"}
    d.shutdown()


def test_hover_opens_the_bubble_with_the_description(tab, monkeypatch):
    ctl = tab.mk
    ctl.store.add(ctl.to_wall(100.0), title="Najazd", description="opis zdarzenia", notes="uwaga", priority=3, conn="Linia 1")
    ctl.sync(True)
    shown = []
    monkeypatch.setattr(QToolTip, "showText", staticmethod(lambda pos, text, *a: shown.append(text)))
    monkeypatch.setattr(QToolTip, "hideText", staticmethod(lambda: shown.append(None)))
    monkeypatch.setattr(QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton))      # earlier tests may leave a button 'pressed'
    pv = tab.plot
    near = pv.vb.mapViewToScene(QPointF(100.2, 0))
    far = pv.vb.mapViewToScene(QPointF(250.0, 0))
    pv._on_hover(near)
    assert shown and "Najazd" in shown[-1] and "opis zdarzenia" in shown[-1] and "uwaga" in shown[-1]
    n = len(shown)
    pv._on_hover(near)
    assert len(shown) == n                                                          # not re-opened while the cursor stays
    pv._on_hover(far)
    assert shown[-1] is None


def test_hover_pen_keeps_colour_and_width_is_the_same_for_points_and_ranges(tab, monkeypatch):
    ctl = tab.mk
    p = ctl.store.add(ctl.to_wall(50.0), title="p", color="#3fc380", conn="Linia 1")
    r = ctl.store.add(ctl.to_wall(100.0), end_us=ctl.to_wall(150.0), kind="range", title="r", color="#4aa3ff", conn="Linia 1")
    ctl.sync(True)
    pv = tab.plot
    hp = pv.mitems[p.id]["main"].hoverPen
    assert hp.color().name() == "#3fc380" and hp.width() == pv.mlook["width_hover"]
    for ln in pv.mitems[r.id]["main"].lines:
        assert ln.hoverPen.color().name() == "#4aa3ff" and ln.hoverPen.width() == pv.mlook["width_hover"]
    # the line widths come from the settings (marker width 0 = 'wg ustawień')
    tab.apply_marker_look({"width_all": 5, "width_sel": 7, "width_other": 2, "width_hover": 9})
    assert pv.mitems[p.id]["main"].pen.width() == 5 and pv.mitems[p.id]["main"].hoverPen.width() == 9
    assert "5 px" in pv.mitems[p.id]["data"]["tip"] or "wg ustawień" in pv.mitems[p.id]["data"]["tip"]
    pv.set_signals([Signal(name="Temp", dtype="REAL", color="#ffb347"), Signal(name="Run", dtype="BOOL", color="#4eb8f0")])
    pv.set_y_layout("lanes")
    q = ctl.store.add(ctl.to_wall(70.0), title="q", signals=["Temp"], conn="Linia 1")
    ctl.sync(True)
    cur = pv.mitems[q.id]
    assert cur["main"].pen.width() == 2 and cur["extras"][0].opts["pen"].width() == 7        # thin guide / the chosen lane
    own = ctl.store.add(ctl.to_wall(80.0), title="own", line_width=3, conn="Linia 1")
    ctl.sync(True)
    assert pv.mitems[own.id]["main"].pen.width() == 3                                          # an own width wins


def test_double_click_on_a_marker_opens_the_editor(tab, monkeypatch):
    ctl = tab.mk
    m = ctl.store.add(ctl.to_wall(50.0), title="x", conn="Linia 1")
    ctl.sync(True)
    seen = []
    monkeypatch.setattr(ctl, "edit", lambda mid: seen.append(mid))
    tab.plot.markerEdit.disconnect()
    tab.plot.markerEdit.connect(lambda mid: seen.append(mid))

    class Ev:
        def __init__(self, double):
            self._d = double

        def button(self):
            return Qt.LeftButton

        def double(self):
            return self._d
    tab.plot._marker_clicked(m.id, Ev(False))
    assert seen == []
    tab.plot._marker_clicked(m.id, Ev(True))
    assert seen == [m.id]


def test_tip_layout_and_yellow_changed_fields(tab, monkeypatch):
    ctl = tab.mk
    r = ctl.store.add(ctl.to_wall(100.0), end_us=ctl.to_wall(102.7), kind="range", title="Zakres", author="jan", conn="Linia 1")
    ctl.sync(True)
    tip = tab.plot.mitems[r.id]["data"]["tip"]
    assert "Od:" in tip and "Do:" in tip and "Consolas" in tip                      # the two dates: a monospaced table, one under the other
    assert tip.index("Autor:") < tip.index("Założono:") < tip.index("Zmodyfikował:") < tip.index("Zmieniono:")
    assert "#ffd24a" not in tip                                                      # nothing changed: nothing highlighted
    _accept(monkeypatch, title="Zmieniony tytuł", prio=3)
    ctl.edit(r.id)
    tip = tab.plot.mitems[r.id]["data"]["tip"]
    assert ctl.draft.changed_fields(r.id) == {"title", "priority"}
    assert tip.count("#ffd24a") == 2 and "Zmieniony tytuł" in tip and "Krytyczny" in tip


def test_recording_starts_when_rec_is_pressed(tmp_path):
    from datetime import datetime, timedelta
    from s7trace.core import store as st
    from s7trace.core.types import Signal as Sg
    cfg = st.StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "r.db"), mode="changes")
    start = datetime(2026, 10, 4, 12, 0, 0)
    rec = st.DbRecorder(cfg, [Sg(name="A", dtype="INT")], start, {"title": "t"}, t0=60.0)      # REC pressed 60 s after Start
    for i in range(21):
        rec.write(60.0 + i, [5.0])                                                             # value never changes after the first row
    rec.close()
    b = st.open_backend(cfg, str(tmp_path))
    (s,) = b.sessions()
    b.close()
    assert abs((s["end_us"] - s["start_us"]) / 1e6 - 20.0) < 0.01                               # 20 s, not 80 s


# ------------------------------------------------------------------ the marker look belongs to the interface configuration
def test_marker_look_is_saved_with_the_interface_configuration(app, tmp_path, monkeypatch):
    import json
    from s7trace.ui import theme as th
    from s7trace.ui.main_window import MainWindow
    monkeypatch.setattr("s7trace.ui.main_window.save_app_config", lambda *a, **k: None)
    look = {"width_all": 5, "width_sel": 6, "width_other": 2, "width_hover": 9}
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    w._apply_marker_look(look)
    assert w.theme["marker_look"] == look
    assert w._config_dict()["ui"]["theme"]["marker_look"] == look and "marker_look" not in w._config_dict()["ui"]
    p = str(tmp_path / "interfejs.json")
    th.save_profile(p, w.theme)                                          # "Zapisz konfigurację interfejsu"
    data = json.load(open(p, encoding="utf-8"))
    assert data["marker_width_all"] == 5 and data["marker_width_hover"] == 9
    w._apply_marker_look({"width_all": 1})                               # something else in the meantime
    assert w.marker_look["width_all"] == 1
    w._load_theme_file(p)                                                # loading the file brings the marker look back
    assert w.marker_look == look and w.theme["marker_look"] == look
    assert w.tabs.widget(0).plot.mlook["width_all"] == 5
    # a file of an older version (no marker keys) leaves the current look alone
    old = {k: v for k, v in data.items() if not k.startswith("marker_")}
    json.dump(old, open(p, "w", encoding="utf-8"))
    w._apply_marker_look({"width_all": 3})
    w._load_theme_file(p)
    assert w.marker_look["width_all"] == 3
    w.close()


def test_marker_look_of_an_older_config_moves_into_the_theme(app, tmp_path, monkeypatch):
    import json
    from s7trace.ui.main_window import MainWindow
    monkeypatch.setattr("s7trace.ui.main_window.save_app_config", lambda *a, **k: None)
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"tabs": [], "ui": {"theme": {"profile": "dark"}, "marker_look": {"width_all": 7}}}), encoding="utf-8")
    w = MainWindow(config_file=str(cfg))
    assert w.marker_look["width_all"] == 7 and w.theme["marker_look"]["width_all"] == 7
    w.close()


# ------------------------------------------------------------------ legend: bubble of a signal, name / address
def test_legend_shows_name_or_address_and_signal_bubble(app, monkeypatch):
    from s7trace.core.types import signal_tip
    tab = TraceTab(TabConfig(), lambda: [])
    sigs = tab.cfg.signals
    tab.plot.set_signals(tab.display_signals())
    names = [lab.text for _s, lab in tab.plot.legend.items]
    assert names == [s.name for s in sigs if s.plot]
    tab.set_legend_mode("address")
    assert [lab.text for _s, lab in tab.plot.legend.items] == [s.address for s in sigs if s.plot]
    assert tab.to_config().legend_mode == "address"
    tab.toggle_legend_mode()
    assert tab.cfg.legend_mode == "name"
    tip = tab._legend_signal_tip(0)
    assert tip == signal_tip(sigs[0], None, reading=False) and "Adres:" in tip and "Aktualna wartość" in tip
    assert "Legenda pokazuje" in [a.text() for a in tab._build_legend_menu().actions() if a.menu()] + [a.text() for a in tab._build_legend_menu().actions()]
    tab.shutdown()


# ------------------------------------------------------------------ foldable groups of the left panel
def test_left_panel_groups_fold_and_unfold(app):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    tab = TraceTab(TabConfig(), lambda: [])
    tab.resize(1200, 800)
    tab.show()
    assert list(tab.folds) == ["Połączenie", "Sterownik", "Zakres okna wykresu", "Trigger", "Nagrywanie REC"]
    g = tab.folds["Trigger"]
    assert g.title() == "Trigger" and g.windowTitle() is not None and g.folded() is False
    full = g.height()
    r = g._label_rect()
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(r.center()), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    g.mousePressEvent(ev)                                           # a click on the title folds the group (animated)
    assert g.folded() is True
    g.set_folded(True, animate=False)
    assert g.height() < full / 2 and not g._body.isVisible() and g._t == 0.0
    tab._layout_moved()
    assert tab.ui_state["folds"]["Trigger"] is True and tab.ui_state["folds"]["Połączenie"] is False
    g.set_folded(False, animate=False)
    assert g._body.isVisible() and g.maximumHeight() > 10000 and g._t == 1.0
    tab.ui_state["folds"] = {"Sterownik": True}
    tab.apply_layout()
    assert tab.folds["Sterownik"].folded() and not tab.folds["Trigger"].folded()
    tab.shutdown()


# ------------------------------------------------------------------ help mode ('?')
def test_help_mode_describes_elements(app, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QDialog
    from s7trace.core import help_texts as ht
    from s7trace.ui import help_mode as hm
    from s7trace.ui.signals_dialog import SignalsDialog
    tab = TraceTab(TabConfig(), lambda: [])
    tab.show()
    t = hm.help_for(tab.btn_sig, QPoint(0, 0))                     # a button with its own text
    assert "Do czego służy" in t and "Jak ustawić" in t
    t = hm.help_for(tab.sp_cycle, QPoint(0, 0))                    # a field: described by its form label
    assert "cykl" in t.lower() and "1–60000" in t
    assert "Zakres" in hm.help_for(tab.cb_tsig, QPoint(0, 0)) or "Sygnał" in hm.help_for(tab.cb_tsig, QPoint(0, 0))
    assert hm.help_for(tab.folds["Trigger"], QPoint(0, 0)).startswith("Co to jest")
    assert ht.norm("Cykle [ms]:") == "cykle [ms]" and ht.lookup("Pobierz")
    d = SignalsDialog(tab.cfg.signals, False, lambda: [], {"autonumber": True, "name_mode": "prev", "own_name": "SIG", "offset_step": 1.1}, tab.current_values)
    d.show()
    h = d.table.horizontalHeader()
    names = [str(d.table.model().headerData(i, Qt.Horizontal)) for i in range(d.table.columnCount())]
    assert all(ht.lookup(n) for n in names if n not in ("", "Opis") or n == "Opis"), [n for n in names if not ht.lookup(n)]
    mode = hm.instance()
    seen = []
    mode.modeChanged.connect(seen.append)
    mode.set_active(True)
    mode.set_active(False)
    assert seen == [True, False]
    d.close()
    tab.shutdown()
