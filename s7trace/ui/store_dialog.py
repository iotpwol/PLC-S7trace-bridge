"""REC target settings (SQLite / InfluxDB 1.x 2.x / TimescaleDB) and the 'Import z bazy → wykres' window."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QDateTime, QTimer, Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .table_kit import SortItem, begin_fill, end_fill, src as table_src, row_of as table_row_of, standard as standard_table
from ..core import store as st
from ..core.config import data_dir
from ..core.csvio import write_csv
from ..core.types import Signal
from .dialog_kit import dialog_info

DB_KINDS = [k for k in st.KINDS if k != "csv"]

# which fields each target needs: (label, StoreConfig attribute, kind of editor)
FIELDS = {
    "sqlite": [("Plik bazy:", "sqlite_path", "file")],
    "influx1": [("Adres (URL):", "url", "text"), ("Baza (database):", "database", "text"),
                ("Użytkownik:", "user", "text"), ("Hasło:", "password", "secret"), ("Pomiar (measurement):", "measurement", "text")],
    "influx2": [("Adres (URL):", "url", "text"), ("Organizacja (org):", "org", "text"), ("Bucket:", "bucket", "text"),
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
    "timescale": "TimescaleDB (PostgreSQL): tabele tworzone automatycznie, hypertable i kompresja (domyślnie po 7 dniach, do zmiany na zakładce „Czasy i bufory”), jeśli "
                 "rozszerzenie timescaledb jest dostępne (zwykły PostgreSQL też działa).",
}


# time / reliability parameters shown for each kind of target (the definitions are in store.PARAMS)
PARAMS_OF = {
    "sqlite": ["keyframe_min", "batch_s", "close_grace_s", "rotate_mb", "read_max_points"],
    **{k: ["keyframe_min", "batch_s", "retry_max_s", "test_timeout_s", "http_timeout_s", "close_grace_s", "queue_max",
           "spool_mb", "read_max_points"] for k in st.StoreConfig.NETWORK},
}
PARAMS_OF["timescale"] = PARAMS_OF["timescale"] + ["compress_days"]


USER_PARAMS = ["trash_days", "retention_days"]               # shown on the "Nagrania i użytkownicy" tab


@dialog_info(lambda d: f"Ustawienia zapisu: {st.KIND_LABEL[d.kind]}",
             "Gdzie i jak REC zapisuje nagrania: adres i dane bazy, czasy, bufory, rotacja plików oraz zasady nazw, kosza i użytkowników. „Test połączenia” sprawdza serwer.")
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
        self._build_users(tabs)
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

    def _param_row(self, form: QFormLayout, name: str) -> None:
        label, lo, hi, unit, desc = st.PARAMS[name]
        defaults = st.StoreConfig()
        w = QDoubleSpinBox() if isinstance(getattr(defaults, name), float) else QSpinBox()
        if isinstance(w, QDoubleSpinBox):
            w.setDecimals(2)
        w.setRange(lo, hi)
        w.setValue(getattr(self.cfg, name))
        w.setSuffix(" " + unit)
        if lo == 0:
            w.setSpecialValueText("wyłączone")
        w.setToolTip(desc)
        self.params[name] = w
        form.addRow(label + ":", w)
        form.addRow(self._note(f"{desc}  <i>Domyślnie: {self._fmt(getattr(defaults, name), unit)}.</i>"))

    @staticmethod
    def _note(html: str) -> QLabel:
        d = QLabel(html)
        d.setWordWrap(True)
        d.setTextFormat(Qt.RichText)
        d.setStyleSheet("color: gray; font-size: 11px; margin-bottom: 6px;")
        return d

    def _build_users(self, tabs: QTabWidget) -> None:
        """Names of recordings, users and the trash."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        form = QFormLayout()
        lay.addLayout(form)
        self.cb_title = QComboBox()
        for k in st.TITLE_ASK:
            self.cb_title.addItem(st.TITLE_ASK_LABEL[k], k)
        self.cb_title.setCurrentIndex(st.TITLE_ASK.index(self.cfg.title_ask))
        form.addRow("Nazwa nagrania:", self.cb_title)
        form.addRow(self._note(
            "<b>Na początku</b> – po REC pojawia się okno z tytułem, uwagami i tagami; nagrywanie rusza po jego zatwierdzeniu "
            "(Anuluj = bez nagrywania). <b>W trakcie</b> – nagrywanie rusza od razu, okno pojawia się obok i można je wypełnić "
            "w dowolnej chwili. <b>Na końcu</b> – pytanie przy zatrzymaniu REC. <b>Nie pytaj</b> – tytuł można nadać później w "
            "oknie „Przegląd nagrań” (Właściwości). <i>Domyślnie: w trakcie.</i>"))
        self.cb_scope = QComboBox()
        self.cb_scope.addItem("Tylko moje nagrania", "mine")
        self.cb_scope.addItem("Wszystkie nagrania", "all")
        self.cb_scope.setCurrentIndex(st.VIEW_SCOPES.index(self.cfg.view_scope))
        form.addRow("Przegląd nagrań pokazuje:", self.cb_scope)
        form.addRow(self._note(
            "Każde nagranie zapisuje konto Windows i nazwę komputera, z którego powstało. W bazach sieciowych (InfluxDB, "
            "TimescaleDB) nagrania wielu osób leżą razem; ten wybór ustawia domyślny filtr w oknie przeglądu (można go tam "
            "zmienić). <i>Domyślnie: tylko moje.</i>"))
        self.chk_others = QCheckBox("Pozwól usuwać i edytować nagrania innych użytkowników")
        self.chk_others.setChecked(self.cfg.delete_others)
        lay.addWidget(self.chk_others)
        lay.addWidget(self._note("Bez zaznaczenia można usuwać i edytować tylko własne nagrania (oraz stare, bez zapisanego "
                                 "właściciela). Program nie zastępuje uprawnień serwera bazy – to ustawienie jest "
                                 "zabezpieczeniem przed pomyłką. <i>Domyślnie: wyłączone.</i>"))
        self.chk_shared = QCheckBox("SQLite: wspólny folder dla wszystkich kont Windows na tym komputerze")
        self.chk_shared.setChecked(self.cfg.sqlite_shared)
        if self.kind == "sqlite":
            lay.addWidget(self.chk_shared)
            lay.addWidget(self._note(
                "Gdy ścieżka pliku jest względna, plik leży w folderze <tt>ProgramData\\S7Trace\\data</tt> zamiast w "
                "Dokumentach bieżącego konta – nagrania widzą wtedy wszyscy użytkownicy tego komputera (każdy z właścicielem "
                "w opisie). Nie używaj tego na udziale sieciowym – SQLite jest tam zawodny. <i>Domyślnie: wyłączone "
                "(każde konto ma własny plik w Dokumentach).</i>"))
        form2 = QFormLayout()
        lay.addLayout(form2)
        for name in USER_PARAMS:
            self._param_row(form2, name)
        lay.addStretch(1)
        tabs.addTab(scroll, "Nagrania i użytkownicy")

    @staticmethod
    def _fmt(v, unit: str) -> str:
        return "wyłączone" if v == 0 else f"{v:g} {unit}"

    def _reset_times(self) -> None:
        d = st.StoreConfig()
        for name, w in self.params.items():
            if name not in USER_PARAMS:
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
        c.title_ask = self.cb_title.currentData()
        c.view_scope = self.cb_scope.currentData()
        c.delete_others = self.chk_others.isChecked()
        c.sqlite_shared = self.chk_shared.isChecked() if self.kind == "sqlite" else self.cfg.sqlite_shared
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


