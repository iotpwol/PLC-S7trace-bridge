"""Ustawienia -> Renderowanie wykresu: how often and how finely the chart is drawn (CPU load), with live preview."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout)

from ..core import render_cfg as rc
from .dialog_kit import dialog_info


@dialog_info("Renderowanie wykresu",
             "Jak często i jak dokładnie rysowany jest wykres. To one decydują o obciążeniu procesora – na mocniejszym komputerze "
             "można je podkręcić. Zmiany działają od razu; „Anuluj” przywraca poprzednie wartości.")
class RenderDialog(QDialog):
    def __init__(self, cfg: dict, apply: Callable[[dict], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Renderowanie wykresu")
        self.resize(620, 640)
        self._apply = apply
        self._original = rc.normalize(cfg)
        self.cfg = dict(self._original)
        self.widgets: dict[str, QSpinBox | QDoubleSpinBox | QCheckBox] = {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        for key in rc.ORDER:
            label, lo, hi, unit, default, desc = rc.PARAMS[key]
            if isinstance(default, bool):
                w = QCheckBox(label)
                w.setChecked(self.cfg[key])
                w.toggled.connect(lambda v, k=key: self._set(k, v))
                form.addRow(w)
            else:
                w = QDoubleSpinBox() if isinstance(default, float) else QSpinBox()
                if isinstance(default, float):
                    w.setDecimals(1)
                    w.setSingleStep(0.1)
                w.setRange(lo, hi)
                w.setSuffix(f" {unit}")
                w.setValue(self.cfg[key])
                w.valueChanged.connect(lambda v, k=key: self._set(k, v))
                form.addRow(label + ":", w)
            w.setToolTip(desc)
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
        self._apply(rc.normalize(self.cfg))

    def reset(self) -> None:
        self.cfg = dict(rc.DEFAULTS)
        for key, w in self.widgets.items():
            w.blockSignals(True)
            (w.setChecked if isinstance(w, QCheckBox) else w.setValue)(self.cfg[key])
            w.blockSignals(False)
        self._apply(rc.normalize(self.cfg))

    def result_cfg(self) -> dict:
        return rc.normalize(self.cfg)

    def reject(self) -> None:
        self._apply(self._original)
        super().reject()
