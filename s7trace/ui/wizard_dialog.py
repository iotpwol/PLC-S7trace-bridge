"""Kreator połączenia: rozpoznaje metodę komunikacji, pokazuje dane sterownika, różnicę czasu i ograniczenia."""
from __future__ import annotations

import html

import threading

from PySide6.QtCore import QThread, Qt, Signal as QtSignal
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..core import detect
from ..core.richtext import bold, bold_numbers
from ..core.types import fmt_diff
from ..core.drivers import CONN_LABEL
from ..core.store import DEVICE_LABELS
from .dialog_kit import dialog_info

STATUS_TXT = {"ok": ("✔ OK", "#2fbf4a"), "fail": ("✖ błąd", "#e04040"), "warn": ("▲ uwaga", "#e0b020"),
              "skip": ("— pominięto", "#8a8a8a")}
INFO_LABELS = DEVICE_LABELS


class DetectWorker(QThread):
    stepDone = QtSignal(object)
    finished_ = QtSignal(object)

    def __init__(self, host: str, opts: dict, rack: int, slot: int, methods=None, stop_at_first=False, parent=None):
        super().__init__(parent)
        self.args = (host, opts, rack, slot, methods, stop_at_first)
        self.cancel = threading.Event()

    def run(self):
        host, opts, rack, slot, methods, first = self.args
        try:
            res = detect.run_detection(host, opts, rack, slot, methods, first, progress=self.stepDone.emit,
                                       cancel=self.cancel)
        except Exception as e:                                       # never let the thread die silently
            res = detect.DetectResult(host=host)
            res.advice.append(f"Błąd kreatora: {e}")
        self.finished_.emit(res)


@dialog_info("Kreator połączenia",
             "Sprawdza adres sterownika i rozpoznaje, którą metodą (S7, OPC UA, Web API, Modbus) da się go odczytać. Wynik można od razu zastosować.")
