import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QApplication, QMessageBox

from s7trace.core import netaddr
from s7trace.core.config import TabConfig
from s7trace.core.naming import NAME_OWN, NAME_PREV, new_signal_name, next_name
from s7trace.core.types import Signal, format_value
from s7trace.ui import theme as th
from s7trace.ui.interface_dialog import InterfaceDialog
from s7trace.ui.main_window import MainWindow
from s7trace.ui.signals_dialog import CI, SignalsDialog
from s7trace.ui.trace_tab import TraceTab
from s7trace.ui.validators import Ipv4Validator


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    th.apply_theme(a, th.DARK)
    return a


# ------------------------------------------------------------ naming
def test_next_name_examples_from_spec():
    assert next_name("D160B") == "D160C"
    assert next_name("123M1") == "123M2"
    assert next_name("SIG1") == "SIG2"
    assert next_name("SIG09") == "SIG10"
    assert next_name("D160Z") == "D160AA"
    assert next_name("A") == "B"
    assert next_name("Motor") == "Motor2"


def test_new_signal_name_modes():
    ex = ["D160A", "D160B", "D160C"]
    assert new_signal_name("D160B", ex, True) == "D160D"          # skips the taken D160C
    assert new_signal_name("D160B", ex, False) == "D160B"         # copy -> duplicate on purpose
    assert new_signal_name("D160B", ex, True, NAME_OWN, "SIG") == "SIG4"
    assert new_signal_name("D160B", ex, False, NAME_OWN, "SIG") == "SIG1"
    assert new_signal_name(None, [], True) == "SIG1"


# ------------------------------------------------------- IP validation
@pytest.mark.parametrize("text,state", [
    ("", netaddr.INTERMEDIATE), ("1", netaddr.INTERMEDIATE), ("192.168.", netaddr.INTERMEDIATE),
    ("192.168.0.1", netaddr.ACCEPTABLE), ("10.12.91.1:102", netaddr.ACCEPTABLE),
    ("127.0.0.1:", netaddr.INTERMEDIATE), ("abc", netaddr.INVALID), ("1.2.3.4.5", netaddr.INVALID),
    ("256.1.1.1", netaddr.INVALID), ("1..2", netaddr.INVALID), (".1", netaddr.INVALID),
    ("01.2.3.4", netaddr.INVALID), ("1.2.3.4:99999", netaddr.INVALID), ("1.2:80", netaddr.INVALID),
    ("::1", netaddr.INVALID), ("fe80::1", netaddr.INVALID), ("1.2.3.4 ", netaddr.INVALID),
])
def test_ipv4_state(text, state):
    assert netaddr.ipv4_state(text) == state


def test_ip_field_blocks_typing(app):
    tab = TraceTab(TabConfig(), lambda: [])
    v = Ipv4Validator()
    assert v.validate("192.168.0.1", 0)[0] == QValidator.Acceptable
    assert v.validate("19x", 0)[0] == QValidator.Invalid
    tab.ed_ip.setText("10.1.1")
    assert tab.ed_ip.property("invalid") is True
    tab.ed_ip.setText("10.1.1.1")
    assert tab.ed_ip.property("invalid") is False
    tab.shutdown()


