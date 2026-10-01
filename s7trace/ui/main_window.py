"""Main window: bottom tab bar (one tab per PLC connection) + menus."""
from __future__ import annotations

import json
import os

from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QFileDialog, QInputDialog, QMainWindow, QMessageBox, QTabWidget,
                               QToolButton)

from ..core import symbols as sym
from ..core.config import (TabConfig, load_app_config, save_app_config, symbols_path)
from .trace_tab import TraceTab

APP_TITLE = "PLC Trace - narzędzie do rysowania wykresów z danych z PLC Siemens"

DOT = {"running": "#4cd964", "connecting": "#ffcc00", "reconnecting": "#ff9500",
       "stopped": "#8a8a8a", "error": "#ff453a"}


class MainWindow(QMainWindow):
    def __init__(self, config_file: str | None = None):
        super().__init__()
        self.config_file = config_file
        self.setWindowTitle(APP_TITLE)
        self.resize(1500, 860)
        self.symbols: list[sym.Symbol] = sym.load_symbols(symbols_path())

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.South)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        plus = QToolButton()
        plus.setText("+")
        plus.setToolTip("Nowa zakładka (nowe połączenie)")
        plus.clicked.connect(lambda: self.new_tab())
        self.tabs.setCornerWidget(plus)
        self.setCentralWidget(self.tabs)
        self._build_menu()

        cfg = load_app_config(self.config_file)
        tabs = cfg.get("tabs") or [TabConfig().to_dict()]
        for d in tabs:
            self.new_tab(TabConfig.from_dict(d))
        self.tabs.setCurrentIndex(min(cfg.get("current", 0), self.tabs.count() - 1))

    # ----------------------------------------------------------- menu
    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("&Plik")
        self._act(m, "Nowa zakładka", lambda: self.new_tab(), "Ctrl+T")
        self._act(m, "Zamknij zakładkę", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        m.addSeparator()
        self._act(m, "Zapisz konfigurację…", self.save_config_as)
        self._act(m, "Wczytaj konfigurację…", self.load_config_from)
        m.addSeparator()
        self._act(m, "Eksport okna → CSV…", lambda: self._cur(lambda t: t.export_window()))
        self._act(m, "Import CSV → wykres…", lambda: self._cur(lambda t: t.import_csv()))
        m.addSeparator()
        self._act(m, "Importuj symbole (TIA / Step 7)…", self.import_symbols)
        self._act(m, "Wyczyść symbole", self.clear_symbols)
        m.addSeparator()
        self._act(m, "Wyjście", self.close, "Ctrl+Q")

        v = mb.addMenu("&Widok")
        self._act(v, "Dopasuj widok do całości", lambda: self._cur(self._fit), "Ctrl+0")
        self._act(v, "Legenda", lambda c: self._cur(lambda t: t.plot.set_legend_visible(c)), checked=True)
        self._act(v, "Siatka", lambda c: self._cur(lambda t: t.plot.set_grid(c)), checked=True)

        h = mb.addMenu("&Pomoc")
        self._act(h, "Adresowanie, rack/slot, S7-1200/1500", lambda: self._cur(
            lambda t: QMessageBox.information(self, "Pomoc", __import__("s7trace.ui.trace_tab", fromlist=["x"]).RACK_SLOT_HELP)))
        self._act(h, "O programie", lambda: QMessageBox.about(
            self, "O programie", "S7Trace — rejestrator przebiegów z PLC Siemens S7\n"
            "(S7comm przez python-snap7, wykresy pyqtgraph)."))

    def _act(self, menu, text, fn, shortcut=None, checked=None):
        a = QAction(text, self)
        if checked is not None:
            a.setCheckable(True)
            a.setChecked(checked)
            a.toggled.connect(fn)
        else:
            a.triggered.connect(lambda _=False: fn())
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        menu.addAction(a)
        return a

    def _cur(self, fn):
        t = self.tabs.currentWidget()
        if t:
            fn(t)

    @staticmethod
    def _fit(t: TraceTab):
        t.btn_pause.setChecked(True)
        t.plot.fit_all()
        t._on_zoomed(t.plot.window)

    # ----------------------------------------------------------- tabs
    def new_tab(self, cfg: TabConfig | None = None) -> TraceTab:
        tab = TraceTab(cfg or TabConfig(), lambda: self.symbols)
        i = self.tabs.addTab(tab, tab.title())
        tab.stateChanged.connect(lambda s, t=tab: self._tab_state(t, s))
        tab.titleChanged.connect(lambda title, t=tab: self._tab_title(t, title))
        self._tab_state(tab, "stopped")
        self.tabs.setCurrentIndex(i)
        return tab

    def _tab_state(self, tab: TraceTab, state: str):
        i = self.tabs.indexOf(tab)
        if i < 0:
            return
        self.tabs.setTabText(i, f"{tab.title()} ●")
        self.tabs.tabBar().setTabTextColor(i, QColor(DOT.get(state, "#8a8a8a")))

    def _tab_title(self, tab: TraceTab, title: str):
        self._tab_state(tab, tab.state)

    def close_tab(self, i: int):
        tab = self.tabs.widget(i)
        if tab is None:
            return
        if tab.state != "stopped":
            r = QMessageBox.question(self, "S7Trace", "Połączenie jest aktywne. Zamknąć zakładkę?")
            if r != QMessageBox.Yes:
                return
        tab.shutdown()
        self.tabs.removeTab(i)
        tab.deleteLater()
        if self.tabs.count() == 0:
            self.new_tab()

    # --------------------------------------------------------- config
    def _config_dict(self) -> dict:
        return {"tabs": [self.tabs.widget(i).to_config().to_dict() for i in range(self.tabs.count())],
                "current": self.tabs.currentIndex()}

    def save_config_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz konfigurację", "s7trace_config.json", "JSON (*.json)")
        if path:
            save_app_config(self._config_dict(), path)

    def load_config_from(self):
        path, _ = QFileDialog.getOpenFileName(self, "Wczytaj konfigurację", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            cfgs = [TabConfig.from_dict(d) for d in data.get("tabs", [])]
        except Exception as e:
            QMessageBox.warning(self, "S7Trace", f"Nie można wczytać konfiguracji: {e}")
            return
        if any(self.tabs.widget(i).state != "stopped" for i in range(self.tabs.count())):
            QMessageBox.information(self, "S7Trace", "Zatrzymaj aktywne połączenia przed wczytaniem konfiguracji.")
            return
        while self.tabs.count():
            t = self.tabs.widget(0)
            t.shutdown()
            self.tabs.removeTab(0)
        for c in cfgs or [TabConfig()]:
            self.new_tab(c)

    # -------------------------------------------------------- symbols
    def import_symbols(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importuj symbole", "",
            "Symbole (*.xlsx *.csv *.db *.scl *.xml *.sdf *.asc *.seq);;Wszystkie (*.*)")
        if not path:
            return
        db = 1
        if path.lower().endswith((".db", ".scl", ".xml")):
            db, ok = QInputDialog.getInt(self, "Numer DB", "Numer bloku danych (DB) dla tego pliku:", 1, 1, 65535)
            if not ok:
                return
        try:
            new = sym.import_symbols(path, db)
        except Exception as e:
            QMessageBox.warning(self, "Import symboli", str(e))
            return
        key = lambda s: (s.name, s.source, s.db, s.byte, s.bit)
        have = {key(s) for s in self.symbols}
        added = [s for s in new if key(s) not in have]
        self.symbols.extend(added)
        sym.save_symbols(symbols_path(), self.symbols)
        QMessageBox.information(self, "Import symboli",
                                f"Wczytano {len(new)} symboli ({len(added)} nowych).\n"
                                "Dodasz je w oknie 'Sygnały…' przyciskiem 'Z symboli…'.")

    def clear_symbols(self):
        if QMessageBox.question(self, "S7Trace", "Usunąć wszystkie zaimportowane symbole?") == QMessageBox.Yes:
            self.symbols.clear()
            sym.save_symbols(symbols_path(), self.symbols)

    # ---------------------------------------------------------- close
    def closeEvent(self, e):
        try:
            save_app_config(self._config_dict(), self.config_file)
        except OSError:
            pass
        for i in range(self.tabs.count()):
            self.tabs.widget(i).shutdown()
        super().closeEvent(e)
