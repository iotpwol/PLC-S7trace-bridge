"""Main trace plot + overview strip + markers (pyqtgraph)."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, Signal as QtSignal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from ..core import render
from .fold_splitter import FoldSplitter
from ..core.buffer import TraceBuffer
from ..core.types import Signal

pg.setConfigOptions(antialias=False, background="k", foreground="#d0d0d0")


MIN_WINDOW = 0.1          # [s] the narrowest time window (mouse wheel stops here)
LANE_PAD = 0.08           # empty margin inside a lane, as a fraction of the lane height


class TimeAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        dec = 0
        if spacing and spacing < 1:
            dec = min(6, int(math.ceil(-math.log10(spacing))))      # sub-second ticks need decimals
        big = max((abs(v) for v in values), default=0) >= 3600
        out = []
        for v in values:
            v = round(v, dec)
            if big:
                whole = int(math.floor(v))
                sec = whole % 60 + (v - whole)
                width = dec + 3 if dec else 2
                out.append(f"{whole // 3600}:{(whole % 3600) // 60:02d}:{sec:0{width}.{dec}f}")
            else:
                out.append(f"{v:.{dec}f}s")
        return out


class LaneAxis(pg.AxisItem):
    """Left axis. In lane mode the labels (MIN / intermediate / MAX of every signal) are drawn in the colour of the
    lane they belong to; `lanes` = [(y_bottom, y_top, colour)] in view coordinates (0 = bottom, 1 = top)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.lanes: list[tuple[float, float, str]] = []

    def drawPicture(self, p, axisSpec, tickSpecs, textSpecs):
        if not self.lanes:
            return super().drawPicture(p, axisSpec, tickSpecs, textSpecs)
        p.setRenderHint(p.RenderHint.Antialiasing, False)
        p.setRenderHint(p.RenderHint.TextAntialiasing, True)
        pen, p1, p2 = axisSpec
        p.setPen(pen)
        p.drawLine(p1, p2)
        for pen, p1, p2 in tickSpecs:
            p.setPen(pen)
            p.drawLine(p1, p2)
        if self.style["tickFont"] is not None:
            p.setFont(self.style["tickFont"])
        p.setClipRect(self.boundingRect().toAlignedRect())
        h = max(self.height(), 1.0)
        for rect, flags, text in textSpecs:
            v = 1.0 - rect.center().y() / h
            lane = min(self.lanes, key=lambda ln: abs(v - (ln[0] + ln[1]) / 2))
            p.setPen(QPen(QColor(lane[2])))
            p.drawText(rect, int(flags), text)


LEGEND_MARGIN = 12


