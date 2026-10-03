"""'Aktywne sesje programu': who has S7Trace open on this computer and which PLC scans run."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..core import sessions as ss
from .dialog_kit import dialog_info

STATE_TEXT = {"stopped": "Zatrzymany", "connecting": "Łączenie…", "running": "Skanuje", "reconnecting": "Ponowne łączenie…"}
COLS = ["Użytkownik", "Sesja Windows", "Uruchomiony", "Karta", "IP sterownika", "Stan", "Skanuje od"]


def short_time(iso: str | None) -> str:
    """'2026-10-02T14:05:09' -> '14:05:09' (the date is added when it is not today)."""
    if not iso:
        return ""
    from datetime import datetime
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return t.strftime("%H:%M:%S") if t.date() == datetime.now().date() else t.strftime("%Y-%m-%d %H:%M")


@dialog_info("Aktywne sesje programu",
             "Kto na tym komputerze uruchomił S7Trace i które sterowniki skanuje – żeby nie odpytywać dwa razy tego samego PLC.")
class SessionsDialog(QDialog):
    def __init__(self, registry: ss.Registry, parent=None):
        super().__init__(parent)
        self.reg = registry
        self.setWindowTitle("Aktywne sesje programu")
        self.resize(860, 380)
        lay = QVBoxLayout(self)
        self.lbl = QLabel()
        self.lbl.setTextFormat(Qt.RichText)
        lay.addWidget(self.lbl)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        note = QLabel("Lista obejmuje programy uruchomione na tym komputerze (przez wszystkich użytkowników). "
                      "Wpis znika, gdy program zostanie zamknięty lub przestanie odpowiadać (ok. 10 s).")
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addStretch(1)
        b = QPushButton("Zamknij")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def refresh(self) -> None:
        self.reg.publish()                                      # our own row is current too
        sess = self.reg.sessions()
        rows = []
        scans = 0
        for s in sess:
            who = s.get("user", "?") + ("  (to okno)" if s.get("me") else "")
            sid = "" if s.get("session") is None else str(s["session"])
            started = short_time(s.get("started"))
            tabs = s.get("tabs") or [{}]
            for t in tabs:
                state = t.get("state", "")
                scanning = state in ss.SCANNING
                scans += scanning
                rows.append([who, sid, started, t.get("title", ""), t.get("ip", ""), STATE_TEXT.get(state, state),
                             short_time(t.get("since")) if scanning else ""])
        self.lbl.setText(f"Otwartych sesji programu: <b>{len(sess)}</b>, aktywnych skanów sterowników: <b>{scans}</b>")
        self.table.setRowCount(len(rows))
        for r, vals in enumerate(rows):
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                f = it.font()
                f.setBold(True)                                 # values bold, like everywhere in the program
                it.setFont(f)
                self.table.setItem(r, c, it)
