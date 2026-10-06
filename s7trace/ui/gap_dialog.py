"""Widok -> Przerwy Stop -> Start -> Wygląd i szerokość przerw...: how the pauses between Stop and Start of the reading are shown (this tab: one of
the three ways + the width of a band in pixels) and the look of a band (interface configuration: fill colour + opacity, the written length of the
pause: on / off, direction, colour, position). Live preview; 'Anuluj' restores the previous values."""
from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout)

from ..core import marker_look as ml
from ..core.config import GAP_MODES, GAP_PX_MAX, GAP_PX_MIN
from .dialog_kit import dialog_info

MODE_LABELS = {"full": "Pusta przerwa w pełnej długości", "join": "Wytnij przerwę z wykresu (jeden znacznik)",
               "fixed": "Przerwa o stałej szerokości (w pikselach)"}
MODE_TIPS = {"full": "Pauza między Stop a Start odczytu to pusty odcinek wykresu tak długi, jak trwała.",
             "join": "Pauza nie zajmuje miejsca: linie się stykają, w tym miejscu stoi jeden znacznik, a opisy osi czasu przeskakują (30 | 50).",
             "fixed": "Pauza to pas o stałej szerokości w pikselach, niezależnie od czasu jej trwania i od przybliżenia."}


def _note(text: str) -> QLabel:
    note = QLabel(text)
    note.setWordWrap(True)
    note.setStyleSheet("font-size: 8pt; color: gray; padding-bottom: 6px;")
    return note


@dialog_info("Wygląd i szerokość przerw",
             "Jak wykres pokazuje pauzę między Stop a Start odczytu. Sposób pokazania i szerokość pasa dotyczą tej karty; wygląd pasa "
             "(kolory, opis) należy do konfiguracji interfejsu. Wygląd działa w trybie „Przerwa o stałej szerokości”. "
             "Zmiany działają od razu; „Anuluj” przywraca poprzednie wartości.")
