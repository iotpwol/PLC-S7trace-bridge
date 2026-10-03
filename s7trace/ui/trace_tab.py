"""One connection tab: settings panel, plot, buttons, trigger handling."""
from __future__ import annotations

import dataclasses
import html
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from PySide6.QtCore import QEvent, QTimer, Qt, Signal as QtSignal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from ..core import render_cfg
from ..core import trigger as trg
from ..core.trigger import DEFAULT_REC_NAME
from ..core.acq_process import ProcAcquirer
from ..core.acquisition import parse_host
from ..core.diagnostics import PingProbe
from ..core.buffer import TraceBuffer
from ..core.config import TabConfig, data_dir
from ..core.csvio import CsvRecorder, read_csv, write_csv
from ..core.planner import MODES
from ..core.symbols import Symbol
from ..core.netaddr import ACCEPTABLE, ipv4_state
from ..core.types import Signal
from ..core.drivers import CONN_LABEL, SOURCE_OF, family_of
from .diag_dialog import DiagDialog
from .duration_combo import DurationCombo
from .plotview import PlotView
from .signals_dialog import SignalsDialog
from ..core import ip_history, sessions
from ..core.store import KIND_LABEL, KINDS, MODE_LABEL, DbRecorder, StoreConfig, test_connection
from ..core.store import MODES as STORE_MODES            # (planner.MODES = communication modes)
from .fold_splitter import DEFAULT_BAR, FoldSplitter
from .pan_label import PanLabel
from .ip_edit import IpCombo

RACK_SLOT_HELP = (
    "Rack / Slot:\n\n"
    "• S7-300 / S7-400: rack 0, slot 2 (CPU) — typowo; w S7-400 slot zależy od konfiguracji.\n"
    "• S7-1200 / S7-1500: rack 0, slot 1.\n\n"
    "S7-1200/1500 wymagają dodatkowo:\n"
    "  – włączonego 'Permit access with PUT/GET communication' we właściwościach CPU,\n"
    "  – bloków DB z wyłączonym 'Optimized block access' (adresy bezwzględne),\n"
    "  – ochrony dostępu dopuszczającej PUT/GET (Full access).\n\n"
    "IP można podać z portem, np. 127.0.0.1:1102 (symulator)."
)


PLACEHOLDERS_HELP = ("Znaczniki w nazwie pliku:\n{confname} – nazwa konfiguracji (gdy jej brak, program zapyta; "
                     "bez odpowiedzi: no_name)\n{ip} – adres IP sterownika\n{tab} – nazwa karty\n"
                     "{date} – data, {time} – godzina")


class ClickLabel(QLabel):
    """Label that reports a left click."""
    clicked = QtSignal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


DEVICE_ROWS = (("Rodzina", "family"), ("Model", "model"), ("Firmware", "firmware"), ("Nazwa stacji", "plc_name"),
               ("Nazwa modułu", "module_name"))


class _Names(dict):
    def __missing__(self, key):          # unknown {placeholder} stays as typed instead of raising KeyError
        return "{" + key + "}"


