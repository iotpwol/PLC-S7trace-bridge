"""One standard for the tables of the program (pattern: the 'Sygnały do śledzenia' window).

`standard(table)`:
  * every column can be resized by dragging the border of its header (no automatic ResizeToContents / Stretch that blocks it),
  * the last column takes the rest of the width,
  * the first time the table is filled the columns get the width of their content (at most MAX_COL px); `equal=True` shares the width
    equally instead (value tables of the diagnostics). After the user has dragged a border the widths are left alone,
  * rows alternate in light / dark (the colour comes from the theme: `theme.alt_row`; switched on for every table by the theme installer).
The look of the grid, the header and the text indent is in `theme.py` (QSS + `IndentDelegate`)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

MAX_COL = 380              # widest column the automatic fit makes [px]
MIN_COL = 50


class _Fit(QObject):
    def __init__(self, table: QTableView, equal: bool):
        super().__init__(table)
        self.table, self.equal = table, equal
        self.manual = False          # the user dragged a header border: the widths are theirs now
        self.busy = False
        self.pressed = False
        hh = table.horizontalHeader()
        self.hv = hh.viewport()
        self.hv.installEventFilter(self)
        hh.sectionResized.connect(self._resized)
        if equal:
            table.viewport().installEventFilter(self)
        m = table.model()
        for sig in (m.rowsInserted, m.modelReset, m.layoutChanged):
            sig.connect(self._later)
        self._later()

    def _later(self, *_):
        QTimer.singleShot(0, self.fit)

    def _resized(self, *_):
        if self.pressed and not self.busy:
            self.manual = True

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self.hv:
            if t == QEvent.MouseButtonPress:
                self.pressed = True
            elif t in (QEvent.MouseButtonRelease, QEvent.Leave):
                self.pressed = False
        elif t == QEvent.Resize:
            self._later()
        return False

    def fit(self) -> None:
        try:
            self._fit()
        except RuntimeError:                                  # the table is already being deleted
            pass

    def _fit(self) -> None:
        t = self.table
        n = t.model().columnCount()
        if self.manual or self.busy or n < 1:
            return
        self.busy = True
        try:
            if self.equal:
                w = max(t.viewport().width() // n, MIN_COL)
                for c in range(n - 1):
                    t.setColumnWidth(c, w)
            elif t.model().rowCount() > 0:
                for c in range(n - 1):
                    t.resizeColumnToContents(c)
                    t.setColumnWidth(c, max(MIN_COL, min(t.columnWidth(c), MAX_COL)))
        finally:
            self.busy = False


def standard(table: QTableView, equal: bool = False, fit: bool = True) -> None:
    """`fit=False`: the caller sets the widths itself (e.g. a table with editors in the cells)."""
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.Interactive)
    hh.setStretchLastSection(True)
    hh.setMinimumSectionSize(MIN_COL // 2)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)                                 # one line per row: the column widths are the user's to set
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    if fit:
        table._fit = _Fit(table, equal)
