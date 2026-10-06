"""Main trace plot + overview strip + markers (pyqtgraph)."""
from __future__ import annotations

import math
import time
from typing import Callable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal as QtSignal
from PySide6.QtGui import QColor, QCursor, QFontMetricsF, QPen
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsTextItem, QLabel, QSplitter, QToolTip, QVBoxLayout, QWidget

from ..core import marker_look, render, render_cfg
from ..core.markers import SPAN_KINDS
from ..core.types import legend_text
from .fold_splitter import FoldSplitter
from ..core.buffer import TraceBuffer
from ..core.types import Signal

pg.setConfigOptions(antialias=False, background="k", foreground="#d0d0d0")


MIN_WINDOW = 0.1          # [s] the narrowest time window (mouse wheel stops here)
LANE_PAD = 0.08           # empty margin inside a lane, as a fraction of the lane height


NICE_SPACING = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800,
                3600, 7200, 10800, 21600, 43200, 86400]          # [s] steps of the clock-like time axis


class TimeAxis(pg.AxisItem):
    """Bottom axis. mode 'rel': seconds from the start (the label is x + shift); 'app' / 'plc': a clock HH:MM:SS.mmm where `shift`
    is the epoch time of x = 0 on that clock; the ticks then fall on whole clock seconds / minutes and only as many parts
    of the time are written as the zoom needs (see core.types.axis_shift)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.mode = "rel"
        self.shift = 0.0

    def set_clock(self, mode: str, shift: float) -> None:
        if (mode, shift) != (self.mode, self.shift):
            self.mode, self.shift = mode, shift
            self.picture = None
            self.update()

    def tickValues(self, minVal, maxVal, size):
        if self.mode == "rel" and not self.shift:
            return super().tickValues(minVal, maxVal, size)
        span = maxVal - minVal
        if size <= 0 or span <= 0:
            return []
        sp = next((n for n in NICE_SPACING if span / n <= max(size / 120.0, 1.0)), NICE_SPACING[-1])
        tz = time.localtime(self.shift + minVal).tm_gmtoff if self.mode != "rel" else 0       # whole local hours / minutes
        first = math.ceil((minVal + self.shift + tz) / sp)
        last = math.floor((maxVal + self.shift + tz) / sp)
        return [(sp, [k * sp - self.shift - tz for k in range(first, min(last, first + 400) + 1)])]

    def tickStrings(self, values, scale, spacing):
        if self.mode != "rel":
            out = []
            for v in values:
                ms = int(round((v + self.shift) * 1000))
                lt = time.localtime(ms // 1000)
                if spacing and spacing >= 60:
                    out.append(f"{lt.tm_hour:02d}:{lt.tm_min:02d}")
                elif spacing and spacing >= 1:
                    out.append(f"{lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}")
                else:
                    out.append(f"{lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}.{ms % 1000:03d}")
            return out
        if self.shift:
            values = [v + self.shift for v in values]
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


class AxisTitle(QGraphicsTextItem):
    """The title of an axis ('Sygnały', 'Czas'). It needs no room of its own: it is drawn BEHIND the tick numbers of the axis (the numbers
    cover it, not the other way round) and can be dragged along the axis with the mouse."""

    def __init__(self, text: str, axis, vertical: bool):
        super().__init__(text, axis)
        self.axis, self.vertical = axis, vertical
        self.frac = 0.5                                            # position along the axis (0..1)
        self.setFlag(QGraphicsItem.ItemStacksBehindParent, True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.SizeVerCursor if vertical else Qt.SizeHorCursor)
        self.setToolTip("Przeciągnij, aby przesunąć opis osi (liczby osi zasłaniają go).")
        if vertical:
            self.setRotation(-90)
        axis.geometryChanged.connect(self.place)
        self.place()

    def set_text(self, text: str) -> None:
        if self.toPlainText() != text:
            self.setPlainText(text)
            self.place()

    def set_color(self, color) -> None:
        self.setDefaultTextColor(QColor(color))

    def _rect(self) -> QRectF:
        """The axis band itself (pyqtgraph's boundingRect() of an axis with a grid reaches over the whole plot)."""
        return QRectF(QPointF(0.0, 0.0), self.axis.size())

    def place(self, *_) -> None:
        r, tb = self._rect(), self.boundingRect()
        if self.vertical:                                          # text rotated by -90: it runs upwards from its position
            c = min(max(self.frac * r.height(), tb.width() / 2), max(r.height() - tb.width() / 2, tb.width() / 2))
            self.setPos(r.left() + 1, r.top() + c + tb.width() / 2)
        else:
            c = min(max(self.frac * r.width(), tb.width() / 2), max(r.width() - tb.width() / 2, tb.width() / 2))
            self.setPos(r.left() + c - tb.width() / 2, r.top() + max((r.height() - tb.height()) / 2, 0.0))

    def mousePressEvent(self, ev) -> None:
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        r = self._rect()
        p = self.axis.mapFromScene(ev.scenePos())
        length = r.height() if self.vertical else r.width()
        if length > 0:
            self.frac = min(max((p.y() - r.top() if self.vertical else p.x() - r.left()) / length, 0.0), 1.0)
            self.place()
        ev.accept()


class LaneAxis(pg.AxisItem):
    """Left axis. In lane mode the labels (MIN / intermediate / MAX of every signal) are drawn in the colour of the
    lane they belong to; `lanes` = [(y_bottom, y_top, colour)] in view coordinates (0 = bottom, 1 = top)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.lanes: list[tuple[float, float, str]] = []
        self.labels: list[tuple[float, str, float, str, str]] = []   # (y, text, anchor y, 'min' / 'max' / 'mid', colour)

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
        # The labels are placed here, not by pyqtgraph (it drops / shifts overlapping ones): the MIN label sits on the lower edge of
        # its lane, the MAX label on the upper edge, so the numbers of neighbouring lanes never run into each other.
        fm = QFontMetricsF(self.style["tickFont"] or p.font())
        th = fm.height()
        xs = [min(a.x(), b.x()) for _pen, a, b in tickSpecs]
        xr = (min(xs) if xs else self.width() - 8) - 3
        for y, text, anchor, kind, colour in self.labels:
            if kind == "min":
                top = (1.0 - anchor) * h - th
            elif kind == "max":
                top = (1.0 - anchor) * h
            else:
                top = (1.0 - y) * h - th / 2
            top = min(max(top, 0.0), max(h - th, 0.0))
            p.setPen(QPen(QColor(colour)))
            p.drawText(QRectF(0.0, top, xr, th), int(Qt.AlignRight | Qt.AlignVCenter), text)


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


class _MarkerRegion(pg.LinearRegionItem):
    """Area of a range marker: dragging it moves the whole range, its edges change the ends; a click is reported (right = menu)."""
    sigRegionClicked = QtSignal(object)

    def mouseClickEvent(self, ev):
        self.sigRegionClicked.emit(ev)
        super().mouseClickEvent(ev)


class PlotView(QWidget):
    windowChanged = QtSignal(float)    # user zoomed -> new visible width [s]
    userMoved = QtSignal()             # user panned/zoomed (tab pauses the live view)
    legendMoved = QtSignal(float, float)    # legend dropped at (fx, fy)
    legendDoubleClicked = QtSignal()        # -> the 'Sygnały…' window
    legendContextMenu = QtSignal(object)    # right click on the legend (global QPoint) -> the tab shows the menu
    splitChanged = QtSignal(int)       # height of the overview strip changed (pixels)
    markerRequested = QtSignal(float, object)   # right click on the empty chart: (time [s], global QPoint) -> 'Dodaj znacznik'
    markerMenu = QtSignal(int, object)          # right click on a marker line: (marker id, global QPoint)
    markerMoved = QtSignal(int, float, float)   # a marker was dragged: (marker id, new start [s], new end [s] (= start for a point))
    markerPlaced = QtSignal(int, float)         # 'Zmień pozycję': the chart was clicked: (marker id, time [s])
    markerOpened = QtSignal(int)                # left click on a marker line: (marker id) -> the tab shows its description
    markerEdit = QtSignal(int)                  # double click on a marker: (marker id) -> the edit window
    ghostMoved = QtSignal(float)                # the ghost of a Start REC was dropped at this time [s]
    ghostMenu = QtSignal(object)                # right click on the ghost (global QPoint)

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
        self.points_hidden = False                       # 'Punkty' is on but there are too many samples in the window to draw
        self.rcfg = dict(render_cfg.DEFAULTS)            # Ustawienia -> Renderowanie wykresu
        self._ov_last = 0.0
        self._x = (0.0, 200.0)
        self._dirty = True
        self._last_version = -1
        self._ov_version = -1
        self._ov_tick = 0
        self._busy = False
        self.gui_lag_ms = 0.0
        self.trigger_lines: list[pg.InfiniteLine] = []
        self.hmarks: list[pg.InfiniteLine] = []
        self._delta_items: list = []                       # overlay of 'Różnica sygnału' markers (levels + the difference)
        self.mitems: dict[int, dict] = {}                 # bookmarks (core.markers) drawn in the visible range
        self.mlook = dict(marker_look.DEFAULTS)           # line widths of the markers (Znaczniki -> Wygląd znaczników)
        self.mhi: set[int] = set()                        # markers drawn highlighted (the one being moved / a whole group)
        self._tip_id: int | None = None                   # marker whose bubble is shown
        self.place_marker: int | None = None              # waiting for a click that gives the new place of this marker
        self._mset = False
        self.ghost: pg.InfiniteLine | None = None         # the twin of a Start REC that is being moved (pulses)
        self._ghost_on = False
        self._ghost_timer = QTimer(self)
        self._ghost_timer.setInterval(380)
        self._ghost_timer.timeout.connect(self._ghost_pulse)
        self.h_mode = False
        self.ctx_y = 0.0
        self.mmovable: set[int] = set()                   # markers unlocked for dragging (right click -> Zmień pozycję znacznika)
        self.legend_pos = (0.0, 0.0)
        self.legend_mode = "name"                      # "name" / "address": what the legend shows
        self.legend_tip = None                         # callable(signal index) -> bubble text of the signal under the cursor
        self._legend_idx: list[int] = []               # signal index of every legend row
        self.legend_style = "legend"                   # "legend" (box in a corner) / "labels" (a name beside every signal)
        self._legend_on = True                         # the View -> Legend switch (shared by both styles)
        self.tags: list[pg.TextItem] = []              # the 'labels' style: one box with the signal name per plotted signal
        self._tag_idx: list[int] = []
        self._tag_y: dict[int, float] = {}             # offset layout: view y where the tag of a signal stands
        self._tag_look = (QColor(0, 0, 0, 170), QColor("#b0b0b0"))
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
        self.title_y = AxisTitle("Sygnały", self.axis_y, True)          # the axis titles take no space of their own
        self.title_x = AxisTitle("Czas", self.plot.getAxis("bottom"), False)
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
        self.ov.getAxis("left").setWidth(62)
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
        self.vb.sigResized.connect(lambda *_: self._place_tags())
        self.curves: list[pg.PlotDataItem] = []
        self.points: list[pg.PlotDataItem] = []
        self.ov_curves: list[pg.PlotDataItem] = []

        self.readout = QLabel(self.glw)
        self.readout.setStyleSheet("background: rgba(0,0,0,170); color: #e8e8e8; border: 1px solid #666;"
                                   " padding: 4px; font-family: Consolas, monospace;")
        self.readout.hide()
        self.plot.scene().sigMouseClicked.connect(self._on_click)
        self.plot.scene().sigMouseMoved.connect(self._on_hover)

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
            p = pg.PlotDataItem(pen=None, symbol="o", symbolSize=self.rcfg["point_size"], symbolBrush=s.color,
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
        self._legend_idx = []
        for t in self.tags:
            t.setParentItem(None)
            if t.scene() is not None:
                t.scene().removeItem(t)
        self.tags, self._tag_idx = [], []
        for i, (c, s) in enumerate(zip(self.curves, self.signals)):
            if s.plot:
                self.legend.addItem(c, legend_text(s, self.legend_mode))
                self._legend_idx.append(i)
                tag = pg.TextItem(legend_text(s, self.legend_mode), color=s.color, anchor=(0, 0.5))
                tag.setParentItem(self.vb)
                tag.setZValue(50)
                self._style_tag(tag)
                self.tags.append(tag)
                self._tag_idx.append(i)
        self._apply_legend_vis()
        self._place_tags()

    def set_legend_mode(self, mode: str) -> None:
        self.legend_mode = "address" if mode == "address" else "name"
        self._rebuild_legend()

    def set_legend_style(self, style: str) -> None:
        """'legend' = one box in a corner, 'labels' = a name in a translucent box beside every signal (right of the Y axis)."""
        self.legend_style = "labels" if style == "labels" else "legend"
        self._apply_legend_vis()
        self._place_tags()

    def _apply_legend_vis(self) -> None:
        self.legend.setVisible(self._legend_on and self.legend_style == "legend")
        for t in self.tags:
            t.setVisible(self._legend_on and self.legend_style == "labels")

    def _style_tag(self, tag: pg.TextItem) -> None:
        bg, fg = self._tag_look
        tag.fill = pg.mkBrush(bg)
        tag.border = pg.mkPen(fg)
        tag.update()

    def _tags_shown(self) -> bool:
        return self._legend_on and self.legend_style == "labels" and bool(self.tags)

    def _place_tags(self) -> None:
        """Every name stands at the middle of its lane (offset layout: at its curve), just right of the vertical axis."""
        if not self._tags_shown():
            return
        pos = []
        for k in self._tag_idx:
            if self.y_layout == "lanes" and k in self._lane_geo:
                b, t = self._lane_geo[k]
                yv = (b + t) / 2
            else:
                yv = self._tag_y.get(k)
            pos.append(None if yv is None else self.vb.mapFromView(QPointF(0.0, yv)).y())
        for tag, p in zip(self.tags, pos):
            tag.setVisible(p is not None)
        shown = [(p, tag) for p, tag in zip(pos, self.tags) if p is not None]
        if self.y_layout != "lanes":                       # curves may be close together: push the names apart
            shown.sort(key=lambda x: x[0])
            ps = [p for p, _ in shown]
            hs = [tag.boundingRect().height() + 2 for _, tag in shown]
            top, bottom = 0.0, float(self.vb.height())
            for i in range(len(ps)):                       # downwards: no overlap, not above the top edge
                ps[i] = max(ps[i], top + hs[i] / 2 if i == 0 else ps[i - 1] + (hs[i - 1] + hs[i]) / 2)
            for i in range(len(ps) - 1, -1, -1):           # upwards: back inside the plot when the stack ran over the bottom
                lim = bottom - hs[i] / 2 if i == len(ps) - 1 else ps[i + 1] - (hs[i + 1] + hs[i]) / 2
                ps[i] = min(ps[i], lim)
            shown = [(p, tag) for p, (_, tag) in zip(ps, shown)]
        for p, tag in shown:
            tag.setPos(6.0, p)

    def _tag_row_at(self, pos):
        """Signal index of the name label under the scene position (None = none)."""
        if not self._tags_shown():
            return None
        for tag, k in zip(self.tags, self._tag_idx):
            if tag.isVisible() and tag.sceneBoundingRect().contains(pos):
                return k
        return None

    def _legend_row_at(self, pos):
        """Index of the signal whose legend row (or name label) is under the scene position (None = none)."""
        k = self._tag_row_at(pos)
        if k is not None:
            return k
        if not self.legend.isVisible():
            return None
        for k, (sample, label) in enumerate(self.legend.items):
            if k < len(self._legend_idx) and sample.sceneBoundingRect().united(label.sceneBoundingRect()).contains(pos):
                return self._legend_idx[k]
        return None

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
        self.title_x.set_color(fg)
        self.title_y.set_color(fg)
        self._axis_labels()
        c = QColor(bg)
        c.setAlpha(170)
        self.legend.setBrush(pg.mkBrush(c))
        self.legend.setPen(pen)
        self.legend.setLabelTextColor(fg)
        self._tag_look = (c, QColor(fg))
        for tag in self.tags:
            self._style_tag(tag)
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
        self.title_y.set_text("Sygnały" if lanes else "Offset")
        self.axis_y.setWidth(62)                                  # just the numbers (the same as the overview strip below)
        if not lanes:
            self.axis_y.lanes = []
            self.axis_y.labels = []
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
        if self.mitems:                                       # bookmarks of chosen plots follow the lanes
            self._marker_extras()
            self._marker_style()
        self._place_tags()

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

    def _lane_labels(self, k: int, lo: float, hi: float, const: bool, px: float) -> list[tuple[float, str, float, str, str]]:
        """Axis labels of one lane: MIN and MAX, plus intermediate values when the lane is tall enough.
        (y of the value, text, y where the label is anchored, 'min' / 'max' / 'mid', lane colour)."""
        b, t = self._lane_geo[k]
        pad = (t - b) * LANE_PAD
        b2, t2 = b + pad, t - pad
        lane_px = (t - b) * px
        col = self.signals[k].color
        if const:
            return [((b2 + t2) / 2, self._fmt((lo + hi) / 2), (b2 + t2) / 2, "mid", col)] if lane_px >= 14 else []
        fr = [0.0, 1.0] if lane_px >= 26 else []
        if self.signals[k].dtype != "BOOL":
            if lane_px >= 140:
                fr = [0.0, 0.25, 0.5, 0.75, 1.0]
            elif lane_px >= 70:
                fr = [0.0, 0.5, 1.0]
        out = []
        for f in fr:
            y = b2 + f * (t2 - b2)
            kind, anchor = ("min", b) if f == 0.0 else ("max", t) if f == 1.0 else ("mid", y)
            out.append((y, self._fmt(lo + f * (hi - lo)), anchor, kind, col))
        return out

    def set_y_range(self, lo: float, hi: float) -> None:
        self.y_range = (lo, hi)
        self._dirty = True

    def apply_render(self, cfg: dict) -> None:
        """Rendering settings (point limits, curve resolution, overview interval, antialiasing, point size)."""
        self.rcfg = render_cfg.normalize(cfg)
        for p in self.points:
            p.setSymbolSize(self.rcfg["point_size"])
        for c in self.curves + self.ov_curves:
            c.opts["antialias"] = self.rcfg["antialias"]
            c.curve.opts["antialias"] = self.rcfg["antialias"]
            c.curve.update()
        self._ov_version = -1                            # the overview is rebuilt with the new resolution
        self._dirty = True

    def set_points(self, on: bool) -> None:
        self.show_points = on
        self._dirty = True

    def set_legend_visible(self, on: bool) -> None:
        self._legend_on = bool(on)
        self._apply_legend_vis()
        self._place_tags()

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

    def _legend_click(self, ev) -> bool:
        """A click on the legend or on a name label: its menu (right button) / the signal list (double click). True = handled.
        It is asked before the markers: a marker area under the legend must not take the click away from it."""
        on_legend = self.legend.isVisible() and self.legend.sceneBoundingRect().contains(ev.scenePos())
        if ev.button() == Qt.RightButton and on_legend:
            ev.accept()
            self.legendContextMenu.emit(ev.screenPos().toPoint())
            return True
        if self._tag_row_at(ev.scenePos()) is not None:           # a name label: the same menu / double click as the legend
            if ev.button() == Qt.RightButton:
                ev.accept()
                self.legendContextMenu.emit(ev.screenPos().toPoint())
                return True
            if ev.button() == Qt.LeftButton and ev.double():
                ev.accept()
                self.legendDoubleClicked.emit()
                return True
        return False

    def _on_click(self, ev):
        if self._legend_click(ev):
            return
        if self.place_marker is not None:
            mid = self.place_marker
            if ev.button() == Qt.LeftButton and self.vb.sceneBoundingRect().contains(ev.scenePos()):
                x = float(self.vb.mapSceneToView(ev.scenePos()).x())
                self.end_marker_placement()
                ev.accept()
                self.markerPlaced.emit(mid, x)
            elif ev.button() == Qt.RightButton:
                self.end_marker_placement()
                ev.accept()
            return
        if ev.isAccepted():
            return
        if ev.button() == Qt.RightButton and self.vb.sceneBoundingRect().contains(ev.scenePos()):
            ev.accept()
            self.ctx_y = float(self.vb.mapSceneToView(ev.scenePos()).y())          # height of the click: which plot a level marker is for
            self.markerRequested.emit(float(self.vb.mapSceneToView(ev.scenePos()).x()), ev.screenPos().toPoint())
            return
        if ev.button() != Qt.LeftButton or ev.double():
            return
        if not self.h_mode:
            return
        pos = ev.scenePos()
        if not self.vb.sceneBoundingRect().contains(pos):
            return
        pt = self.vb.mapSceneToView(pos)
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

    def set_h_mode(self, on: bool) -> None:
        self.h_mode = on
        if not on:
            for m in self.hmarks:
                self.plot.removeItem(m)
            self.hmarks.clear()
        self.update_readout()

    # ------------------------------------------------------------ bookmarks
    LINE_STYLES = {"solid": Qt.SolidLine, "dash": Qt.DashLine, "dot": Qt.DotLine, "dashdot": Qt.DashDotLine}

    def set_time_axis(self, mode: str, shift: float) -> None:
        """Labels of the time axes (chart and overview): see TimeAxis / core.types.axis_shift."""
        for ax in (self.plot.getAxis("bottom"), self.ov.getAxis("bottom")):
            ax.set_clock(mode, shift)

    def set_marker_movable(self, mid: int, on: bool) -> None:
        """A marker can be dragged only while it is unlocked, so a drag that starts on a marker pans the chart instead."""
        (self.mmovable.add if on else self.mmovable.discard)(mid)
        cur = self.mitems.get(mid)
        if cur is not None:
            cur["main"].setMovable(on)

    def set_markers(self, items: list[dict]) -> None:
        """items = dicts: id, kind ('point' / 'range'), x0, x1 (time [s]; x1 only for a range), color '#rrggbb', width [px],
        style ('solid' / 'dash' / 'dot' / 'dashdot'), opacity [%] of the area of a range, title, tip (html), signals (names;
        empty = all plots). Markers that are not listed any more are removed, the others
        are updated in place (rebuilt when their look changes)."""
        want = {it["id"]: it for it in items}
        for mid in [m for m in self.mitems if m not in want]:
            self._marker_remove(mid)
        self._mset = True
        try:
            for it in items:
                mid = it["id"]
                cur = self.mitems.get(mid)
                look = (it["kind"], it["color"], it["width"], it["style"], it["opacity"], it["title"], tuple(it["signals"]), it.get("title2", ""))
                if cur is not None and cur["look"] != look:
                    self._marker_remove(mid)
                    cur = None
                if cur is None:
                    cur = self._marker_create(it, look)
                    self.mitems[mid] = cur
                else:
                    main = cur["main"]
                    moving = getattr(main, "moving", False) or any(getattr(l, "moving", False) for l in getattr(main, "lines", []))
                    if not moving:
                        if it["kind"] in SPAN_KINDS:
                            if tuple(main.getRegion()) != (it["x0"], it["x1"]):
                                main.setRegion((it["x0"], it["x1"]))
                        elif abs(main.value() - it["x0"]) > 1e-9:
                            main.setValue(it["x0"])
                cur["data"] = it
                cur["main"].setToolTip(it["tip"])
            self._marker_extras()
            self._marker_style()
            self._delta_overlay()
        finally:
            self._mset = False

    def set_marker_look(self, cfg: dict) -> None:
        """Line widths of the markers (settings); the markers are rebuilt with the new look."""
        self.mlook = marker_look.normalize(cfg)
        for mid in list(self.mitems):
            self._marker_remove(mid)

    def _width(self, it: dict, case: str) -> int:
        """Line width [px] of a marker: its own width (> 0) or the setting of the case: 'all' / 'sel' / 'other' / 'hover'."""
        own = int(it["width"] or 0)
        if case == "hover":
            return max(self.mlook["width_hover"], own + 1)
        if case == "other":
            return self.mlook["width_other"]
        return own or self.mlook["width_all" if case == "all" else "width_sel"]

    def _marker_pen(self, it: dict, hi: bool = False):
        restricted = bool(it["signals"]) and self.y_layout == "lanes"       # the full-height line is only a thin guide then
        col = QColor("#ffffff" if hi else it["color"])
        if restricted and not hi:
            col.setAlpha(120)
        style = Qt.SolidLine if hi else self.LINE_STYLES.get(it["style"], Qt.SolidLine)
        w = self._width(it, "hover") if hi else self._width(it, "other" if restricted else "all")
        return pg.mkPen(col, width=w, style=style)

    def _hover_pen(self, it: dict):
        """The line under the mouse: the marker's own colour, thicker (the same for points and the edges of a range)."""
        return pg.mkPen(QColor(it["color"]), width=self._width(it, "hover"), style=self.LINE_STYLES.get(it["style"], Qt.SolidLine))

    def _marker_create(self, it: dict, look: tuple) -> dict:
        mid, col = it["id"], it["color"]
        text = (it["title"] or "").strip()
        text = (text[:28] + "…") if len(text) > 29 else text
        restricted = bool(it["signals"])
        label_opts = {"color": col, "position": 0.985, "rotateAxis": (1, 0), "anchors": [(1, 1), (1, 1)]}
        if it.get("passive"):                                        # only a translucent area (REC between Start and Stop): no edges, no clicks
            main = pg.LinearRegionItem(values=(it["x0"], it["x1"]), brush=pg.mkBrush(self._range_fill(it)), pen=pg.mkPen(None), movable=False)
            main.setZValue(5)
            main.setAcceptedMouseButtons(Qt.NoButton)
            for ln in main.lines:
                ln.setAcceptedMouseButtons(Qt.NoButton)
                ln.setVisible(False)
            self.plot.addItem(main, ignoreBounds=True)
            return {"look": look, "main": main, "label": None, "extras": [], "data": it}
        if it["kind"] in SPAN_KINDS:
            fill = self._range_fill(it)
            main = _MarkerRegion(values=(it["x0"], it["x1"]), brush=pg.mkBrush(fill), pen=self._marker_pen(it),
                                 hoverBrush=pg.mkBrush(fill), movable=mid in self.mmovable)
            main.setZValue(7)
            main.sigRegionChangeFinished.connect(lambda r, i=mid: self._marker_dropped(i, r))
            main.sigRegionClicked.connect(lambda ev, i=mid: self._marker_clicked(i, ev))
            for ln in main.lines:
                ln.sigClicked.connect(lambda l, ev, i=mid: self._marker_clicked(i, ev))
                ln.setHoverPen(self._hover_pen(it))
            label = pg.InfLineLabel(main.lines[0], text, position=0.985, color=col, rotateAxis=(1, 0), anchors=[(1, 1), (1, 1)])
            if it.get("title2"):                                     # a named second edge (Manual Stop REC)
                t2 = it["title2"]
                pg.InfLineLabel(main.lines[1], (t2[:28] + "…") if len(t2) > 29 else t2, position=0.985, color=col, rotateAxis=(1, 0),
                                anchors=[(1, 1), (1, 1)])
            self.plot.addItem(main, ignoreBounds=True)
        else:
            main = pg.InfiniteLine(pos=it["x0"], angle=90, movable=mid in self.mmovable, pen=self._marker_pen(it),
                                   hoverPen=self._hover_pen(it), label=text, labelOpts=label_opts)
            main.setZValue(8)
            main.sigPositionChangeFinished.connect(lambda l, i=mid: self._marker_dropped(i, l))
            main.sigClicked.connect(lambda l, ev, i=mid: self._marker_clicked(i, ev))
            label = main.label
            self.plot.addItem(main, ignoreBounds=True)
        return {"look": look, "main": main, "label": label, "extras": [], "data": it}

    def _marker_remove(self, mid: int) -> None:
        cur = self.mitems.pop(mid, None)
        if cur is None:
            return
        for e in cur["extras"]:
            self.plot.removeItem(e)
        self.plot.removeItem(cur["main"])

    def _marker_extras(self) -> None:
        """Markers that belong to chosen plots only: a coloured area / bar in exactly those lanes (lane layout)."""
        for cur in self.mitems.values():
            for e in cur["extras"]:
                self.plot.removeItem(e)
            cur["extras"] = []
            it = cur["data"]
            if not it["signals"] or self.y_layout != "lanes":
                continue
            col = QColor(it["color"])
            for k, (b, t) in self._lane_geo.items():
                if k >= len(self.signals) or self.signals[k].name not in it["signals"]:
                    continue
                if it["kind"] in SPAN_KINDS:
                    r = pg.QtWidgets.QGraphicsRectItem(it["x0"], b, it["x1"] - it["x0"], t - b)
                    fill = QColor(col)
                    fill.setAlpha(self._alpha(it))
                    r.setBrush(pg.mkBrush(fill))
                    r.setPen(pg.mkPen(None))
                    r.setZValue(6)
                    r.setAcceptedMouseButtons(Qt.NoButton)
                    self.plot.addItem(r, ignoreBounds=True)
                    cur["extras"].append(r)
                pen = pg.mkPen(col, width=self._width(it, "sel"), style=self.LINE_STYLES.get(it["style"], Qt.SolidLine))
                for x in ((it["x0"], it["x1"]) if it["kind"] in SPAN_KINDS else (it["x0"],)):     # a bar (edges of a range) in the lane
                    seg = pg.PlotCurveItem([x, x], [b, t], pen=pen)
                    seg.setZValue(7)
                    seg.setAcceptedMouseButtons(Qt.NoButton)
                    self.plot.addItem(seg, ignoreBounds=True)
                    cur["extras"].append(seg)

    def _level_at(self, k: int, t: float):
        """(raw value, y on the chart) of signal k at time t (the last sample at or before t); None when there is no such sample."""
        s = self.signals[k]
        ts, vs = self.buffer.snapshot(t, t)
        if not len(ts) or k >= vs.shape[1]:
            return None
        j = int(np.searchsorted(ts, t, "right")) - 1
        if j < 0:
            return None
        v = float(vs[j, k])
        if not math.isfinite(v):
            return None
        if self.y_layout == "lanes":
            info = self._lane_info.get(k)
            if info is None or info[3] <= info[2]:
                return None
            b, top, lo, hi, _ = info
            return v, b + (v * s.gain - lo) / (hi - lo) * (top - b)
        return v, v * s.gain + s.offset_y

    def _delta_overlay(self) -> None:
        """'Różnica sygnału': the level of the signal at both ends of the marker, an arrow between them and the difference of the
        values. Redrawn with every chart refresh because the lane scale follows the visible window."""
        for e in self._delta_items:
            self.plot.removeItem(e)
        self._delta_items = []
        x_lo, x_hi = self._x
        for cur in self.mitems.values():
            it = cur["data"]
            if it["kind"] != "delta" or len(it["signals"]) != 1:
                continue
            k = next((i for i, sg in enumerate(self.signals) if sg.name == it["signals"][0] and sg.plot), None)
            if k is None or k >= len(self.curves):
                continue
            a, b = self._level_at(k, it["x0"]), self._level_at(k, it["x1"])
            if a is None or b is None:
                continue
            col = QColor(it["color"])
            width = self._width(it, "sel")
            style = self.LINE_STYLES.get(it["style"], Qt.SolidLine)
            ref = pg.PlotCurveItem([it["x0"], it["x1"]], [a[1], a[1]], pen=pg.mkPen(col, width=1, style=Qt.DotLine))
            arrow = pg.PlotCurveItem([it["x1"], it["x1"]], [a[1], b[1]], pen=pg.mkPen(col, width=max(width, 2), style=style))
            dots = pg.ScatterPlotItem(x=[it["x0"], it["x1"]], y=[a[1], b[1]], size=7, brush=pg.mkBrush(col), pen=pg.mkPen(None))
            d = b[0] - a[0]
            right = it["x1"] > x_lo + 0.8 * (x_hi - x_lo)
            lab = pg.TextItem(f"Δ = {d:+.5g}  ({a[0]:.5g} → {b[0]:.5g})", color=col, anchor=(1.0 if right else 0.0, 0.5))
            lab.setPos(it["x1"] + (-1 if right else 1) * self.vb.viewPixelSize()[0] * 6, (a[1] + b[1]) / 2)
            for e, z in ((ref, 8), (arrow, 9), (dots, 9), (lab, 10)):
                e.setZValue(z)
                if hasattr(e, "setAcceptedMouseButtons"):
                    e.setAcceptedMouseButtons(Qt.NoButton)
                self.plot.addItem(e, ignoreBounds=True)
                self._delta_items.append(e)

    def _marker_style(self) -> None:
        """The marker chosen for moving ('Zmień pozycję') is drawn white and thick; the others in their own colour."""
        for mid, cur in self.mitems.items():
            it, hi = cur["data"], mid in self.mhi
            if it.get("passive"):
                continue
            pen = self._marker_pen(it, hi)
            main = cur["main"]
            if it["kind"] in SPAN_KINDS:
                main.setBrush(pg.mkBrush(QColor(255, 255, 255, 90) if hi else self._range_fill(it)))
                for ln in main.lines:
                    ln.setPen(pen)
                    ln.setHoverPen(self._hover_pen(it))
            else:
                main.setPen(pen)
                main.setHoverPen(self._hover_pen(it))

    @staticmethod
    def _alpha(it: dict) -> int:
        if it["kind"] == "delta":
            return 0                                                  # a difference marker has no area, only the bars and the arrow
        return int(round(max(0, min(100, it["opacity"])) * 2.55))

    def _range_fill(self, it: dict) -> QColor:
        """Colour of the area of a range marker (transparent when the area is drawn lane by lane instead)."""
        fill = QColor(it["color"])
        fill.setAlpha(0 if it["signals"] and self.y_layout == "lanes" else self._alpha(it))
        return fill

    def set_marker_highlight(self, ids) -> None:
        """ids: a marker id, a set of ids or None (nothing highlighted)."""
        self.mhi = set() if ids is None else ({ids} if isinstance(ids, int) else set(ids))
        self._marker_style()

    def _on_hover(self, pos) -> None:
        """The cursor over a marker opens a bubble with its parameters and descriptions."""
        if QApplication.mouseButtons() != Qt.NoButton:
            return
        if self.legend_tip is not None:                             # the cursor over a legend row: the bubble of that signal
            row = self._legend_row_at(pos)
            if row is not None:
                if self._tip_id != ("leg", row):
                    self._tip_id = ("leg", row)
                    QToolTip.showText(QCursor.pos(), self.legend_tip(row), self.glw)
                return
            if isinstance(self._tip_id, tuple):
                QToolTip.hideText()
                self._tip_id = None
        if not self.mitems:
            return
        best, score = None, None
        if self.vb.sceneBoundingRect().contains(pos):
            x = float(self.vb.mapSceneToView(pos).x())
            tol = self.vb.viewPixelSize()[0] * 6
            for mid, cur in self.mitems.items():
                it = cur["data"]
                if it.get("passive"):
                    continue
                hit = (it["x0"] - tol <= x <= it["x1"] + tol) if it["kind"] in SPAN_KINDS else abs(x - it["x0"]) <= tol
                if hit:
                    sc = (it["kind"] == "point", it["priority"])          # a line wins over the area it lies in
                    if score is None or sc > score:
                        best, score = mid, sc
        if best is None:
            if self._tip_id is not None:
                QToolTip.hideText()
            self._tip_id = None
        elif best != self._tip_id:
            self._tip_id = best
            QToolTip.showText(QCursor.pos(), self.mitems[best]["data"]["tip"], self.glw)

    def start_marker_placement(self, mid: int) -> None:
        """'Zmień pozycję': the marker is highlighted; the next left click on the chart puts it there (right click = cancel)."""
        self.place_marker = mid
        self.set_marker_highlight(mid)
        self.glw.setCursor(Qt.CrossCursor)

    def end_marker_placement(self) -> None:
        self.place_marker = None
        self.set_marker_highlight(None)
        self.glw.unsetCursor()

    def _marker_dropped(self, mid: int, item) -> None:
        if self._mset:
            return
        cur = self.mitems.get(mid)
        if cur is None:
            return
        if cur["data"]["kind"] in SPAN_KINDS:
            a, b = item.getRegion()
            self.markerMoved.emit(mid, float(a), float(b))
        else:
            self.markerMoved.emit(mid, float(item.value()), float(item.value()))

    def _marker_clicked(self, mid: int, ev) -> None:
        if self.place_marker is not None:
            return                                                   # the click is for the placement (scene handler)
        if self._legend_click(ev):
            return                                                   # the legend / a name label lies over the marker: it gets the click
        if ev.button() == Qt.RightButton:
            ev.accept()
            self.markerMenu.emit(mid, ev.screenPos().toPoint())
        elif ev.button() == Qt.LeftButton:
            if ev.double():
                self.markerEdit.emit(mid)
            else:
                self.markerOpened.emit(mid)

    # ---- the ghost of a moved 'Start REC'
    def set_ghost(self, t: float | None, color: str = "#ff8c1a", width: int = 2, text: str = "") -> None:
        """A draggable twin line at time `t` that pulses (colour <-> white); None removes it. The user drops it somewhere else and
        chooses 'Zmień Start REC' from its menu."""
        if t is None:
            if self.ghost is not None:
                self.plot.removeItem(self.ghost)
                self.ghost = None
            self._ghost_timer.stop()
            return
        self._ghost_color, self._ghost_width = color, width
        if self.ghost is None:
            g = pg.InfiniteLine(pos=t, angle=90, movable=True, pen=pg.mkPen(color, width=width + 1, style=Qt.DashLine),
                                hoverPen=pg.mkPen("#ffffff", width=width + 2), label=text,
                                labelOpts={"color": color, "position": 0.8, "rotateAxis": (1, 0), "anchors": [(1, 1), (1, 1)]})
            g.setZValue(12)
            g.sigPositionChangeFinished.connect(lambda l: self.ghostMoved.emit(float(l.value())))
            g.sigClicked.connect(self._ghost_clicked)
            self.plot.addItem(g, ignoreBounds=True)
            self.ghost = g
        else:
            self.ghost.setValue(t)
            if self.ghost.label is not None:
                self.ghost.label.setText(text)
        self._ghost_on = False
        self._ghost_pulse()
        self._ghost_timer.start()

    def _ghost_pulse(self) -> None:
        if self.ghost is None:
            return
        self._ghost_on = not self._ghost_on
        col = QColor("#ffffff" if self._ghost_on else self._ghost_color)
        self.ghost.setPen(pg.mkPen(col, width=self._ghost_width + 1, style=Qt.DashLine))
        if self.ghost.label is not None:
            self.ghost.label.setColor(col)

    def _ghost_clicked(self, line, ev) -> None:
        if ev.button() == Qt.RightButton:
            ev.accept()
            self.ghostMenu.emit(ev.screenPos().toPoint())

    def clear_markers(self) -> None:
        self.set_markers([])

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
        n_vis = int(vis.sum()) if vis is not None else 0
        draw_points = self.show_points and 0 < n_vis <= self.rcfg["points_max"]
        self.points_hidden = bool(self.show_points and n_vis > self.rcfg["points_max"])
        px = max(self.vb.height(), 1.0)
        lo = hi = None
        ticks, marks, info = [], [], {}
        tag_y: dict[int, float] = {}
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
                marks += self._lane_labels(k, llo, lhi, const, px)
            x_end = x1 if (self.follow and x1 > t[-1]) else None
            xs, ys = render.curve_data(t, v[:, k], g, off, x_end, max_points=self.rcfg["curve_points"])
            self.curves[k].setData(xs, ys, connect="finite")
            if draw_points:
                m = (t >= x0) & (t <= x1)
                self.points[k].setData(t[m], v[m, k] * g + off)
            else:
                self.points[k].setData([], [])
            fin = ys[np.isfinite(ys)]
            if len(fin):
                lo = fin.min() if lo is None else min(lo, fin.min())
                hi = fin.max() if hi is None else max(hi, fin.max())
                tag_y[k] = float(np.median(fin))
        self._tag_y = tag_y
        self.vb.setXRange(x0, x1, padding=0)
        if lanes:
            self._lane_info = info
            self.axis_y.lanes = [(*self._lane_geo[k], self.signals[k].color) for k in self._lane_geo]
            ticks = [(m[0], m[1]) for m in marks]
            if marks != self.axis_y.labels:
                self.axis_y.labels = marks
                self.axis_y.update()
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
        self._place_tags()
        self._update_overview(x0, x1, ver)
        if self.mitems:
            self._delta_overlay()

    def _update_overview(self, x0: float, x1: float, ver: int) -> None:
        if len(self.buffer) == 0:
            self.ov.vb.setXRange(x0, x1, padding=0)
            self.region.setRegion((x0, x1))
            return
        a, b = self.buffer.first_time(), self.buffer.last_time()
        lo_x, hi_x = min(a, x0), max(b, x1)
        now = time.monotonic()
        if ver != self._ov_version and (now - self._ov_last >= self.rcfg["overview_s"] or self._ov_version == -1
                                        or not self.follow):
            self._ov_last = now
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
                xs, ys = render.curve_data(t, v[:, k], g, off, None, max_points=self.rcfg["overview_points"])
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
