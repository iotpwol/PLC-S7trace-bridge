"""Status label with a configurable number of lines and a text that can be dragged with the mouse when it does not fit.

  * One line (the default): the text is right (or left, see set_align) aligned while it fits; when it is wider than the bar it starts at the
    left edge and the mouse (or the wheel) moves it between two stops - the right end of the text at the right edge of
    the bar, and the left end of the text at the left edge. It never goes further out of the bar.
  * Several lines (the 'Interfejs' setting): the text wraps; the bar is as high as the text needs, but never more than the
    chosen number of lines - there is no empty line. A text longer than that is dragged up and down the same way."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class PanLabel(QWidget):
    menuRequested = Signal(QPoint)                            # right click: the owner shows the status bar menu (global position)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)           # the background colour from the stylesheet
        self._lbl = QLabel(self)
        self._lbl.setTextFormat(Qt.RichText)
        self._lbl.setWordWrap(False)
        self._lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._probe = QLabel("Xg", self)                    # measures the height of one line in the bar's own style
        self._probe.hide()
        self._max_lines = 1
        self._align = "right"                              # justification of the text: "right" (default) / "left"
        self._off = 0                                       # x (one line) or y (several lines) of the text, <= 0
        self._press: tuple[int, int] | None = None
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)      # a long text never widens the window
        self.setMinimumWidth(0)
        self._set_height(max(self._lbl.sizeHint().height(), 18))

    # ---- the QLabel-like part of the interface used by the tab
    def setText(self, text: str) -> None:
        self._lbl.setText(text)
        self._layout_text()

    def text(self) -> str:
        return self._lbl.text()

    def setTextFormat(self, fmt) -> None:
        self._lbl.setTextFormat(fmt)

    def set_max_lines(self, n: int) -> None:
        n = max(1, int(n))
        if n != self._max_lines:
            self._max_lines = n
            self._off = 0
            self._layout_text()

    def set_colors(self, bg: str, fg: str) -> None:
        """Background and text colour of the bar ('Interfejs' settings)."""
        self.setStyleSheet(f"PanLabel {{ background: {bg}; }} PanLabel QLabel {{ color: {fg}; background: transparent; }}")

    def max_lines(self) -> int:
        return self._max_lines

    def set_align(self, align: str) -> None:
        align = "left" if align == "left" else "right"
        if align != self._align:
            self._align = align
            self._off = 0
            self._layout_text()

    def align(self) -> str:
        return self._align

    def contextMenuEvent(self, e):
        self.menuRequested.emit(e.globalPos())
        e.accept()

    # ---- geometry
    def _set_height(self, h: int) -> None:
        if self.height() != h or self.minimumHeight() != h:
            self.setFixedHeight(h)

    def _multi(self) -> bool:
        return self._max_lines > 1

    def _text_size(self) -> tuple[int, int]:
        """(width, height) the text needs in the present mode (several lines: wrapped to the bar width)."""
        if self._multi():
            w = max(self.width(), 1)
            return w, max(self._lbl.heightForWidth(w), self.line_height())
        sh = self._lbl.sizeHint()
        return sh.width(), sh.height()

    def line_height(self) -> int:
        return max(self._probe.sizeHint().height(), 1)

    def lines_shown(self) -> int:
        return max(round(self.height() / self.line_height()), 1)

    def overflow(self) -> int:
        """How many pixels of the text do not fit (0 = it fits)."""
        tw, th = self._text_size()
        return max(th - self.height(), 0) if self._multi() else max(tw - self.width(), 0)

    def text_pos(self) -> int:
        return self._lbl.y() if self._multi() else self._lbl.x()

    def _layout_text(self) -> None:
        self._lbl.setWordWrap(self._multi())
        h_al = Qt.AlignLeft if self._align == "left" else Qt.AlignRight
        self._lbl.setAlignment((h_al | Qt.AlignTop) if self._multi() else (Qt.AlignLeft | Qt.AlignVCenter))
        if self._multi():
            w, h = self._text_size()
            lh = self.line_height()
            per_line = h / max(round(h / lh), 1)
            vis = int(min(h, self._max_lines * per_line + 0.5))
            self._set_height(max(vis, 18))
            self._lbl.resize(w, h)
            self._off = max(min(self._off, 0), self.height() - h)
            self._lbl.move(0, self._off)
        else:
            tw, th = self._text_size()
            self._set_height(max(th, 18))
            self._lbl.resize(tw, self.height())
            if tw <= self.width():
                x = 0 if self._align == "left" else self.width() - tw      # fits: right (default) or left aligned
                self._off = 0
            else:
                self._off = max(min(self._off, 0), self.width() - tw)      # the stops: [bar width - text width, 0]
                x = self._off
            self._lbl.move(x, 0)
        self.setCursor(Qt.OpenHandCursor if self.overflow() else Qt.ArrowCursor)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_text()

    # ---- panning
    def _pan_to(self, pos: int) -> None:
        tw, th = self._text_size()
        if self._multi():
            self._off = max(min(pos, 0), self.height() - th)
            self._lbl.move(0, self._off)
        elif tw > self.width():
            self._off = max(min(pos, 0), self.width() - tw)
            self._lbl.move(self._off, 0)

    def _axis(self, e) -> int:
        return int(e.position().y() if self._multi() else e.position().x())

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.overflow():
            self._press = (self._axis(e), self._off)
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None:
            self._pan_to(self._press[1] + self._axis(e) - self._press[0])
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._press is not None:
            self._press = None
            self.setCursor(Qt.OpenHandCursor if self.overflow() else Qt.ArrowCursor)
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        if self.overflow():
            d = e.angleDelta().y() or e.angleDelta().x()
            self._pan_to(self._off + (60 if d > 0 else -60))
            e.accept()
        else:
            super().wheelEvent(e)
