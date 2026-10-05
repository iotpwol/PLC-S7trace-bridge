"""Help mode ('?' button): every dialog gets the system '?' button next to the close button (the main window has its own '?' in the
menu bar, Shift+F1 too). While the mode is on, the element under the mouse - window, button, field, column / row name, table cell -
shows a bubble: what it is, what it is for, how to set it and the range (`core/help_texts.py`; elements without a text of their own
get the tooltip they already have or a general description). Esc or the '?' again ends the mode."""
from __future__ import annotations

import html

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QFormLayout, QGroupBox, QHeaderView, QLabel, QLineEdit, QTabBar, QTableView, QToolTip,
                               QWidget)

from ..core.help_texts import generic, lookup

_INSTANCE: "HelpMode | None" = None


def instance() -> "HelpMode":
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = HelpMode()
    return _INSTANCE


def install(app: QApplication) -> "HelpMode":
    h = instance()
    if not getattr(h, "_installed", False):
        app.installEventFilter(h)
        h._installed = True
    return h


def _rich(text: str) -> str:
    lines = []
    for ln in text.split("\n"):
        k, sep, rest = ln.partition(": ")
        lines.append(f"<b>{html.escape(k)}:</b> {html.escape(rest)}" if sep and len(k) < 24 else html.escape(ln))
    return "<div style='white-space:normal; max-width:420px'>" + "<br>".join(lines) + "</div>"


def is_bubble(w: QWidget) -> bool:
    """The tooltip window itself (the bubble can end up under the cursor): describing it would put the bubble text into a new bubble,
    which doubled on every poll and hung the program."""
    return bool(w.window().windowFlags() & Qt.ToolTip == Qt.ToolTip) or w.window().metaObject().className() == "QTipLabel"


def caption_of(w: QWidget) -> str:
    if isinstance(w, QGroupBox):
        return w.title()
    if isinstance(w, (QAbstractButton, QLabel)):
        return w.text() if not isinstance(w, QLabel) or not w.pixmap() else ""
    return ""


def _form_label(w: QWidget) -> str:
    """The caption of the form row the field `w` stands in (QFormLayout label)."""
    p = w.parentWidget()
    while p is not None:
        lay = p.layout()
        if isinstance(lay, QFormLayout):
            probe = w
            while probe is not None and probe is not p:
                lab = lay.labelForField(probe)
                if lab is not None and hasattr(lab, "text"):
                    return lab.text()
                probe = probe.parentWidget()
        p = p.parentWidget()
    return ""


def help_for(w: QWidget, gpos: QPoint) -> str:
    """The bubble text for the widget under the mouse ('' = nothing to show)."""
    if w is None or is_bubble(w):
        return ""
    explicit = w.property("help")
    if explicit:
        return str(explicit)
    if isinstance(w, QTabBar):
        i = w.tabAt(w.mapFromGlobal(gpos))
        if i >= 0:
            return lookup(w.tabText(i)) or generic("tab", w.tabText(i))
    if isinstance(w, QHeaderView):
        i = w.logicalIndexAt(w.mapFromGlobal(gpos))
        model = w.model()
        if i >= 0 and model is not None:
            cap = str(model.headerData(i, w.orientation()) or "")
            if w.orientation() == Qt.Horizontal:
                return lookup(cap) or str(model.headerData(i, w.orientation(), Qt.ToolTipRole) or "") or generic("header", cap)
            return f"Wiersz {cap}: jeden element listy (np. sygnał). Wartości wiersza edytujesz w komórkach po prawej; dymek nad komórką opisuje jej kolumnę."
    # a cell (or a widget in a cell) of a table: described by its column
    p = w
    while p is not None:
        if isinstance(p, QAbstractItemView) or (p.parentWidget() is not None and isinstance(p.parentWidget(), QAbstractItemView)):
            view = p if isinstance(p, QAbstractItemView) else p.parentWidget()
            if isinstance(view, QTableView) or hasattr(view, "horizontalHeader"):
                try:
                    idx = view.indexAt(view.viewport().mapFromGlobal(gpos))
                    if idx.isValid():
                        cap = str(view.model().headerData(idx.column(), Qt.Horizontal) or "")
                        tip = lookup(cap)
                        if tip:
                            return tip
                except Exception:
                    pass
            break
        p = p.parentWidget()
    # the widget itself, then its form label, then its parents
    probe, depth = w, 0
    while probe is not None and depth < 5:
        cap = caption_of(probe) or _form_label(probe)
        if cap:
            t = lookup(cap)
            if t:
                return t
        tip = probe.toolTip()
        if tip and not isinstance(probe, (QDialog,)):
            plain = html.unescape(tip)
            return "Opis: " + plain.replace("<br>", "\n")
        if isinstance(probe, QDialog):
            return lookup(probe.windowTitle()) or f"Okno „{probe.windowTitle()}”.\nNajedź kursorem na przyciski, pola i nazwy kolumn, aby zobaczyć ich opis. Naciśnij „?” albo Esc, aby zakończyć."
        probe, depth = probe.parentWidget(), depth + 1
    kind = ("button" if isinstance(w, QAbstractButton) else "combo" if isinstance(w, QComboBox) else "spin" if isinstance(w, QAbstractSpinBox)
            else "edit" if isinstance(w, QLineEdit) else "label")
    return generic(kind, caption_of(w) or _form_label(w))


class HelpMode(QObject):
    modeChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.active = False
        self._last = (None, "")
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._poll)

    def set_active(self, on: bool) -> None:
        if on == self.active:
            return
        self.active = on
        if on:
            QApplication.setOverrideCursor(Qt.WhatsThisCursor)
            self._timer.start()
        else:
            self._timer.stop()
            QApplication.restoreOverrideCursor()
            QToolTip.hideText()
            self._last = (None, "")
        self.modeChanged.emit(on)

    def toggle(self) -> None:
        self.set_active(not self.active)

    def _poll(self) -> None:
        pos = QCursor.pos()
        w = QApplication.widgetAt(pos)
        if w is not None and is_bubble(w):                       # the cursor is over the bubble: keep it as it is
            return
        text = help_for(w, pos) if w is not None else ""
        key = (id(w), text, pos.x() // 24, pos.y() // 12)
        if key == self._last:
            return
        self._last = key
        if text:
            QToolTip.showText(pos + QPoint(14, 18), _rich(text), w)
        else:
            QToolTip.hideText()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.EnterWhatsThisMode:                       # the system '?' button of a dialog
            self.toggle()
            return True
        if t == QEvent.Polish and isinstance(obj, QDialog) and not isinstance(obj, QFileDialog):
            if not obj.windowFlags() & Qt.WindowContextHelpButtonHint and not obj.windowFlags() & Qt.WindowMinMaxButtonsHint:
                obj.setWindowFlag(Qt.WindowContextHelpButtonHint, True)
            return False
        if self.active:
            if t == QEvent.ToolTip:                              # our bubble replaces the ordinary tooltips
                return True
            if t == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
                self.set_active(False)
                return True
        return False