class DraggableLegend(pg.LegendItem):
    """Legend that can be dragged with the mouse; `on_moved(fx, fy)` reports the drop position
    as fractions (0..1) of the free room inside the chart."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.on_moved = None

    def mouseDragEvent(self, ev):
        super().mouseDragEvent(ev)
        if ev.isFinish() and self.on_moved and self.parentItem() is not None:
            r = self.parentItem().boundingRect()
            w, h = max(r.width() - self.boundingRect().width(), 1), max(r.height() - self.boundingRect().height(), 1)
            self.on_moved(min(max(self.pos().x() / w, 0.0), 1.0), min(max(self.pos().y() / h, 0.0), 1.0))


class PlotView(QWidget):
    windowChanged = QtSignal(float)    # user zoomed -> new visible width [s]
    userMoved = QtSignal()             # user panned/zoomed (tab pauses the live view)
    legendMoved = QtSignal(float, float)    # legend dropped at (fx, fy)
    legendDoubleClicked = QtSignal()        # -> the 'Sygnały…' window
    legendContextMenu = QtSignal(object)    # right click on the legend (global QPoint) -> the tab shows the menu
    splitChanged = QtSignal(int)       # height of the overview strip changed (pixels)

    def __init__(self, buffer: TraceBuffer, parent=None):
        super().__init__(parent)
        self.buffer = buffer
        self.signals: list[Signal] = []
        self.time_source: Callable[[], float] | None = None
        self.follow = False
        self.window = 200.0
        self.auto_y = True
        self.y_range = (0.0, 10.0)
        self.show_points = False
        self._x = (0.0, 200.0)
        self._dirty = True
        self._last_version = -1
        self._ov_version = -1
        self._ov_tick = 0
        self._busy = False
        self.gui_lag_ms = 0.0
        self.trigger_lines: list[pg.InfiniteLine] = []
        self.vmarks: list[pg.InfiniteLine] = []
        self.hmarks: list[pg.InfiniteLine] = []
        self.v_mode = False
        self.h_mode = False
        self.legend_pos = (0.0, 0.0)
        self._ov_want: int | None = None
        self.y_layout = "lanes"                     # "lanes" (Share) / "offset" (Offset Y + Gain)
        self._lane_geo: dict[int, tuple[float, float]] = {}
        self._lane_info: dict[int, tuple] = {}      # signal index -> (y_bottom, y_top, lo, hi, name) of the last redraw
        self._lane_ticks: list = []
        self._lane_lines: list[pg.InfiniteLine] = []

        self.glw = pg.GraphicsLayoutWidget()          # main chart
        self.glw_ov = pg.GraphicsLayoutWidget()       # overview strip (own widget -> draggable splitter)
        self.glw_ov.setMinimumHeight(48)
        self.split = FoldSplitter(Qt.Vertical, 1, 100)       # button / double click on the bar folds the overview down
        self.split.addWidget(self.glw)
        self.split.addWidget(self.glw_ov)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.split.setSizes([10000, 100])
        self.split.splitterMoved.connect(lambda *_: self.splitChanged.emit(self.overview_height()))
        self.split.foldChanged.connect(lambda *_: self.splitChanged.emit(self.overview_height()))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.split)

        self.axis_y = LaneAxis("left")
        self.plot = self.glw.addPlot(row=0, col=0, axisItems={"bottom": TimeAxis("bottom"), "left": self.axis_y})
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Czas")
        self._axis_labels()
        self.plot.hideButtons()
        self.vb = self.plot.getViewBox()
        self.vb.setMenuEnabled(False)
        self.vb.setMouseEnabled(x=True, y=False)
        self.vb.setLimits(minXRange=MIN_WINDOW)      # the wheel cannot zoom below 0.1 s
        self.vb.disableAutoRange()
        self.vb.sigRangeChangedManually.connect(self._on_manual_range)

        self.ov = self.glw_ov.addPlot(row=0, col=0, axisItems={"bottom": TimeAxis("bottom")})
        self.ov.setMenuEnabled(False)
        self.ov.getAxis("left").setWidth(48)
        self.ov.getAxis("left").setStyle(showValues=False)
        self.ov.hideButtons()
        self.ov.setMouseEnabled(x=False, y=False)
        self.ov.vb.disableAutoRange()
        self.ov.vb.setMouseEnabled(x=False, y=False)
        self.region = pg.LinearRegionItem(values=(0, 200), brush=pg.mkBrush(110, 100, 0, 150),
                                          pen=pg.mkPen("#b0a000"))
        self.region.setZValue(10)
        self.ov.addItem(self.region)
        self.region.sigRegionChanged.connect(self._on_region)

        self.legend = DraggableLegend(offset=(LEGEND_MARGIN, LEGEND_MARGIN), labelTextColor="#e8e8e8")
        self.legend.setParentItem(self.vb)
        self.legend.on_moved = self._legend_dropped
        self.legend.sigDoubleClicked.connect(lambda *_: self.legendDoubleClicked.emit())   # -> 'Sygnały…'
        self.legend.setBrush(pg.mkBrush(0, 0, 0, 170))
        self.legend.setPen(pg.mkPen("#b0b0b0"))
        self.curves: list[pg.PlotDataItem] = []
        self.points: list[pg.PlotDataItem] = []
        self.ov_curves: list[pg.PlotDataItem] = []

        self.readout = QLabel(self.glw)
        self.readout.setStyleSheet("background: rgba(0,0,0,170); color: #e8e8e8; border: 1px solid #666;"
                                   " padding: 4px; font-family: Consolas, monospace;")
        self.readout.hide()
        self.plot.scene().sigMouseClicked.connect(self._on_click)

    # ------------------------------------------------------------ config
    def set_signals(self, signals: list[Signal]) -> None:
        self.signals = signals
        for c in self.curves + self.points:
            self.plot.removeItem(c)
        for c in self.ov_curves:
            self.ov.removeItem(c)
        self.legend.clear()
        self.curves, self.points, self.ov_curves = [], [], []
        for s in signals:
            c = pg.PlotDataItem(pen=pg.mkPen(s.color, width=1), connect="finite")
            p = pg.PlotDataItem(pen=None, symbol="o", symbolSize=4, symbolBrush=s.color,
                                symbolPen=None)
            o = pg.PlotDataItem(pen=pg.mkPen(s.color, width=1), connect="finite")
            self.plot.addItem(c)
            self.plot.addItem(p)
            self.ov.addItem(o)
            self.curves.append(c)
            self.points.append(p)
            self.ov_curves.append(o)
        self._rebuild_legend()
        self._layout_lanes()
        self._ov_version = -1
        self._dirty = True

    def _rebuild_legend(self) -> None:
        self.legend.clear()
        for c, s in zip(self.curves, self.signals):
            if s.plot:
                self.legend.addItem(c, s.name)

    # ------------------------------------------------ layout (saved in the UI settings)
    def overview_height(self) -> int:
        return self.split.sizes()[1]

    def set_overview_height(self, px: int) -> None:
        self.split.saved = int(px)
        if self.split.collapsed:                          # remembered; used when the strip is shown again
            return
        self._ov_want = int(px)
        self._fit_overview()

    def set_overview_collapsed(self, on: bool) -> None:
        self._ov_want = None
        self.split.set_collapsed(on)

    def _fit_overview(self) -> None:
        total = self.height()
        if self.split.collapsed or self._ov_want is None or total < 200:          # not laid out yet -> apply on the first resize
            return
        px = max(48, min(self._ov_want, total - 100))
        self.split.blockSignals(True)
        self.split.setSizes([total - px, px])
        self.split.blockSignals(False)
        self._ov_want = None

    def set_legend_pos(self, fx: float, fy: float) -> None:
        """(0,0) top-left ... (1,1) bottom-right; anything in between = freely dragged."""
        fx, fy = min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0)
        self.legend_pos = (fx, fy)
        m = LEGEND_MARGIN
        self.legend.anchor(itemPos=(fx, fy), parentPos=(fx, fy), offset=(m * (1 - 2 * fx), m * (1 - 2 * fy)))

    def _legend_dropped(self, fx: float, fy: float) -> None:
        self.set_legend_pos(fx, fy)
        self.legendMoved.emit(fx, fy)

    def apply_theme(self, bg: str, fg: str) -> None:
        """Chart colours from the 'Interfejs' settings."""
        self.glw.setBackground(bg)
        self.glw_ov.setBackground(bg)
        pen = pg.mkPen(fg)
        for pl in (self.plot, self.ov):
            for ax in ("left", "bottom"):
                a = pl.getAxis(ax)
                a.setPen(pen)
                a.setTextPen(pen)
        self.plot.setLabel("bottom", "Czas")
        self._axis_labels()
        c = QColor(bg)
        c.setAlpha(170)
        self.legend.setBrush(pg.mkBrush(c))
        self.legend.setPen(pen)
        self.legend.setLabelTextColor(fg)
        self.readout.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},200); color: {fg};"
                                   f" border: 1px solid {fg}; padding: 4px; font-family: Consolas, monospace;")

    def set_follow(self, on: bool) -> None:
        self.follow = on
        self._dirty = True

    def set_window(self, sec: float) -> None:
        sec = max(MIN_WINDOW, sec)
        if not self.follow:
            x1 = self._x[1]
            self._x = (x1 - sec, x1)
        self.window = sec
        self._dirty = True

    def set_view(self, x0: float, x1: float) -> None:
        self._x = (x0, x1)
        self.window = max(x1 - x0, MIN_WINDOW)
        self._dirty = True

    def view_range(self) -> tuple[float, float]:
        return self._x

    def set_auto_y(self, on: bool) -> None:
        self.auto_y = on
        self._update_mouse()
        self._dirty = True

    def _update_mouse(self) -> None:
        self.vb.setMouseEnabled(x=True, y=(self.y_layout == "offset" and not self.auto_y))

    def set_y_layout(self, mode: str) -> None:
        self.y_layout = "offset" if mode == "offset" else "lanes"
        self._update_mouse()
        self._axis_labels()
        self._layout_lanes()
        self._lane_ticks = []
        self._ov_version = -1
        self._dirty = True

    def _axis_labels(self) -> None:
        lanes = getattr(self, "y_layout", "lanes") == "lanes"
        self.plot.setLabel("left", "Sygnały" if lanes else "Offset")
        self.axis_y.setWidth(70 if lanes else 52)
        if not lanes:
            self.axis_y.lanes = []
            self.axis_y.setTicks(None)

    # ------------------------------------------------------------ lanes (Share)
    def _plotted(self) -> list[int]:
        return [k for k, s in enumerate(self.signals) if s.plot and k < len(self.curves)]

    def _layout_lanes(self) -> None:
        """Bands of the Y axis: top to bottom in signal order, heights proportional to Share."""
        for ln in self._lane_lines:
            self.plot.removeItem(ln)
        self._lane_lines = []
        self._lane_geo = {}
        self._lane_ticks = []
        ks = self._plotted()
        total = sum(max(self.signals[k].share, 1e-6) for k in ks)
        y = 1.0
        for i, k in enumerate(ks):
            h = max(self.signals[k].share, 1e-6) / total
            self._lane_geo[k] = (y - h, y)
            y -= h
            if self.y_layout == "lanes" and i < len(ks) - 1:
                ln = pg.InfiniteLine(pos=y, angle=0, movable=False, pen=pg.mkPen(128, 128, 128, 70, style=Qt.DotLine))
                self.plot.addItem(ln, ignoreBounds=True)
                self._lane_lines.append(ln)

    def lane_geometry(self) -> dict[int, tuple[float, float]]:
        return dict(self._lane_geo)

    def _lane_xf(self, k: int, vals: np.ndarray) -> tuple[float, float, float, float, bool]:
        """(effective gain, effective offset, lo, hi, constant) mapping raw values of signal k into its lane;
        lo/hi = MIN / MAX of the gain-scaled `vals` (BOOL: 0 and gain)."""
        s = self.signals[k]
        b, t = self._lane_geo[k]
        pad = (t - b) * LANE_PAD
        b2, t2 = b + pad, t - pad
        fin = vals[np.isfinite(vals)] * s.gain
        if s.dtype == "BOOL":
            lo, hi = sorted((0.0, s.gain if s.gain else 1.0))
        elif len(fin):
            lo, hi = float(fin.min()), float(fin.max())
        else:
            lo, hi = 0.0, 1.0
        const = hi - lo <= 1e-12 * max(1.0, abs(lo), abs(hi))
        if const:
            lo, hi = lo - 0.5, hi + 0.5
        sc = (t2 - b2) / (hi - lo)
        return s.gain * sc, b2 - lo * sc, lo, hi, const

    @staticmethod
    def _fmt(v: float) -> str:
        return f"{v:.5g}"

    def _lane_labels(self, k: int, lo: float, hi: float, const: bool, px: float) -> list[tuple[float, str]]:
        """Axis labels of one lane: MIN and MAX, plus intermediate values when the lane is tall enough."""
        b, t = self._lane_geo[k]
        pad = (t - b) * LANE_PAD
        b2, t2 = b + pad, t - pad
        lane_px = (t - b) * px
        if const:
            return [((b2 + t2) / 2, self._fmt((lo + hi) / 2))] if lane_px >= 14 else []
        fr = [0.0, 1.0] if lane_px >= 26 else []
        if self.signals[k].dtype != "BOOL":
            if lane_px >= 140:
                fr = [0.0, 0.25, 0.5, 0.75, 1.0]
            elif lane_px >= 70:
                fr = [0.0, 0.5, 1.0]
        return [(b2 + f * (t2 - b2), self._fmt(lo + f * (hi - lo))) for f in fr]

    def set_y_range(self, lo: float, hi: float) -> None:
        self.y_range = (lo, hi)
        self._dirty = True

    def set_points(self, on: bool) -> None:
        self.show_points = on
        self._dirty = True

    def set_legend_visible(self, on: bool) -> None:
        self.legend.setVisible(on)

    def set_grid(self, on: bool) -> None:
        self.plot.showGrid(x=on, y=on, alpha=0.25)

    def touch(self) -> None:
        self._dirty = True

    def fit_all(self) -> None:
        if len(self.buffer):
            a, b = self.buffer.first_time(), self.buffer.last_time()
            self.set_view(a, b if b > a else a + 1)

    # ----------------------------------------------------------- events
    def clamp_view(self, x0: float, x1: float) -> tuple[float, float]:
        """The view dragged / zoomed by the user stays inside the collected data: it cannot go past the newest
        sample, before the oldest one, or become wider than everything that was collected."""
        if len(self.buffer) == 0:
            return x0, x1
        a, b = self.buffer.first_time(), self.buffer.last_time()
        w = min(max(x1 - x0, MIN_WINDOW), max(b - a, MIN_WINDOW))
        if x1 > b:
            x0, x1 = b - w, b
        if x0 < a:
            x0, x1 = a, a + w
        return x0, x0 + w

    def _on_manual_range(self, *_):
        if self._busy:
            return
        (x0, x1), (y0, y1) = self.vb.viewRange()
        x0, x1 = self.clamp_view(x0, x1)
        self._x = (x0, x1)
        self.window = x1 - x0
        if not self.auto_y and self.y_layout == "offset":
            self.y_range = (y0, y1)
        self.userMoved.emit()
        self.windowChanged.emit(self.window)
        self._dirty = True

    def _on_region(self):
        if self._busy:
            return
        x0, x1 = self.region.getRegion()
        if x1 - x0 < MIN_WINDOW:
            return
        r0, r1 = x0, x1
        x0, x1 = self.clamp_view(x0, x1)
        if abs(x0 - r0) > 1e-9 or abs(x1 - r1) > 1e-9:         # the yellow window cannot leave the data either
            self._busy = True
            try:
                self.region.setRegion((x0, x1))
            finally:
                self._busy = False
        self._x = (x0, x1)
        self.window = x1 - x0
        self.userMoved.emit()
        self.windowChanged.emit(self.window)
        self._dirty = True

    def _on_click(self, ev):
        if (ev.button() == Qt.RightButton and self.legend.isVisible()
                and self.legend.sceneBoundingRect().contains(ev.scenePos())):
            ev.accept()
            self.legendContextMenu.emit(ev.screenPos().toPoint())
            return
        if ev.button() != Qt.LeftButton or ev.double() or ev.isAccepted():
            return
        if not (self.v_mode or self.h_mode):
            return
        pos = ev.scenePos()
        if not self.vb.sceneBoundingRect().contains(pos):
            return
        pt = self.vb.mapSceneToView(pos)
        if self.v_mode:
            self._add_marker(self.vmarks, pt.x(), 90)
        if self.h_mode:
            self._add_marker(self.hmarks, pt.y(), 0)
        ev.accept()
        self.update_readout()

    def _add_marker(self, lst: list, pos: float, angle: int) -> None:
        if len(lst) >= 2:
            old = lst.pop(0)
            self.plot.removeItem(old)
        col = "#ffffff" if angle == 90 else "#ffd24a"
        n = len(lst) + 1
        line = pg.InfiniteLine(pos=pos, angle=angle, movable=True,
                               pen=pg.mkPen(col, width=1, style=Qt.DashLine),
                               label=("V" if angle == 90 else "H") + str(n),
                               labelOpts={"color": col, "position": 0.96 if angle == 90 else 0.05})
        line.sigPositionChanged.connect(self.update_readout)
        self.plot.addItem(line, ignoreBounds=True)
        lst.append(line)

    def set_v_mode(self, on: bool) -> None:
        self.v_mode = on
        if not on:
            for m in self.vmarks:
                self.plot.removeItem(m)
            self.vmarks.clear()
        self.update_readout()

    def set_h_mode(self, on: bool) -> None:
        self.h_mode = on
        if not on:
            for m in self.hmarks:
                self.plot.removeItem(m)
            self.hmarks.clear()
        self.update_readout()

    def mark_trigger(self, t: float) -> None:
        for ln in self.trigger_lines:
            self.plot.removeItem(ln)
        ln = pg.InfiniteLine(pos=t, angle=90, movable=False,
                             pen=pg.mkPen("#ff4040", width=1, style=Qt.DotLine),
                             label="TRIG", labelOpts={"color": "#ff6060", "position": 0.92})
        self.plot.addItem(ln, ignoreBounds=True)
        self.trigger_lines = [ln]

    def clear_trigger_marks(self) -> None:
        for ln in self.trigger_lines:
            self.plot.removeItem(ln)
        self.trigger_lines = []

    def update_readout(self, *_):
        lines = []
        for i, m in enumerate(self.vmarks, 1):
            t = m.value()
            ts, vs = self.buffer.snapshot(t, t)
            vals = ""
            if len(ts):
                j = int(np.clip(np.searchsorted(ts, t, "right") - 1, 0, len(ts) - 1))
                vals = "  " + "  ".join(f"{s.name}={vs[j, k]:g}" for k, s in enumerate(self.signals)
                                        if k < vs.shape[1])
            lines.append(f"V{i}: t={t:.3f} s{vals}")
        if len(self.vmarks) == 2:
            dt = self.vmarks[1].value() - self.vmarks[0].value()
            f = f"  ({1 / abs(dt):.3f} Hz)" if dt else ""
            lines.append(f"Δt = {dt:.3f} s{f}")
        if self.y_layout == "lanes":
            hv = [self._lane_value(m.value()) for m in self.hmarks]
            for i, h in enumerate(hv, 1):
                lines.append(f"H{i}: {h[0]} = {h[1]:.5g}" if h else f"H{i}: (poza pasmem sygnału)")
            if len(hv) == 2 and hv[0] and hv[1] and hv[0][0] == hv[1][0]:
                lines.append(f"ΔY = {hv[1][1] - hv[0][1]:.5g}")
        else:
            for i, m in enumerate(self.hmarks, 1):
                lines.append(f"H{i}: y={m.value():.3f}")
            if len(self.hmarks) == 2:
                lines.append(f"ΔY = {self.hmarks[1].value() - self.hmarks[0].value():.3f}")
        if lines:
            self.readout.setText("\n".join(lines))
            self.readout.adjustSize()
            self._place_readout()
            self.readout.show()
        else:
            self.readout.hide()

    def _lane_value(self, y: float):
        """(signal name, value) under the height y of the lane layout, None outside every lane."""
        for k, (b, t, lo, hi, name) in self._lane_info.items():
            if b <= y <= t and t > b:
                return name, lo + (y - b) / (t - b) * (hi - lo)
        return None

    def _place_readout(self):
        self.readout.move(max(self.glw.width() - self.readout.width() - 16, 60), 10)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_overview()
        if self.readout.isVisible():
            self._place_readout()

    # ----------------------------------------------------------- redraw
    def refresh(self, force: bool = False) -> None:
        import time
        ver = self.buffer.version
        if not (force or self._dirty or (self.follow and ver != self._last_version)):
            return
        t_start = time.perf_counter()
        self._busy = True
        try:
            self._redraw(ver)
        finally:
            self._busy = False
        self._dirty = False
        self._last_version = ver
        self.gui_lag_ms = (time.perf_counter() - t_start) * 1000.0

    def _inner(self, k: int) -> tuple[float, float]:
        b, t = self._lane_geo[k]
        pad = (t - b) * LANE_PAD
        return b + pad, t - pad

    def _redraw(self, ver: int) -> None:
        if self.follow:
            now = self.time_source() if self.time_source else self.buffer.last_time()
            self._x = (now - self.window, now)
        x0, x1 = self._x
        t, v = self.buffer.snapshot(x0, x1)
        lanes = self.y_layout == "lanes"
        vis = (t >= x0) & (t <= x1) if len(t) else None
        if vis is not None and not vis.any():
            vis = None
        px = max(self.vb.height(), 1.0)
        lo = hi = None
        ticks, lane_cols, info = [], [], {}
        for k, s in enumerate(self.signals):
            if k >= len(self.curves):
                break
            if not s.plot or len(t) == 0 or k >= v.shape[1]:
                self.curves[k].setData([], [])
                self.points[k].setData([], [])
                continue
            g, off = s.gain, s.offset_y
            if lanes and k in self._lane_geo:
                g, off, llo, lhi, const = self._lane_xf(k, v[:, k] if vis is None else v[vis, k])
                b2, t2 = self._inner(k)
                info[k] = (b2, t2, llo, lhi, s.name)
                ticks += self._lane_labels(k, llo, lhi, const, px)
            x_end = x1 if (self.follow and x1 > t[-1]) else None
            xs, ys = render.curve_data(t, v[:, k], g, off, x_end)
            self.curves[k].setData(xs, ys, connect="finite")
            if self.show_points and len(t) <= 4000:
                m = (t >= x0) & (t <= x1)
                self.points[k].setData(t[m], v[m, k] * g + off)
            else:
                self.points[k].setData([], [])
            fin = ys[np.isfinite(ys)]
            if len(fin):
                lo = fin.min() if lo is None else min(lo, fin.min())
                hi = fin.max() if hi is None else max(hi, fin.max())
        self.vb.setXRange(x0, x1, padding=0)
        if lanes:
            self._lane_info = info
            self.axis_y.lanes = [(*self._lane_geo[k], self.signals[k].color) for k in self._lane_geo]
            if ticks != self._lane_ticks:
                self._lane_ticks = ticks
                self.axis_y.setTicks([ticks])
            self.vb.setYRange(0.0, 1.0, padding=0)
        elif self.auto_y:
            if lo is None:
                lo, hi = 0.0, 1.0
            pad = max((hi - lo) * 0.06, 0.3)
            self.vb.setYRange(lo - pad, hi + pad, padding=0)
        else:
            self.vb.setYRange(*self.y_range, padding=0)
        self._update_overview(x0, x1, ver)

    def _update_overview(self, x0: float, x1: float, ver: int) -> None:
        if len(self.buffer) == 0:
            self.ov.vb.setXRange(x0, x1, padding=0)
            self.region.setRegion((x0, x1))
            return
        a, b = self.buffer.first_time(), self.buffer.last_time()
        lo_x, hi_x = min(a, x0), max(b, x1)
        self._ov_tick += 1
        if ver != self._ov_version and (self._ov_tick % 15 == 0 or self._ov_version == -1 or not self.follow):
            t, v = self.buffer.snapshot()
            lanes = self.y_layout == "lanes"
            lo = hi = None
            for k, s in enumerate(self.signals):
                if k >= len(self.ov_curves) or k >= v.shape[1]:
                    break
                if not s.plot:
                    self.ov_curves[k].setData([], [])
                    continue
                g, off = s.gain, s.offset_y
                if lanes and k in self._lane_geo:
                    g, off = self._lane_xf(k, v[:, k])[:2]
                xs, ys = render.curve_data(t, v[:, k], g, off, None, max_points=2000)
                self.ov_curves[k].setData(xs, ys, connect="finite")
                fin = ys[np.isfinite(ys)]
                if len(fin):
                    lo = fin.min() if lo is None else min(lo, fin.min())
                    hi = fin.max() if hi is None else max(hi, fin.max())
            if lanes:
                self.ov.vb.setYRange(0.0, 1.0, padding=0)
            elif lo is not None:
                pad = max((hi - lo) * 0.08, 0.2)
                self.ov.vb.setYRange(lo - pad, hi + pad, padding=0)
            self._ov_version = ver
        self.ov.vb.setXRange(lo_x, hi_x, padding=0)
        self.region.setRegion((x0, x1))
