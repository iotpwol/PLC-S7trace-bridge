"""Markers on the chart (unsaved drafts, saving, reminders), the markers window and the search window (desktop, offscreen)."""
import time
from datetime import datetime

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QFormLayout, QInputDialog, QMenu, QMessageBox, QToolTip

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
    labels = []
    monkeypatch.setattr(ctl, "_run_menu", lambda menu, pos: labels.extend(x.text() for x in menu.actions()))
    ctl.chart_menu(50.0, None)
    assert any("zakresu czasu" in t for t in labels) and "Zapisz znaczniki (1)…" in labels
    assert "Dodaj znacznik różnicy poziomu…" in labels and not any("V1" in t for t in labels)    # the V cursors are gone


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
    g.mousePressEvent(ev)                                           # a click on the title folds the group (animated), on release
    g.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(r.center()), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    assert g.folded() is True
    g.set_folded(True, animate=False)
    assert g.height() < full / 2 and not g._body.isVisible() and g._t == 0.0
    tab._layout_moved()
    st = tab.panel_state()
    assert st["folds"]["Trigger"] is True and st["folds"]["Połączenie"] is False
    g.set_folded(False, animate=False)
    assert g._body.isVisible() and g.maximumHeight() > 10000 and g._t == 1.0
    tab.apply_panel({"folds": {"Sterownik": True}})
    assert tab.folds["Sterownik"].folded() and not tab.folds["Trigger"].folded()
    tab.shutdown()


def test_left_panel_drag_reorder_and_interface_profile(app, tmp_path):
    from s7trace.core import panel_cfg
    from s7trace.ui import theme as th
    tab = TraceTab(TabConfig(), lambda: [])
    tab.resize(1200, 900)
    tab.show()
    default = list(panel_cfg.GROUPS)
    assert tab._group_order() == default
    g = tab.folds["Trigger"]
    top = tab.folds["Połączenie"]
    tab._reorder_group(g, top.mapToGlobal(top.rect().center()).y() - 5)        # dragged above the first group
    assert tab._group_order()[0] == "Trigger" and sorted(tab._group_order()) == sorted(default)
    seen = []
    tab.layoutChanged.connect(lambda: seen.append(1))
    tab._layout_moved()
    st = tab.panel_state()
    assert st["order"][0] == "Trigger" and seen
    # the order is a part of the interface configuration: normalised, saved in the profile file and loaded back
    theme = th.normalize({"panel": st})
    assert theme["panel"]["order"][0] == "Trigger"
    f = tmp_path / "iface.json"
    th.save_profile(str(f), theme)
    back = th.load_profile(str(f))
    assert back["panel"]["order"] == st["order"]
    tab.apply_panel(panel_cfg.DEFAULTS)                                       # another configuration puts the groups back
    assert tab._group_order() == default
    tab.apply_panel(back["panel"])
    assert tab._group_order() == st["order"]
    tab.shutdown()


def test_left_panel_rows_hide_via_menus_and_profile(app, tmp_path):
    from s7trace.core import panel_cfg
    from s7trace.ui import theme as th
    tab = TraceTab(TabConfig(), lambda: [])
    tab.resize(1200, 900)
    tab.show()
    for g in panel_cfg.ALL_GROUPS:                                            # the names the menus use = panel_cfg.ROWS
        assert tuple(k for k in tab._row_keys[g] if k) == panel_cfg.ROWS[g]
    assert tab.ed_ip.isVisible() and tab.sp_cycle.isVisible()
    tab._toggle_row("Połączenie", "IP", False)                               # right click on the name "IP" -> Ukryj
    assert not tab.ed_ip.isVisible() and tab.sp_cycle.isVisible()
    assert tab.panel_state()["hidden"]["Połączenie"] == ["IP"]
    m = QMenu()
    tab._rows_menu(m, "Połączenie")                                           # menu of the group title: check list + show all
    acts = {a.text(): a for a in m.actions() if a.text()}
    assert acts["IP"].isCheckable() and not acts["IP"].isChecked() and acts["Cykle [ms]"].isChecked() and acts["Pokaż wszystkie elementy"].isEnabled()
    acts["IP"].trigger()
    assert tab.ed_ip.isVisible() and tab.panel_state()["hidden"]["Połączenie"] == []
    # the right click on the label / on the group title reaches the menus
    seen = []
    tab._row_menu = lambda t, k, pos: seen.append((t, k))
    lab = tab._forms["Połączenie"].itemAt(0, QFormLayout.LabelRole).widget()
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtCore import QPoint
    QApplication.sendEvent(lab, QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(3, 3), QPoint(3, 3)))
    assert seen == [("Połączenie", "IP")]
    # saved in the interface configuration file and loaded back (unknown names are dropped)
    st = {**tab.panel_state(), "hidden": {"Trigger": ["Folder", "Nie ma takiego"], "Połączenie": ["Metoda"]}}
    theme = th.normalize({"panel": st})
    assert theme["panel"]["hidden"]["Trigger"] == ["Folder"] and theme["panel"]["hidden"]["Połączenie"] == ["Metoda"]
    f = tmp_path / "iface.json"
    th.save_profile(str(f), theme)
    back = th.load_profile(str(f))
    tab.apply_panel(back["panel"])
    assert not tab.lbl_method.isVisible() and tab.ed_ip.isVisible()
    tab.apply_panel(panel_cfg.DEFAULTS)
    assert tab.lbl_method.isVisible()
    tab.shutdown()


