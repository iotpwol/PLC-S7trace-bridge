"""Round 7: chart rendering settings (frame rate, hidden tabs, points limit, curve / overview resolution, antialiasing)."""
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from s7trace.core import render_cfg as rc
from s7trace.core.config import TabConfig
from s7trace.core.types import Signal
from s7trace.ui.main_window import MainWindow
from s7trace.ui.render_dialog import RenderDialog
from s7trace.ui.theme import apply_dark
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def _tab(n=2000):
    c = TabConfig(ip="10.1.2.3", conf_name="L1")
    c.signals = [Signal(name=n_, dtype="REAL", db=1, byte=i * 4, color=col)
                 for i, (n_, col) in enumerate(zip("AB", ("#ffb347", "#4eb8f0")))]
    tab = TraceTab(c, lambda: [])
    tab.resize(1400, 800)
    tab.show()
    QApplication.processEvents()
    t = np.arange(n) * 0.05
    tab.buffer.reset(2)
    tab.buffer.load(t, np.column_stack([np.sin(t), np.cos(t)]))
    tab.plot.set_follow(False)
    tab.plot.set_view(0, 100)
    tab.plot.refresh(force=True)
    return tab


def test_normalize_clamps_and_defaults():
    d = rc.normalize(None)
    assert d["fps"] == 20 and d["pause_hidden"] is True and d["points_max"] == 800 and d["antialias"] is False
    n = rc.normalize({"fps": 999, "overview_s": 0.0, "points_max": -5, "antialias": "yes", "curve_points": 12345, "x": 1})
    assert n["fps"] == 60 and n["overview_s"] == 0.2 and n["points_max"] == 0 and n["antialias"] is False
    assert n["curve_points"] == 12345 and set(n) == set(rc.DEFAULTS)
    assert isinstance(n["overview_s"], float) and isinstance(n["fps"], int)


def test_frame_rate_sets_the_timer(app):
    tab = _tab()
    assert tab.timer.interval() == 50                                    # 20 Hz by default (it used to be 30 Hz)
    tab.apply_render({"fps": 60})
    assert tab.timer.interval() == 16
    tab.apply_render({"fps": 5})
    assert tab.timer.interval() == 200
    tab.shutdown()


def test_points_are_drawn_only_below_the_limit(app):
    tab = _tab()
    tab.plot.set_points(True)
    tab.plot.set_view(10, 20)                                           # 200 samples in the window
    tab.plot.refresh(force=True)
    assert not tab.plot.points_hidden and len(tab.plot.points[0].getData()[0]) > 100
    tab.plot.set_view(0, 100)                                           # 2000 samples: above the default limit of 800
    tab.plot.refresh(force=True)
    assert tab.plot.points_hidden and len(tab.plot.points[0].getData()[0] if tab.plot.points[0].getData()[0] is not None else []) == 0
    tab.apply_render({"points_max": 5000})                              # raised: drawn again
    tab.plot.refresh(force=True)
    assert not tab.plot.points_hidden and len(tab.plot.points[0].getData()[0]) > 1000
    tab.apply_render({"points_max": 0})                                 # 0 = never
    tab.plot.refresh(force=True)
    assert tab.plot.points_hidden
    tab.apply_render({"point_size": 9})
    assert tab.plot.points[0].opts["symbolSize"] == 9
    tab.shutdown()


def test_the_status_line_explains_why_points_vanished(app):
    tab = _tab()
    tab.btn_pts.setChecked(True)
    tab.plot.refresh(force=True)
    tab._update_status()
    assert "Punkty ukryte" in tab.lbl_status.text()
    tab.apply_render({"points_max": 5000})
    tab.plot.refresh(force=True)
    tab._update_status()
    assert "Punkty ukryte" not in tab.lbl_status.text()
    tab.shutdown()


def test_curve_resolution_follows_the_setting(app):
    tab = _tab(40000)
    tab.plot.set_view(0, 2000)
    tab.apply_render({"curve_points": 500})
    tab.plot.refresh(force=True)
    few = len(tab.plot.curves[0].getData()[0])
    tab.apply_render({"curve_points": 20000})
    tab.plot.refresh(force=True)
    many = len(tab.plot.curves[0].getData()[0])
    assert few <= 1200 < many
    tab.apply_render({"antialias": True})
    assert tab.plot.curves[0].opts["antialias"] is True
    tab.shutdown()


def test_hidden_tabs_do_not_redraw_but_catch_up_when_shown(app, tmp_path):
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    w.resize(1300, 800)
    w.show()
    t0 = w.tabs.widget(0)
    t1 = w.new_tab()                                                      # t1 is on top, t0 is hidden
    QApplication.processEvents()
    assert not t0.plot.isVisible() and t1.plot.isVisible()
    calls = []
    orig = t0.plot.refresh
    t0.plot.refresh = lambda *a, **k: calls.append(1) or orig(*a, **k)
    t0._tick()
    assert not calls and t0._skipped                                      # nothing is computed for an invisible chart
    w.tabs.setCurrentIndex(0)
    QApplication.processEvents()
    t0._tick()
    assert calls and not t0._skipped                                      # back on top: redrawn at once
    t0.apply_render({"pause_hidden": False})
    w.tabs.setCurrentIndex(1)
    QApplication.processEvents()
    calls.clear()
    t0._tick()
    assert calls                                                          # the option off: hidden tabs are drawn as before
    w.close()


def test_overview_interval_is_a_setting(app):
    tab = _tab()
    tab.plot.set_follow(True)
    tab.plot.refresh(force=True)
    v0 = tab.plot._ov_version
    tab.buffer.append(200.0, [1.0, 2.0])
    tab.apply_render({"overview_s": 30.0})
    tab.plot.refresh(force=True)                                          # (apply_render invalidated it: rebuilt once)
    v1 = tab.plot._ov_version
    tab.buffer.append(200.05, [1.0, 2.0])
    tab.plot.refresh(force=True)
    assert tab.plot._ov_version == v1 != v0 or v1 == tab.buffer.version - 1                # not rebuilt again within 30 s
    tab.apply_render({"overview_s": 0.2})
    tab.plot._ov_last = 0.0
    tab.buffer.append(200.10, [1.0, 2.0])
    tab.plot.refresh(force=True)
    assert tab.plot._ov_version == tab.buffer.version                      # a short interval: rebuilt
    tab.shutdown()


def test_render_dialog_applies_live_cancel_restores_and_main_window_keeps_it(app, tmp_path):
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    seen = []
    d = RenderDialog(w.render_cfg, lambda c: (seen.append(c), w._apply_render(c)), w)
    d.show()
    assert d._kit["header"].lbl_title.text() == "Renderowanie wykresu" and set(d.widgets) == set(rc.ORDER)
    d.widgets["fps"].setValue(40)
    d.widgets["antialias"].setChecked(True)
    assert w.tabs.widget(0).timer.interval() == 25 and seen[-1]["antialias"] is True
    d.reset()
    assert w.render_cfg == rc.DEFAULTS and d.widgets["fps"].value() == 20
    d.widgets["points_max"].setValue(1234)
    d.reject()                                                             # cancel: the values from before the dialog
    assert w.render_cfg == rc.DEFAULTS
    w._apply_render({**rc.DEFAULTS, "fps": 33})
    assert w._config_dict()["ui"]["render"]["fps"] == 33                   # saved with the configuration
    w.close()
    w2 = MainWindow(config_file=str(tmp_path / "c.json"))
    w2.render_cfg = rc.normalize({"fps": 33})
    assert w2.new_tab().timer.interval() == 30                             # a new tab starts with the saved settings
    w2.close()
