"""'Sygnały do śledzenia' dialog + symbol picker."""
from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QDialog, QDoubleSpinBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QTableWidget, QVBoxLayout)

from ..core.symbols import Symbol
from ..core.types import SOURCES, TYPES, Signal, default_signal

COLS = ["Nazwa", "Źródło", "Typ", "DB", "Bajt", "Bit", "Offset Y", "Gain", "Kolor"]
STRUCTURAL = (1, 2, 3, 4, 5)   # columns locked while acquisition runs


class SymbolPicker(QDialog):
    def __init__(self, symbols: list[Symbol], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dodaj sygnały z symboli")
        self.resize(640, 480)
        self.symbols = symbols
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Szukaj po nazwie lub adresie…")
        self.filter.textChanged.connect(self._fill)
        lay.addWidget(self.filter)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Nazwa", "Adres", "Typ"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self.accept)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.info = QLabel()
        row.addWidget(self.info)
        row.addStretch()
        ok, cancel = QPushButton("Dodaj"), QPushButton("Anuluj")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        self._shown: list[Symbol] = []
        self._fill()

    def _fill(self):
        q = self.filter.text().strip().lower()
        self._shown = [s for s in self.symbols if not q or q in s.name.lower() or q in s.address.lower()][:3000]
        self.table.setRowCount(len(self._shown))
        for r, s in enumerate(self._shown):
            for c, txt in enumerate((s.name, s.address, s.dtype)):
                from PySide6.QtWidgets import QTableWidgetItem
                self.table.setItem(r, c, QTableWidgetItem(txt))
        self.info.setText(f"{len(self._shown)} z {len(self.symbols)} symboli"
                          if self.symbols else "Brak symboli — zaimportuj je z menu Plik.")

    def selected(self) -> list[Symbol]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._shown[r] for r in rows]


class SignalsDialog(QDialog):
    def __init__(self, signals: list[Signal], locked: bool, symbols: Callable[[], list[Symbol]],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sygnały do śledzenia")
        self.resize(980, 420)
        self.locked = locked
        self._symbols = symbols
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 130)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self.table)
        if locked:
            note = QLabel("Połączenie aktywne: zmiana źródła/typu/adresu możliwa po Stop. "
                          "Nazwę, offset, gain i kolor można zmieniać.")
            note.setStyleSheet("color:#e0b050")
            lay.addWidget(note)
        row = QHBoxLayout()
        self.btn_add = QPushButton("Dodaj")
        self.btn_sym = QPushButton("Z symboli…")
        self.btn_del = QPushButton("Usuń")
        for b in (self.btn_add, self.btn_sym, self.btn_del):
            row.addWidget(b)
            b.setEnabled(not locked)
        row.addStretch()
        ok, cancel = QPushButton("OK"), QPushButton("Anuluj")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.btn_add.clicked.connect(self._add)
        self.btn_del.clicked.connect(self._remove)
        self.btn_sym.clicked.connect(self._from_symbols)
        for s in signals:
            self._append(s)

    # ------------------------------------------------------------ rows
    def _append(self, s: Signal) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QLineEdit(s.name)
        src = QComboBox(); src.addItems(SOURCES); src.setCurrentText(s.source)
        typ = QComboBox(); typ.addItems(list(TYPES)); typ.setCurrentText(s.dtype)
        db = QSpinBox(); db.setRange(0, 65535); db.setValue(s.db)
        byte = QSpinBox(); byte.setRange(0, 65535); byte.setValue(s.byte)
        bit = QSpinBox(); bit.setRange(0, 7); bit.setValue(s.bit)
        off = QDoubleSpinBox(); off.setRange(-1e9, 1e9); off.setDecimals(3); off.setValue(s.offset_y)
        gain = QDoubleSpinBox(); gain.setRange(-1e9, 1e9); gain.setDecimals(4); gain.setValue(s.gain)
        color = QPushButton(); self._set_color(color, s.color)
        color.clicked.connect(lambda _=False, b=color: self._pick_color(b))
        for c, w in enumerate((name, src, typ, db, byte, bit, off, gain, color)):
            self.table.setCellWidget(r, c, w)
            if self.locked and c in STRUCTURAL:
                w.setEnabled(False)
        src.currentTextChanged.connect(lambda _=None, rr=src, d=db: d.setEnabled(rr.currentText() == "DB" and not self.locked))
        typ.currentTextChanged.connect(lambda _=None, t=typ, b=bit: b.setEnabled(t.currentText() == "BOOL" and not self.locked))
        db.setEnabled(s.source == "DB" and not self.locked)
        bit.setEnabled(s.dtype == "BOOL" and not self.locked)

    @staticmethod
    def _set_color(btn: QPushButton, color: str) -> None:
        btn.setProperty("color", color)
        btn.setStyleSheet(f"background:{color}; border:1px solid #222;")

    def _pick_color(self, btn: QPushButton) -> None:
        c = QColorDialog.getColor(QColor(btn.property("color")), self, "Kolor sygnału")
        if c.isValid():
            self._set_color(btn, c.name())

    def _row_signal(self, r: int) -> Signal:
        w = lambda c: self.table.cellWidget(r, c)
        return Signal(name=w(0).text().strip() or f"SIG{r + 1}", source=w(1).currentText(),
                      dtype=w(2).currentText(), db=w(3).value(), byte=w(4).value(), bit=w(5).value(),
                      offset_y=w(6).value(), gain=w(7).value(), color=w(8).property("color"))

    def signals(self) -> list[Signal]:
        return [self._row_signal(r) for r in range(self.table.rowCount())]

    def _add(self) -> None:
        cur = self.signals()
        self._append(default_signal(len(cur), cur))

    def _remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.rowCount():
            rows = [self.table.rowCount() - 1]
        for r in rows:
            self.table.removeRow(r)

    def _from_symbols(self) -> None:
        dlg = SymbolPicker(self._symbols(), self)
        if dlg.exec():
            for sym in dlg.selected():
                cur = self.signals()
                s = sym.to_signal()
                base = default_signal(len(cur))
                s.color, s.offset_y = base.color, base.offset_y
                self._append(s)
