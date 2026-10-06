"""v1.21 Web: 'Ukrywanie nieaktywnych' - the logic of app.js (rows of the settings panel) is run with node on a small fake DOM; the server keeps
the setting in the account's panel preferences."""
import json
import os
import shutil
import subprocess

import pytest

from s7trace.core import panel_cfg
from s7trace.web.prefs import Prefs

STATIC = os.path.join(os.path.dirname(__file__), "..", "s7trace", "web", "static")
NODE = shutil.which("node")


def test_prefs_keep_autohide_per_account(tmp_path):
    pr = Prefs(str(tmp_path))
    assert pr.get("ola")["panel"]["autohide"] == {g: True for g in panel_cfg.AUTOHIDE_GROUPS}
    out = pr.update("ola", {"panel": {"autohide": {"Trigger": False}}})
    assert out["panel"]["autohide"]["Trigger"] is False and out["panel"]["autohide"]["Połączenie"] is True
    assert pr.get("ola")["panel"]["autohide"]["Trigger"] is False and pr.get("ala")["panel"]["autohide"]["Trigger"] is True


JS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('const PANEL_GROUPS'), b = src.indexOf('function panelApply()');
const c = src.indexOf('function panelSetRow'), d = src.indexOf('const panelDeviceItem');
// fake DOM: folds with rows; a row has controls with .disabled / .dataset
const mkRow = (name, ctrls) => ({ dataset: { row: name }, classList: { s: new Set(), toggle(c, on) { on ? this.s.add(c) : this.s.delete(c); }, contains(c) { return this.s.has(c); } },
  querySelectorAll: () => ctrls });
const ctl = (dis, lock) => ({ disabled: dis, dataset: lock ? { lock: '1' } : {} });
const folds = { 'Trigger': [mkRow('Akcja', [ctl(false)]), mkRow('Zapis snapshotu do', [ctl(true)]), mkRow('Baza snapshotów', [ctl(true), ctl(true)]), mkRow('A', [ctl(false), ctl(true)])],
                'Połączenie': [mkRow('Adres IP', [ctl(true, true)]), mkRow('Rack', [ctl(true)])], 'Sterownik': [mkRow('Model', [ctl(true)])] };
const mkFold = (n) => ({ dataset: { fold: n }, classList: { toggle() {}, contains: () => false }, querySelectorAll: () => folds[n] });
const document = { querySelectorAll: (sel) => { const m = /data-fold="([^"]+)"\] \[data-row\]/.exec(sel); if (m) return folds[m[1]] || []; return Object.keys(folds).map(mkFold); } };
const ctx = { document, folds, console, JSON, Object, Set, Array, Number, $: () => null, api: async () => ({}), sideRefresh() {}, panelPersist() {}, setTimeout, clearTimeout };
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + src.slice(c, d) + '; this.api2 = {PANEL: () => PANEL, normalize: panelNormalize};', ctx);
const out = vm.runInContext(process.argv[2], ctx);
console.log(JSON.stringify(out));
"""


def run(expr: str):
    expr = expr.encode("ascii", "backslashreplace").decode()                              # (a command line is not UTF-8 on Windows: escapes)
    r = subprocess.run([NODE, "-e", JS, os.path.join(STATIC, "app.js"), expr], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


pytestmark_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytestmark_node
def test_inactive_rows_hide_unless_pinned_and_locks_do_not_count():
    out = run("""
panelApplyHidden();
const f = (g) => folds[g].map((r) => [r.dataset.row, r.classList.contains('row-hidden')]);
({ trig: f('Trigger'), conn: f('Połączenie'), dev: f('Sterownik') })""")
    t = dict(map(tuple, out["trig"]))
    assert t == {"Akcja": False, "Zapis snapshotu do": True, "Baza snapshotów": True, "A": False}          # 'A': one control still works
    c = dict(map(tuple, out["conn"]))
    assert c["Adres IP"] is False and c["Rack"] is True                                                    # a locked control is not 'inactive'
    assert dict(map(tuple, out["dev"]))["Model"] is False                                                  # this group has no automatic hiding


@pytestmark_node
def test_pin_lasts_until_the_state_changes_and_the_switch_is_per_group():
    out = run("""
const hid = (n) => folds['Trigger'].find((r) => r.dataset.row === n).classList.contains('row-hidden');
const res = {}; panelApplyHidden(); res.start = hid('Zapis snapshotu do');
panelSetRow('Trigger', 'Zapis snapshotu do', true); res.pinned = hid('Zapis snapshotu do'); res.items1 = panelRowItems('Trigger').filter((i) => i[0] === 'Zapis snapshotu do')[0][2];
folds['Trigger'][1].querySelectorAll()[0].disabled = false; panelApplyHidden(); res.active = hid('Zapis snapshotu do');        // becomes active: pin dropped
folds['Trigger'][1].querySelectorAll()[0].disabled = true; panelApplyHidden(); res.again = hid('Zapis snapshotu do');          // inactive again: hidden again
res.items2 = panelRowItems('Trigger').filter((i) => i[0] === 'Zapis snapshotu do')[0][2];
panelSetRow('Trigger', 'Zapis snapshotu do', true); panelSetRow('Trigger', 'Zapis snapshotu do', false); res.unpinned = hid('Zapis snapshotu do'); res.manual = PANEL.hidden['Trigger'];
const last = panelRowItems('Trigger').slice(-1)[0]; res.switchLabel = last[0]; res.switchOn = last[2];
last[1](); res.off = PANEL.autohide['Trigger']; res.shownWhenOff = hid('Zapis snapshotu do'); res.otherGroup = PANEL.autohide['Połączenie'];
res.noSwitch = panelRowItems('Sterownik').slice(-1)[0][0];
res.showAll = (() => { PANEL.autohide['Trigger'] = true; panelApplyHidden(); panelShowAll('Trigger'); return [hid('Zapis snapshotu do'), hid('Baza snapshotów')]; })();
res""")
    assert out["start"] is True and out["pinned"] is False and out["items1"] is True
    assert out["active"] is False and out["again"] is True and out["items2"] is False
    assert out["unpinned"] is True and out["manual"] == []                                                 # not a persisted choice
    assert out["switchLabel"] == "Ukrywanie nieaktywnych" and out["switchOn"] is True and out["off"] is False
    assert out["shownWhenOff"] is False and out["otherGroup"] is True
    assert out["noSwitch"] == "Pokaż wszystkie elementy"                                                   # groups without greyed elements have no switch
    assert out["showAll"] == [False, False]


@pytestmark_node
def test_normalize_knows_the_switch():
    out = run("[normalize({autohide: {Trigger: false}}).autohide, normalize({}).autohide, normalize({autohide: 5}).autohide.Trigger]".replace("normalize", "api2.normalize"))
    assert out[0] == {"Połączenie": True, "Zakres okna wykresu": True, "Trigger": False, "Nagrywanie REC": True}
    assert out[1]["Trigger"] is True and out[2] is True
