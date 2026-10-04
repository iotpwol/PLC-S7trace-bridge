"""REC target in the tab (CSV / database, every sample / changes), the settings dialog and the import window."""
import csv
import time
from datetime import datetime

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QDialog

from s7trace.core import store
from s7trace.core.config import TabConfig
from s7trace.core.store import KINDS, StoreConfig, open_backend
from s7trace.ui.main_window import MainWindow
from s7trace.ui.store_dialog import FIELDS, StoreDialog, StoreImportDialog
from s7trace.ui.theme import apply_dark
from test_round5 import _tab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def _record(tab, n=120):
    """A short run through the tab's own recorder: A toggles, B ramps and holds."""
    tab._run_signals = list(tab.cfg.signals)
    tab.start_wall = datetime(2026, 10, 3, 8, 0, 0)
    tab._open_recorder()
    assert tab.recorder is not None
    rows = []
    for i in range(n):
        v = [float((i // 40) % 2), min(i, 30) * 1.0]
        rows.append((i * 0.05, v))
        tab.recorder.write(i * 0.05, v)
    tab._close_recorder()
    return rows


# ------------------------------------------------------------------ REC panel
def test_rec_panel_defaults_and_enabling(app):
    tab = _tab()
    assert [tab.cb_rkind.itemData(i) for i in range(tab.cb_rkind.count())] == KINDS
    assert tab.cb_rkind.currentData() == "csv" and tab.cb_rmode.currentData() == "changes"     # default: changes of state
    assert tab.ed_rfolder.isEnabled() and tab.ed_rname.isEnabled() and not tab.btn_rdb.isEnabled()
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("influx2"))
    assert not tab.ed_rfolder.isEnabled() and not tab.ed_rname.isEnabled() and tab.btn_rdb.isEnabled()
    assert tab.to_config().store.kind == "influx2"
    tab.cb_rmode.setCurrentIndex(tab.cb_rmode.findData("all"))
    again = TabConfig.from_dict(tab.to_config().to_dict())
    assert again.store.kind == "influx2" and again.store.mode == "all"
    tab.shutdown()


def test_old_configs_get_the_default_target():
    c = TabConfig.from_dict({"ip": "1.2.3.4"})                      # a file saved before the databases existed
    assert c.store.kind == "csv" and c.store.mode == "changes"


def test_csv_rec_through_the_tab_writes_only_changes_by_default(app, tmp_path):
    tab = _tab()
    tab.ed_rfolder.setText(str(tmp_path))
    tab.ed_rname.setText("r_{tab}.csv")
    _record(tab)
    files = list(tmp_path.glob("r_*.csv"))
    assert len(files) == 1
    rows = [r for r in csv.reader(l for l in files[0].read_text().splitlines() if not l.startswith("#"))][1:]
    assert 30 < len(rows) < 45                                       # not 120: only the moments with a change
    tab.cb_rmode.setCurrentIndex(tab.cb_rmode.findData("all"))
    _record(tab)
    second = [p for p in tmp_path.glob("r_*.csv") if p not in files]
    assert len(second) == 1
    assert len([l for l in second[0].read_text().splitlines() if not l.startswith("#")]) - 1 == 120   # every sample
    tab.shutdown()


def test_sqlite_rec_through_the_tab_and_import_back(app, tmp_path, monkeypatch):
    tab = _tab()
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("sqlite"))
    tab.cfg.store.sqlite_path = str(tmp_path / "rec.db")
    rows = _record(tab)
    b = store.open_backend(tab.cfg.store)
    sess = b.sessions()
    assert len(sess) == 1 and sess[0]["tab"] == tab.title() and len(sess[0]["signals"]) == 2
    b.close()
    # import it into a fresh tab through the import window
    t2 = _tab()
    t2.cfg.store = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "rec.db"))
    shown = {}

    def fake_exec(self):
        self.refresh()
        shown["rows"] = self.table.rowCount()
        self.table.selectRow(0)
        self.load()
        return QDialog.Accepted if self.result else QDialog.Rejected

    monkeypatch.setattr(StoreImportDialog, "exec", fake_exec)
    asked = []
    monkeypatch.setattr(type(t2), "_ask_target", lambda self, active: asked.append(active) or "here")
    t2.import_db()
    assert asked == [False]                                               # this tab already holds data: the user is asked
    assert shown["rows"] == 1
    assert [s.name for s in t2.cfg.signals] == ["A", "B"] and len(t2.buffer) > 3
    t, v = t2.buffer.snapshot()
    k = np.searchsorted(t, 3.0 + 1e-6, side="right") - 1                 # the rebuilt step curve equals what was recorded
    assert np.allclose(v[k], rows[60][1])
    assert "Wczytano" in t2.status_msg and t2.cfg.store.sqlite_path.endswith("rec.db")
    tab.shutdown()
    t2.shutdown()


