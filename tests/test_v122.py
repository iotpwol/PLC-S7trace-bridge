"""v1.22: tabs (close the last one, '+' defaults), spin box arrows, inactive elements (hide / grey), diagnostics (address header, load), tray menu,
pauses in a chart opened from the database (Web part run with node)."""
import json
import os
import shutil
import subprocess

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from s7trace.core import diagnostics as dg
from s7trace.core import panel_cfg, startmenu
from s7trace.core.config import TabConfig
from s7trace.ui import theme as th
from s7trace.ui import tray
from s7trace.ui.diag_dialog import DiagDialog
from s7trace.ui.main_window import APP_TITLE, MainWindow, blank_tab_config
from s7trace.ui.theme import apply_dark
from s7trace.ui.trace_tab import TraceTab

STATIC = os.path.join(os.path.dirname(__file__), "..", "s7trace", "web", "static")
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


# ------------------------------------------------------------------ tabs
def test_last_tab_can_be_closed_and_plus_opens_a_blank_one(app, tmp_path):
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    w.show()
    while w.tabs.count():
        w.close_tab(0)
    assert w.tabs.count() == 0                                                   # no tab is created behind the user's back
    t = w.new_tab(blank_tab_config())
    assert t.title() == "Nowa karta" and t.ed_ip.text().replace(".", "").strip() == ""
    assert (t.cfg.rack, t.cfg.slot) == (0, 0)
    w.close_tab(0)
    assert w.tabs.count() == 0


def test_empty_window_is_saved_and_reopened_empty(app, tmp_path):
    cfg = str(tmp_path / "c.json")
    w = MainWindow(config_file=cfg)
    while w.tabs.count():
        w.close_tab(0)
    w._save_config()
    w2 = MainWindow(config_file=cfg)
    assert w2.tabs.count() == 0


def test_titles_renamed(app, tmp_path):
    assert APP_TITLE.startswith("PLC S7 Trace")


# ------------------------------------------------------------------ spin boxes
def test_spin_arrows_have_files_and_the_combo_fill(app):
    qss = th._spin_qss(th.DARK)
    assert "QSpinBox::up-button" in qss and "QTimeEdit::down-arrow" in qss
    files = [part.split(")")[0] for part in qss.split("url(")[1:]]
    assert files and all(os.path.exists(f) for f in files)
    assert qss.split("background: ")[1][:7] == th.DARK["edit_bg"]                    # the same fill as the drop-down part of a combo box
    assert "subcontrol-origin: padding" in qss                                         # the buttons sit inside the field's frame
    assert th._spin_qss(th.LIGHT) in th.build_qss(th.LIGHT)


# ------------------------------------------------------------------ inactive elements: hide / grey
def test_inactive_mode_in_panel_cfg_profile_and_tab(app, tmp_path):
    assert panel_cfg.normalize({})["inactive"] == "hide"
    assert panel_cfg.normalize({"inactive": "grey"})["inactive"] == "grey"
    assert panel_cfg.normalize({"inactive": "zzz"})["inactive"] == "hide"
    p = str(tmp_path / "p.json")
    th.save_profile(p, {**th.LIGHT, "panel": {**panel_cfg.normalize({}), "inactive": "grey"}})
    assert '"panel_inactive": "grey"' in open(p, encoding="utf-8").read()
    assert th.load_profile(p)["panel"]["inactive"] == "grey"
    t = TraceTab(TabConfig(ip="10.1.2.3"), lambda: [])
    t.apply_panel({**t.panel_state(), "inactive": "grey"})
    assert t.panel_state()["inactive"] == "grey"
    assert not any(t._auto_hidden(g, k) for g in panel_cfg.AUTOHIDE_GROUPS for k in ("Zapis do", "Baza", "Folder"))
    t.apply_panel({**t.panel_state(), "inactive": "hide"})
    assert t.panel_state()["inactive"] == "hide"
    t.shutdown()


def test_interface_dialog_has_the_inactive_choice(app):
    from s7trace.ui.interface_dialog import InterfaceDialog
    d = InterfaceDialog({**th.DARK, "panel": panel_cfg.normalize({})}, lambda t: None)
    assert d.cb_inactive.findData("grey") >= 0
    d.cb_inactive.setCurrentIndex(d.cb_inactive.findData("grey"))
    assert d.theme["panel"]["inactive"] == "grey"


