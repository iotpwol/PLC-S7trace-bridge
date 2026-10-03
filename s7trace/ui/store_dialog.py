"""REC target settings (SQLite / InfluxDB 1.x 2.x 3.x / TimescaleDB) and the 'Import z bazy → wykres' window."""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from ..core import store as st
from ..core.config import data_dir
from ..core.csvio import write_csv
from ..core.types import Signal

DB_KINDS = [k for k in st.KINDS if k != "csv"]

# which fields each target needs: (label, StoreConfig attribute, kind of editor)
FIELDS = {
    "sqlite": [("Plik bazy:", "sqlite_path", "file")],
    "influx1": [("Adres (URL):", "url", "text"), ("Baza (database):", "database", "text"),
                ("Użytkownik:", "user", "text"), ("Hasło:", "password", "secret"), ("Pomiar (measurement):", "measurement", "text")],
    "influx2": [("Adres (URL):", "url", "text"), ("Organizacja (org):", "org", "text"), ("Bucket:", "bucket", "text"),
                ("Token:", "token", "secret"), ("Pomiar (measurement):", "measurement", "text")],
    "influx3": [("Adres (URL):", "url", "text"), ("Baza (database):", "database", "text"),
                ("Token:", "token", "secret"), ("Pomiar (measurement):", "measurement", "text")],
    "timescale": [("Serwer:", "host", "text"), ("Port:", "port", "int"), ("Baza:", "pg_database", "text"),
                  ("Użytkownik:", "pg_user", "text"), ("Hasło:", "pg_password", "secret"),
                  ("SSL (sslmode):", "pg_sslmode", "text"), ("Tabela:", "table", "text")],
}
HINTS = {
    "sqlite": "Plik wbudowanej bazy (bez serwera). Ścieżka względna = folder Dokumenty\\S7Trace bieżącego użytkownika. "
              "Jeden plik może zawierać wiele nagrań.",
    "influx1": "InfluxDB 1.x: zapis przez /write (line protocol), baza jest tworzona, jeśli konto ma uprawnienia.",
    "influx2": "InfluxDB 2.x: zapis przez /api/v2/write. Bucket i token (z prawem zapisu i odczytu) tworzy się w InfluxDB.",
    "influx3": "InfluxDB 3.x: zapis przez /api/v3/write_lp, odczyt przez SQL. Token może być pusty, gdy serwer nie wymaga logowania.",
    "timescale": "TimescaleDB (PostgreSQL): tabele tworzone automatycznie, hypertable i kompresja po 7 dniach, jeśli rozszerzenie "
                 "timescaledb jest dostępne (zwykły PostgreSQL też działa).",
}


# time / reliability parameters shown for each kind of target (the definitions are in store.PARAMS)
PARAMS_OF = {
    "sqlite": ["keyframe_min", "batch_s", "close_grace_s", "rotate_mb", "read_max_points"],
    **{k: ["keyframe_min", "batch_s", "retry_max_s", "test_timeout_s", "http_timeout_s", "close_grace_s", "queue_max",
           "spool_mb", "read_max_points"] for k in st.StoreConfig.NETWORK},
}


