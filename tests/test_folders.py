"""Snapshot / REC folders: relative names live in the user's data folder, the fields show the full system path."""
import os

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from s7trace.core.config import TabConfig, data_dir
from s7trace.ui.theme import apply_dark
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def test_folder_fields_show_the_system_path_and_pick_relative(app, monkeypatch, tmp_path):
    t = TraceTab(TabConfig(ip="10.0.0.1"), lambda: [])
    t.show()
    base = data_dir()
    assert t.ed_tfolder.placeholderText() == "snapshots" and os.path.join(base, "snapshots") in t.ed_tfolder.toolTip()
    assert os.path.join(base, "rec") in t.ed_rfolder.toolTip()
    t.ed_tfolder.setText("moje")
    assert os.path.join(base, "moje") in t.ed_tfolder.toolTip()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: os.path.join(base, "inne", "snap")))
    t._pick_folder()
    assert t.ed_tfolder.text() == os.path.join("inne", "snap") and t.cfg.trigger.folder == os.path.join("inne", "snap")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    t._pick_rec_folder()
    assert t.ed_rfolder.text() == str(tmp_path)                           # outside the user's folder: stays absolute
    assert t._portable_folder(base) == "."
