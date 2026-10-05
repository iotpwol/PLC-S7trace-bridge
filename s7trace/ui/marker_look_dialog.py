"""Znaczniki -> Wygląd znaczników: line widths of the markers (all plots / chosen plots / the others / highlighted) and the look of the REC
marks (Start REC / Stop REC lines, Manual REC areas: on / off, colour, width, style, opacity), live preview."""
from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout)

from ..core import marker_look as ml
from ..core.markers import LINE_STYLES
from .dialog_kit import dialog_info


def _note(desc: str) -> QLabel:
    note = QLabel(desc)
    note.setWordWrap(True)
    note.setStyleSheet("font-size: 8pt; color: gray; padding-bottom: 6px;")
    return note


@dialog_info("Wygląd znaczników",
             "Grubość linii znaczników na wykresie. Dotyczy znaczników, które nie mają własnej grubości (w oknie znacznika: 0 = wg ustawień). "
             "Niżej: wygląd znaczników REC („Start REC”, „Stop REC”, obszar „Manual REC”). "
             "Zmiany działają od razu; „Anuluj” przywraca poprzednie wartości.")
class MarkerLookDialog(QDialog):
    def __init__(self, cfg: dict, apply: Callable[[dict], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wygląd znaczników")
        self.resize(600, 640)
        self._apply = apply
        self._original = ml.normalize(cfg)
        self.cfg = dict(self._original)
        self.widgets: dict[str, QSpinBox | QCheckBox] = {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        for key in ml.ORDER:
            label, lo, hi, unit, _default, desc = ml.PARAMS[key]
            if key in ml.FLAGS:
                w = QCheckBox("włączone")
                w.setChecked(bool(self.cfg[key]))
                w.toggled.connect(lambda v, k=key: self._set(k, int(v)))
            else:
                w = QSpinBox()
                w.setRange(lo, hi)
                w.setSuffix(f" {unit}")
                w.setValue(self.cfg[key])
                w.valueChanged.connect(lambda v, k=key: self._set(k, v))
            w.setToolTip(desc)
            form.addRow(label + ":", w)
            self.widgets[key] = w
            form.addRow("", _note(desc))
            if key == "rec_show":                                            # the colour and the style of the REC marks come right after the switch
                self._rec_extras(form)
        lay.addLayout(form)
        lay.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        self.btn_default = QPushButton("Domyślne")
        ok, cancel = QPushButton("OK"), QPushButton("Anuluj")
        ok.setDefault(True)
        self.btn_default.clicked.connect(self.reset)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        for b in (self.btn_default, ok, cancel):
            row.addWidget(b)
        lay.addLayout(row)

    def _rec_extras(self, form: QFormLayout) -> None:
        label, _d, desc = ml.STRINGS["rec_color"]
        self.btn_color = QPushButton()
        self.btn_color.setToolTip(desc)
        self.btn_color.clicked.connect(self._pick_color)
        self._paint_color()
        form.addRow(label + ":", self.btn_color)
        form.addRow("", _note(desc))
        label, _d, desc = ml.STRINGS["rec_style"]
        self.cb_style = QComboBox()
        for k in ml.STYLES:
            self.cb_style.addItem(LINE_STYLES[k], k)
        self.cb_style.setCurrentIndex(self.cb_style.findData(self.cfg["rec_style"]))
        self.cb_style.setToolTip(desc)
        self.cb_style.currentIndexChanged.connect(lambda _i: self._set("rec_style", self.cb_style.currentData()))
        form.addRow(label + ":", self.cb_style)
        form.addRow("", _note(desc))

    def _paint_color(self) -> None:
        c = self.cfg["rec_color"]
        self.btn_color.setText(c)
        text = "#000000" if QColor(c).lightness() > 128 else "#ffffff"
        self.btn_color.setStyleSheet(f"QPushButton {{ background: {c}; color: {text}; }}")          # scoped: a bare 'background' leaks into tooltips

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.cfg["rec_color"]), self, "Kolor znaczników REC")
        if c.isValid():
            self._set("rec_color", c.name())
            self._paint_color()

    def _set(self, key: str, value) -> None:
        self.cfg[key] = value
        self._apply(ml.normalize(self.cfg))

    def reset(self) -> None:
        self.cfg = dict(ml.DEFAULTS)
        for key, w in self.widgets.items():
            w.blockSignals(True)
            w.setChecked(bool(self.cfg[key])) if key in ml.FLAGS else w.setValue(self.cfg[key])
            w.blockSignals(False)
        self.cb_style.blockSignals(True)
        self.cb_style.setCurrentIndex(self.cb_style.findData(self.cfg["rec_style"]))
        self.cb_style.blockSignals(False)
        self._paint_color()
        self._apply(ml.normalize(self.cfg))

    def result_cfg(self) -> dict:
        return ml.normalize(self.cfg)

    def reject(self) -> None:
        self._apply(self._original)
        super().reject()
