"""v1.19: the look of the pause bands (fill, written length: direction / colour / position) and of the TRIG (n) lines (numbering, look),
hints on the greyed-out trigger fields - desktop + the Web side."""
import json
import os
import shutil
import subprocess

import pytest
from PySide6.QtWidgets import QApplication

from s7trace.core import marker_look as ml
from s7trace.ui import theme
from s7trace.ui.gap_dialog import GapDialog
from s7trace.ui.theme import apply_dark
from s7trace.web.prefs import Prefs
from test_gapjoin import gap_tab
from test_rec_marks_ui import db_tab, feed, pump

STATIC = os.path.join(os.path.dirname(__file__), "..", "s7trace", "web", "static")
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


# ------------------------------------------------------------------------------------------------ the settings
def test_look_keys_are_validated_and_survive_the_interface_profile(tmp_path):
    d = ml.normalize({"gap_fill": "#112233", "gap_opacity": 400, "gap_text": 0, "gap_text_color": "red", "gap_text_dir": "horizontal",
                      "gap_text_pos": "diagonal", "trig_show": 0, "trig_width": 5, "trig_color": "#AABBCC", "trig_style": "dash"})
    assert d["gap_fill"] == "#112233" and d["gap_opacity"] == 100 and d["gap_text"] == 0           # limits
    assert d["gap_text_color"] == ml.DEFAULTS["gap_text_color"] and d["gap_text_pos"] == "middle"  # invalid -> default
    assert d["gap_text_dir"] == "horizontal" and (d["trig_show"], d["trig_width"], d["trig_color"], d["trig_style"]) == (0, 5, "#aabbcc", "dash")
    assert ml.DEFAULTS["gap_text_dir"] == "vertical" and ml.DEFAULTS["trig_style"] == "dot"
    assert not any(k.startswith(("gap_", "trig_")) and k in ml.ORDER for k in ml.GAP_KEYS) and "trig_show" in ml.ORDER
    path = str(tmp_path / "interface.json")
    t = theme.normalize({"marker_look": d})
    theme.save_profile(path, t)
    text = open(path, encoding="utf-8").read()
    assert '"marker_gap_fill": "#112233"' in text and '"marker_trig_style": "dash"' in text           # one parameter per line
    assert theme.load_profile(path)["marker_look"] == d


def test_web_prefs_keep_the_new_keys(tmp_path):
    pr = Prefs(str(tmp_path))
    out = pr.update("ola", {"marker_look": {"gap_text_pos": "top", "gap_fill": "#010203", "trig_color": "#0a0b0c", "trig_width": 3}})
    look = out["marker_look"]
    assert (look["gap_text_pos"], look["gap_fill"], look["trig_color"], look["trig_width"]) == ("top", "#010203", "#0a0b0c", 3)
    assert pr.get("ola")["marker_look"] == look and pr.get("nobody")["marker_look"]["gap_text_dir"] == "vertical"


# ------------------------------------------------------------------------------------------------ the bands
def test_band_look_follows_the_settings(app, tmp_path):
    tab = gap_tab(tmp_path)
    pv = tab.plot
    tab.show()
    pump(lambda: False, 0.2)
    pv.set_view(0, 70)
    tab.set_gap_mode("fixed", 50)
    pv.refresh(True)
    reg, txt = pv._band_items[0], pv._band_items[1]
    assert txt.angle == 90                             # a vertical text by default
    base = dict(pv.mlook)
    pv.set_marker_look({**base, "gap_fill": "#ff0000", "gap_opacity": 50, "gap_text_color": "#00ff00", "gap_text_dir": "horizontal", "gap_text_pos": "top"})
    reg, txt = pv._band_items[0], pv._band_items[1]
    c = reg.brush.color()
    assert (c.red(), c.green(), c.blue()) == (255, 0, 0) and abs(c.alphaF() - 0.5) < 0.01
    assert txt.angle == 0 and txt.textItem.defaultTextColor().name() == "#00ff00"
    (_, _), (y0, y1) = pv.vb.viewRange()
    assert txt.pos().y() > y0 + 0.9 * (y1 - y0)                                              # at the top of the band
    pv.set_marker_look({**base, "gap_text_pos": "bottom"})
    assert pv._band_items[1].pos().y() < y0 + 0.1 * (y1 - y0)
    pv.set_marker_look({**base, "gap_text": 0})
    assert len(pv._band_items) == 1 and all(not getattr(i, "_band", False) for i in pv._band_items)   # the bands only, no text
    tab.shutdown()