@dialog_info("Nazwa nagrania",
             "Tytuł, uwagi i etykiety zapisywane razem z nagraniem w bazie – po nich znajdziesz je w oknie „Przegląd nagrań”.")
class RecInfoDialog(QDialog):
    """Title, notes and tags of a recording (asked when REC starts / during / ends, and edited in the overview)."""

    def __init__(self, title="", notes="", tags="", heading="", ok_text="Zapisz", cancel_text="Pomiń", parent=None, description=""):
        super().__init__(parent)
        self.setWindowTitle("Nagranie – tytuł, opis i uwagi")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        if heading:
            h = QLabel(heading)
            h.setWordWrap(True)
            lay.addWidget(h)
        form = QFormLayout()
        lay.addLayout(form)
        self.ed_title = QLineEdit(title)
        self.ed_title.setPlaceholderText("np. Rozruch pieca 2 po remoncie")
        self.ed_desc = QPlainTextEdit(description)
        self.ed_desc.setPlaceholderText("co zawiera nagranie, w jakich warunkach powstało")
        self.ed_desc.setFixedHeight(70)
        self.ed_notes = QPlainTextEdit(notes)
        self.ed_notes.setFixedHeight(70)
        self.ed_tags = QLineEdit(tags)
        self.ed_tags.setPlaceholderText("tagi po przecinku, np. rozruch, piec 2")
        form.addRow("Tytuł:", self.ed_title)
        form.addRow("Opis:", self.ed_desc)
        form.addRow("Uwagi:", self.ed_notes)
        form.addRow("Tagi:", self.ed_tags)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_ok, self.btn_cancel = QPushButton(ok_text), QPushButton(cancel_text)
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_ok)
        row.addWidget(self.btn_cancel)
        lay.addLayout(row)

    def values(self) -> dict:
        return {"title": self.ed_title.text().strip(), "description": self.ed_desc.toPlainText().strip(),
                "notes": self.ed_notes.toPlainText().strip(),
                "tags": self.ed_tags.text().strip()}