class WizardDialog(QDialog):
    """auto=True: used by Start in automatic mode – closes itself when a working method is found."""

    def __init__(self, tab, auto: bool = False, show_tab: int = 0, methods: list[str] | None = None, parent=None,
                 stored: "detect.DetectResult | None" = None):
        super().__init__(parent or tab)
        self.tab, self.auto, self.methods = tab, auto, methods
        self.result: detect.DetectResult | None = None
        self.method: str | None = None
        self.setWindowTitle("Kreator połączenia – rozpoznawanie metody komunikacji")
        self.resize(900, 700)
        lay = QVBoxLayout(self)
        self.lbl = QLabel()
        self.lbl.setTextFormat(Qt.RichText)                     # data inside the sentences is bold (core/richtext.py)
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        self.t_steps = QTableWidget(0, 4)
        self.t_steps.setHorizontalHeaderLabels(["Test", "Wynik", "Czas [ms]", "Szczegóły"])
        self.t_steps.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.t_steps.verticalHeader().setVisible(False)
        self.t_steps.setWordWrap(True)
        self.t_steps.setEditTriggers(QTableWidget.NoEditTriggers)
        self.t_steps.setColumnWidth(0, 230)
        self.t_steps.setColumnWidth(1, 110)
        self.t_steps.setColumnWidth(2, 80)
        self.tabs.addTab(self.t_steps, "Wyniki testów")

        w = QWidget()
        v = QVBoxLayout(w)
        self.t_info = QTableWidget(0, 2)
        self.t_info.setHorizontalHeaderLabels(["Parametr", "Wartość"])
        self.t_info.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.t_info.verticalHeader().setVisible(False)
        self.t_info.setColumnWidth(0, 250)
        self.t_info.setEditTriggers(QTableWidget.NoEditTriggers)
        self.lbl_time = QLabel()
        self.lbl_time.setTextFormat(Qt.RichText)
        self.lbl_time.setWordWrap(True)
        v.addWidget(self.t_info, 1)
        v.addWidget(self.lbl_time)
        self.tabs.addTab(w, "Sterownik i czas")

        self.txt_limits = QPlainTextEdit()
        self.txt_limits.setReadOnly(True)
        self.tabs.addTab(self.txt_limits, "Ograniczenia i blokady")
        self.tabs.setCurrentIndex(show_tab)

        row = QHBoxLayout()
        self.btn_again = QPushButton("Uruchom ponownie")
        self.btn_use = QPushButton("Użyj zalecanej metody")
        self.btn_copy = QPushButton("Kopiuj raport")
        close = QPushButton("Zamknij")
        for b in (self.btn_again, self.btn_use, self.btn_copy):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        close.clicked.connect(self.reject)
        self.btn_again.clicked.connect(self.run)
        self.btn_use.clicked.connect(self._use)
        self.btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(detect.format_result(self.result)
                                                                               if self.result else ""))
        self.worker: DetectWorker | None = None
        if stored is not None:                                    # data from the last connection: no new probing
            self._show_stored(stored)
        else:
            self.run()

    def _show_stored(self, res: detect.DetectResult) -> None:
        self.result = res
        self.btn_again.setEnabled(True)
        self.btn_use.setEnabled(False)
        self.lbl.setText(f"Dane sterownika {bold(res.host)} pobrane przy ostatnim połączeniu. "
                         "„Uruchom ponownie” wykonuje pełne rozpoznawanie (nowy odczyt).")
        self._fill_info(res, stored=True)
        self._fill_limits()

    # ------------------------------------------------------------------
    def run(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        t = self.tab
        self.t_steps.setRowCount(0)
        self.btn_again.setEnabled(False)
        self.btn_use.setEnabled(False)
        self.lbl.setText(f"Rozpoznawanie połączenia z {bold(t.ed_ip.text().strip())} …")
        self.worker = DetectWorker(t.ed_ip.text(), dict(t.cfg.conn), t.sp_rack.value(), t.sp_slot.value(),
                                   self.methods, stop_at_first=self.auto, parent=self)
        self.worker.stepDone.connect(self._add_step)
        self.worker.finished_.connect(self._done)
        self.worker.start()

    def _add_step(self, st) -> None:
        r = self.t_steps.rowCount()
        self.t_steps.insertRow(r)
        txt, col = STATUS_TXT[st.status]
        for c, val in enumerate((st.title, txt, f"{st.ms:.0f}" if st.ms else "", st.detail)):
            it = QTableWidgetItem(val)
            if c == 1:
                it.setForeground(Qt.GlobalColor.white)
                it.setBackground(self._color(col))
            self.t_steps.setItem(r, c, it)
        self.t_steps.resizeRowToContents(r)

    @staticmethod
    def _color(hex_):
        from PySide6.QtGui import QColor
        return QColor(hex_)

    def _done(self, res: detect.DetectResult) -> None:
        self.result = res
        self.method = res.recommended
        self.btn_again.setEnabled(True)
        self.btn_use.setEnabled(bool(res.recommended))
        if res.recommended:
            head = f"Zalecana metoda: {CONN_LABEL[res.recommended]}"
        else:
            head = "Nie wykryto działającej metody komunikacji."
        self.lbl.setText(bold_numbers(head) + "<br>" + "<br>".join("• " + bold_numbers(a) for a in res.advice if not a.startswith("Zalecana")))
        self._fill_info(res)
        self._fill_limits()
        if self.auto and res.recommended:
            self.accept()

    def _fill_limits(self) -> None:
        lim = ["OGRANICZENIA SYSTEMOWE I SIECIOWE", ""] + ["• " + s for s in detect.SYSTEM_LIMITS]
        for m in detect.ORDER:
            lim += ["", CONN_LABEL[m].upper()] + ["• " + s for s in detect.LIMITS[m]]
        self.txt_limits.setPlainText("\n".join(lim))

    def _fill_info(self, res: detect.DetectResult, stored: bool = False) -> None:
        rows = [(lbl, ", ".join(v) if isinstance(v := res.info.get(k), list) else str(v))
                for k, lbl in INFO_LABELS if res.info.get(k) not in (None, "", [])]
        if res.info.get("s7_access"):
            acc = {"ok": "działa", "denied": "ODMOWA (PUT/GET wyłączony?)", "range": "adres niedostępny (DB zoptymalizowane?)",
                   "other": "błąd", "unknown": "nieznany"}[res.info["s7_access"]]
            rows.append(("S7comm: odczyt pamięci bezwzględnej", acc))
        self.t_info.setRowCount(len(rows))
        for r, (a, b) in enumerate(rows):
            self.t_info.setItem(r, 0, QTableWidgetItem(a))
            it = QTableWidgetItem(b)
            f = it.font()
            f.setBold(True)                                  # values bold, the parameter names normal
            it.setFont(f)
            self.t_info.setItem(r, 1, it)
        if res.plc_time:
            self.lbl_time.setText(
                f"Czas sterownika{' w chwili połączenia' if stored else ''}: "
                f"<b>{res.plc_time:%Y-%m-%d %H:%M:%S}{' (UTC)' if res.plc_time_utc else ''}</b>   |   "
                f"różnica do czasu lokalnego komputera: <b>{fmt_diff(res.time_diff_local)}</b>   |   "
                f"do UTC: <b>{fmt_diff(res.time_diff_utc)}</b><br>"
                "Sterowniki Siemensa często pracują w UTC – właściwa jest ta różnica, która jest bliższa zera.")
        else:
            why = getattr(res, "time_error", "")
            self.lbl_time.setText("Czas sterownika: <b>nie odczytano</b>" + (f" ({html.escape(why)})" if why else "") + ".")

    def _use(self) -> None:
        if self.method:
            self.tab.set_conn_type(self.method)
            self.accept()

    def reject(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel.set()
            self.worker.wait(4000)
        super().reject()
