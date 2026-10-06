"""Where the trigger writes its snapshots: CSV file, or a database - the general one (as REC) or a separate one."""
import os
import time

import pytest
from PySide6.QtWidgets import QApplication

from s7trace.core import rec_ops, store
from s7trace.core import trigger as trg
from s7trace.core.config import TabConfig
from s7trace.core.store import StoreConfig
from s7trace.ui.theme import apply_dark
from test_rec_marks_ui import db_tab, feed, pump


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def test_snapshot_store_general_or_separate():
    base = StoreConfig(kind="sqlite", sqlite_path="rec.db", measurement="m", table="t", rotate_mb=5, rotate_daily=True)
    g = rec_ops.snapshot_store(base, "sqlite", "shared")
    assert g.kind == "sqlite" and g.sqlite_path == "rec.db" and g.rotate_mb == 5                      # the general database = the settings of REC
    o = rec_ops.snapshot_store(base, "sqlite", "own", r"C:\x\snapshots.db")
    assert o.sqlite_path == r"C:\x\snapshots.db" and o.rotate_mb == 0 and not o.rotate_daily and base.sqlite_path == "rec.db"
    i = rec_ops.snapshot_store(base, "influx1", "own")
    assert i.kind == "influx1" and i.measurement == "m_snapshots" and i.table == "t_snapshots"        # separate measurement next to the general one
    t = rec_ops.snapshot_store(base, "timescale", "shared")
    assert t.kind == "timescale" and t.table == "t"
    assert trg.action_label("Pauza + zapis CSV", "SQLite") == "Pauza + zapis SQLite" and trg.saves("Zapis CSV") and not trg.saves("Pauza")


def test_config_roundtrip_and_defaults():
    c = TabConfig()
    assert c.trigger.target == "csv" and c.trigger.place == "shared" and c.trigger.db_file == "snapshots.db"
    c.trigger.target, c.trigger.place = "sqlite", "own"
    d = TabConfig.from_dict(c.to_dict())
    assert (d.trigger.target, d.trigger.place) == ("sqlite", "own")
    assert TabConfig.from_dict({"trigger": {"place": "weird"}}).trigger.place == "shared"
    assert TabConfig.from_dict({"trigger": {"action": "Zapis CSV"}}).trigger.target == "csv"           # an older file: CSV as before


def test_panel_follows_the_target(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.chk_trig.setChecked(True)
    tab.cb_tact.setCurrentIndex(tab.cb_tact.findData("Pauza + zapis CSV"))
    assert tab.ed_tfolder.isEnabled() and tab.ed_tname.isEnabled() and not tab.cb_tplace.isEnabled() and not tab.ed_tdb.isEnabled()      # CSV: folder + name
    tab.cb_ttarget.setCurrentIndex(tab.cb_ttarget.findData("sqlite"))
    assert tab.cb_tact.itemText(2) == "Pauza + zapis SQLite" and tab.cb_tplace.isEnabled()
    assert not tab.ed_tfolder.isEnabled() and not tab.ed_tname.isEnabled()                       # the general database: no folder
    tab.cb_tplace.setCurrentIndex(tab.cb_tplace.findData("own"))
    assert tab.cb_tplace.currentText() == "Osobny plik w folderze" and tab.ed_tfolder.isEnabled() and tab.ed_tdb.isEnabled() and not tab.ed_tname.isEnabled()
    tab.cb_ttarget.setCurrentIndex(tab.cb_ttarget.findData("influx1"))
    assert tab.cb_tplace.currentText() == "Osobna tabela / measurement" and not tab.ed_tdb.isEnabled() and not tab.ed_tfolder.isEnabled()
    tab.cb_ttarget.setCurrentIndex(tab.cb_ttarget.findData("sqlite"))
    c = tab._collect()
    assert (c.trigger.target, c.trigger.place, c.trigger.action) == ("sqlite", "own", "Pauza + zapis CSV")
    tab.shutdown()


def _fire(tab, tmp_path):
    tab.cfg.trigger.signal = tab._run_signals[0].name
    tab.status_msg = ""
    tab.trig_t, tab.trig_win = 10.0, 6.0
    tab._trigger_action()
    assert pump(lambda: "zapisano snapshot" in tab.status_msg or "błąd" in tab.status_msg, 10)


def test_trigger_snapshot_goes_to_the_general_or_a_separate_sqlite(app, tmp_path):
    tab = db_tab(tmp_path)
    feed(tab, 0.0, 30.0)
    general = os.path.join(str(tmp_path), "general.db")
    tab.cfg.store = StoreConfig(kind="sqlite", sqlite_path=general, mode="changes")
    def setup(action, target, place, folder="", db_file=""):
        tab.chk_trig.setChecked(True)
        tab.cb_tact.setCurrentIndex(tab.cb_tact.findData(action))
        tab.cb_ttarget.setCurrentIndex(tab.cb_ttarget.findData(target))
        tab.cb_tplace.setCurrentIndex(tab.cb_tplace.findData(place))
        tab.ed_tfolder.setText(folder or "snapshots")
        tab.ed_tdb.setText(db_file or "snapshots.db")
        tab.sp_tpre.setValue(0.0)
        tab._trigger_changed()
    setup("Zapis CSV", "sqlite", "shared")
    _fire(tab, tmp_path)
    assert "zapisano snapshot" in tab.status_msg and os.path.exists(general)
    be = store.open_backend(StoreConfig(kind="sqlite", sqlite_path=general), str(tmp_path))
    sess = be.sessions()
    be.close()
    assert len(sess) == 1 and sess[0]["title"] == "Snapshot (trigger)"                               # a recording of the general database
    setup("Zapis CSV", "sqlite", "own", str(tmp_path / "snaps"), "mine.db")
    tab.trig_state = "armed"
    _fire(tab, tmp_path)
    own = tmp_path / "snaps" / "mine.db"
    assert own.exists()
    be = store.open_backend(StoreConfig(kind="sqlite", sqlite_path=str(own)), str(tmp_path))
    assert len(be.sessions()) == 1
    be.close()
    be = store.open_backend(StoreConfig(kind="sqlite", sqlite_path=general), str(tmp_path))
    assert len(be.sessions()) == 1                                                                   # the general one did not get the second snapshot
    be.close()
    tab.shutdown()