def test_panel_cfg_normalize():
    from s7trace.core import panel_cfg
    n = panel_cfg.normalize({"order": ["Trigger", "x", "Trigger"], "folds": {"Trigger": 1}, "info_tab": 7})
    assert n["order"][0] == "Trigger" and sorted(n["order"]) == sorted(panel_cfg.GROUPS)
    assert n["folds"]["Trigger"] is True and n["folds"]["Połączenie"] is False and n["info_tab"] == 0
    assert panel_cfg.normalize(None) == panel_cfg.DEFAULTS


def test_side_tabs_system_and_network(app):
    from s7trace.core import sysinfo
    tab = TraceTab(TabConfig(), lambda: [])
    tab.show()
    assert [tab.info_tabs.tabText(i) for i in range(tab.info_tabs.count())] == ["System", "Sieć"]
    tab._update_side()
    assert tab.sys_vals["Godzina systemowa"].text() and tab.sys_vals["Obciążenie CPU"].text()
    assert tab.sys_vals["System operacyjny"].text() and "Windows" in tab.sys_vals["System operacyjny"].text()
    assert "Brak połączenia" in tab.lbl_netmsg.text() and not tab.net_vals["Missed"].isVisibleTo(tab.page_net)
    tab._update_status()
    assert "PLC comm lag" not in tab.lbl_status.text()
    v = sysinfo.cpu_percent()
    assert v is None or 0.0 <= v <= 100.0
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


# ---------------------------------------------------------- 'Różnica sygnału' (a level difference of ONE signal)
def test_delta_marker_needs_exactly_one_signal(tmp_path):
    store_ = mk.MarkerStore(str(tmp_path / "d.db"))
    base = 1_800_000_000_000_000
    for bad in ([], ["A", "B"]):
        with pytest.raises(mk.MarkerError):
            store_.add(base, kind="delta", end_us=base + 10, signals=bad)
    d = store_.add(base + 20, kind="delta", end_us=base + 5, signals=["A"])
    assert d.kind == "delta" and (d.at_us, d.end_us) == (base + 5, base + 20) and d.last_us == base + 20     # ends put in order
    with pytest.raises(mk.MarkerError):
        store_.update(d.id, {"signals": ["A", "B"]})                    # also a later change keeps the rule
    assert store_.update(d.id, {"signals": ["B"]}).signals == ["B"]
    assert store_.search(t0_us=base + 18)                                   # found by its end like a range


def test_delta_dialog_forces_one_selected_signal(tab, app):
    ctl = tab.mk
    m = mk.Marker(kind="point", at_us=ctl.to_wall(10.0))
    d = mu.MarkerEditDialog(m, True, tab, ["Temp", "Run"], [])
    d.cb_kind.setCurrentIndex(d.cb_kind.findData("delta"))
    assert d.rb_sel.isChecked() and not d.rb_all.isEnabled() and not d.dt2.isHidden() and d.w_transp.isHidden()
    d.lst.item(0).setCheckState(Qt.Checked)
    d.lst.item(1).setCheckState(Qt.Checked)                                  # a second tick moves the choice, it does not add
    assert [d.lst.item(i).checkState() == Qt.Checked for i in range(2)] == [False, True]
    d.cb_kind.setCurrentIndex(d.cb_kind.findData("range"))
    assert d.rb_all.isEnabled()


def test_delta_marker_draws_difference_and_menu_offers_it(tab, monkeypatch):
    ctl = tab.mk
    plot = tab.plot
    b, t = plot._lane_geo[0]                                                 # the lane of Temp
    plot.ctx_y = (b + t) / 2
    assert ctl.level_signal() == "Temp"
    labels = {}
    monkeypatch.setattr(ctl, "_run_menu", lambda menu, pos: labels.update({x.text(): x for x in menu.actions()}))
    ctl.chart_menu(100.0, None)
    assert labels["Dodaj znacznik różnicy poziomu…"].isEnabled()
    _accept(monkeypatch, title="Wzrost")
    m = ctl.add_at_us(ctl.to_wall(100.0), end_us=ctl.to_wall(160.0), signals=[ctl.level_signal()], kind="delta")
    assert m.kind == "delta" and m.signals == ["Temp"]
    plot.refresh(force=True)
    want = 10 * (np.sin(160 / 40) - np.sin(100 / 40))
    texts = [e.toPlainText() for e in plot._delta_items if hasattr(e, "toPlainText")]
    assert len(texts) == 1 and texts[0].startswith(f"Δ = {want:+.5g}")
    assert "Różnica sygnału" in plot.mitems[m.id]["data"]["tip"]
    assert plot.mitems[m.id]["main"].brush.color().alpha() == 0              # no area, only the bars and the arrow
    ctl.delete(m.id)
    assert not plot._delta_items                                              # the overlay disappears with the marker
    ctl.dlg and ctl.dlg.shutdown()


def test_level_marker_and_points_are_menu_items(app):
    from s7trace.ui.main_window import MainWindow
    w = MainWindow()
    try:
        t = w.tabs.currentWidget() or w.new_tab()
        assert not hasattr(t, "btn_v") and not hasattr(t, "btn_h") and not hasattr(t, "btn_pts")
        w.act_hlevel.setChecked(True)
        w.act_points.setChecked(True)
        assert t.act_hlev.isChecked() and t.plot.h_mode and t.act_pts.isChecked() and t.plot.show_points
        t2 = w.new_tab()                                                     # another tab has its own state: the menu follows it
        assert not w.act_hlevel.isChecked() and not w.act_points.isChecked()
        w.tabs.setCurrentIndex(0)
        assert w.act_hlevel.isChecked() and w.act_points.isChecked()
        assert w.act_hlevel.text().startswith("Znacznik poziomu sygnału") and "Punkty" in w.act_points.text()
    finally:
        w.close()


