"""Ustawienia -> Serwer Web: reporting of this program to the S7Trace web server (central registry of sessions)."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout)

from ..core import web_agent
from .dialog_kit import dialog_info


@dialog_info("Serwer Web",
             "Program może zgłaszać serwerowi Web, kto go uruchomił i które sterowniki skanuje (wspólny rejestr dla wielu "
             "komputerów). W zamian przed Startem ostrzega, gdy ten sam sterownik skanuje ktoś inny – także na innym komputerze "
             "albo serwer. Token wystawia administrator na stronie „Użytkownicy” serwera.")
class WebServerDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Serwer Web – zgłaszanie sesji")
        self.resize(560, 300)
        c = web_agent.normalize(cfg)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.chk = QCheckBox("Zgłaszaj sesję temu serwerowi")
        self.chk.setChecked(c["enabled"])
        self.url = QLineEdit(c["url"])
        self.url.setPlaceholderText("https://serwer:8080")
        self.token = QLineEdit(c["token"])
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("token programu")
        self.verify = QCheckBox("Sprawdzaj certyfikat serwera (odznacz dla certyfikatu samopodpisanego)")
        self.verify.setChecked(c["verify"])
        form.addRow(self.chk)
        form.addRow("Adres serwera", self.url)
        form.addRow("Token", self.token)
        form.addRow(self.verify)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.btn_test = QPushButton("Test połączenia")
        self.btn_test.clicked.connect(self._test)
        row.addWidget(self.btn_test)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        row.addWidget(self.lbl, 1)
        lay.addLayout(row)
        lay.addStretch(1)
        bb = QHBoxLayout()
        bb.addStretch(1)
        ok, cancel = QPushButton("Zapisz"), QPushButton("Anuluj")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        bb.addWidget(ok)
        bb.addWidget(cancel)
        lay.addLayout(bb)

    def result_cfg(self) -> dict:
        return web_agent.normalize({"enabled": self.chk.isChecked(), "url": self.url.text(), "token": self.token.text(),
                                    "verify": self.verify.isChecked()})

    def _test(self) -> None:
        c = self.result_cfg()
        try:
            r = web_agent.post(c, "/api/agent/report", {"id": "test-" + str(id(self)), "user": "test", "host": "test", "tabs": []})
            self.lbl.setText(f"<b>OK</b> – serwer odpowiada (sterowników skanowanych przez innych: {len(r.get('scans', []))}).")
        except (OSError, ValueError) as e:
            self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {e}")
