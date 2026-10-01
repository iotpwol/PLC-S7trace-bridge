"""'Sygnały do śledzenia' dialog + symbol picker."""
from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QByteArray, QEvent, QObject, Qt, QTimer, Signal as QtSignal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QToolTip, QVBoxLayout, QWidget)
from PySide6.QtGui import QActionGroup

from ..core.naming import NAME_OWN, NAME_PREV, new_signal_name
from ..core.symbols import Symbol
from ..core.types import (DEFAULT_COLORS, FORMATS, SOURCES, TYPES, Signal, address_key, format_value)

# key, header, default width
COLS = [
    ("fetch", "Pobierz", 62), ("plot", "Wykres", 62), ("name", "Nazwa", 130),
    ("value", "Aktualna wartość", 125), ("fmt", "Sposób wyświetlania", 135), ("source", "Źródło", 70),
    ("dtype", "Typ", 85), ("db", "DB", 70), ("byte", "Bajt", 75), ("bit", "Bit", 55),
    ("offset", "Offset Y", 85), ("gain", "Gain", 85), ("color", "Kolor", 80), ("comment", "Opis", 220),
]
CI = {k: i for i, (k, _, _) in enumerate(COLS)}
STRUCTURAL = ("fetch", "source", "dtype", "db", "byte", "bit")   # locked while acquisition runs
ADDRESS_CELLS = ("source", "dtype", "db", "byte", "bit")

RED = "background:#9a2a2a; color:#ffffff;"
YELLOW = "background:#c9b030; color:#000000;"


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
                self.table.setItem(r, c, QTableWidgetItem(txt))
        self.info.setText(f"{len(self._shown)} z {len(self.symbols)} symboli"
                          if self.symbols else "Brak symboli — zaimportuj je z menu Plik.")

    def selected(self) -> list[Symbol]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._shown[r] for r in rows]


class RowGrip(QHeaderView):
    """Vertical header used as a drag handle: grab a row number, drag, drop on another row."""

    moved = QtSignal(int, int)                       # from row, to row

    def __init__(self, table: QTableWidget):
        super().__init__(Qt.Vertical, table)
        self._table = table
        self._src = -1
        self.dragging = False
        self.enabled_drag = True
        self.setSectionsClickable(False)
        self.setDefaultAlignment(Qt.AlignCenter)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Chwyć numer wiersza i przeciągnij, aby zmienić kolejność zmiennych")
        self._line = QWidget(table.viewport())
        self._line.setStyleSheet("background:#2a82da;")
        self._line.setFixedHeight(3)
        self._line.hide()

    def _target(self, y: int) -> int:
        n = self._table.rowCount()
        r = self._table.rowAt(y)
        return n - 1 if r < 0 and y > 0 else max(r, 0)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.enabled_drag:
            self._src = self.logicalIndexAt(ev.position().toPoint().y())
            self.dragging = False
            if self._src >= 0:
                self._table.selectRow(self._src)
            ev.accept()
        else:
            ev.ignore()

    def mouseMoveEvent(self, ev):
        if self._src < 0 or not (ev.buttons() & Qt.LeftButton):
            return
        self.dragging = True
        t = self._target(ev.position().toPoint().y())
        y = self._table.rowViewportPosition(t)
        if t > self._src:
            y += self._table.rowHeight(t)           # dropping below the row we hover
        self._line.setGeometry(0, max(y - 1, 0), self._table.viewport().width(), 3)
        self._line.show()
        self._line.raise_()
        ev.accept()

    def mouseReleaseEvent(self, ev):
        src, was = self._src, self.dragging
        self._src, self.dragging = -1, False
        self._line.hide()
        if src >= 0 and was:
            dst = self._target(ev.position().toPoint().y())
            if dst != src:
                self.moved.emit(src, dst)
        ev.accept()


class _RowFilter(QObject):
    """Row tooltip on hover + remembers the row that last had keyboard focus."""

    def __init__(self, dlg: "SignalsDialog"):
        super().__init__(dlg)
        self.dlg = dlg

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.ToolTip:
            row = self.dlg._row_of(obj)
            if row >= 0:
                QToolTip.showText(ev.globalPos(), self.dlg.row_tooltip(row), obj)
                return True
        elif t == QEvent.FocusIn:
            row = self.dlg._row_of(obj)
            if row >= 0:
                self.dlg._last_row = row
        return False


