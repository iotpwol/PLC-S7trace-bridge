"""Every marker knows the recording it belongs to (column 'Zapis'); markers that exist only for a chart buffer are offered for deletion
when the buffer goes away; deleting a recording asks about its markers."""
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from s7trace.core import markers as mk
from s7trace.ui import markers_ui as mu
from test_markers_ui import _accept, _pending, app     # noqa: F401 (fixtures)
from test_rec_marks_ui import db_tab, feed, pump, us


def answer(monkeypatch, which):
    """The question box is answered by clicking the button 0 = delete ('Usuń…'), 1 = keep ('Zostaw…'), 2 = back / cancel;
    the texts shown are collected."""
    seen = []
    starts = (("Usuń",), ("Zostaw",), ("Wróć", "Anuluj"))[which]

    def ex(self):
        seen.append(self.text())
        next(b for b in self.buttons() if b.text().startswith(starts)).click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", ex)
    return seen


def save(tab, monkeypatch):
    _pending(monkeypatch, "save")                                    # the window that lists what is going to be saved says 'Zapisz'
    return tab.mk.save()


def place(tab, t, **kw):
    return tab.mk.add_at_us(us(tab, t), **kw)


def test_marker_gets_the_recording_of_the_time_it_was_put_at(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    tab.mk._store = mk.MarkerStore(str(tmp_path / "m.db"))
    _accept(monkeypatch, title="x")
    feed(tab, 0.0, 20.0)
    before = place(tab, 5.0)                                         # no REC yet: only the chart buffer
    assert before.rec_id == ""
    tab.btn_rec.setChecked(True)
    app.processEvents()
    sid = tab.recorder.session
    feed(tab, 20.0, 24.0)
    during = place(tab, 22.0)                                        # REC runs: the recording
    assert during.rec_id == sid
    tab.btn_rec.setChecked(False)
    app.processEvents()
    after = place(tab, 23.0)                                         # REC is off now, but the time is inside the recording
    outside = place(tab, 10.0)
    assert after.rec_id == sid and outside.rec_id == ""
    tab.btn_rec.setChecked(False)
    tab.shutdown()


def test_manual_area_and_moved_start_pull_markers_into_the_recording(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    tab.mk._store = mk.MarkerStore(str(tmp_path / "m.db"))
    _accept(monkeypatch, title="x")
    feed(tab, 0.0, 20.0)
    inside, outside = place(tab, 8.0), place(tab, 15.0)
    assert save(tab, monkeypatch)                                             # both are in the file now (buffer only)
    unsaved = place(tab, 9.0)                                        # ... and one is still a draft
    assert inside.rec_id == "" and unsaved.rec_id == ""
    tab.mk.rec.m.place_manual(5.0)
    tab.mk.rec.m.place_manual(12.0)
    tab.mk.rec.save_manual(1, wait=True)
    assert pump(lambda: tab.mk.rec.m.manual_get(1)["saved"] not in ("", "zapisuję…"))
    st = tab.mk.store
    sid = st.get(next(m.id for m in st.search() if m.at_us == inside.at_us)).rec_id
    assert sid and st.get(next(m.id for m in st.search() if m.at_us == outside.at_us)).rec_id == ""
    assert tab.mk.draft.new[unsaved.id].rec_id == sid                 # the unsaved one follows too
    # a Start REC moved earlier / later: the markers follow the data
    tab.btn_rec.setChecked(True)
    app.processEvents()
    feed(tab, 20.0, 22.0)
    real = tab.recorder.session
    m14 = tab.mk.store.add(us(tab, 14.0), conn=tab.mk.key())
    assert m14.rec_id == ""
    assert tab.mk.rec.change_start.__name__                           # (the dialog itself is not driven here)
    tab.mk.link_range(real, us(tab, 13.0), us(tab, 16.0))
    assert tab.mk.store.get(m14.id).rec_id == real
    tab.mk.unlink_range(real, us(tab, 13.0), us(tab, 15.0))
    assert tab.mk.store.get(m14.id).rec_id == ""
    tab.btn_rec.setChecked(False)
    tab.shutdown()


def test_the_list_shows_the_recording_column_and_filters(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    tab.mk._store = mk.MarkerStore(str(tmp_path / "m.db"))
    _accept(monkeypatch, title="x")
    feed(tab, 0.0, 20.0)
    a = place(tab, 3.0)
    tab.btn_rec.setChecked(True)
    app.processEvents()
    feed(tab, 20.0, 22.0)
    b = place(tab, 21.0)
    save(tab, monkeypatch)
    d = mu.MarkersDialog(tab.mk)
    d.refresh()
    col = d.COLS.index("Zapis")
    texts = {d.table.item(r, 0).text(): d.table.item(r, col).text() for r in range(d.table.rowCount())}
    assert sorted(texts.values()) == sorted([mu.BUFFER_LABEL, tab.recorder.session])
    d.cb_rec.setCurrentIndex(d.cb_rec.findData("buffer"))
    assert d.table.rowCount() == 1 and d.table.item(0, col).text() == mu.BUFFER_LABEL
    d.cb_rec.setCurrentIndex(d.cb_rec.findData("rec"))
    assert d.table.rowCount() == 1 and d.table.item(0, col).text() == tab.recorder.session
    assert d.btn_orph.isEnabled() and "(1)" in d.btn_orph.text()
    d.close()
    tab.btn_rec.setChecked(False)
    tab.shutdown()


def test_buffer_markers_are_deleted_when_the_buffer_goes_away(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    tab.mk._store = mk.MarkerStore(str(tmp_path / "m.db"))
    _accept(monkeypatch, title="x")
    feed(tab, 0.0, 20.0)
    place(tab, 3.0)
    place(tab, 4.0)
    save(tab, monkeypatch)
    st = tab.mk.store
    assert st.count() == 2
    seen = answer(monkeypatch, 2)                                    # 'Wróć' / 'Anuluj Start'
    assert tab.mk.confirm_buffer("close") is False and st.count() == 2 and "2" in seen[-1]
    answer(monkeypatch, 1)                                           # 'Zostaw'
    assert tab.mk.confirm_buffer("close") is True and st.count() == 2
    assert tab.mk.confirm_buffer("close", shared=True) is True       # another tab has the same connection: nothing is asked
    answer(monkeypatch, 0)                                           # 'Usuń znaczniki'
    assert tab.mk.confirm_buffer("start") is True and st.count() == 0
    assert tab.mk.confirm_buffer("close") is True                    # nothing left: no question
    tab.shutdown()


def test_start_asks_and_can_be_cancelled(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    tab.state = "stopped"
    tab.cfg.conn_type = "s7"                                         # no wizard / probing of the network
    tab.btn_reset.set_auto(True)                                     # Auto-Reset: a Start clears the chart (otherwise it would continue it)
    tab.mk._store = mk.MarkerStore(str(tmp_path / "m.db"))
    _accept(monkeypatch, title="x")
    feed(tab, 0.0, 10.0)
    place(tab, 3.0)
    save(tab, monkeypatch)
    seen = answer(monkeypatch, 2)
    n = len(tab.buffer)
    tab.start()
    assert seen and "Starcie" in seen[-1]
    assert tab.state == "stopped" and len(tab.buffer) == n and tab.mk.store.count() == 1     # cancelled: the old chart stays
    tab.shutdown()


def test_delete_buffer_only_button_leaves_open_charts(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    st = tab.mk._store = mk.MarkerStore(str(tmp_path / "m.db"))
    feed(tab, 0.0, 10.0)
    key = tab.mk.key()
    st.add(us(tab, 1.0), conn=key)                                    # of the open chart
    st.add(us(tab, 1.0), conn="Stara linia")                          # left over by an earlier run
    st.add(us(tab, 2.0), conn="Stara linia", rec_id="20260101-000000-abcd")      # belongs to a recording
    d = mu.MarkersDialog(tab.mk)
    d.refresh()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    d.delete_buffer_only()
    assert sorted((m.conn, bool(m.rec_id)) for m in st.search()) == [(key, False), ("Stara linia", True)]
    d.close()
    tab.shutdown()


def test_deleting_a_recording_for_good_asks_about_its_markers(app, tmp_path, monkeypatch):
    from test_store_manage import make_db, dialog
    cfg, ids = make_db(tmp_path)
    st = mk.MarkerStore(str(tmp_path / "mk.db"))
    monkeypatch.setattr(mk, "default_store", lambda: st)
    for rid in (ids[0], ids[0], ids[1]):
        st.add(1_800_000_000_000_000, conn="L1", rec_id=rid)
    d = dialog(cfg, tmp_path)
    d.cb_user.setCurrentIndex(d.cb_user.findData("all"))
    sel = [s for s in d.all if s["id"] == ids[0]]
    seen = answer(monkeypatch, 2)                                    # 'Anuluj': nothing is deleted
    d._apply(sel, True)
    assert st.count() == 3 and any(s["id"] == ids[0] for s in d.all) and "2" in seen[-1]
    answer(monkeypatch, 1)                                           # 'Zostaw znaczniki'
    d._apply(sel, True)
    assert st.count() == 3 and not any(s["id"] == ids[0] for s in d.all)
    sel = [s for s in d.all if s["id"] == ids[1]]
    answer(monkeypatch, 0)                                           # 'Usuń też znaczniki'
    d._apply(sel, True)
    assert st.count() == 2 and all(m.rec_id == ids[0] for m in st.search())      # only those of the deleted recording went