def dot_icon(color: str | None, size: int = 12) -> QIcon:
    """Filled circle (None = transparent, keeps the button width constant)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    if color:
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(1, 1, size - 2, size - 2)
        p.end()
    return QIcon(pm)


def _sanitize(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s).strip("_") or "tab"


def _spin(lo, hi, val, dec=None, step=None):
    w = QSpinBox() if dec is None else QDoubleSpinBox()
    w.setRange(lo, hi)
    if dec is not None:
        w.setDecimals(dec)
    w.setValue(val)
    w.setKeyboardTracking(False)
    w.setFocusPolicy(Qt.StrongFocus)
    w.wheelEvent = lambda e: e.ignore()
    w.setMinimumWidth(70)               # wide ranges (±1e9) must not squeeze the form labels in a narrow panel
    return w


class TraceTab(QWidget):
    stateChanged = QtSignal(str)       # stopped / connecting / running / reconnecting / error
    titleChanged = QtSignal(str)
    _stateRaw = QtSignal(str, str)     # from worker thread
    layoutChanged = QtSignal()         # splitters / legend moved -> main window syncs the other tabs
    legendHideRequested = QtSignal()   # 'Ukryj legendę' in the legend's context menu (the setting is shared by all tabs)
    _dbProbe = QtSignal(str, str)      # (recording id, cause or "") - result of the connection test run when REC starts
    _infoRaw = QtSignal(object)        # device data from the acquisition process (worker thread)

    def __init__(self, cfg: TabConfig, symbols: callable, ui_state: dict | None = None,
                 other_tabs: callable = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.symbols = symbols
        self.ui_state = ui_state if ui_state is not None else {}
        self.other_tabs = other_tabs or (lambda: [])
        self.buffer = TraceBuffer(len(self.display_signals()))
        self.acq: ProcAcquirer | None = None
        self.state = "stopped"
        self.status_msg = "Gotowy."
        self.paused = False
        self.recorder: CsvRecorder | None = None
        self.start_wall = datetime.now()
        self._run_signals: list[Signal] = []
        self._pending: deque = deque()
        self.engine = trg.TriggerEngine(cfg.trigger)
        self.trig_state = "idle"       # idle / armed / post / hold
        self.trig_t = 0.0
        self.trig_win = 0.0
        self.trig_post_end = 0.0
        self._stat_tick = 0
        self._loading = False
        self._noname_asked = False
        self.ping_probe: PingProbe | None = None
        self.diag_dlg: DiagDialog | None = None
        self._want_left: int | None = None
        self.device: dict | None = None            # PLC data read at the last connection (valid for _device_ip only)
        self._device_ip = ""
        self._rec_dot, self._rec_idle, self._rec_phase = "#ff2020", "#c0c0c0", True
        self._build()
        self._load_cfg()
        self._stateRaw.connect(self._on_state)
        self._infoRaw.connect(self._on_info)
        self._dbProbe.connect(self._on_db_probe)
        self._probe_box = None
        self.loaded: dict | None = None                        # a recording from a database shown in this tab
        self.new_tab_cb = None                                 # set by the main window: opens a new tab (TabConfig -> TraceTab)
        self._rec_info: dict = {}                              # title / notes / tags of the running DB recording
        self._info_dlg = None                                  # the non-modal "name the recording" window
        self.ed_ip.textChanged.connect(self._ip_changed_device)
        self.timer = QTimer(self)
        self._render = render_cfg.normalize(None)               # Ustawienia -> Renderowanie wykresu (set by the main window)
        self._skipped = False                                  # redraws were skipped while the tab was not visible
        self.timer.setInterval(int(1000 / self._render["fps"]))
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.blink = QTimer(self)                    # REC dot
        self.blink.timeout.connect(self._blink_tick)
        self.apply_ctl_theme({"rec_dot": self._rec_dot, "rec_blink_hz": 0.5})
        self._set_buttons()
        self.apply_layout()

    # ================================================================== UI
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- left panel
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 10, 8, 6)

        def group(title):
            g = QGroupBox(title)
            f = QFormLayout(g)
            f.setLabelAlignment(Qt.AlignLeft)
            f.setContentsMargins(8, 10, 8, 8)
            lv.addWidget(g)
            return f

        f = group("Połączenie")
        self.ed_ip = IpCombo()                      # 4 cells with fixed dots + history list; text() is the plain address
        self.ed_ip.setPlaceholderText("192 . 168 . 0 . 1")
        self.ed_ip.setToolTip("Adres IPv4 sterownika (opcjonalnie :port). IPv6 i nazwy hostów nie są obsługiwane.")
        self.ed_ip.textChanged.connect(self._ip_check)
        self.sp_rack = _spin(0, 7, 0)
        self.sp_slot = _spin(0, 31, 2)
        help_btn = QPushButton("?")
        help_btn.setFixedWidth(22)
        help_btn.setToolTip("Pomoc: rack / slot, S7-1200/1500")
        help_btn.clicked.connect(lambda: QMessageBox.information(self, "Rack / Slot", RACK_SLOT_HELP))
        rs = QHBoxLayout()
        rs.addWidget(self.sp_rack)
        rs.addWidget(self.sp_slot)
        rs.addWidget(help_btn)
        self.sp_cycle = _spin(1, 60000, 25)
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(MODES)
        self.lbl_method = QLabel()
        self.lbl_method.setProperty("val", True)            # values are bold (QSS QLabel[val="true"])
        self.lbl_method.setWordWrap(True)
        self.lbl_method.setToolTip("Metoda komunikacji – zmiana: Ustawienia → Metoda połączenia…")
        f.addRow("IP:", self.ed_ip)
        f.addRow("Rack / Slot:", rs)
        f.addRow("Cykle [ms]:", self.sp_cycle)
        f.addRow("Tryb komunik.:", self.cb_mode)
        f.addRow("Metoda:", self.lbl_method)
        self._conn_widgets = [self.ed_ip, self.sp_rack, self.sp_slot, self.sp_cycle, self.cb_mode]

        f = group("Sterownik")
        self.lbl_dev = ClickLabel()
        self.lbl_dev.setTextFormat(Qt.RichText)
        self.lbl_dev.setWordWrap(True)
        self.lbl_dev.setMinimumHeight(self.lbl_dev.fontMetrics().lineSpacing() * len(DEVICE_ROWS) + 8)
        self.lbl_dev.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.lbl_dev.clicked.connect(self.open_device_info)
        f.addRow(self.lbl_dev)
        self._show_device()

        f = group("Zakres okna wykresu")
        self.sp_window = DurationCombo(200.0)      # typed seconds or a pick from the list (5 s ... 24 h)
        self.sp_window.setMinimumWidth(70)
        self.cb_ylayout = QComboBox()
        self.cb_ylayout.addItem("Pasma wg Share", "lanes")
        self.cb_ylayout.addItem("Offset + Gain", "offset")
        self.cb_ylayout.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)   # do not squeeze the labels
        self.cb_ylayout.setMinimumContentsLength(8)                                           # in a narrow panel
        self.cb_ylayout.setMinimumWidth(70)
        self.cb_ylayout.setToolTip(
            "Pasma wg Share: każdy sygnał ma własne pasmo na osi pionowej (wysokość ~ kolumna „Share” w oknie Sygnały), "
            "skalowane do MIN…MAX widocznego fragmentu; oś pokazuje wartości MIN / pośrednie / MAX.\n"
            "Offset + Gain: jedna wspólna skala, sygnały przesunięte o „Offset Y” i pomnożone przez „Gain”.")
        self.chk_auto = QCheckBox("Auto Y")
        self.sp_ymin = _spin(-1e9, 1e9, 0, dec=3)
        self.sp_ymax = _spin(-1e9, 1e9, 10, dec=3)
        f.addRow("Okno czasu [s]:", self.sp_window)
        f.addRow("Układ osi Y:", self.cb_ylayout)
        f.addRow(self.chk_auto)
        f.addRow("Y min:", self.sp_ymin)
        f.addRow("Y max:", self.sp_ymax)

        f = group("Trigger")
        self.chk_trig = QCheckBox("Włącz trigger")
        self.cb_tsig = QComboBox()
        self.cb_tmode = QComboBox()
        self.cb_tmode.addItems(trg.MODES)
        self.sp_ta = _spin(-1e9, 1e9, 0, dec=3)
        self.sp_tb = _spin(-1e9, 1e9, 0, dec=3)
        self.sp_thyst = _spin(0, 1e9, 0, dec=3)
        self.sp_tpre = _spin(0, 86400, 0, dec=3)
        self.cb_tact = QComboBox()
        self.cb_tact.addItems(trg.ACTIONS)
        self.ed_tfolder = QLineEdit()
        btn_folder = QPushButton("...")
        btn_folder.clicked.connect(self._pick_folder)
        fr = QHBoxLayout()
        fr.addWidget(self.ed_tfolder)
        fr.addWidget(btn_folder)
        self.ed_tname = QLineEdit()
        f.addRow(self.chk_trig)
        f.addRow("Sygnał:", self.cb_tsig)
        f.addRow("Tryb:", self.cb_tmode)
        f.addRow("Wartość A:", self.sp_ta)
        f.addRow("Wartość B:", self.sp_tb)
        f.addRow("Histereza:", self.sp_thyst)
        f.addRow("Pretrigger [s]:", self.sp_tpre)
        f.addRow("Akcja:", self.cb_tact)
        f.addRow("Folder:", fr)
        f.addRow("Nazwa pliku:", self.ed_tname)

        f = group("Nagrywanie REC")
        self.ed_rfolder = QLineEdit()
        self.btn_rfolder = QPushButton("...")
        self.btn_rfolder.clicked.connect(self._pick_rec_folder)
        rr = QHBoxLayout()
        rr.addWidget(self.ed_rfolder)
        rr.addWidget(self.btn_rfolder)
        self.cb_rkind = QComboBox()                      # where REC writes: CSV file or a database
        for k in KINDS:
            self.cb_rkind.addItem(KIND_LABEL[k], k)
        self.cb_rmode = QComboBox()                      # every sample or only the changes of state (default)
        for m in STORE_MODES:
            self.cb_rmode.addItem(MODE_LABEL[m], m)
        for cb in (self.cb_rkind, self.cb_rmode):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(6)
            cb.setMinimumWidth(70)
        self.btn_rdb = QPushButton("...")
        self.btn_rdb.setToolTip("Ustawienia bazy danych (adres, baza, użytkownik / token, test połączenia)")
        self.btn_rdb.clicked.connect(self.edit_store)
        rk = QHBoxLayout()
        rk.addWidget(self.cb_rkind)
        rk.addWidget(self.btn_rdb)
        self.cb_rkind.currentIndexChanged.connect(self._rkind_changed)
        self.cb_rmode.currentIndexChanged.connect(self._rkind_changed)
        self.ed_rname = QLineEdit()
        self.ed_rname.setToolTip(PLACEHOLDERS_HELP)
        self.ed_tname.setToolTip(PLACEHOLDERS_HELP)
        f.addRow("Zapis do:", rk)
        f.addRow("Próbki:", self.cb_rmode)
        f.addRow("Folder:", rr)
        f.addRow("Nazwa pliku:", self.ed_rname)
        lv.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self._left_min = 230                           # kept up to date by _fit_left_min (content width, screen permitting)

        # ---- right side
        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(4, 4, 4, 4)
        self.plot = PlotView(self.buffer)
        right.addWidget(self.plot, 1)
        bar = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_pause = QPushButton("Pauza")
        self.btn_pause.setCheckable(True)
        self.btn_rec = QPushButton("REC")
        self.btn_rec.setCheckable(True)
        self.btn_rec.toggled.connect(lambda _on: self._blink_tick(reset=True))
        self.btn_pts = QPushButton("Punkty")
        self.btn_pts.setCheckable(True)
        self.btn_v = QPushButton("V znacznik")
        self.btn_v.setCheckable(True)
        self.btn_h = QPushButton("H znacznik")
        self.btn_h.setCheckable(True)
        self.btn_sig = QPushButton("Sygnały...")
        self.btn_diag = QPushButton("Diagnostyka…")
        self.btn_diag.setToolTip("Szczegółowa diagnostyka połączenia: opóźnienia, utracone cykle, ping, przepustowość")
        self.btn_exp = QPushButton("Eksport okna → CSV")
        self.btn_imp = QPushButton("Import CSV → wykres")
        for b in (self.btn_start, self.btn_stop, self.btn_pause, self.btn_rec, self.btn_pts,
                  self.btn_v, self.btn_h):
            bar.addWidget(b)
        bar.addStretch()
        for b in (self.btn_sig, self.btn_diag, self.btn_exp, self.btn_imp):
            bar.addWidget(b)
        right.addLayout(bar)
        self.lbl_status = PanLabel()                  # right aligned; a long text can be dragged with the mouse
        right.addWidget(self.lbl_status)

        self.split_h = FoldSplitter(Qt.Horizontal, 0, 290)   # drag the bar to resize; button / double click folds the panel
        self.split_h.addWidget(scroll)
        self.split_h.addWidget(right_w)
        self.split_h.setStretchFactor(0, 0)
        self.split_h.setStretchFactor(1, 1)
        self.split_h.setSizes([290, 1000])
        root.addWidget(self.split_h)
        self.split_h.splitterMoved.connect(self._layout_moved)
        self.split_h.foldChanged.connect(self._layout_moved)
        self.plot.splitChanged.connect(self._layout_moved)
        self.plot.legendMoved.connect(self._legend_moved)
        self.plot.legendDoubleClicked.connect(self.edit_signals)
        self.plot.legendContextMenu.connect(self._legend_menu)
        self.cb_ylayout.currentIndexChanged.connect(self._on_ylayout)

        for b, role in ((self.btn_start, "start"), (self.btn_stop, "stop"), (self.btn_pause, "pause"),
                        (self.btn_rec, "rec"), (self.btn_pts, "mark"), (self.btn_v, "mark"), (self.btn_h, "mark")):
            b.setProperty("ctl", True)
            b.setProperty("role", role)
            b.setProperty("on", False)
        for b in (self.btn_pause, self.btn_rec, self.btn_pts, self.btn_v, self.btn_h):
            b.toggled.connect(lambda on, w=b: self._set_on(w, on))

        # ---- wiring
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_pause.toggled.connect(self._on_pause)
        self.btn_rec.toggled.connect(self._on_rec)
        self.btn_pts.toggled.connect(self.plot.set_points)
        self.btn_v.toggled.connect(self.plot.set_v_mode)
        self.btn_h.toggled.connect(self.plot.set_h_mode)
        self.btn_sig.clicked.connect(self.edit_signals)
        self.btn_diag.clicked.connect(self.open_diag)
        self.btn_exp.clicked.connect(self.export_window)
        self.btn_imp.clicked.connect(self.import_csv)
        self.sp_window.valueChanged.connect(self.plot.set_window)
        self.chk_auto.toggled.connect(self._on_auto_y)
        self.sp_ymin.valueChanged.connect(self._on_y_manual)
        self.sp_ymax.valueChanged.connect(self._on_y_manual)
        self.plot.windowChanged.connect(self._on_zoomed)
        self.plot.userMoved.connect(self._on_user_moved)
        self.ed_ip.editingFinished.connect(lambda: self.titleChanged.emit(self.title()))
        for w in (self.chk_trig, self.cb_tsig, self.cb_tmode, self.cb_tact):
            (w.toggled if isinstance(w, QCheckBox) else w.currentIndexChanged).connect(self._trigger_changed)
        for w in (self.sp_ta, self.sp_tb, self.sp_thyst, self.sp_tpre):
            w.valueChanged.connect(self._trigger_changed)
        for w in (self.ed_tfolder, self.ed_tname):
            w.editingFinished.connect(self._trigger_changed)
        for w in (self.ed_rfolder, self.ed_rname):
            w.editingFinished.connect(self._collect)

    # ======================================================= buttons / layout
    @staticmethod
    def _set_on(btn: QPushButton, on: bool) -> None:
        if bool(btn.property("on")) != bool(on):
            btn.setProperty("on", bool(on))
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def apply_ctl_theme(self, theme: dict) -> None:
        """REC dot colour and blink frequency from the 'Interfejs' settings."""
        self._rec_dot = theme.get("rec_dot", self._rec_dot)
        self._rec_idle = theme.get("ctl_text", self._rec_idle)          # REC off: the dot has the colour of the text
        hz = max(0.1, float(theme.get("rec_blink_hz", 0.5)))
        self._icon_on, self._icon_off = dot_icon(self._rec_dot), dot_icon(None)
        self._icon_idle = dot_icon(self._rec_idle)
        bar, always = theme.get("bar", DEFAULT_BAR), bool(theme.get("bar_always", False))
        self.lbl_status.set_colors(theme.get("status_bg", "#2b2b2b"), theme.get("status_text", "#d0d0d0"))
        self.lbl_status.set_max_lines(int(theme.get("status_lines", 1)))
        self.split_h.set_bar(bar, always)                # the thin resize bars: colour and permanent visibility
        self.plot.split.set_bar(bar, always)
        self.blink.start(int(1000 / (2 * hz)))          # half period = dot on / dot off
        self._blink_tick(reset=True)

    def _blink_tick(self, reset: bool = False) -> None:
        self._rec_phase = True if reset else not self._rec_phase
        if not self.btn_rec.isChecked():
            self.btn_rec.setIcon(self._icon_idle)
        else:
            self.btn_rec.setIcon(self._icon_on if self._rec_phase else self._icon_off)

    def _layout_moved(self, *_) -> None:
        self._want_left = None                                       # the user's own drag wins over a pending restore
        self.ui_state["left_collapsed"] = self.split_h.collapsed
        self.ui_state["overview_collapsed"] = self.plot.split.collapsed
        # a folded pane keeps the size it had when it was last visible
        self.ui_state["left_width"] = self.split_h.saved if self.split_h.collapsed else self.split_h.sizes()[0]
        self.ui_state["overview_h"] = (self.plot.split.saved if self.plot.split.collapsed
                                       else self.plot.overview_height())
        self.layoutChanged.emit()

    def _legend_menu(self, pos) -> None:
        self._build_legend_menu().exec(pos)

    def _build_legend_menu(self) -> QMenu:
        """Right click on the legend: signals window, corner of this tab's legend, hide the legend."""
        m = QMenu(self)
        m.addAction("Sygnały…", lambda: self.edit_signals())
        corners = m.addMenu("Położenie legendy (ta karta)")
        for label, p in (("Lewy górny róg", (0, 0)), ("Prawy górny róg", (1, 0)),
                         ("Lewy dolny róg", (0, 1)), ("Prawy dolny róg", (1, 1))):
            corners.addAction(label, lambda p=p: self.set_legend_pos(*p))
        m.addSeparator()
        m.addAction("Ukryj legendę", lambda: self.legendHideRequested.emit())
        return m

    def _legend_moved(self, fx: float, fy: float) -> None:
        self.cfg.legend_pos = [round(fx, 4), round(fy, 4)]          # per tab (saved in the tab's configuration)

    def set_legend_pos(self, fx: float, fy: float) -> None:
        self.cfg.legend_pos = [float(fx), float(fy)]
        self.plot.set_legend_pos(fx, fy)

    def apply_layout(self) -> None:
        """Splitter sizes + legend position from the shared UI settings (applied once the widget has a size)."""
        st = self.ui_state
        if isinstance(st.get("left_width"), int):
            self._want_left = st["left_width"]
            self.split_h.saved = st["left_width"]
        if isinstance(st.get("overview_h"), int):
            self.plot.set_overview_height(st["overview_h"])
        if st.get("left_collapsed"):
            self._want_left = None
        else:
            self.split_h.set_collapsed(False)
        self.split_h.set_collapsed(bool(st.get("left_collapsed", False)))
        self.plot.set_overview_collapsed(bool(st.get("overview_collapsed", False)))
        self._fit_layout()

    def _fit_left_min(self) -> None:
        """The settings panel is never narrower than what its widgets need (fonts / scaling change that), unless that
        would take more than half of the tab - then the panel scrolls sideways instead."""
        try:
            sc = self.split_h.widget(0)
        except RuntimeError:                                   # the tab is already gone (a queued call)
            return
        need = sc.widget().minimumSizeHint().width() + sc.verticalScrollBar().sizeHint().width() + 2 * sc.frameWidth() + 2
        cap = max(self.width() // 2, 200)
        new = max(min(need, cap), 200)
        if new != self._left_min:
            self._left_min = new
            self.split_h.set_pane_min(new)
            if not self.split_h.collapsed and self.split_h.sizes()[0] < new and self.width() > 400:
                self.split_h.set_sizes_for(new)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.FontChange, QEvent.StyleChange, QEvent.PaletteChange) and hasattr(self, "_left_min"):
            QTimer.singleShot(0, self._fit_left_min)

    def _fit_layout(self) -> None:
        self._fit_left_min()
        total = self.width()
        if self._want_left and total > 400:
            w = max(self._left_min, min(self._want_left, total - 300))
            if not self.split_h.collapsed:
                self.split_h.set_sizes_for(w)
            if w == self._want_left:                      # the window was still too small (not laid out yet): try again
                self._want_left = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_layout()

    # ============================================================= config
    def title(self) -> str:
        return self.cfg.name.strip() or self.ed_ip.text().strip() or "PLC"

    def rename(self, name: str) -> None:
        self.cfg.name = name.strip()
        self.titleChanged.emit(self.title())

    def display_signals(self) -> list[Signal]:
        """Signals that are read from the PLC (= buffer columns, curves, CSV columns)."""
        return [s for s in self.cfg.signals if s.enabled]

    def current_values(self) -> list | None:
        """Latest value per signal of cfg.signals (None = not read now)."""
        if self.state not in ("running", "reconnecting"):
            return None
        row = self.buffer.last_row()
        if row is None:
            return None
        out, k = [], 0
        for s in self.cfg.signals:
            if s.enabled and k < len(row):
                out.append(float(row[k]))
                k += 1
            else:
                out.append(None)
        return out

    def _ip_check(self, text: str = "") -> None:
        bad = ipv4_state(self.ed_ip.text()) != ACCEPTABLE
        if bool(self.ed_ip.property("invalid")) != bad:
            self.ed_ip.setProperty("invalid", bad)
            self.ed_ip.style().unpolish(self.ed_ip)
            self.ed_ip.style().polish(self.ed_ip)

    def apply_plot_theme(self, bg: str, fg: str) -> None:
        self.plot.apply_theme(bg, fg)

    def update_method_label(self) -> None:
        t = self.cfg.conn_type
        self.lbl_method.setText(CONN_LABEL[t] if t in CONN_LABEL else t)

    def set_conn_type(self, kind: str) -> None:
        """Chosen manually or by the wizard ('Użyj zalecanej metody')."""
        self.cfg.conn_type = kind
        self.update_method_label()

    def _load_cfg(self):
        self.update_method_label()
        self._loading = True
        c = self.cfg
        self.ed_ip.setText(c.ip)
        self.sp_rack.setValue(c.rack)
        self.sp_slot.setValue(c.slot)
        self.sp_cycle.setValue(c.cycle_ms)
        self.cb_mode.setCurrentText(c.mode)
        self.sp_window.setValue(c.window_s)
        self.chk_auto.setChecked(c.auto_y)
        self.sp_ymin.setValue(c.y_min)
        self.sp_ymax.setValue(c.y_max)
        self.btn_pts.setChecked(c.show_points)
        t = c.trigger
        self.chk_trig.setChecked(t.enabled)
        self.cb_tmode.setCurrentText(t.mode)
        self.sp_ta.setValue(t.a)
        self.sp_tb.setValue(t.b)
        self.sp_thyst.setValue(t.hysteresis)
        self.sp_tpre.setValue(t.pretrigger)
        self.cb_tact.setCurrentText(t.action)
        self.ed_tfolder.setText(t.folder)
        self.ed_tname.setText(t.filename)
        self._refresh_signal_widgets(select=t.signal)
        self.plot.set_window(c.window_s)
        self.plot.set_auto_y(c.auto_y)
        self.plot.set_y_range(c.y_min, c.y_max)
        self.plot.set_points(c.show_points)
        i = self.cb_ylayout.findData(c.y_layout)
        self.cb_ylayout.setCurrentIndex(max(i, 0))
        self.plot.set_y_layout(self.cb_ylayout.currentData())
        self._on_auto_y(c.auto_y)
        self.ed_rfolder.setText(c.rec_folder)
        self.ed_rname.setText(c.rec_filename)
        self.cb_rkind.setCurrentIndex(max(self.cb_rkind.findData(c.store.kind), 0))
        self.cb_rmode.setCurrentIndex(max(self.cb_rmode.findData(c.store.mode), 0))
        self._rkind_changed()
        self.plot.set_legend_pos(float(c.legend_pos[0]), float(c.legend_pos[1]))
        self._loading = False
        self._trigger_changed()

    def _collect(self) -> TabConfig:
        c = self.cfg
        c.ip = self.ed_ip.text().strip()
        c.rack, c.slot = self.sp_rack.value(), self.sp_slot.value()
        c.cycle_ms = self.sp_cycle.value()
        c.mode = self.cb_mode.currentText()
        c.window_s = self.sp_window.value()
        c.auto_y = self.chk_auto.isChecked()
        c.y_min, c.y_max = self.sp_ymin.value(), self.sp_ymax.value()
        c.show_points = self.btn_pts.isChecked()
        c.y_layout = self.cb_ylayout.currentData()
        c.rec_folder, c.rec_filename = self.ed_rfolder.text().strip(), self.ed_rname.text().strip()
        c.store.kind, c.store.mode = self.cb_rkind.currentData(), self.cb_rmode.currentData()
        t = c.trigger
        t.enabled = self.chk_trig.isChecked()
        t.signal = self.cb_tsig.currentText()
        t.mode = self.cb_tmode.currentText()
        t.a, t.b = self.sp_ta.value(), self.sp_tb.value()
        t.hysteresis, t.pretrigger = self.sp_thyst.value(), self.sp_tpre.value()
        t.action = self.cb_tact.currentText()
        t.folder, t.filename = self.ed_tfolder.text().strip(), self.ed_tname.text().strip()
        return c

    def to_config(self) -> TabConfig:
        return self._collect()

    def load_config(self, cfg: TabConfig) -> bool:
        """Replace this tab's configuration (signals, trigger, ranges) in place; only while stopped."""
        if self.state != "stopped":
            return False
        cfg.name = self.cfg.name                       # the tab keeps its own title
        self.cfg = cfg
        self.buffer.reset(len(self.display_signals()))
        self._run_signals = []
        self.plot.clear_trigger_marks()
        self._noname_asked = False
        self._load_cfg()
        self.titleChanged.emit(self.title())
        return True

    def _refresh_signal_widgets(self, select: str | None = None):
        keep = select if select is not None else self.cb_tsig.currentText()
        self.cb_tsig.blockSignals(True)
        self.cb_tsig.clear()
        names = [s.name for s in self.display_signals()]
        self.cb_tsig.addItems(names)
        if keep in names:
            self.cb_tsig.setCurrentText(keep)
        self.cb_tsig.blockSignals(False)
        self.plot.set_signals(self.display_signals())

    # ============================================================ handlers
    def _on_auto_y(self, on: bool):
        manual_ok = self.cb_ylayout.currentData() == "offset"          # Auto Y / Y min / Y max: only without lanes
        self.chk_auto.setEnabled(manual_ok)
        self.sp_ymin.setEnabled(manual_ok and not on)
        self.sp_ymax.setEnabled(manual_ok and not on)
        self.plot.set_auto_y(on)

    def _on_ylayout(self, *_):
        if self._loading:
            return
        self.cfg.y_layout = self.cb_ylayout.currentData()
        self.plot.set_y_layout(self.cfg.y_layout)
        self._on_auto_y(self.chk_auto.isChecked())

    def _on_y_manual(self, *_):
        self.plot.set_y_range(self.sp_ymin.value(), self.sp_ymax.value())

    def _on_zoomed(self, width: float):
        self.sp_window.blockSignals(True)
        self.sp_window.setValue(min(max(width, 0.1), 86400))
        self.sp_window.blockSignals(False)
        if not self.chk_auto.isChecked():
            lo, hi = self.plot.y_range
            for sp, v in ((self.sp_ymin, lo), (self.sp_ymax, hi)):
                sp.blockSignals(True)
                sp.setValue(v)
                sp.blockSignals(False)

    def _on_user_moved(self):
        if self.state in ("running", "reconnecting") and not self.paused:
            self.btn_pause.setChecked(True)

    def _on_pause(self, on: bool):
        self.paused = on
        self.btn_pause.setText("Wznów" if on else "Pauza")
        live = self.state in ("running", "reconnecting") and not on
        self.plot.set_follow(live)
        if on:
            self.plot.set_follow(False)
        elif self.trig_state == "hold":
            self.engine.reset()
            self.trig_state = "armed" if self.cfg.trigger.enabled else "idle"
        self.plot.touch()

    def _trigger_changed(self, *_):
        if self._loading:
            return
        t = self._collect().trigger
        self.sp_tb.setEnabled(t.mode == "between")
        self.engine = trg.TriggerEngine(t)
        if self.state == "running" and t.enabled and self.trig_state in ("idle", "armed"):
            self.trig_state = "armed"
        elif not t.enabled and self.trig_state != "hold":
            self.trig_state = "idle"

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder zapisu", self._abs_folder())
        if d:
            self.ed_tfolder.setText(d)
            self._trigger_changed()

    def _pick_rec_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder nagrań REC", self._abs_folder(self.ed_rfolder.text().strip()
                                                                                          or "rec"))
        if d:
            self.ed_rfolder.setText(d)
            self._collect()

    # ========================================================== lifecycle
    def _warn_if_scanned_elsewhere(self, ip: str) -> None:
        """Information only: another program instance (another Windows user) already scans this PLC."""
        others = sessions.others_scanning(ip)
        if not others:
            return
        from .sessions_dialog import short_time
        lines = "\n".join(f"• {o['user']}" + (f" (karta „{o['title']}”)" if o["title"] else "")
                          + (f" – od {short_time(o['since'])}" if o["since"] else "") for o in others)
        QMessageBox.warning(self, "S7Trace — sterownik jest już skanowany",
                            f"Sterownik {ip} jest już skanowany przez:\n{lines}\n\nMożesz kontynuować, ale każdy dodatkowy "
                            "skan obciąża sterownik i zajmuje jedno z jego połączeń.")

    def start(self):
        if self.state != "stopped":
            return
        c = self._collect()
        if ipv4_state(c.ip) != ACCEPTABLE:
            QMessageBox.warning(self, "S7Trace", "Niepoprawny adres IP. Wpisz adres IPv4, np. 192.168.0.1 "
                                "(opcjonalnie z portem: 127.0.0.1:1102).")
            self.ed_ip.setFocus()
            return
        writes_trigger = c.trigger.enabled and "CSV" in c.trigger.action and "{confname}" in c.trigger.filename
        writes_rec = self.btn_rec.isChecked() and "{confname}" in c.rec_filename
        if writes_trigger or writes_rec:                 # ask for the configuration name before the first file is written
            self._confname_for_file()
        run = self.display_signals()
        method = self._resolve_method(run)
        if method is None:
            return
        if not run:
            QMessageBox.information(self, "S7Trace", "Brak sygnałów do pobierania. Dodaj sygnały albo zaznacz "
                                    "„Pobierz” w oknie 'Sygnały...'.")
            return
        self._warn_if_scanned_elsewhere(c.ip)
        self.buffer.reset(len(run))
        self._run_signals = [Signal.from_dict(s.to_dict()) for s in run]
        self.plot.set_signals(run)
        self.plot.clear_trigger_marks()
        self._pending.clear()
        self.engine = trg.TriggerEngine(c.trigger)
        self.trig_state = "armed" if c.trigger.enabled else "idle"
        self.btn_pause.setChecked(False)
        if self.ui_state.get("diag_ping", True):
            self.set_ping(True)
        self.acq = acq = ProcAcquirer(
            c.ip, c.rack, c.slot, c.cycle_ms, run, c.mode, self.buffer,
            on_state=lambda s, m: self._stateRaw.emit(s, m),
            on_sample=lambda t, v: self._pending.append((t, list(v))),
            driver={"type": method, "opts": dict(c.conn)} if method != "s7" else None,
            on_info=lambda d: self._infoRaw.emit(d))
        self.plot.time_source = lambda a=acq: (time.perf_counter() - a.t0) if a.t0 else self.buffer.last_time()
        self.loaded = None
        self.state = "connecting"
        self.status_msg = f"Łączenie z {c.ip}…"
        self._set_buttons()
        self.stateChanged.emit(self.state)
        acq.start()

    def stop(self):
        if self.acq and self.state != "stopped":
            self.acq.stop()
            self.status_msg = "Zatrzymywanie…"

    # ------------------------------------------------- connection method
    def _resolve_method(self, run: list[Signal]) -> str | None:
        """Method for this Start: the manual choice, or the wizard's pick in automatic mode. None = do not start."""
        from .wizard_dialog import WizardDialog
        if not run:
            return self.cfg.conn_type if self.cfg.conn_type != "auto" else "s7"     # start() reports "no signals"
        fam = family_of(run)
        if fam is None:
            QMessageBox.warning(self, "S7Trace", "Pobierane sygnały używają różnych metod (np. S7 i OPC UA). "
                                "W jednej karcie wszystkie pobierane sygnały muszą mieć źródło z jednej rodziny "
                                "(I/Q/M/DB, OPC, WEB albo MBx).")
            return None
        kind = self.cfg.conn_type
        if kind == "auto":
            order = [fam] + [m for m in ("s7", "opcua", "webapi", "modbus") if m != fam] if fam else None
            dlg = WizardDialog(self, auto=True, methods=order, parent=self)   # signals' own family is probed first
            dlg.exec()
            res = dlg.result
            if res is None:
                return None
            ok = [m for m in ("s7", "opcua", "webapi", "modbus") if res.methods.get(m, {}).get("ok")]
            if fam in ok:
                if fam == "s7":                                  # the rack/slot that actually worked
                    self.sp_rack.setValue(res.rack)
                    self.sp_slot.setValue(res.slot)
                self.status_msg = f"Automatycznie wybrano: {CONN_LABEL[fam]}."
                return fam
            if ok and fam:
                QMessageBox.warning(self, "S7Trace", f"Sygnały używają metody „{CONN_LABEL[fam]}”, która nie działa, "
                                    f"ale działa „{CONN_LABEL[ok[0]]}”. Zmień źródło sygnałów (np. OPC UA – przycisk "
                                    "„Z OPC UA…” w oknie Sygnały) lub włącz brakującą funkcję w sterowniku "
                                    "(patrz Kreator połączenia).")
            return None                      # nothing usable: the wizard window already showed the report
        if fam is not None and fam != kind:
            QMessageBox.warning(self, "S7Trace", f"Wybrana metoda to „{CONN_LABEL[kind]}”, a sygnały mają źródła "
                                f"{', '.join(SOURCE_OF[fam])}. Zmień metodę w Ustawienia → Metoda połączenia "
                                "albo źródła sygnałów.")
            return None
        return kind

    # ------------------------------------------------------- device data
    def _on_info(self, d: dict) -> None:
        """Data of the PLC read right after a (re)connection: replaces the previous data of this address."""
        self.device, self._device_ip = d, self.ed_ip.text()
        self._show_device()

    def _ip_changed_device(self, *_) -> None:
        if self.device is not None and self.ed_ip.text() != self._device_ip:      # another device: the data is stale
            self.device = None
            self._show_device()

    def _show_device(self) -> None:
        d = self.device
        if d is None:
            self.lbl_dev.setText("<i>Brak połączenia ze sterownikiem – dane zostaną pobrane po pierwszym połączeniu.</i>")
            self.lbl_dev.setCursor(Qt.ArrowCursor)
            self.lbl_dev.setToolTip("Dane sterownika pojawią się po pierwszym połączeniu.")
            return
        info = d.get("info") or {}
        if d.get("method") == "other" or not info:
            self.lbl_dev.setText("<i>Brak danych sterownika dla tej metody połączenia.</i>")
        else:
            rows = "".join(f"<tr><td>{label}:&nbsp;&nbsp;</td><td><b>{html.escape(str(info.get(key) or '—'))}</b></td></tr>"
                           for label, key in DEVICE_ROWS)       # a table: all values start in one vertical line
            self.lbl_dev.setText(f'<table cellspacing="0" cellpadding="0">{rows}</table>')
        self.lbl_dev.setCursor(Qt.PointingHandCursor)
        self.lbl_dev.setToolTip("Kliknij, aby zobaczyć pełne informacje o sterowniku (zakładka „Sterownik i czas”).")

    def device_result(self):
        """The stored device data as a detect.DetectResult (for the 'Sterownik i czas' window)."""
        from ..core.detect import DetectResult
        d = self.device or {}
        res = DetectResult(host=self._device_ip)
        res.info = dict(d.get("info") or {})
        for k in ("plc_time", "plc_time_utc", "time_diff_local", "time_diff_utc"):
            if k in d:
                setattr(res, k, d[k])
        res.rack, res.slot = d.get("rack", 0), d.get("slot", 2)
        return res

    def open_device_info(self) -> None:
        if self.device is None:
            return
        from .wizard_dialog import WizardDialog
        WizardDialog(self, show_tab=1, stored=self.device_result(), parent=self.window()).exec()

    # ---------------------------------------------------------- diagnostics
    def open_diag(self) -> None:
        if self.diag_dlg is None:
            self.diag_dlg = DiagDialog(self, self.window())
        self.diag_dlg.show()
        self.diag_dlg.raise_()
        self.diag_dlg.activateWindow()

    def diag_closed(self) -> None:
        self.diag_dlg = None
        if self.state == "stopped":
            self._stop_ping()

    def set_ping(self, on: bool) -> None:
        """ICMP probe to the PLC address (independent of the S7 connection)."""
        if not on:
            self._stop_ping()
            return
        if ipv4_state(self.ed_ip.text()) != ACCEPTABLE:
            return
        host = parse_host(self.ed_ip.text())[0]
        p = self.ping_probe
        if p is not None and p.is_alive() and p.host == host:
            return
        self._stop_ping()
        self.ping_probe = PingProbe(host)
        self.ping_probe.start()

    def _stop_ping(self) -> None:
        if self.ping_probe is not None:
            self.ping_probe.stop()                  # the object stays: its statistics remain readable

    def shutdown(self):
        self._stop_ping()
        if self.diag_dlg is not None:
            self.diag_dlg.close()
        if self.acq:
            self.acq.stop()
            self.acq.join(2.0)
        self._close_recorder()
        self.timer.stop()

    def _on_state(self, state: str, msg: str):
        """Runs in GUI thread (queued from worker)."""
        if state == "running":
            if self.state in ("connecting", "stopped"):
                self.start_wall = datetime.now()
            self.status_msg = msg
            self.state = "running"
            ip_history.add(self.ed_ip.text())                  # an address that really connected: remembered per user
            self.plot.set_follow(not self.paused)
            if self.btn_rec.isChecked() and not self.recorder:
                self._open_recorder()
        elif state == "reconnecting":
            self.state = "reconnecting"
            self.status_msg = msg
        elif state in ("stopped", "error"):
            self.state = "stopped"
            self.status_msg = msg
            self.plot.set_follow(False)
            if self.btn_pause.isChecked():              # Pauza / Wznów only makes sense while a connection is active
                self.btn_pause.setChecked(False)
            self._close_recorder(ask=True)
            self._rec_info = {}
            if self.diag_dlg is None:
                self._stop_ping()
            if self.acq is not None:
                self._drain()
            if state == "error":
                QMessageBox.warning(self, "S7Trace — błąd połączenia", msg)
                self.stateChanged.emit("error")
        else:
            self.state = state
            self.status_msg = msg
        self._set_buttons()
        if state != "error":
            self.stateChanged.emit(self.state)

    def _set_buttons(self):
        stopped = self.state == "stopped"
        self.btn_start.setEnabled(stopped)
        self.btn_stop.setEnabled(not stopped)
        self._set_on(self.btn_start, not stopped)       # "on" = connection is active
        self._set_on(self.btn_stop, stopped)            # "on" = connection is stopped
        self.btn_pause.setEnabled(not stopped)
        self.btn_imp.setEnabled(stopped)
        for w in self._conn_widgets:
            w.setEnabled(stopped)

    # ============================================================== tick
    def apply_render(self, cfg: dict) -> None:
        self._render = render_cfg.normalize(cfg)
        self.timer.setInterval(max(int(1000 / self._render["fps"]), 1))
        self.plot.apply_render(self._render)

    def _tick(self):
        self._drain()                                          # data, trigger and REC always run
        if self._render["pause_hidden"] and (not self.plot.isVisible() or self.window().isMinimized()):
            self._skipped = True                               # nobody sees the chart: do not compute it
        else:
            if self._skipped:
                self._skipped = False
                self.plot.touch()                              # up to date at once when the tab comes back
            self.plot.refresh()
        self._stat_tick += 1
        if self._stat_tick % 8 == 0:
            self._update_status()

    def _drain(self):
        tc = self.cfg.trigger
        names = [s.name for s in self._run_signals]
        while self._pending:
            t, vals = self._pending.popleft()
            if self.recorder:
                self.recorder.write(t, vals)
            if self.trig_state == "armed" and tc.enabled and tc.signal in names \
                    and names.index(tc.signal) < len(vals):
                if self.engine.feed(vals[names.index(tc.signal)]):
                    self.trig_t, self.trig_win = t, self.plot.window
                    pre = min(tc.pretrigger, self.trig_win)
                    self.trig_post_end = t + max(self.trig_win - pre, 0.0)
                    self.trig_state = "post"
                    self.plot.mark_trigger(t)
            if self.trig_state == "post" and t >= self.trig_post_end:
                self._trigger_action()

    def _trigger_action(self):
        tc = self.cfg.trigger
        pre = min(tc.pretrigger, self.trig_win)
        x0 = self.trig_t - pre
        x1 = x0 + self.trig_win
        note = ""
        if "CSV" in tc.action:
            try:
                path = self._save_range(x0, x1, tc.filename, "snapshot")
                note = f"Trigger: zapisano {path}"
            except Exception as e:
                note = f"Trigger: błąd zapisu CSV — {e}"
        if "Pauza" in tc.action:
            self.trig_state = "hold"
            self.btn_pause.blockSignals(True)
            self.btn_pause.setChecked(True)
            self.btn_pause.setText("Wznów")
            self.btn_pause.blockSignals(False)
            self.paused = True
            self.plot.set_follow(False)
            self.plot.set_view(x0, x1)
            self._on_zoomed(x1 - x0)
            note = note or "Trigger: wstrzymano (Wznów = ponowne uzbrojenie)."
        else:
            self.engine.reset()
            self.trig_state = "armed"
        if note:
            self.status_msg = note

    def _ping_text(self) -> str:
        p = self.ping_probe.snapshot() if self.ping_probe is not None and self.ping_probe.is_alive() else None
        if not p or not p["sent"]:
            return ""
        last = f"{p['last']:.0f} ms" if p["last"] is not None else "brak odp."
        return f" | Ping: <b>{last}</b>, utrata <b>{p['loss_pct']:.1f}%</b>"

    def _update_status(self):
        hint = (" | <b>Punkty ukryte: za dużo próbek w oknie – przybliż wykres albo zwiększ limit "
                "(Ustawienia → Renderowanie wykresu)</b>") if self.btn_pts.isChecked() and self.plot.points_hidden else ""
        if self.acq and self.state in ("running", "reconnecting"):
            st = self.acq.stats
            st.gui_lag_ms = self.plot.gui_lag_ms
            self.lbl_status.setText(
                f"PLC comm lag Avg: <b>{st.avg_lag:.1f} ms</b> (n=<b>{st.n}</b>), Last: <b>{st.last_lag:.1f} ms</b> | "
                f"GUI lag: <b>{st.gui_lag_ms:.1f} ms</b>  Missed: <b>{st.missed} ({st.missed_pct:.1f}%)</b>"
                f"{self._ping_text()}{self._rec_status()}  <b>{html.escape(self.status_msg)}</b>{hint}")
        else:
            self.lbl_status.setText(f"<b>{html.escape(self.status_msg)}</b>{hint}")
        tip = html.unescape(re.sub(r"<[^>]+>", "", self.lbl_status.text()))
        if tip != self.lbl_status.toolTip():
            self.lbl_status.setToolTip(tip)                          # the full text when it does not fit

    # ================================================================ IO
    def _abs_folder(self, folder: str | None = None) -> str:
        f = (self.cfg.trigger.folder if folder is None else folder) or "snapshots"
        return f if os.path.isabs(f) else os.path.join(data_dir(), f)       # relative: in the user's Documents\\S7Trace

    def _confname_for_file(self) -> str:
        """{confname}: the configuration's name; without one the user is asked (fallback 'no_name')."""
        n = self.cfg.conf_name.strip()
        if n:
            return _sanitize(n)
        if not self._noname_asked:
            self._noname_asked = True
            name, ok = QInputDialog.getText(
                self, "Nazwa konfiguracji",
                "Ta konfiguracja nie ma jeszcze nazwy, a jest użyta w nazwie pliku ({confname}).\n"
                "Podaj nazwę konfiguracji (puste = no_name):")
            if ok and name.strip():
                self.cfg.conf_name = name.strip()
                return _sanitize(self.cfg.conf_name)
        return "no_name"

    def _file_name(self, template: str, prefix: str, folder: str | None = None) -> str:
        now = datetime.now()
        tpl = template or f"{prefix}_{{confname}}_{{ip}}_{{tab}}_{{date}}_{{time}}.csv"
        conf = self._confname_for_file() if "{confname}" in tpl else ""
        name = tpl.format_map(_Names(
            tab=_sanitize(self.title()), date=now.strftime("%Y-%m-%d"), time=now.strftime("%H-%M-%S"),
            confname=conf, ip=_sanitize(parse_host(self.ed_ip.text())[0])))
        if not name.lower().endswith(".csv"):
            name += ".csv"
        folder = self._abs_folder(folder)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, _sanitize_filename(name))
        base, ext = os.path.splitext(path)
        n = 1
        while os.path.exists(path):
            path = f"{base}_{n}{ext}"
            n += 1
        return path

    def _save_range(self, x0: float, x1: float, template: str, prefix: str) -> str:
        path = self._file_name(template, prefix)
        self._write_range(path, x0, x1)
        return path

    def _write_range(self, path: str, x0: float, x1: float) -> None:
        t, v = self.buffer.snapshot(x0, x1)
        m = (t >= x0) & (t <= x1)
        if not m.any():
            raise ValueError("brak próbek w zakresie")
        sigs = self._run_signals or self.display_signals()
        write_csv(path, sigs, t[m], v[m], self.start_wall)

    def export_window(self):
        x0, x1 = self.plot.view_range()
        if len(self.buffer) == 0:
            QMessageBox.information(self, "S7Trace", "Brak danych do eksportu.")
            return
        default = self._file_name(self.cfg.trigger.filename, "window")
        path, _ = QFileDialog.getSaveFileName(self, "Eksport okna → CSV", default, "CSV (*.csv)")
        if not path:
            return
        try:
            self._write_range(path, x0, x1)
            self.status_msg = f"Wyeksportowano okno do {path}"
            self._update_status()
        except Exception as e:
            QMessageBox.warning(self, "S7Trace", f"Eksport nie powiódł się: {e}")

    def import_csv(self):
        if self.state != "stopped":
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import CSV → wykres", self._abs_folder(), "CSV (*.csv *.txt)")
        if not path:
            return
        try:
            sigs, t, v = read_csv(path)
        except Exception as e:
            QMessageBox.warning(self, "S7Trace", f"Import nie powiódł się: {e}")
            return
        self._show_loaded(sigs, t, v, f"Zaimportowano {len(t)} próbek z {os.path.basename(path)}")

    def _show_loaded(self, sigs, t, v, message: str, info: dict | None = None) -> None:
        self.loaded = info                                   # what the tab shows (tooltip of the tab); None = a live tab
        self.cfg.signals = sigs
        self._run_signals = [Signal.from_dict(s.to_dict()) for s in sigs]
        self.buffer.load(t, v)
        self._refresh_signal_widgets()
        self.btn_pause.setChecked(False)
        self.plot.set_follow(False)
        self.plot.fit_all()
        self._on_zoomed(self.plot.window)
        self.status_msg = message
        self._update_status()

    def _connected(self) -> bool:
        return self.state in ("running", "connecting", "reconnecting")

    def _ask_target(self, active: bool) -> str:
        """'new' / 'here' / '' (cancel): where a recording from the database is opened."""
        box = QMessageBox(self)
        box.setWindowTitle("Otwieranie przebiegu z bazy")
        if active:
            box.setText("Ta karta ma aktywne połączenie ze sterownikiem, więc przebieg z bazy zostanie otwarty w nowej karcie.")
            new = box.addButton("Otwórz w nowej karcie", QMessageBox.AcceptRole)
            here = None
        else:
            box.setText("Ta karta zawiera dane. Gdzie otworzyć przebieg z bazy?")
            new = box.addButton("Nowa karta", QMessageBox.AcceptRole)
            here = box.addButton("Bieżąca karta (zastąpi dane)", QMessageBox.DestructiveRole)
        box.addButton("Anuluj", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        return "new" if clicked is new else ("here" if here is not None and clicked is here else "")

    def _target_for_recording(self):
        """The tab that receives a recording: this one when it is empty, otherwise the user chooses (a new tab is the only
        choice while the connection is active). None = cancelled."""
        active = self._connected()
        if not active and len(self.buffer) == 0 and getattr(self, "loaded", None) is None:
            return self
        answer = self._ask_target(active)
        if answer == "here":
            return self
        if answer == "new":
            if self.new_tab_cb is None:                      # (a tab outside the main window)
                return None if active else self
            cfg = TabConfig()
            cfg.store = dataclasses.replace(self.cfg.store)
            return self.new_tab_cb(cfg)
        return None

    def import_db(self):
        """Plik → Przegląd nagrań: a recording (or a time range of it) from SQLite / InfluxDB / TimescaleDB. It opens in
        this tab when it is empty, otherwise the user chooses the tab; with an active connection it is always a new one."""
        from .store_dialog import StoreImportDialog
        d = StoreImportDialog(self.cfg.store, self, can_load=True, base_dir=data_dir())
        if not d.exec() or d.result is None:
            return
        target = self._target_for_recording()
        if target is not None:
            target.load_recording(*d.result, note=d.note)

    def load_recording(self, meta: dict, t_us, v, used: StoreConfig, note: str = "") -> None:
        """Shows a recording read from a database; the tab takes the title of the recording."""
        self.cfg.store = dataclasses.replace(used, kind=self.cfg.store.kind, mode=self.cfg.store.mode)   # keep the connection settings
        sigs = [Signal.from_dict(s) for s in meta["signals"]]
        self.start_wall = datetime.fromtimestamp(float(t_us[0]) / 1e6)
        t = (t_us - t_us[0]) / 1e6
        name = (meta.get("title") or meta.get("conf") or meta.get("tab") or meta.get("id") or "").strip()
        self._show_loaded(sigs, t, v, f"Wczytano {len(t)} próbek z bazy ({meta.get('tab') or meta['id']}){note}",
                          {"meta": meta, "used": used, "samples": len(t)})
        if name:
            self.rename(name)

    # ---- the tooltip of the tab: everything about what the tab holds and where it records
    @staticmethod
    def _db_rows(c: StoreConfig) -> list[tuple[str, str]]:
        rows = [("Cel zapisu", KIND_LABEL.get(c.kind, c.kind)), ("Adres / plik", c.describe())]
        if c.kind == "csv":
            return rows
        rows += [("Próbki", MODE_LABEL.get(c.mode, c.mode)),
                 ("Pełny stan co", f"{c.keyframe_min:g} min" if c.keyframe_min else "wyłączony"),
                 ("Wysyłanie paczek co", f"{c.batch_s:g} s"), ("Kolejka w pamięci", f"{c.queue_max:,} wpisów".replace(",", " "))]
        if c.kind in StoreConfig.NETWORK:
            rows += [("Bufor na dysku", f"{c.spool_mb} MB" if c.spool_mb else "wyłączony"),
                     ("Limit odpowiedzi serwera", f"{c.http_timeout_s:g} s")]
        if c.kind == "sqlite":
            rows += [("Nowy plik", "co dzień" if c.rotate_daily else (f"po {c.rotate_mb} MB" if c.rotate_mb else "nigdy")),
                     ("Folder", "wspólny (ProgramData)" if c.sqlite_shared else "konto użytkownika")]
        if c.kind == "timescale":
            rows.append(("Kompresja", f"po {c.compress_days} dniach" if c.compress_days else "wyłączona"))
        rows += [("Odczyt: maks. punktów", f"{c.read_max_points:,}".replace(",", " ")),
                 ("Kosz", f"{c.trash_days} dni" if c.trash_days else "bez kosza")]
        return rows

    def tooltip_html(self) -> str:
        esc = html.escape
        out: list[str] = []

        def sec(title: str) -> None:
            out.append(f"<tr><td colspan='2' style='padding-top:4px'><u><b>{esc(title)}</b></u></td></tr>")

        def row(k: str, val) -> None:
            out.append(f"<tr><td>{esc(k)}:&nbsp;</td><td><b>{esc(str(val))}</b></td></tr>")

        def when(us) -> str:
            return datetime.fromtimestamp(float(us) / 1e6).strftime("%Y-%m-%d %H:%M:%S") if us else "–"

        info = getattr(self, "loaded", None)
        if info and info.get("meta"):
            m = info["meta"]
            sec("Przebieg wczytany z bazy danych")
            row("Tytuł", m.get("title") or "–")
            for label, key in (("Uwagi", "notes"), ("Etykiety", "tags"), ("Autor (konto)", "owner"), ("Komputer", "computer")):
                row(label, m.get(key) or "–")
            row("Początek", when(m.get("start_us")))
            row("Koniec", when(m.get("end_us")))
            row("Tryb zapisu", MODE_LABEL.get(m.get("mode"), m.get("mode") or "–"))
            if m.get("keyframe_min"):
                row("Pełny stan co", f"{m['keyframe_min']:g} min")
            names = [x.get("name", "") for x in m.get("signals", [])]
            row("Sygnały", f"{len(names)}: " + ", ".join(names[:8]) + (" …" if len(names) > 8 else ""))
            row("Wczytanych próbek", info.get("samples", 0))
            row("Sterownik (z zapisu)", " / ".join(x for x in (m.get("ip"), m.get("tab"), m.get("conf")) if x) or "–")
            sec("Baza danych, z której wczytano")
            for k, val in self._db_rows(info.get("used") or self.cfg.store):
                row(k, val)
        else:
            sec("Połączenie ze sterownikiem")
            row("Stan", {"running": "praca", "connecting": "łączenie", "reconnecting": "ponawianie połączenia",
                         "stopped": "zatrzymana", "error": "błąd"}.get(self.state, self.state))
            row("Adres IP", self.ed_ip.text() or "–")
            row("Rack / Slot", f"{self.sp_rack.value()} / {self.sp_slot.value()}")
            row("Cykl", f"{self.sp_cycle.value()} ms")
            row("Tryb komunikacji", self.cb_mode.currentText())
            row("Metoda", re.sub(r"<[^>]+>", "", self.lbl_method.text()) or "–")
            sec("Baza danych (zapis REC)")
            for k, val in self._db_rows(self.cfg.store):
                row(k, val)
        return f"<b>{esc(self.title())}</b><table cellspacing='0' cellpadding='1'>{''.join(out)}</table>"

    def edit_signals(self):
        locked = self.state != "stopped"
        c = self.cfg
        opts = {"autonumber": c.autonumber, "name_mode": c.name_mode, "own_name": c.own_name,
                "offset_step": c.offset_step}
        dlg = SignalsDialog(self.cfg.signals, locked, self.symbols, opts, self.current_values,
                            self.other_tabs, self.ui_state.setdefault("signals_dialog", {}), self._browse_opc, self)
        if not dlg.exec():
            return
        c.autonumber, c.name_mode = dlg.opts["autonumber"], dlg.opts["name_mode"]
        c.own_name, c.offset_step = dlg.opts["own_name"], dlg.opts["offset_step"]
        self.apply_signals(dlg.signals(), locked)

    def _browse_opc(self) -> list[Signal]:
        from .opc_browser import OpcBrowser
        dlg = OpcBrowser(self.ed_ip.text().split(":")[0].strip(), dict(self.cfg.conn), self, len(self.cfg.signals))
        return dlg.signals() if dlg.exec() else []

    def apply_signals(self, new: list[Signal], locked: bool) -> None:
        old = self.cfg.signals
        if locked:       # structure of existing signals is fixed while running: display attributes change,
            for o, n in zip(old, new):                      # new signals can only be appended at the end
                o.name, o.offset_y, o.gain, o.share, o.color = n.name, n.offset_y, n.gain, n.share, n.color
                o.comment, o.plot, o.fmt = n.comment, n.plot, n.fmt
            self._append_live(new[len(old):])
        else:
            addr = lambda L: [(s.source, s.dtype, s.db, s.byte, s.bit) for s in L if s.enabled]
            if addr(old) != addr(new) or sum(s.enabled for s in new) != self.buffer.n:
                self.buffer.reset(sum(s.enabled for s in new))
            self.cfg.signals = new
            self._run_signals = [Signal.from_dict(s.to_dict()) for s in new if s.enabled]
        self._refresh_signal_widgets()
        self.plot.touch()

    def _append_live(self, added: list[Signal]) -> None:
        """Add signals during a running connection: buffer gets NaN-filled columns, the acquisition process
        gets the longer list and starts reading them from its next cycle."""
        if not added:
            return
        self.cfg.signals.extend(added)
        fetched = [Signal.from_dict(s.to_dict()) for s in added if s.enabled]
        if not fetched:
            return
        self.buffer.add_columns(len(fetched))              # first the buffer, then the reader (row widths)
        self._run_signals.extend(fetched)
        if self.acq is not None and self.state != "stopped":
            self.acq.update_signals(self._run_signals)
        if self.recorder:                                  # new header = new REC file (same title, no new question)
            self._close_recorder()
            self._open_recorder(ask=False)

    # ================================================================ REC
    def _on_rec(self, on: bool):
        if on and self.state == "running":
            self._open_recorder()
        elif not on:
            self._close_recorder(ask=True)
            self._rec_info = {}

    def _rkind_changed(self, *_) -> None:
        """CSV uses the folder / file name fields, databases use their own settings (button next to the list)."""
        csv_ = self.cb_rkind.currentData() == "csv"
        for w in (self.ed_rfolder, self.ed_rname, self.btn_rfolder):
            w.setEnabled(csv_)
        self.btn_rdb.setEnabled(not csv_)
        if not self._loading:
            self._collect()

    def edit_store(self, pick: bool = False) -> None:
        """Settings of the REC database. `pick` (menu Ustawienia): when the tab records to CSV, ask which database."""
        from .store_dialog import StoreDialog
        kind = self.cb_rkind.currentData()
        if kind == "csv":
            if not pick:
                return
            labels = [KIND_LABEL[k] for k in KINDS if k != "csv"]
            label, ok = QInputDialog.getItem(self, "Zapis nagrań w bazie", "Baza danych:", labels, 0, False)
            if not ok:
                return
            kind = next(k for k in KINDS if k != "csv" and KIND_LABEL[k] == label)
            self.cb_rkind.setCurrentIndex(self.cb_rkind.findData(kind))        # the tab records there from now on
        d = StoreDialog(self.cfg.store, kind, self)
        if d.exec():
            self.cfg.store = d.config()

    def open_spools(self) -> None:
        """Ustawienia -> Zaległe bufory: data a closed recording could not deliver (server was away)."""
        from .store_dialog import SpoolDialog
        SpoolDialog(self.cfg.store, data_dir(), self).exec()

    def _rec_status(self) -> str:
        r = self.recorder
        return f" | REC: <b>{html.escape(r.status())}</b>" if isinstance(r, DbRecorder) else ""

    def _open_recorder(self, ask: bool = True):
        try:
            c = self._collect()
            if c.store.kind == "csv":
                path = self._file_name(c.rec_filename or DEFAULT_REC_NAME, "REC", c.rec_folder or "rec")
                self.recorder = CsvRecorder(path, self._run_signals, self.start_wall, c.store.mode)
            else:
                from .store_dialog import RecInfoDialog
                mode, info = c.store.title_ask, dict(self._rec_info)
                if ask and mode == "start":                    # question first, recording after the answer
                    d = RecInfoDialog(info.get("title") or c.conf_name, info.get("notes", ""), info.get("tags", ""),
                                      "Nazwa nagrania – zostanie zapisana w bazie razem z nagraniem.",
                                      "Rozpocznij nagrywanie", "Anuluj REC", self)
                    if not d.exec():
                        self.recorder = None
                        self.btn_rec.setChecked(False)
                        return
                    info = d.values()
                self._rec_info = info
                self.recorder = DbRecorder(
                    c.store, self._run_signals, self.start_wall,
                    {"name": self.title(), "ip": c.ip, "tab": self.title(), "conf": c.conf_name, **info},
                    base_dir=data_dir())
                path = self.recorder.path
                if c.store.kind in StoreConfig.NETWORK:
                    self._probe_db(c.store, self.recorder.session)
                if ask and mode == "during":                   # recording runs; the window opens beside it
                    self._show_info_dialog(info, c.conf_name)
            self.status_msg = f"REC → {path}"
        except Exception as e:
            self.recorder = None
            self.btn_rec.setChecked(False)
            QMessageBox.warning(self, "S7Trace", f"Nie można rozpocząć nagrywania: {e}")

    def _show_info_dialog(self, info: dict, default_title: str) -> None:
        from .store_dialog import RecInfoDialog
        rec = self.recorder
        d = RecInfoDialog(info.get("title") or default_title, info.get("notes", ""), info.get("tags", ""),
                          "Nagrywanie trwa. Nadaj nazwę nagraniu – możesz to zrobić w dowolnej chwili, także później w oknie "
                          "„Przegląd nagrań”.", "Zapisz", "Pomiń", self)
        d.setModal(False)
        d.accepted.connect(lambda: self._apply_info(rec, d.values()))
        self._info_dlg = d
        d.show()

    def _apply_info(self, rec, vals: dict) -> None:
        if rec is self.recorder and isinstance(rec, DbRecorder):
            self._rec_info.update(vals)
            rec.update_info(**vals)
            self.status_msg = f"REC: zapisano tytuł „{vals.get('title', '')}”"

    def _probe_db(self, cfg: StoreConfig, session: str) -> None:
        """Checks the server in the background (the REC press must not freeze the window). Recording runs meanwhile:
        the data wait in the queue / disk buffer. A failure is reported at once, with its cause."""
        cfg = dataclasses.replace(cfg)
        folder = data_dir()

        def run():
            try:
                test_connection(cfg, folder, cfg.test_timeout_s)
                err = ""
            except Exception as e:
                err = str(e) or type(e).__name__
            try:
                self._dbProbe.emit(session, err)
            except RuntimeError:                                  # the tab is gone
                pass

        threading.Thread(target=run, daemon=True, name="StoreProbe").start()

    def _on_db_probe(self, session: str, err: str) -> None:
        r = self.recorder
        if not err or not isinstance(r, DbRecorder) or r.session != session:
            return
        where = "w buforze na dysku" if r.spool is not None else "w kolejce w pamięci"
        box = QMessageBox(QMessageBox.Warning, "S7Trace – REC",
                          f"Baza danych nie odpowiada:\n{err}\n\nNagrywanie trwa – dane czekają {where} i zostaną wysłane, "
                          "gdy serwer wróci (próby są ponawiane). Możesz też przerwać REC i poprawić ustawienia bazy "
                          "(przycisk „...” przy REC lub menu Ustawienia).", QMessageBox.NoButton, self)
        box.addButton("Kontynuuj REC", QMessageBox.AcceptRole)
        stop = box.addButton("Przerwij REC", QMessageBox.RejectRole)
        box.setModal(False)                                       # the acquisition and the chart go on behind it
        box.buttonClicked.connect(lambda b: self.btn_rec.setChecked(False) if b is stop else None)
        self._probe_box = box
        self.status_msg = f"REC: brak połączenia z bazą – {err}"
        box.show()

    def _close_recorder(self, ask: bool = False):
        """`ask`: the user stopped the recording - in the "ask at the end" mode this is the moment to name it."""
        if self._info_dlg is not None:
            self._info_dlg.close()
            self._info_dlg = None
        if self.recorder and ask and isinstance(self.recorder, DbRecorder) and self.recorder.cfg.title_ask == "end" \
                and not self._rec_info.get("title"):
            from .store_dialog import RecInfoDialog
            d = RecInfoDialog(self.cfg.conf_name, self._rec_info.get("notes", ""), self._rec_info.get("tags", ""),
                              "Zatrzymano nagrywanie. Nadaj nazwę nagraniu.", "Zapisz", "Pomiń", self)
            if d.exec():
                self.recorder.update_info(**d.values())
        if self.recorder:
            self.status_msg = f"REC zakończony: {self.recorder.path}"
            self.recorder.close()
            self.recorder = None


def _sanitize_filename(n: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", n)
