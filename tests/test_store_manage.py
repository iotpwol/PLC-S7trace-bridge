"""Przegląd nagrań: titles, owner, search / filter, trash, deleting, retention, name prompts, leftover buffers."""
import sqlite3
import time
from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from s7trace.core import store
from s7trace.core.store import DbRecorder, StoreConfig
from s7trace.core.types import Signal
from s7trace.ui import store_dialog as sd
from s7trace.ui.store_dialog import RecInfoDialog, SpoolDialog, StoreDialog, StoreImportDialog
from s7trace.ui.theme import apply_dark
from test_round5 import _tab
from test_store import INFLUX_CFGS, FakeInflux

DAY = 86_400_000_000


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


@pytest.fixture
def yes(monkeypatch):
    """Every confirmation box answers Yes (and the question is remembered)."""
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: asked.append("W:" + str(a[2])) or QMessageBox.Ok))
    return asked


def make_db(tmp_path, rows=(("Rozruch pieca", "po remoncie", "piec, rozruch", None, 3.0),
                           ("Test pompy", "", "pompa", "other", 2.0),
                           ("Awaria", "zatrzymanie linii", "awaria", None, 1.0))):
    """A SQLite file with a few recordings: (title, notes, tags, owner override, days ago)."""
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "m.db"), mode="all")
    ids = []
    for title, notes, tags, owner, ago in rows:
        start = datetime.fromtimestamp(time.time() - ago * 86400)
        rec = DbRecorder(cfg, [Signal(name="A")], start, {"title": title, "notes": notes, "tags": tags, "conf": "L1",
                                                          "ip": "10.1.1.1", "tab": "T"})
        for i in range(30):
            rec.write(i * 1.0, [float(i)])
        rec.close()
        ids.append(rec.session)
        if owner:
            db = sqlite3.connect(cfg.sqlite_path)
            db.execute("UPDATE sessions SET owner=?, computer='OTHER-PC' WHERE id=?", (owner, rec.session))
            db.commit()
            db.close()
    return cfg, ids


def dialog(cfg, tmp_path, **kw):
    sd.data_dir = lambda: str(tmp_path)
    d = StoreImportDialog(cfg, base_dir=str(tmp_path), **kw)
    d.refresh()
    return d


def titles(d):
    return [d.cell(r, "title") for r in range(d.table.rowCount())]


# ------------------------------------------------------------------ overview
def test_overview_shows_the_description_and_sorts(app, tmp_path):
    cfg, ids = make_db(tmp_path)
    d = dialog(cfg, tmp_path, can_load=True)
    d.cb_user.setCurrentIndex(d.cb_user.findData("all"))
    assert d.table.rowCount() == 3
    assert titles(d) == ["Awaria", "Test pompy", "Rozruch pieca"]                 # newest first
    r = titles(d).index("Rozruch pieca")
    assert d.cell(r, "tags") == "piec, rozruch" and d.cell(r, "notes") == "po remoncie"
    assert d.cell(r, "owner") == store.current_user() and d.cell(r, "computer")
    assert d.cell(r, "events") and d.cell(r, "dur").endswith("s")                  # entries and duration are listed
    d.table.sortByColumn([k for k, _ in d.COLS].index("title"), sd.Qt.AscendingOrder)
    assert titles(d) == sorted(titles(d), key=str.lower)
    assert "Nagrań w bazie: <b>3</b>" in d.lbl.text()


def test_overview_filters_by_user_and_search(app, tmp_path):
    cfg, ids = make_db(tmp_path)
    d = dialog(cfg, tmp_path)
    assert d.cb_user.currentData() == "mine" and sorted(titles(d)) == ["Awaria", "Rozruch pieca"]    # default: mine
    d.cb_user.setCurrentIndex(d.cb_user.findData("all"))
    assert d.table.rowCount() == 3
    d.cb_user.setCurrentIndex(d.cb_user.findData("u:other"))
    assert titles(d) == ["Test pompy"]
    d.cb_user.setCurrentIndex(d.cb_user.findData("all"))
    d.ed_search.setText("linii")                                                      # found in the notes
    assert titles(d) == ["Awaria"]
    d.ed_search.setText("POMPA")                                                      # tags, case-insensitive
    assert titles(d) == ["Test pompy"]
    d.ed_search.setText("nic takiego")
    assert d.table.rowCount() == 0
    cfg2 = StoreConfig(kind="sqlite", sqlite_path=cfg.sqlite_path, view_scope="all")
    d2 = StoreImportDialog(cfg2, base_dir=str(tmp_path))
    assert d2.cb_user.currentData() == "all"                                          # the setting is the default filter


