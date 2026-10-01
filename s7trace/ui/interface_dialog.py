"""Widok -> Interfejs: colours and font of the application, with live preview."""
from __future__ import annotations

import os
from typing import Callable

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDialog, QFileDialog, QFontComboBox,
                               QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from . import theme as th


class InterfaceDialog(QDialog):
    """Edits a theme dict; every change is previewed at once through `apply`."""

    def __init__(self, theme: dict, apply: Callable[[dict], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Interfejs")
        self.resize(460, 620)
        self._apply = apply
        self._original = th.normalize(theme)
        self.theme = dict(self._original)
        self._buttons: dict[str, QPushButton] = {}

        lay = QVBoxLayout(self)
        top = QFormLayout()
        self.cb_profile = QComboBox()
        for key, label in th.PROFILES:
            self.cb_profile.addItem(label, key)
        top.addRow("Profil kolorów:", self.cb_profile)
        cfgrow = QHBoxLayout()
        self.cb_saved = QComboBox()
        self.btn_save = QPushButton("Zapisz jako…")
        self.btn_open = QPushButton("Wczytaj z pliku…")
        cfgrow.addWidget(self.cb_saved, 1)
        cfgrow.addWidget(self.btn_save)
        cfgrow.addWidget(self.btn_open)
        top.addRow("Zapisane konfiguracje:", cfgrow)
        lay.addLayout(top)
        self.btn_save.clicked.connect(self._save_as)
        self.btn_open.clicked.connect(self._open_file)
        self.cb_saved.activated.connect(self._saved_chosen)
        self._fill_saved()

        form = QFormLayout()
        for key, (label, _) in th.COLOR_KEYS.items():
            b = QPushButton()
            b.setFixedWidth(120)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            self._buttons[key] = b
            form.addRow(label + ":", b)
        self.font_family = QFontComboBox()
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 32)
        form.addRow("Czcionka:", self.font_family)
        form.addRow("Rozmiar czcionki:", self.font_size)
        host = QWidget()
        host.setLayout(form)
        lay.addWidget(host)
        hint = QLabel("Czcionka „systemowa” = domyślna Windows. Zmiany widać od razu; "
                      "„Anuluj” przywraca poprzedni wygląd.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        self.btn_default = QPushButton("Domyślne")
        ok, cancel = QPushButton("OK"), QPushButton("Anuluj")
        ok.setDefault(True)
        self.btn_default.clicked.connect(lambda: self._load(th.DARK, keep_font=False))
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        for b in (self.btn_default, ok, cancel):
            row.addWidget(b)
        lay.addLayout(row)

        self._sync_widgets()
        self.cb_profile.activated.connect(lambda _=0: self._set_profile(self.cb_profile.currentData()))
        self.font_family.currentFontChanged.connect(self._font_changed)
        self.font_size.valueChanged.connect(self._font_changed)

    # ------------------------------------------------------------------
    def _sync_widgets(self) -> None:
        self.cb_profile.setCurrentIndex(max(0, th.PROFILE_KEYS.index(self.theme.get("profile", "custom"))))
        for key, b in self._buttons.items():
            c = self.theme[key]
            fg = "#000000" if QColor(c).lightness() > 128 else "#ffffff"
            b.setText(c)
            b.setStyleSheet(f"background:{c}; color:{fg}; border:1px solid #777;")
        self.font_family.blockSignals(True)
        self.font_size.blockSignals(True)
        fam = self.theme["font_family"]
        self.font_family.setCurrentFont(QFont(fam) if fam else QApplication.font())
        self.font_size.setValue(self.theme["font_size"])
        self.font_family.blockSignals(False)
        self.font_size.blockSignals(False)

    def _pick(self, key: str) -> None:
        c = QColorDialog.getColor(QColor(self.theme[key]), self, th.COLOR_KEYS[key][0])
        if c.isValid():
            self.theme[key] = c.name()
            self.theme["profile"] = "custom"
            self._sync_widgets()
            self._apply(self.theme)

    def _font_changed(self, *_):
        self.theme["font_family"] = self.font_family.currentFont().family()
        self.theme["font_size"] = self.font_size.value()
        self._apply(self.theme)

    def _load(self, preset: dict, keep_font: bool = True) -> None:
        font = {k: self.theme[k] for k in ("font_family", "font_size")}
        self.theme = th.normalize(preset)
        if keep_font:
            self.theme.update(font)
        self._sync_widgets()
        self._apply(self.theme)

    def _set_profile(self, profile: str) -> None:
        self.theme["profile"] = profile
        self.theme.update(th.profile_colors(profile))
        self._sync_widgets()
        self._apply(self.theme)

    # ------------------------------------------- saved configurations (.json)
    def _fill_saved(self) -> None:
        self.cb_saved.clear()
        self.cb_saved.addItem("— wybierz —", "")
        for name, path in th.list_profiles():
            self.cb_saved.addItem(name, path)

    def _saved_chosen(self, _=0) -> None:
        path = self.cb_saved.currentData()
        if path:
            self._load_file(path)

    def _load_file(self, path: str) -> None:
        try:
            t = th.load_profile(path)
        except Exception as e:
            QMessageBox.warning(self, "Interfejs", f"Nie można wczytać konfiguracji: {e}")
            return
        self.theme = t
        self._sync_widgets()
        self._apply(self.theme)

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Wczytaj konfigurację interfejsu", th.profiles_dir(),
                                              "JSON (*.json)")
        if path:
            self._load_file(path)

    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz konfigurację interfejsu",
                                              os.path.join(th.profiles_dir(), "interfejs.json"), "JSON (*.json)")
        if not path:
            return
        try:
            th.save_profile(path, self.theme)
        except OSError as e:
            QMessageBox.warning(self, "Interfejs", f"Nie można zapisać: {e}")
            return
        self._fill_saved()
        i = self.cb_saved.findData(path)
        if i >= 0:
            self.cb_saved.setCurrentIndex(i)

    def reject(self) -> None:
        self._apply(self._original)
        super().reject()
