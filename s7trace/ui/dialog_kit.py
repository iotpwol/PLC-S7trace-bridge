"""Common frame of the settings windows.

`@dialog_info("Name", "What it is for")` on a QDialog class does two things when the window is first shown:
  * a header strip with the name of the function and a one-sentence description is put on top,
  * the content goes into a scroll area (the buttons at the bottom stay outside it) and the window is made smaller than
    the screen when it would not fit: scroll bars (vertical / horizontal) appear instead of cut-off content."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QLayoutItem, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

SCREEN_FRACTION = (0.96, 0.92)               # largest share of the available screen (width, height) a window may take


class DialogHeader(QFrame):
    """Name of the function and what it is for - the first thing in every settings window."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("dlgHeader")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(2)
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("dlgTitle")
        lay.addWidget(self.lbl_title)
        self.lbl_text = QLabel(text)
        self.lbl_text.setObjectName("dlgText")
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setVisible(bool(text))
        lay.addWidget(self.lbl_text)


def _is_button_row(item: QLayoutItem) -> bool:
    """A horizontal row that holds only buttons (and spacers): the OK / Cancel row at the bottom of a window."""
    lay = item.layout()
    if not isinstance(lay, QHBoxLayout):
        return False
    buttons = 0
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is None:
            if lay.itemAt(i).layout() is not None:
                return False
            continue                                          # a spacer
        if isinstance(w, QPushButton):
            buttons += 1
        elif not isinstance(w, (QCheckBox, QLabel)):
            return False
    return buttons > 0


def prepare_dialog(dlg: QDialog, title: str, text: str = "") -> None:
    lay = dlg.layout()
    if not isinstance(lay, QBoxLayout):                       # an unusual window: only the header, no scrolling
        return
    margins = lay.contentsMargins()
    spacing = lay.spacing()
    footer = None
    if lay.count() and _is_button_row(lay.itemAt(lay.count() - 1)):
        footer = lay.takeAt(lay.count() - 1)
    body = QWidget()
    body_lay = QVBoxLayout(body)
    body_lay.setContentsMargins(margins)
    body_lay.setSpacing(spacing)
    while lay.count():
        stretch = lay.stretch(0)
        it = lay.takeAt(0)
        if it.widget() is not None:
            body_lay.addWidget(it.widget(), stretch)
        elif it.layout() is not None:
            body_lay.addLayout(it.layout(), stretch)
        else:
            body_lay.addItem(it)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(body)
    scroll.viewport().setAutoFillBackground(False)
    body.setAutoFillBackground(False)
    header = DialogHeader(title, text)
    foot = None
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(header)
    lay.addWidget(scroll, 1)
    if footer is not None:
        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(margins.left(), 6, margins.right(), margins.bottom())
        fl.addLayout(footer.layout())
        lay.addWidget(foot)
    dlg._kit = {"header": header, "scroll": scroll, "body": body, "footer": foot}
    fit_to_screen(dlg)


def fit_to_screen(dlg: QDialog) -> None:
    """Large enough for the content, never larger than the screen (the scroll area takes up the difference)."""
    kit = dlg._kit
    screen = (dlg.screen() if dlg.windowHandle() else None) or QGuiApplication.primaryScreen()
    if dlg.parentWidget() is not None and dlg.parentWidget().screen() is not None:
        screen = dlg.parentWidget().screen()
    av = screen.availableGeometry()
    frame = dlg.frameGeometry().size() - dlg.geometry().size()
    chrome_h = kit["header"].sizeHint().height() + (kit["footer"].sizeHint().height() if kit["footer"] else 0)
    hint = kit["body"].sizeHint()
    want = QSize(max(dlg.width(), hint.width() + 4), max(dlg.height(), hint.height() + chrome_h + 4))
    max_w = int(av.width() * SCREEN_FRACTION[0]) - frame.width()
    max_h = int(av.height() * SCREEN_FRACTION[1]) - frame.height()
    size = QSize(max(min(want.width(), max_w), 200), max(min(want.height(), max_h), 150))
    dlg.setMinimumSize(min(dlg.minimumWidth(), size.width()), min(dlg.minimumHeight(), size.height()))
    dlg.resize(size)
    parent = dlg.parentWidget()
    center = parent.window().frameGeometry().center() if parent is not None and parent.window().isVisible() else av.center()
    pos = QPoint(center.x() - (size.width() + frame.width()) // 2, center.y() - (size.height() + frame.height()) // 2)
    pos.setX(max(av.left(), min(pos.x(), av.right() - size.width() - frame.width() + 1)))
    pos.setY(max(av.top(), min(pos.y(), av.bottom() - size.height() - frame.height() + 1)))
    dlg.move(pos)


def dialog_info(title: "str | Callable[[QDialog], str]", text: "str | Callable[[QDialog], str]" = ""):
    """Class decorator: header + scroll area + fit to the screen when the window is first shown."""
    def deco(cls):
        orig = cls.showEvent

        def showEvent(self, e):
            if not getattr(self, "_kit_done", False):
                self._kit_done = True
                prepare_dialog(self, title(self) if callable(title) else title, text(self) if callable(text) else text)
            orig(self, e)
        cls.showEvent = showEvent
        return cls
    return deco
