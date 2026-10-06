"""Time axis of a chart whose pauses (Stop -> Start of the reading) are cut out (Qt-free).

The data stay on the real chart time (seconds since the connection's start). `GapMap` maps that time to the DISPLAY position `x` of the
chart and back: every pause (a, b) has zero width on the screen, so the line before it and the line after it meet in one point (the
'junction', where the chart puts one Stop / Start mark) and the axis labels jump: ... 20 - 30 | 50 - 60 ... Everything is a shift
(no scaling), so the mapping does not depend on the zoom.

    disp(t)  real -> display; a time inside a pause lands on its junction
    real(x)  display -> real; the junction itself gives the Stop side (`side="lo"`) or the Start side (`side="hi"`)
"""
from __future__ import annotations

import numpy as np

MIN_GAP = 0.002            # [s] a shorter pause is not a gap


class GapMap:
    def __init__(self, gaps=()):
        g = sorted((float(a), float(b)) for a, b in gaps if float(b) - float(a) > MIN_GAP)
        merged: list[list[float]] = []
        for a, b in g:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.a = np.array([m[0] for m in merged], dtype=float)         # Stop of every pause (real time)
        self.b = np.array([m[1] for m in merged], dtype=float)         # Start after it
        self.cum = np.concatenate(([0.0], np.cumsum(self.b - self.a)))   # cum[k] = total length of the first k pauses
        self.j = self.a - self.cum[:-1]                                  # display position of every junction
        self.n = len(self.a)

    def __bool__(self) -> bool:
        return self.n > 0

    def key(self) -> tuple:
        return tuple(zip(self.a.tolist(), self.b.tolist()))

    # ---- real -> display
    def disp(self, t):
        """Display position of the real time `t` (number or array)."""
        if not self.n:
            return t
        ta = np.asarray(t, dtype=float)
        k = np.searchsorted(self.a, ta, side="right")                     # pauses that began at or before t
        prev = np.maximum(k - 1, 0)
        rest = np.where(k > 0, np.clip(self.b[prev] - ta, 0.0, None), 0.0)   # the part of the pause t is still inside of
        out = ta - (self.cum[k] - rest)
        return float(out) if np.ndim(t) == 0 else out

    # ---- display -> real
    def real(self, x, side: str = "lo"):
        """Real time of the display position `x`. At a junction `side` 'lo' = the Stop side, 'hi' = the Start side."""
        if not self.n:
            return x
        xa = np.asarray(x, dtype=float)
        k = np.searchsorted(self.j, xa, side="left" if side == "lo" else "right")
        out = xa + self.cum[k]
        return float(out) if np.ndim(x) == 0 else out

    # ---- helpers for the axis and the markers
    def junction_at(self, x: float, tol: float = 1e-9) -> int | None:
        """Index of the junction that lies at the display position x (None = none)."""
        if not self.n:
            return None
        i = int(np.argmin(np.abs(self.j - x)))
        return i if abs(self.j[i] - x) <= tol else None

    def in_gap(self, t: float) -> int | None:
        """Index of the pause the real time t lies inside of (None = none)."""
        if not self.n:
            return None
        k = int(np.searchsorted(self.a, t, side="right")) - 1
        return k if k >= 0 and t < self.b[k] else None

    def segments(self, x0: float, x1: float) -> list[tuple[float, float]]:
        """Real-time stretches that are visible between the display positions x0 .. x1 (one per piece between the junctions)."""
        cuts = [float(c) for c in self.j if x0 < c < x1]
        edges = [x0] + cuts + [x1]
        out = []
        for i in range(len(edges) - 1):
            lo = self.real(edges[i], "hi" if i > 0 else "lo")
            hi = self.real(edges[i + 1], "lo")
            out.append((lo, hi))
        return out

    def drop_gap_rows(self, t: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The samples that sit INSIDE a pause (the NaN rows that keep the old value from being held across it) are removed; the first sample
        after the pause stays, so the line goes straight from the last old value to the first new one."""
        if not self.n or not len(t):
            return t, v
        keep = np.ones(len(t), dtype=bool)
        for a, b in zip(self.a, self.b):
            lo = int(np.searchsorted(t, a, side="right"))
            hi = int(np.searchsorted(t, b, side="right"))
            if hi > lo:
                nan_row = np.isnan(v[lo:hi]).all(axis=1) if v.ndim == 2 else np.isnan(v[lo:hi])
                keep[lo:hi] = ~nan_row
        return (t, v) if keep.all() else (t[keep], v[keep])
