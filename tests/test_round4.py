"""Round 4: per-tab legend, {ip} + REC naming, lanes (Share), diagnostics look, zoom limit, paddings."""
import os
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from s7trace.core import diagnostics as dg
from s7trace.core.config import TabConfig
from s7trace.core.trigger import DEFAULT_REC_NAME, DEFAULT_SNAPSHOT_NAME, OLD_SNAPSHOT_NAME, TriggerConfig
from s7trace.core.types import Signal
from s7trace.ui import theme as th
from s7trace.ui.diag_dialog import RATING_SCORE, SPANS, DiagDialog
from s7trace.ui.plotview import MIN_WINDOW, TimeAxis
from s7trace.ui.signals_dialog import CI, SignalsDialog
from s7trace.ui.theme import apply_dark
from s7trace.ui.trace_tab import TraceTab


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def cfg_with(shares=(1, 1, 2)):
    c = TabConfig(ip="10.1.2.3:1102", conf_name="Linia 1")
    c.signals = [Signal(name=n, dtype="BOOL" if n == "A" else "REAL", db=1, byte=i * 4, color=col, share=sh)
                 for i, (n, col, sh) in enumerate(zip("ABC", ("#ffb347", "#4ef04e", "#4eb8f0"), shares))]
    return c


# ------------------------------------------------------------------ config / names
def test_config_defaults_and_roundtrip():
    c = TabConfig()
    assert c.trigger.filename == "snapshot_{confname}_{ip}_{tab}_{date}_{time}.csv" == DEFAULT_SNAPSHOT_NAME
    assert c.rec_filename == "REC_{confname}_{ip}_{tab}_{date}_{time}.csv" == DEFAULT_REC_NAME
    assert c.rec_folder == "rec" and c.legend_pos == [0.0, 0.0] and c.y_layout == "lanes"
    c.legend_pos, c.rec_folder, c.rec_filename, c.y_layout = [1.0, 0.5], "nagrania", "r_{ip}.csv", "offset"
    c.signals[0].share = 2.5
    again = TabConfig.from_dict(c.to_dict())
    assert again.to_dict() == c.to_dict() and again.signals[0].share == 2.5
    # the former default name becomes the new default; a custom name stays
    old = TabConfig.from_dict({"trigger": {"filename": OLD_SNAPSHOT_NAME}})
    assert old.trigger.filename == DEFAULT_SNAPSHOT_NAME
    mine = TabConfig.from_dict({"trigger": {"filename": "moje_{tab}.csv"}, "y_layout": "bzdura", "legend_pos": [1]})
    assert mine.trigger.filename == "moje_{tab}.csv" and mine.y_layout == "lanes" and mine.legend_pos == [0.0, 0.0]
    assert Signal.from_dict({"name": "x", "share": -3}).share == 1.0           # invalid share -> 1


def test_ip_placeholder_and_rec_folder(app, tmp_path):
    tab = TraceTab(cfg_with(), lambda: [])
    tab.cfg.name = "Piec"
    tab.ed_ip.setText("10.1.2.3:1102")
    p = tab._file_name("x_{confname}_{ip}_{tab}.csv", "x", str(tmp_path))
    assert os.path.basename(p) == "x_Linia_1_10.1.2.3_Piec.csv"                # host without port, sanitised
    tab.ed_rfolder.setText(str(tmp_path / "rec"))
    tab._run_signals = tab.display_signals()
    tab.state = "running"
    tab.btn_rec.setChecked(True)
    assert tab.recorder is not None
    assert os.path.dirname(tab.recorder.path) == str(tmp_path / "rec")
    assert os.path.basename(tab.recorder.path).startswith("REC_Linia_1_10.1.2.3_Piec_")
    tab.btn_rec.setChecked(False)
    tab.state = "stopped"
    tab.shutdown()


