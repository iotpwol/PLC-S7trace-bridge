"""One standard for the tables of the program (pattern: the 'Sygnały do śledzenia' window).

`standard(table, sort=True)` (header click sorts, see `filling` / `src`):
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


def standard(table: QTableView, equal: bool = False, fit: bool = True, sort: bool = False) -> None:
    """`fit=False`: the caller sets the widths itself (e.g. a table with editors in the cells)."""
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.Interactive)
    hh.setStretchLastSection(True)
    hh.setMinimumSectionSize(MIN_COL // 2)
    table.setAlternatingRowColors(True)
    from PySide6.QtWidgets import QStyledItemDelegate
    from .theme import IndentDelegate
    if type(table.itemDelegate()) is QStyledItemDelegate:
        table.setItemDelegate(IndentDelegate(table))         # indent + bold text of the cells (also for a table that is not shown yet)
    table.setWordWrap(False)                                 # one line per row: the column widths are the user's to set
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    if fit:
        table._fit = _Fit(table, equal)
    if sort:
        sortable(table)


# ----------------------------------------------------------------------------- sorting by a click on the header
import re
from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

ROLE = Qt.UserRole + 7                  # in column 0 of every row: the index the row had when the table was filled (before sorting)


def natural_key(text: str):
    """'2 min 32 s' < '15 min 53 s', 'D160A' < 'D160B', 'DB2' < 'DB10': numbers inside the text compare as numbers."""
    return [(0, float(p.replace(",", "."))) if i % 2 else (1, p) for i, p in enumerate(re.split(r"(\d+(?:[.,]\d+)?)", text.casefold()))]


class SortItem(QTableWidgetItem):
    """A cell that sorts by a key (default: natural order of its text) instead of the plain text."""

    def __init__(self, text: str, key=None):
        super().__init__(text)
        self.key = natural_key(text) if key is None else key

    def __lt__(self, other) -> bool:
        k = getattr(other, "key", None)
        if k is None:
            k = natural_key(other.text())
        try:
            return self.key < k
        except TypeError:
            return str(self.key) < str(k)


@contextmanager
def filling(table: QTableWidget):
    """Fill a sortable table: sorting is off while the rows are written (they would jump around), every row remembers its original
    index (`src`), then the sort chosen by the user (header click) is applied again."""
    table.setSortingEnabled(False)
    try:
        yield
    finally:
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it is not None:
                it.setData(ROLE, r)
        table.setSortingEnabled(True)


def src(table: QTableWidget, row: int) -> int:
    """Index in the caller's list of the item shown in table row `row` (the table may be sorted)."""
    it = table.item(row, 0) if 0 <= row < table.rowCount() else None
    v = it.data(ROLE) if it is not None else None
    return int(v) if v is not None else row


def row_of(table: QTableWidget, idx: int) -> int:
    for r in range(table.rowCount()):
        if src(table, r) == idx:
            return r
    return -1


def sortable(table: QTableWidget) -> None:
    """Header click sorts (indicator shown); no sort until the first click."""
    hh = table.horizontalHeader()
    hh.setSectionsClickable(True)
    hh.setSortIndicatorShown(True)
    table.setSortingEnabled(True)
    hh.setSortIndicator(-1, Qt.AscendingOrder)


def begin_fill(table: QTableWidget) -> None:
    """Call before writing the rows of a sortable table (they would jump around while sorting is on); `end_fill` after it."""
    table.setSortingEnabled(False)


def end_fill(table: QTableWidget) -> None:
    """Every row remembers the index it had when the table was filled (`src`), then the user's sort (header click) is applied again."""
    for r in range(table.rowCount()):
        it = table.item(r, 0)
        if it is not None:
            it.setData(ROLE, r)
    table.setSortingEnabled(True)
