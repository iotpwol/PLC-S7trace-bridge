"""Ustawienia → Metoda połączenia: ręczny wybór sposobu komunikacji i dane logowania / porty / certyfikaty."""
from __future__ import annotations

import os

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

from ..core.config import app_dir
from ..core.drivers import CONN_TYPES, generate_client_cert
from .wizard_dialog import DetectWorker
from .dialog_kit import dialog_info

HINTS = {
    "auto": "Przy każdym Start program sprawdza kolejno: S7comm → OPC UA → Web API → Modbus TCP i używa pierwszej działającej "
            "metody zgodnej ze źródłami sygnałów. Gdy żadna nie działa, pokazuje kreatora z zaleceniami.",
    "s7": "Najszybsza metoda. S7-1200/1500: wymaga „Permit access with PUT/GET” i DB bez „Optimized block access”. "
          "Rack/Slot ustawiasz w panelu Połączenie. Sygnały: źródło I, Q, M, DB.",
    "opcua": "Czyta zmienne po nazwie (także DB zoptymalizowane). Wymaga włączonego serwera OPC UA w CPU (zwykle licencja). "
             "Sygnały: źródło OPC, węzeł np. ns=3;s=\"DB_Piec\".\"Temperatura\" (przeglądarka: przycisk „Z OPC UA…” w oknie Sygnały).",
    "webapi": "Eksperymentalne. Wymaga włączonego Web API w CPU i użytkownika z prawem odczytu. Sygnały: źródło WEB, "
              "nazwa zmiennej np. \"DB_Piec\".Temperatura.",
    "modbus": "Wymaga serwera Modbus TCP w programie PLC. Sygnały: źródła MBH/MBI (rejestry), MBC/MBD (cewki); "
              "bajt = numer rejestru, DB = Unit ID (0 = domyślny).",
}


@dialog_info("Metoda połączenia i dane logowania",
             "Wybiera sposób komunikacji ze sterownikiem (S7, OPC UA, Web API, Modbus) i dane logowania. „Test” sprawdza połączenie, „Kreator” rozpoznaje metodę sam.")