def test_properties_edit_changes_the_database(app, tmp_path, monkeypatch):
    cfg, ids = make_db(tmp_path)
    d = dialog(cfg, tmp_path)
    d.table.selectRow(titles(d).index("Awaria"))
    monkeypatch.setattr(RecInfoDialog, "exec", lambda self: self.ed_title.setText("Awaria linii 2") or
                        self.ed_tags.setText("awaria, pilne") or self.ed_notes.setPlainText("nowa uwaga") or True)
    d.edit_properties()
    assert "Awaria linii 2" in titles(d)
    b = store.open_backend(cfg)
    s = next(x for x in b.sessions() if x["title"] == "Awaria linii 2")
    assert s["tags"] == "awaria, pilne" and s["notes"] == "nowa uwaga"
    b.close()


# ------------------------------------------------------------------ trash, deleting, rights
def test_delete_goes_to_the_trash_and_can_be_restored(app, tmp_path, yes):
    cfg, ids = make_db(tmp_path)
    d = dialog(cfg, tmp_path)
    d.table.selectRow(titles(d).index("Awaria"))
    d.delete_selected()
    assert "Przenieść do kosza" in yes[-1] and "30 dni" in yes[-1]
    assert titles(d) == ["Rozruch pieca"]
    d.chk_trash.setChecked(True)
    assert titles(d) == ["Awaria"] and d.btn_del.text() == "Usuń trwale" and d.btn_restore.isVisibleTo(d)
    assert not d.btn_load.isEnabled()                                                  # a deleted recording is not loaded
    d.table.selectRow(0)
    d.restore_selected()
    d.chk_trash.setChecked(False)
    assert sorted(titles(d)) == ["Awaria", "Rozruch pieca"]
    d.table.selectRow(titles(d).index("Awaria"))
    d.delete_selected()
    d.chk_trash.setChecked(True)
    d.table.selectRow(0)
    d.delete_selected()                                                                # from the trash: for good
    assert "TRWALE" in yes[-1] and d.table.rowCount() == 0
    b = store.open_backend(cfg)
    assert [x["title"] for x in b.sessions()] == ["Test pompy", "Rozruch pieca"] or \
        sorted(x["title"] for x in b.sessions()) == ["Rozruch pieca", "Test pompy"]
    assert ids[2] not in b.stats()                                                     # the samples are gone, not just hidden
    b.close()


def test_without_a_trash_the_delete_is_immediate(app, tmp_path, yes):
    cfg, ids = make_db(tmp_path)
    cfg.trash_days = 0
    d = dialog(cfg, tmp_path)
    d.table.selectRow(titles(d).index("Awaria"))
    d.delete_selected()
    assert "TRWALE" in yes[-1]
    b = store.open_backend(cfg)
    assert ids[2] not in [x["id"] for x in b.sessions()]
    b.close()


def test_other_users_recordings_are_protected_unless_allowed(app, tmp_path, yes):
    cfg, ids = make_db(tmp_path)
    d = dialog(cfg, tmp_path)
    d.cb_user.setCurrentIndex(d.cb_user.findData("all"))
    d.table.selectRow(titles(d).index("Test pompy"))
    assert not d.btn_del.isEnabled() and not d.btn_props.isEnabled()
    d.delete_selected()
    assert not yes                                                                      # nothing was even asked
    cfg.delete_others = True
    d2 = dialog(cfg, tmp_path)
    d2.cb_user.setCurrentIndex(d2.cb_user.findData("all"))
    d2.table.selectRow(titles(d2).index("Test pompy"))
    assert d2.btn_del.isEnabled() and d2.btn_props.isEnabled()
    d2.delete_selected()
    assert "Test pompy" not in titles(d2)


