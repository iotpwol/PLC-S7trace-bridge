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
        self.menu.addAction("Pokaż S7Trace", self.restore)
        self.menu.addSeparator()
        self.menu.addAction("Zakończ", win.close)
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
