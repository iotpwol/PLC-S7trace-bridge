"""Ikona programu: pasek zadań / obszar powiadomień (przy zegarze) / oba."""
import json

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from s7trace.ui.main_window import MainWindow
from s7trace.ui.theme import apply_dark


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def test_app_icon_placement_menu_and_saving(app, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    cfg = str(tmp_path / "c.json")
    w = MainWindow(config_file=cfg)
    w.show()
    assert w.act_icon["taskbar"].isChecked() and not w.tray.active              # default: the taskbar only
    labels = [a.text() for a in w.menu_icon.actions()]
    assert labels == ["Pasek zadań", "Obszar powiadomień (przy zegarze)", "Pasek zadań i obszar powiadomień"]
    w.act_icon["both"].trigger()
    assert w.ui["app_icon"] == "both" and w.tray.active and w.tray.icon.isVisible()
    hidden = []
    monkeypatch.setattr(type(w), "hide", lambda self: hidden.append(1))
    w.tray.minimized()
    assert hidden == []                                                         # 'both': minimizing stays in the taskbar
    w.act_icon["tray"].trigger()
    w.tray.minimized()
    app.processEvents()
    assert hidden == [1]                                                        # 'tray': the minimized window leaves the taskbar
    w.set_app_icon("taskbar")
    assert not w.tray.icon.isVisible()
    w._save_config()
    assert json.load(open(cfg, encoding="utf-8"))["ui"]["app_icon"] == "taskbar"
    w.set_app_icon("tray")
    w._save_config()
    w2 = MainWindow(config_file=cfg)                                            # remembered between runs
    assert w2.act_icon["tray"].isChecked() and w2.tray.mode == "tray"
    w2.tray.icon.setVisible(False)
    w.tray.icon.setVisible(False)


def test_without_a_system_tray_the_taskbar_is_used(app, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    w.set_app_icon("tray")
    assert not w.tray.active and not w.tray.icon.isVisible()
    hidden = []
    monkeypatch.setattr(type(w), "hide", lambda self: hidden.append(1))
    w.tray.minimized()
    assert hidden == []                                                         # nothing to hide into: the window stays in the taskbar
