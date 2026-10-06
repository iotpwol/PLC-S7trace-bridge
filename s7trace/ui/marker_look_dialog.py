"""Znaczniki -> Wygląd znaczników: line widths of the markers (all plots / chosen plots / the others / highlighted), the look of the REC
marks (Start REC / Stop REC lines, Manual REC areas: on / off, colour, width, style, opacity) and of the TRIG (n) lines, live preview."""
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
             "Niżej: wygląd znaczników REC („Start REC”, „Stop REC”, obszar „Manual REC”) i linii TRIG (n). "
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
        self.btns: dict[str, QPushButton] = {}
        self.combos: dict[str, QComboBox] = {}
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
                self._extras(form, "rec", "Kolor znaczników REC")
            elif key == "trig_show":                                         # (and of the TRIG lines)
                self._extras(form, "trig", "Kolor linii TRIG")
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

    def _extras(self, form: QFormLayout, prefix: str, title: str) -> None:
        """Colour + line style rows that belong to a switch ('rec' = REC marks, 'trig' = TRIG lines)."""
        key = prefix + "_color"
        label, _d, desc = ml.STRINGS[key]
        btn = self.btns[key] = QPushButton()
        btn.setToolTip(desc)
        btn.clicked.connect(lambda: self._pick_color(key, title))
        self._paint_color(key)
        form.addRow(label + ":", btn)
        form.addRow("", _note(desc))
        key = prefix + "_style"
        label, _d, desc = ml.STRINGS[key]
        cb = self.combos[key] = QComboBox()
        for k in ml.STYLES:
            cb.addItem(LINE_STYLES[k], k)
        cb.setCurrentIndex(cb.findData(self.cfg[key]))
        cb.setToolTip(desc)
        cb.currentIndexChanged.connect(lambda _i: self._set(key, cb.currentData()))
        form.addRow(label + ":", cb)
        form.addRow("", _note(desc))

    def _paint_color(self, key: str) -> None:
        c, btn = self.cfg[key], self.btns[key]
        btn.setText(c)
        text = "#000000" if QColor(c).lightness() > 128 else "#ffffff"
        btn.setStyleSheet(f"QPushButton {{ background: {c}; color: {text}; }}")          # scoped: a bare 'background' leaks into tooltips

    def _pick_color(self, key: str, title: str) -> None:
        c = QColorDialog.getColor(QColor(self.cfg[key]), self, title)
        if c.isValid():
            self._set(key, c.name())
            self._paint_color(key)

    def _set(self, key: str, value) -> None:
        self.cfg[key] = value
        self._apply(ml.normalize(self.cfg))

    def reset(self) -> None:
        self.cfg = dict(ml.DEFAULTS)
        for key, w in self.widgets.items():
            w.blockSignals(True)
            w.setChecked(bool(self.cfg[key])) if key in ml.FLAGS else w.setValue(self.cfg[key])
            w.blockSignals(False)
        for key, cb in self.combos.items():
            cb.blockSignals(True)
            cb.setCurrentIndex(cb.findData(self.cfg[key]))
            cb.blockSignals(False)
        for key in self.btns:
            self._paint_color(key)
        self._apply(ml.normalize(self.cfg))

    def result_cfg(self) -> dict:
        return ml.normalize(self.cfg)

    def reject(self) -> None:
        self._apply(self._original)
        super().reject()
