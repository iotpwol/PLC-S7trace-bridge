"""Przeglądarka zmiennych OPC UA: wybór węzłów z drzewa serwera i dodanie ich jako sygnałów."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from ..core.types import DEFAULT_COLORS, Signal
from .dialog_kit import dialog_info

VARIANT_TO_DTYPE = {"Boolean": "BOOL", "SByte": "SINT", "Byte": "USINT", "Int16": "INT", "UInt16": "UINT",
                    "Int32": "DINT", "UInt32": "UDINT", "Int64": "LREAL", "UInt64": "LREAL", "Float": "REAL",
                    "Double": "LREAL"}


@dialog_info("Przeglądarka zmiennych OPC UA",
             "Drzewo węzłów serwera OPC UA. Zaznacz zmienne, które mają trafić na listę sygnałów do śledzenia.")
class OpcBrowser(QDialog):
    def __init__(self, host: str, opts: dict, parent=None, first_color: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Przeglądarka zmiennych OPC UA")
        self.resize(700, 560)
        self._first_color = first_color
        self.client = None
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Węzeł", "Typ", "NodeId"])
        self.tree.setColumnWidth(0, 280)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemExpanded.connect(self._expand)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        ok, cancel = QPushButton("Dodaj zaznaczone zmienne"), QPushButton("Anuluj")
        row.addStretch()
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        try:
            from asyncua.sync import Client
            self.client = Client(f"opc.tcp://{host}:{int(opts.get('opcua_port', 4840))}", timeout=6)
            if not opts.get("opcua_anonymous", True) and opts.get("username"):
                self.client.set_user(opts["username"])
                self.client.set_password(opts.get("password", ""))
            sec = opts.get("opcua_security", "None")
            if sec != "None" and opts.get("cert") and opts.get("key"):
                self.client.set_security_string(f"{sec},{opts['cert']},{opts['key']}")
            self.client.connect()
            self.info.setText("Rozwiń drzewo (Objects → …) i zaznacz zmienne. Zmienne zoptymalizowane widać tu po nazwie.")
            self._add(self.tree.invisibleRootItem(), self.client.get_objects_node())
        except Exception as e:
            self.info.setText(f"Nie można połączyć z serwerem OPC UA: {e}")
            self.client = None

    def _add(self, parent, node) -> None:
        try:
            children = node.get_children()
        except Exception:
            return
        for ch in children:
            try:
                name = ch.read_browse_name().Name
                cls = ch.read_node_class().name
            except Exception:
                continue
            dtype = ""
            if cls == "Variable":
                try:
                    dtype = ch.read_data_type_as_variant_type().name
                except Exception:
                    dtype = "?"
            it = QTreeWidgetItem([name, dtype, ch.nodeid.to_string()])
            it.setData(0, Qt.UserRole, (cls, dtype))
            if cls != "Variable" or True:
                it.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            parent.addChild(it)

    def _expand(self, item: QTreeWidgetItem) -> None:
        if self.client is None or item.data(0, Qt.UserRole + 1):
            return
        item.setData(0, Qt.UserRole + 1, True)                     # children are loaded once
        self._add(item, self.client.get_node(item.text(2)))

    def signals(self) -> list[Signal]:
        out = []
        for it in self.tree.selectedItems():
            cls, vt = it.data(0, Qt.UserRole)
            if cls != "Variable":
                continue
            out.append(Signal(name=it.text(0), source="OPC", node=it.text(2), dtype=VARIANT_TO_DTYPE.get(vt, "REAL"),
                              color=DEFAULT_COLORS[(self._first_color + len(out)) % len(DEFAULT_COLORS)]))
        return out

    def done(self, r: int) -> None:
        if r and not self.signals() and self.tree.selectedItems():
            QMessageBox.information(self, "OPC UA", "Zaznaczono tylko węzły niebędące zmiennymi.")
            return
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None
        super().done(r)
