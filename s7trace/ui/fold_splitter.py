"""Splitter whose one pane can be folded away and brought back: a double click on the handle. The handle is thin
and shows itself only while the mouse is over it (or always, when the user chose so in 'Interfejs'). Used for the
settings panel (folds to the left) and the overview strip (folds down)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal as QtSignal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QSplitter, QSplitterHandle

HANDLE = 4                                   # thickness of the handle in pixels (it used to be 14 with an arrow button)
DEFAULT_BAR = "#2a82da"


class FoldHandle(QSplitterHandle):
    def __init__(self, orientation, parent: "FoldSplitter"):
        super().__init__(orientation, parent)
        self._hover = False
        self._drag = False
        self.setAttribute(Qt.WA_Hover, True)
        self.update_tip()

    def update_tip(self) -> None:
        sp: FoldSplitter = self.splitter()
        what = "panel ustawień" if sp.orientation() == Qt.Horizontal else "wykres przeglądowy"
        self.setToolTip(f"Przeciągnij: zmień rozmiar. Dwukrotne kliknięcie: {'pokaż' if sp.collapsed else 'schowaj'} {what}")

    update_arrow = update_tip                                 # (called when the fold state changes)

    def _visible_bar(self) -> bool:
        return self._hover or self._drag or self.splitter().bar_always

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._drag = True
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = False
        self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        if not self._visible_bar():
            return                                            # invisible until the mouse is over it
        c = QColor(self.splitter().bar_color)
        if not (self._hover or self._drag):
            c.setAlpha(150)                                   # 'always visible' but quieter than under the mouse
        p = QPainter(self)
        p.fillRect(self.rect(), c)

    def mouseDoubleClickEvent(self, e):
        self.splitter().toggle()


class FoldSplitter(QSplitter):
    """`fold_index` = the pane that folds (0 = first / left / top, 1 = second / bottom)."""
    foldChanged = QtSignal(bool)

    def __init__(self, orientation, fold_index: int, default_size: int, parent=None):
        super().__init__(orientation, parent)
        self.fold_index = fold_index
        self.collapsed = False
        self.bar_color = DEFAULT_BAR              # colour and permanent visibility of the handle ('Interfejs' settings)
        self.bar_always = False
        self.saved = default_size                 # size of the folding pane when it was last visible
        self._min = 0
        self._policy = QSizePolicy.Preferred
        self._pending: bool | None = None         # fold requested before the splitter had a size
        self.setHandleWidth(HANDLE)
        self.setChildrenCollapsible(False)
        self.splitterMoved.connect(self._moved)

    def createHandle(self):
        return FoldHandle(self.orientation(), self)

    def set_bar(self, color: str, always: bool) -> None:
        self.bar_color, self.bar_always = color or DEFAULT_BAR, bool(always)
        h = self.handle(1)
        if h is not None:
            h.update()

    def set_pane_min(self, v: int) -> None:
        """Smallest width / height of the folding pane; applied at once when it is shown, on unfolding otherwise."""
        if self.collapsed:
            self._min = v
        else:
            self._set_min(v)

    # ---- state
    def _extent(self) -> int:
        return self.width() if self.orientation() == Qt.Horizontal else self.height()

    def _pane(self):
        return self.widget(self.fold_index)

    def _pane_size(self) -> int:
        return self.sizes()[self.fold_index]

    def _set_min(self, v: int, fold: bool | None = None) -> None:
        """Minimum size of the folding pane. While it is folded its size policy is 'Ignored' in that direction,
        otherwise the splitter would still keep the widget's minimumSizeHint (a scroll area: ~70 px)."""
        w = self._pane()
        horiz = self.orientation() == Qt.Horizontal
        if horiz:
            w.setMinimumWidth(v)
        else:
            w.setMinimumHeight(v)
        if fold is not None:
            pol = w.sizePolicy()
            if fold:
                self._policy = pol.horizontalPolicy() if horiz else pol.verticalPolicy()
                new = QSizePolicy.Ignored
            else:
                new = self._policy
            if horiz:
                pol.setHorizontalPolicy(new)
            else:
                pol.setVerticalPolicy(new)
            w.setSizePolicy(pol)

    def _get_min(self) -> int:
        w = self._pane()
        return w.minimumWidth() if self.orientation() == Qt.Horizontal else w.minimumHeight()

    def _arrow(self) -> None:
        h = self.handle(1)
        if isinstance(h, FoldHandle):
            h.update_arrow()

    def set_sizes_for(self, pane_px: int) -> None:
        total = max(self._extent() - self.handleWidth(), pane_px + 1)
        sizes = [0, 0]
        sizes[self.fold_index] = pane_px
        sizes[1 - self.fold_index] = total - pane_px
        self.blockSignals(True)
        self.setSizes(sizes)
        self.blockSignals(False)

    def set_collapsed(self, on: bool) -> None:
        if on == self.collapsed:
            return
        if self._extent() < 80:                   # not laid out yet: do it on the first resize
            self._pending = on
            return
        if on:
            if self._pane_size() > 0:
                self.saved = self._pane_size()
            self._min = self._get_min()
            self._set_min(0, fold=True)
            self.collapsed = True
            self.set_sizes_for(0)
        else:
            self._set_min(self._min, fold=False)
            self.collapsed = False
            self.set_sizes_for(max(self.saved, self._min, 40))
        self._arrow()
        self.foldChanged.emit(self.collapsed)

    def toggle(self) -> None:
        self.set_collapsed(not self.collapsed)

    def _moved(self, *_) -> None:
        size = self._pane_size()
        if self.collapsed and size > 8:           # the user dragged the folded pane open
            self._set_min(self._min, fold=False)
            self.collapsed = False
            self._arrow()
            self.foldChanged.emit(False)
        if not self.collapsed and size > 0:
            self.saved = size

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._pending is not None and self._extent() >= 80:
            on, self._pending = self._pending, None
            self.set_collapsed(on)
