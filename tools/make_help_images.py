"""Generates the pictures of the help ('Pomoc -> opis programu') from the RUNNING program.

    python tools/make_help_images.py [output_dir]          (default: s7trace/help/img)

The program is started against its own PLC simulator (127.0.0.1, python-snap7 server), runs for a few seconds so that the chart,
the status fields and the statistics are real, and then every element described in the help is photographed: the whole window,
every menu and sub-menu, the groups of the settings panel, single fields, the button rows, the chart, the status bar and the
dialogs. Nothing is drawn by hand - if the program looks different tomorrow, run the script again.

The real Windows platform plugin is used (fonts and widget styles are the ones the user sees); the windows flash on the screen
for a moment. Everything the program writes (settings, markers, recordings) goes to a temporary folder."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "s7trace", "help", "img")
_base = os.environ.get("PUBLIC", "")                           # a path without the real account name (the status bar shows the REC path)
TMP = tempfile.mkdtemp(prefix="s7trace_help_", dir=_base if os.path.isdir(_base) else None)
os.environ["APPDATA"] = os.path.join(TMP, "appdata")
os.environ["PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["PUBLIC"] = os.path.join(TMP, "public")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["USERDOMAIN"] = "PLANT"
os.environ["USERNAME"] = os.environ["USER"] = os.environ["LOGNAME"] = "OT-engineer"          # the pictures must not show the real account
import platform                                                                         # noqa: E402
platform.node = lambda: "PL-NOW-ADS01"

from PySide6.QtCore import QPoint, QRect, Qt, QTimer                      # noqa: E402
from PySide6.QtGui import QPixmap                                         # noqa: E402
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QMenu, QWidget)       # noqa: E402

from s7trace.core import config as cfgmod, markers as mk                 # noqa: E402

DATA = os.path.join(TMP, "documents")
os.makedirs(DATA, exist_ok=True)
cfgmod.data_dir = lambda: DATA                                           # snapshots, REC, markers: a private folder
mk.default_path = lambda: os.path.join(DATA, "markers.db")
PORT = 11102
SAVED: list[str] = []


def pump(n: int = 6, ms: int = 30) -> None:
    for _ in range(n):
        QApplication.processEvents()
        time.sleep(ms / 1000)


def save(pm: QPixmap, name: str) -> None:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name + ".png")
    pm.save(path)
    SAVED.append(name)
    print(f"  {name}.png  {pm.width()}x{pm.height()}")


def shot(w: QWidget, name: str, margin: int = 0) -> None:
    """A picture of a widget exactly as it is drawn now."""
    pump(3)
    pm = w.grab()
    if margin:
        big = QPixmap(pm.width() + 2 * margin, pm.height() + 2 * margin)
        big.fill(w.palette().window().color())
        from PySide6.QtGui import QPainter
        p = QPainter(big)
        p.drawPixmap(margin, margin, pm)
        p.end()
        pm = big
    save(pm, name)


def shot_rect(win: QWidget, widgets: list[QWidget], name: str, pad: int = 4) -> None:
    """A picture of the part of `win` that holds all `widgets` (their union rectangle)."""
    pump(3)
    r = QRect()
    for w in widgets:
        tl = w.mapTo(win, QPoint(0, 0))
        r = r.united(QRect(tl, w.size()))
    r = r.adjusted(-pad, -pad, pad, pad).intersected(win.rect())
    save(win.grab(r), name)


def shot_menu(menu: QMenu, name: str, at: QPoint | None = None) -> None:
    """A picture of an opened menu."""
    menu.popup(at or QPoint(120, 120))
    pump(4)
    save(menu.grab(), name)
    menu.hide()
    pump(2)


def menu_by_title(win, title: str) -> QMenu:
    for a in win.menuBar().actions():
        if a.text().replace("&", "") == title:
            return a.menu()
    raise KeyError(title)


def sub_menu(menu: QMenu, title: str) -> QMenu:
    for a in menu.actions():
        if a.menu() is not None and a.text().replace("&", "") == title:
            return a.menu()
    raise KeyError(title)


def start_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from s7trace.ui.theme import apply_theme
    apply_theme(app, None)
    return app


def main() -> None:
    app = start_app()
    from s7trace.core.config import TabConfig
    from s7trace.core.types import Signal
    from s7trace.sim import Simulator
    from s7trace.ui.main_window import MainWindow

    sim = Simulator(PORT)
    sim.start()
    sim_std = Simulator(102)                          # the standard S7 port: the connection wizard probes it
    try:
        sim_std.start()
    except Exception as e:                            # noqa: BLE001
        print("no simulator on port 102:", e)
        sim_std = None
    time.sleep(0.6)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        sigs = [Signal(name=f"D160{c}", source="DB", dtype="BOOL", db=1, byte=160, bit=i, color=col, comment=f"Czujnik {i + 1}")
                for i, (c, col) in enumerate(zip("ABCDE", ("#ffb347", "#c8f04e", "#4ef04e", "#4ef0c0", "#4eb8f0")))]
        sigs.append(Signal(name="Licznik", source="DB", dtype="INT", db=1, byte=170, color="#b388ff", comment="Licznik cykli 0…30000"))
        sigs.append(Signal(name="Sinus", source="DB", dtype="REAL", db=1, byte=172, color="#ff6b6b", comment="Przebieg testowy ±50"))
        cfg = TabConfig(ip=f"127.0.0.1:{PORT}", conf_name="Linia 1 - piec", cycle_ms=25, window_s=20, signals=sigs)
        tab = win.new_tab(cfg)
        win.tabs.removeTab(0)
        win.tabs.setCurrentIndex(win.tabs.indexOf(tab))
        pump(8)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import help_shots as shots                                           # the pictures themselves
        shots.run(app, win, tab, sim, save=save, shot=shot, shot_rect=shot_rect, shot_menu=shot_menu,
                  menu_by_title=menu_by_title, sub_menu=sub_menu, pump=pump, tmp=TMP)
    finally:
        sim.stop()
        if sim_std is not None:
            sim_std.stop()
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(SAVED)} pictures in {OUT}")


if __name__ == "__main__":
    main()
