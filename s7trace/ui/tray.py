"""Where the program's icon lives: the taskbar, the notification area next to the clock (tray), or both (Ustawienia -> Ikona programu)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

MODES = (("taskbar", "Pasek zadań"), ("tray", "Obszar powiadomień (przy zegarze)"), ("both", "Pasek zadań i obszar powiadomień"))


def normalize(mode) -> str:
    return mode if mode in ("taskbar", "tray", "both") else "taskbar"


class TrayController(QObject):
    """Owns the tray icon of a main window. 'tray' mode: minimizing the window hides it from the taskbar, the tray icon brings it back;
    'both': the icon is in both places; 'taskbar' (default): no tray icon. Without a system tray (e.g. a server session) the taskbar is used."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.mode = "taskbar"
        self.hidden = False                                      # the window was hidden into the tray by us
        self.icon = QSystemTrayIcon(win)
        self.icon.setToolTip("S7Trace")
        self.menu = QMenu(win)
        self.a_title = self.menu.addAction(win.windowIcon(), "S7Trace")          # icon + name, as before
        self.a_title.setEnabled(False)
        self.a_conn = self.menu.addAction("")                                   # Połączenia PLC: W / LU / AU
        self.a_conn.setEnabled(False)
        self.a_load = self.menu.addAction("")                                   # Obciążenie: this program / the whole computer
        self.a_load.setEnabled(False)
        self.menu.addSeparator()
        self.a_show = self.menu.addAction("", self.toggle)                      # "Pokaż S7Trace" <-> "Ukryj S7Trace"
        self.menu.addSeparator()
        self.a_pin = self.menu.addAction("", self.toggle_pin)                   # "Przypnij do belki" <-> "Odepnij od belki"
        self.menu.addSeparator()
        self.a_quit = self.menu.addAction("Zakończ", self.quit)
        self.timer = QTimer(self)                                               # the numbers follow while the menu is open
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.menu.aboutToShow.connect(self._menu_show)
        self.menu.aboutToHide.connect(self.timer.stop)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    @property
    def active(self) -> bool:
        """True when the tray icon is shown."""
        return self.mode in ("tray", "both") and self.available()

    def set_mode(self, mode: str) -> None:
        self.mode = normalize(mode)
        if self.mode != "taskbar" and self.available():
            self.icon.setIcon(self.win.windowIcon())
            self.icon.setVisible(True)
        else:
            self.icon.setVisible(False)
            if self.hidden:                                      # hidden in the tray and the icon goes away: do not lose the window
                self.restore()

    # ------------------------------------------------------------------ the menu
    def hidden_now(self) -> bool:
        w = self.win
        return self.hidden or not w.isVisible() or w.isMinimized()

    def counts(self) -> tuple[int, int, int | None]:
        """(W, LU, AU): connections being recorded / scanned by this user, scanned by all users of this computer (None = only one user)."""
        from ..core import sessions
        reg = sessions.REGISTRY
        mine = self.win._session_tabs()
        w = sum(1 for t in mine if t.get("rec"))
        lu = sum(1 for t in mine if t.get("state") in sessions.SCANNING)
        if reg is None:
            return w, lu, None
        users, au = {reg.user}, 0
        w = lu = 0
        for ses in reg.sessions():
            tabs = ses.get("tabs", [])
            scan = sum(1 for t in tabs if t.get("state") in sessions.SCANNING)
            au += scan
            users.add(ses.get("user"))
            if ses.get("user") == reg.user:
                lu += scan
                w += sum(1 for t in tabs if t.get("rec"))
        return w, lu, (au if len(users) > 1 else None)

    def conn_text(self) -> str:
        w, lu, au = self.counts()
        return f"Połączenia PLC: {w} / {lu}" + ("" if au is None else f" / {au}")

    def load_text(self) -> str:
        from ..core import sysinfo
        a, c = sysinfo.app_cpu_percent(), sysinfo.cpu_percent()
        f = lambda v: "—" if v is None else f"{v:.0f} %"
        return f"Obciążenie: {f(a)} / {f(c)}"

    def refresh(self) -> None:
        from ..core import startmenu
        self.a_title.setIcon(self.win.windowIcon())
        self.a_conn.setText(self.conn_text())
        self.a_load.setText(self.load_text())
        self.a_show.setText("Pokaż S7Trace" if self.hidden_now() else "Ukryj S7Trace")
        self.a_pin.setText("Odepnij od belki" if startmenu.is_pinned() else "Przypnij do belki")

    def _menu_show(self) -> None:
        self.refresh()
        self.timer.start()

    def toggle(self) -> None:
        """Show the window when it is hidden (taken down to the bar / tray), hide it (to the bar) when it is on the screen."""
        if self.hidden_now():
            self.restore()
        elif self.active:
            self.hidden = True
            self.win.hide()
        else:
            self.win.showMinimized()

    def toggle_pin(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from ..core import startmenu
        from . import appicon
        if startmenu.is_pinned():
            if not startmenu.unpin():
                QMessageBox.warning(self.win, "S7Trace", "Nie udało się usunąć skrótu z menu Start.")
            return
        target, args, workdir, ico = appicon.launch_spec()
        if not startmenu.pin(target, args, workdir, ico):
            QMessageBox.warning(self.win, "S7Trace", "Nie udało się utworzyć skrótu w menu Start.")
            return
        QMessageBox.information(self.win, "S7Trace", "Skrót S7Trace został dodany do menu Start, więc zostaje po zamknięciu programu.\n\n"
                                "Windows nie pozwala programom same przypiąć się do paska zadań – jeśli chcesz mieć ikonę także na pasku, "
                                "kliknij ją prawym przyciskiem (na pasku albo w menu Start) i wybierz „Przypnij do paska zadań”.")

    def quit(self) -> None:
        """'Zakończ' does not force the exit: it asks what to do (the window can also just go down to the bar)."""
        if self.hidden_now():
            self.restore()
        if self.win.ask_quit():
            self.win.close()

    def restore(self) -> None:
        w = self.win
        self.hidden = False
        w.showNormal()
        w.raise_()
        w.activateWindow()

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.win.isVisible() and not self.win.isMinimized():
                self.win.activateWindow()
            else:
                self.restore()

    def minimized(self) -> None:
        """Called when the window was minimized: in 'tray' mode it disappears from the taskbar."""
        if self.mode == "tray" and self.active:
            self.hidden = True
            QTimer.singleShot(0, self.win.hide)
