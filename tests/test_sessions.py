"""Registry of running program instances: who has S7Trace open, which scans run, warning about a scanned PLC."""
import json
import os
import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from s7trace.core import sessions as ss
from s7trace.core.config import TabConfig
from s7trace.ui.main_window import MainWindow
from s7trace.ui.theme import apply_dark
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def _fake_other(d, user="PLANT\\anna", ip="10.1.1.1", state="running", age=0.0):
    data = {"id": "other" + user[-3:], "user": user, "host": "H", "pid": 1, "session": 3,
            "started": "2026-10-02T08:00:00", "updated": time.time() - age,
            "tabs": [{"title": "Piec", "ip": ip, "state": state, "since": "2026-10-02T08:05:00"}]}
    with open(os.path.join(d, data["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def test_registry_publishes_and_lists_own_session(app):
    r = ss.Registry(lambda: [{"title": "A", "ip": "10.1.1.1", "state": "running", "since": "2026-10-02T09:00:00"}])
    assert r.dir and "programdata" in r.dir
    r.publish()
    me = [s for s in r.sessions() if s["me"]]
    assert len(me) == 1 and me[0]["tabs"][0]["ip"] == "10.1.1.1" and me[0]["user"] and me[0]["pid"] == os.getpid()
    r.close()
    assert r.sessions() == []                                                   # removed at once on close


def test_registry_falls_back_to_public_folder(app, monkeypatch, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setenv("PROGRAMDATA", str(blocker))                             # a folder cannot be made there
    r = ss.Registry(lambda: [])
    assert r.dir and "public" in r.dir


def test_stale_sessions_are_ignored_and_purged(app):
    r = ss.Registry(lambda: [])
    r.publish()
    _fake_other(r.dir, "PLANT\\old", age=ss.STALE_S + 5)                        # not refreshed: program is gone
    _fake_other(r.dir, "PLANT\\dead", age=ss.PURGE_S + 5)
    assert [s["user"] for s in r.sessions() if not s["me"]] == []
    assert not any("dead" in n for n in os.listdir(r.dir))                      # very old files are deleted
    r.close()


def test_others_scanning_same_plc_only(app):
    r = ss.Registry(lambda: [{"title": "mine", "ip": "10.1.1.1", "state": "running", "since": None}])
    r.publish()
    _fake_other(r.dir, "PLANT\\anna", ip="10.1.1.1:102", state="running")
    _fake_other(r.dir, "PLANT\\bob", ip="10.9.9.9", state="running")
    _fake_other(r.dir, "PLANT\\eve", ip="10.1.1.1", state="stopped")            # open but not scanning
    found = r.others_scanning("10.1.1.1")
    assert [f["user"] for f in found] == ["PLANT\\anna"]                        # own session never counts
    assert r.others_scanning("10.5.5.5") == []
    r.close()


def test_start_warns_but_does_not_block(app, monkeypatch):
    r = ss.Registry(lambda: [])
    r.publish()
    _fake_other(r.dir, "PLANT\\anna", ip="10.1.1.1")
    monkeypatch.setattr(ss, "REGISTRY", r)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    tab = TraceTab(TabConfig(ip="10.1.1.1"), lambda: [])
    tab._warn_if_scanned_elsewhere("10.1.1.1")
    assert shown and "PLANT\\anna" in shown[0] and "Piec" in shown[0]
    shown.clear()
    tab._warn_if_scanned_elsewhere("10.2.2.2")
    assert not shown
    tab.shutdown()
    r.close()


def test_main_window_registers_tabs_and_unregisters_on_close(app, tmp_path, monkeypatch):
    monkeypatch.setattr("s7trace.ui.main_window.save_app_config", lambda *a, **k: None)
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    assert ss.REGISTRY is w.registry
    mine = [s for s in w.registry.sessions() if s["me"]][0]
    assert mine["tabs"][0]["state"] == "stopped" and mine["tabs"][0]["since"] is None
    w.tabs.widget(0).state = "running"
    w.registry.publish()
    mine = [s for s in w.registry.sessions() if s["me"]][0]
    assert mine["tabs"][0]["state"] == "running" and mine["tabs"][0]["since"]
    w.tabs.widget(0).state = "stopped"
    folder = w.registry.dir
    w.close()
    assert ss.REGISTRY is None and os.listdir(folder) == []


def test_sessions_dialog_lists_users_and_scans(app, tmp_path, monkeypatch):
    from s7trace.ui.sessions_dialog import SessionsDialog
    r = ss.Registry(lambda: [{"title": "A", "ip": "10.1.1.1", "state": "stopped", "since": None}])
    _fake_other(r.dir, "PLANT\\anna", ip="10.4.4.4")
    d = SessionsDialog(r)
    cells = [[d.table.item(i, c).text() for c in range(d.table.columnCount())] for i in range(d.table.rowCount())]
    assert len(cells) == 2 and any("PLANT\\anna" in row[0] for row in cells)
    assert any("(to okno)" in row[0] for row in cells)
    anna = next(row for row in cells if "anna" in row[0])
    assert anna[4] == "10.4.4.4" and anna[5] == "Skanuje" and anna[1] == "3"
    assert "<b>2</b>" in d.lbl.text() and "<b>1</b>" in d.lbl.text()           # 2 sessions, 1 scan
    d.timer.stop()
    r.close()
