"""Pomoc → opis programu: spis treści + opisy z rysunkami (QTextBrowser)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLineEdit, QListWidget, QPushButton, QSplitter, QTextBrowser,
                               QVBoxLayout, QWidget)

from .help_content import HELP_DIR, sections                      # noqa: E402,F401  (HELP_DIR / sections: part of this module's interface)


class HelpDialog(QDialog):
    def __init__(self, parent=None, topic: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Pomoc – S7Trace")
        self.resize(1100, 760)
        self._sections = sections()
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Szukaj w pomocy…")
        self.search.returnPressed.connect(self._find)
        btn = QPushButton("Szukaj")
        btn.clicked.connect(self._find)
        top.addWidget(self.search, 1)
        top.addWidget(btn)
        lay.addLayout(top)
        split = QSplitter(Qt.Horizontal)
        self.toc = QListWidget()
        self.toc.addItems([t for t, _ in self._sections])
        self.toc.setMaximumWidth(300)
        self.view = QTextBrowser()
        self.view.setSearchPaths([HELP_DIR])
        self.view.setOpenExternalLinks(False)
        split.addWidget(self.toc)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 840])
        lay.addWidget(split, 1)
        close = QPushButton("Zamknij")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        self.toc.currentRowChanged.connect(self._show)
        self.toc.setCurrentRow(0)
        for i, (title, _) in enumerate(self._sections):
            if topic and topic.lower() in title.lower():
                self.toc.setCurrentRow(i)

    def _show(self, i: int) -> None:
        if 0 <= i < len(self._sections):
            self.view.setHtml(self._sections[i][1])

    def _find(self) -> None:
        """Jumps to the next section containing the text, highlighting the match."""
        q = self.search.text().strip().lower()
        if not q:
            return
        n = len(self._sections)
        start = self.toc.currentRow()
        if self.view.find(self.search.text()):                      # next match in the current section
            return
        for k in range(1, n + 1):
            i = (start + k) % n
            if q in self._sections[i][1].lower() or q in self._sections[i][0].lower():
                self.toc.setCurrentRow(i)
                self.view.find(self.search.text())
                return
