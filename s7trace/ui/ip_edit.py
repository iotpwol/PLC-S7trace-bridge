"""IP address field: shows the dots with spaces ("10 . 12 . 91 . 1") for readability, but text() stays "10.12.91.1"."""
from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from .validators import Ipv4Validator


class IpEdit(QLineEdit):
    """All other code keeps using text() / setText() with the plain address (optionally ':port'); only the display is
    spaced. Typing a '.' adds the spaces by itself, Backspace over a space removes the dot as well."""

    MAX_SHOWN = 33                                   # "255 . 255 . 255 . 255:65535"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setValidator(Ipv4Validator(self))
        self.setMaxLength(self.MAX_SHOWN)
        self._prev = ""
        self.textEdited.connect(self._reformat)

    @staticmethod
    def spaced(raw: str) -> str:
        return raw.replace(".", " . ")

    def text(self) -> str:                           # plain address for every consumer
        return super().text().replace(" ", "")

    def setText(self, text: str) -> None:
        super().setText(self.spaced(text.replace(" ", "")))
        self._prev = super().text()

    def _reformat(self, shown: str) -> None:
        raw = shown.replace(" ", "")
        n = len(shown[:self.cursorPosition()].replace(" ", ""))          # characters before the cursor
        if len(shown) < len(self._prev) and raw == self._prev.replace(" ", "") and n > 0:
            raw = raw[:n - 1] + raw[n:]                                   # only a space was deleted: take the dot too
            n -= 1
        want = self.spaced(raw)
        if want != shown:
            super().setText(want)
            i, count = 0, 0
            while i < len(want) and count < n:
                if want[i] != " ":
                    count += 1
                i += 1
            if i > 0 and want[i - 1] == "." and i < len(want) and want[i] == " ":
                i += 1                                                    # after a typed dot: behind its trailing space
            self.setCursorPosition(i)
        self._prev = want
