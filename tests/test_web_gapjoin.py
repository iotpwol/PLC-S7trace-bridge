"""Web: pauses (Stop -> Start of the reading) cut out of the live chart (v1.17) - the JavaScript helpers are run with node, the server side is checked in Python."""
import json
import os
import shutil
import subprocess

import pytest

from s7trace.core.config import TabConfig
from s7trace.web import editing

STATIC = os.path.join(os.path.dirname(__file__), "..", "s7trace", "web", "static")
NODE = shutil.which("node")


def run_js(test: str):
    """Loads chartx.js into a sandbox (with the few globals it needs) and returns the JSON of `test` (an expression / statements ending in `out`)."""
    script = r"""
const vm = require('vm'), fs = require('fs');
const handlers = {}, whandlers = {};
const ctx = { console, Math, JSON, Number, Array, Set, Map, Date, String,
  window: { addEventListener: (t, f) => { (whandlers[t] = whandlers[t] || []).push(f); } },
  COLORS: ['#f00', '#0f0'], recmGaps: () => [{ n: 1, t0: 30, t1: 50 }, { n: 2, t0: 70, t1: 90 }],
  legendStyleThis() {}, legStyle: () => 'legend', ctxMenu() {}, $: () => null, H: handlers, WH: whandlers };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const out = vm.runInContext(process.argv[2], ctx);
console.log(JSON.stringify(out));
"""
    r = subprocess.run([NODE, "-e", script, os.path.join(STATIC, "chartx.js"), test], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def test_js_gapmap_matches_the_python_one():
    out = run_js("""
const gm = gmMake([{t0: 30, t1: 50}, {t0: 70, t1: 90}]);
({ disp: [0, 29, 30, 40, 50, 51, 69, 70, 80, 90, 95].map((t) => gmD(gm, t)),
   real: [0, 29, 30, 31, 50, 60, 80].map((x) => gmR(gm, x)), lo: gmR(gm, 30), hi: gmR(gm, 30, true), hi2: gmR(gm, 50, true),
   segs: gmSeg(gm, 0, 60), inside: [29, 30, 40, 50, 51].map((t) => gmJoinRow(gm, t)), none: gmMake([{t0: 5, t1: 5.001}]), same: gmD(null, 7) })""")
    assert out["disp"] == [0, 29, 30, 30, 30, 31, 49, 50, 50, 50, 55]
    assert out["real"] == [0, 29, 30, 51, 70, 100, 120]
    assert (out["lo"], out["hi"], out["hi2"]) == (30, 50, 90)
    assert out["segs"] == [[0, 30], [50, 70], [90, 100]]
    assert out["inside"] == [False, False, True, True, False]                       # rows with 30 < t <= 50 are the empty rows of the pause
    assert out["none"] is None and out["same"] == 7


def test_js_pixels_map_to_real_times_and_back():
    out = run_js("""
const geo = { t0: 0, t1: 100, pad: { l: 60, r: 10 }, W: 860, H: 300, gm: gmMake([{t0: 30, t1: 50}, {t0: 70, t1: 90}]) };
const w = 860 - 70;
({ x100: cxX(geo, 100), x0: cxX(geo, 0), xj: cxX(geo, 30), xj2: cxX(geo, 50), t_mid: cxT(geo, 60 + w / 2), t_end: cxT(geo, 60 + w, true), t_clamped: cxT(geo, 5000, true),
   back: [10, 40, 60, 95].map((t) => cxT(geo, cxX(geo, t))) , w })""")
    w = out["w"]
    assert abs(out["x100"] - (60 + w)) < 1e-9 and out["x0"] == 60
    assert abs(out["xj"] - out["xj2"]) < 1e-9 and abs(out["xj"] - (60 + w * 30 / 60)) < 1e-9              # 100 s of data, 40 s cut out: 60 s on the screen
    assert abs(out["t_mid"] - 30) < 1e-6                                                              # the middle of the screen is the first junction (the Stop side)
    assert abs(out["t_end"] - 100) < 1e-6 and abs(out["t_clamped"] - 100) < 1e-6
    assert [round(t, 6) for t in out["back"]] == [10, 30, 60, 95]                                    # 40 s lies inside the pause: it comes back as the junction


def test_js_gap_spec_follows_the_viewer_and_the_connection():
    out = run_js("""
const ds = { layout: { gap_mode: 'join' } }, cv = { id: 'canvas', _cx: { gapmode: '', gappx: 0 } }, other = { id: 'rv-canvas', _cx: { gapmode: '' } };
const a = cxGapSpec(cv, ds), b = cxGapSpec(other, ds); cv._cx.gapmode = 'full'; const c = cxGapSpec(cv, ds); cv._cx.gapmode = 'fixed'; const d = cxGapSpec(cv, { layout: { gap_px: 55 } });
cv._cx.gappx = 70; const e = cxGapSpec(cv, ds);
({ conn: a && a.px, rec: !!b, full: !!c, fixed: d && d.px, own: e && e.px })""")
    assert out == {"conn": 0, "rec": False, "full": False, "fixed": 55, "own": 70}                  # only the live chart has pauses; the viewer's choice wins


def test_js_axis_jumps_at_the_junction():
    out = run_js("""
const texts = [], g = { save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, fillText: (t, x, y) => texts.push([t, x]) };
const gm = gmMake([{t0: 30, t1: 50}, {t0: 70, t1: 90}]), geo = { t0: 0, t1: 100, pad: { l: 60, r: 10, t: 8, b: 40 }, W: 860, H: 300, gm };
cxAxis(g, geo, { mode: 'rel', shift: 0, tz: 0 });
const rel = texts.map((t) => t[0]); texts.length = 0;
// the clock: x = 0 is 12:00:00 local time (tz: 0 -> the clock reads UTC)
cxAxis(g, geo, { mode: 'app', shift: 12 * 3600, tz: 0 });
({ rel, clock: texts.map((t) => t[0]) })""")
    assert "30 s | 50 s" in out["rel"] and "70 s | 90 s" in out["rel"]
    assert "0 s" in out["rel"] and "100 s" in out["rel"] or "10 s" in out["rel"]
    assert any("12:00:30 | 12:00:50" in t for t in out["clock"]), out["clock"]
    assert not any(t in ("30 s", "50 s") for t in out["rel"])                                      # no plain tick crowds the double label


def test_js_pan_and_zoom_keep_the_width_on_the_screen():
    """Dragging / Ctrl+wheel work on display positions: the stretch shown keeps its width in scanned time."""
    out = run_js("""
const cvH = {}, canvas = { width: 860, height: 300, addEventListener: (t, f) => { cvH[t] = f; }, getBoundingClientRect: () => ({ left: 0, top: 0, width: 860, height: 300 }), style: {} };
const gm = gmMake([{t0: 30, t1: 50}, {t0: 70, t1: 90}]); let range = [10, 60]; const calls = [];
canvas._geo = { t0: 10, t1: 60, pad: { l: 60, r: 10 }, W: 860, H: 300, gm };
cxAttach(canvas, { range: () => range, limits: () => [0, 100], setRange: (a, b) => { range = [a, b]; calls.push([a, b]); }, redraw() {}, busy: () => false, gm });
cvH.mousedown({ button: 0, clientX: 400, clientY: 100, shiftKey: false, stopImmediatePropagation() {}, preventDefault() {} });
WH.mousemove[0]({ clientX: 500, clientY: 100 });
const D = (t) => gmD(gm, t), w0 = D(60) - D(10), moved = range.slice(); WH.mouseup[0]({ clientX: 500, clientY: 100, target: canvas });
({ range: moved, width: D(moved[1]) - D(moved[0]), w0 })""")
    assert abs(out["width"] - out["w0"]) < 1e-6                                                      # the same stretch of scanned time
    assert out["range"][0] < 10 and out["range"][0] >= 0                                              # dragged to the right = earlier data


def test_server_keeps_the_mode_per_connection():
    cfg = TabConfig()
    v = editing.view(cfg)
    assert (v["gap_mode"], v["gap_px"]) == ("full", 40)
    editing.apply(cfg, {"gap_mode": "fixed", "gap_px": 60}, running=True)                           # a look setting: allowed while running
    assert (cfg.gap_mode, cfg.gap_px) == ("fixed", 60)
    for bad in ({"gap_mode": "zzz"}, {"gap_px": 2}, {"gap_px": 5000}):
        with pytest.raises(editing.EditError):
            editing.apply(TabConfig(), bad, running=False)


def test_js_band_matches_the_python_map():
    out = run_js("""
const gm = gmMake([{t0: 30, t1: 50}, {t0: 70, t1: 90}], 6);
({ disp: [0, 29, 30, 40, 50, 51, 69, 70, 80, 90, 95].map((t) => gmD(gm, t)), real: [0, 30, 33, 34.5, 36, 37, 55, 56, 59, 62, 67].map((x) => gmR(gm, x)),
   D: gm.D, E: gm.E, j: gm.j, segs: gmSeg(gm, 0, 70), join: gmJoinRow(gm, 40),
   fit: gmFit(gmMake([{t0: 30, t1: 50}, {t0: 70, t1: 90}]), 0, 100, 40, 800),
   spec: (() => { const m = cxGm({ gaps: [{ t0: 30, t1: 50 }], px: 40 }, 0, 100, 800, 0), f = cxGm({ gaps: [{ t0: 30, t1: 50 }], px: 40 }, 0, 0, 800, 60); return [m.g, f.g]; })() })""")
    assert out["disp"] == [0, 29, 30, 33, 36, 37, 55, 56, 59, 62, 67]
    assert out["real"] == [0, 30, 40, 45, 50, 51, 69, 70, 80, 90, 95]
    assert out["D"] == [30, 56] and out["E"] == [36, 62] and out["j"] == [33, 59]
    assert out["segs"] == [[0, 30], [50, 70], [90, 98]] and out["join"] is False
    assert abs(out["fit"] - 40 * (60 + 2 * out["fit"]) / 800) < 1e-9                                  # 40 px of 800
    assert abs(out["spec"][1] - 40 * 60 / 800) < 1e-9                                                  # following the last 60 s: 40 px of the window
    assert out["spec"][0] > 0


def test_js_axis_in_a_band_has_one_double_label_in_its_middle():
    out = run_js("""
const texts = [], g = { save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, fillText: (t, x, y) => texts.push([t, x]) };
const gm = gmMake([{t0: 30, t1: 50}], 4), geo = { t0: 0, t1: 100, pad: { l: 60, r: 10, t: 8, b: 40 }, W: 860, H: 300, gm };
cxAxis(g, geo, { mode: 'rel', shift: 0, tz: 0 });
({ texts, x: cxX(geo, 30), x2: cxX(geo, 50), mid: (cxX(geo, 30) + cxX(geo, 50)) / 2 })""")
    dbl = [t for t in out["texts"] if "|" in t[0]]
    assert len(dbl) == 1 and dbl[0][0] == "30 s | 50 s" and abs(dbl[0][1] - out["mid"]) < 1e-6
    assert out["x2"] > out["x"]                                                                       # the two ends of the pause are apart


def test_front_end_wires_the_modes():
    js = open(os.path.join(STATIC, "chartx.js"), encoding="utf-8").read()
    app = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert 'data-x="gj"' in js and 'data-x="gpx"' in js and "cxGapSpec" in js and "cxGm" in js
    assert "gapModeThis" in app and "gap_mode" in app and "gm.g > 0" in app