# ---------------------------------------------------------- markers are locked until 'Zmień pozycję znacznika' is ticked
def test_markers_are_locked_until_unlocked_in_the_menu(tab, monkeypatch):
    ctl = tab.mk
    _accept(monkeypatch, title="p")
    p = ctl.add_at_us(ctl.to_wall(50.0))
    _accept(monkeypatch, title="r", kind="range")
    r = ctl.add_at_us(ctl.to_wall(100.0), end_us=ctl.to_wall(160.0))
    plot = tab.plot
    assert not plot.mitems[p.id]["main"].movable and not plot.mitems[r.id]["main"].movable   # a drag pans the chart, not the marker
    acts = {}
    monkeypatch.setattr(ctl, "_run_menu", lambda menu, pos: acts.update({x.text(): x for x in menu.actions()}))
    ctl.marker_menu(r.id, None)
    a = acts["Zmień pozycję znacznika"]
    assert a.isCheckable() and not a.isChecked()
    a.setChecked(True)                                                       # ticked: this marker can be dragged
    assert plot.mitems[r.id]["main"].movable and not plot.mitems[p.id]["main"].movable
    ctl.sync(True)                                                           # a redraw / rebuild keeps the unlock
    assert plot.mitems[r.id]["main"].movable
    acts.clear()
    ctl.marker_menu(r.id, None)
    assert acts["Zmień pozycję znacznika"].isChecked()
    acts["Zmień pozycję znacznika"].setChecked(False)
    assert not plot.mitems[r.id]["main"].movable
    ctl.dlg and ctl.dlg.shutdown()


# ---------------------------------------------------------- the time axis: seconds / computer clock / PLC clock, with an offset
def test_time_axis_clock_modes_and_offset(tab):
    ax = tab.plot.plot.getAxis("bottom")
    ov = tab.plot.ov.getAxis("bottom")
    t0 = START.timestamp()
    assert ax.mode == "rel" and ax.shift == 0 and ax.tickStrings([10.0, 20.0], 1, 10) == ["10s", "20s"]
    tab.cb_taxis.setCurrentIndex(tab.cb_taxis.findData("app"))
    assert ax.mode == "app" and ov.mode == "app" and abs(ax.shift - t0) < 1e-6 and tab.cfg.time_axis == "app"
    v = ax.tickValues(0, 10, 800)[0]
    assert ax.tickStrings(v[1][:2], 1, v[0]) == ["10:00:00", "10:00:02"]                    # whole seconds on round clock values
    assert ax.tickStrings([0.0], 1, 1.0) == ["10:00:00"] and ax.tickStrings([0.25], 1, 0.05) == ["10:00:00.250"]
    assert ax.tickStrings([0.0], 1, 60.0) == ["10:00"]                                      # only as much as the zoom needs
    tab.sp_toff.setValue(1.5)                                                               # the axis is corrected by +1.5 s
    assert abs(ax.shift - (t0 + 1.5)) < 1e-6 and ax.tickStrings([0.0], 1, 0.5) == ["10:00:01.500"]
    tab.device = {"method": "s7", "info": {"family": "S7-1500"}, "time_diff_local": 2.0}
    tab.cb_taxis.setCurrentIndex(tab.cb_taxis.findData("plc"))                              # controller clock = computer + difference
    assert abs(ax.shift - (t0 + 2.0 + 1.5)) < 1e-6 and ax.tickStrings([0.0], 1, 0.5) == ["10:00:03.500"]
    tab.cb_taxis.setCurrentIndex(tab.cb_taxis.findData("rel"))
    assert ax.mode == "rel" and ax.shift == 1.5 and ax.tickStrings([10.0], 1, 0.5) == ["11.5s"]
    c = tab.to_config()
    assert (c.time_axis, c.time_offset) == ("rel", 1.5)
    from s7trace.core.config import TabConfig as TC
    c2 = TC.from_dict({**c.to_dict(), "time_axis": "zzz", "time_offset": "x"})
    assert (c2.time_axis, c2.time_offset) == ("rel", 0.0)
    ticks = ax.tickValues(0, 30, 800)
    assert ticks and all(abs((x + 1.5) / ticks[0][0] - round((x + 1.5) / ticks[0][0])) < 1e-9 for x in ticks[0][1])   # ticks on the shifted scale


def test_help_bubble_under_the_cursor_is_not_described_again(tab, monkeypatch):
    """The bubble of the help mode ended up under the cursor, was described as an element and the new bubble contained the old one: the
    text doubled on every poll and the program hung."""
    from PySide6.QtCore import QPoint
    from s7trace.ui import help_mode as hmod
    QToolTip.showText(QPoint(200, 200), "Opis testowy", tab)
    QApplication.processEvents()
    bubble = next((w for w in QApplication.topLevelWidgets() if w.metaObject().className() == "QTipLabel" and w.isVisible()), None)
    assert bubble is not None and hmod.is_bubble(bubble) and hmod.help_for(bubble, QPoint(200, 200)) == ""
    hm = hmod.instance()
    shown = []
    monkeypatch.setattr(hmod.QToolTip, "showText", lambda *a: shown.append(a))
    monkeypatch.setattr(hmod.QApplication, "widgetAt", staticmethod(lambda pos: bubble))
    for _ in range(5):
        hm._poll()
    assert not shown                                                         # nothing new is shown while the cursor is on the bubble
    QToolTip.hideText()


