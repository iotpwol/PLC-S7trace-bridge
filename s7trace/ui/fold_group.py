"""Collapsible group box: a click on the title folds / unfolds the contents. The title is followed by two spaces and a triangle
(pointing right = folded, down = unfolded) that turns by 90 degrees while the box folds / unfolds."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QPainter, QPolygonF
from PySide6.QtWidgets import QApplication, QGroupBox, QStyle, QStyleOptionGroupBox, QVBoxLayout, QWidget

QWIDGETSIZE_MAX = 16777215
NB = chr(0xA0)                                      # non-breaking spaces are not trimmed from the title


class FoldGroup(QGroupBox):
    foldedChanged = Signal(bool)
    dragMoved = Signal(int)                                  # global y of the mouse while the group is dragged by its title
    dragFinished = Signal()
    contextRequested = Signal(QPoint)                        # right click on the title (global position): menu of the group

    def __init__(self, title: str, key: str = "", parent=None):
        super().__init__(title + NB * 2 + NB * 3, parent)   # two spaces between the name and the triangle (+ room for it)
        self._plain = title
        self.key = key or title
        self._body: QWidget | None = None
        self._t = 1.0                                        # 1 = unfolded (triangle down), 0 = folded (triangle right)
        self._open_h = 0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self._finished)
        self.setMouseTracking(True)
        self.setToolTip("")
        self._press = None                                   # (global mouse position) of a press on the title
        self._dragging = False

    def title(self) -> str:                                  # the name without the spacing
        return self._plain

    def set_body(self, body: QWidget) -> None:
        """The widget with the contents (the only child of the group's layout)."""
        self._body = body
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(body)

    # ---- state
    def folded(self) -> bool:
        return self._t < 0.5 if not self._anim.state() == QVariantAnimation.Running else self._anim.endValue() < 0.5

    def set_folded(self, folded: bool, animate: bool = True) -> None:
        if folded == self.folded() and self._anim.state() != QVariantAnimation.Running:
            return
        target = 0.0 if folded else 1.0
        if not folded and self._body is not None:
            self._body.setVisible(True)
        if folded and self._body is not None and self._anim.state() != QVariantAnimation.Running:
            self._open_h = max(self.height(), self.sizeHint().height())
        self._anim.stop()
        if not animate or not self.isVisible():
            self._t = target
            self._apply_height(target)
            if self._body is not None:
                self._body.setVisible(not folded)
            self.update()
        else:
            self._anim.setStartValue(self._t)
            self._anim.setEndValue(target)
            self._anim.start()
        self.foldedChanged.emit(folded)

    def toggle(self) -> None:
        self.set_folded(not self.folded())

    def _closed_h(self) -> int:
        opt = QStyleOptionGroupBox()
        self.initStyleOption(opt)
        return self.style().subControlRect(QStyle.CC_GroupBox, opt, QStyle.SC_GroupBoxContents, self).top() + 4

    def _apply_height(self, t: float) -> None:
        if t >= 1.0:
            self.setMaximumHeight(QWIDGETSIZE_MAX)
        else:
            lo = self._closed_h()
            self.setMaximumHeight(int(lo + (max(self._open_h, lo) - lo) * t))

    def _step(self, v) -> None:
        self._t = float(v)
        self._apply_height(self._t)
        self.update()

    def _finished(self) -> None:
        if self._t < 0.5 and self._body is not None:
            self._body.setVisible(False)                     # folded: nothing inside takes focus
        self._apply_height(self._t)

    # ---- painting / mouse
    def _label_rect(self):
        opt = QStyleOptionGroupBox()
        self.initStyleOption(opt)
        return self.style().subControlRect(QStyle.CC_GroupBox, opt, QStyle.SC_GroupBoxLabel, self)

    def paintEvent(self, e):
        super().paintEvent(e)
        r = self._label_rect()
        size = max(self.fontMetrics().height() * 0.42, 5.0)
        fm = self.fontMetrics()
        cx, cy = r.left() + fm.horizontalAdvance(self._plain + NB * 2) + size * 0.7, r.center().y() + 1
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(cx, cy)
        p.rotate(90.0 * self._t)                             # 0 deg = pointing right (folded), 90 deg = pointing down
        p.setBrush(self.palette().windowText())
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(-size * 0.5, -size * 0.6), QPointF(-size * 0.5, size * 0.6), QPointF(size * 0.65, 0)]))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._label_rect().adjusted(-4, -2, 4, 2).contains(e.position().toPoint()):
            self._press = e.globalPosition().toPoint()       # a click folds / unfolds, a drag up / down moves the group
            self._dragging = False
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and e.buttons() & Qt.LeftButton:
            gp = e.globalPosition().toPoint()
            if not self._dragging and abs(gp.y() - self._press.y()) >= QApplication.startDragDistance():
                self._dragging = True
                self.setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                self.dragMoved.emit(gp.y())
            e.accept()
            return
        over = self._label_rect().adjusted(-4, -2, 4, 2).contains(e.position().toPoint())
        self.setCursor(Qt.PointingHandCursor if over else Qt.ArrowCursor)
        super().mouseMoveEvent(e)

    def contextMenuEvent(self, e):
        if self._label_rect().adjusted(-4, -2, 4, 2).contains(e.pos()):
            self.contextRequested.emit(e.globalPos())
            e.accept()
            return
        super().contextMenuEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press is not None:
            was_drag, self._press, self._dragging = self._dragging, None, False
            self.setCursor(Qt.PointingHandCursor)
            if was_drag:
                self.dragFinished.emit()
            else:
                self.toggle()
            e.accept()
            return
        super().mouseReleaseEvent(e)
