"""Znaczniki -> Wygląd znaczników: line widths of the markers (all plots / chosen plots / the others / highlighted), live preview."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from ..core import marker_look as ml
from .dialog_kit import dialog_info


@dialog_info("Wygląd znaczników",
             "Grubość linii znaczników na wykresie. Dotyczy znaczników, które nie mają własnej grubości (w oknie znacznika: 0 = wg ustawień). "
             "Zmiany działają od razu; „Anuluj” przywraca poprzednie wartości.")
class MarkerLookDialog(QDialog):
    def __init__(self, cfg: dict, apply: Callable[[dict], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wygląd znaczników")
        self.resize(560, 420)
        self._apply = apply
        self._original = ml.normalize(cfg)
        self.cfg = dict(self._original)
        self.widgets: dict[str, QSpinBox] = {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        for key in ml.ORDER:
            label, lo, hi, unit, _default, desc = ml.PARAMS[key]
            w = QSpinBox()
            w.setRange(lo, hi)
            w.setSuffix(f" {unit}")
            w.setValue(self.cfg[key])
            w.valueChanged.connect(lambda v, k=key: self._set(k, v))
            w.setToolTip(desc)
            form.addRow(label + ":", w)
            self.widgets[key] = w
            note = QLabel(desc)
            note.setWordWrap(True)
            note.setStyleSheet("font-size: 8pt; color: gray; padding-bottom: 6px;")
            form.addRow("", note)
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

    def _set(self, key: str, value) -> None:
        self.cfg[key] = value
        self._apply(ml.normalize(self.cfg))

    def reset(self) -> None:
        self.cfg = dict(ml.DEFAULTS)
        for key, w in self.widgets.items():
            w.blockSignals(True)
            w.setValue(self.cfg[key])
            w.blockSignals(False)
        self._apply(ml.normalize(self.cfg))

    def result_cfg(self) -> dict:
        return ml.normalize(self.cfg)

    def reject(self) -> None:
        self._apply(self._original)
        super().reject()