# ---------------------------------------------------------- offset = date (days) + HH:MM:SS.mmm; the PLC clock in the 'Sterownik' box
def test_offset_helpers_and_editor_roundtrip(tab):
    from s7trace.core.types import TIME_OFFSET_MAX, fmt_offset, offset_join, offset_split
    assert offset_split(0) == (False, 0, 0) and offset_split(90061.5) == (False, 1, 3_661_500)
    assert offset_split(-90061.5) == (True, 1, 3_661_500) and offset_join(True, 1, 3_661_500) == -90061.5
    assert offset_split(-0.0004) == (False, 0, 0)                                   # a sign without a value is no offset
    assert offset_split(1e12)[1] == 3650 and TIME_OFFSET_MAX == 3650 * 86400.0       # clamped to 10 years
    assert fmt_offset(-(3 * 86400 + 7200)) == "-3 d 02:00:00.000"
    ed = tab.sp_toff
    for v in (0.0, 1.5, -2.25, 86400.0 * 400 + 3723.004, -86400.0 * 3650):
        ed.setValue(v)
        assert abs(ed.value() - v) < 1e-6, v
    ed.setValue(-90061.5)                                                           # the two fields + the sign button
    assert ed.btn_sign.isChecked() and ed.sp_days.value() == 1 and ed.ed_time.time().toString("HH:mm:ss.zzz") == "01:01:01.500"
    got = []
    ed.valueChanged.connect(got.append)
    ed.sp_days.setValue(2)
    assert got and abs(got[-1] - -(2 * 86400 + 3661.5)) < 1e-6
    ed.setValue(0.0)
    tab.sp_toff.setValue(5 * 86400 + 1.5)                                           # the tab takes it into the axis and the config
    ax = tab.plot.plot.getAxis("bottom")
    assert tab.to_config().time_offset == 5 * 86400 + 1.5 and ax.shift == 5 * 86400 + 1.5          # (relative axis: shift = offset)


def test_sterownik_box_shows_the_plc_clock_and_suggests_an_offset(tab):
    from datetime import datetime, timedelta
    dev = {"method": "s7", "info": {"family": "S7-300", "model": "CPU 315-2 PN/DP", "firmware": "V3.2.10", "plc_name": "Proofer",
                                    "module_name": "CPU 315-2 PN/DP"}, "time_diff_local": 3 * 86400.0 + 7200.0}
    tab._infoRaw.emit(dev)
    QApplication.processEvents()
    plc = datetime.now() + timedelta(seconds=dev["time_diff_local"])
    t = tab.device_text()
    assert f"Czas PLC: {plc:%Y-%m-%d}  {plc:%H:%M}" in t                                        # date and time separated by two spaces
    assert t.index("Nazwa modułu") < t.index("Czas PLC")                                        # the sixth line
    assert "+3 d 02:00:00.000" in tab.lbl_status.text() and "Offset osi" in tab.lbl_status.text()  # a day or more: announced
    tab._tick_plc_time()                                                                        # refreshed from the computer's clock
    assert "Czas PLC:" in tab.device_text() and tab.plc_timer.interval() == 1000 and tab.plc_timer.isActive()
    tab.sp_toff.setValue(-dev["time_diff_local"])                                               # 'Wyrównaj do komputera'
    tab.cb_taxis.setCurrentIndex(tab.cb_taxis.findData("plc"))
    ax = tab.plot.plot.getAxis("bottom")
    assert abs(ax.shift - tab.start_wall.timestamp()) < 1e-6                                    # PLC axis = the computer's clock again
    tab.status_msg = "Gotowy."
    tab._update_status()
    tab._infoRaw.emit({**dev, "time_diff_local": 2.0})
    assert "Czas PLC" in tab.device_text() and "różni się" not in tab.lbl_status.text()         # a small difference is not announced
    tab._infoRaw.emit({**dev, "time_diff_local": None, "time_error": "sterownik odrzucił odczyt zegara"})
    assert "Czas PLC: nie odczytano" in tab.device_text()                                       # the clock could not be read
    assert "odrzucił" in tab.dev_vals["Czas PLC"].toolTip()
    tab.device = None
    tab._show_device()
    assert "Czas PLC" not in tab.device_text()


# ------------------------------------------------------------------ 'Pobierz dane sterownika' + the load of this program
def test_read_device_button_reads_only_controller_data(app):
    import time as _t
    from s7trace.sim import Simulator
    sim = Simulator(11177)
    sim.start()
    _t.sleep(0.5)
    try:
        tab = TraceTab(TabConfig(), lambda: [])
        tab.show()
        tab.ed_ip.setText("127.0.0.1:11177")
        assert tab.btn_dev.isEnabled() and tab.state == "stopped" and tab.device is None
        assert "Brak danych sterownika" in tab.lbl_dev.text()
        tab.read_device_now()                                               # no Start, no signals, no chart
        assert tab._dev_busy and not tab.btn_dev.isEnabled() and tab.btn_dev.text() == "Pobieranie…"
        end = _t.time() + 15
        while tab._dev_busy and _t.time() < end:
            app.processEvents()
            _t.sleep(0.05)
        assert not tab._dev_busy and tab.btn_dev.isEnabled() and tab.btn_dev.text() == "Pobierz dane sterownika"
        assert tab.state == "stopped" and tab.acq is None
        assert tab.device is not None and tab.device["method"] == "s7"
        assert "Nie udało się" not in tab.lbl_dev.text()
        tab.shutdown()
    finally:
        sim.stop()


