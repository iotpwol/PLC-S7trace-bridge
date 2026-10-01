"""Main window: tab bar in the menu row (right aligned, one tab per PLC connection) + menus."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QByteArray, QSize, QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QMainWindow, QMenu,
                               QMessageBox, QStackedWidget, QTabBar, QToolButton, QWidget)

from ..core import symbols as sym
from ..core.config import TabConfig, app_dir, load_app_config, save_app_config, symbols_path
from ..core.naming import suggest_config_name
from . import theme as th
from .help_dialog import HelpDialog
from .conn_dialog import ConnectionDialog
from .interface_dialog import InterfaceDialog
from .wizard_dialog import WizardDialog
from .trace_tab import RACK_SLOT_HELP, TraceTab, dot_icon

APP_TITLE = "PLC Trace - narzędzie do rysowania wykresów z danych z PLC Siemens"

STATE_PL = {"running": "praca", "connecting": "łączenie", "reconnecting": "ponawianie połączenia",
            "stopped": "zatrzymana", "error": "błąd"}
DOT = {"running": "#4cd964", "connecting": "#ffcc00", "reconnecting": "#ff9500",
       "stopped": "#8a8a8a", "error": "#ff453a"}


class TopTabs:
    """QTabBar + QStackedWidget behind the small subset of the QTabWidget API used by the window."""

    def __init__(self, bar: QTabBar, stack: QStackedWidget):
        self.bar, self.stack = bar, stack
        self.pages: list[QWidget] = []
        bar.currentChanged.connect(self._show)
        bar.tabMoved.connect(lambda a, b: self.pages.insert(b, self.pages.pop(a)))

    def _show(self, i: int) -> None:
        if 0 <= i < len(self.pages):
            self.stack.setCurrentWidget(self.pages[i])

    def count(self) -> int:
        return len(self.pages)

    def widget(self, i: int):
        return self.pages[i] if 0 <= i < len(self.pages) else None

    def currentIndex(self) -> int:
        return self.bar.currentIndex()

    def currentWidget(self):
        return self.widget(self.bar.currentIndex())

    def setCurrentIndex(self, i: int) -> None:
        self.bar.setCurrentIndex(i)
        self._show(i)

    def indexOf(self, w) -> int:
        return self.pages.index(w) if w in self.pages else -1

    def addTab(self, w: QWidget, title: str) -> int:
        self.pages.append(w)
        self.stack.addWidget(w)
        return self.bar.addTab(title)

    def removeTab(self, i: int) -> None:
        w = self.pages.pop(i)
        self.bar.removeTab(i)
        self.stack.removeWidget(w)

    def setTabText(self, i: int, t: str) -> None:
        self.bar.setTabText(i, t)

    def tabBar(self) -> QTabBar:
        return self.bar


class MainWindow(QMainWindow):
    def __init__(self, config_file: str | None = None):
        super().__init__()
        self.config_file = config_file
        self.setWindowTitle(APP_TITLE)
        self.resize(1500, 860)
        self.symbols: list[sym.Symbol] = sym.load_symbols(symbols_path())
        cfg = load_app_config(self.config_file)
        self.ui: dict = cfg.get("ui") if isinstance(cfg.get("ui"), dict) else {}
        self.theme = th.normalize(self.ui.get("theme"))

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        bar = QTabBar()
        bar.setShape(QTabBar.RoundedNorth)
        bar.setTabsClosable(True)
        bar.setMovable(True)
        bar.setExpanding(False)
        bar.setDrawBase(False)
        bar.setElideMode(Qt.ElideRight)
        bar.setIconSize(QSize(12, 12))
        bar.setContextMenuPolicy(Qt.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._tab_menu)
        bar.tabCloseRequested.connect(self.close_tab)
        bar.tabBarDoubleClicked.connect(self.rename_tab)
        self.tabs = TopTabs(bar, self.stack)
        plus = QToolButton()
        plus.setText("+")
        plus.setToolTip("Nowa karta (nowe połączenie)")
        plus.clicked.connect(lambda: self.new_tab())
        corner = QWidget()
        lay = QHBoxLayout(corner)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(2)
        lay.addWidget(bar)
        lay.addWidget(plus)
        self._build_menu()
        self._corner, self._plus = corner, plus       # keep the Python wrappers alive
        self.menuBar().setCornerWidget(corner, Qt.TopRightCorner)

        tabs = cfg.get("tabs") or [TabConfig().to_dict()]
        for d in tabs:
            self.new_tab(TabConfig.from_dict(d))
        self.tabs.setCurrentIndex(min(max(cfg.get("current", 0), 0), self.tabs.count() - 1))
        geo = self.ui.get("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass
        self._apply_theme(self.theme)
        self._apply_layouts()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(self._on_os_scheme)
        except Exception:
            pass                                       # Qt < 6.5
        self._autosave = QTimer(self)
        self._autosave.setInterval(20000)
        self._autosave.timeout.connect(self._save_config)
        self._autosave.start()

    # ----------------------------------------------------------- menu
    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("&Plik")
        self._act(m, "Nowa karta", lambda: self.new_tab(), "Ctrl+T")
        self._act(m, "Zmień nazwę karty…", lambda: self.rename_tab(self.tabs.currentIndex()), "F2")
        self._act(m, "Duplikuj kartę", lambda: self.duplicate_tab(self.tabs.currentIndex()))
        self._act(m, "Zamknij kartę", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
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
        self.act_legend = self._act(v, "Legenda", self._set_legend, checked=self.ui.get("legend", True))
        self.act_grid = self._act(v, "Siatka", self._set_grid, checked=self.ui.get("grid", True))
        v.addSeparator()
        self._act(v, "Diagnostyka połączenia…", lambda: self._cur(lambda t: t.open_diag()), "Ctrl+D")
        self.menu_legend = v.addMenu("Położenie legendy")
        for label, pos in (("Lewy górny róg", (0, 0)), ("Prawy górny róg", (1, 0)),
                           ("Lewy dolny róg", (0, 1)), ("Prawy dolny róg", (1, 1))):
            self._act(self.menu_legend, label, lambda p=pos: self.set_legend_pos(*p))
        self.menu_legend.addSeparator()
        hint = self.menu_legend.addAction("…albo przeciągnij legendę myszą na wykresie")
        hint.setEnabled(False)

        st = mb.addMenu("&Ustawienia")
        self._act(st, "Metoda połączenia i dane logowania…", lambda: self._cur(self.edit_connection))
        self._act(st, "Kreator połączenia (rozpoznawanie metody)…", lambda: self._cur(self.run_wizard))
        self._act(st, "Informacje o sterowniku i czas…", lambda: self._cur(lambda t: self.run_wizard(t, 1)))
        self._act(st, "Wymagania, ograniczenia i blokady…", lambda: self.show_help("Ograniczenia"))
        st.addSeparator()
        self._act(st, "Interfejs (kolory, czcionki)…", self.edit_interface)
        self.menu_saved = st.addMenu("Zapisane konfiguracje interfejsu")
        self.menu_saved.aboutToShow.connect(self._fill_saved_menu)
        self.menu_profile = st.addMenu("Profil kolorów")
        self.menu_profile.aboutToShow.connect(self._fill_profile_menu)
        st.addSeparator()
        self._act(st, "Zapisz konfigurację karty…", self.save_config_as)
        self._act(st, "Wczytaj konfigurację do karty…", self.load_config_from)

        h = mb.addMenu("&Pomoc")
        self._act(h, "Pomoc – opis programu…", lambda: self.show_help(), "F1")
        h.addSeparator()
        self._act(h, "Adresowanie, rack/slot, S7-1200/1500",
                  lambda: QMessageBox.information(self, "Pomoc", RACK_SLOT_HELP))
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

    def _set_legend(self, on: bool):
        self.ui["legend"] = on
        for i in range(self.tabs.count()):
            self.tabs.widget(i).plot.set_legend_visible(on)

    def _set_grid(self, on: bool):
        self.ui["grid"] = on
        for i in range(self.tabs.count()):
            self.tabs.widget(i).plot.set_grid(on)

    # ----------------------------------------------------------- theme
    def _apply_theme(self, theme: dict) -> None:
        self.theme = th.apply_theme(QApplication.instance(), theme)
        for i in range(self.tabs.count()):
            self.tabs.widget(i).apply_plot_theme(self.theme["plot_bg"], self.theme["plot_fg"])
            self.tabs.widget(i).apply_ctl_theme(self.theme)
        self._relayout_tabs()

    # ------------------------------------------------- tab bar sizing / layout sync
    def _relayout_tabs(self) -> None:
        """The tab bar is as wide as its tabs need (full names), at most up to the end of the menu items."""
        bar, mb = self.tabs.bar, self.menuBar()
        acts = mb.actions()
        left = mb.actionGeometry(acts[-1]).right() + 16 if acts else 160
        plus = self._plus.sizeHint().width() + 10
        avail = mb.width() - left - plus
        want = sum(bar.tabSizeHint(i).width() for i in range(bar.count())) + 8
        w = int(max(min(want, avail), 140))
        bar.setFixedWidth(w)
        self._corner.setFixedWidth(w + plus)
        self._corner.updateGeometry()
        mb.updateGeometry()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout_tabs()

    def showEvent(self, e):
        super().showEvent(e)
        self._relayout_tabs()

    def _apply_layouts(self, source: TraceTab | None = None) -> None:
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) is not source:
                self.tabs.widget(i).apply_layout()

    def set_legend_pos(self, fx: float, fy: float) -> None:
        self.ui["legend_pos"] = [fx, fy]
        self._apply_layouts()

    def show_help(self, topic: str = "") -> None:
        HelpDialog(self, topic).exec()

    def edit_connection(self, tab) -> None:
        ConnectionDialog(tab, self).exec()

    def run_wizard(self, tab, page: int = 0) -> None:
        WizardDialog(tab, show_tab=page, parent=self).exec()

    def _commit_theme(self, theme: dict) -> None:
        self.ui["theme"] = th.normalize(theme)
        self._apply_theme(self.ui["theme"])

    def _fill_saved_menu(self) -> None:
        m = self.menu_saved
        m.clear()
        profiles = th.list_profiles()
        for name, path in profiles:
            m.addAction(name, lambda p=path: self._load_theme_file(p))
        if profiles:
            m.addSeparator()
        m.addAction("Zapisz bieżącą jako…", self._save_theme_file)
        m.addAction("Wczytaj z pliku…", self._open_theme_file)

    def _load_theme_file(self, path: str) -> None:
        try:
            self._commit_theme(th.load_profile(path))
        except Exception as e:
            QMessageBox.warning(self, "Interfejs", f"Nie można wczytać konfiguracji: {e}")

    def _open_theme_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Wczytaj konfigurację interfejsu", th.profiles_dir(),
                                              "JSON (*.json)")
        if path:
            self._load_theme_file(path)

    def _save_theme_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz konfigurację interfejsu",
                                              os.path.join(th.profiles_dir(), "interfejs.json"), "JSON (*.json)")
        if path:
            try:
                th.save_profile(path, self.theme)
            except OSError as e:
                QMessageBox.warning(self, "Interfejs", f"Nie można zapisać: {e}")

    def _fill_profile_menu(self) -> None:
        m = self.menu_profile
        m.clear()
        for key, label in th.PROFILES[:3]:
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.theme.get("profile") == key)
            a.triggered.connect(lambda _=False, k=key: self.set_profile(k))

    def set_profile(self, profile: str) -> None:
        self._commit_theme({**self.theme, "profile": profile})

    def _on_os_scheme(self, *_) -> None:
        if self.theme.get("profile") == "system":          # follow the Windows light/dark switch live
            self._commit_theme(self.theme)

    def edit_interface(self):
        dlg = InterfaceDialog(self.theme, self._apply_theme, self)
        if dlg.exec():
            self._commit_theme(dlg.theme)

    # ----------------------------------------------------------- tabs
    def _other_tabs(self, me: TraceTab):
        return lambda: [(self.tabs.widget(i).title(), self.tabs.widget(i).cfg.signals)
                        for i in range(self.tabs.count()) if self.tabs.widget(i) is not me]

    def new_tab(self, cfg: TabConfig | None = None) -> TraceTab:
        tab = TraceTab(cfg or TabConfig(), lambda: self.symbols, self.ui)
        tab.other_tabs = self._other_tabs(tab)
        i = self.tabs.addTab(tab, tab.title())
        tab.stateChanged.connect(lambda s, t=tab: self._tab_state(t, s))
        tab.titleChanged.connect(lambda title, t=tab: self._tab_state(t, t.state))
        tab.layoutChanged.connect(lambda t=tab: self._apply_layouts(t))
        tab.plot.set_legend_visible(self.ui.get("legend", True))
        tab.plot.set_grid(self.ui.get("grid", True))
        tab.apply_plot_theme(self.theme["plot_bg"], self.theme["plot_fg"])
        tab.apply_ctl_theme(self.theme)
        tab.apply_layout()
        self._tab_state(tab, "stopped")
        self.tabs.setCurrentIndex(i)
        return tab

    def _tab_state(self, tab: TraceTab, state: str):
        i = self.tabs.indexOf(tab)
        if i < 0:
            return
        bar = self.tabs.tabBar()
        bar.setTabText(i, tab.title())
        bar.setTabIcon(i, dot_icon(DOT.get(state, "#8a8a8a")))        # state dot: green running, grey stopped...
        bar.setTabToolTip(i, f"{tab.title()} — {STATE_PL.get(state, state)}")
        self._relayout_tabs()

    def rename_tab(self, i: int):
        tab = self.tabs.widget(i)
        if tab is None:
            return
        name, ok = QInputDialog.getText(self, "Zmień nazwę karty",
                                        "Nazwa karty (puste = adres IP):", text=tab.cfg.name or tab.title())
        if ok:
            tab.rename(name)

    def duplicate_tab(self, i: int):
        tab = self.tabs.widget(i)
        if tab is None:
            return
        cfg = TabConfig.from_dict(tab.to_config().to_dict())
        cfg.name = f"{tab.title()} (kopia)"
        self.new_tab(cfg)

    def _tab_menu(self, pos):
        i = self.tabs.tabBar().tabAt(pos)
        if i < 0:
            return
        menu = QMenu(self)
        menu.addAction("Zmień nazwę…", lambda: self.rename_tab(i))
        menu.addAction("Duplikuj", lambda: self.duplicate_tab(i))
        menu.addSeparator()
        menu.addAction("Zamknij", lambda: self.close_tab(i))
        menu.exec(self.tabs.tabBar().mapToGlobal(pos))

    def close_tab(self, i: int):
        tab = self.tabs.widget(i)
        if tab is None:
            return
        if tab.state != "stopped":
            r = QMessageBox.question(self, "S7Trace", "Połączenie jest aktywne. Zamknąć kartę?")
            if r != QMessageBox.Yes:
                return
        tab.shutdown()
        self.tabs.removeTab(i)
        tab.deleteLater()
        if self.tabs.count() == 0:
            self.new_tab()
        self._relayout_tabs()

    # --------------------------------------------------------- config
    def _config_dict(self) -> dict:
        self.ui["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self.ui["theme"] = self.theme
        return {"tabs": [self.tabs.widget(i).to_config().to_dict() for i in range(self.tabs.count())],
                "current": self.tabs.currentIndex(), "ui": self.ui}

    def _save_config(self):
        try:
            save_app_config(self._config_dict(), self.config_file)
        except OSError:
            pass

    def _config_dir(self) -> str:
        d = self.ui.get("config_dir") or os.path.join(app_dir(), "konfiguracje")
        os.makedirs(d, exist_ok=True)
        return d

    def save_config_as(self):
        """Saves the configuration of the CURRENT tab (connection, signals, trigger, ranges)."""
        tab = self.tabs.currentWidget()
        if tab is None:
            return
        folder = self._config_dir()
        stem = suggest_config_name(folder, tab.cfg.conf_name)
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz konfigurację", os.path.join(folder, stem + ".json"),
                                              "JSON (*.json)")
        if not path:
            return
        tab.cfg.conf_name = os.path.splitext(os.path.basename(path))[0]
        self.ui["config_dir"] = os.path.dirname(path)
        save_app_config({"tabs": [tab.to_config().to_dict()], "current": 0}, path)
        tab.status_msg = f"Zapisano konfigurację: {path}"

    def load_config_from(self):
        """Loads a configuration into the CURRENT tab; other tabs keep running."""
        tab = self.tabs.currentWidget()
        if tab is None:
            return
        if tab.state != "stopped":
            QMessageBox.information(self, "S7Trace", "Zatrzymaj połączenie na bieżącej karcie przed wczytaniem "
                                    "konfiguracji (połączenia na innych kartach mogą pracować dalej).")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Wczytaj konfigurację", self._config_dir(), "JSON (*.json)")
        if path:
            self.load_config_file(path, tab)

    def load_config_file(self, path: str, tab: TraceTab | None = None) -> bool:
        tab = tab or self.tabs.currentWidget()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            cfgs = [TabConfig.from_dict(d) for d in data.get("tabs", [])]
        except Exception as e:
            QMessageBox.warning(self, "S7Trace", f"Nie można wczytać konfiguracji: {e}")
            return False
        if not cfgs or tab.state != "stopped":
            return False
        stem = os.path.splitext(os.path.basename(path))[0]
        self.ui["config_dir"] = os.path.dirname(path)
        cfgs[0].conf_name = stem
        tab.load_config(cfgs[0])                        # first configuration -> this tab
        for c in cfgs[1:]:                              # a multi-tab file adds the rest as new tabs
            self.new_tab(c)
        self.tabs.setCurrentIndex(self.tabs.indexOf(tab))
        return True

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
        self._save_config()
        for i in range(self.tabs.count()):
            self.tabs.widget(i).shutdown()
        super().closeEvent(e)
