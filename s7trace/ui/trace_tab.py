"""One connection tab: settings panel, plot, buttons, trigger handling."""
from __future__ import annotations

import os
import re
import time
from collections import deque
from datetime import datetime, timedelta

from PySide6.QtCore import QTimer, Qt, Signal as QtSignal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..core import trigger as trg
from ..core.acq_process import ProcAcquirer
from ..core.buffer import TraceBuffer
from ..core.config import TabConfig
from ..core.csvio import CsvRecorder, read_csv, write_csv
from ..core.planner import MODES
from ..core.symbols import Symbol
from ..core.types import Signal
from .plotview import PlotView
from .signals_dialog import SignalsDialog

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
    return w


class TraceTab(QWidget):
    stateChanged = QtSignal(str)       # stopped / connecting / running / reconnecting / error
    titleChanged = QtSignal(str)
    _stateRaw = QtSignal(str, str)     # from worker thread

    def __init__(self, cfg: TabConfig, symbols: callable, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.symbols = symbols
        self.buffer = TraceBuffer(len(cfg.signals))
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
        self._build()
        self._load_cfg()
        self._stateRaw.connect(self._on_state)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._set_buttons()

    # ================================================================== UI
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- left panel
        left = QWidget()
        left.setFixedWidth(262)
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
        self.ed_ip = QLineEdit()
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
        f.addRow("IP:", self.ed_ip)
        f.addRow("Rack / Slot:", rs)
        f.addRow("Cykle [ms]:", self.sp_cycle)
        f.addRow("Tryb komunik.:", self.cb_mode)
        self._conn_widgets = [self.ed_ip, self.sp_rack, self.sp_slot, self.sp_cycle, self.cb_mode]

        f = group("Zakres")
        self.sp_window = _spin(0.05, 86400, 200, dec=1)
        self.chk_auto = QCheckBox("Auto Y")
        self.sp_ymin = _spin(-1e9, 1e9, 0, dec=3)
        self.sp_ymax = _spin(-1e9, 1e9, 10, dec=3)
        f.addRow("Okno czasu [s]:", self.sp_window)
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
        lv.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(280)
        scroll.setFrameShape(QScrollArea.NoFrame)

        # ---- right side
        right = QVBoxLayout()
        right.setContentsMargins(4, 4, 4, 4)
        self.plot = PlotView(self.buffer)
        right.addWidget(self.plot, 1)
        bar = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_pause = QPushButton("Pauza")
        self.btn_pause.setCheckable(True)
        self.btn_rec = QPushButton("● REC")
        self.btn_rec.setCheckable(True)
        self.btn_pts = QPushButton("Punkty")
        self.btn_pts.setCheckable(True)
        self.btn_v = QPushButton("V znacznik")
        self.btn_v.setCheckable(True)
        self.btn_h = QPushButton("H znacznik")
        self.btn_h.setCheckable(True)
        self.btn_sig = QPushButton("Sygnały...")
        self.btn_exp = QPushButton("Eksport okna → CSV")
        self.btn_imp = QPushButton("Import CSV → wykres")
        for b in (self.btn_start, self.btn_stop, self.btn_pause, self.btn_rec, self.btn_pts,
                  self.btn_v, self.btn_h):
            bar.addWidget(b)
        bar.addStretch()
        for b in (self.btn_sig, self.btn_exp, self.btn_imp):
            bar.addWidget(b)
        right.addLayout(bar)
        self.lbl_status = QLabel()
        self.lbl_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right.addWidget(self.lbl_status)

        root.addWidget(scroll)
        root.addLayout(right, 1)

        # ---- wiring
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_pause.toggled.connect(self._on_pause)
        self.btn_rec.toggled.connect(self._on_rec)
        self.btn_pts.toggled.connect(self.plot.set_points)
        self.btn_v.toggled.connect(self.plot.set_v_mode)
        self.btn_h.toggled.connect(self.plot.set_h_mode)
        self.btn_sig.clicked.connect(self.edit_signals)
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

    # ============================================================= config
    def title(self) -> str:
        return self.ed_ip.text().strip() or "PLC"

    def _load_cfg(self):
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
        self._on_auto_y(c.auto_y)
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

    def _refresh_signal_widgets(self, select: str | None = None):
        keep = select if select is not None else self.cb_tsig.currentText()
        self.cb_tsig.blockSignals(True)
        self.cb_tsig.clear()
        self.cb_tsig.addItems([s.name for s in self.cfg.signals])
        if keep in [s.name for s in self.cfg.signals]:
            self.cb_tsig.setCurrentText(keep)
        self.cb_tsig.blockSignals(False)
        self.plot.set_signals(self.cfg.signals)

    # ============================================================ handlers
    def _on_auto_y(self, on: bool):
        self.sp_ymin.setEnabled(not on)
        self.sp_ymax.setEnabled(not on)
        self.plot.set_auto_y(on)

    def _on_y_manual(self, *_):
        self.plot.set_y_range(self.sp_ymin.value(), self.sp_ymax.value())

    def _on_zoomed(self, width: float):
        self.sp_window.blockSignals(True)
        self.sp_window.setValue(min(max(width, 0.05), 86400))
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

    # ========================================================== lifecycle
    def start(self):
        if self.state != "stopped":
            return
        c = self._collect()
        if not c.signals:
            QMessageBox.information(self, "S7Trace", "Dodaj przynajmniej jeden sygnał (przycisk 'Sygnały...').")
            return
        self.buffer.reset(len(c.signals))
        self._run_signals = [Signal.from_dict(s.to_dict()) for s in c.signals]
        self.plot.set_signals(c.signals)
        self.plot.clear_trigger_marks()
        self._pending.clear()
        self.engine = trg.TriggerEngine(c.trigger)
        self.trig_state = "armed" if c.trigger.enabled else "idle"
        self.btn_pause.setChecked(False)
        self.acq = acq = ProcAcquirer(
            c.ip, c.rack, c.slot, c.cycle_ms, c.signals, c.mode, self.buffer,
            on_state=lambda s, m: self._stateRaw.emit(s, m),
            on_sample=lambda t, v: self._pending.append((t, list(v))))
        self.plot.time_source = lambda a=acq: (time.perf_counter() - a.t0) if a.t0 else self.buffer.last_time()
        self.state = "connecting"
        self.status_msg = f"Łączenie z {c.ip}…"
        self._set_buttons()
        self.stateChanged.emit(self.state)
        acq.start()

    def stop(self):
        if self.acq and self.state != "stopped":
            self.acq.stop()
            self.status_msg = "Zatrzymywanie…"

    def shutdown(self):
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
            self._close_recorder()
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
        self.btn_pause.setEnabled(not stopped)
        self.btn_imp.setEnabled(stopped)
        for w in self._conn_widgets:
            w.setEnabled(stopped)

    # ============================================================== tick
    def _tick(self):
        self._drain()
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
            if self.trig_state == "armed" and tc.enabled and tc.signal in names:
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

    def _update_status(self):
        if self.acq and self.state in ("running", "reconnecting"):
            st = self.acq.stats
            st.gui_lag_ms = self.plot.gui_lag_ms
            self.lbl_status.setText(
                f"PLC comm lag Avg: {st.avg_lag:.1f} ms (n={st.n}), Last: {st.last_lag:.1f} ms | "
                f"GUI lag: {st.gui_lag_ms:.1f} ms  Missed: {st.missed} ({st.missed_pct:.1f}%)  {self.status_msg}")
        else:
            self.lbl_status.setText(self.status_msg)

    # ================================================================ IO
    def _abs_folder(self) -> str:
        f = self.cfg.trigger.folder or "snapshots"
        return f if os.path.isabs(f) else os.path.join(os.getcwd(), f)

    def _file_name(self, template: str, prefix: str) -> str:
        now = datetime.now()
        name = (template or f"{prefix}_{{tab}}_{{date}}_{{time}}.csv").format(
            tab=_sanitize(self.title()), date=now.strftime("%Y-%m-%d"), time=now.strftime("%H-%M-%S"))
        if not name.lower().endswith(".csv"):
            name += ".csv"
        folder = self._abs_folder()
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
        sigs = self._run_signals or self.cfg.signals
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
        self.cfg.signals = sigs
        self._run_signals = [Signal.from_dict(s.to_dict()) for s in sigs]
        self.buffer.load(t, v)
        self._refresh_signal_widgets()
        self.btn_pause.setChecked(False)
        self.plot.set_follow(False)
        self.plot.fit_all()
        self._on_zoomed(self.plot.window)
        self.status_msg = f"Zaimportowano {len(t)} próbek z {os.path.basename(path)}"
        self._update_status()

    def edit_signals(self):
        locked = self.state != "stopped"
        dlg = SignalsDialog(self.cfg.signals, locked, self.symbols, self)
        if not dlg.exec():
            return
        new = dlg.signals()
        old = self.cfg.signals
        if locked:
            for o, n in zip(old, new):
                o.name, o.offset_y, o.gain, o.color = n.name, n.offset_y, n.gain, n.color
        else:
            struct = lambda L: [(s.source, s.dtype, s.db, s.byte, s.bit) for s in L]
            if struct(old) != struct(new) and len(self.buffer):
                self.buffer.reset(len(new))
            elif len(new) != self.buffer.n:
                self.buffer.reset(len(new))
            self.cfg.signals = new
            self._run_signals = [Signal.from_dict(s.to_dict()) for s in new]
        self._refresh_signal_widgets()
        self.plot.touch()

    # ================================================================ REC
    def _on_rec(self, on: bool):
        if on and self.state == "running":
            self._open_recorder()
        elif not on:
            self._close_recorder()

    def _open_recorder(self):
        try:
            path = self._file_name("rec_{tab}_{date}_{time}.csv", "rec")
            self.recorder = CsvRecorder(path, self._run_signals, self.start_wall)
            self.status_msg = f"REC → {path}"
        except Exception as e:
            self.recorder = None
            self.btn_rec.setChecked(False)
            QMessageBox.warning(self, "S7Trace", f"Nie można rozpocząć nagrywania: {e}")

    def _close_recorder(self):
        if self.recorder:
            self.status_msg = f"REC zakończony: {self.recorder.path}"
            self.recorder.close()
            self.recorder = None


def _sanitize_filename(n: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", n)
