"""Shared test setup: no modal prompt may block a test run."""
import pytest


@pytest.fixture(autouse=True)
def _no_name_prompt(monkeypatch):
    """The default file names contain {confname}: a tab without a configuration name asks for it. In tests the
    question is answered 'cancel' (-> no_name); tests of the prompt itself patch getText again."""
    try:
        from PySide6.QtWidgets import QInputDialog
    except Exception:                                  # pragma: no cover
        return
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
