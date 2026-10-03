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
    assert "padding: 2px 4px 2px 10px" in qss                                    # numbers, text and drop-downs alike


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


# ------------------------------------------------- per-user data folder (many Windows accounts)
def test_relative_folders_go_to_user_documents(app, tmp_path, monkeypatch):
    from s7trace.core import config as cfgmod
    monkeypatch.setattr(cfgmod, "_known_documents", lambda: str(tmp_path / "Docs"))
    assert cfgmod.data_dir() == str(tmp_path / "Docs" / "S7Trace")
    tab = TraceTab(cfg_with(), lambda: [])
    assert tab._abs_folder("snapshots") == str(tmp_path / "Docs" / "S7Trace" / "snapshots")
    assert tab._abs_folder("rec") == str(tmp_path / "Docs" / "S7Trace" / "rec")
    assert tab._abs_folder(str(tmp_path / "abs")) == str(tmp_path / "abs")          # absolute stays as it is
    p = tab._file_name("a_{ip}.csv", "x", "rec")
    assert os.path.dirname(p) == str(tmp_path / "Docs" / "S7Trace" / "rec") and os.path.isdir(os.path.dirname(p))
    tab.shutdown()


def test_data_dir_is_real_documents_folder():
    from s7trace.core import config as cfgmod
    d = cfgmod.data_dir()
    assert d.endswith(os.path.join("", "S7Trace")) and os.path.isabs(d)
    if os.name == "nt":
        assert cfgmod._known_documents() and os.path.isdir(cfgmod._known_documents())


# ------------------------------------------------------------------- tab bar / group names
def test_tab_bar_stays_inside_window_when_tabs_are_added(app, tmp_path, monkeypatch):
    from s7trace.ui.main_window import MainWindow
    monkeypatch.setattr("s7trace.ui.main_window.save_app_config", lambda *a, **k: None)
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    w.resize(1250, 600)
    w.show()
    bar = w.tabs.bar
    for ip in ("10.12.91.1", "192.168.0.1", "192.168.100.200", "10.1.1.1", "10.1.1.2", "172.16.0.10"):
        w.new_tab(TabConfig(ip=ip))
        QApplication.processEvents()
        assert bar.mapTo(w, bar.rect().topRight()).x() <= w.width()              # the tab bar ends inside the window
        assert w._plus.mapTo(w, w._plus.rect().topRight()).x() <= w.width()      # '+' stays visible
        assert bar.mapTo(w, bar.rect().topLeft()).x() >= w.menuBar().actionGeometry(w.menuBar().actions()[-1]).right()
    w.close()


def test_range_group_renamed(app):
    from PySide6.QtWidgets import QGroupBox
    tab = TraceTab(cfg_with(), lambda: [])
    titles = [g.title() for g in tab.findChildren(QGroupBox)]
    assert "Zakres okna wykresu" in titles and "Zakres" not in titles
    tab.shutdown()


def test_stop_releases_pause_button(app):
    tab = TraceTab(cfg_with(), lambda: [])
    tab.state = "running"
    tab._set_buttons()
    tab.btn_pause.setChecked(True)
    assert tab.btn_pause.text() == "Wznów" and tab.paused
    tab._on_state("stopped", "Zatrzymano.")                                     # Stop pressed
    assert not tab.btn_pause.isChecked() and tab.btn_pause.text() == "Pauza" and not tab.paused
    assert not tab.btn_pause.isEnabled() and not bool(tab.btn_pause.property("on"))
    assert tab.state == "stopped"
    tab.shutdown()


# ------------------------------------------------------- the view stays inside the collected data
def test_view_cannot_leave_collected_data(app):
    tab, _ = _loaded_tab()                                           # data 0 ... 19.95 s
    p = tab.plot
    a, b = p.buffer.first_time(), p.buffer.last_time()
    p.set_follow(False)
    p.vb.setRange(xRange=(15.0, 25.0), padding=0)                    # drag the chart to the right, past the data
    p._on_manual_range()
    assert p.view_range()[1] == pytest.approx(b) and p.view_range()[0] == pytest.approx(b - 10.0)
    p.vb.setRange(xRange=(-8.0, 2.0), padding=0)                     # ... and to the left
    p._on_manual_range()
    assert p.view_range()[0] == pytest.approx(a) and p.view_range()[1] == pytest.approx(a + 10.0)
    p.vb.setRange(xRange=(-50.0, 90.0), padding=0)                   # zoom out: not wider than the collected data
    p._on_manual_range()
    x0, x1 = p.view_range()
    assert x0 == pytest.approx(a) and x1 == pytest.approx(b)
    p.refresh(force=True)
    assert p.vb.viewRange()[0][1] == pytest.approx(b)                # the chart itself follows the clamped view
    tab.shutdown()