# ------------------------------------------------------------------ diagnostics
def test_load_metrics_scale_with_the_rate():
    a = dg.load_metrics(10.0, 5.0, 100, 2)
    b = dg.load_metrics(20.0, 5.0, 100, 2)
    assert a["data_Bps"] == 1000 and a["pkts_to"] == 20
    assert b["total_kbps"] == pytest.approx(2 * a["total_kbps"]) and b["plc_busy_pct"] == pytest.approx(2 * a["plc_busy_pct"])
    assert dg.load_metrics(0.0, None, 100, 2)["plc_busy_pct"] is None
    big = dg.load_metrics(1.0, 5.0, 4000, 1)                                       # an answer larger than one TCP segment takes more packets
    assert big["pkts_from"] > big["pkts_to"]


def test_snapshot_has_the_four_load_windows():
    d = dg.LinkDiag(cycle_ms=25, bytes_per_cycle=10, req_per_cycle=1)
    for i in range(200):
        d.add_sample(i * 0.05, 12.0)
    s = d.snapshot()
    assert set(s["load"]) == {"now", "w10", "w60", "all"} and s["load"]["all"]["hz"] > 5


def test_diag_dialog_shows_address_and_load(app):
    t = TraceTab(TabConfig(ip="127.0.0.1:8080"), lambda: [])
    t.ui_state["diag_ping"] = False
    dlg = DiagDialog(t)
    dlg.refresh()
    assert "127.0.0.1" in dlg.lbl_target.text() and "<b>8080</b>" in dlg.lbl_target.text()
    t.ed_ip.setText("10.1.2.3")
    assert "(domyślny)" in dlg._target_text()
    assert dlg.t_load.rowCount() == len(dlg.load_rows)
    dlg.close()
    t.shutdown()


def test_local_connections_parses_netstat(monkeypatch):
    out = ("  Proto  Local Address          Foreign Address        State           PID\n"
           "  TCP    10.0.0.5:50000         10.1.2.3:102           ESTABLISHED     4242\n"
           "  TCP    10.0.0.5:50001         8.8.8.8:443            ESTABLISHED     1\n")

    class R:
        stdout = out

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    rows = dg.local_connections_to("10.1.2.3")
    assert len(rows) == 1 and rows[0]["rport"] == "102" and rows[0]["pid"] == "4242"