def test_read_device_button_reports_failure_and_wrong_method(app, monkeypatch):
    tab = TraceTab(TabConfig(), lambda: [])
    tab.show()
    from s7trace.core import detect
    monkeypatch.setattr(detect, "read_device_s7", lambda *a: (_ for _ in ()).throw(RuntimeError("brak odpowiedzi")))
    tab.ed_ip.setText("127.0.0.1:11999")
    tab.read_device_now()
    import time as _t
    end = _t.time() + 10
    while tab._dev_busy and _t.time() < end:
        app.processEvents()
        _t.sleep(0.05)
    assert "Nie udało się pobrać danych sterownika: brak odpowiedzi" in tab.lbl_dev.text() and tab.device is None
    tab.cb_ctype = getattr(tab, "cb_ctype", None)
    tab.cfg.conn_type = "opcua"
    tab._collect = lambda: type("C", (), {"conn_type": "opcua", "ip": "127.0.0.1"})()
    tab.read_device_now()
    assert "tylko dla połączenia S7comm" in tab.lbl_dev.text() and not tab._dev_busy
    tab.shutdown()


def test_system_tab_shows_the_load_of_this_program(app):
    import time as _t
    from s7trace.core import sysinfo
    sysinfo.app_cpu_percent()
    end = _t.time() + 1.2
    while _t.time() < end:                                                    # burn a little CPU so that the interval has a load
        sum(i * i for i in range(20000))
    v = sysinfo.app_cpu_percent()
    assert v is not None and 0.0 <= v <= 100.0
    tab = TraceTab(TabConfig(), lambda: [])
    tab.show()
    tab._update_side()
    assert tab.sys_vals["w tym ta aplikacja"].text() not in ("", "—") or sysinfo.app_cpu_percent() is None
    tab.shutdown()


def test_recording_info_dialog_has_title_description_notes_tags(app):
    from PySide6.QtWidgets import QLabel
    from s7trace.ui.store_dialog import RecInfoDialog
    d = RecInfoDialog("Piec 2", "uwaga", "rozruch", "Nazwa", description="opis 1")
    labels = [w.text() for w in d.findChildren(QLabel) if w.text().endswith(":")]
    assert labels == ["Tytuł:", "Opis:", "Uwagi:", "Tagi:"]                                   # the order of the standard fields
    assert d.values() == {"title": "Piec 2", "description": "opis 1", "notes": "uwaga", "tags": "rozruch"}
    d.ed_desc.setPlainText("zmieniony")
    assert d.values()["description"] == "zmieniony"


def test_data_in_sentences_is_bold_everywhere():
    from s7trace.core.richtext import bold, bold_numbers
    t = bold_numbers("Pominięte cykle: 19.8% – cykl (25 ms), zalecany ≥ 45 ms; CPU S7-300, DB1, 10.12.91.1 <ok>")
    assert "<b>19.8%</b>" in t and "<b>25 ms</b>" in t and "<b>≥ 45 ms</b>" in t
    assert "S7-300" in t and "DB1" in t and "10.12.91.1" in t and "&lt;ok&gt;" in t        # names / addresses / markup are left alone
    assert bold("10.12.91.1 <x>") == "<b>10.12.91.1 &lt;x&gt;</b>"


def test_plc_clock_is_parsed_from_the_raw_answer_and_a_failure_is_explained():
    from datetime import datetime
    from s7trace.core import detect
    real = bytes.fromhex("3207000000030" + "00c000e00011208128701000000000" + "0ff09000a00" + "2026100511443112" + "34")
    assert detect.parse_clock_pdu(real) == datetime(2026, 10, 5, 11, 44, 31)                  # a PLC sends 10 bytes with the century
    wrong = bytes.fromhex("3207000000030" + "00c000e00011208128701000000000" + "0ff09000a00" + "1926100511443112" + "34")
    assert detect.parse_clock_pdu(wrong) == datetime(2026, 10, 5, 11, 44, 31)                 # the century byte is a fixed 0x19 in some PLCs: ignored (was 1926)
    sim = bytes.fromhex("32070000000300" + "0c000c000112081287010000000000" + "ff09000800" + "261005114431" + "01")
    assert detect.parse_clock_pdu(sim) == datetime(2026, 10, 5, 11, 44, 31)                   # the simulator sends 8
    refused = bytes.fromhex("32070000000300" + "0c0004000112081287010000000000" + "0a000000")
    with pytest.raises(RuntimeError, match="odrzucił"):
        detect.parse_clock_pdu(refused)