def test_overview_region_cannot_leave_collected_data(app):
    tab, _ = _loaded_tab()
    p = tab.plot
    b = p.buffer.last_time()
    p.set_view(5, 10)
    p.refresh(force=True)
    p.region.setRegion((18.0, 30.0))                                  # dragging the yellow window past the end
    x0, x1 = p.view_range()
    assert x1 == pytest.approx(b) and x1 - x0 == pytest.approx(12.0)   # shifted back, the width is kept
    r0, r1 = p.region.getRegion()
    assert r1 == pytest.approx(b) and r1 - r0 == pytest.approx(12.0)   # and the yellow window itself stops at the end
    p.refresh(force=True)
    assert p.region.getRegion()[1] <= b + 1e-9                        # the region is put back inside the data
    tab.shutdown()


def test_clamp_view_without_data_and_min_window(app):
    tab = TraceTab(cfg_with(), lambda: [])
    assert tab.plot.clamp_view(100.0, 200.0) == (100.0, 200.0)       # nothing collected yet: nothing to clamp to
    tab, _ = _loaded_tab()
    x0, x1 = tab.plot.clamp_view(5.0, 5.01)
    assert x1 - x0 >= MIN_WINDOW - 1e-9
    tab.shutdown()


def test_diagnostics_entry_lives_in_settings_menu(app, tmp_path, monkeypatch):
    from s7trace.ui.main_window import MainWindow
    monkeypatch.setattr("s7trace.ui.main_window.save_app_config", lambda *a, **k: None)
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    menus = {a.text().replace("&", ""): a.menu() for a in w.menuBar().actions() if a.menu()}
    names = lambda m: [x.text() for x in m.actions()]
    assert "Diagnostyka połączenia…" in names(menus["Ustawienia"])
    assert "Diagnostyka połączenia…" not in names(menus["Widok"])
    act = next(x for x in menus["Ustawienia"].actions() if x.text() == "Diagnostyka połączenia…")
    assert act.shortcut().toString() == "Ctrl+D"
    w.close()


# ------------------------------------------------------------ 'Okno czasu [s]': typed value or a list
def test_window_field_list_and_typing(app):
    from s7trace.ui.duration_combo import PRESETS
    tab = TraceTab(cfg_with(), lambda: [])
    f = tab.sp_window
    assert f.isEditable()
    secs = [f.itemData(i) for i in range(f.count())]
    assert secs == [5, 10, 15, 30, 60, 90, 120, 180, 300, 600, 900, 1800, 3600, 5400, 7200, 10800, 14400,
                    21600, 28800, 43200, 57600, 86400] == [s for s, _ in PRESETS]
    assert [f.itemText(i) for i in (0, 6, 12, 15, 21)] == ["5 sekund", "2 minuty  (120 s)", "60 minut  (3600 s)",
                                                           "3 godziny  (10800 s)", "24 godziny  (86400 s)"]
    got = []
    f.valueChanged.connect(got.append)
    f.activated.emit(8)                                              # a pick: 5 minutes
    assert got == [300.0] and tab.plot.window == pytest.approx(300.0)
    assert f.lineEdit().text() in ("300,0", "300.0")                  # the field shows seconds
    f.lineEdit().setText("12,5")                                     # typing, as before
    f.lineEdit().editingFinished.emit()
    assert f.value() == pytest.approx(12.5) and tab.plot.window == pytest.approx(12.5)
    f.lineEdit().setText("0.01")                                      # below the minimum -> 0.1 s
    f.lineEdit().editingFinished.emit()
    assert f.value() == pytest.approx(0.1)
    f.lineEdit().setText("abc")                                       # garbage: the previous value comes back
    f.lineEdit().editingFinished.emit()
    assert f.value() == pytest.approx(0.1)
    f.setValue(10 ** 7)
    assert f.value() == 86400.0
    assert tab.to_config().window_s == 86400.0
    tab.shutdown()