def test_db_status_text_shows_progress_and_errors(app, tmp_path):
    tab = _tab()
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("sqlite"))
    tab.cfg.store.sqlite_path = str(tmp_path / "s.db")
    tab._run_signals = list(tab.cfg.signals)
    tab.start_wall = datetime.now()
    tab._open_recorder()
    tab.recorder.write(0.0, [1.0, 2.0])
    time.sleep(0.8)
    assert "zapisano" in tab._rec_status()
    tab.recorder.last_error = "serwer nie odpowiada"
    assert "BŁĄD" in tab._rec_status()
    tab._close_recorder()
    tab.shutdown()


def test_db_recording_stores_the_controller_data(app, tmp_path):
    tab = _tab()
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("sqlite"))
    tab.cfg.store.sqlite_path = str(tmp_path / "dev.db")
    tab.device = {"ip": "10.1.1.1", "method": "s7", "rack": 0, "slot": 2,
                  "info": {"model": "CPU 315-2 PN/DP", "serial": "S C-1", "plc_name": "Piec", "firmware": "V3.3"}}
    tab._run_signals = list(tab.cfg.signals)
    tab.start_wall = datetime.now()
    tab._open_recorder()
    tab.recorder.write(0.0, [1.0, 2.0])
    tab._on_info({**tab.device, "info": {**tab.device["info"], "firmware": "V3.4"}})     # the PLC reports newer data after a reconnect
    tab._close_recorder()
    b = open_backend(tab.cfg.store)
    (s,) = b.sessions()
    assert s["device"]["info"]["model"] == "CPU 315-2 PN/DP" and s["device"]["info"]["firmware"] == "V3.4"
    assert s["device"]["slot"] == 2
    b.close()
    tab.shutdown()


# ------------------------------------------------------------------ dialogs
@pytest.mark.parametrize("kind", [k for k in KINDS if k != "csv"])
def test_store_dialog_has_the_fields_of_each_target(app, kind):
    cfg = StoreConfig(kind="csv", token="T", password="P", pg_password="Q")
    d = StoreDialog(cfg, kind)
    assert set(d.edits) == {a for _, a, _ in FIELDS[kind]} and d.cfg.kind == kind
    for attr, w in d.edits.items():                                      # secrets are hidden while typing
        if attr in StoreConfig.SECRETS:
            from PySide6.QtWidgets import QLineEdit
            assert w.echoMode() == QLineEdit.Password
    c = d.config()
    assert c.kind == kind and not c.remember
    assert d.chk_remember.isHidden() == (kind == "sqlite") or kind == "sqlite"       # (no secrets for a local file)


def test_store_dialog_edit_and_test_connection(app, tmp_path):
    d = StoreDialog(StoreConfig(), "sqlite")
    d.edits["sqlite_path"].setText(str(tmp_path / "t.db"))
    d.test()
    assert "OK" in d.lbl.text() and "SQLite" in d.lbl.text()
    assert d.config().sqlite_path == str(tmp_path / "t.db")
    d2 = StoreDialog(StoreConfig(), "influx1")
    d2.edits["url"].setText("http://127.0.0.1:9")
    d2.test()
    assert "Błąd" in d2.lbl.text() and "brak połączenia" in d2.lbl.text()
    d3 = StoreDialog(StoreConfig(), "timescale")
    d3.edits["port"].setValue(6543)
    d3.edits["pg_password"].setText("secret")
    d3.chk_remember.setChecked(True)
    c = d3.config()
    assert c.port == 6543 and c.pg_password == "secret" and c.remember and c.to_dict()["pg_password"] == "secret"