def test_every_data_row_of_the_boxes_hides_and_the_read_button_comes_from_the_menu(app):
    from PySide6.QtWidgets import QMenu
    from s7trace.core import panel_cfg
    tab = TraceTab(TabConfig(), lambda: [])
    tab.show()
    tab._infoRaw.emit({"method": "s7", "info": {"family": "S7-300", "model": "M", "serial": "SN1", "state": "S7CpuStatusRun"}, "time_diff_local": 1.0})
    QApplication.processEvents()
    assert tab.dev_vals["Rodzina"].isVisible() and not tab.dev_vals["Numer seryjny"].isVisible()      # the extra data starts hidden
    tab._toggle_row("Sterownik", "Numer seryjny", True)                                       # ... and can be shown one by one
    assert tab.dev_vals["Numer seryjny"].isVisible() and not tab.dev_vals["Stan CPU"].isVisible()
    tab._toggle_row("Sterownik", "Rodzina", False)
    assert not tab.dev_vals["Rodzina"].isVisible() and tab.dev_vals["Model"].isVisible()
    tab._toggle_row("Sterownik", "Pobierz dane", False)                                       # the button hides like any element
    assert not tab.btn_dev.isVisible()
    m = QMenu()
    tab._device_action(m)                                                                     # ... and stays available from the menu
    assert [a.text() for a in m.actions()] == ["Pobierz dane sterownika"] and m.actions()[0].isEnabled()
    tab._update_side()                                                                        # the bottom tabs: single rows
    assert tab.sys_vals["GUI lag"].isVisibleTo(tab.page_sys)
    tab._toggle_row("System", "GUI lag", False)
    assert not tab.sys_vals["GUI lag"].isVisibleTo(tab.page_sys) and tab.sys_vals["Obciążenie CPU"].isVisibleTo(tab.page_sys)
    assert tab.panel_state()["hidden"]["System"] == ["GUI lag"] and "Rodzina" in tab.panel_state()["hidden"]["Sterownik"]
    assert panel_cfg.normalize({})["hidden"]["Sterownik"] == panel_cfg.DEFAULT_HIDDEN["Sterownik"]       # the defaults
    assert panel_cfg.normalize({"hidden": {"Sterownik": []}})["hidden"]["Sterownik"] == []              # an explicit choice wins
    tab.shutdown()


def test_help_mode_button_lights_up_and_the_menu_item_is_ticked(app):
    from s7trace.ui import theme as th
    from s7trace.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    assert w.help_btn.objectName() == "helpBtn" and not w.help_btn.isChecked() and not w.act_help_mode.isChecked()
    qss = app.styleSheet()
    assert "QToolButton#helpBtn:checked" in qss and th.DARK["help_on_bg"] in qss                   # orange while the mode is on (theme keys)
    assert "help_on_bg" in th.COLOR_KEYS and "help_on_text" in th.COLOR_KEYS                       # editable: Widok -> Interfejs
    w.help_mode.set_active(True)
    assert w.help_btn.isChecked() and w.act_help_mode.isChecked() and w.act_help_mode.isCheckable()  # the tick in the Pomoc menu
    w.act_help_mode.setChecked(False)                                                              # clicking the item again switches it off
    assert not w.help_mode.active and not w.help_btn.isChecked()
    w.close()


def test_marker_bubble_names_the_description(app):
    from s7trace.core import markers as mk
    from s7trace.ui.markers_ui import marker_tip
    m = mk.Marker(id=1, kind="point", at_us=1_000_000, title="Początek cyklu", description="Trzy sygnały są zaznaczone", notes="A to uwagi")
    t = marker_tip(m)
    assert "<i>Opis:</i> Trzy sygnały są zaznaczone" in t and "<i>Uwagi:</i> A to uwagi" in t


class _FakeClient:
    """snap7 client stand-in: only the listed (rack, slot) pairs are accepted, the others fail with `error`."""
    ok_pairs: set = set()
    error = "Receive error: [WinError 10054] An existing connection was forcibly closed by the remote host"
    attempts: list = []

    def connect(self, host, rack, slot, port=102):
        type(self).attempts.append((rack, slot))
        if (rack, slot) not in type(self).ok_pairs:
            raise RuntimeError(type(self).error)

    def disconnect(self):
        pass


def _fake_snap7(monkeypatch, ok_pairs, error=None):
    import snap7
    from s7trace.core import detect
    _FakeClient.ok_pairs, _FakeClient.attempts = set(ok_pairs), []
    _FakeClient.error = error or "Receive error: [WinError 10054] An existing connection was forcibly closed by the remote host"
    monkeypatch.setattr(snap7.client, "Client", _FakeClient)
    monkeypatch.setattr(detect, "identify_s7", lambda client, res, notes=None: res.info.update(family="S7-1200", model="CPU 1214C"))


def test_read_device_tries_other_rack_slot_pairs(monkeypatch):
    from s7trace.core import detect
    _fake_snap7(monkeypatch, {(0, 1)})
    d = detect.read_device_s7("10.12.92.72", 0, 2)                                            # configured 0/2, the PLC wants 0/1
    assert (d["rack"], d["slot"]) == (0, 1) and d["info"]["family"] == "S7-1200"
    assert _FakeClient.attempts == [(0, 2), (0, 1)]                                           # the configured pair first, then the usual ones
    _fake_snap7(monkeypatch, {(0, 2)})
    assert detect.read_device_s7("10.12.92.72", 0, 2)["slot"] == 2 and _FakeClient.attempts == [(0, 2)]       # no needless attempts


def test_read_device_explains_a_refused_session_in_polish(monkeypatch):
    from s7trace.core import detect
    _fake_snap7(monkeypatch, set())
    with pytest.raises(detect.DeviceReadError) as e:
        detect.read_device_s7("10.12.92.72", 0, 2)
    msg = str(e.value)
    assert "zerwał połączenie" in msg and "PUT/GET" in msg and "0/2, 0/1, 0/0, 1/2, 0/3" in msg and "10054" in msg      # all pairs tried, cause + hints
    assert _FakeClient.attempts == [(0, 2), (0, 1), (0, 0), (1, 2), (0, 3)]
    _fake_snap7(monkeypatch, set(), error="TCP : Connection timed out [WinError 10060]")
    with pytest.raises(detect.DeviceReadError, match="nie odpowiada"):
        detect.read_device_s7("10.12.92.72", 0, 2)
    assert _FakeClient.attempts == [(0, 2)]                                                   # a network problem: other pairs cannot help
    _fake_snap7(monkeypatch, set(), error="[WinError 10061] No connection could be made because the target machine actively refused it")
    with pytest.raises(detect.DeviceReadError, match="odrzucił połączenie"):
        detect.read_device_s7("10.12.92.72", 0, 2)