class GapDialog(QDialog):
    def __init__(self, mode: str, px: int, look: dict, apply_mode: Callable[[str, int], None], apply_look: Callable[[dict], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wygląd i szerokość przerw")
        self.resize(560, 560)
        self._apply_mode, self._apply_look = apply_mode, apply_look
        self._orig = (mode, px, ml.normalize(look))
        self.mode, self.px = mode, px
        self.look = dict(self._orig[2])
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.cb_mode = QComboBox()
        for k in GAP_MODES:
            self.cb_mode.addItem(MODE_LABELS[k], k)
            self.cb_mode.setItemData(self.cb_mode.count() - 1, MODE_TIPS[k], 3)             # Qt.ToolTipRole
        self.cb_mode.setCurrentIndex(self.cb_mode.findData(mode))
        self.cb_mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Sposób pokazania przerwy:", self.cb_mode)
        form.addRow("", _note("Pusta przerwa (domyślnie), wycięcie (zerowa szerokość, jeden znacznik, opisy osi przeskakują) albo pas o stałej szerokości."))
        self.sp_px = QSpinBox()
        self.sp_px.setRange(GAP_PX_MIN, GAP_PX_MAX)
        self.sp_px.setSuffix(" px")
        self.sp_px.setValue(px)
        self.sp_px.valueChanged.connect(self._mode_changed)
        form.addRow("Szerokość pasa przerwy:", self.sp_px)
        form.addRow("", _note("Szerokość pasa w pikselach (tryb stałej szerokości): niezależna od czasu przerwy i od przybliżenia."))
        self.btn_fill = self._color_button("gap_fill", "Kolor wypełnienia pasa")
        form.addRow(ml.STRINGS["gap_fill"][0].replace("Przerwa (pas): ", "").capitalize() + ":", self.btn_fill)
        self.sp_op = QSpinBox()
        self.sp_op.setRange(*ml.PARAMS["gap_opacity"][1:3])
        self.sp_op.setSuffix(" %")
        self.sp_op.setValue(self.look["gap_opacity"])
        self.sp_op.setToolTip(ml.PARAMS["gap_opacity"][5])
        self.sp_op.valueChanged.connect(lambda v: self._set("gap_opacity", v))
        form.addRow("Nieprzezroczystość wypełnienia:", self.sp_op)
        form.addRow("", _note(ml.PARAMS["gap_opacity"][5]))
        self.chk_text = QCheckBox("włączony")
        self.chk_text.setChecked(bool(self.look["gap_text"]))
        self.chk_text.setToolTip(ml.PARAMS["gap_text"][5])
        self.chk_text.toggled.connect(lambda v: self._set("gap_text", int(v)))
        form.addRow("Opis długości przerwy:", self.chk_text)
        form.addRow("", _note(ml.PARAMS["gap_text"][5]))
        self.cb_dir = self._enum_combo("gap_text_dir")
        form.addRow("Kierunek opisu:", self.cb_dir)
        self.btn_text = self._color_button("gap_text_color", "Kolor opisu przerwy")
        form.addRow("Kolor czcionki opisu:", self.btn_text)
        self.cb_pos = self._enum_combo("gap_text_pos")
        form.addRow("Położenie opisu:", self.cb_pos)
        form.addRow("", _note(ml.STRINGS["gap_text_pos"][2]))
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
        self._enable()

    # -- building blocks
    def _color_button(self, key: str, title: str) -> QPushButton:
        b = QPushButton()
        b.setToolTip(ml.STRINGS[key][2])
        b.clicked.connect(lambda: self._pick(key, b, title))
        self._paint(b, self.look[key])
        return b

    def _enum_combo(self, key: str) -> QComboBox:
        cb = QComboBox()
        for v in ml.ENUMS[key]:
            cb.addItem(ml.ENUM_LABELS[key][v], v)
        cb.setCurrentIndex(cb.findData(self.look[key]))
        cb.setToolTip(ml.STRINGS[key][2])
        cb.currentIndexChanged.connect(lambda _i, k=key, c=cb: self._set(k, c.currentData()))
        return cb

    @staticmethod
    def _paint(b: QPushButton, c: str) -> None:
        b.setText(c)
        text = "#000000" if QColor(c).lightness() > 128 else "#ffffff"
        b.setStyleSheet(f"QPushButton {{ background: {c}; color: {text}; }}")          # scoped: a bare 'background' leaks into tooltips

    def _pick(self, key: str, b: QPushButton, title: str) -> None:
        c = QColorDialog.getColor(QColor(self.look[key]), self, title)
        if c.isValid():
            self._set(key, c.name())
            self._paint(b, c.name())

    # -- changes (live)
    def _enable(self) -> None:
        fixed = self.cb_mode.currentData() == "fixed"
        for w in (self.sp_px, self.btn_fill, self.sp_op, self.chk_text, self.cb_dir, self.btn_text, self.cb_pos):
            w.setEnabled(fixed)
        if fixed:
            for w in (self.cb_dir, self.btn_text, self.cb_pos):
                w.setEnabled(bool(self.look["gap_text"]))

    def _mode_changed(self, *_):
        self.mode, self.px = self.cb_mode.currentData(), self.sp_px.value()
        self._enable()
        self._apply_mode(self.mode, self.px)

    def _set(self, key: str, value) -> None:
        self.look[key] = value
        self._enable()
        self._apply_look(ml.normalize(self.look))

    def reset(self) -> None:
        for k in ml.GAP_KEYS:
            self.look[k] = ml.DEFAULTS[k]
        self.sp_op.setValue(self.look["gap_opacity"])
        self.chk_text.setChecked(bool(self.look["gap_text"]))
        self.cb_dir.setCurrentIndex(self.cb_dir.findData(self.look["gap_text_dir"]))
        self.cb_pos.setCurrentIndex(self.cb_pos.findData(self.look["gap_text_pos"]))
        self._paint(self.btn_fill, self.look["gap_fill"])
        self._paint(self.btn_text, self.look["gap_text_color"])
        self._apply_look(ml.normalize(self.look))

    def result(self) -> tuple[str, int, dict]:
        return self.cb_mode.currentData(), self.sp_px.value(), ml.normalize(self.look)

    def reject(self) -> None:
        self._apply_mode(self._orig[0], self._orig[1])
        self._apply_look(self._orig[2])
        super().reject()