def test_import_dialog_lists_loads_and_limits_range(app, tmp_path):
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "i.db"))
    sigs = [__import__("s7trace.core.types", fromlist=["Signal"]).Signal(name="A")]
    start = datetime(2026, 10, 3, 8, 0, 0)
    rec = store.DbRecorder(cfg, sigs, start, {"ip": "10.1.1.1", "tab": "Piec", "conf": "L1"})
    for i in range(100):
        rec.write(i * 1.0, [float(i)])
    rec.close()
    import s7trace.ui.store_dialog as sd
    sd.data_dir = lambda: str(tmp_path)
    d = StoreImportDialog(cfg)
    d.refresh()
    assert d.table.rowCount() == 1 and d.cell(0, "conf") == "L1" and d.cell(0, "ip") == "10.1.1.1"
    assert "Tylko zmiany" in d.cell(0, "mode")
    assert d.btn_load.isEnabled() and not d.dt0.isEnabled()
    d.chk_range.setChecked(True)
    assert d.dt0.isEnabled() and d.selected_range()[0] is not None
    d.dt0.setDateTime(d.dt0.dateTime().addSecs(10))
    d.dt1.setDateTime(d.dt0.dateTime().addSecs(20))
    d.load()
    meta, t, v, _ = d.result
    assert 10 <= len(t) <= 22 and t[0] >= (d.selected_range()[0])
    bad = StoreImportDialog(StoreConfig(kind="influx2", url="http://127.0.0.1:9"))
    bad.refresh()
    assert "Błąd" in bad.lbl.text()


def test_main_menu_has_the_database_import(app, tmp_path):
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    names = [a.text() for a in w.menuBar().actions()[0].menu().actions()]
    assert any("Przegląd nagrań" in n for n in names) and any("Import CSV" in n for n in names)
    w.close()


# ------------------------------------------------------------------ REC press: connection test in the background
def test_rec_press_reports_an_unreachable_server_and_can_abort(app, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    tab = _tab()
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("influx1"))
    tab.cfg.store = StoreConfig(kind="influx1", url="http://127.0.0.1:9", database="d", test_timeout_s=1.0,
                                spool_mb=5, retry_max_s=1)
    tab._run_signals = list(tab.cfg.signals)
    tab.start_wall = datetime.now()
    tab.state = "running"
    tab.btn_rec.setChecked(True)
    deadline = time.time() + 10
    while tab._probe_box is None and time.time() < deadline:        # the test runs in a thread; its result comes by signal
        QApplication.processEvents()
        time.sleep(0.02)
    box = tab._probe_box
    assert box is not None and "brak połączenia" in box.text() and "na dysku" in box.text()
    assert tab.recorder is not None and "brak połączenia" in tab.status_msg            # recording is still running
    assert [b.text() for b in box.buttons()] == ["Kontynuuj REC", "Przerwij REC"]
    abort = next(b for b in box.buttons() if b.text() == "Przerwij REC")
    abort.click()
    assert not tab.btn_rec.isChecked()
    box.close()
    tab.shutdown()


def test_rec_press_with_a_working_server_shows_no_message(app, tmp_path):
    tab = _tab()
    tab.cfg.store = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "ok.db"))
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("sqlite"))
    tab._run_signals = list(tab.cfg.signals)
    tab.start_wall = datetime.now()
    tab._open_recorder()
    tab._on_db_probe(tab.recorder.session, "")
    assert tab._probe_box is None
    tab._close_recorder()
    tab.shutdown()


# ------------------------------------------------------------------ time parameters in the database settings
@pytest.mark.parametrize("kind", [k for k in KINDS if k != "csv"])
def test_store_dialog_lists_every_time_parameter_with_a_description(app, kind):
    from s7trace.ui.store_dialog import PARAMS_OF
    d = StoreDialog(StoreConfig(), kind)
    from s7trace.ui.store_dialog import USER_PARAMS
    assert list(d.params) == PARAMS_OF[kind] + USER_PARAMS
    for name, w in d.params.items():
        label, lo, hi, unit, desc = store.PARAMS[name]
        assert len(desc) > 60 and w.toolTip() == desc and w.minimum() == lo and w.maximum() == hi
        assert w.value() == getattr(StoreConfig(), name)                  # the defaults are what the dialog starts with
    assert "keyframe_min" in d.params and "read_max_points" in d.params


