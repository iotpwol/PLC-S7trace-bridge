"""Main window: tab bar in the menu row (right aligned, one tab per PLC connection) + menus."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QByteArray, QEvent, QSize, QTimer, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QMainWindow, QMenu,
                               QMessageBox, QStackedWidget, QTabBar, QToolButton, QToolTip, QWidget)

from ..core import marker_look, panel_cfg, render_cfg, sessions, web_agent
from ..core import symbols as sym
from ..core.config import TabConfig, app_dir, load_app_config, save_app_config, symbols_path
from ..core.naming import suggest_config_name
from . import theme as th
from .help_dialog import HelpDialog
from .conn_dialog import ConnectionDialog
from ..version import about_lines
from . import help_mode
from .interface_dialog import InterfaceDialog
from .render_dialog import RenderDialog
from .marker_look_dialog import MarkerLookDialog
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
        old_look = self.ui.get("marker_look")                  # before the look belonged to the theme it was a separate key
        theme0 = self.ui.get("theme") if isinstance(self.ui.get("theme"), dict) else None
        if theme0 is not None and "marker_look" not in theme0 and isinstance(old_look, dict):
            theme0 = {**theme0, "marker_look": old_look}
        if isinstance(theme0, dict) and "panel" not in theme0 and (isinstance(self.ui.get("folds"), dict) or "info_tab" in self.ui):
            theme0 = {**theme0, "panel": {"folds": self.ui.get("folds"), "info_tab": self.ui.get("info_tab", 0)}}   # before: kept in ui
        self.theme = th.normalize(theme0)
        if theme0 is None:
            self.theme["panel"] = panel_cfg.normalize({"folds": self.ui.get("folds"), "info_tab": self.ui.get("info_tab", 0)})
        self.ui.pop("folds", None)
        self.ui.pop("info_tab", None)
        self.web_cfg = web_agent.normalize(self.ui.get("web_server"))         # Ustawienia -> Serwer Web
        self.render_cfg = render_cfg.normalize(self.ui.get("render"))      # Ustawienia -> Renderowanie wykresu
        self.marker_look = self.theme["marker_look"]       # Znaczniki -> Wygląd znaczników (part of the interface configuration)

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
        bar.installEventFilter(self)                   # the tooltip of a tab lists its connection / recording and database
        self.help_btn = QToolButton()                  # help mode: the same '?' as in the title bar of every dialog
        self.help_btn.setText("?")
        self.help_btn.setObjectName("helpBtn")          # lights up (theme keys help_on_bg / help_on_text) while the mode is on
        self.help_btn.setCheckable(True)
        self.help_btn.setToolTip("Tryb pomocy: po włączeniu najedź kursorem na dowolny element, aby zobaczyć jego opis (Shift+F1, Esc kończy)")
        self.help_mode = help_mode.install(QApplication.instance())
        self.help_btn.clicked.connect(lambda on: self.help_mode.set_active(on))
        self.help_mode.modeChanged.connect(self.help_btn.setChecked)
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
        lay.addWidget(self.help_btn)
        self._build_menu()
        self._corner, self._plus = corner, plus       # keep the Python wrappers alive
        self.menuBar().setCornerWidget(corner, Qt.TopRightCorner)

        tabs = cfg.get("tabs") or [TabConfig().to_dict()]
        legacy_legend = self.ui.get("legend_pos")                # before: one position for all tabs
        for d in tabs:
            tc = TabConfig.from_dict(d)
            if "legend_pos" not in d and isinstance(legacy_legend, (list, tuple)) and len(legacy_legend) == 2:
                tc.legend_pos = [float(legacy_legend[0]), float(legacy_legend[1])]
            self.new_tab(tc)
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
        self.registry = sessions.Registry(self._session_tabs)   # who runs the program / which scans run (this computer)
        sessions.REGISTRY = self.registry
        self.registry.publish()
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(int(sessions.HEARTBEAT_S * 1000))
        self._heartbeat.timeout.connect(self.registry.publish)
        self._heartbeat.timeout.connect(self._refresh_agent_payload)
        self._heartbeat.start()
        self._agent_payload: dict = {}
        self._reporter = None
        self._refresh_agent_payload()
        self._start_reporter()
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
        self._act(m, "Przegląd nagrań w bazach (SQLite / InfluxDB / TimescaleDB)…", lambda: self._cur(lambda t: t.import_db()))
        m.addSeparator()
        self._act(m, "Importuj symbole (TIA / Step 7)…", self.import_symbols)
        self._act(m, "Wyczyść symbole", self.clear_symbols)
        m.addSeparator()
        self._act(m, "Wyjście", self.close, "Ctrl+Q")

        v = mb.addMenu("&Widok")
        self._act(v, "Dopasuj widok do całości", lambda: self._cur(self._fit), "Ctrl+0")
        self.act_legend = self._act(v, "Legenda", self._set_legend, checked=self.ui.get("legend", True))
        self.act_grid = self._act(v, "Siatka", self._set_grid, checked=self.ui.get("grid", True))
        self.act_points = self._act(v, "Punkty (znaczniki próbek na krzywych, ta karta)",
                                    lambda on: self._cur(lambda t: t.act_pts.setChecked(on)), checked=False)
        v.addSeparator()
        self.menu_style = v.addMenu("Nazwy sygnałów na wykresie")
        self.grp_style = QActionGroup(self)
        self.act_style = {}
        for key, label in (("legend", "Legenda (ramka z listą w rogu)"), ("labels", "Opisy przy sygnałach (po prawej stronie osi Y)")):
            a = self.menu_style.addAction(label)
            a.setCheckable(True)
            a.setChecked(key == self.ui.get("theme", {}).get("legend_style", "legend"))
            self.grp_style.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self._edit_theme({"legend_style": k}))
            self.act_style[key] = a
        self.menu_legend = v.addMenu("Położenie legendy (ta karta)")
        for label, pos in (("Lewy górny róg", (0, 0)), ("Prawy górny róg", (1, 0)),
                           ("Lewy dolny róg", (0, 1)), ("Prawy dolny róg", (1, 1))):
            self._act(self.menu_legend, label, lambda p=pos: self.set_legend_pos(*p))
        self.menu_legend.addSeparator()
        hint = self.menu_legend.addAction("…albo przeciągnij legendę myszą na wykresie")
        hint.setEnabled(False)

        dg = mb.addMenu("&Diagnostyka")
        self._act(dg, "Diagnostyka połączenia…", lambda: self._cur(lambda t: t.open_diag()), "Ctrl+D")
        self._act(dg, "Informacje o sterowniku i czas…", lambda: self._cur(lambda t: self.run_wizard(t, 1)))
        dg.addSeparator()
        self._act(dg, "Aktywne sesje programu…", self.show_sessions)
        self._act(dg, "Zaległe bufory zapisu do baz…", lambda: self._cur(lambda t: t.open_spools()))

        mk = mb.addMenu("&Znaczniki")
        self._act(mk, "Dodaj znacznik teraz", lambda: self._cur(lambda t: t.mk.add_now()), "Ctrl+Shift+M")
        self.act_hlevel = self._act(mk, "Znacznik poziomu sygnału (kliknij na wykresie; maks. 2 poziome kursory)",
                                    lambda on: self._cur(lambda t: t.act_hlev.setChecked(on)), checked=False)
        self._act(mk, "Lista znaczników…", lambda: self._cur(lambda t: t.mk.open_list()), "Ctrl+M")
        self._act(mk, "Zapisz znaczniki…", lambda: self._cur(lambda t: t.mk.save()), "Ctrl+Shift+S")
        mk.addSeparator()
        self._act(mk, "Wyszukiwarka danych (po wartościach i godzinach)…", lambda: self._cur(lambda t: t.mk.open_search()), "Ctrl+F")
        mk.addSeparator()
        self._act(mk, "Wygląd znaczników (linie, REC)…", self.edit_marker_look)
        mk.addSeparator()
        hint = mk.addAction("Znacznik w wybranym miejscu (także różnicy poziomu): prawy przycisk myszy na wykresie")
        hint.setEnabled(False)
        self.tabs.tabBar().currentChanged.connect(lambda _i: self._sync_tab_actions())

        st = mb.addMenu("&Ustawienia")
        self._act(st, "Metoda połączenia i dane logowania…", lambda: self._cur(self.edit_connection))
        self._act(st, "Kreator połączenia (rozpoznawanie metody)…", lambda: self._cur(self.run_wizard))
        self._act(st, "Zapis nagrań w bazach danych (SQLite / InfluxDB / TimescaleDB)…",
                  lambda: self._cur(lambda t: t.edit_store(pick=True)))
        self._act(st, "Wymagania, ograniczenia i blokady…", lambda: self.show_help("Ograniczenia"))
        st.addSeparator()
        self._act(st, "Interfejs (kolory, czcionki)…", self.edit_interface)
        self._act(st, "Renderowanie wykresu (odświeżanie, punkty, obciążenie CPU)…", self.edit_render)
        self._act(st, "Serwer Web (zgłaszanie sesji i wspólny rejestr)…", self.edit_web_server)
        self.menu_saved = st.addMenu("Zapisane konfiguracje interfejsu")
        self.menu_saved.aboutToShow.connect(self._fill_saved_menu)
        self.menu_profile = st.addMenu("Profil kolorów")
        self.menu_profile.aboutToShow.connect(self._fill_profile_menu)
        st.addSeparator()
        self._act(st, "Zapisz konfigurację karty…", self.save_config_as)
        self._act(st, "Wczytaj konfigurację do karty…", self.load_config_from)

        h = mb.addMenu("&Pomoc")
        self._act(h, "Pomoc – opis programu…", lambda: self.show_help(), "F1")
        self.act_help_mode = self._act(h, "Tryb pomocy (opisy elementów po najechaniu)", lambda on: self.help_mode.set_active(on), "Shift+F1",
                                       checked=False)                # a tick while the mode is on
        self.help_mode.modeChanged.connect(self.act_help_mode.setChecked)
        h.addSeparator()
        self._act(h, "Adresowanie, rack/slot, S7-1200/1500",
                  lambda: QMessageBox.information(self, "Pomoc", RACK_SLOT_HELP))
        self._act(h, "O programie", lambda: QMessageBox.about(self, "O programie", "\n".join(about_lines())))

    def _sync_tab_actions(self) -> None:
        """The checkable menu items (Punkty, Znacznik poziomu sygnału) show the state of the current tab."""
        t = self.tabs.currentWidget()
        for act, src in ((self.act_points, "act_pts"), (self.act_hlevel, "act_hlev")):
            act.blockSignals(True)
            act.setChecked(bool(t is not None and getattr(t, src).isChecked()))
            act.setEnabled(t is not None)
            act.blockSignals(False)

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
    def _apply_render(self, cfg: dict) -> None:
        self.render_cfg = render_cfg.normalize(cfg)
        for i in range(self.tabs.count()):
            self.tabs.widget(i).apply_render(self.render_cfg)

    # ---------------------------------------------------------- reporting to the web server
    def _refresh_agent_payload(self) -> None:
        """Built in the GUI thread (the reporter thread only reads the finished dict)."""
        self._agent_payload = {"id": self.registry.id, "user": self.registry.user, "host": self.registry.host, "pid": os.getpid(),
                               "started": self.registry.started, "tabs": self._session_tabs()}

    def _start_reporter(self) -> None:
        if self._reporter is not None:
            self._reporter.stop()
        self._reporter = web_agent.WebReporter(lambda: self._agent_payload, self.web_cfg)
        sessions.REMOTE = self._reporter if self.web_cfg["enabled"] else None
        self._reporter.start()

    def edit_web_server(self) -> None:
        from .web_server_dialog import WebServerDialog
        dlg = WebServerDialog(self.web_cfg, self)
        if dlg.exec():
            self.web_cfg = dlg.result_cfg()
            self._start_reporter()

    def _apply_marker_look(self, cfg: dict) -> None:
        self.marker_look = marker_look.normalize(cfg)
        self.theme = {**self.theme, "marker_look": self.marker_look}
        for i in range(self.tabs.count()):
            self.tabs.widget(i).apply_marker_look(self.marker_look)

    def edit_marker_look(self) -> None:
        dlg = MarkerLookDialog(self.marker_look, self._apply_marker_look, self)
        if dlg.exec():
            self._apply_marker_look(dlg.result_cfg())

    def edit_render(self) -> None:
        dlg = RenderDialog(self.render_cfg, self._apply_render, self)
        if dlg.exec():
            self._apply_render(dlg.result_cfg())

    def _apply_theme(self, theme: dict) -> None:
        old_panel = self.theme.get("panel")
        self.theme = th.apply_theme(QApplication.instance(), theme)
        if self.theme["panel"] != old_panel:                     # another configuration (or its preview): the panels follow it
            for i in range(self.tabs.count()):
                self.tabs.widget(i).apply_panel(self.theme["panel"])
        if self.theme["marker_look"] != self.marker_look:      # a configuration (or the preview of one) with another marker look
            self._apply_marker_look(self.theme["marker_look"])
        for i in range(self.tabs.count()):
            self.tabs.widget(i).apply_plot_theme(self.theme["plot_bg"], self.theme["plot_fg"])
            self.tabs.widget(i).apply_ctl_theme(self.theme)
        if hasattr(self, "act_style"):
            self.act_style[self.theme["legend_style"]].setChecked(True)
        self._relayout_tabs()

    # ------------------------------------------------- tab bar sizing / layout sync
    def _relayout_tabs(self) -> None:
        """The tab bar is as wide as its tabs need (full names), at most up to the end of the menu items."""
        bar, mb = self.tabs.bar, self.menuBar()
        acts = mb.actions()
        left = mb.actionGeometry(acts[-1]).right() + 16 if acts else 160
        plus = self._plus.sizeHint().width() + self.help_btn.sizeHint().width() + 14
        avail = mb.width() - left - plus
        want = sum(bar.tabSizeHint(i).width() for i in range(bar.count())) + 8
        w = int(max(min(want, avail), 140))
        bar.setFixedWidth(w)
        self._corner.setFixedWidth(w + plus)
        self._corner.updateGeometry()
        mb.updateGeometry()
        self._place_corner()

    def _place_corner(self) -> None:
        """QMenuBar keeps the corner widget where it was laid out for the old width: after the tab bar grew, the
        new tab stuck out to the right of the window. Re-seat the corner so it ends exactly at the window edge."""
        mb, c = self.menuBar(), self._corner
        c.setGeometry(max(mb.width() - c.width(), 0), 0, c.width(), mb.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout_tabs()

    def showEvent(self, e):
        super().showEvent(e)
        self._relayout_tabs()

    def _apply_layouts(self, source: TraceTab | None = None) -> None:
        if source is not None:                                  # the panel layout (order / folds / bottom tab) is a part of the theme
            self.theme = {**self.theme, "panel": source.panel_state()}
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) is not source:
                self.tabs.widget(i).apply_layout()

    def set_legend_pos(self, fx: float, fy: float) -> None:
        """Legend corner of the CURRENT tab (every tab keeps its own position)."""
        self._cur(lambda t: t.set_legend_pos(fx, fy))

    def show_help(self, topic: str = "") -> None:
        HelpDialog(self, topic).exec()

    def edit_connection(self, tab) -> None:
        ConnectionDialog(tab, self).exec()

    def run_wizard(self, tab, page: int = 0) -> None:
        WizardDialog(tab, show_tab=page, parent=self).exec()

    def _edit_theme(self, changes: dict) -> None:
        """A change of the interface configuration made outside the 'Interfejs' window (e.g. the status bar menu)."""
        self._commit_theme({**self.theme, **changes})

    def _commit_theme(self, theme: dict) -> None:
        if "marker_look" not in theme:                          # e.g. a configuration file of an older version
            theme = {**theme, "marker_look": self.marker_look}
        if "panel" not in theme:
            theme = {**theme, "panel": self.theme["panel"]}
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
        tab.panel_src = lambda: self.theme["panel"]
        tab.theme_edit = self._edit_theme
        tab.new_tab_cb = self.new_tab
        i = self.tabs.addTab(tab, tab.title())
        tab.stateChanged.connect(lambda s, t=tab: self._tab_state(t, s))
        tab.titleChanged.connect(lambda title, t=tab: self._tab_state(t, t.state))
        tab.act_pts.toggled.connect(lambda _on: self._sync_tab_actions())
        tab.act_hlev.toggled.connect(lambda _on: self._sync_tab_actions())
        tab.layoutChanged.connect(lambda t=tab: self._apply_layouts(t))
        tab.legendHideRequested.connect(lambda: self.act_legend.setChecked(False))
        tab.plot.set_legend_visible(self.ui.get("legend", True))
        tab.plot.set_grid(self.ui.get("grid", True))
        tab.apply_plot_theme(self.theme["plot_bg"], self.theme["plot_fg"])
        tab.apply_ctl_theme(self.theme)
        tab.apply_render(self.render_cfg)
        tab.apply_marker_look(self.marker_look)
        tab.apply_layout()
        self._tab_state(tab, "stopped")
        self.tabs.setCurrentIndex(i)
        return tab

    def eventFilter(self, obj, e):
        if e.type() == QEvent.ToolTip and obj is self.tabs.tabBar():
            i = obj.tabAt(e.pos())
            tab = self.tabs.widget(i) if i >= 0 else None
            if tab is not None:
                QToolTip.showText(e.globalPos(), tab.tooltip_html(), obj)
                return True
        return super().eventFilter(obj, e)

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
        if not tab.mk.confirm_close():                           # unsaved markers: listed, the user decides
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
        self.ui["render"] = self.render_cfg
        self.ui.pop("marker_look", None)                       # now inside ui["theme"]
        self.ui["web_server"] = self.web_cfg
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

    # ---------------------------------------------------------- sessions
    def _session_tabs(self) -> list[dict]:
        out = []
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            scanning = t.state in sessions.SCANNING
            out.append({"title": t.title(), "ip": t.ed_ip.text(), "state": t.state,
                        "since": t.start_wall.isoformat(timespec="seconds") if scanning else None})
        return out

    def show_sessions(self) -> None:
        from .sessions_dialog import SessionsDialog
        SessionsDialog(self.registry, self).exec()

    # ---------------------------------------------------------- close
    def closeEvent(self, e):
        for i in range(self.tabs.count()):                        # unsaved markers of any tab: remind before anything is closed
            tab = self.tabs.widget(i)
            if tab.mk.pending():
                self.tabs.setCurrentIndex(i)
                if not tab.mk.confirm_close():
                    e.ignore()
                    return
        self._heartbeat.stop()
        if self._reporter is not None:
            self._reporter.stop()
        if sessions.REMOTE is self._reporter:
            sessions.REMOTE = None
        self.registry.close()                                     # the session disappears from the list at once
        if sessions.REGISTRY is self.registry:
            sessions.REGISTRY = None
        self._save_config()
        for i in range(self.tabs.count()):
            self.tabs.widget(i).shutdown()
        super().closeEvent(e)