def test_start_refuses_bad_ip(app, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    tab = TraceTab(TabConfig(), lambda: [])
    tab.ed_ip.setText("10.1.1")
    tab.start()
    assert tab.state == "stopped" and shown and "IP" in shown[0]
    tab.shutdown()


# ------------------------------------------------------ value format
def test_format_value():
    b, i, r = Signal(dtype="BOOL"), Signal(dtype="INT"), Signal(dtype="REAL")
    assert format_value(b, 1.0) == "1" and format_value(b, 1.0, "TRUE/FALSE") == "TRUE"
    assert format_value(i, -2.0, "HEX") == "16#FFFE"
    assert format_value(i, 5.0, "BIN") == "2#0000_0000_0000_0101"
    assert format_value(b, 1.0, "BIN") == "2#1"
    assert format_value(r, 1.0, "HEX") == "16#3F800000"
    assert format_value(r, 12.5) == "12.5"
    assert format_value(r, float("nan")) == "—"
    assert format_value(i, 1234.0, "Naukowo") == "1.234000E+03"


# ----------------------------------------------------------- dialog
def rows(*names):
    return [Signal(name=n, dtype="BOOL", db=1, byte=160, bit=i, offset_y=round(-1.1 * i, 3))
            for i, n in enumerate(names)]


def test_add_goes_to_end_and_name_follows_cursor_row(app):
    d = SignalsDialog(rows("D160A", "D160B", "D160C", "D160D"), False, lambda: [])
    d._last_row = 1                                   # cursor in row 2 ("D160B")
    d._add()
    sigs = d.signals()
    assert len(sigs) == 5
    assert sigs[-1].name == "D160E"                   # appended at the END, next free in sequence
    assert [s.name for s in sigs[:4]] == ["D160A", "D160B", "D160C", "D160D"]
    assert sigs[-1].offset_y == pytest.approx(-4.4)   # last offset (-3.3) + step (-1.1)
    assert (sigs[-1].byte, sigs[-1].bit) == (160, 2)  # address continues from the reference row


def test_autonumber_off_and_own_name(app):
    d = SignalsDialog(rows("SIG1"), False, lambda: [], {"autonumber": False})
    d._add()
    assert [s.name for s in d.signals()] == ["SIG1", "SIG1"]
    d2 = SignalsDialog(rows("D160A"), False, lambda: [], {"name_mode": NAME_OWN, "own_name": "SIG"})
    d2._add()
    d2._add()
    assert [s.name for s in d2.signals()] == ["D160A", "SIG2", "SIG3"]


def test_duplicate_names_and_addresses_highlighted(app):
    sigs = rows("A", "B", "C")
    sigs[1].name = "A"                                # duplicate name
    sigs[2].bit = 0                                   # same address as row 0 (DB1.DBX160.0)
    d = SignalsDialog(sigs, False, lambda: [])
    st = lambda r, k: d._cell(r, k).styleSheet()
    assert "9a2a2a" in st(0, "name") and "9a2a2a" in st(1, "name") and st(2, "name") == ""
    assert "c9b030" in st(0, "byte") and "c9b030" in st(2, "byte") and st(1, "byte") == ""
    assert "c9b030" in st(0, "bit")
    # a different type at the same bytes is NOT an address duplicate
    d._cell(2, "dtype").setCurrentText("INT")
    assert st(0, "byte") == "" and st(2, "byte") == ""
    # fixing the name clears the red
    d._cell(1, "name").setText("B")
    assert st(0, "name") == "" and st(1, "name") == ""


def test_columns_order_and_extras(app):
    keys = list(CI)
    assert keys[:2] == ["fetch", "plot"] and keys[2:5] == ["name", "value", "fmt"] and keys[-1] == "comment"
    s = rows("X")
    s[0].comment, s[0].enabled, s[0].plot, s[0].fmt = "opis", False, False, "HEX"
    d = SignalsDialog(s, False, lambda: [])
    got = d.signals()[0]
    assert (got.comment, got.enabled, got.plot, got.fmt) == ("opis", False, False, "HEX")


def test_header_actions_fix_offsets_and_columns(app):
    sig = rows("A", "B", "C")
    for s in sig:
        s.offset_y = 7.0
    d = SignalsDialog(sig, False, lambda: [], {"offset_step": -1.5})
    d.fix_offsets()
    assert [s.offset_y for s in d.signals()] == [0.0, -1.5, -3.0]
    d.table.setColumnHidden(CI["gain"], True)
    st = {}
    d.ui_state = st
    d._save_state()
    assert "gain" in st["hidden"]
    d2 = SignalsDialog(sig, False, lambda: [], ui_state=st)
    assert d2.table.isColumnHidden(CI["gain"])


def test_tooltip_and_live_value(app):
    s = rows("A")
    s[0].comment = "silnik 1"
    s[0].fmt = "TRUE/FALSE"
    d = SignalsDialog(s, True, lambda: [], value_provider=lambda: [1.0])
    tip = d.row_tooltip(0)
    assert "silnik 1" in tip and "DB1.DBX160.0" in tip and "TRUE" in tip
    d._refresh_values()
    assert d._cell(0, "value").text() == "TRUE"
    d2 = SignalsDialog(s, False, lambda: [], value_provider=lambda: None)
    assert d2._cell(0, "value").text() == "—" and "nie jest teraz pobierana" in d2.row_tooltip(0)


# ------------------------------------------------------------- tab
def test_disabled_signal_not_read_and_hidden_not_plotted(app):
    cfg = TabConfig()
    cfg.signals = rows("A", "B", "C")
    cfg.signals[1].enabled = False
    cfg.signals[2].plot = False
    tab = TraceTab(cfg, lambda: [])
    assert [s.name for s in tab.display_signals()] == ["A", "C"]
    assert tab.buffer.n == 2 and tab.cb_tsig.count() == 2
    assert len(tab.plot.curves) == 2
    tab.buffer.append(0.0, [1.0, 0.0])
    tab.buffer.append(1.0, [1.0, 1.0])
    tab.plot.set_view(0, 1)
    tab.plot.refresh(True)
    assert len(tab.plot.curves[0].getData()[0]) > 0
    hidden_x = tab.plot.curves[1].getData()[0]
    assert hidden_x is None or len(hidden_x) == 0         # "Wykres" off -> not drawn
    assert [e[1].text for e in tab.plot.legend.items] == ["A"]
    tab.state = "running"
    assert tab.current_values() == [1.0, None, 1.0]       # aligned with cfg.signals, B not read
    tab.state = "stopped"
    tab.shutdown()


def test_tab_rename_and_persistence(app, tmp_path):
    cf = str(tmp_path / "c.json")
    w = MainWindow(config_file=cf)
    w.rename_tab = MainWindow.rename_tab.__get__(w)
    t0 = w.tabs.widget(0)
    t0.rename("Linia 1")
    assert w.tabs.tabBar().tabText(0).startswith("Linia 1")
    w.duplicate_tab(0)
    assert w.tabs.count() == 2 and w.tabs.widget(1).title() == "Linia 1 (kopia)"
    w.ui["theme"] = th.normalize({**th.LIGHT, "font_size": 11})
    w._apply_theme(w.ui["theme"])
    w.resize(1111, 777)
    w.close()
    w2 = MainWindow(config_file=cf)
    assert [w2.tabs.widget(i).title() for i in range(2)] == ["Linia 1", "Linia 1 (kopia)"]
    assert w2.theme["window_bg"] == th.LIGHT["window_bg"] and w2.theme["font_size"] == 11
    assert w2.menuBar().cornerWidget(Qt.TopRightCorner) is not None        # tab bar sits in the menu row
    w2.close()
    th.apply_theme(QApplication.instance(), th.DARK)


def test_signal_list_shared_between_tabs(app):
    w = MainWindow(config_file=os.devnull)
    w.tabs.widget(0).cfg.signals = rows("A", "B")
    w.new_tab()
    got = w.tabs.widget(1).other_tabs()
    assert got and got[0][1][0].name == "A"
    w.close()


def test_interface_dialog_preview_and_cancel(app):
    seen = []
    d = InterfaceDialog(th.DARK, lambda t: seen.append(dict(t)))
    d._load(th.LIGHT, keep_font=True)
    assert seen[-1]["window_bg"] == th.LIGHT["window_bg"]
    d.reject()                                              # restores the original look
    assert seen[-1]["window_bg"] == th.DARK["window_bg"]
    assert th.normalize({"window_bg": "not-a-colour", "font_size": 999})["window_bg"] == th.DARK["window_bg"]


# ------------------------------------------------------- row drag & drop
def test_move_row_reorders_and_keeps_data(app):
    d = SignalsDialog(rows("A", "B", "C", "D"), False, lambda: [])
    d._cell(1, "comment").setText("opis B")
    d.move_row(1, 3)                                         # B -> end
    assert [s.name for s in d.signals()] == ["A", "C", "D", "B"]
    assert d.signals()[3].comment == "opis B" and d.signals()[3].bit == 1
    d.move_row(3, 0)
    assert [s.name for s in d.signals()] == ["B", "A", "C", "D"]
    d.move_row(0, 9)                                         # out of range -> ignored
    assert [s.name for s in d.signals()] == ["B", "A", "C", "D"]


def test_row_grip_mouse_drag(app):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    d = SignalsDialog(rows("A", "B", "C"), False, lambda: [])
    d.show()
    QApplication.processEvents()
    g, tb = d.grip, d.table
    y = lambda r: tb.rowViewportPosition(r) + tb.rowHeight(r) // 2
    vp = g.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(5, y(0)))
    QTest.mouseMove(vp, QPoint(5, y(1)))
    QTest.mouseMove(vp, QPoint(5, y(2)))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(5, y(2)))
    assert [s.name for s in d.signals()] == ["B", "C", "A"]
    d.close()