def test_trash_is_emptied_after_the_configured_days_and_retention_moves_old_ones(app, tmp_path):
    cfg, ids = make_db(tmp_path)
    cfg.trash_days, cfg.retention_days = 7, 2
    b = store.open_backend(cfg)
    b.update_session(ids[0], {"deleted_us": int(time.time() * 1e6) - 10 * DAY})        # 10 days in the trash: purged
    b.update_session(ids[2], {"deleted_us": int(time.time() * 1e6) - 1 * DAY})         # 1 day: stays
    b.close()
    d = dialog(cfg, tmp_path)
    b = store.open_backend(cfg)
    left = {x["id"]: x for x in b.sessions()}
    assert ids[0] not in left and left[ids[2]]["deleted_us"]
    assert left[ids[1]]["deleted_us"] is None                                          # (other's recording, 2 days old: kept)
    b.close()
    cfg2, ids2 = make_db(tmp_path / "r")                                               # own recordings 3 days and 1 day old
    cfg2.retention_days = 2
    dialog(cfg2, tmp_path / "r")
    b = store.open_backend(cfg2)
    st = {x["id"]: x["deleted_us"] for x in b.sessions()}
    assert st[ids2[0]] and st[ids2[2]] is None                                         # only the 3-day-old one was moved
    b.close()


def test_empty_trash(app, tmp_path, yes):
    cfg, ids = make_db(tmp_path)
    d = dialog(cfg, tmp_path)
    for title in ("Awaria", "Rozruch pieca"):
        d.table.selectRow(titles(d).index(title))
        d.delete_selected()
    d.chk_trash.setChecked(True)
    assert d.table.rowCount() == 2 and d.btn_empty.isEnabled()
    d.empty_trash()
    assert d.table.rowCount() == 0
    b = store.open_backend(cfg)
    assert [x["title"] for x in b.sessions()] == ["Test pompy"]
    b.close()


# ------------------------------------------------------------------ name prompts in the tab
def _rec_tab(tmp_path, ask):
    tab = _tab()
    tab.cfg.store = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "t.db"), title_ask=ask, batch_s=0.05)
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("sqlite"))
    tab._run_signals = list(tab.cfg.signals)
    tab.start_wall = datetime.now()
    tab.state = "running"
    return tab


def _titles_in(cfg):
    b = store.open_backend(cfg)
    try:
        return [x["title"] for x in b.sessions()]
    finally:
        b.close()


def test_ask_at_the_start_then_record(app, tmp_path, monkeypatch):
    tab = _rec_tab(tmp_path, "start")
    seen = {}

    def fake_exec(self):
        seen["heading"] = self.ed_title.text()
        self.ed_title.setText("Z początku")
        return True
    monkeypatch.setattr(RecInfoDialog, "exec", fake_exec)
    tab.btn_rec.setChecked(True)
    assert isinstance(tab.recorder, DbRecorder) and tab._info_dlg is None
    tab.btn_rec.setChecked(False)
    assert _titles_in(tab.cfg.store) == ["Z początku"]
    tab.shutdown()


def test_cancel_at_the_start_means_no_recording(app, tmp_path, monkeypatch):
    tab = _rec_tab(tmp_path, "start")
    monkeypatch.setattr(RecInfoDialog, "exec", lambda self: False)
    tab.btn_rec.setChecked(True)
    assert tab.recorder is None and not tab.btn_rec.isChecked()
    tab.shutdown()


