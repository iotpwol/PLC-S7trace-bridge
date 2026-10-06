"""A pause (Stop -> Start of the reading) cut out of the chart: zero width, one Stop / Start mark, axis labels that jump (v1.17)."""
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from s7trace.core import rec_marks as rmk
from s7trace.core.gapmap import GapMap
from s7trace.ui.theme import apply_dark
from test_rec_marks_ui import db_tab, feed, pump


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


# ------------------------------------------------------------------------------------------------ the mapping (Qt-free)
def test_gapmap_shifts_everything_after_a_pause_and_maps_back():
    g = GapMap([(30, 50), (70, 90)])
    t = np.array([0, 29, 30, 40, 50, 51, 69, 70, 80, 90, 95.0])
    assert g.disp(t).tolist() == [0, 29, 30, 30, 30, 31, 49, 50, 50, 50, 55]      # a time inside a pause = its junction
    assert g.real(31.0) == 51.0 and g.real(60.0) == 100.0 and g.real(29.0) == 29.0
    assert g.real(30.0, "lo") == 30.0 and g.real(30.0, "hi") == 50.0              # the junction itself: Stop side / Start side
    assert g.real(50.0, "lo") == 70.0 and g.real(50.0, "hi") == 90.0
    assert g.disp(5.0) == 5.0 and g.disp(100.0) == 60.0                            # 100 s of data, 40 s cut out
    for x in (0.0, 12.5, 30.5, 49.0, 50.5, 77.0):                                  # disp(real(x)) = x away from the junctions
        assert abs(g.disp(g.real(x)) - x) < 1e-9


def test_gapmap_without_pauses_is_the_identity_and_ignores_tiny_ones():
    assert not GapMap()
    assert GapMap().disp(12.0) == 12.0 and GapMap().real(7.0) == 7.0
    assert not GapMap([(5.0, 5.001)])                                              # shorter than 2 ms is no pause
    g = GapMap([(10, 20), (15, 30)])                                               # overlapping pauses are merged
    assert g.n == 1 and g.a[0] == 10 and g.b[0] == 30


def test_gapmap_segments_and_junction_rows():
    g = GapMap([(30, 50), (70, 90)])
    assert g.segments(0, 60) == [(0.0, 30.0), (50.0, 70.0), (90.0, 100.0)]
    assert g.segments(35, 50) == [(55.0, 70.0)]
    assert g.junction_at(30.0) == 0 and g.junction_at(31.0) is None
    t = np.array([10, 30, 30.001, 50, 50, 60.0])
    v = np.array([[1], [2], [np.nan], [np.nan], [3], [4]])
    t2, v2 = g.drop_gap_rows(t, v)                                                 # the NaN rows inside the pause go, the real samples stay
    assert t2.tolist() == [10, 30, 50, 60] and v2[:, 0].tolist() == [1, 2, 3, 4]


def test_rec_marks_items_join_the_scan_marks():
    m = rmk.RecMarks()
    m.add_gap(30.0, 50.0)
    look = {"rec_show": 1}
    two = [i for i in m.items(look) if rmk.parse(i["id"])[0] in (rmk.SCAN_STOP, rmk.SCAN_START)]
    one = [i for i in m.items(look, join=True) if rmk.parse(i["id"])[0] in (rmk.SCAN_STOP, rmk.SCAN_START)]
    assert len(two) == 2 and len(one) == 1 and "Stop / Start odczytu (1)" in one[0]["title"]


# ------------------------------------------------------------------------------------------------ the chart
def gap_tab(tmp_path):
    """20 s of data, a pause of 20 s (30 .. 50 on the chart time, with the NaN rows the acquisition puts into it), 20 s more."""
    tab = db_tab(tmp_path)
    feed(tab, 0, 30)
    tab.buffer.append(30.0 + 0.001, [float("nan")] * 2)
    tab.buffer.append(50.0, [float("nan")] * 2)
    feed(tab, 50, 70)
    tab.mk.rec.m.add_gap(29.95, 50.0)
    return tab


