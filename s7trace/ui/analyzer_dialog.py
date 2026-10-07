"""Ustawienia -> Analizator anomalii: the bridge to the external S7SignalAnalyzer (see core/ext_bridge.py)."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QVBoxLayout)

from ..core import ext_bridge
from .dialog_kit import dialog_info


@dialog_info("Analizator anomalii",
             "Program może udostępniać dane jednej karty zewnętrznemu analizatorowi (S7SignalAnalyzer), który uczy się normalnej "
             "pracy maszyny i zgłasza odchylenia. Most nasłuchuje tylko na tym komputerze (127.0.0.1); analizator łączy się "
             "z podanym portem i tokenem. Gdy nic nie jest połączone, dane nie są nigdzie wysyłane.")
class AnalyzerDialog(QDialog):
    def __init__(self, cfg: dict, tab_titles: list[str], info_fn, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Analizator anomalii – most do S7SignalAnalyzer")
        self.resize(560, 330)
        self._info_fn = info_fn
        c = ext_bridge.normalize(cfg)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.chk = QCheckBox("Udostępniaj dane analizatorowi")
        self.chk.setChecked(c["enabled"])
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(c["port"])
        self.token = QLineEdit(c["token"] or ext_bridge.new_token())
        row = QHBoxLayout()
        row.addWidget(self.token, 1)
        b_new, b_copy = QPushButton("Nowy token"), QPushButton("Kopiuj")
        b_new.clicked.connect(lambda: self.token.setText(ext_bridge.new_token()))
        b_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.token.text()))
        row.addWidget(b_new)
        row.addWidget(b_copy)
        self.source = QComboBox()
        self.source.addItems(tab_titles)
        if c["source"] in tab_titles:
            self.source.setCurrentIndex(tab_titles.index(c["source"]))
        form.addRow(self.chk)
        form.addRow("Port (127.0.0.1)", self.port)
        form.addRow("Token", row)
        form.addRow("Karta źródłowa", self.source)
        lay.addLayout(form)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        lay.addStretch(1)
        bb = QHBoxLayout()
        bb.addStretch(1)
        ok, cancel = QPushButton("Zapisz"), QPushButton("Anuluj")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        bb.addWidget(ok)
        bb.addWidget(cancel)
        lay.addLayout(bb)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)
        self._refresh()

    def _refresh(self) -> None:
        i = self._info_fn()
        if i["error"]:
            self.lbl.setText(f"<b>Błąd mostu:</b> {i['error']}")
        elif not i["running"]:
            self.lbl.setText("Most wyłączony.")
        else:
            who = ", ".join(i["clients"]) or "brak połączonego analizatora"
            st = (i["status"] or {}).get("text", "")
            self.lbl.setText(f"Most działa na porcie <b>{i['port']}</b>. Połączeni: <b>{who}</b>. "
                             f"Zdarzeń: <b>{i['events']}</b>." + (f"<br>Status analizatora: {st}" if st else ""))

    def result_cfg(self) -> dict:
        return ext_bridge.normalize({"enabled": self.chk.isChecked(), "port": self.port.value(),
                                     "token": self.token.text().strip(), "source": self.source.currentText()})