class SignalsDialog(QDialog):
    def __init__(self, signals: list[Signal], locked: bool, symbols: Callable[[], list[Symbol]],
                 opts: dict | None = None, value_provider: Callable[[], list | None] | None = None,
                 other_tabs: Callable[[], list[tuple[str, list[Signal]]]] | None = None,
                 ui_state: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sygnały do śledzenia")
        self.resize(1250, 460)
        self.locked = locked
        self._base = len(signals)          # rows that existed when the dialog opened (locked while running)
        self._symbols = symbols
        self._values = value_provider or (lambda: None)
        self._other_tabs = other_tabs or (lambda: [])
        self.ui_state = ui_state if ui_state is not None else {}
        self.opts = {"autonumber": True, "name_mode": NAME_PREV, "own_name": "SIG", "offset_step": -1.1}
        self.opts.update(opts or {})
        self._last_row = -1
        self._filter = _RowFilter(self)

        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([h for _, h, _ in COLS])
        self.grip = RowGrip(self.table)
        self.table.setVerticalHeader(self.grip)
        self.grip.setFixedWidth(30)
        self.grip.enabled_drag = not locked          # the order is the order of the data columns while running
        self.grip.moved.connect(self.move_row)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        hh.setContextMenuPolicy(Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._header_menu)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for i, (_, _, w) in enumerate(COLS):
            self.table.setColumnWidth(i, w)
        lay.addWidget(self.table)
        if locked:
            note = QLabel("Połączenie aktywne: można DODAWAĆ nowe zmienne (będą pobierane od razu po OK). "
                          "Źródło/typ/adres i „Pobierz” istniejących wierszy oraz ich kolejność i usuwanie "
                          "zmienisz po Stop; nazwę, wykres, sposób wyświetlania, offset, gain, kolor i opis "
                          "- zawsze.")
            note.setWordWrap(True)
            note.setStyleSheet("color:#e0b050")
            lay.addWidget(note)
        row = QHBoxLayout()
        self.btn_add = QPushButton("Dodaj")
        self.btn_sym = QPushButton("Z symboli…")
        self.btn_del = QPushButton("Usuń")
        for b in (self.btn_add, self.btn_sym, self.btn_del):
            row.addWidget(b)
        row.addSpacing(20)
        self.btn_save = QPushButton("Zapisz listę…")
        self.btn_load = QPushButton("Wczytaj listę…")
        self.btn_copy = QPushButton("Z innej karty…")
        for b in (self.btn_save, self.btn_load, self.btn_copy):
            row.addWidget(b)
        self.btn_load.setEnabled(not locked)
        self.btn_copy.setEnabled(not locked)
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
        self.btn_save.clicked.connect(self._save_list)
        self.btn_load.clicked.connect(self._load_list)
        self.btn_copy.clicked.connect(self._copy_from_tab)

        for s in signals:
            self._append(s)
        self._restore_state()
        self._update_marks()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh_values)
        self._timer.start()
        self._refresh_values()

    # ----------------------------------------------------------- state
    def _restore_state(self) -> None:
        st = self.ui_state
        g = st.get("geometry")
        if g:
            try:
                self.restoreGeometry(QByteArray.fromBase64(g.encode()))
            except Exception:
                pass
        for key, w in (st.get("widths") or {}).items():
            if key in CI and isinstance(w, int) and w > 10:
                self.table.setColumnWidth(CI[key], w)
        for key in st.get("hidden") or []:
            if key in CI:
                self.table.setColumnHidden(CI[key], True)

    def _save_state(self) -> None:
        st = self.ui_state
        st["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        st["widths"] = {k: self.table.columnWidth(i) for k, i in CI.items()
                        if not self.table.isColumnHidden(i)}
        st["hidden"] = [k for k, i in CI.items() if self.table.isColumnHidden(i)]

    def done(self, r: int) -> None:
        self._timer.stop()
        self._save_state()
        super().done(r)

    # ------------------------------------------------------------ rows
    def _check_cell(self, checked: bool) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        cb = QCheckBox()
        cb.setChecked(checked)
        lay.addWidget(cb)
        w._cb = cb
        return w

    def _cell(self, r: int, key: str):
        return self.table.cellWidget(r, CI[key])

    def _append(self, s: Signal) -> int:
        r = self.table.rowCount()
        self.table.insertRow(r)
        w: dict[str, QWidget] = {}
        w["fetch"] = self._check_cell(s.enabled)
        w["plot"] = self._check_cell(s.plot)
        w["name"] = QLineEdit(s.name)
        w["value"] = QLabel("—")
        w["fmt"] = QComboBox()
        w["fmt"].addItems(FORMATS)
        w["fmt"].setCurrentText(s.fmt if s.fmt in FORMATS else FORMATS[0])
        w["source"] = QComboBox()
        w["source"].addItems(SOURCES)
        w["source"].setCurrentText(s.source)
        w["dtype"] = QComboBox()
        w["dtype"].addItems(list(TYPES))
        w["dtype"].setCurrentText(s.dtype)
        w["db"] = QSpinBox()
        w["db"].setRange(0, 65535)
        w["db"].setValue(s.db)
        w["byte"] = QSpinBox()
        w["byte"].setRange(0, 65535)
        w["byte"].setValue(s.byte)
        w["bit"] = QSpinBox()
        w["bit"].setRange(0, 7)
        w["bit"].setValue(s.bit)
        w["offset"] = QDoubleSpinBox()
        w["offset"].setRange(-1e9, 1e9)
        w["offset"].setDecimals(3)
        w["offset"].setValue(s.offset_y)
        w["gain"] = QDoubleSpinBox()
        w["gain"].setRange(-1e9, 1e9)
        w["gain"].setDecimals(4)
        w["gain"].setValue(s.gain)
        w["color"] = QPushButton()
        self._set_color(w["color"], s.color)
        w["color"].clicked.connect(lambda _=False, b=w["color"]: self._pick_color(b))
        w["comment"] = QLineEdit(s.comment)
        row_locked = self.locked and r < self._base       # rows added while running stay editable
        for key, widget in w.items():
            self.table.setCellWidget(r, CI[key], widget)
            self._install(widget)
            if row_locked and key in STRUCTURAL:
                widget.setEnabled(False)
        w["_locked"] = row_locked
        w["name"].textChanged.connect(self._update_marks)
        for k in ("source", "dtype"):
            w[k].currentTextChanged.connect(self._update_marks)
        for k in ("db", "byte", "bit"):
            w[k].valueChanged.connect(self._update_marks)
        w["source"].currentTextChanged.connect(lambda _=None, rr=w: self._enable_fields(rr))
        w["dtype"].currentTextChanged.connect(lambda _=None, rr=w: self._enable_fields(rr))
        self._enable_fields(w)
        return r

    def _enable_fields(self, w: dict) -> None:
        lk = w.get("_locked", False)
        w["db"].setEnabled(w["source"].currentText() == "DB" and not lk)
        w["bit"].setEnabled(w["dtype"].currentText() == "BOOL" and not lk)
        self._update_marks()

    def _install(self, widget: QWidget) -> None:
        widget.installEventFilter(self._filter)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self._filter)
        widget.setMouseTracking(True)

    def _row_of(self, w) -> int:
        vp = self.table.viewport()
        while w is not None and w.parentWidget() is not vp:
            w = w.parentWidget()
        return self.table.indexAt(w.pos()).row() if w is not None else -1

    @staticmethod
    def _set_color(btn: QPushButton, color: str) -> None:
        btn.setProperty("color", color)
        btn.setStyleSheet(f"background:{color}; border:1px solid #222;")

    def _pick_color(self, btn: QPushButton) -> None:
        c = QColorDialog.getColor(QColor(btn.property("color")), self, "Kolor sygnału")
        if c.isValid():
            self._set_color(btn, c.name())

    def _row_signal(self, r: int) -> Signal:
        c = lambda k: self._cell(r, k)
        return Signal(
            name=c("name").text().strip() or f"SIG{r + 1}", source=c("source").currentText(),
            dtype=c("dtype").currentText(), db=c("db").value(), byte=c("byte").value(), bit=c("bit").value(),
            offset_y=c("offset").value(), gain=c("gain").value(), color=c("color").property("color"),
            comment=c("comment").text(), enabled=c("fetch")._cb.isChecked(), plot=c("plot")._cb.isChecked(),
            fmt=c("fmt").currentText())

    def signals(self) -> list[Signal]:
        return [self._row_signal(r) for r in range(self.table.rowCount())]

    # ------------------------------------------------- duplicates marks
    def _update_marks(self, *_) -> None:
        if not hasattr(self, "table"):
            return
        sigs = [self._row_signal(r) for r in range(self.table.rowCount())]
        names, addrs = {}, {}
        for s in sigs:
            names[s.name] = names.get(s.name, 0) + 1
            addrs[address_key(s)] = addrs.get(address_key(s), 0) + 1
        for r, s in enumerate(sigs):
            self._cell(r, "name").setStyleSheet(
                f"QLineEdit {{ {RED} }}" if names[s.name] > 1 else "")
            dup = addrs[address_key(s)] > 1
            used = {"source", "dtype", "byte"} | ({"db"} if s.source == "DB" else set()) | \
                   ({"bit"} if s.dtype == "BOOL" else set())
            for key in ADDRESS_CELLS:
                widget = self._cell(r, key)
                cls = "QComboBox" if key in ("source", "dtype") else "QSpinBox"
                widget.setStyleSheet(f"{cls} {{ {YELLOW} }}" if dup and key in used else "")

    # ---------------------------------------------------------- values
    def _refresh_values(self) -> None:
        vals = self._values()
        for r in range(self.table.rowCount()):
            lab = self._cell(r, "value")
            v = vals[r] if vals is not None and r < len(vals) else None
            lab.setText(format_value(self._row_signal(r), v) if v is not None else "—")

    def row_tooltip(self, r: int) -> str:
        s = self._row_signal(r)
        vals = self._values()
        v = vals[r] if vals is not None and r < len(vals) else None
        if v is None:
            cur = "— (zmienna nie jest teraz pobierana)"
        else:
            cur = f"{format_value(s, v)}   (surowa: {v:g})"
        return (f"Nazwa: {s.name}\nAdres: {s.address}\n"
                f"Źródło: {s.source}   Typ: {s.dtype}   DB: {s.db if s.source == 'DB' else '—'}   "
                f"Bajt: {s.byte}   Bit: {s.bit if s.dtype == 'BOOL' else '—'}\n"
                f"Pobieranie: {'tak' if s.enabled else 'nie'}   Na wykresie: {'tak' if s.plot else 'nie'}\n"
                f"Offset Y: {s.offset_y:g}   Gain: {s.gain:g}   Kolor: {s.color}\n"
                f"Sposób wyświetlania: {s.fmt}\nOpis: {s.comment or '—'}\n"
                f"Aktualna wartość: {cur}")

    # ------------------------------------------------------- add/remove
    def _add(self) -> None:
        sigs = self.signals()
        ref = None
        if sigs:
            ref = sigs[self._last_row] if 0 <= self._last_row < len(sigs) else sigs[-1]
        s = Signal()
        if ref is not None:
            s.source, s.dtype, s.db, s.fmt, s.gain = ref.source, ref.dtype, ref.db, ref.fmt, ref.gain
            s.byte, s.bit = ref.byte, ref.bit
            if ref.dtype == "BOOL":
                s.bit = (ref.bit + 1) % 8
                s.byte = ref.byte + (1 if ref.bit == 7 else 0)
            else:
                s.byte = ref.byte + ref.size
        s.name = new_signal_name(ref.name if ref else None, [x.name for x in sigs],
                                 self.opts["autonumber"], self.opts["name_mode"], self.opts["own_name"])
        s.offset_y = round(sigs[-1].offset_y + self.opts["offset_step"], 3) if sigs else 0.0
        s.color = DEFAULT_COLORS[len(sigs) % len(DEFAULT_COLORS)]
        r = self._append(s)               # always at the end of the list
        self.table.scrollToBottom()
        self._last_row = r
        self._cell(r, "name").setFocus()
        self._cell(r, "name").selectAll()

    def move_row(self, src: int, dst: int) -> None:
        """Move row `src` so that it ends up at index `dst` (drag & drop on the row-number handle)."""
        n = self.table.rowCount()
        if self.locked or not (0 <= src < n and 0 <= dst < n) or src == dst:
            return
        sigs = self.signals()
        sigs.insert(dst, sigs.pop(src))
        self.table.setRowCount(0)
        for s in sigs:
            self._append(s)
        self.table.selectRow(dst)
        self._last_row = dst
        self._update_marks()
        self._refresh_values()

    def _remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and 0 <= self._last_row < self.table.rowCount():
            rows = [self._last_row]
        if not rows and self.table.rowCount():
            rows = [self.table.rowCount() - 1]
        for r in rows:
            if not self.locked or r >= self._base:          # while running only the rows added now
                self.table.removeRow(r)
        self._last_row = -1
        self._update_marks()

    def _from_symbols(self) -> None:
        dlg = SymbolPicker(self._symbols(), self)
        if dlg.exec():
            for sym in dlg.selected():
                cur = self.signals()
                s = sym.to_signal()
                s.color = DEFAULT_COLORS[len(cur) % len(DEFAULT_COLORS)]
                s.offset_y = round(cur[-1].offset_y + self.opts["offset_step"], 3) if cur else 0.0
                self._append(s)

    # ------------------------------------------------------ list in/out
    def _save_list(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz listę zmiennych", "zmienne.json", "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"signals": [s.to_dict() for s in self.signals()], "options": self.opts},
                          f, ensure_ascii=False, indent=2)

    def _load_list(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Wczytaj listę zmiennych", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            sigs = [Signal.from_dict(d) for d in data["signals"]]
        except Exception as e:
            QMessageBox.warning(self, "S7Trace", f"Nie można wczytać listy: {e}")
            return
        self._insert_list(sigs, data.get("options"))

    def _copy_from_tab(self) -> None:
        tabs = [t for t in self._other_tabs() if t[1]]
        if not tabs:
            QMessageBox.information(self, "S7Trace", "Brak innych kart z zapisanymi zmiennymi.")
            return
        menu = QMenu(self)
        for name, sigs in tabs:
            menu.addAction(f"{name} ({len(sigs)})", lambda s=sigs: self._insert_list(
                [Signal.from_dict(x.to_dict()) for x in s]))
        menu.exec(self.btn_copy.mapToGlobal(self.btn_copy.rect().bottomLeft()))

    def _insert_list(self, sigs: list[Signal], options: dict | None = None) -> None:
        if self.table.rowCount():
            box = QMessageBox(self)
            box.setWindowTitle("Lista zmiennych")
            box.setText("Aktualna lista nie jest pusta.")
            rep = box.addButton("Zastąp", QMessageBox.AcceptRole)
            app = box.addButton("Dołącz na końcu", QMessageBox.AcceptRole)
            box.addButton("Anuluj", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is rep:
                self.table.setRowCount(0)
            elif box.clickedButton() is not app:
                return
        for s in sigs:
            self._append(s)
        if options and not self.table.rowCount() == 0:
            for k in ("autonumber", "name_mode", "own_name", "offset_step"):
                if k in options:
                    self.opts[k] = options[k]
        self._last_row = -1
        self._update_marks()

    # ------------------------------------------------- header context menu
    def _header_menu(self, pos) -> None:
        col = self.table.horizontalHeader().logicalIndexAt(pos)
        if col < 0:
            return
        key = COLS[col][0]
        menu = QMenu(self)
        if key == "offset":
            menu.addAction("Skoryguj wszystkie Offset Y", self.fix_offsets)
            menu.addAction("Zmień Offset Y…", self._change_offset_step)
            menu.addSeparator()
        elif key == "name":
            a = menu.addAction("Auto-numerowanie włączone")
            a.setCheckable(True)
            a.setChecked(self.opts["autonumber"])
            a.toggled.connect(lambda c: self.opts.__setitem__("autonumber", c))
            menu.addSeparator()
            grp = QActionGroup(menu)
            for mode, label in ((NAME_PREV, "Nazwa z poprzedniej zmiennej"),
                                (NAME_OWN, f"Nazwa własna ({self.opts['own_name']}1, {self.opts['own_name']}2, …)")):
                act = menu.addAction(label)
                act.setCheckable(True)
                act.setActionGroup(grp)
                act.setChecked(self.opts["name_mode"] == mode)
                act.triggered.connect(lambda _=False, m=mode: self.opts.__setitem__("name_mode", m))
            menu.addAction("Ustaw nazwę własną…", self._set_own_name)
            menu.addSeparator()
        visible = [i for i in range(len(COLS)) if not self.table.isColumnHidden(i)]
        hide = menu.addAction("Ukryj kolumnę")
        hide.setEnabled(len(visible) > 1 and not self.table.isColumnHidden(col))
        hide.triggered.connect(lambda: self.table.setColumnHidden(col, True))
        show = menu.addMenu("Pokaż kolumnę")
        hidden = [i for i in range(len(COLS)) if self.table.isColumnHidden(i)]
        show.setEnabled(bool(hidden))
        for i in hidden:
            show.addAction(COLS[i][1], lambda i=i: self.table.setColumnHidden(i, False))
        if len(hidden) > 1:
            show.addSeparator()
            show.addAction("Wszystkie", lambda: [self.table.setColumnHidden(i, False) for i in hidden])
        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def fix_offsets(self) -> None:
        """Re-lay all Offset Y from 0.000 (first row) by the current step."""
        step = self.opts["offset_step"]
        for r in range(self.table.rowCount()):
            self._cell(r, "offset").setValue(round(r * step, 3))

    def _change_offset_step(self) -> None:
        v, ok = QInputDialog.getDouble(self, "Offset Y", "Krok Offset Y dla nowych zmiennych:",
                                       self.opts["offset_step"], -1e6, 1e6, 3)
        if ok:
            self.opts["offset_step"] = v

    def _set_own_name(self) -> None:
        t, ok = QInputDialog.getText(self, "Nazwa własna", "Początek nazwy (po nim idzie numer):",
                                     text=self.opts["own_name"])
        if ok and t.strip():
            self.opts["own_name"] = t.strip()
