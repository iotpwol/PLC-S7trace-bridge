"""Offset of the time axis as two fields side by side: whole days (the date part) and a time HH:MM:SS.mmm, plus a sign button.
value() / setValue() work in seconds (signed), like a spin box, so the rest of the program does not care how it is shown."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QTime, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSpinBox, QTimeEdit, QWidget

from ..core.types import TIME_OFFSET_MAX, offset_join, offset_split


class OffsetEdit(QWidget):
    valueChanged = Signal(float)
    contextRequested = Signal(QPoint)               # right click on any part: the tab offers 'align to the computer' / 'zero'

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.btn_sign = QPushButton("+")
        self.btn_sign.setCheckable(True)
        self.btn_sign.setFixedWidth(34)
        self.btn_sign.setStyleSheet("QPushButton { padding: 0px; font-weight: bold; }")
        self.btn_sign.setToolTip("Znak offsetu: + = późniejszy czas na osi, - = wcześniejszy")
        self.sp_days = QSpinBox()
        self.sp_days.setRange(0, int(TIME_OFFSET_MAX // 86400))
        self.sp_days.setSuffix(" d")
        self.sp_days.setMinimumWidth(66)
        self.sp_days.setToolTip("Data: pełne doby korekty (0 – 3650)")
        self.ed_time = QTimeEdit()
        self.ed_time.setDisplayFormat("HH:mm:ss.zzz")
        self.ed_time.setMinimumWidth(104)
        self.ed_time.setToolTip("Godzina: HH:MM:SS.mmm (godziny, minuty, sekundy, milisekundy) korekty")
        for w in (self.sp_days, self.ed_time):
            w.setKeyboardTracking(False)
            w.setFocusPolicy(Qt.StrongFocus)
            w.wheelEvent = lambda e: e.ignore()
        lay.addWidget(self.btn_sign)
        lay.addWidget(self.sp_days, 1)
        lay.addWidget(self.ed_time, 2)
        self.btn_sign.toggled.connect(self._sign)
        self.sp_days.valueChanged.connect(self._changed)
        self.ed_time.timeChanged.connect(self._changed)
        for w in (self, self.btn_sign, self.sp_days, self.ed_time, self.sp_days.lineEdit(), self.ed_time.lineEdit()):
            w.setContextMenuPolicy(Qt.CustomContextMenu)
            w.customContextMenuRequested.connect(lambda p, src=w: self.contextRequested.emit(src.mapToGlobal(p)))

    def _sign(self, neg: bool) -> None:
        self.btn_sign.setText("-" if neg else "+")
        self._changed()

    def _changed(self, *_) -> None:
        self.valueChanged.emit(self.value())

    def value(self) -> float:
        ms = self.ed_time.time().msecsSinceStartOfDay()
        return offset_join(self.btn_sign.isChecked(), self.sp_days.value(), ms)

    def setValue(self, seconds: float) -> None:
        neg, days, ms = offset_split(seconds)
        for w in (self.btn_sign, self.sp_days, self.ed_time):
            w.blockSignals(True)
        self.btn_sign.setChecked(neg)
        self.btn_sign.setText("-" if neg else "+")
        self.sp_days.setValue(days)
        self.ed_time.setTime(QTime.fromMSecsSinceStartOfDay(ms))
        for w in (self.btn_sign, self.sp_days, self.ed_time):
            w.blockSignals(False)
        self._changed()
