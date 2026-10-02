"""'Okno czasu [s]': a number typed in seconds, or picked from a drop-down list of ready values (5 s ... 24 h)."""
from __future__ import annotations

from PySide6.QtCore import QLocale, Qt, Signal as QtSignal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QComboBox

MIN_S, MAX_S = 0.1, 86400.0

# seconds -> text in the list (the field itself always shows seconds)
PRESETS: list[tuple[float, str]] = [
    (5, "5 sekund"), (10, "10 sekund"), (15, "15 sekund"), (30, "30 sekund"), (60, "60 sekund"), (90, "90 sekund"),
    (120, "2 minuty"), (180, "3 minuty"), (300, "5 minut"), (600, "10 minut"), (900, "15 minut"),
    (1800, "30 minut"), (3600, "60 minut"), (5400, "90 minut"),
    (7200, "2 godziny"), (10800, "3 godziny"), (14400, "4 godziny"), (21600, "6 godzin"), (28800, "8 godzin"),
    (43200, "12 godzin"), (57600, "16 godzin"), (86400, "24 godziny"),
]


class DurationCombo(QComboBox):
    """Editable combo box with the API of the spin box it replaces: value(), setValue(), valueChanged(float).
    Typing is committed with Enter / when the field loses focus; a pick from the list is committed at once."""

    valueChanged = QtSignal(float)

    def __init__(self, value: float = 200.0, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setFocusPolicy(Qt.StrongFocus)
        for sec, label in PRESETS:
            self.addItem(f"{label}  ({int(sec)} s)" if sec >= 120 else label, sec)
        self.setCurrentIndex(-1)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)   # the long list texts must not widen
        self.setMinimumContentsLength(6)                                            # the field (it would squeeze the labels)
        self.view().setMinimumWidth(self.fontMetrics().horizontalAdvance("3 godziny  (10800 s)") + 40)
        v = QDoubleValidator(MIN_S, MAX_S, 3, self)
        v.setNotation(QDoubleValidator.StandardNotation)
        self.lineEdit().setValidator(v)
        self.lineEdit().setToolTip("Wpisz liczbę sekund (0,1 … 86400) albo wybierz z listy.")
        self._value = float(value)
        self._show(self._value)
        self.lineEdit().editingFinished.connect(self._commit_text)
        self.activated.connect(self._picked)

    # ---- spin-box compatible API
    def value(self) -> float:
        return self._value

    def minimum(self) -> float:
        return MIN_S

    def maximum(self) -> float:
        return MAX_S

    def setValue(self, v: float) -> None:
        v = min(max(float(v), MIN_S), MAX_S)
        changed = abs(v - self._value) > 1e-9
        self._value = v
        self._show(v)
        if changed:
            self.valueChanged.emit(v)

    # ---- internals
    def _show(self, v: float) -> None:
        self.lineEdit().setText(_fmt(v))

    def _commit_text(self) -> None:
        txt = self.lineEdit().text().strip()
        loc = QLocale()
        loc.setNumberOptions(QLocale.OmitGroupSeparator)
        v, ok = loc.toDouble(txt)
        if not ok:
            try:
                v, ok = float(txt.replace(",", ".")), True
            except ValueError:
                ok = False
        if ok:
            self.setValue(v)
        else:
            self._show(self._value)                          # unreadable text: back to the last good value

    def _picked(self, index: int) -> None:
        sec = self.itemData(index)
        if sec is not None:
            self.setValue(float(sec))
            self._show(self._value)                          # the field shows seconds, not the list label

    def wheelEvent(self, e):                                 # like the other numeric fields: no accidental change
        e.ignore()


def _fmt(v: float) -> str:
    """Seconds as shown in the field: 120,0 / 0,1 / 86400,0 (the decimal separator follows the system)."""
    loc = QLocale()
    loc.setNumberOptions(QLocale.OmitGroupSeparator)                 # 86400,0 – not "86 400,0"
    return loc.toString(float(v), "f", 1 if abs(v * 10 - round(v * 10)) < 1e-9 else 3)
