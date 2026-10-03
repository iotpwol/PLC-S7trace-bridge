"""Splitter whose one pane can be folded away and brought back: a small arrow button on the handle, or a double click
on the handle. Used for the settings panel (folds to the left) and the overview strip (folds down)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal as QtSignal
from PySide6.QtWidgets import QSizePolicy, QSplitter, QSplitterHandle, QToolButton

HANDLE = 14                                  # thickness of the handle: room for the button


class FoldHandle(QSplitterHandle):
    def __init__(self, orientation, parent: "FoldSplitter"):
        super().__init__(orientation, parent)
        self.btn = QToolButton(self)
        self.btn.setAutoRaise(True)
        self.btn.setFixedSize(HANDLE, HANDLE)
        self.btn.setCursor(Qt.ArrowCursor)
        self.btn.clicked.connect(parent.toggle)
        self.setToolTip("Dwukrotne kliknięcie: zwiń / rozwiń")
        self.update_arrow()

    def update_arrow(self) -> None:
        sp: FoldSplitter = self.splitter()
        if sp.orientation() == Qt.Horizontal:                 # pane on the left folds to the left
            arrow = Qt.RightArrow if sp.collapsed else Qt.LeftArrow
            tip = "Pokaż panel ustawień" if sp.collapsed else "Schowaj panel ustawień"
        else:                                                 # pane at the bottom folds down
            arrow = Qt.UpArrow if sp.collapsed else Qt.DownArrow
            tip = "Pokaż wykres przeglądowy" if sp.collapsed else "Schowaj wykres przeglądowy"
        self.btn.setArrowType(arrow)
        self.btn.setToolTip(tip)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.orientation() == Qt.Horizontal:               # button at the top of the vertical bar
            self.btn.move(max((self.width() - HANDLE) // 2, 0), 0)
        else:                                                 # button at the left end of the horizontal bar
            self.btn.move(0, max((self.height() - HANDLE) // 2, 0))

    def mouseDoubleClickEvent(self, e):
        self.splitter().toggle()


class FoldSplitter(QSplitter):
    """`fold_index` = the pane that folds (0 = first / left / top, 1 = second / bottom)."""
    foldChanged = QtSignal(bool)

    def __init__(self, orientation, fold_index: int, default_size: int, parent=None):
        super().__init__(orientation, parent)
        self.fold_index = fold_index
        self.collapsed = False
        self.saved = default_size                 # size of the folding pane when it was last visible
        self._min = 0
        self._policy = QSizePolicy.Preferred
        self._pending: bool | None = None         # fold requested before the splitter had a size
        self.setHandleWidth(HANDLE)
        self.setChildrenCollapsible(False)
        self.splitterMoved.connect(self._moved)

    def createHandle(self):
        return FoldHandle(self.orientation(), self)

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