def test_store_dialog_edits_and_resets_the_times(app):
    d = StoreDialog(StoreConfig(kind="influx2"), "influx2")
    d.params["keyframe_min"].setValue(2.5)
    d.params["retry_max_s"].setValue(30)
    d.params["spool_mb"].setValue(0)
    c = d.config()
    assert (c.keyframe_min, c.retry_max_s, c.spool_mb) == (2.5, 30.0, 0)
    c2 = StoreConfig.from_dict(c.to_dict())
    assert (c2.keyframe_min, c2.retry_max_s, c2.spool_mb) == (2.5, 30.0, 0)
    d._reset_times()
    assert d.config().keyframe_min == 10.0 and d.config().spool_mb == 500
    s = StoreDialog(StoreConfig(), "sqlite")
    s.chk_daily.setChecked(True)
    assert s.config().rotate_daily and "retry_max_s" not in s.params


def test_out_of_range_values_are_clamped_when_loading():
    c = StoreConfig.from_dict({"keyframe_min": -5, "batch_s": 0, "queue_max": 5, "spool_mb": "x", "retry_max_s": 99999})
    assert c.keyframe_min == 0 and c.batch_s == 0.05 and c.queue_max == 1000 and c.spool_mb == 500 and c.retry_max_s == 600


def test_menu_entry_opens_the_database_settings(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    names = [a.text() for a in w.menuBar().actions()[3].menu().actions() if a.text()]
    entry = next(a for a in w.menuBar().actions() if a.menu() and a.text().replace("&", "") == "Ustawienia").menu()
    act = next(a for a in entry.actions() if "Zapis nagrań w bazach danych" in a.text())
    opened = {}
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (store.KIND_LABEL["influx2"], True)))

    def fake_exec(self):
        opened["kind"] = self.kind
        self.params["keyframe_min"].setValue(3)
        return QDialog.Accepted

    monkeypatch.setattr(StoreDialog, "exec", fake_exec)
    act.trigger()
    t = w.tabs.currentWidget()
    assert opened["kind"] == "influx2" and t.cb_rkind.currentData() == "influx2" and t.cfg.store.keyframe_min == 3.0
    w.close()


# ------------------------------------------------------------------ import: rotated files, CSV export, thinning note
def _make_db(path, start, n=100):
    rec = store.DbRecorder(StoreConfig(kind="sqlite", sqlite_path=str(path), mode="all"),
                           [__import__("s7trace.core.types", fromlist=["Signal"]).Signal(name="A")], start, {"tab": "T"})
    for i in range(n):
        rec.write(i * 1.0, [float(i)])
    rec.close()


def test_import_dialog_sees_rotated_files_and_exports_csv(app, tmp_path, monkeypatch):
    import s7trace.ui.store_dialog as sd
    from PySide6.QtWidgets import QFileDialog
    sd.data_dir = lambda: str(tmp_path)
    _make_db(tmp_path / "rec_2026-10-02.db", datetime(2026, 10, 2, 8, 0, 0))
    _make_db(tmp_path / "rec_2026-10-03.db", datetime(2026, 10, 3, 8, 0, 0))
    d = StoreImportDialog(StoreConfig(kind="sqlite", sqlite_path="rec.db"))
    d.refresh()
    assert d.table.rowCount() == 2 and d.cell(0, "start").startswith("2026-10-03")        # newest first, both files
    d.table.selectRow(1)
    assert d.btn_csv.isEnabled()
    out = tmp_path / "x.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    d.export_csv()
    lines = [l for l in out.read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
    assert len(lines) == 101 and lines[1].split(",")[0] == "0.0000" and "Zapisano" in d.lbl.text()


def test_import_dialog_thins_out_long_recordings_and_says_so(app, tmp_path):
    import s7trace.ui.store_dialog as sd
    sd.data_dir = lambda: str(tmp_path)
    _make_db(tmp_path / "long.db", datetime(2026, 10, 3, 8, 0, 0), n=5000)
    d = StoreImportDialog(StoreConfig(kind="sqlite", sqlite_path="long.db", read_max_points=1000))
    d.refresh()
    d.table.selectRow(0)
    d.load()
    meta, t, v, _ = d.result
    assert len(t) < 1700 and v[:, 0].max() == 4999.0 and "zmniejszono z 5000" in d.note


def test_compress_days_is_a_timescale_only_option_in_the_dialog(app):
    d = StoreDialog(StoreConfig(kind="timescale"), "timescale")
    assert "compress_days" in d.params and d.params["compress_days"].value() == 7
    d.params["compress_days"].setValue(0)
    assert d.config().compress_days == 0
    d._reset_times()
    assert d.config().compress_days == 7
    for kind in ("sqlite", "influx1", "influx2"):
        assert "compress_days" not in StoreDialog(StoreConfig(), kind).params
