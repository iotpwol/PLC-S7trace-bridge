"""IP address field: four independent number cells inside one edit box with fixed dots.

    "10  . 12  . 91  . 1  "      "    . 12  .     . 1  "      "    .     .     .    "

The dots never move and cannot be deleted; Backspace / Delete only remove digits. text() / setText() work with the
plain address ("10.12.91.1", optionally ":port"), the display is the padded form. IpCombo adds a drop-down with the
history of the addresses that were really connected (newest first)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal as QtSignal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox, QLineEdit

CELL = 3                       # digits per octet
SEP = " . "
STRIDE = CELL + len(SEP)       # display width of one octet with its dot
PORT_AT = 3 * STRIDE + CELL    # display position where " : port" starts (after the 4th octet)
PORT_SEP = " : "
PORT_DIGITS = 5


class IpEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._c = ["", "", "", ""]
        self._port: str | None = None
        self._cur = (0, 0)                                 # (cell 0..3 or 4 = port, offset in the cell)
        super().setText(self._display())
        self.setCursorPosition(0)

    # ------------------------------------------------------------ plain <-> display
    def text(self) -> str:
        if not any(self._c) and self._port is None:
            return ""
        host = ".".join(self._c)
        while host.endswith("."):                            # an unfinished tail is simply cut: "10.12.."
            host = host[:-1]
        return host + (f":{self._port}" if self._port is not None else "")

    def setText(self, text: str) -> None:
        raw = text.replace(" ", "")
        raw, colon, port = raw.partition(":")
        cells = [p[:CELL] for p in raw.split(".")][:4]
        self._c = cells + [""] * (4 - len(cells))
        self._port = port[:PORT_DIGITS] if colon else None
        self._cur = (0, 0)
        self._render()

    def clear(self) -> None:
        self.setText("")

    def _display(self) -> str:
        s = SEP.join(c.ljust(CELL) for c in self._c)
        if self._port is not None:
            s += PORT_SEP + self._port
        return s

    def _render(self, cur: tuple[int, int] | None = None) -> None:
        if cur is not None:
            self._cur = cur
        shown = self._display()
        if shown != super().text():
            super().setText(shown)                           # emits textChanged (state is already up to date)
        self.setCursorPosition(self._pos(*self._cur))

    # ------------------------------------------------------------ cursor <-> cell
    def _pos(self, cell: int, off: int) -> int:
        if cell >= 4:
            return PORT_AT + len(PORT_SEP) + off
        return cell * STRIDE + off

    def _cell_at(self, pos: int) -> tuple[int, int]:
        if self._port is not None and pos > PORT_AT:
            return 4, min(max(pos - PORT_AT - len(PORT_SEP), 0), len(self._port))
        i = min(pos // STRIDE, 3)
        r = pos - i * STRIDE
        if r > CELL:                                          # on a dot: the start of the next cell
            if i < 3:
                return i + 1, 0
            return 3, len(self._c[3])
        return i, min(r, len(self._c[i]))

    def _cursor(self) -> tuple[int, int]:
        return self._cell_at(self.cursorPosition())

    # ------------------------------------------------------------ editing
    def _delete_range(self, a: int, b: int) -> tuple[int, int]:
        """Removes the digits inside display range [a, b); the dots stay. Returns the cursor for the start."""
        for i in range(4):
            lo = i * STRIDE
            n = len(self._c[i])
            s, e = max(a, lo) - lo, min(b, lo + n) - lo
            if e > s:
                self._c[i] = self._c[i][:s] + self._c[i][e:]
        if self._port is not None and b > PORT_AT:
            p0 = PORT_AT + len(PORT_SEP)
            if a <= PORT_AT:
                self._port = None
            else:
                s, e = max(a, p0) - p0, min(b, p0 + len(self._port)) - p0
                if e > s:
                    self._port = self._port[:s] + self._port[e:]
        return self._cell_at(a)

    def _selection(self) -> tuple[int, int] | None:
        return (self.selectionStart(), self.selectionEnd()) if self.hasSelectedText() else None

    def _insert_digit(self, ch: str) -> None:
        sel = self._selection()
        cell, off = self._delete_range(*sel) if sel else self._cursor()
        if cell == 4:
            cur = self._port or ""
            new = cur[:off] + ch + cur[off:]
            if len(new) > PORT_DIGITS or (len(new) > 1 and new[0] == "0") or int(new) > 65535:
                self._render((cell, off))
                return
            self._port = new
            self._render((4, off + 1))
            return
        cur = self._c[cell]
        new = cur[:off] + ch + cur[off:]
        if len(new) > CELL or (len(new) > 1 and new[0] == "0") or int(new) > 255:
            self._render((cell, off))
            return
        self._c[cell] = new
        off += 1
        if len(new) == CELL and cell < 3 and off == CELL:     # a full octet: go on to the next one
            cell, off = cell + 1, 0
        self._render((cell, off))

    def _next_cell(self) -> None:
        cell, _ = self._cursor()
        if cell < 3:
            self._render((cell + 1, 0))

    def _start_port(self) -> None:
        if self._port is None and all(self._c):               # ':port' only after a complete address
            self._port = ""
        if self._port is not None:
            self._render((4, len(self._port)))

    def _move(self, target: int, mark: bool) -> None:
        if mark:
            self.cursorForward(True, target - self.cursorPosition())
        else:
            self.setCursorPosition(target)

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        txt = e.text()
        if ctrl and key == Qt.Key_A:
            self.selectAll()
        elif ctrl and key in (Qt.Key_C, Qt.Key_Insert):
            if self.hasSelectedText():
                QGuiApplication.clipboard().setText(self.text())
        elif ctrl and key == Qt.Key_X:
            if self.hasSelectedText():
                QGuiApplication.clipboard().setText(self.text())
                self._delete_selection_or(None)
        elif (ctrl and key == Qt.Key_V) or (shift and key == Qt.Key_Insert):
            self._paste(QGuiApplication.clipboard().text())
        elif key in (Qt.Key_Left, Qt.Key_Right):
            cell, off = self._cursor()
            if self.hasSelectedText() and not shift:
                self.setCursorPosition(self.selectionStart() if key == Qt.Key_Left else self.selectionEnd())
                return
            if key == Qt.Key_Left:
                if off > 0:
                    off -= 1
                elif cell == 4:
                    cell, off = 3, len(self._c[3])
                elif cell > 0:
                    cell -= 1
                    off = len(self._c[cell])
            else:
                limit = len(self._port) if cell == 4 else len(self._c[cell])
                if off < limit:
                    off += 1
                elif cell < 3:
                    cell, off = cell + 1, 0
                elif cell == 3 and self._port is not None:
                    cell, off = 4, 0
            self._move(self._pos(cell, off), shift)
        elif key in (Qt.Key_Home, Qt.Key_End):
            if key == Qt.Key_Home:
                self._move(0, shift)
            else:
                self._move(len(self._display()), shift)
        elif key == Qt.Key_Backspace:
            sel = self._selection()
            if sel:
                self._render(self._delete_range(*sel))
                return
            cell, off = self._cursor()
            if cell == 4:
                if off > 0:
                    self._port = self._port[:off - 1] + self._port[off:]
                    self._render((4, off - 1))
                elif not self._port:
                    self._port = None
                    self._render((3, len(self._c[3])))
                else:
                    self._render((3, len(self._c[3])))
            elif off > 0:
                self._c[cell] = self._c[cell][:off - 1] + self._c[cell][off:]
                self._render((cell, off - 1))
            elif cell > 0:                                      # the dot stays; the cursor steps over it
                self._render((cell - 1, len(self._c[cell - 1])))
        elif key == Qt.Key_Delete:
            sel = self._selection()
            if sel:
                self._render(self._delete_range(*sel))
                return
            cell, off = self._cursor()
            if cell == 4:
                if off < len(self._port or ""):
                    self._port = self._port[:off] + self._port[off + 1:]
                    self._render((4, off))
            elif off < len(self._c[cell]):
                self._c[cell] = self._c[cell][:off] + self._c[cell][off + 1:]
                self._render((cell, off))
        elif txt and txt in "0123456789" and not ctrl:
            self._insert_digit(txt)
        elif txt in (".", ",", " ") and not ctrl:
            sel = self._selection()
            if sel and txt == " ":                              # Space over a selection clears it (the dots stay)
                self._render(self._delete_range(*sel))
            elif not sel:
                self._next_cell()
        elif txt == ":" and not ctrl:
            self._start_port()
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
            super().keyPressEvent(e)                            # editingFinished / focus handling
        else:
            e.ignore() if txt else super().keyPressEvent(e)

    def _delete_selection_or(self, _):
        sel = self._selection()
        if sel:
            self._render(self._delete_range(*sel))

    def _paste(self, text: str) -> None:
        plain = text.strip().replace(" ", "")
        if plain and all(c in "0123456789.:" for c in plain):
            sel = self._selection()
            if sel and sel != (0, len(super().text())):         # a partial selection: paste only digits-in-place
                self._render(self._delete_range(*sel))
            self.setText(plain)


class IpCombo(QComboBox):
    """Editable drop-down around IpEdit. Plain QLineEdit-like API (text, setText, textChanged, editingFinished ...)."""

    textChanged = QtSignal(str)
    editingFinished = QtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._edit = IpEdit(self)
        self.setEditable(True)
        self.setLineEdit(self._edit)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(4)
        self.setMinimumWidth(70)                              # never squeezes the form label away in a narrow panel
        self._edit.setMinimumWidth(20)
        self._edit.textChanged.connect(lambda *_: self.textChanged.emit(self.text()))
        self._edit.editingFinished.connect(self.editingFinished)
        self.activated.connect(self._picked)
        self.view().setMinimumWidth(self.fontMetrics().horizontalAdvance("255 . 255 . 255 . 255") + 50)

    def text(self) -> str:
        return self._edit.text()

    def setText(self, text: str) -> None:
        self._edit.setText(text)

    def clear(self) -> None:
        self._edit.clear()

    def setPlaceholderText(self, text: str) -> None:        # the fixed dots are always shown, so there is no hint text
        self._edit.setPlaceholderText(text)

    def displayText(self) -> str:
        return self._edit.displayText()

    def set_history(self, items: list[str]) -> None:
        """Newest first; the list shows the spaced form, the plain address is kept as item data."""
        self.blockSignals(True)
        try:
            self.clear_items()
            for s in items:
                self.addItem(s.replace(".", " . "), s)
            self.setCurrentIndex(-1)
        finally:
            self.blockSignals(False)

    def clear_items(self) -> None:
        keep = self._edit.text()
        QComboBox.clear(self)
        self._edit.setText(keep)

    def showPopup(self) -> None:
        from ..core import ip_history
        self.set_history(ip_history.load())
        super().showPopup()

    def _picked(self, index: int) -> None:
        addr = self.itemData(index)
        if addr:
            self._edit.setText(addr)
            self.editingFinished.emit()

    def wheelEvent(self, e):
        e.ignore()