def test_row_drag_locked_while_running(app):
    d = SignalsDialog(rows("A", "B"), True, lambda: [])
    d.move_row(0, 1)
    assert [s.name for s in d.signals()] == ["A", "B"] and not d.grip.enabled_drag


# --------------------------------------------------- colour profiles + saved configs
def test_profiles_dark_light_system_custom(app, monkeypatch):
    assert th.normalize(None)["profile"] == "dark"
    assert th.normalize({**th.DARK, "profile": "light"})["window_bg"] == th.LIGHT["window_bg"]
    assert th.normalize({**th.LIGHT, "profile": "dark"})["window_bg"] == th.DARK["window_bg"]
    c = th.normalize({**th.DARK, "profile": "custom", "window_bg": "#123456"})
    assert c["window_bg"] == "#123456" and c["profile"] == "custom"
    assert th.normalize({"window_bg": "#123456"})["profile"] == "custom"       # old config without the key
    monkeypatch.setattr(th, "system_is_dark", lambda: True)
    assert th.normalize({"profile": "system"})["window_bg"] == th.DARK["window_bg"]
    monkeypatch.setattr(th, "system_is_dark", lambda: False)
    t = th.normalize({"profile": "system", "font_size": 11})
    assert t["window_bg"] == th.LIGHT["window_bg"] and t["profile"] == "system" and t["font_size"] == 11