def test_chart_cuts_the_pause_out_and_keeps_real_times_outside(app, tmp_path):
    tab = gap_tab(tmp_path)
    pv = tab.plot
    pv.set_view(0, 70)
    assert pv.view_range() == (0.0, 70.0) and not pv.gm                              # off by default: the full axis
    tab.set_gap_join(True)
    assert tab.cfg.gap_join and pv.gm.n == 1
    pv.refresh(True)
    assert abs(pv._x[1] - (70 - 20.05)) < 0.06                                       # the chart is as long as the scanned time
    assert abs(pv.view_range()[1] - 70.0) < 1e-6                                     # ... and the rest of the program still sees real times
    xs, ys = pv.curves[0].getData()
    assert xs.max() <= pv._x[1] + 1e-6
    junction = float(pv.gm.j[0])
    near = (np.abs(xs - junction) < 1e-6)
    assert near.sum() >= 2 and np.isfinite(ys[near]).all()                           # the line goes straight across: old value -> new value
    assert np.isfinite(ys).sum() >= len(ys) - 2


def test_markers_are_drawn_on_display_positions_and_reported_in_real_time(app, tmp_path):
    tab = gap_tab(tmp_path)
    pv = tab.plot
    tab.set_gap_join(True)
    pv.set_view(0, 70)
    pv.refresh(True)
    item = {"id": 7, "kind": "point", "x0": 60.0, "x1": 60.0, "color": "#00ff00", "width": 1, "style": "solid", "opacity": 0,
            "priority": 1, "title": "m", "tip": "", "signals": []}
    pv.set_markers([item])
    cur = pv.mitems[7]
    assert abs(cur["main"].value() - (60.0 - 20.05)) < 0.06                          # 60 s of real time stands 20 s earlier
    got = []
    pv.markerMoved.connect(lambda mid, a, b: got.append((mid, a, b)))
    cur["main"].setValue(float(pv.gm.j[0]) + 5.0)                                    # dragged to 5 s after the junction
    pv._marker_dropped(7, cur["main"])
    assert got and abs(got[0][1] - (50.0 + 5.0)) < 0.06                              # = 55 s after the pause
    pv.set_gaps([])                                                                  # cutting off: the marker goes back to its real place
    assert abs(pv.mitems[7]["main"].value() - 60.0) < 1e-6


def test_axis_labels_jump_at_the_junction(app, tmp_path):
    tab = gap_tab(tmp_path)
    pv = tab.plot
    tab.set_gap_join(True)
    ax = pv.plot.getAxis("bottom")
    j = float(pv.gm.j[0])
    ticks = ax.tickValues(0.0, 50.0, 800)[0][1]
    assert any(abs(t - j) < 1e-9 for t in ticks)                                     # one tick at the junction
    assert not any(0 < abs(t - j) < 1e-9 + 0.5 for t in ticks)                       # no tick crowds its double label
    s = ax.tickStrings([5.0, j, j + 10.0], 1, 10.0)
    assert s[0] == "5s" and s[1] == "30s | 50s" and s[2] == "60s"                    # '30 | 50' at the junction, the real time after it


def test_rec_marks_follow_the_switch(app, tmp_path):
    tab = gap_tab(tmp_path)
    n_full = len([i for i in tab.mk.rec.items() if rmk.parse(i["id"])[0] in (rmk.SCAN_STOP, rmk.SCAN_START)])
    tab.set_gap_join(True)
    n_join = len([i for i in tab.mk.rec.items() if rmk.parse(i["id"])[0] in (rmk.SCAN_STOP, rmk.SCAN_START)])
    assert (n_full, n_join) == (2, 1)
    tab.set_gap_join(False)
    assert not tab.plot.gm


def test_config_keeps_the_switch():
    from s7trace.core.config import TabConfig
    c = TabConfig()
    assert c.gap_join is False
    c.gap_join = True
    assert TabConfig.from_dict(c.to_dict()).gap_join is True


def test_span_around_counts_scanned_time(app, tmp_path):
    tab = gap_tab(tmp_path)
    pv = tab.plot
    assert pv.span_around(40.0, 20.0) == (30.0, 50.0)                              # no pauses cut out: plain real times
    tab.set_gap_join(True)
    x0, x1 = pv.span_around(60.0, 20.0)                                            # 20 s of scanned time around real 60 s
    assert abs(pv.gm.disp(x1) - pv.gm.disp(x0) - 20.0) < 1e-6 and x0 < 60.0 < x1
    pv.set_view(x0, x1)
    assert abs(pv.window - 20.0) < 1e-6
