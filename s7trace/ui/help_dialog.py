"""Pomoc → opis programu: spis treści + opisy z rysunkami (QTextBrowser)."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea, QSplitter,
                               QTextBrowser, QVBoxLayout, QWidget)

from .help_content import HELP_DIR, sections                      # noqa: E402,F401  (HELP_DIR / sections: part of this module's interface)

CAPTURE_DPR = 1.25         # the pictures are taken by tools/make_help_images.py at 125 % screen scale (sharp); their size in the Help (75 % of the real
                           # window, 50 % for the whole program window) is stored in the file (PNG resolution = 3780 x capture scale / display scale)
DPM_LOGICAL = 3780         # dots per metre of a 96 dpi image: a picture with this resolution is shown pixel for pixel


class ImageBrowser(QTextBrowser):
    """QTextBrowser that shows the pictures 1:1 in screen pixels (no scaling when they fit) and scales only the wider ones itself, smoothly -
    the built-in scaling is a fast, unfiltered one and made the photographs blurry. A click on a picture opens it in full resolution (link `zoom:<name>`)."""

    def loadResource(self, rtype, url: QUrl):
        if rtype == 2 and url.path().lower().endswith(".png"):                       # QTextDocument.ImageResource
            path = os.path.join(HELP_DIR, url.path().replace("/", os.sep).lstrip(os.sep))
            img = QImage(path)
            if not img.isNull():
                dpr = self.devicePixelRatioF()
                room = max(300, round((self.viewport().width() - 30) * dpr))            # text area in real pixels
                logical = img.width() * DPM_LOGICAL / max(img.dotsPerMeterX(), 1)        # the width the picture has on screen (logical pixels): 75 % / 50 % of the window
                want = min(round(logical * dpr), room)                                   # a picture that does not fit is scaled down
                if want != img.width():                                                  # always smooth (a sharp downscale of the full capture)
                    img = img.scaledToWidth(want, Qt.SmoothTransformation)
                img.setDevicePixelRatio(dpr)
                return img
        return super().loadResource(rtype, url)


class ZoomDialog(QDialog):
    """A picture of the help in its full resolution (scrollable)."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Zdjęcie – {name}")
        pm = QPixmap(os.path.join(HELP_DIR, "img", name + ".png"))
        lab = QLabel()
        lab.setPixmap(pm)
        area = QScrollArea()
        area.setWidget(lab)
        lay = QVBoxLayout(self)
        lay.addWidget(area, 1)
        btn = QPushButton("Zamknij")
        btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(btn)
        lay.addLayout(row)
        self.resize(min(pm.width() + 40, 1500), min(pm.height() + 100, 950))


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
        self.view = ImageBrowser()
        self.view.setSearchPaths([HELP_DIR])
        self.view.setOpenLinks(False)
        self.view.setOpenExternalLinks(False)
        self.view.anchorClicked.connect(self._link)
        self._relayout = QTimer(self)                              # the pictures are scaled to the width of the text area
        self._relayout.setSingleShot(True)
        self._relayout.setInterval(250)
        self._relayout.timeout.connect(self._rerender)
        self._last_w = 0
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

    def _link(self, url: QUrl) -> None:
        if url.scheme() == "zoom":
            ZoomDialog(url.path(), self).exec()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._relayout.start()

    def _rerender(self) -> None:
        w = self.view.viewport().width()
        if abs(w - self._last_w) > 20 and self.isVisible():
            sb = self.view.verticalScrollBar().value()
            self._show(self.toc.currentRow())
            self.view.verticalScrollBar().setValue(sb)

    def _show(self, i: int) -> None:
        self._last_w = self.view.viewport().width()
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
