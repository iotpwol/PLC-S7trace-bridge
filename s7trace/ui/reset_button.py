"""The 'Reset' button: a click clears the chart buffer; holding it turns on 'Auto-Reset' (every Start clears the chart).

Press and hold: after 1 s the label counts down 'Reset (3s)' ... 'Reset (1s)'; at 0 the button latches as 'Auto-Reset' (checked, its look
comes from the theme keys reset_on_bg / reset_on_text). Released before the count-down starts = a click (resetRequested); released during
the count-down = cancelled, nothing happens. While latched a click only switches 'Auto-Reset' off (no reset)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QTimer, Qt, Signal as QtSignal
from PySide6.QtWidgets import QPushButton

HOLD_START_S = 1.0        # the count-down is shown after this long
HOLD_TOTAL_S = 4.0        # Auto-Reset latches after this long


def countdown_label(held: float) -> str:
    """The text for a button held for `held` seconds ('' = the plain 'Reset')."""
    if held < HOLD_START_S:
        return "Reset"
    return f"Reset ({max(math.ceil(HOLD_TOTAL_S - held), 0)}s)"


class ResetButton(QPushButton):
    resetRequested = QtSignal()
    autoChanged = QtSignal(bool)

    def __init__(self, parent=None):
        super().__init__("Reset", parent)
        self.setCheckable(True)
        self._auto = False
        self._t0: float | None = None          # when the hold began
        self._armed_off = False                # pressed while latched: the release switches it off
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self.setToolTip("Reset: czyści bufor i wykres (kliknięcie).\n"
                        "Przytrzymaj 4 s (odliczanie od 1. sekundy), aby załączyć „Auto-Reset” – wykres będzie czyszczony przy każdym Start.\n"
                        "Puszczenie w trakcie odliczania anuluje. Kliknięcie „Auto-Reset” wyłącza go.")
        self.clicked.connect(self._key_click)

    # ---- state
    @property
    def auto(self) -> bool:
        return self._auto

    def set_auto(self, on: bool, emit: bool = False) -> None:
        on = bool(on)
        changed = on != self._auto
        self._auto = on
        self.setChecked(on)
        self._cancel_hold()
        self.setText("Auto-Reset" if on else "Reset")
        if changed and emit:
            self.autoChanged.emit(on)

    def _cancel_hold(self) -> None:
        self._timer.stop()
        self._t0 = None
        self._armed_off = False
        if not self._auto:
            self.setText("Reset")

    # ---- the mouse: all the logic lives here (the default toggling of a checkable button is switched off)
    def nextCheckState(self) -> None:
        pass

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.LeftButton or not self.isEnabled():
            return super().mousePressEvent(e)
        self.setDown(True)
        if self._auto:
            self._armed_off = True
        else:
            self._t0 = time.monotonic()
            self._timer.start()
        e.accept()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(e)
        self.setDown(False)
        inside = self.rect().contains(e.position().toPoint())
        if self._armed_off:                                        # latched: a click switches Auto-Reset off
            self._armed_off = False
            if inside:
                self.set_auto(False, emit=True)
        elif self._t0 is not None:
            held = time.monotonic() - self._t0
            self._cancel_hold()
            if inside and held < HOLD_START_S:                     # a click
                self.resetRequested.emit()
            # held longer: cancelled (the count-down was showing)
        e.accept()

    def _tick(self) -> None:
        if self._t0 is None:
            return
        held = time.monotonic() - self._t0
        if held >= HOLD_TOTAL_S:
            self.set_auto(True, emit=True)
            return
        self.setText(countdown_label(held))

    def _key_click(self, _checked=False) -> None:
        """Space / Enter on the focused button (and click()): the same as a mouse click."""
        if self._auto:
            self.set_auto(False, emit=True)
        else:
            self.resetRequested.emit()