def test_the_pair_that_worked_becomes_the_setting(app, monkeypatch):
    import time as _t
    from s7trace.core import detect
    _fake_snap7(monkeypatch, {(0, 1)})
    tab = TraceTab(TabConfig(ip="10.12.92.72"), lambda: [])
    tab.show()
    assert (tab.sp_rack.value(), tab.sp_slot.value()) == (0, 2)
    tab.read_device_now()
    end = _t.time() + 10
    while tab._dev_busy and _t.time() < end:
        app.processEvents()
        _t.sleep(0.05)
    assert (tab.sp_rack.value(), tab.sp_slot.value()) == (0, 1) and tab.device is not None
    assert "0/1" in tab.status_msg and "było 0/2" in tab.status_msg
    tab.shutdown()


def test_clock_differences_are_never_huge_numbers_of_seconds():
    from s7trace.core.types import fmt_diff
    assert fmt_diff(2.5) == "+2.5 s" and fmt_diff(-0.04) == "-0.0 s"
    assert fmt_diff(-3155760944.4) == "-36525 d 00:15:44" or fmt_diff(-3155760944.4).startswith("-36")
    assert fmt_diff(3 * 86400 + 7200) == "+3 d 02:00:00" and fmt_diff(-3725) == "-01:02:05"


def test_table_cells_get_the_standard_left_indent(app):
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
    from s7trace.ui import theme as th
    t = QTableWidget(2, 2)
    t.setItem(0, 0, QTableWidgetItem("Wartość"))
    t.show()
    app.processEvents()
    assert isinstance(t.itemDelegate(), th.IndentDelegate) and th.CELL_INDENT >= 10           # one rule for every table, not only the QSS
    img = t.viewport().grab().toImage()
    row = range(2, t.rowHeight(0) - 2)
    bg = img.pixelColor(3, 3).lightness()
    first_ink = min(x for x in range(3, 90) if any(abs(img.pixelColor(x, y).lightness() - bg) > 60 for y in row))     # first pixel of the text
    assert first_ink >= th.CELL_INDENT - 2
    t.close()


def test_status_bar_menu_alignment_and_the_interface_file(app, tmp_path):
    from PySide6.QtWidgets import QMenu
    from s7trace.ui import theme as th
    from s7trace.ui.interface_dialog import InterfaceDialog
    from s7trace.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    tab = w.tabs.widget(0)
    lbl = tab.lbl_status
    lbl.setText("Krótki tekst")
    app.processEvents()
    assert lbl.align() == "right" and lbl._lbl.x() + lbl._lbl.sizeHint().width() >= lbl.width() - 2          # the default: to the right
    seen = []
    lbl.menuRequested.connect(lambda pos: seen.append(pos))                                                  # right click asks for the menu
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication
    QApplication.sendEvent(lbl, QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5), QPoint(5, 5)))
    names = [a.text() for a in tab._status_popup.actions()]
    assert len(seen) == 1 and "Kolor tła paska…" in names and "Justowanie tekstu" in names and "Maksymalna liczba wierszy w pasku" in names
    just = next(a for a in tab._status_popup.actions() if a.text() == "Justowanie tekstu")                 # a submenu: do lewej / do prawej
    assert [a.text() for a in just.menu().actions()] == ["do lewej", "do prawej"]
    left = just.menu().actions()[0]
    left.trigger()                                                                                           # the menu item itself
    assert lbl.align() == "left" and w.ui["theme"]["status_align"] == "left"
    tab._status_popup.close()
    w._edit_theme({"status_align": "left", "status_lines": 3, "status_bg": "#112233", "profile": "custom"})   # what the menu items do
    app.processEvents()
    assert lbl.align() == "left" and lbl._lbl.x() == 0 and lbl.max_lines() == 3
    assert w.ui["theme"]["status_align"] == "left" and w.ui["theme"]["status_lines"] == 3 and w.ui["theme"]["status_bg"] == "#112233"
    p = str(tmp_path / "pasek.json")
    th.save_profile(p, w.ui["theme"])                                                                        # saved in the interface file …
    assert '  "status_align": "left",' in open(p, encoding="utf-8").read().splitlines()
    assert th.load_profile(p)["status_align"] == "left"                                                      # … and read back
    d = InterfaceDialog(w.ui["theme"], lambda t: None)                                                       # the Interface window has the setting too
    assert d.status_align.currentData() == "left"
    d.status_align.setCurrentIndex(d.status_align.findData("right"))
    assert d.theme["status_align"] == "right"
    d.close()
    w.close()