def test_save_profile_one_parameter_per_line(app, tmp_path):
    p = str(tmp_path / "moj.json")
    th.save_profile(p, {**th.LIGHT, "font_size": 12, "font_family": "Arial"})
    lines = open(p, encoding="utf-8").read().splitlines()
    assert lines[0] == "{" and lines[-1] == "}"
    body = lines[1:-1]
    from s7trace.core import marker_look
    assert len(body) == 8 + len(th.COLOR_KEYS) + len(marker_look.DEFAULTS) + 4          # profile, font x2, REC blink, bar_always, status_lines, status_align, legend_style + colours + marker look (widths + REC marks) + panel (order, folds, hidden, info_tab)
    import json
    assert all(l.startswith('  "') and len(json.loads("{" + l.rstrip(",") + "}")) == 1 for l in body)       # name: value, nothing else
    assert '  "window_bg": "#f0f0f0",' in body
    got = th.load_profile(p)
    assert got["profile"] == "light" and got["font_size"] == 12 and got["font_family"] == "Arial"
    (tmp_path / "bad.json").write_text("[1,2]")
    with pytest.raises(ValueError):
        th.load_profile(str(tmp_path / "bad.json"))


def test_interface_dialog_profile_and_saved_configs(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    seen = []
    d = InterfaceDialog(th.DARK, lambda t: seen.append(dict(t)))
    assert d.cb_profile.currentData() == "dark"
    d.cb_profile.setCurrentIndex(1)
    d._set_profile(d.cb_profile.currentData())                    # Jasny
    assert seen[-1]["window_bg"] == th.LIGHT["window_bg"] and d.theme["profile"] == "light"
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog, QFileDialog
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a, **k: QColor("#abcdef")))
    d._pick("accent")
    assert d.theme["profile"] == "custom" and d.cb_profile.currentData() == "custom"
    target = str(tmp_path / "S7Trace" / "interfejs" / "niebieski.json")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (target, "")))
    d._save_as()
    assert [n for n, _ in th.list_profiles()] == ["niebieski"] and d.cb_saved.currentText() == "niebieski"
    d._set_profile("dark")
    d._saved_chosen()                                             # picks it from the drop-down again
    assert d.theme["accent"] == "#abcdef" and d.theme["profile"] == "custom"
    assert seen[-1]["accent"] == "#abcdef"


