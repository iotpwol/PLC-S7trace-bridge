"""Qt validators for input fields."""
from __future__ import annotations

from PySide6.QtGui import QValidator

from ..core.netaddr import ACCEPTABLE, INVALID, ipv4_state


class Ipv4Validator(QValidator):
    """Blocks wrong characters while typing: digits, dots, optional ':port' (IPv4 only)."""

    def validate(self, text: str, pos: int):
        st = ipv4_state(text)
        state = {INVALID: QValidator.Invalid, ACCEPTABLE: QValidator.Acceptable}.get(st, QValidator.Intermediate)
        return state, text, pos
