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


@pytest.fixture(autouse=True)
def _private_sessions(monkeypatch, tmp_path):
    """The session registry lives in %ProgramData% / %PUBLIC%: tests use a private folder and no leftover registry."""
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "programdata"))
    monkeypatch.setenv("PUBLIC", str(tmp_path / "public"))
    from s7trace.core import sessions
    monkeypatch.setattr(sessions, "REGISTRY", None)
    monkeypatch.setattr(sessions, "_grant_everyone", lambda p: None)



@pytest.fixture(autouse=True)
def _close_windows_after_test(monkeypatch, _private_appdata, _private_sessions):
    """Tabs / main windows a test leaves behind keep their refresh timers and heartbeats running for the rest of the run,
    which made the full run slower and slower (every later setStyleSheet re-polishes all living widgets). Everything created
    by the test is shut down and deleted after it. Requests monkeypatch + the private-folder fixtures so that it runs before
    their undo."""
    created = []
    try:
        from s7trace.ui import main_window as mw, trace_tab as tt
    except Exception:                                  # pragma: no cover
        yield
        return

    def track(cls):
        orig = cls.__init__

        def init(self, *a, **k):
            orig(self, *a, **k)
            created.append(self)
        monkeypatch.setattr(cls, "__init__", init)

    track(tt.TraceTab)
    track(mw.MainWindow)
    import importlib
    import pkgutil
    import s7trace.ui as ui_pkg
    from PySide6.QtWidgets import QDialog
    for m in pkgutil.iter_modules(ui_pkg.__path__):                       # every dialog class of the program
        mod = importlib.import_module(f"s7trace.ui.{m.name}")
        for cls in vars(mod).values():
            if isinstance(cls, type) and issubclass(cls, QDialog) and cls.__module__ == mod.__name__:
                track(cls)
    yield
    for w in reversed(created):
        try:
            if isinstance(w, mw.MainWindow):
                for t in (w._heartbeat, w._autosave):
                    t.stop()
                w.registry.close()
                for i in range(w.tabs.count()):
                    w.tabs.widget(i).shutdown()
            elif hasattr(w, "shutdown"):
                w.shutdown()
            w.hide()
            w.deleteLater()                            # a hidden but living widget is re-styled by every later setStyleSheet
        except Exception:                              # already closed / deleted by the test itself
            pass
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    except Exception:                                  # pragma: no cover
        pass