def test_gap_dialog_changes_the_tab_and_the_look_live_and_cancel_restores(app, tmp_path):
    calls = {"mode": [], "look": []}
    look = ml.normalize({})
    dlg = GapDialog("full", 40, look, lambda m, px: calls["mode"].append((m, px)), lambda d: calls["look"].append(d))
    assert not dlg.sp_px.isEnabled() and not dlg.btn_fill.isEnabled()                          # the band look applies to the 'fixed' mode only
    dlg.cb_mode.setCurrentIndex(dlg.cb_mode.findData("fixed"))
    assert calls["mode"][-1] == ("fixed", 40) and dlg.sp_px.isEnabled() and dlg.cb_pos.isEnabled()
    dlg.sp_px.setValue(80)
    assert calls["mode"][-1] == ("fixed", 80)
    dlg.cb_dir.setCurrentIndex(dlg.cb_dir.findData("horizontal"))
    dlg.cb_pos.setCurrentIndex(dlg.cb_pos.findData("bottom"))
    dlg.sp_op.setValue(60)
    assert calls["look"][-1]["gap_text_dir"] == "horizontal" and calls["look"][-1]["gap_text_pos"] == "bottom" and calls["look"][-1]["gap_opacity"] == 60
    dlg.chk_text.setChecked(False)
    assert not dlg.cb_dir.isEnabled() and not dlg.cb_pos.isEnabled() and calls["look"][-1]["gap_text"] == 0
    mode, px, res = dlg.result()
    assert (mode, px) == ("fixed", 80) and res["gap_opacity"] == 60
    dlg.reject()
    assert calls["mode"][-1] == ("full", 40) and calls["look"][-1] == look                     # the old values are back
    dlg2 = GapDialog("fixed", 40, {**look, "gap_opacity": 70}, lambda *a: None, lambda d: calls["look"].append(d))
    dlg2.reset()
    assert calls["look"][-1]["gap_opacity"] == ml.DEFAULTS["gap_opacity"]


# ------------------------------------------------------------------------------------------------ TRIG (n)
def test_trig_lines_are_numbered_and_look_like_the_settings(app, tmp_path):
    tab = db_tab(tmp_path)
    feed(tab, 0, 30)
    pv = tab.plot
    pv.mark_trigger(5.0, 1)
    pv.mark_trigger(12.0, 2)
    assert [ln.label.toPlainText() if hasattr(ln.label, "toPlainText") else ln.label.textItem.toPlainText() for ln in pv.trigger_lines] == ["TRIG (1)", "TRIG (2)"]
    assert [round(ln.value(), 3) for ln in pv.trigger_lines] == [5.0, 12.0]                       # the earlier line stays
    pv.set_marker_look({**pv.mlook, "trig_color": "#00ff00", "trig_width": 3})
    assert len(pv.trigger_lines) == 2 and pv.trigger_lines[0].pen.color().name() == "#00ff00" and pv.trigger_lines[0].pen.width() == 3
    pv.set_marker_look({**pv.mlook, "trig_show": 0})
    assert pv.trigger_lines == []
    pv.set_marker_look({**pv.mlook, "trig_show": 1})
    assert len(pv.trigger_lines) == 2                                                             # (hidden = only not drawn)
    tab.trig_n = 7
    tab._clear_trig()
    assert tab.trig_n == 0 and pv.trigger_lines == []                                             # a new run / Reset starts the numbering again
    tab.shutdown()


def test_trig_lines_follow_the_pauses(app, tmp_path):
    tab = gap_tab(tmp_path)
    pv = tab.plot
    pv.set_view(0, 70)
    pv.mark_trigger(60.0, 3)
    before = pv.trigger_lines[0].value()
    tab.set_gap_mode("join")
    assert abs(pv.trigger_lines[0].value() - (before - 20.05)) < 1e-6                              # the cut-out pause shifts the line
    tab.shutdown()