def test_every_table_follows_the_standard_look_and_resizes(app):
    from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem
    from s7trace.ui import theme as th
    from s7trace.ui.table_kit import standard
    t = QTableWidget(3, 3)
    t.setHorizontalHeaderLabels(["A", "Bardzo długi tytuł kolumny", "C"])
    standard(t)
    for r in range(3):
        t.setItem(r, 0, QTableWidgetItem("2026-10-05 11:44:44"))
    t.resize(600, 200)
    t.show()
    app.processEvents()
    hh = t.horizontalHeader()
    assert hh.sectionResizeMode(0) == QHeaderView.Interactive and hh.stretchLastSection() and t.alternatingRowColors()   # draggable borders
    assert t.columnWidth(0) >= 100 and not t.wordWrap()                                                                   # the first fill fits the content
    t.setColumnWidth(0, 250)
    assert t.columnWidth(0) == 250
    assert th.alt_row("#262626") != "#262626" and th.alt_row("#ffffff") != "#ffffff"                                     # light / dark rows
    assert "alternate-background-color: " + th.alt_row(th.DARK["table_bg"]) in app.styleSheet()
    t.close()
    from s7trace.ui.store_dialog import StoreImportDialog
    from s7trace.core import store as st
    d = StoreImportDialog(st.StoreConfig(kind="sqlite"), can_load=False)
    assert d.table.horizontalHeader().sectionResizeMode(1) == QHeaderView.Interactive and d.table.alternatingRowColors()   # 'Przegląd nagrań'
    d.close()


def test_table_colours_are_interface_settings(app, tmp_path):
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
    from s7trace.ui import theme as th
    from s7trace.ui.interface_dialog import InterfaceDialog
    keys = ("header_bg", "header_text", "row_odd_bg", "row_odd_text", "row_even_bg", "row_even_text", "table_border")
    assert all(k in th.COLOR_KEYS for k in keys)                                           # editable in Widok -> Interfejs, one button each
    d = InterfaceDialog(th.DARK, lambda t: None)
    assert all(k in d._buttons for k in keys)
    d.close()
    t = {**th.DARK, "profile": "custom", "row_odd_bg": "#101010", "row_even_bg": "#202020", "row_even_text": "#00ff00", "table_border": "#ff0000", "header_text": "#ffff00"}
    th.apply_theme(app, t)
    qss = app.styleSheet()
    assert "background: #101010" in qss and "alternate-background-color: #202020" in qss and "gridline-color: #ff0000" in qss and "color: #ffff00" in qss
    assert th.ROW_TEXT["even"] == "#00ff00"                                                # the font of the even rows (drawn by the delegate)
    p = str(tmp_path / "tab.json")
    th.save_profile(p, t)                                                                  # in the interface file, one parameter per line
    assert '  "row_even_bg": "#202020",' in open(p, encoding="utf-8").read().splitlines()
    assert th.load_profile(p)["table_border"] == "#ff0000"
    old = th.normalize({"profile": "custom", "table_bg": "#ffffff", "table_text": "#111111", "text": "#222222", "window_bg": "#f0f0f0"})   # a file without the new keys
    assert old["row_odd_bg"] == "#ffffff" and old["row_odd_text"] == "#111111" and old["header_text"] == "#222222"
    th.apply_theme(app, th.DARK)


def test_header_click_sorts_tables_and_the_signal_list(app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableWidget
    from s7trace.core.types import Signal
    from s7trace.ui import table_kit as tk
    from s7trace.ui.signals_dialog import SignalsDialog
    assert tk.natural_key("2 min 32 s") < tk.natural_key("15 min 53 s") and tk.natural_key("DB2") < tk.natural_key("DB10")
    t = QTableWidget(0, 2)
    tk.standard(t, sort=True)
    tk.begin_fill(t)
    t.setRowCount(3)
    for r, v in enumerate(["DB10", "DB2", "DB1"]):
        t.setItem(r, 0, tk.SortItem(v))
        t.setItem(r, 1, tk.SortItem(str(r)))
    tk.end_fill(t)
    t.sortByColumn(0, Qt.AscendingOrder)
    assert [t.item(r, 0).text() for r in range(3)] == ["DB1", "DB2", "DB10"]                  # natural order
    assert [tk.src(t, r) for r in range(3)] == [2, 1, 0]                                      # which of the original rows each one is
    sigs = [Signal(name=n, source="DB", dtype="INT", db=1, byte=b) for n, b in (("S3", 6), ("S1", 2), ("S2", 4))]
    d = SignalsDialog(sigs, False, lambda: [])
    d.sort_by(0 if False else 2)                                                              # 'Nazwa'
    assert [s.name for s in d.signals()] == ["S1", "S2", "S3"]
    d.sort_by(2)                                                                              # second click: descending
    assert [s.name for s in d.signals()] == ["S3", "S2", "S1"]
    d.close()
    dl = SignalsDialog(sigs, True, lambda: [])                                                # while running the order is locked
    dl.sort_by(2)
    assert [s.name for s in dl.signals()] == ["S3", "S1", "S2"]
    dl.close()


def test_method_row_says_what_automatic_picked(app):
    tab = TraceTab(TabConfig(), lambda: [])
    assert tab.lbl_method.text() == "Automatycznie (rozpoznaj)"
    tab.run_method, tab.state = "s7", "running"
    tab.update_method_label()
    assert tab.lbl_method.text() == "Auto: S7comm (snap7, PUT/GET)"
    tab.state = "stopped"
    tab.update_method_label()
    assert tab.lbl_method.text() == "Automatycznie (rozpoznaj)"
    tab.cfg.conn_type = "opcua"
    tab.state = "running"
    tab.update_method_label()
    assert tab.lbl_method.text() == "OPC UA"                                                  # a manual choice is shown as it is
    tab.state = "stopped"