def test_rec_panel_widgets_and_tooltips(app):
    tab = TraceTab(cfg_with(), lambda: [])
    assert tab.ed_rname.text() == DEFAULT_REC_NAME and tab.ed_rfolder.text() == "rec"
    tab.ed_rfolder.setText("moje")
    tab.ed_rname.setText("r_{ip}.csv")
    c = tab.to_config()
    assert c.rec_folder == "moje" and c.rec_filename == "r_{ip}.csv"
    assert "{ip}" in tab.ed_tname.toolTip() and "{ip}" in tab.ed_rname.toolTip()
    tab.shutdown()


# ---------------------------------------------------------------- legend per tab
def test_legend_double_click_opens_signals(app, monkeypatch):
    tab = TraceTab(cfg_with(), lambda: [])
    tab.resize(1200, 700)
    tab.show()
    QApplication.processEvents()
    opened = []
    monkeypatch.setattr(SignalsDialog, "exec", lambda self: opened.append(1) or 0)
    tab.plot.legendDoubleClicked.emit()                                        # the signal is wired to the dialog
    assert opened == [1]
    # a real double click on the legend (scene -> view coordinates)
    r = tab.plot.legend.sceneBoundingRect()
    pos = tab.plot.glw.mapFromScene(r.center())
    QTest.mouseDClick(tab.plot.glw.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
    QApplication.processEvents()
    assert len(opened) >= 2
    tab.shutdown()


def test_legend_position_saved_in_tab_config(app):
    tab = TraceTab(cfg_with(), lambda: [])
    tab.plot._legend_dropped(0.3, 0.6)
    assert tab.to_config().legend_pos == [0.3, 0.6]
    tab2 = TraceTab(TabConfig.from_dict(tab.to_config().to_dict()), lambda: [])
    assert tab2.plot.legend_pos == (0.3, 0.6)
    tab.shutdown()
    tab2.shutdown()


# ------------------------------------------------------------------ lanes / Share
def _loaded_tab(shares=(1, 1, 2)):
    tab = TraceTab(cfg_with(shares), lambda: [])
    tab.resize(1200, 700)
    tab.show()
    QApplication.processEvents()
    t = np.arange(0, 20, 0.05)
    v = np.zeros((len(t), 3))
    v[:, 0] = (t % 5 < 2).astype(float)
    v[:, 1] = 100 + 50 * np.sin(t)
    v[:, 2] = -3 + 6 * np.sin(t / 2)
    tab.buffer.reset(3)
    tab.buffer.load(t, v)
    tab.plot.set_follow(False)
    tab.plot.set_view(0, 20)
    tab.plot.refresh(force=True)
    QApplication.processEvents()
    return tab, v


def test_share_splits_axis_height(app):
    tab, _ = _loaded_tab((1, 1, 2))
    g = tab.plot.lane_geometry()
    h = [g[k][1] - g[k][0] for k in range(3)]
    assert h == pytest.approx([0.25, 0.25, 0.5])                               # C (Share 2) = twice A or B
    assert g[0][1] == pytest.approx(1.0) and g[2][0] == pytest.approx(0.0)      # top to bottom, no gaps
    assert g[0][0] == pytest.approx(g[1][1]) and g[1][0] == pytest.approx(g[2][1])
    # the curves never leave their lane
    for k in range(3):
        ys = tab.plot.curves[k].getData()[1]
        b, t = g[k]
        assert ys.min() >= b - 1e-9 and ys.max() <= t + 1e-9
    tab.shutdown()


def test_lane_axis_shows_min_and_max(app):
    tab, v = _loaded_tab((1, 1, 2))
    labels = [lab for _, lab in tab.plot._lane_ticks]
    for k in (1, 2):                                                            # analog signals: MIN and MAX of the window
        assert f"{v[:, k].min():.5g}" in labels and f"{v[:, k].max():.5g}" in labels
    assert "0" in labels and "1" in labels                                      # BOOL lane
    assert tab.plot.axis_y.lanes and tab.plot.axis_y.lanes[0][2] == "#ffb347"   # labels take the signal colour
    # taller lane -> intermediate values too
    n_big = sum(1 for p, _ in tab.plot._lane_ticks if tab.plot.lane_geometry()[2][0] <= p <= tab.plot.lane_geometry()[2][1])
    assert n_big >= 3
    tab.shutdown()


def test_lane_xf_maps_min_max_to_lane_edges(app):
    tab, v = _loaded_tab((1, 1, 2))
    p = tab.plot
    g, off, lo, hi, const = p._lane_xf(2, v[:, 2])
    b2, t2 = p._inner(2)
    assert not const and lo == pytest.approx(v[:, 2].min()) and hi == pytest.approx(v[:, 2].max())
    assert v[:, 2].min() * g + off == pytest.approx(b2) and v[:, 2].max() * g + off == pytest.approx(t2)
    flat = p._lane_xf(1, np.full(10, 7.0))                                      # constant signal: centred, one label
    assert flat[4] and flat[2] < 7.0 < flat[3]
    tab.shutdown()


def test_y_layout_switch_and_axis_labels(app):
    tab, _ = _loaded_tab()
    ax = tab.plot.plot.getAxis
    assert ax("left").labelText == "Sygnały" and ax("bottom").labelText == "Czas"
    assert not tab.chk_auto.isEnabled() and not tab.sp_ymin.isEnabled()         # Auto Y / Y min / Y max: not in lanes
    tab.cb_ylayout.setCurrentIndex(tab.cb_ylayout.findData("offset"))
    tab.plot.refresh(force=True)
    assert ax("left").labelText == "Offset" and tab.cfg.y_layout == "offset"
    assert tab.chk_auto.isEnabled()
    tab.shutdown()


def test_h_marker_reads_lane_value(app):
    tab, v = _loaded_tab((1, 1, 2))
    p = tab.plot
    p.set_h_mode(True)
    p._add_marker(p.hmarks, sum(p._inner(2)) / 2, 0)                            # the middle of lane C
    p.update_readout()
    mid = (v[:, 2].min() + v[:, 2].max()) / 2
    assert f"C = {mid:.5g}" in p.readout.text()
    tab.shutdown()


# ---------------------------------------------------------- time axis / zoom limit
def test_time_axis_ticks_distinct_when_zoomed(app):
    ax = TimeAxis("bottom")
    vals = [4326.0 + i * 0.02 for i in range(6)]
    big = ax.tickStrings(vals, 1, 0.02)
    assert len(set(big)) == 6 and big[0].startswith("1:12:06") and "." in big[0]
    small = ax.tickStrings([1.0, 1.5, 2.0], 1, 0.5)
    assert small == ["1.0s", "1.5s", "2.0s"]
    assert ax.tickStrings([10.0, 20.0], 1, 10) == ["10s", "20s"]


def test_zoom_stops_at_100_ms(app):
    tab, _ = _loaded_tab()
    assert MIN_WINDOW == 0.1
    tab.plot.vb.setRange(xRange=(5.0, 5.001), padding=0)                        # what the wheel would do
    x0, x1 = tab.plot.vb.viewRange()[0]
    assert x1 - x0 >= MIN_WINDOW - 1e-6
    assert tab.sp_window.minimum() == pytest.approx(0.1)
    tab.shutdown()


# ---------------------------------------------------------------------- REC dot
def test_rec_dot_idle_colour_is_text_colour(app):
    tab = TraceTab(cfg_with(), lambda: [])
    tab.apply_ctl_theme({"rec_dot": "#ff0000", "rec_blink_hz": 2.0, "ctl_text": "#aaaaaa"})
    assert not tab.btn_rec.isChecked()
    assert tab.btn_rec.icon().cacheKey() == tab._icon_idle.cacheKey()
    img = tab._icon_idle.pixmap(12, 12).toImage()
    assert img.pixelColor(6, 6).name() == "#aaaaaa"
    tab.btn_rec.setChecked(True)
    assert tab.btn_rec.icon().cacheKey() == tab._icon_on.cacheKey()
    tab.btn_rec.setChecked(False)
    assert tab.btn_rec.icon().cacheKey() == tab._icon_idle.cacheKey()
    tab.shutdown()


# --------------------------------------------------------------- signals dialog
def test_signals_dialog_has_share_column(app):
    sigs = cfg_with((1, 3, 2)).signals
    d = SignalsDialog(sigs, False, lambda: [], {"autonumber": True, "name_mode": "prev", "own_name": "SIG",
                                                "offset_step": -1.1})
    heads = [d.table.horizontalHeaderItem(i).text() for i in range(d.table.columnCount())]
    assert heads.index("Share") == heads.index("Gain") + 1                      # right after Gain
    assert [d.table.cellWidget(r, CI["share"]).value() for r in range(3)] == [1.0, 3.0, 2.0]
    d.table.cellWidget(0, CI["share"]).setValue(4.5)
    assert d.signals()[0].share == 4.5
    assert "Share: 4.5" in d.row_tooltip(0)
    d.reject()


def test_apply_signals_while_running_updates_share(app):
    tab = TraceTab(cfg_with(), lambda: [])
    new = [Signal.from_dict(s.to_dict()) for s in tab.cfg.signals]
    new[1].share = 5.0
    tab.apply_signals(new, locked=True)
    assert tab.cfg.signals[1].share == 5.0
    tab.shutdown()


# ---------------------------------------------------------------- diagnostics
def _diag_tab():
    tab = TraceTab(TabConfig(ip="10.12.91.1"), lambda: [])
    d = dg.LinkDiag(cycle_ms=40)
    rng = np.random.default_rng(3)
    t0 = time.perf_counter() - 200
    for i in range(3000):
        d.add_sample(t0 + i * 0.04, float(rng.choice([8, 12, 15, 25], p=[.1, .6, .25, .05])))
    d.note_state("running")
    tab.acq = SimpleNamespace(diag=d, t0=t0, stats=SimpleNamespace(), state="running")
    return tab, d


def test_diag_rating_bar_and_bold_values(app):
    tab, _ = _diag_tab()
    dlg = DiagDialog(tab)
    dlg.refresh()
    assert dlg.bar_rating.score == RATING_SCORE[dlg.lbl_rating.text()] == 100 and dlg.bar_rating.filled() == 10
    head = dlg.lbl_head.text()
    assert "Stan: <b>running</b>" in head and "Czas pracy: <b>" in head and "Próbkowanie: <b>" in head
    for r in range(dlg.t_lat.rowCount()):
        assert dlg.t_lat.item(r, 0).font().bold()                               # values bold ...
    assert not dlg.t_lat.verticalHeaderItem(0).font().bold()                    # ... labels normal
    assert dlg.t_rel.item(0, 0).font().bold()
    dlg.close()
    tab.acq = None
    tab.shutdown()


def test_diag_rating_scores_ordered():
    s = [RATING_SCORE[k] for k in ("Bardzo dobre", "Dobre", "Przeciętne", "Słabe", "Brak połączenia")]
    assert s == sorted(s, reverse=True) and RATING_SCORE["Brak danych"] == 0


def test_diag_histogram_values_above_bars(app):
    tab, d = _diag_tab()
    dlg = DiagDialog(tab)
    dlg.refresh()
    shown = [(i, t.toPlainText()) for i, t in enumerate(dlg.hist_texts) if t.isVisible()]
    hist = d.snapshot()["hist"]
    assert [i for i, _ in shown] == [i for i, h in enumerate(hist) if h > 0]     # only non-empty bars
    assert all(txt.endswith("%") for _, txt in shown)
    tot = sum(hist)
    i, txt = shown[0]
    assert float(txt.rstrip("%")) == pytest.approx(100.0 * hist[i] / tot, abs=0.06)
    dlg.close()
    tab.acq = None
    tab.shutdown()


def test_diag_note_number_not_split_and_spans(app):
    tab, d = _diag_tab()
    dlg = DiagDialog(tab)
    from PySide6.QtWidgets import QLabel
    notes = [w.text() for w in dlg.findChildren(QLabel) if "P95 / P99" in w.text()]
    assert notes and "20 000 próbek" in notes[0]                       # non-breaking: never split over lines
    assert [dlg.cb_span.itemText(i) for i in range(dlg.cb_span.count())] == \
        ["10 s", "30 s", "1 min", "3 min", "10 min", "30 min", "60 min"]
    assert [dlg.cb_span.itemData(i) for i in range(dlg.cb_span.count())] == [10, 30, 60, 180, 600, 1800, 3600]
    assert SPANS[-1] == ("60 min", 3600)
    for i in range(dlg.cb_span.count()):                                        # every span can be drawn
        dlg.cb_span.setCurrentIndex(i)
        dlg.refresh()
    dlg.close()
    tab.acq = None
    tab.shutdown()


def test_lag_series_long_spans_use_per_second_maxima():
    d = dg.LinkDiag(cycle_ms=25, keep=100)                                       # raw history much shorter than 60 min
    for i in range(8000):                                                        # 2000 s at 4 Hz
        d.add_sample(1000.0 + i * 0.25, 10.0 if i % 40 else 30.0)
    t, v = d.lag_series(3600)
    assert t[-1] - t[0] > 1500 and len(t) < 2100                                 # ~1 point per second over >25 min
    assert v.max() == 30.0
    t2, v2 = d.lag_series(30)
    assert len(t2) <= 100 and t2[-1] - t2[0] <= 30
    ping = dg.PingProbe("127.0.0.1")
    assert ping.history.maxlen >= 3600


# ------------------------------------------------------------- bold values / paddings
def test_status_values_are_bold_and_escaped(app):
    tab = TraceTab(cfg_with(), lambda: [])
    tab.status_msg = "Błąd <x> & y"
    tab._update_status()
    assert tab.lbl_status.text() == "<b>Błąd &lt;x&gt; &amp; y</b>"
    assert tab.lbl_method.property("val") is True
    tab.shutdown()


def test_qss_paddings_and_bold_labels():
    qss = th.build_qss(th.DARK)
    assert "QLabel[val=\"true\"]" in qss and "font-weight: bold" in qss
    assert "QTableWidget::item { padding-left: 12px; }" in qss                   # values: twice the label padding
    assert "padding: 3px 3px 3px 6px" in qss                                     # header (labels) 6 px
    assert "QSpinBox, QDoubleSpinBox { padding-left: 10px; }" in qss


def test_wizard_values_bold(app):
    from s7trace.core import detect
    from s7trace.ui.wizard_dialog import WizardDialog
    tab = TraceTab(cfg_with(), lambda: [])
    dlg = WizardDialog.__new__(WizardDialog)                                     # only _fill_info is exercised
    from PySide6.QtWidgets import QDialog, QLabel, QTableWidget
    QDialog.__init__(dlg)
    dlg.t_info, dlg.lbl_time = QTableWidget(0, 2), QLabel()
    res = detect.DetectResult()
    res.info = {"family": "S7-300"}
    import datetime as dt
    res.plc_time, res.plc_time_utc = dt.datetime(2026, 1, 2, 3, 4, 5), False
    res.time_diff_local, res.time_diff_utc = 1.5, -3598.5
    WizardDialog._fill_info(dlg, res)
    assert dlg.t_info.rowCount() >= 1 and dlg.t_info.item(0, 1).font().bold() and not dlg.t_info.item(0, 0).font().bold()
    assert "<b>2026-01-02 03:04:05</b>" in dlg.lbl_time.text() and "<b>+1.5 s</b>" in dlg.lbl_time.text()
    tab.shutdown()