class ConnectionDialog(QDialog):
    def __init__(self, tab, parent=None):
        super().__init__(parent or tab)
        self.tab = tab
        self.setWindowTitle("Metoda połączenia i dane logowania")
        self.resize(640, 640)
        c = tab.cfg.conn
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.cb_type = QComboBox()
        for k, label in CONN_TYPES:
            self.cb_type.addItem(label, k)
        self.cb_type.setCurrentIndex(max(self.cb_type.findData(tab.cfg.conn_type), 0))
        form.addRow("Metoda połączenia:", self.cb_type)
        lay.addLayout(form)
        self.lbl_hint = QLabel()
        self.lbl_hint.setWordWrap(True)
        lay.addWidget(self.lbl_hint)

        g = QGroupBox("OPC UA")
        f = QFormLayout(g)
        self.sp_opc = self._spin(1, 65535, c["opcua_port"])
        self.cb_sec = QComboBox()
        self.cb_sec.addItems(["None", "Basic256Sha256,SignAndEncrypt", "Basic256Sha256,Sign", "Aes128_Sha256_RsaOaep,SignAndEncrypt"])
        self.cb_sec.setCurrentText(c["opcua_security"] if c["opcua_security"] else "None")
        self.chk_anon = QCheckBox("Dostęp anonimowy (gość)")
        self.chk_anon.setChecked(c["opcua_anonymous"])
        self.ed_cert, self.ed_key = QLineEdit(c["cert"]), QLineEdit(c["key"])
        b_cert = QPushButton("Generuj certyfikat klienta…")
        b_cert.clicked.connect(self._gen_cert)
        f.addRow("Port:", self.sp_opc)
        f.addRow("Zabezpieczenia:", self.cb_sec)
        f.addRow("", self.chk_anon)
        f.addRow("Certyfikat klienta (.der):", self.ed_cert)
        f.addRow("Klucz prywatny (.pem):", self.ed_key)
        f.addRow("", b_cert)
        lay.addWidget(g)
        self.g_opc = g

        g = QGroupBox("Web API")
        f = QFormLayout(g)
        self.chk_https = QCheckBox("HTTPS")
        self.chk_https.setChecked(c["web_https"])
        self.sp_web = self._spin(1, 65535, c["web_port"])
        self.chk_verify = QCheckBox("Weryfikuj certyfikat serwera (domyślnie wyłączone – certyfikaty PLC są samopodpisane)")
        self.chk_verify.setChecked(c["web_verify"])
        f.addRow("", self.chk_https)
        f.addRow("Port:", self.sp_web)
        f.addRow("", self.chk_verify)
        lay.addWidget(g)
        self.g_web = g

        g = QGroupBox("Modbus TCP")
        f = QFormLayout(g)
        self.sp_mb = self._spin(1, 65535, c["modbus_port"])
        self.sp_unit = self._spin(0, 255, c["modbus_unit"])
        self.chk_swap = QCheckBox("Odwrócona kolejność słów 16-bit (dla 32/64-bit)")
        self.chk_swap.setChecked(c["modbus_wordswap"])
        f.addRow("Port:", self.sp_mb)
        f.addRow("Unit ID:", self.sp_unit)
        f.addRow("", self.chk_swap)
        lay.addWidget(g)
        self.g_mb = g

        g = QGroupBox("Logowanie (OPC UA bez dostępu anonimowego, Web API)")
        f = QFormLayout(g)
        self.ed_user = QLineEdit(c["username"])
        self.ed_pass = QLineEdit(c["password"])
        self.ed_pass.setEchoMode(QLineEdit.Password)
        self.chk_remember = QCheckBox("Zapamiętaj hasło w pliku konfiguracji (jawnym tekstem w %APPDATA%\\S7Trace – tylko na zaufanym komputerze)")
        self.chk_remember.setChecked(c["remember_password"])
        f.addRow("Użytkownik:", self.ed_user)
        f.addRow("Hasło:", self.ed_pass)
        f.addRow("", self.chk_remember)
        lay.addWidget(g)
        self.g_login = g

        self.lbl_test = QLabel()
        self.lbl_test.setWordWrap(True)
        lay.addWidget(self.lbl_test)
        row = QHBoxLayout()
        self.btn_test = QPushButton("Testuj wybraną metodę")
        self.btn_wiz = QPushButton("Kreator połączenia…")
        ok, cancel = QPushButton("OK"), QPushButton("Anuluj")
        ok.setDefault(True)
        for b in (self.btn_test, self.btn_wiz):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        ok.clicked.connect(self._ok)
        cancel.clicked.connect(self.reject)
        self.btn_test.clicked.connect(self._test)
        self.btn_wiz.clicked.connect(self._wizard)
        self.cb_type.currentIndexChanged.connect(self._sync)
        self._sync()

    @staticmethod
    def _spin(lo, hi, val):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(int(val))
        return s

    def _sync(self) -> None:
        k = self.cb_type.currentData()
        self.lbl_hint.setText(HINTS[k])
        self.g_opc.setVisible(k in ("auto", "opcua"))
        self.g_web.setVisible(k in ("auto", "webapi"))
        self.g_mb.setVisible(k in ("auto", "modbus"))
        self.g_login.setVisible(k in ("auto", "opcua", "webapi"))

    def values(self) -> dict:
        return {"opcua_port": self.sp_opc.value(), "opcua_security": self.cb_sec.currentText(),
                "opcua_anonymous": self.chk_anon.isChecked(), "username": self.ed_user.text().strip(),
                "password": self.ed_pass.text(), "remember_password": self.chk_remember.isChecked(),
                "cert": self.ed_cert.text().strip(), "key": self.ed_key.text().strip(),
                "web_port": self.sp_web.value(), "web_https": self.chk_https.isChecked(),
                "web_verify": self.chk_verify.isChecked(), "modbus_port": self.sp_mb.value(),
                "modbus_unit": self.sp_unit.value(), "modbus_wordswap": self.chk_swap.isChecked()}

    def _ok(self) -> None:
        self.tab.cfg.conn_type = self.cb_type.currentData()
        self.tab.cfg.conn = self.values()
        self.tab.update_method_label()
        self.accept()

    def _gen_cert(self) -> None:
        folder = os.path.join(app_dir(), "certyfikaty")
        try:
            cert, key = generate_client_cert(folder)
        except Exception as e:
            QMessageBox.warning(self, "Certyfikat", f"Nie można wygenerować certyfikatu: {e}")
            return
        self.ed_cert.setText(cert)
        self.ed_key.setText(key)
        QMessageBox.information(self, "Certyfikat klienta",
                                f"Zapisano:\n{cert}\n{key}\n\nW TIA Portal dodaj certyfikat klienta do zaufanych "
                                "(serwer OPC UA → Security → Trusted clients) albo zatwierdź go w menedżerze certyfikatów.")

    def _test(self) -> None:
        k = self.cb_type.currentData()
        methods = None if k == "auto" else [k]
        self.lbl_test.setText("Testowanie…")
        self.btn_test.setEnabled(False)
        host = self.tab.ed_ip.text()
        w = DetectWorker(host, self.values(), self.tab.sp_rack.value(), self.tab.sp_slot.value(), methods, parent=self)
        w.finished_.connect(self._tested)
        self._w = w
        w.start()

    def _tested(self, res) -> None:
        self.btn_test.setEnabled(True)
        lines = [f"{'✔' if s.status == 'ok' else '▲' if s.status == 'warn' else '✖' if s.status == 'fail' else '—'} "
                 f"{s.title}: {s.detail}" for s in res.steps if not s.key.startswith(("ping", "port"))]
        self.lbl_test.setText("\n".join(lines + [f"→ {a}" for a in res.advice[:2]]))

    def _wizard(self) -> None:
        from .wizard_dialog import WizardDialog
        self.tab.cfg.conn = self.values()
        WizardDialog(self.tab, parent=self).exec()