# ------------------------------------------------------------------ tray menu
def test_tray_menu_texts_and_alternating_items(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    w.show()
    QApplication.processEvents()
    tc = w.tray
    tc.refresh()
    assert tc.a_conn.text().startswith("Połączenia PLC: 0 / 0")
    assert tc.a_load.text().startswith("Obciążenie: ") and tc.a_load.text().count("/") == 1
    assert tc.a_show.text() == "Ukryj S7Trace"
    tc.hidden = True
    tc.refresh()
    assert tc.a_show.text() == "Pokaż S7Trace"
    assert tc.a_pin.text() == "Przypnij do belki"
    assert [a.text() for a in tc.menu.actions() if not a.isSeparator()][-1] == "Zakończ"
    # the other user's session adds the third number
    from s7trace.core import sessions
    reg = sessions.REGISTRY
    if reg is not None:
        other = {"id": "x", "user": "ktos_inny", "host": "h", "pid": 1, "session": 9, "started": "2026-01-01T00:00:00", "updated": 4e12,
                 "tabs": [{"title": "T", "ip": "1.1.1.1", "state": "running", "since": None, "rec": False}]}
        monkeypatch.setattr(reg, "sessions", lambda: [{**other, "me": False}])
        assert tc.conn_text().endswith("/ 1")
    w.tabs.setCurrentIndex(0) if w.tabs.count() else None


def test_tray_quit_asks_and_pin_creates_a_start_menu_shortcut(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    w.show()
    asked = []
    monkeypatch.setattr(MainWindow, "ask_quit", lambda self: asked.append(1) or False)
    closed = []
    monkeypatch.setattr(MainWindow, "close", lambda self: closed.append(1))
    w.tray.quit()
    assert asked and not closed                                                    # the answer 'no' leaves the program running
    monkeypatch.setattr(MainWindow, "ask_quit", lambda self: True)
    w.tray.quit()
    assert closed
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(startmenu, "pin", lambda *a, **k: open(startmenu.shortcut_path(), "w").close() or True)
    os.makedirs(os.path.dirname(startmenu.shortcut_path()), exist_ok=True)
    w.tray.toggle_pin()
    assert startmenu.is_pinned()
    w.tray.refresh()
    assert w.tray.a_pin.text() == "Odepnij od belki"
    w.tray.toggle_pin()
    assert not startmenu.is_pinned()


# ------------------------------------------------------------------ Web: pauses of a recording opened from the database
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_finds_pauses_in_a_loaded_recording():
    script = r"""
const vm = require('vm'), fs = require('fs');
const ctx = { console, Math, JSON, Number, Array, Set, Map, Date, String, window: { addEventListener() {} }, recmGaps: () => [],
  legendStyleThis() {}, legStyle: () => 'legend', ctxMenu() {}, $: () => null };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
console.log(JSON.stringify(vm.runInContext(process.argv[2], ctx)));
"""
    test = """(() => {
  const t = [0, 1, 2, 3, 4, 20, 21, 22, 22.5, 23, 40, 41], nan = null;
  const a = [1, 1, 1, nan, nan, 5, 5, nan, 5, 5, 5, 5], b = [2, 2, 2, nan, nan, 6, 6, nan, 6, 6, 6, 6];
  const ds = { t, values: [a, b], layout: {} };
  const g = cxFindGaps(ds);
  const cv = { id: 'rv-canvas', _cx: { gapmode: 'join' } };
  return { g, spec: !!cxGapSpec(cv, ds), full: cxGapSpec({ id: 'rv-canvas', _cx: {} }, ds), live: cxGapSpec({ id: 'canvas', _cx: { gapmode: 'join' } }, ds) };
})()"""
    r = subprocess.run([NODE, "-e", script, os.path.join(STATIC, "chartx.js"), test], capture_output=True, text=True, timeout=30, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["g"] == [{"n": 1, "t0": 3, "t1": 20}]                              # the dropout of one cycle (t = 22) is not a pause
    assert out["spec"] is True and out["full"] is None and out["live"] is None      # 'live' has no recmGaps here


def test_gap_text_is_the_marker_colour_and_reads_przerwa_with_two_spaces():
    from s7trace.core import marker_look as ml
    assert ml.DEFAULTS["gap_text_color"] == ml.DEFAULTS["rec_color"]
    assert ml.normalize({"gap_text_color": "#a0a0a0"})["gap_text_color"] == ml.DEFAULTS["gap_text_color"]      # the grey default of v1.19 - 1.21 is migrated
    assert ml.normalize({"gap_text_color": "#123456"})["gap_text_color"] == "#123456"                       # a colour chosen by the user stays
    src = open(os.path.join(os.path.dirname(__file__), "..", "s7trace", "ui", "plotview.py"), encoding="utf-8").read()
    assert 'f"Przerwa:  {L:.1f} s"' in src
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "`Przerwa:  ${gm.L[i].toFixed(1)} s`" in js


def test_signal_names_stay_visible_in_the_offset_layout_without_data(app):
    """'Opisy przy sygnałach' in the Offset + Gain layout stood at the median of the curve - with no data in view (stopped, empty chart) the names vanished."""
    t = TraceTab(TabConfig(ip="10.1.2.3"), lambda: [])
    t.resize(1200, 700)
    t.show()
    QApplication.processEvents()
    t.plot.set_legend_style("labels")
    t.cb_ylayout.setCurrentIndex(t.cb_ylayout.findData("offset"))
    QApplication.processEvents()
    t.plot.refresh(force=True)
    QApplication.processEvents()
    assert t.plot.tags and all(tag.isVisible() for tag in t.plot.tags)
    t.shutdown()


def test_wheel_over_a_number_field_of_the_signal_list_does_not_change_it(app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from s7trace.core.types import Signal
    from s7trace.ui.signals_dialog import SignalsDialog
    d = SignalsDialog([Signal(name=f"S{i}", dtype="BYTE", db=1, byte=160 + i) for i in range(3)], False, lambda: [])
    d.resize(1250, 460)
    d.show()
    QApplication.processEvents()
    for key in ("byte", "bit", "share"):
        w = d._cell(1, key)
        v = w.value()
        assert w.focusPolicy() == Qt.StrongFocus and not w.hasMouseTracking()          # built like the fields of the left panel
        for target in (w, w.lineEdit()):
            ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            QApplication.sendEvent(target, ev)
        assert w.value() == v, key
    d.close()


def test_asyncua_helper_threads_are_daemons():
    """asyncua's synchronous client / server start a ThreadLoop thread that was not a daemon: it kept the process alive after a failed OPC UA probe."""
    pytest.importorskip("asyncua")
    from asyncua.sync import ThreadLoop
    from s7trace.core.opcua_loop import make_daemon
    make_daemon()
    make_daemon()                                                    # idempotent
    t = ThreadLoop()
    assert t.daemon
