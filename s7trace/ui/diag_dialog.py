"""Diagnostyka połączenia: opóźnienia, jitter, utracone cykle, zerwania, przepustowość, ping ICMP, wykresy."""
from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..core import diagnostics as dg
from ..core.acquisition import parse_host

RATING_COLOR = {"Bardzo dobre": "#2fbf4a", "Dobre": "#7fcf3a", "Przeciętne": "#e0b020", "Słabe": "#e04040",
                "Brak połączenia": "#e04040", "Brak danych": "#8a8a8a"}
STAT_COLS = [("Chwilowo", "last"), ("Śr. 10 s", "avg10"), ("Śr. 60 s", "avg60"), ("Śr. całość", "avg"),
             ("Min", "min"), ("Max", "max"), ("Odch. std.", "std"), ("P95", "p95"), ("P99", "p99")]


def _f(v, fmt="{:.1f}") -> str:
    return dg._f(v, fmt)


def _hms(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


class _Table(QTableWidget):
    def __init__(self, rows: list[str], cols: list[str]):
        super().__init__(len(rows), len(cols))
        self.setVerticalHeaderLabels(rows)
        self.setHorizontalHeaderLabels(cols)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.verticalHeader().setMinimumWidth(190)
        for r in range(len(rows)):
            for c in range(len(cols)):
                it = QTableWidgetItem("—")
                it.setTextAlignment(Qt.AlignCenter if len(cols) > 1 else Qt.AlignVCenter | Qt.AlignLeft)
                self.setItem(r, c, it)

    def put(self, r: int, c: int, text: str) -> None:
        it = self.item(r, c)
        if it.text() != text:
            it.setText(text)


class DiagDialog(QDialog):
    """Non-modal window with the complete link diagnostics of one tab."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self.tab = tab
        self.setWindowTitle(f"Diagnostyka połączenia – {tab.title()}")
        self.resize(980, 720)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        lay = QVBoxLayout(self)

        self.lbl_rating = QLabel()
        self.lbl_rating.setStyleSheet("font-size: 15pt; font-weight: bold;")
        self.lbl_head = QLabel()
        self.lbl_head.setWordWrap(True)
        self.lbl_notes = QLabel()
        self.lbl_notes.setWordWrap(True)
        self.lbl_notes.setTextFormat(Qt.PlainText)
        top = QHBoxLayout()
        top.addWidget(QLabel("Ocena łącza:"))
        top.addWidget(self.lbl_rating)
        top.addStretch()
        lay.addLayout(top)
        lay.addWidget(self.lbl_head)
        lay.addWidget(self.lbl_notes)

        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        # --- latencies
        self.t_lat = _Table(["Czas odczytu PLC [ms]", "Okres próbkowania [ms]", "Ping ICMP (RTT) [ms]"],
                            [h for h, _ in STAT_COLS])
        self.hist_plot = pg.PlotWidget()
        self.hist_plot.setMouseEnabled(False, False)
        self.hist_plot.setMenuEnabled(False)
        self.hist_plot.setLabel("left", "% odczytów")
        self.hist_plot.setLabel("bottom", "czas odczytu [ms]")
        self.hist_bars = pg.BarGraphItem(x=[], height=[], width=0.8, brush="#2a82da")
        self.hist_plot.addItem(self.hist_bars)
        ticks = [(i, f"{a}–{b}") for i, (a, b) in enumerate(zip(dg.HIST_EDGES, dg.HIST_EDGES[1:]))]
        ticks.append((len(dg.HIST_EDGES) - 1, f"≥{dg.HIST_EDGES[-1]}"))
        self.hist_plot.getAxis("bottom").setTicks([ticks])
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(self.t_lat)
        v.addWidget(QLabel("Rozkład czasu odczytu (histogram):"))
        v.addWidget(self.hist_plot, 1)
        note = QLabel("Chwilowo = ostatnia próbka; Śr. 10 s / 60 s = średnia z ostatnich sekund; Min/Max/Odch. std. liczone od startu; "
                      "P95 / P99 = 95% / 99% odczytów jest szybszych (z ostatnich ~20 000 próbek). Jitter = średnia zmiana "
                      "okresu między kolejnymi próbkami.")
        note.setWordWrap(True)
        v.addWidget(note)
        tabs.addTab(w, "Opóźnienia")

        # --- reliability / packets
        self.rel_names = ["Odebrane próbki", "Pominięte cykle", "Pominięte cykle [%]", "Odczyty dłuższe niż cykl",
                          "Odczyty dłuższe niż cykl [%]", "Błędy odczytu / utraty połączenia", "Ponowne połączenia",
                          "Ostatni błąd", "Czas przerw w połączeniu", "Dostępność łącza [%]",
                          "Czas nawiązania połączenia [ms]", "Jitter próbkowania [ms]",
                          "Ping: wysłane", "Ping: odebrane", "Ping: utracone", "Ping: utrata pakietów [%]",
                          "Ping: kolejno utracone", "Ping: jitter [ms]"]
        self.t_rel = _Table(self.rel_names, ["Wartość"])
        tabs.addTab(self.t_rel, "Pakiety i niezawodność")

        # --- throughput
        self.thr_names = ["Ustawiony cykl [ms]", "Częstotliwość oczekiwana [Hz]", "Częstotliwość rzeczywista (10 s) [Hz]",
                          "Częstotliwość rzeczywista (całość) [Hz]", "Maks. możliwa częstotliwość [Hz]",
                          "Zalecany najkrótszy cykl [ms]", "Dane na cykl [B]", "Żądań S7 na cykl",
                          "Przepustowość danych [B/s]", "Żądań S7 na sekundę",
                          "Ruch w sieci – szacunek [kb/s]"]
        self.t_thr = _Table(self.thr_names, ["Wartość"])
        tabs.addTab(self.t_thr, "Przepustowość")

        # --- charts
        self.cb_span = QComboBox()
        for label, sec in (("30 s", 30), ("2 min", 120), ("10 min", 600)):
            self.cb_span.addItem(label, sec)
        self.cb_span.setCurrentIndex(1)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("left", "ms")
        self.plot.setLabel("bottom", "s temu")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.addLegend(offset=(10, 10))
        self.c_lag = self.plot.plot(pen=pg.mkPen("#ffaa44", width=1), name="czas odczytu PLC", connect="finite")
        self.c_ping = self.plot.plot(pen=pg.mkPen("#44c0ff", width=1), name="ping ICMP", connect="finite",
                                     symbol="o", symbolSize=3, symbolBrush="#44c0ff", symbolPen=None)
        self.c_lag.setDownsampling(auto=True, method="peak")
        self.c_lag.setClipToView(True)
        self.c_cycle = pg.InfiniteLine(angle=0, pen=pg.mkPen("#e04040", style=Qt.DashLine))
        self.plot.addItem(self.c_cycle)
        cw = QWidget()
        cv = QVBoxLayout(cw)
        row = QHBoxLayout()
        row.addWidget(QLabel("Zakres czasu:"))
        row.addWidget(self.cb_span)
        row.addWidget(QLabel("Czerwona przerywana linia = ustawiony cykl."))
        row.addStretch()
        cv.addLayout(row)
        cv.addWidget(self.plot, 1)
        tabs.addTab(cw, "Wykresy w czasie")

        # --- buttons
        row = QHBoxLayout()
        self.chk_ping = QCheckBox("Ping ICMP do sterownika")
        self.chk_ping.setToolTip("Co sekundę wysyła pojedynczy ping (nie zajmuje połączenia S7). Działa też bez uruchomionego "
                                 "połączenia – można sprawdzić sieć przed Start. Jeśli ICMP jest zablokowane w sieci, pokaże 100% utraty.")
        self.chk_ping.setChecked(bool(tab.ui_state.get("diag_ping", True)))
        self.btn_port = QPushButton("Test portu TCP…")
        self.btn_port.setToolTip("Jednorazowe nawiązanie połączenia TCP z portem S7 (domyślnie 102) – mierzy czas i sprawdza, "
                                 "czy port jest osiągalny (routing, zapora).")
        self.btn_reset = QPushButton("Resetuj statystyki")
        self.btn_copy = QPushButton("Kopiuj raport")
        self.btn_save = QPushButton("Zapisz raport…")
        close = QPushButton("Zamknij")
        for b in (self.chk_ping, self.btn_port, self.btn_reset, self.btn_copy, self.btn_save):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        close.clicked.connect(self.close)
        self.btn_port.clicked.connect(self._port_test)
        self.btn_reset.clicked.connect(self._reset)
        self.btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.report()))
        self.btn_save.clicked.connect(self._save)
        self.chk_ping.toggled.connect(self._ping_toggled)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        if self.chk_ping.isChecked():
            self.tab.set_ping(True)
        self.refresh()

    # ------------------------------------------------------------------
    def _snap(self):
        diag = self.tab.acq.diag if self.tab.acq else None
        d = diag.snapshot() if diag else None
        p = self.tab.ping_probe.snapshot() if self.tab.ping_probe else None
        return diag, d, p

    def report(self) -> str:
        _, d, p = self._snap()
        if d is None:
            return "Brak danych diagnostycznych – uruchom połączenie (Start).\n"
        return dg.format_report(d, p, self.tab.ed_ip.text(), self.tab.title())

    def refresh(self) -> None:
        self.setWindowTitle(f"Diagnostyka połączenia – {self.tab.title()}")
        diag, d, p = self._snap()
        if d is None:
            self.lbl_rating.setText("Brak danych")
            self.lbl_rating.setStyleSheet(f"font-size: 15pt; font-weight: bold; color: {RATING_COLOR['Brak danych']};")
            ping_txt = f"Ping: {_f(p['last'])} ms, utrata {p['loss_pct']:.1f}%" if p and p["sent"] else "Ping wyłączony"
            self.lbl_head.setText(f"Połączenie nie było uruchomione.   {ping_txt}")
            self.lbl_notes.setText("Kliknij Start na karcie, aby zbierać statystyki odczytu. Test portu TCP i ping działają także bez Start.")
            self._fill_ping_only(p)
            return
        rating, notes = dg.verdict(d, p)
        self.lbl_rating.setText(rating)
        self.lbl_rating.setStyleSheet(f"font-size: 15pt; font-weight: bold; color: {RATING_COLOR.get(rating, '#ccc')};")
        lg = d["lag"]
        ping_txt = (f"   |   Ping: {_f(p['last'])} ms (śr. {_f(p['avg'])}), utrata {p['loss_pct']:.1f}%"
                    if p and p["sent"] else "")
        self.lbl_head.setText(
            f"Stan: {d['state']}   |   Czas pracy: {_hms(d['uptime_s'])}   |   Odczyt chwilowo: {_f(lg.get('last'))} ms, "
            f"średnio: {_f(lg.get('avg'))} ms   |   Utracone cykle: {d['missed_pct']:.1f}%   |   "
            f"Próbkowanie: {_f(d['rate10'])} Hz z {_f(d['expected_rate'])} Hz{ping_txt}")
        self.lbl_notes.setText("\n".join("• " + n for n in notes))

        # latencies
        for c, (_, k) in enumerate(STAT_COLS):
            self.t_lat.put(0, c, _f(lg.get(k)))
            self.t_lat.put(1, c, _f(d["period"].get(k)))
            self.t_lat.put(2, c, _f(p.get(k) if p and k in p else None))
        if p:
            self.t_lat.put(2, 0, _f(p["last"]))
            self.t_lat.put(2, 3, _f(p["avg"]))
            self.t_lat.put(2, 4, _f(p["min"]))
            self.t_lat.put(2, 5, _f(p["max"]))
        tot = max(sum(d["hist"]), 1)
        self.hist_bars.setOpts(x=list(range(len(d["hist"]))), height=[100.0 * h / tot for h in d["hist"]])
        # reliability
        r = self.t_rel
        vals = [str(d["samples"]), str(d["missed"]), f"{d['missed_pct']:.2f}", str(d["overruns"]), f"{d['overrun_pct']:.2f}",
                str(d["errors"]), str(d["reconnects"]), d["last_error"] or "—", f"{d['down_s']:.1f} s",
                f"{d['availability']:.2f}", _f(d["connect_ms"]), _f(d["period"].get("jitter")),
                str(p["sent"]) if p else "—", str(p["recv"]) if p else "—", str(p["lost"]) if p else "—",
                f"{p['loss_pct']:.2f}" if p else "—", str(p["consec_lost"]) if p else "—",
                _f(p["jitter"]) if p else "—"]
        for i, t in enumerate(vals):
            r.put(i, 0, t)
        # throughput
        thr = [f"{d['cycle_ms']:g}", _f(d["expected_rate"]), _f(d["rate10"]), _f(d["rate"]), _f(d["max_rate"]),
               str(d["safe_cycle_ms"]), str(d["bytes_per_cycle"]), str(d["req_per_cycle"]),
               _f(d["bytes_per_s"], "{:.0f}"), _f(d["req_per_s"]), _f(d["wire_bytes_per_s"] * 8 / 1000)]
        for i, t in enumerate(thr):
            self.t_thr.put(i, 0, t)
        self._plots(diag, p)

    def _fill_ping_only(self, p) -> None:
        if not p:
            return
        for c, k in ((0, "last"), (3, "avg"), (4, "min"), (5, "max")):
            self.t_lat.put(2, c, _f(p[k]))
        base = self.rel_names.index("Ping: wysłane")
        for i, t in enumerate([str(p["sent"]), str(p["recv"]), str(p["lost"]), f"{p['loss_pct']:.2f}",
                               str(p["consec_lost"]), _f(p["jitter"])]):
            self.t_rel.put(base + i, 0, t)

    def _plots(self, diag, p) -> None:
        span = float(self.cb_span.currentData())
        t0 = self.tab.acq.t0 if self.tab.acq else 0.0
        now = time.perf_counter()
        if diag is not None and t0:
            t, v = diag.lag_series(span)
            self.c_lag.setData(-(now - t0 - t), v) if len(t) else self.c_lag.setData([], [])
        if p and self.tab.ping_probe:
            pts = self.tab.ping_probe.series(span)
            self.c_ping.setData([-(now - x) for x, _ in pts], [np.nan if r is None else r for _, r in pts])
        self.c_cycle.setValue(self.tab.cfg.cycle_ms)

    # ------------------------------------------------------------------ actions
    def _ping_toggled(self, on: bool) -> None:
        self.tab.ui_state["diag_ping"] = on
        self.tab.set_ping(on)

    def _reset(self) -> None:
        if self.tab.acq:
            self.tab.acq.diag.reset()
        if self.tab.ping_probe:
            self.tab.ping_probe.reset()
        self.refresh()

    def _port_test(self) -> None:
        host, port = parse_host(self.tab.ed_ip.text())
        ok, ms, err = dg.tcp_probe(host, port)
        if ok:
            QMessageBox.information(self, "Test portu TCP", f"{host}:{port} – port otwarty, czas połączenia {ms:.1f} ms.")
        else:
            QMessageBox.warning(self, "Test portu TCP",
                                f"{host}:{port} – brak połączenia po {ms:.0f} ms.\n{err}\n\nSprawdź routing, zaporę "
                                "(port 102) i ustawienie „Permit access with PUT/GET” w CPU.")

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz raport diagnostyczny", "raport_diagnostyczny.txt",
                                              "Tekst (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.report())

    def closeEvent(self, e):
        self.timer.stop()
        self.tab.diag_closed()
        super().closeEvent(e)
