"""Time axis of a chart whose pauses (Stop -> Start of the reading) are cut out or shown as bands of a fixed width (Qt-free).

The data stay on the real chart time (seconds since the connection's start). `GapMap` maps that time to the DISPLAY position `x` of the
chart and back. Two modes, chosen by the width `width` of a pause in display units:

* width = 0: every pause has zero width, the line before it and the line after it meet in one point (the 'junction', where the chart puts
  one Stop / Start mark) and the axis labels jump: ... 20 - 30 | 50 - 60 ... Everything is a shift (no scaling), independent of the zoom.
* width > 0: every pause is a BAND of that width (the chart gives it `gap_px` pixels whatever its duration); the time inside the band is
  mapped proportionally (a marker in a pause stands where it belongs, a click gives the proportional time). The width follows the zoom
  (`fit`): units = pixels * view width / plot width.

    disp(t)  real -> display
    real(x)  display -> real; at a zero-width junction `side="lo"` is the Stop side, `side="hi"` the Start side
"""
from __future__ import annotations

import numpy as np

MIN_GAP = 0.002            # [s] a shorter pause is not a gap


class GapMap:
    def __init__(self, gaps=(), width: float = 0.0):
        g = sorted((float(a), float(b)) for a, b in gaps if float(b) - float(a) > MIN_GAP)
        merged: list[list[float]] = []
        for a, b in g:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.a = np.array([m[0] for m in merged], dtype=float)         # Stop of every pause (real time)
        self.b = np.array([m[1] for m in merged], dtype=float)         # Start after it
        self.n = len(self.a)
        self.g = max(0.0, float(width))                                # display width of one pause (0 = a junction)
        self.L = self.b - self.a
        self.cum = np.concatenate(([0.0], np.cumsum(self.L)))          # cum[k] = total length of the first k pauses
        self.D = self.a - self.cum[:-1] + self.g * np.arange(self.n)   # display position where the band / junction of every pause begins
        self.E = self.D + self.g                                       # ... and ends
        self.j = self.D + self.g / 2                                   # the centre of a band = the junction (axis label)

    def __bool__(self) -> bool:
        return self.n > 0

    def key(self) -> tuple:
        return tuple(zip(self.a.tolist(), self.b.tolist())) + (round(self.g, 9),)

    # ---- real -> display
    def disp(self, t):
        """Display position of the real time `t` (number or array)."""
        if not self.n:
            return t
        ta = np.asarray(t, dtype=float)
        k = np.searchsorted(self.a, ta, side="right")                     # pauses that began at or before t
        prev = np.maximum(k - 1, 0)
        inside = (k > 0) & (ta < self.b[prev])                            # t lies inside the pause `prev`
        outside = ta - self.cum[k] + self.g * k
        within = self.D[prev] + (self.g * (ta - self.a[prev]) / self.L[prev] if self.g > 0 else 0.0)
        out = np.where(inside, within, outside)
        return float(out) if np.ndim(t) == 0 else out

    # ---- display -> real
    def real(self, x, side: str = "lo"):
        """Real time of the display position `x`. At a zero-width junction `side` 'lo' = the Stop side, 'hi' = the Start side."""
        if not self.n:
            return x
        xa = np.asarray(x, dtype=float)
        if self.g <= 0:
            k = np.searchsorted(self.D, xa, side="left" if side == "lo" else "right")
            out = xa + self.cum[k]
        else:
            k = np.searchsorted(self.D, xa, side="left")                  # bands that begin before x
            prev = np.maximum(k - 1, 0)
            inside = (k > 0) & (xa < self.E[prev])
            outside = xa + self.cum[k] - self.g * k
            within = self.a[prev] + (xa - self.D[prev]) / self.g * self.L[prev]
            out = np.where(inside, within, outside)
        return float(out) if np.ndim(x) == 0 else out

    # ---- helpers for the axis and the markers
    def junction_at(self, x: float, tol: float = 1e-9) -> int | None:
        """Index of the pause whose junction / band centre lies at the display position x (None = none)."""
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

    def bands(self, x0: float, x1: float) -> list[int]:
        """Pauses that are (at least partly) between the display positions x0 .. x1."""
        return [i for i in range(self.n) if self.E[i] >= x0 and self.D[i] <= x1]

    def segments(self, x0: float, x1: float) -> list[tuple[float, float]]:
        """Real-time stretches that are visible between the display positions x0 .. x1 outside the pauses."""
        out = []
        pos = x0
        edges = [(float(self.D[i]), float(self.E[i])) for i in range(self.n) if self.E[i] > x0 and self.D[i] < x1]
        for d, e in edges:
            if d > pos:
                out.append((float(self.real(pos, "hi")), float(self.real(d, "lo"))))
            pos = max(pos, e)
        if x1 > pos:
            out.append((float(self.real(pos, "hi")), float(self.real(x1, "lo"))))
        if not edges and not out:
            out.append((float(self.real(x0, "lo")), float(self.real(x1, "lo"))))
        return out

    def fit(self, t0: float, t1: float, px: float, plot_px: float) -> float:
        """Display width of one pause so that it takes `px` pixels on a plot `plot_px` wide that shows the REAL stretch t0 .. t1:
        wv = scanned time in view / (1 - share of the pauses); width = px * wv / plot_px."""
        if not self.n or px <= 0 or plot_px <= 0 or t1 <= t0:
            return 0.0
        ov = np.clip(np.minimum(self.b, t1) - np.maximum(self.a, t0), 0.0, None)      # the real length of every pause inside the view
        s = (t1 - t0) - float(ov.sum())
        c = float((ov / self.L).sum())                                                  # pauses in view, fractions counted
        room = 1.0 - c * px / plot_px
        if room < 0.05:                                                                 # the bands would fill the plot
            room = 0.05
        wv = max(s, 1e-6) / room
        return px * wv / plot_px

    def drop_gap_rows(self, t: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Zero-width pauses only: the samples that sit INSIDE a pause (the NaN rows that keep the old value from being held across it) are
        removed; the first sample after the pause stays, so the line goes straight from the last old value to the first new one. A band keeps
        them: they break the line inside it."""
        if not self.n or not len(t) or self.g > 0:
            return t, v
        keep = np.ones(len(t), dtype=bool)
        for a, b in zip(self.a, self.b):
            lo = int(np.searchsorted(t, a, side="right"))
            hi = int(np.searchsorted(t, b, side="right"))
            if hi > lo:
                nan_row = np.isnan(v[lo:hi]).all(axis=1) if v.ndim == 2 else np.isnan(v[lo:hi])
                keep[lo:hi] = ~nan_row
        return (t, v) if keep.all() else (t[keep], v[keep])


def find_gaps(t, v, min_len: float = 1.0) -> list[tuple[float, float]]:
    """The pauses of a LOADED recording (CSV / database): stretches where every signal is empty (NaN). The acquisition puts such a row right after
    the last sample of a run (+1 ms) and the next real sample comes at the new start, so a pause = (time of the empty row, time of the next
    non-empty row). Stretches shorter than `min_len` s are not pauses (a dropout of one cycle). Returns [(t0, t1)]."""
    import numpy as np
    t = np.asarray(t, float)
    v = np.asarray(v, float)
    if len(t) < 3 or v.ndim != 2 or v.shape[1] == 0:
        return []
    empty = np.isnan(v).all(axis=1)
    out: list[tuple[float, float]] = []
    i, n = 0, len(t)
    while i < n:
        if not empty[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and empty[j + 1]:
            j += 1
        if i > 0 and j + 1 < n and t[j + 1] - t[i] >= min_len:      # (empty rows at the very beginning / end are no pause)
            out.append((float(t[i]), float(t[j + 1])))
        i = j + 1
    return out