def test_window_field_follows_zoom_and_config(app):
    tab = TraceTab(TabConfig(ip="1.2.3.4", window_s=45.0), lambda: [])
    assert tab.sp_window.value() == pytest.approx(45.0)
    tab._on_zoomed(7.5)                                               # the wheel changed the window -> the field follows
    assert tab.sp_window.value() == pytest.approx(7.5)
    assert tab.to_config().window_s == pytest.approx(7.5)
    tab.shutdown()


def test_form_labels_visible_in_narrowest_panel(app):
    from PySide6.QtWidgets import QFormLayout, QLabel
    tab = TraceTab(cfg_with(), lambda: [])
    tab.resize(1200, 700)
    tab.show()
    QApplication.processEvents()
    tab.split_h.set_sizes_for(150)                                             # as narrow as the panel allows
    QApplication.processEvents()
    assert tab.split_h.sizes()[0] == tab._left_min                              # = what its widgets need
    for field in (tab.sp_window, tab.cb_ylayout, tab.sp_ymin, tab.ed_ip):
        lay = field.parentWidget().layout()
        lab = lay.labelForField(field)
        assert lab is not None and lab.width() >= min(40, lab.sizeHint().width()), lab.text()   # long fields never squeeze the labels
    tab.shutdown()


# ----------------------------------------------------------------- IP field: 4 cells, fixed dots
def _ipbox():
    from s7trace.ui.ip_edit import IpEdit
    e = IpEdit()
    e.show()
    e.setFocus()
    return e


def test_ip_edit_has_fixed_dots_and_plain_text(app):
    e = _ipbox()
    assert e.text() == "" and e.displayText().count(".") == 3                 # empty address: only the dots
    e.setText("10.12.91.1")
    assert e.text() == "10.12.91.1" and e.displayText() == "10  . 12  . 91  . 1  "
    e.setText("192.168.0.10:1102")
    assert e.text() == "192.168.0.10:1102" and e.displayText().endswith(" : 1102")
    e.setText("")
    QTest.keyClicks(e, "10.12.91.1")
    assert e.text() == "10.12.91.1"
    e.hide()


def test_ip_edit_dots_never_move_and_cannot_be_deleted(app):
    e = _ipbox()
    e.setText("10.12.91.1")
    dots = [i for i, c in enumerate(e.displayText()) if c == "."]
    QTest.keyClick(e, Qt.Key_End)
    for _ in range(40):                                                       # Backspace steps over the dots, takes digits
        QTest.keyClick(e, Qt.Key_Backspace)
    assert e.text() == "" and [i for i, c in enumerate(e.displayText()) if c == "."] == dots
    e.setText("10.12.91.1")
    QTest.keyClick(e, Qt.Key_Home)
    for _ in range(40):
        QTest.keyClick(e, Qt.Key_Delete)
    assert e.text() == ".12.91.1"                                             # Delete never pulls the next cell back
    assert [i for i, c in enumerate(e.displayText()) if c == "."] == dots
    e.setText("10.12.91.1")
    QTest.keyClick(e, Qt.Key_Home)
    for _ in range(2):
        QTest.keyClick(e, Qt.Key_Right)
    QTest.keyClick(e, Qt.Key_Delete)                                          # at the end of a cell: nothing to delete
    assert e.text() == "10.12.91.1"
    e.hide()


def test_ip_edit_cells_are_independent_and_can_be_empty(app):
    e = _ipbox()
    e.setText("10.12.91.1")
    e.setCursorPosition(0)
    QTest.keyClick(e, Qt.Key_Delete)
    QTest.keyClick(e, Qt.Key_Delete)                                          # first cell emptied, the rest stays
    assert e.text() == ".12.91.1" and e.displayText().startswith("    . 12  .")
    e.selectAll()
    QTest.keyClick(e, Qt.Key_Space)                                           # one key clears everything, dots stay
    assert e.text() == "" and e.displayText().count(".") == 3
    QTest.keyClicks(e, ".12..1")
    assert e.text() == ".12..1"
    e.setCursorPosition(0)
    QTest.keyClicks(e, "256")                                                 # > 255 is refused
    assert e.text().split(".")[0] in ("25", "2")
    e.selectAll()
    QTest.keyClick(e, Qt.Key_Delete)
    assert e.text() == ""
    QTest.keyClicks(e, "x a-")                                                # only digits are accepted
    assert e.text() == ""
    e.hide()