def test_ask_during_opens_a_non_modal_window_and_applies_the_answer(app, tmp_path):
    tab = _rec_tab(tmp_path, "during")
    tab.btn_rec.setChecked(True)
    assert tab.recorder is not None and tab._info_dlg is not None and not tab._info_dlg.isModal()
    tab.recorder.write(0.0, [1.0, 2.0])                                                  # recording is already running
    tab._info_dlg.ed_title.setText("W trakcie")
    tab._info_dlg.ed_tags.setText("t1")
    tab._info_dlg.accept()
    time.sleep(0.4)
    b = store.open_backend(tab.cfg.store)
    assert b.sessions()[0]["title"] == "W trakcie" and b.sessions()[0]["tags"] == "t1"
    b.close()
    tab.btn_rec.setChecked(False)
    tab.shutdown()


def test_ask_at_the_end(app, tmp_path, monkeypatch):
    tab = _rec_tab(tmp_path, "end")
    tab.btn_rec.setChecked(True)
    assert tab._info_dlg is None                                                         # nothing asked while recording
    tab.recorder.write(0.0, [1.0, 2.0])
    monkeypatch.setattr(RecInfoDialog, "exec", lambda self: self.ed_title.setText("Na końcu") or True)
    tab.btn_rec.setChecked(False)
    assert _titles_in(tab.cfg.store) == ["Na końcu"]
    tab.shutdown()


def test_never_ask(app, tmp_path, monkeypatch):
    tab = _rec_tab(tmp_path, "off")
    monkeypatch.setattr(RecInfoDialog, "exec", lambda self: pytest.fail("no question expected"))
    tab.btn_rec.setChecked(True)
    assert tab._info_dlg is None
    tab.btn_rec.setChecked(False)
    assert _titles_in(tab.cfg.store) == [""]
    tab.shutdown()


def test_title_survives_a_restart_of_the_recording_for_new_signals(app, tmp_path, monkeypatch):
    tab = _rec_tab(tmp_path, "start")
    monkeypatch.setattr(RecInfoDialog, "exec", lambda self: self.ed_title.setText("Jeden tytuł") or True)
    tab.btn_rec.setChecked(True)
    tab._close_recorder()
    tab._open_recorder(ask=False)                                                         # what adding a signal does
    assert tab.recorder._meta["title"] == "Jeden tytuł"
    tab.btn_rec.setChecked(False)
    tab.shutdown()


# ------------------------------------------------------------------ settings dialog + menu
def test_store_dialog_has_the_user_tab(app):
    d = StoreDialog(StoreConfig(kind="sqlite", title_ask="end", view_scope="all", delete_others=True, sqlite_shared=True,
                                trash_days=5, retention_days=90), "sqlite")
    c = d.config()
    assert (c.title_ask, c.view_scope, c.delete_others, c.sqlite_shared, c.trash_days, c.retention_days) == \
        ("end", "all", True, True, 5, 90)
    d.cb_title.setCurrentIndex(d.cb_title.findData("off"))
    d.chk_others.setChecked(False)
    d.params["trash_days"].setValue(0)
    c = d.config()
    assert c.title_ask == "off" and not c.delete_others and c.trash_days == 0
    n = StoreDialog(StoreConfig(), "influx2")
    assert n.config().sqlite_shared is False and n.chk_shared.parent() is None                # (SQLite only)


def test_menu_entries(app, tmp_path):
    from s7trace.ui.main_window import MainWindow
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    texts = [a.text() for m in w.menuBar().actions() if m.menu() for a in m.menu().actions()]
    assert any("Przegląd nagrań" in t for t in texts) and any("Zaległe bufory" in t for t in texts)
    w.close()