class SortItem(QTableWidgetItem):
    """A table cell that sorts by a key (time, count) instead of its text."""

    def __init__(self, text: str, key=None):
        super().__init__(text)
        self.key = text.lower() if key is None else key

    def __lt__(self, other) -> bool:
        k = getattr(other, "key", other.text().lower())
        try:
            return self.key < k
        except TypeError:
            return str(self.key) < str(k)


DAYS_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


def fmt_duration(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec} s"
    if sec < 3600:
        return f"{sec // 60} min {sec % 60:02d} s"
    return f"{sec // 3600} h {sec % 3600 // 60:02d} min"


@dialog_info("Przegląd nagrań",
             "Nagrania zapisane w bazie danych: sortowanie, wyszukiwanie, opisy, kosz, usuwanie i wczytanie wybranego przebiegu (albo zakresu czasu) na wykres.")
class StoreImportDialog(QDialog):
    """Przegląd nagrań: the recordings of a database (sort, search, filter by user), their title / notes / tags, the trash,
    deleting, export to CSV and loading a recording (or a time range of it) into the tab."""

    COLS = [("start", "Początek"), ("dur", "Czas trwania"), ("title", "Tytuł"), ("desc", "Opis"), ("tags", "Tagi"), ("notes", "Uwagi"),
            ("owner", "Użytkownik"), ("computer", "Komputer"), ("conf", "Konfiguracja"), ("ip", "IP"), ("tab", "Karta"),
            ("plc", "Sterownik"), ("plc_sn", "Nr seryjny"), ("mode", "Zapis"), ("sigs", "Sygnały"), ("events", "Wpisy")]

    def __init__(self, cfg: st.StoreConfig, parent=None, can_load: bool = True, base_dir: str | None = None):
        super().__init__(parent)
        self.cfg = cfg if cfg.kind in DB_KINDS else replace(cfg, kind="sqlite")
        self.can_load = can_load
        self.base_dir = base_dir if base_dir is not None else data_dir()
        self.all: list[dict] = []                                # every recording of the database (incl. the trash)
        self.sessions: list[dict] = []                           # the ones shown
        self.result: tuple | None = None                         # (meta, t_us, matrix, store config)
        self.note = ""                                           # e.g. "thinned out from N to M rows"
        self._policies_done = False
        self._shown_once = False
        self.setWindowTitle("Przegląd nagrań")
        self.resize(1180, 560)
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
        self.btn_spool = QPushButton("Zaległe bufory…")
        self.btn_spool.setToolTip("Dane, które nie zdążyły dotrzeć do serwera przed zamknięciem programu.")
        self.btn_spool.clicked.connect(self.open_spools)
        top.addWidget(self.btn_spool)
        top.addStretch(1)
        lay.addLayout(top)
        flt = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Szukaj w tytule, uwagach, tagach, konfiguracji, użytkowniku…")
        self.ed_search.setClearButtonEnabled(True)
        flt.addWidget(self.ed_search, 1)
        flt.addWidget(QLabel("Pokaż:"))
        self.cb_user = QComboBox()
        flt.addWidget(self.cb_user)
        self.chk_trash = QCheckBox("Kosz")
        self.chk_trash.setToolTip("Pokazuje usunięte nagrania (można je przywrócić do czasu opróżnienia kosza).")
        flt.addWidget(self.chk_trash)
        self.chk_group = QCheckBox("Grupuj po dniach")
        self.chk_group.setToolTip("Nagłówek z datą nad nagraniami z danego dnia (najnowsze dni na górze). "
                                  "Przy grupowaniu sortowanie po kolumnach jest wyłączone.")
        flt.addWidget(self.chk_group)
        lay.addLayout(flt)
        self._set_users([])
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([h for _, h in self.COLS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        standard_table(self.table)
        self.table.setSortingEnabled(True)
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
        self.btn_props = QPushButton("Właściwości…")
        self.btn_props.setToolTip("Tytuł, uwagi i tagi wybranego nagrania.")
        self.btn_props.clicked.connect(self.edit_properties)
        self.btn_plc = QPushButton("Sterownik…")
        self.btn_plc.setToolTip("Dane sterownika PLC zapisane razem z nagraniem (model, numer katalogowy, firmware, numer seryjny…).")
        self.btn_plc.clicked.connect(self.show_device)
        self.btn_del = QPushButton("Usuń")
        self.btn_del.clicked.connect(self.delete_selected)
        self.btn_restore = QPushButton("Przywróć")
        self.btn_restore.clicked.connect(self.restore_selected)
        self.btn_empty = QPushButton("Opróżnij kosz")
        self.btn_empty.clicked.connect(self.empty_trash)
        for b in (self.btn_props, self.btn_plc, self.btn_del, self.btn_restore, self.btn_empty):
            row.addWidget(b)
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
        self.ed_search.textChanged.connect(self._fill)
        self.cb_user.currentIndexChanged.connect(self._fill)
        self.chk_trash.toggled.connect(self._fill)
        self.chk_group.toggled.connect(self._fill)
        now = QDateTime.currentDateTime()
        self.dt0.setDateTime(now.addSecs(-3600))
        self.dt1.setDateTime(now)
        self._range_enabled(False)
        self._update_buttons()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._shown_once:                                 # the list is read when the window opens
            self._shown_once = True
            QTimer.singleShot(0, self.refresh)

    # ---- helpers
    def cell(self, row: int, key: str) -> str:
        """Text of the cell in column `key` (columns are identified by name, not by position)."""
        return self.table.item(row, [k for k, _ in self.COLS].index(key)).text()

    def own(self, s: dict) -> bool:
        return s.get("owner", "") in ("", st.current_user())      # recordings of older versions have no owner: they are yours

    def running(self, s: dict) -> bool:
        return s["id"] in st._ACTIVE_SESSIONS                     # being recorded by this program right now

    def can_modify(self, s: dict) -> bool:
        return (self.own(s) or self.cfg.delete_others) and not self.running(s)

    def _set_users(self, owners: list[str]) -> None:
        keep = self.cb_user.currentData() if self.cb_user.count() else self.cfg.view_scope
        self.cb_user.blockSignals(True)
        self.cb_user.clear()
        self.cb_user.addItem("Moje nagrania", "mine")
        self.cb_user.addItem("Wszystkie nagrania", "all")
        for o in sorted(set(owners)):
            if o and o != st.current_user():
                self.cb_user.addItem(f"Użytkownik: {o}", "u:" + o)
        i = self.cb_user.findData(keep)
        self.cb_user.setCurrentIndex(i if i >= 0 else 0)
        self.cb_user.blockSignals(False)

    @contextmanager
    def _backend(self, s: dict):
        b = st.open_backend(s.get("_cfg", self.cfg), self.base_dir)
        try:
            yield b
        finally:
            b.close()

    def _kind_changed(self) -> None:
        self.cfg = replace(self.cfg, kind=self.cb_kind.currentData())
        self._policies_done = False
        self.all, self.sessions = [], []
        self._fill()
        self.refresh()                                           # the other database is read at once

    def edit_settings(self) -> None:
        d = StoreDialog(self.cfg, self.cb_kind.currentData(), self)
        if d.exec():
            self.cfg = d.config()

    def _sources(self) -> list[st.StoreConfig]:
        if self.cfg.kind != "sqlite":
            return [self.cfg]
        p = self.cfg.sqlite_path or "s7trace.db"
        p = p if os.path.isabs(p) else os.path.join(st.effective_base(self.cfg, self.base_dir), p)
        return [replace(self.cfg, sqlite_path=f) for f in st.sqlite_family(p) if os.path.exists(f)] or [self.cfg]

    # ---- reading the list
    def refresh(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        err = ""
        try:
            self.all = []
            for c in self._sources():                            # SQLite: the file and its rotated siblings
                b = st.open_backend(c, self.base_dir)
                try:
                    try:
                        stats = b.stats()
                    except Exception:
                        stats = {}
                    for s in b.sessions():
                        self.all.append({**s, "_cfg": c, "_events": stats.get(s["id"])})
                finally:
                    b.close()
        except Exception as e:                                   # StoreError or a driver error that is not ours
            self.all, err = [], str(e)
        finally:
            QApplication.restoreOverrideCursor()
        if err:
            self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {err}")
        elif not self._policies_done:
            self._policies_done = True
            if self._apply_policies():                           # the trash / retention changed something: read again
                return self.refresh()
        self._set_users([s["owner"] for s in self.all])
        self._fill()
        if not err:
            self._status_line()

    def _apply_policies(self) -> bool:
        """Empties the trash of recordings that have been there longer than 'Kosz: przechowuj' and moves own recordings
        older than 'Automatyczne czyszczenie' to the trash."""
        now = int(time.time() * 1e6)
        changed = False
        for s in list(self.all):
            try:
                with self._backend(s) as b:
                    if s["deleted_us"]:
                        if self.can_modify(s) and now - s["deleted_us"] > self.cfg.trash_days * 86_400_000_000:
                            b.delete_session(s["id"])
                            changed = True
                    elif self.cfg.retention_days > 0 and self.own(s) and \
                            now - s["start_us"] > self.cfg.retention_days * 86_400_000_000:
                        if self.cfg.trash_days > 0:
                            b.update_session(s["id"], {"deleted_us": now})
                        else:
                            b.delete_session(s["id"])
                        changed = True
            except Exception:
                continue
        return changed

    def _status_line(self) -> None:
        live = [s for s in self.all if not s["deleted_us"]]
        trash = [s for s in self.all if s["deleted_us"]]
        ev = sum(s["_events"] or 0 for s in live)
        txt = f"Nagrań w bazie: <b>{len(live)}</b>" + (f", w koszu: <b>{len(trash)}</b>" if trash else "")
        if ev:
            txt += f", wpisów: <b>{ev:,}</b>".replace(",", " ")
        if self.chk_trash.isChecked() and self.cfg.trash_days > 0:
            txt += f". Kosz opróżnia się sam po {self.cfg.trash_days} dniach."
        n = len(st.scan_spools(self.base_dir)) if self.cfg.kind in st.StoreConfig.NETWORK else 0
        self.btn_spool.setVisible(n > 0)
        if n:
            txt += f"  <span style='color:#e0a030'>Zaległe bufory zapisu: {n}.</span>"
        self.lbl.setText(txt)

    def _fill(self) -> None:
        trash = self.chk_trash.isChecked()
        who = self.cb_user.currentData()
        needle = self.ed_search.text().strip().lower()
        rows = []
        for s in self.all:
            if bool(s["deleted_us"]) != trash:
                continue
            if who == "mine" and not self.own(s):
                continue
            if who and who.startswith("u:") and s["owner"] != who[2:]:
                continue
            hay = " ".join([str(s.get(k, "")) for k in ("title", "description", "notes", "tags", "conf", "name", "tab", "ip", "owner",
                                                           "computer")] + [v for _l, v in st.device_lines(s.get("device"))]).lower()
            if needle and needle not in hay:
                continue
            rows.append(s)
        self.sessions = rows
        grouped = self.chk_group.isChecked()
        self.table.setSortingEnabled(False)
        self.table.clearSpans()
        order = sorted(range(len(rows)), key=lambda i: -rows[i]["start_us"]) if grouped else list(range(len(rows)))
        layout, day = [], None                                   # table rows: ("day", text) headers and ("rec", index)
        for i in order:
            if grouped:
                d = datetime.fromtimestamp(rows[i]["start_us"] / 1e6).date()
                if d != day:
                    day = d
                    n = sum(1 for k in order if datetime.fromtimestamp(rows[k]["start_us"] / 1e6).date() == d)
                    layout.append(("day", f"{d:%Y-%m-%d} ({DAYS_PL[d.weekday()]}) – {n} nagr."))
            layout.append(("rec", i))
        self.table.setRowCount(len(layout))
        for r, (kind, ref) in enumerate(layout):
            if kind == "day":
                it = QTableWidgetItem(ref)
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setFlags(Qt.ItemIsEnabled)                    # not selectable
                it.setBackground(self.palette().alternateBase())
                self.table.setItem(r, 0, it)
                self.table.setSpan(r, 0, 1, len(self.COLS))
                continue
            idx, s = ref, rows[ref]
            end = s.get("end_us")
            dur = max((end - s["start_us"]) / 1e6, 0) if end else None
            vals = {
                "start": (datetime.fromtimestamp(s["start_us"] / 1e6).strftime("%Y-%m-%d %H:%M:%S"), s["start_us"]),
                "dur": (fmt_duration(dur) if dur is not None else "trwa / nie zakończono", dur if dur is not None else -1),
                "title": (s["title"], None), "desc": (s.get("description", "").replace("\n", " "), None), "tags": (s["tags"], None),
                "notes": (s["notes"].replace("\n", " "), None), "owner": (s["owner"], None),
                "computer": (s["computer"], None), "conf": (s.get("conf") or s.get("name") or "", None),
                "ip": (s.get("ip", ""), None), "tab": (s.get("tab", ""), None),
                "plc": (st.device_title(s.get("device")), None),
                "plc_sn": (str((s.get("device") or {}).get("info", {}).get("serial", "")), None),
                "mode": (st.MODE_LABEL.get(s.get("mode"), s.get("mode", "")), None),
                "sigs": (str(len(s.get("signals", []))), len(s.get("signals", []))),
                "events": ("" if s["_events"] is None else f"{s['_events']:,}".replace(",", " "), s["_events"] or 0)}
            for c, (key, _h) in enumerate(self.COLS):
                text, k = vals[key]
                it = SortItem(text, k)
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                if key in ("plc", "plc_sn") and s.get("device"):
                    it.setToolTip("\n".join(f"{a}: {b}" for a, b in st.device_lines(s["device"])))
                if key == "start":
                    it.setData(Qt.UserRole, idx)
                    if s["deleted_us"] or not self.can_modify(s):
                        it.setToolTip("Usunięte" if s["deleted_us"] else
                                      "Nagranie trwa" if self.running(s) else "Nagranie innego użytkownika")
                self.table.setItem(r, c, it)
        if not grouped:
            self.table.setSortingEnabled(True)
            self.table.sortByColumn(0, Qt.DescendingOrder)
        first = next((r for r, (k, _) in enumerate(layout) if k == "rec"), None)
        if first is not None:
            self.table.selectRow(first)
        self._update_buttons()

    def _picked(self) -> list[dict]:
        out = []
        for r in sorted({i.row() for i in self.table.selectedItems()}):
            it = self.table.item(r, 0)
            idx = it.data(Qt.UserRole) if it else None
            if idx is not None and 0 <= idx < len(self.sessions):
                out.append(self.sessions[idx])
        return out

    def _selected(self) -> None:
        sel = self._picked()
        if len(sel) == 1:
            s = sel[0]
            self.dt0.setDateTime(QDateTime.fromSecsSinceEpoch(int(s["start_us"] / 1e6)))
            end = s.get("end_us") or s["start_us"] + 3_600_000_000
            self.dt1.setDateTime(QDateTime.fromSecsSinceEpoch(int(end / 1e6) + 1))
        self._update_buttons()

    def _update_buttons(self) -> None:
        sel = self._picked()
        trash = self.chk_trash.isChecked()
        one = len(sel) == 1
        self.btn_load.setEnabled(one and not trash and self.can_load)
        self.btn_load.setToolTip("" if self.can_load else "Wczytanie na wykres jest możliwe, gdy karta jest zatrzymana.")
        self.btn_csv.setEnabled(one)
        self.btn_props.setEnabled(one and self.can_modify(sel[0]))
        self.btn_plc.setEnabled(one)
        mods = bool(sel) and all(self.can_modify(s) for s in sel)
        self.btn_del.setEnabled(mods)
        self.btn_del.setText("Usuń trwale" if trash else "Usuń")
        self.btn_restore.setVisible(trash)
        self.btn_restore.setEnabled(mods)
        self.btn_empty.setVisible(trash)
        self.btn_empty.setEnabled(any(self.can_modify(s) for s in self.sessions))

    def _range_enabled(self, on: bool) -> None:
        self.dt0.setEnabled(on)
        self.dt1.setEnabled(on)

    # ---- properties, trash, deleting
    def edit_properties(self) -> None:
        sel = self._picked()
        if len(sel) != 1 or not self.can_modify(sel[0]):
            return
        s = sel[0]
        d = RecInfoDialog(s["title"], s["notes"], s["tags"], ok_text="Zapisz", cancel_text="Anuluj", parent=self,
                          description=s.get("description", ""))
        if not d.exec():
            return
        try:
            with self._backend(s) as b:
                b.update_session(s["id"], d.values())
        except Exception as e:
            QMessageBox.warning(self, "S7Trace", f"Nie udało się zapisać opisu: {e}")
            return
        s.update(d.values())
        self._fill()
        self._status_line()

    def show_device(self) -> None:
        sel = self._picked()
        if len(sel) != 1:
            return
        rows = st.device_lines(sel[0].get("device"))
        if not rows:
            QMessageBox.information(self, "Sterownik", "To nagranie nie ma zapisanych danych sterownika (powstało w starszej wersji "
                                    "programu albo przed odczytem danych sterownika).")
            return
        html = "<table cellpadding='3'>" + "".join(f"<tr><td>{a}</td><td><b>{b}</b></td></tr>" for a, b in rows) + "</table>"
        QMessageBox.information(self, "Sterownik – " + (sel[0]["title"] or sel[0].get("conf") or sel[0]["id"]), html)

    def _describe(self, sel: list[dict]) -> str:
        names = [f"• {datetime.fromtimestamp(s['start_us'] / 1e6):%Y-%m-%d %H:%M}  {s['title'] or s.get('conf') or s['id']}"
                 for s in sel[:6]]
        return "\n".join(names) + (f"\n… i {len(sel) - 6} więcej" if len(sel) > 6 else "")

    def delete_selected(self) -> None:
        sel = [s for s in self._picked() if self.can_modify(s)]
        if not sel:
            return
        in_trash = self.chk_trash.isChecked()
        permanent = in_trash or self.cfg.trash_days <= 0
        if permanent:
            text = f"Usunąć TRWALE {len(sel)} nagr.? Tej operacji nie można cofnąć.\n\n{self._describe(sel)}"
        else:
            text = (f"Przenieść do kosza {len(sel)} nagr.? Można je przywrócić przez {self.cfg.trash_days} dni, potem znikną "
                    f"na stałe.\n\n{self._describe(sel)}")
        if QMessageBox.question(self, "Usuń nagrania", text) != QMessageBox.Yes:
            return
        self._apply(sel, permanent)

    def restore_selected(self) -> None:
        sel = [s for s in self._picked() if self.can_modify(s)]
        errs = []
        for s in sel:
            try:
                with self._backend(s) as b:
                    b.update_session(s["id"], {"deleted_us": None})
                s["deleted_us"] = None
            except Exception as e:
                errs.append(str(e))
        if errs:
            QMessageBox.warning(self, "S7Trace", "Nie udało się przywrócić: " + errs[0])
        self._fill()
        self._status_line()

    def empty_trash(self) -> None:
        sel = [s for s in self.all if s["deleted_us"] and self.can_modify(s)]
        if not sel:
            return
        if QMessageBox.question(self, "Opróżnij kosz", f"Usunąć trwale {len(sel)} nagr. z kosza?\n\n{self._describe(sel)}") \
                != QMessageBox.Yes:
            return
        self._apply(sel, True)

    def _apply(self, sel: list[dict], permanent: bool) -> None:
        errs, now = [], int(time.time() * 1e6)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for s in sel:
                try:
                    with self._backend(s) as b:
                        if permanent:
                            b.delete_session(s["id"])
                            self.all.remove(s)
                        else:
                            b.update_session(s["id"], {"deleted_us": now})
                            s["deleted_us"] = now
                except Exception as e:
                    errs.append(str(e))
        finally:
            QApplication.restoreOverrideCursor()
        self._fill()
        self._status_line()
        if errs:
            QMessageBox.warning(self, "S7Trace", "\n".join(sorted(set(errs))[:4]))

    def open_spools(self) -> None:
        SpoolDialog(self.cfg, self.base_dir, self).exec()
        self._status_line()

    # ---- load
    def selected_range(self) -> tuple[int | None, int | None]:
        if not self.chk_range.isChecked():
            return None, None
        return self.dt0.dateTime().toSecsSinceEpoch() * 1_000_000, self.dt1.dateTime().toSecsSinceEpoch() * 1_000_000

    def load(self) -> None:
        sel = self._picked()
        if len(sel) != 1 or not self.can_load or self.chk_trash.isChecked():
            return
        try:
            meta, t, v, note = self._read(sel[0], downsample=True)
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
            b = st.open_backend(c, self.base_dir)
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
        sel = self._picked()
        if len(sel) != 1:
            return
        sess = sel[0]
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


@dialog_info("Zaległe bufory zapisu",
             "Dane, których nie udało się wysłać do bazy (serwer był niedostępny) i które czekają na dysku. Można je dosłać, zachować albo usunąć.")
class SpoolDialog(QDialog):
    """Buffers left on disk by recordings that could not deliver everything (the server was away when the program closed)."""

    def __init__(self, cfg: st.StoreConfig, base_dir: str, parent=None):
        super().__init__(parent)
        self.cfg, self.base_dir = cfg, base_dir
        self.setWindowTitle("Zaległe bufory zapisu")
        self.resize(820, 340)
        lay = QVBoxLayout(self)
        info = QLabel("Dane zapisane na dysku, bo serwer bazy był niedostępny. Program dosyła je sam przy następnym nagraniu "
                      "do tej samej bazy; tu można to zrobić od razu albo usunąć bufor.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Nagranie", "Cel", "Wpisów", "Rozmiar", "Ta baza?"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        standard_table(self.table, sort=True)
        lay.addWidget(self.table, 1)
        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        row = QHBoxLayout()
        self.btn_send = QPushButton("Wyślij teraz")
        self.btn_send.clicked.connect(self.send)
        self.btn_del = QPushButton("Usuń bufor")
        self.btn_del.clicked.connect(self.remove)
        close = QPushButton("Zamknij")
        close.clicked.connect(self.accept)
        row.addWidget(self.btn_send)
        row.addWidget(self.btn_del)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.items: list[dict] = []
        self.table.itemSelectionChanged.connect(self._buttons)
        self.refresh()

    def refresh(self) -> None:
        self.items = st.scan_spools(self.base_dir)
        self.table.setRowCount(len(self.items))
        begin_fill(self.table)
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            m = it["meta"]
            when = datetime.fromtimestamp(m.get("start_us", 0) / 1e6).strftime("%Y-%m-%d %H:%M:%S") if m.get("start_us") else "?"
            vals = [f"{when}  {m.get('title') or m.get('conf') or it['name']}", it["target"], f"{it['rows']:,}".replace(",", " "),
                    f"{it['size'] / 1e6:.1f} MB", "tak" if it["target"] == self.cfg.describe() else "nie"]
            keys = (None, None, it["rows"], it["size"], None)
            for c, v in enumerate(vals):
                self.table.setItem(r, c, SortItem(v, keys[c]))
        end_fill(self.table)
        if self.items:
            self.table.selectRow(0)
        self._buttons()

    def _cur(self) -> dict | None:
        r = self.table.currentRow()
        return self.items[table_src(self.table, r)] if 0 <= r < len(self.items) else None

    def _buttons(self) -> None:
        it = self._cur()
        self.btn_send.setEnabled(bool(it) and it["target"] == self.cfg.describe())
        self.btn_del.setEnabled(bool(it))

    def send(self) -> None:
        it = self._cur()
        if not it:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            n = st.deliver_spool(self.cfg, it["path"], self.base_dir)
            self.lbl.setText(f"<span style='color:#4ec04e'><b>OK</b></span> – wysłano {n} wpisów.")
        except Exception as e:
            self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {e}")
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh()

    def remove(self) -> None:
        it = self._cur()
        if not it:
            return
        if QMessageBox.question(self, "Usuń bufor", f"Usunąć bufor ({it['rows']} wpisów)? Tych danych nie da się odzyskać.") \
                != QMessageBox.Yes:
            return
        st.remove_spool(it["path"])
        self.refresh()