def test_ip_edit_digits_move_on_after_three(app):
    e = _ipbox()
    QTest.keyClicks(e, "192168001")
    assert e.text() == "192.168.0"                                            # '001' stops after '0' (no leading zeros)
    e.setText("")
    QTest.keyClicks(e, "1921681011")
    assert e.text() == "192.168.101.1"
    e.setText("10.1.1.1")
    e.setCursorPosition(len(e.displayText()))
    QTest.keyClicks(e, ":1102")
    assert e.text() == "10.1.1.1:1102"
    QTest.keyClick(e, Qt.Key_Backspace)
    assert e.text() == "10.1.1.1:110"
    e.hide()


def test_ip_field_in_tab_uses_plain_text_everywhere(app):
    tab = TraceTab(TabConfig(ip="10.12.91.1"), lambda: [])
    assert tab.ed_ip.displayText() == "10  . 12  . 91  . 1  " and tab.ed_ip.text() == "10.12.91.1"
    assert tab.to_config().ip == "10.12.91.1" and tab.title() == "10.12.91.1"
    assert not tab.ed_ip.property("invalid")
    tab.ed_ip.setText("10.1.1")
    assert tab.ed_ip.property("invalid") is True
    tab.shutdown()


def test_ip_history_per_user_newest_first(app, tmp_path):
    from s7trace.core import ip_history
    assert ip_history.load() == []
    ip_history.add("10.1.1.1")
    ip_history.add("10.1.1.2")
    ip_history.add("10.1.1.1:102")
    ip_history.add("10.1.1")                                                  # incomplete: not stored
    ip_history.add("10.1.1.2")                                                # used again: back to the top
    assert ip_history.load() == ["10.1.1.2", "10.1.1.1:102", "10.1.1.1"]
    assert str(tmp_path) in ip_history._path()                                # in the (per-user) %APPDATA%
    for i in range(30):
        ip_history.add(f"10.0.0.{i}")
    assert len(ip_history.load()) == ip_history.MAX_ITEMS


def test_ip_combo_lists_history_and_picking_fills_the_field(app):
    from s7trace.core import ip_history
    ip_history.add("172.16.0.5")
    ip_history.add("10.12.91.1")
    tab = TraceTab(TabConfig(ip="1.1.1.1"), lambda: [])
    tab.ed_ip.set_history(ip_history.load())
    assert tab.ed_ip.count() == 2 and tab.ed_ip.itemText(0) == "10 . 12 . 91 . 1"      # newest first
    tab.ed_ip.activated.emit(1)
    assert tab.ed_ip.text() == "172.16.0.5"
    tab.shutdown()


def test_successful_connection_is_remembered(app):
    from s7trace.core import ip_history
    tab = TraceTab(TabConfig(ip="10.7.7.7"), lambda: [])
    tab._on_state("running", "ok")
    assert ip_history.load() == ["10.7.7.7"]
    tab.shutdown()


def test_values_in_fields_are_bold_with_one_left_margin():
    qss = th.build_qss(th.DARK)
    assert "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QComboBox QAbstractItemView { font-weight: bold; }" in qss
    assert qss.count("padding: 2px 4px 2px 10px") == 1                  # one margin for edit fields and drop-downs


# --------------------------------------------------------------- device data box under 'Połączenie'
DEV = {"method": "s7", "info": {"family": "S7-1500", "model": "CPU 1515-2 PN", "firmware": "V2.9.4",
                                "plc_name": "PIEC_1", "module_name": "CPU_1515", "serial": "S C-X1", "pdu": 960},
       "plc_time": __import__("datetime").datetime(2026, 5, 6, 7, 8, 9), "plc_time_utc": False,
       "time_diff_local": 2.5, "time_diff_utc": -7197.5, "rack": 0, "slot": 1}