def test_trigger_counts_the_firings_in_the_tab(app, tmp_path):
    from collections import deque
    tab = db_tab(tmp_path)
    feed(tab, 0, 10)
    name = tab._run_signals[0].name
    tc = tab.cfg.trigger
    tc.enabled, tc.signal, tc.mode, tc.a, tc.action = True, name, ">", 0.5, "Pauza"
    tab.engine.reset()
    tab.trig_state = "armed"
    tab.trig_n = 0
    tab._pending = deque([(11.0, [0.0, 0.0]), (11.1, [1.0, 0.0])])
    tab._drain()
    assert tab.trig_n == 1 and len(tab.plot.trigger_lines) == 1
    tab.trig_state = "armed"                                                                       # (re-armed by the user)
    tab.engine.reset()
    tab._pending = deque([(12.0, [0.0, 0.0]), (12.1, [1.0, 0.0])])
    tab._drain()
    assert tab.trig_n == 2 and len(tab.plot.trigger_lines) == 2
    tab.shutdown()


# ------------------------------------------------------------------------------------------------ hints of the greyed-out fields
def test_greyed_out_trigger_fields_say_why(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.chk_trig.setChecked(True)
    tab.cb_tact.setCurrentIndex(tab.cb_tact.findData("Pauza"))                                     # nothing is saved
    assert not tab.cb_ttarget.isEnabled() and "Pole nieaktywne" in tab.cb_ttarget.toolTip() and "Pauza" in tab.cb_ttarget.toolTip()
    assert not tab.cb_tplace.isEnabled() and "Pole nieaktywne" in tab.cb_tplace.toolTip()
    tab.cb_tact.setCurrentIndex(tab.cb_tact.findData("Pauza + zapis CSV"))
    tab.cb_ttarget.setCurrentIndex(tab.cb_ttarget.findData("csv"))
    assert tab.cb_ttarget.isEnabled() and "Pole nieaktywne" not in tab.cb_ttarget.toolTip()
    assert not tab.cb_tplace.isEnabled() and "bazy danych" in tab.cb_tplace.toolTip()               # CSV: no database choice
    assert not tab.ed_tdb.isEnabled() and "SQLite" in tab.ed_tdb.toolTip()
    assert tab.ed_tfolder.isEnabled() and "Pole nieaktywne" not in tab.ed_tfolder.toolTip() and "Zapis do:" in tab.ed_tfolder.toolTip()
    tab.cb_ttarget.setCurrentIndex(tab.cb_ttarget.findData("influx1"))
    assert not tab.ed_tname.isEnabled() and "CSV" in tab.ed_tname.toolTip() and "Pole nieaktywne" in tab.ed_tname.toolTip()
    assert not tab.ed_tfolder.isEnabled() and "Pole nieaktywne" in tab.ed_tfolder.toolTip() and "Zapis do:" in tab.ed_tfolder.toolTip()
    tab.shutdown()


# ------------------------------------------------------------------------------------------------ Web
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_look_normalizes_the_new_keys():
    script = r"""
const vm = require('vm'), fs = require('fs');
const ctx = { console, Math, JSON, Number, Object, document: { addEventListener() {} }, window: { addEventListener() {} } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';this.f = mkLookFrom; this.d = MK_LOOK_DEF;', ctx);
console.log(JSON.stringify({ a: ctx.f({ gap_fill: '#ABCDEF', gap_opacity: 999, gap_text_dir: 'horizontal', gap_text_pos: 'x', trig_style: 'dash', trig_width: 4, trig_show: 0, trig_color: 'blue' }), d: ctx.d }));
"""
    r = subprocess.run([NODE, "-e", script, os.path.join(STATIC, "markers.js")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    a, d = out["a"], out["d"]
    assert (a["gap_fill"], a["gap_opacity"], a["gap_text_dir"], a["gap_text_pos"]) == ("#abcdef", 100, "horizontal", "middle")
    assert (a["trig_style"], a["trig_width"], a["trig_show"], a["trig_color"]) == ("dash", 4, 0, "#ff4040")
    assert set(ml.DEFAULTS) == set(d)                                                              # the browser knows exactly the keys of the program
    assert all(d[k] == ml.DEFAULTS[k] for k in d)                                                  # ... with the same defaults