def test_main_window_theme_menus(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    th.save_profile(os.path.join(th.profiles_dir(), "jasna.json"), th.LIGHT)
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    w._fill_saved_menu()
    assert "jasna" in [a.text() for a in w.menu_saved.actions()]
    w._load_theme_file(os.path.join(th.profiles_dir(), "jasna.json"))
    assert w.theme["window_bg"] == th.LIGHT["window_bg"] and w.ui["theme"]["profile"] == "light"
    monkeypatch.setattr(th, "system_is_dark", lambda: True)
    w.set_profile("system")
    assert w.theme["window_bg"] == th.DARK["window_bg"]
    monkeypatch.setattr(th, "system_is_dark", lambda: False)
    w._on_os_scheme()                                             # Windows switched to light
    assert w.theme["window_bg"] == th.LIGHT["window_bg"] and w.theme["profile"] == "system"
    w._fill_profile_menu()
    assert [a.isChecked() for a in w.menu_profile.actions()] == [False, False, True]
    w.close()
    th.apply_theme(QApplication.instance(), th.DARK)


# ------------------------------------------------ adding variables during a running connection
def test_dialog_locked_allows_adding_new_rows_only(app):
    d = SignalsDialog(rows("A", "B"), True, lambda: [])
    assert d.btn_add.isEnabled() and d.btn_sym.isEnabled()
    d._add()
    assert not d._cell(0, "byte").isEnabled() and d._cell(2, "byte").isEnabled()      # new row is editable
    assert d._cell(2, "fetch").isEnabled() and d._cell(2, "source").isEnabled()
    d._cell(2, "byte").setValue(200)
    d.table.selectRow(0)
    d._remove()                                              # existing rows cannot be removed while running
    assert len(d.signals()) == 3
    d.table.selectRow(2)
    d._remove()
    assert len(d.signals()) == 2


def test_tab_appends_signals_live(app, tmp_path):
    cfg = TabConfig()
    cfg.signals = rows("A", "B")
    tab = TraceTab(cfg, lambda: [])
    tab.buffer.append(0.0, [1.0, 0.0])
    tab.state = "running"
    sent = []

    class FakeAcq:
        def update_signals(self, sigs):
            sent.append([s.name for s in sigs])

    tab.acq = FakeAcq()
    tab._run_signals = [Signal.from_dict(s.to_dict()) for s in cfg.signals]
    new = [Signal.from_dict(s.to_dict()) for s in cfg.signals]
    new[0].name = "A2"                                       # attribute change of an old row still applies
    new += [Signal(name="C", source="M", dtype="BYTE", byte=3),
            Signal(name="D", source="M", dtype="BYTE", byte=4, enabled=False)]
    tab.apply_signals(new, True)
    assert [s.name for s in tab.cfg.signals] == ["A2", "B", "C", "D"]
    assert tab.buffer.n == 3 and sent == [["A", "B", "C"]]    # D is not fetched -> no column, no reader change
    assert len(tab.plot.curves) == 3 and tab.cb_tsig.count() == 3
    t, v = tab.buffer.snapshot()
    assert v.shape == (1, 3) and np.isnan(v[0, 2])
    tab.buffer.append(1.0, [1.0, 0.0])                       # in-flight row with the old width
    cur = tab.current_values()
    assert cur[:2] == [1.0, 0.0] and cur[2] != cur[2] and cur[3] is None     # NaN shows as "—" until read
    tab.state = "stopped"
    tab.acq = None
    tab.shutdown()