def test_device_box_empty_until_connection_and_cleared_by_ip_change(app):
    tab = TraceTab(TabConfig(ip="10.1.1.1"), lambda: [])
    assert "Brak połączenia ze sterownikiem" in tab.lbl_dev.text() and tab.device is None
    from PySide6.QtWidgets import QGroupBox
    titles = [g.title() for g in tab.findChildren(QGroupBox)]
    assert titles.index("Sterownik") == titles.index("Połączenie") + 1             # right under 'Połączenie'
    tab._infoRaw.emit(DEV)
    QApplication.processEvents()
    t = tab.lbl_dev.text()
    for label, val in (("Rodzina", "S7-1500"), ("Model", "CPU 1515-2 PN"), ("Firmware", "V2.9.4"),
                       ("Nazwa stacji", "PIEC_1"), ("Nazwa modułu", "CPU_1515")):
        assert f"{label}:&nbsp;&nbsp;</td><td><b>{val}</b>" in t
    assert "Numer seryjny" not in t and "S C-X1" not in t                           # only the five requested fields
    tab.ed_ip.setText("10.1.1.1")                                                   # same address: data stays
    assert tab.lbl_dev.text() == t
    tab.ed_ip.setText("10.1.1.2")                                                   # another device: empty again
    assert "Brak połączenia ze sterownikiem" in tab.lbl_dev.text() and tab.device is None
    tab._infoRaw.emit({"method": "s7", "info": {"family": "S7-300"}})               # new connection: updated
    assert "S7-300" in tab.lbl_dev.text() and "Model:&nbsp;&nbsp;</td><td><b>—</b>" in tab.lbl_dev.text()
    tab._infoRaw.emit({"method": "other", "info": {}})
    assert "Brak danych sterownika" in tab.lbl_dev.text()
    tab.shutdown()


def test_click_on_device_box_opens_full_info_without_new_probe(app, monkeypatch):
    from s7trace.ui import wizard_dialog as wd
    tab = TraceTab(TabConfig(ip="10.1.1.1"), lambda: [])
    seen = []
    monkeypatch.setattr(wd.WizardDialog, "exec", lambda self: seen.append(self) or 0)
    started = []
    monkeypatch.setattr(wd.DetectWorker, "start", lambda self: started.append(1))
    QTest.mouseClick(tab.lbl_dev, Qt.LeftButton)                                    # nothing to show yet
    assert not seen
    tab._infoRaw.emit(DEV)
    QApplication.processEvents()
    tab.lbl_dev.clicked.emit()
    assert len(seen) == 1 and not started                                           # stored data, no new detection
    dlg = seen[0]
    assert dlg.tabs.currentIndex() == 1 and dlg.tabs.tabText(1) == "Sterownik i czas"
    rows = {dlg.t_info.item(r, 0).text(): dlg.t_info.item(r, 1).text() for r in range(dlg.t_info.rowCount())}
    assert rows["Rodzina"] == "S7-1500" and rows["Wersja firmware"] == "V2.9.4" and rows["Numer seryjny"] == "S C-X1"
    assert "w chwili połączenia" in dlg.lbl_time.text() and "<b>+2.5 s</b>" in dlg.lbl_time.text()
    assert dlg.btn_again.isEnabled() and not dlg.btn_use.isEnabled()
    tab.shutdown()


def test_device_data_arrives_from_simulator_after_start(app):
    from s7trace.sim import Simulator
    sim = Simulator(11131)
    sim.start()
    time.sleep(0.6)
    tab = TraceTab(TabConfig(ip="127.0.0.1:11131", conn_type="s7", cycle_ms=50), lambda: [])
    try:
        tab.start()
        t0 = time.time()
        while time.time() - t0 < 15 and tab.device is None:
            QApplication.processEvents()
            time.sleep(0.05)
        assert tab.device is not None and tab.device["method"] == "s7"
        t = tab.lbl_dev.text()
        assert "S7-300" in t and "CPU 315-2 PN/DP" in t and "V3.3.0" in t and "SNAP7-SERVER" in t
        tab.stop()
        t0 = time.time()
        while time.time() - t0 < 10 and tab.state != "stopped":
            QApplication.processEvents()
            time.sleep(0.05)
        assert tab.lbl_dev.text() == t                                              # stays after Stop
    finally:
        tab.shutdown()
        sim.stop()
