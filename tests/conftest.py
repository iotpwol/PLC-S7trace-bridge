"""Shared test setup: no modal prompt may block a test run, no test writes into the real user profile."""
import pytest


@pytest.fixture(autouse=True)
def _private_appdata(monkeypatch, tmp_path):
    """The address history (and other per-user files) live in %APPDATA%\\S7Trace: tests get an empty private one."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))


@pytest.fixture(autouse=True)
def _no_name_prompt(monkeypatch):
    """The default file names contain {confname}: a tab without a configuration name asks for it. In tests the
    question is answered 'cancel' (-> no_name); tests of the prompt itself patch getText again."""
    try:
        from PySide6.QtWidgets import QInputDialog
    except Exception:                                  # pragma: no cover
        return
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
