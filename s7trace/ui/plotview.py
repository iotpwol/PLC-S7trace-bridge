"""Main trace plot + overview strip + markers (pyqtgraph)."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, Signal as QtSignal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..core import render
from ..core.buffer import TraceBuffer
from ..core.types import Signal

pg.setConfigOptions(antialias=False, background="k", foreground="#d0d0d0")


class TimeAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        out = []
        big = max((abs(v) for v in values), default=0) >= 3600
        for v in values:
            if big:
                s = int(round(v))
                out.append(f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}")
            else:
                out.append(f"{v:g}s")
        return out


class PlotView(QWidget):
    windowChanged = QtSignal(float)    # user zoomed -> new visible width [s]
    userMoved = QtSignal()             # user panned/zoomed (tab pauses the live view)

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

        self.glw = pg.GraphicsLayoutWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.glw)

        self.plot = self.glw.addPlot(row=0, col=0, axisItems={"bottom": TimeAxis("bottom")})
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("left", "Value")
        self.plot.setLabel("bottom", "Time")
        self.plot.getAxis("left").setWidth(48)
        self.plot.hideButtons()
        self.vb = self.plot.getViewBox()
        self.vb.setMenuEnabled(False)
        self.vb.setMouseEnabled(x=True, y=False)
        self.vb.disableAutoRange()
        self.vb.sigRangeChangedManually.connect(self._on_manual_range)

        self.ov = self.glw.addPlot(row=1, col=0, axisItems={"bottom": TimeAxis("bottom")})
        self.ov.setMenuEnabled(False)
        self.ov.setFixedHeight(70)
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

        self.legend = self.plot.addLegend(offset=(12, 12), labelTextColor="#e8e8e8")
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
            c = pg.PlotDataItem(pen=pg.mkPen(s.color, width=1), connect="finite", name=s.name)
            p = pg.PlotDataItem(pen=None, symbol="o", symbolSize=4, symbolBrush=s.color,
                                symbolPen=None)
            o = pg.PlotDataItem(pen=pg.mkPen(s.color, width=1), connect="finite")
            self.plot.addItem(c)
            self.plot.addItem(p)
            self.ov.addItem(o)
            self.curves.append(c)
            self.points.append(p)
            self.ov_curves.append(o)
        self._ov_version = -1
        self._dirty = True

    def set_follow(self, on: bool) -> None:
        self.follow = on
        self._dirty = True

    def set_window(self, sec: float) -> None:
        sec = max(0.05, sec)
        if not self.follow:
            x1 = self._x[1]
            self._x = (x1 - sec, x1)
        self.window = sec
        self._dirty = True

    def set_view(self, x0: float, x1: float) -> None:
        self._x = (x0, x1)
        self.window = max(x1 - x0, 0.05)
        self._dirty = True

    def view_range(self) -> tuple[float, float]:
        return self._x

    def set_auto_y(self, on: bool) -> None:
        self.auto_y = on
        self.vb.setMouseEnabled(x=True, y=not on)
        self._dirty = True

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
    def _on_manual_range(self, *_):
        if self._busy:
            return
        (x0, x1), (y0, y1) = self.vb.viewRange()
        self._x = (x0, x1)
        self.window = x1 - x0
        if not self.auto_y:
            self.y_range = (y0, y1)
        self.userMoved.emit()
        self.windowChanged.emit(self.window)
        self._dirty = True

    def _on_region(self):
        if self._busy:
            return
        x0, x1 = self.region.getRegion()
        if x1 - x0 < 0.05:
            return
        self._x = (x0, x1)
        self.window = x1 - x0
        self.userMoved.emit()
        self.windowChanged.emit(self.window)
        self._dirty = True

    def _on_click(self, ev):
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

    def _place_readout(self):
        self.readout.move(max(self.glw.width() - self.readout.width() - 16, 60), 10)

    def resizeEvent(self, e):
        super().resizeEvent(e)
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

    def _redraw(self, ver: int) -> None:
        if self.follow:
            now = self.time_source() if self.time_source else self.buffer.last_time()
            self._x = (now - self.window, now)
        x0, x1 = self._x
        t, v = self.buffer.snapshot(x0, x1)
        lo = hi = None
        for k, s in enumerate(self.signals):
            if k >= len(self.curves):
                break
            if len(t) == 0 or k >= v.shape[1]:
                self.curves[k].setData([], [])
                self.points[k].setData([], [])
                continue
            x_end = x1 if (self.follow and x1 > t[-1]) else None
            xs, ys = render.curve_data(t, v[:, k], s.gain, s.offset_y, x_end)
            self.curves[k].setData(xs, ys, connect="finite")
            if self.show_points and len(t) <= 4000:
                m = (t >= x0) & (t <= x1)
                self.points[k].setData(t[m], v[m, k] * s.gain + s.offset_y)
            else:
                self.points[k].setData([], [])
            fin = ys[np.isfinite(ys)]
            if len(fin):
                lo = fin.min() if lo is None else min(lo, fin.min())
                hi = fin.max() if hi is None else max(hi, fin.max())
        self.vb.setXRange(x0, x1, padding=0)
        if self.auto_y:
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
            lo = hi = None
            for k, s in enumerate(self.signals):
                if k >= len(self.ov_curves) or k >= v.shape[1]:
                    break
                xs, ys = render.curve_data(t, v[:, k], s.gain, s.offset_y, None, max_points=2000)
                self.ov_curves[k].setData(xs, ys, connect="finite")
                fin = ys[np.isfinite(ys)]
                if len(fin):
                    lo = fin.min() if lo is None else min(lo, fin.min())
                    hi = fin.max() if hi is None else max(hi, fin.max())
            if lo is not None:
                pad = max((hi - lo) * 0.08, 0.2)
                self.ov.vb.setYRange(lo - pad, hi + pad, padding=0)
            self._ov_version = ver
        self.ov.vb.setXRange(lo_x, hi_x, padding=0)
        self.region.setRegion((x0, x1))