class StoreDialog(QDialog):
    """Settings of one database target. `kind` is fixed by the caller (chosen in the REC panel / import window)."""

    def __init__(self, cfg: st.StoreConfig, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.cfg = replace(cfg, kind=kind)
        self.setWindowTitle(f"Ustawienia: {st.KIND_LABEL[kind]}")
        self.setMinimumWidth(560)
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs, 1)
        page = QWidget()
        tabs.addTab(page, "Połączenie")
        lay = QVBoxLayout(page)
        hint = QLabel(HINTS[kind])
        hint.setWordWrap(True)
        lay.addWidget(hint)
        form = QFormLayout()
        lay.addLayout(form)
        self.edits: dict[str, QLineEdit | QSpinBox] = {}
        for label, attr, typ in FIELDS[kind]:
            val = getattr(self.cfg, attr)
            if typ == "int":
                w = QSpinBox()
                w.setRange(1, 65535)
                w.setValue(int(val))
            else:
                w = QLineEdit(str(val))
                if typ == "secret":
                    w.setEchoMode(QLineEdit.Password)
            self.edits[attr] = w
            if typ == "file":
                row = QHBoxLayout()
                row.addWidget(w)
                b = QPushButton("...")
                b.clicked.connect(self._browse)
                row.addWidget(b)
                form.addRow(label, row)
            else:
                form.addRow(label, w)
        self.chk_remember = QCheckBox("Zapamiętaj hasło / token w konfiguracji (plik na dysku, jawnym tekstem)")
        self.chk_remember.setChecked(self.cfg.remember)
        if kind != "sqlite":
            lay.addWidget(self.chk_remember)
        lay.addStretch(1)
        self._build_times(tabs)
        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        self.lbl.setTextFormat(Qt.RichText)
        outer.addWidget(self.lbl)
        row = QHBoxLayout()
        self.btn_test = QPushButton("Testuj połączenie")
        self.btn_test.clicked.connect(self.test)
        row.addWidget(self.btn_test)
        row.addStretch(1)
        ok, cancel = QPushButton("OK"), QPushButton("Anuluj")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        outer.addLayout(row)

    def _build_times(self, tabs: QTabWidget) -> None:
        """The 'Czasy i bufory' tab: every time-related parameter with a precise description under it."""
        self.params: dict[str, QSpinBox | QDoubleSpinBox] = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        intro = QLabel("Wszystkie parametry czasowe zapisu. Wartości domyślne są dobrane do nagrań trwających godziny "
                       "i dni; zmieniaj je tylko, gdy wiesz, po co (opis pod każdym polem).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        lay.addLayout(form)
        defaults = st.StoreConfig()
        for name in PARAMS_OF[self.kind]:
            label, lo, hi, unit, desc = st.PARAMS[name]
            cur = getattr(self.cfg, name)
            if isinstance(getattr(defaults, name), float):
                w = QDoubleSpinBox()
                w.setDecimals(2)
            else:
                w = QSpinBox()
            w.setRange(lo, hi)
            w.setValue(cur)
            w.setSuffix(" " + unit)
            if lo == 0:
                w.setSpecialValueText("wyłączone")
            w.setToolTip(desc)
            self.params[name] = w
            form.addRow(label + ":", w)
            d = QLabel(f"{desc}  <i>Domyślnie: {self._fmt(getattr(defaults, name), unit)}.</i>")
            d.setWordWrap(True)
            d.setTextFormat(Qt.RichText)
            d.setStyleSheet("color: gray; font-size: 11px; margin-bottom: 6px;")
            form.addRow(d)
        self.chk_daily = QCheckBox("SQLite: nowy plik każdego dnia")
        self.chk_daily.setChecked(self.cfg.rotate_daily)
        self.chk_daily.setToolTip("Pierwsze nagranie rozpoczęte danego dnia trafia do nowego pliku (nazwa_RRRR-MM-DD.db). "
                                  "Kilkudniowe nagranie nie jest dzielone – jedno nagranie zostaje w jednym pliku.")
        if self.kind == "sqlite":
            lay.addWidget(self.chk_daily)
        lay.addStretch(1)
        reset = QPushButton("Przywróć wartości domyślne")
        reset.clicked.connect(self._reset_times)
        lay.addWidget(reset, 0, Qt.AlignLeft)
        tabs.addTab(scroll, "Czasy i bufory")

    @staticmethod
    def _fmt(v, unit: str) -> str:
        return "wyłączone" if v == 0 else f"{v:g} {unit}"

    def _reset_times(self) -> None:
        d = st.StoreConfig()
        for name, w in self.params.items():
            w.setValue(getattr(d, name))
        self.chk_daily.setChecked(d.rotate_daily)

    def _browse(self) -> None:
        cur = self.edits["sqlite_path"].text().strip() or "s7trace.db"
        path, _ = QFileDialog.getSaveFileName(self, "Plik bazy SQLite", cur if cur.startswith(("/", "\\")) or ":" in cur
                                              else data_dir() + "\\" + cur, "SQLite (*.db *.sqlite);;Wszystkie (*.*)")
        if path:
            self.edits["sqlite_path"].setText(path)

    def config(self) -> st.StoreConfig:
        c = replace(self.cfg)
        for attr, w in self.edits.items():
            setattr(c, attr, w.value() if isinstance(w, QSpinBox) else w.text().strip())
        c.remember = self.chk_remember.isChecked() and self.kind != "sqlite"
        for name, w in self.params.items():
            setattr(c, name, w.value())
        c.rotate_daily = self.chk_daily.isChecked() if self.kind == "sqlite" else self.cfg.rotate_daily
        return c

    def test(self) -> None:
        self.btn_test.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            c = self.config()
            msg = st.test_connection(c, data_dir(), c.test_timeout_s if "test_timeout_s" in self.params else None)
            self.lbl.setText(f"<span style='color:#4ec04e'><b>OK</b></span> – {msg}")
        except st.StoreError as e:
            self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {e}")
        except Exception as e:                                   # a driver error that is not ours
            self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_test.setEnabled(True)

    def accept(self) -> None:
        super().accept()


class StoreImportDialog(QDialog):
    """Pick a recording from a database and load it into the tab (whole recording or a time range)."""

    COLS = ["Początek", "Nazwa / konfiguracja", "IP", "Karta", "Zapis", "Sygnały"]

    def __init__(self, cfg: st.StoreConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg if cfg.kind in DB_KINDS else replace(cfg, kind="sqlite")
        self.sessions: list[dict] = []
        self.result: tuple | None = None                         # (meta, t_us, matrix, store config)
        self.note = ""                                           # e.g. "thinned out from N to M rows"
        self.setWindowTitle("Import z bazy → wykres")
        self.resize(900, 460)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Baza:"))
        self.cb_kind = QComboBox()
        for k in DB_KINDS:
            self.cb_kind.addItem(st.KIND_LABEL[k], k)
        self.cb_kind.setCurrentIndex(DB_KINDS.index(self.cfg.kind))
        top.addWidget(self.cb_kind)
        self.btn_set = QPushButton("Ustawienia…")
        self.btn_set.clicked.connect(self.edit_settings)
        top.addWidget(self.btn_set)
        self.btn_list = QPushButton("Odśwież listę")
        self.btn_list.clicked.connect(self.refresh)
        top.addWidget(self.btn_list)
        top.addStretch(1)
        lay.addLayout(top)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.itemDoubleClicked.connect(lambda *_: self.load())
        lay.addWidget(self.table, 1)
        rng = QHBoxLayout()
        self.chk_range = QCheckBox("Tylko zakres czasu:")
        self.chk_range.toggled.connect(self._range_enabled)
        rng.addWidget(self.chk_range)
        self.dt0, self.dt1 = QDateTimeEdit(), QDateTimeEdit()
        for w in (self.dt0, self.dt1):
            w.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            w.setCalendarPopup(True)
        rng.addWidget(self.dt0)
        rng.addWidget(QLabel("do"))
        rng.addWidget(self.dt1)
        rng.addStretch(1)
        lay.addLayout(rng)
        self.lbl = QLabel("Wybierz nagranie. Przy wielogodzinnych nagraniach wczytaj węższy zakres czasu.")
        self.lbl.setWordWrap(True)
        self.lbl.setTextFormat(Qt.RichText)
        lay.addWidget(self.lbl)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_load = QPushButton("Wczytaj")
        self.btn_load.setEnabled(False)
        self.btn_load.clicked.connect(self.load)
        self.btn_csv = QPushButton("Zapisz jako CSV…")
        self.btn_csv.setToolTip("Zapisuje wybrane nagranie (albo zakres czasu) do pliku CSV – wszystkie wiersze, bez zmniejszania.")
        self.btn_csv.setEnabled(False)
        self.btn_csv.clicked.connect(self.export_csv)
        close = QPushButton("Zamknij")
        close.clicked.connect(self.reject)
        row.addWidget(self.btn_csv)
        row.addWidget(self.btn_load)
        row.addWidget(close)
        lay.addLayout(row)
        self.cb_kind.currentIndexChanged.connect(self._kind_changed)
        now = QDateTime.currentDateTime()
        self.dt0.setDateTime(now.addSecs(-3600))
        self.dt1.setDateTime(now)
        self._range_enabled(False)

    # ---- settings / list
    def _kind_changed(self) -> None:
        self.cfg = replace(self.cfg, kind=self.cb_kind.currentData())
        self.sessions = []
        self.table.setRowCount(0)
        self.btn_load.setEnabled(False)

    def edit_settings(self) -> None:
        d = StoreDialog(self.cfg, self.cb_kind.currentData(), self)
        if d.exec():
            self.cfg = d.config()

    def refresh(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.sessions = []
            for c in self._sources():                            # SQLite: the file and its rotated siblings
                b = st.open_backend(c, data_dir())
                try:
                    for s in b.sessions():
                        self.sessions.append({**s, "_cfg": c})
                finally:
                    b.close()
            self.sessions.sort(key=lambda s: -s["start_us"])
        except st.StoreError as e:
            self.sessions = []
            self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {e}")
        except Exception as e:
            self.sessions = []
            self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {e}")
        finally:
            QApplication.restoreOverrideCursor()
        self.table.setRowCount(len(self.sessions))
        for r, s in enumerate(self.sessions):
            vals = [datetime.fromtimestamp(s["start_us"] / 1e6).strftime("%Y-%m-%d %H:%M:%S"),
                    s.get("conf") or s.get("name") or "", s.get("ip", ""), s.get("tab", ""),
                    st.MODE_LABEL.get(s.get("mode"), s.get("mode", "")), str(len(s.get("signals", [])))]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                self.table.setItem(r, c, it)
        if self.sessions:
            self.lbl.setText(f"Nagrań w bazie: <b>{len(self.sessions)}</b>")
            self.table.selectRow(0)

    def _sources(self) -> list[st.StoreConfig]:
        if self.cfg.kind != "sqlite":
            return [self.cfg]
        p = self.cfg.sqlite_path or "s7trace.db"
        p = p if os.path.isabs(p) else os.path.join(data_dir(), p)
        return [replace(self.cfg, sqlite_path=f) for f in st.sqlite_family(p) if os.path.exists(f)] or [self.cfg]

    def _selected(self) -> None:
        r = self.table.currentRow()
        ok = 0 <= r < len(self.sessions)
        self.btn_load.setEnabled(ok)
        self.btn_csv.setEnabled(ok)
        if ok:
            s = self.sessions[r]
            self.dt0.setDateTime(QDateTime.fromSecsSinceEpoch(int(s["start_us"] / 1e6)))
            end = s.get("end_us") or s["start_us"] + 3_600_000_000
            self.dt1.setDateTime(QDateTime.fromSecsSinceEpoch(int(end / 1e6) + 1))

    def _range_enabled(self, on: bool) -> None:
        self.dt0.setEnabled(on)
        self.dt1.setEnabled(on)

    # ---- load
    def selected_range(self) -> tuple[int | None, int | None]:
        if not self.chk_range.isChecked():
            return None, None
        return self.dt0.dateTime().toSecsSinceEpoch() * 1_000_000, self.dt1.dateTime().toSecsSinceEpoch() * 1_000_000

    def load(self) -> None:
        r = self.table.currentRow()
        if not (0 <= r < len(self.sessions)):
            return
        try:
            meta, t, v, note = self._read(self.sessions[r], downsample=True)
        except Exception as e:
            QMessageBox.warning(self, "S7Trace", f"Wczytanie nie powiodło się: {e}")
            return
        self.note = note
        self.result = (meta, t, v, self.cfg)
        self.accept()

    def _read(self, sess: dict, downsample: bool):
        """(meta, t_us, matrix, note). With `downsample` a recording longer than 'read_max_points' is thinned out
        (min / max of every part of the time axis)."""
        t0, t1 = self.selected_range()
        c = sess.get("_cfg", self.cfg)
        limit = self.cfg.read_max_points if downsample else 0
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            b = st.open_backend(c, data_dir())
            try:
                meta, t, v = b.read(sess["id"], t0, t1, limit)
            finally:
                b.close()
            if len(t) == 0:
                raise st.StoreError("W wybranym zakresie nie ma danych.")
            n0 = len(t)
            t, v = st.downsample_minmax(t, v, limit)
        finally:
            QApplication.restoreOverrideCursor()
        note = f"; zmniejszono z {n0} do {len(t)} wierszy (min/max)" if len(t) < n0 else ""
        return meta, t, v, note

    def export_csv(self) -> None:
        """The selected recording (or its time range) as a CSV file - every row, nothing thinned out."""
        r = self.table.currentRow()
        if not (0 <= r < len(self.sessions)):
            return
        sess = self.sessions[r]
        stamp = datetime.fromtimestamp(sess["start_us"] / 1e6).strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz nagranie jako CSV",
                                              os.path.join(data_dir(), f"nagranie_{stamp}.csv"), "CSV (*.csv)")
        if not path:
            return
        try:
            meta, t, v, _ = self._read(sess, downsample=False)
            sigs = [Signal.from_dict(s) for s in meta["signals"]]
            start = datetime.fromtimestamp(float(t[0]) / 1e6)
            write_csv(path, sigs, (t - t[0]) / 1e6, v, start)
        except Exception as e:
            QMessageBox.warning(self, "S7Trace", f"Eksport nie powiódł się: {e}")
            return
        self.lbl.setText(f"Zapisano <b>{len(t)}</b> wierszy: {path}")