# ------------------------------------------------------------------ leftover disk buffers
def test_spool_dialog_lists_delivers_and_removes(app, tmp_path, yes):
    srv = FakeInflux()
    try:
        cfg = StoreConfig(url=srv.url, mode="all", **INFLUX_CFGS[2])
        meta = {"id": "S-LEFT", "name": "n", "title": "z bufora", "start_us": store.to_us(datetime(2026, 10, 3, 8), 0),
                "mode": "all", "signals": [Signal(name="A").to_dict()], "fields": ["A"]}
        folder = tmp_path / "spool"
        sp = store.Spool(str(folder / "spool_S-LEFT.db"), 10)
        sp.set_meta(meta, cfg.describe())
        sp.add([(store.to_us(datetime(2026, 10, 3, 8), i), {0: float(i)}) for i in range(20)])
        sp.close()
        other = store.Spool(str(folder / "spool_S-OTHER.db"), 10)
        other.set_meta({**meta, "id": "S-OTHER"}, "InfluxDB 2.x inny serwer")
        other.add([(1, {0: 1.0})])
        other.close()
        items = store.scan_spools(str(tmp_path))
        assert [i["rows"] for i in items] == [20, 1] or sorted(i["rows"] for i in items) == [1, 20]
        d = SpoolDialog(cfg, str(tmp_path))
        assert d.table.rowCount() == 2
        mine = next(r for r in range(2) if d.items[r]["meta"]["id"] == "S-LEFT")
        d.table.selectRow(mine)
        assert d.btn_send.isEnabled()
        d.send()
        assert len(srv.select("s7trace")) == 20 and "OK" in d.lbl.text()
        assert d.table.rowCount() == 1 and not (folder / "spool_S-LEFT.db").exists()
        d.table.selectRow(0)
        assert not d.btn_send.isEnabled()                                                  # another server: cannot be sent from here
        d.remove()
        assert d.table.rowCount() == 0 and not list(folder.glob("spool_*.db"))
    finally:
        srv.close()


def test_the_overview_announces_leftover_buffers(app, tmp_path):
    srv = FakeInflux()
    try:
        cfg = StoreConfig(url=srv.url, mode="all", **INFLUX_CFGS[2])
        sp = store.Spool(str(tmp_path / "spool" / "spool_X.db"), 10)
        sp.set_meta({"id": "X", "start_us": 1, "signals": [], "fields": []}, cfg.describe())
        sp.add([(1, {0: 1.0})])
        sp.close()
        d = dialog(cfg, tmp_path)
        assert "Zaległe bufory zapisu: 1" in d.lbl.text() and not d.btn_spool.isHidden()
    finally:
        srv.close()


def test_a_running_recording_cannot_be_deleted_in_the_overview(app, tmp_path, yes):
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "live.db"), mode="all", batch_s=0.05)
    rec = DbRecorder(cfg, [Signal(name="A")], datetime.now(), {"title": "trwa"})
    rec.write(0.0, [1.0])
    time.sleep(0.3)
    d = dialog(cfg, tmp_path)
    d.table.selectRow(0)
    assert not d.btn_del.isEnabled() and not d.btn_props.isEnabled()
    d.delete_selected()
    assert not yes
    rec.close()
    d.refresh()
    d.table.selectRow(0)
    assert d.btn_del.isEnabled()


def test_grouping_by_days(app, tmp_path):
    cfg, ids = make_db(tmp_path, rows=(("A1", "", "", None, 3.0), ("A2", "", "", None, 3.0), ("B", "", "", None, 1.0)))
    d = dialog(cfg, tmp_path)
    assert d.table.rowCount() == 3 and not d.chk_group.isChecked()
    d.chk_group.setChecked(True)
    assert d.table.rowCount() == 5                                                      # 2 day headers + 3 recordings
    assert d.table.item(0, 0).text().startswith(f"{datetime.fromtimestamp(time.time() - 86400):%Y-%m-%d}") and "1 nagr." in d.table.item(0, 0).text()
    assert "2 nagr." in d.table.item(2, 0).text() and d.table.columnSpan(0, 0) == len(d.COLS)
    assert d.cell(1, "title") == "B" and sorted(d.cell(r, "title") for r in (3, 4)) == ["A1", "A2"]
    assert [s["title"] for s in d._picked()] == ["B"]                                    # the first recording is selected
    d.table.selectRow(2)                                                                 # a day header cannot be selected
    assert not (d.table.item(2, 0).flags() & sd.Qt.ItemIsSelectable)
    d.table.selectRow(3)
    assert len(d._picked()) == 1 and d.btn_del.isEnabled()
    d.chk_group.setChecked(False)
    assert d.table.rowCount() == 3 and d.table.isSortingEnabled()
