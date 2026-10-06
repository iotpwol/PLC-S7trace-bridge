"""v1.21: 'Ukrywanie nieaktywnych' - elements greyed out by another setting hide themselves (per group), the group's menu can show them anyway
until their state changes again; desktop panel (the Web side is in test_web_autohide.py)."""
import pytest
from PySide6.QtWidgets import QApplication, QMenu

from s7trace.core import panel_cfg
from s7trace.ui.theme import apply_dark
from test_rec_marks_ui import db_tab, pump


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def vis(tab, title):
    f = tab._forms[title]
    return [k for r, k in enumerate(tab._row_keys[title]) if k and f.isRowVisible(r)]


def act(tab, action):
    tab.cb_tact.setCurrentIndex(tab.cb_tact.findData(action))
    pump(lambda: False, 0.1)


def menu_actions(tab, title):
    m = QMenu()
    tab._rows_menu(m, title)
    return {a.text(): a for a in m.actions() if a.text()}, m


def test_inactive_elements_hide_and_come_back(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.show()
    act(tab, "Pauza + zapis CSV")
    t = vis(tab, "Trigger")
    assert "Zapis do" in t and "Folder" in t and "Nazwa pliku" in t and "Baza" not in t and "Plik bazy" not in t and "Wartość B" not in t
    act(tab, "Pauza")                                                                   # nothing is saved: everything about the snapshot goes
    t = vis(tab, "Trigger")
    assert not {"Zapis do", "Baza", "Folder", "Nazwa pliku", "Plik bazy"} & set(t) and "Akcja" in t
    act(tab, "Pauza + zapis CSV")
    assert "Zapis do" in vis(tab, "Trigger")                                           # active again: shown again
    tab.cb_tmode.setCurrentIndex(tab.cb_tmode.findData("between")) if tab.cb_tmode.findData("between") >= 0 else tab.cb_tmode.setCurrentText("between")
    pump(lambda: False, 0.1)
    assert "Wartość B" in vis(tab, "Trigger")
    tab.shutdown()


def test_a_hidden_element_can_be_shown_by_hand_until_its_state_changes(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.show()
    act(tab, "Pauza")
    assert "Zapis do" not in vis(tab, "Trigger")
    acts, _m = menu_actions(tab, "Trigger")
    assert not acts["Zapis do"].isChecked()                                              # an auto-hidden element is unchecked in the menu
    acts["Zapis do"].trigger()
    assert "Zapis do" in vis(tab, "Trigger") and not tab.cb_ttarget.isEnabled()          # shown greyed out
    assert tab._hidden["Trigger"] == []                                                  # (not a persisted choice)
    acts, _m = menu_actions(tab, "Trigger")
    assert acts["Zapis do"].isChecked()
    act(tab, "Pauza + zapis CSV")                                                        # the state changes ...
    act(tab, "Pauza")                                                                    # ... and back: hidden again
    assert "Zapis do" not in vis(tab, "Trigger")
    acts, _m = menu_actions(tab, "Trigger")
    acts["Zapis do"].trigger()                                                           # pin again, then unpin by hand
    assert "Zapis do" in vis(tab, "Trigger")
    acts, _m = menu_actions(tab, "Trigger")
    acts["Zapis do"].trigger()
    assert "Zapis do" not in vis(tab, "Trigger") and tab._hidden["Trigger"] == []
    tab.shutdown()


def test_manual_hiding_still_works_and_show_all_pins_the_inactive(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.show()
    act(tab, "Pauza + zapis CSV")
    tab._toggle_row("Trigger", "Folder", False)                                          # an ACTIVE element hidden by hand (persisted)
    assert "Folder" not in vis(tab, "Trigger") and tab._hidden["Trigger"] == ["Folder"]
    act(tab, "Pauza")
    tab._show_all("Trigger")
    t = vis(tab, "Trigger")
    assert {"Zapis do", "Baza", "Folder", "Nazwa pliku", "Plik bazy", "Wartość B"} <= set(t) and tab._hidden["Trigger"] == []
    act(tab, "Pauza + zapis CSV")
    t = vis(tab, "Trigger")
    assert "Zapis do" in t and "Baza" in t              # 'Baza' stayed inactive all the time: its pin stays; 'Zapis do' became active (no pin needed)
    act(tab, "Pauza")
    assert "Zapis do" not in vis(tab, "Trigger") and "Baza" in vis(tab, "Trigger")      # 'Zapis do' changed state: hidden again
    tab.shutdown()


def test_the_switch_is_per_group_and_saved_with_the_panel(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.show()
    act(tab, "Pauza")
    acts, m = menu_actions(tab, "Trigger")
    assert acts["Ukrywanie nieaktywnych"].isCheckable() and acts["Ukrywanie nieaktywnych"].isChecked()
    assert m.actions()[-1].text() == "Ukrywanie nieaktywnych" and m.actions()[-2].isSeparator()             # at the very bottom after a separator
    assert "Ukrywanie nieaktywnych" not in menu_actions(tab, "Sterownik")[0]                                 # groups without greyed elements have none
    acts["Ukrywanie nieaktywnych"].trigger()                                                                  # off: the greyed rows stay visible
    assert "Zapis do" in vis(tab, "Trigger") and tab.panel_state()["autohide"]["Trigger"] is False
    assert tab.panel_state()["autohide"]["Zakres okna wykresu"] is True                                       # the other groups keep theirs
    p = tab.panel_state()
    tab2 = db_tab(tmp_path)
    tab2.show()
    tab2.apply_panel(p)
    act2 = tab2.cb_tact
    act2.setCurrentIndex(act2.findData("Pauza"))
    pump(lambda: False, 0.1)
    assert "Zapis do" in vis(tab2, "Trigger")
    assert panel_cfg.normalize({"autohide": {"Trigger": False}})["autohide"] == {"Połączenie": True, "Zakres okna wykresu": True, "Trigger": False, "Nagrywanie REC": True}
    assert panel_cfg.normalize({"autohide": "x"})["autohide"]["Trigger"] is True
    tab.shutdown()
    tab2.shutdown()


def test_other_groups_hide_their_inactive_elements_too(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.show()
    pump(lambda: False, 0.1)
    z = vis(tab, "Zakres okna wykresu")
    assert "Y min" not in z and "Y max" not in z and "Auto Y" not in z                                         # lanes layout: no manual Y
    tab.cb_ylayout.setCurrentIndex(tab.cb_ylayout.findData("offset"))
    pump(lambda: False, 0.1)
    assert "Auto Y" in vis(tab, "Zakres okna wykresu")
    r = vis(tab, "Nagrywanie REC")
    assert "Folder" not in r and "Nazwa pliku" not in r and "Zapis do" in r                                    # a database target: no file fields
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("csv"))
    pump(lambda: False, 0.1)
    r = vis(tab, "Nagrywanie REC")
    assert "Folder" in r and "Nazwa pliku" in r                                                                # CSV: the file fields work
    tab.shutdown()


def test_locking_the_connection_while_reading_does_not_hide_it(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.show()
    tab.state = "running"
    tab._set_buttons()                                                                                         # the connection fields are frozen
    pump(lambda: False, 0.2)
    assert {"IP", "Rack / Slot", "Cykle [ms]", "Tryb komunik."} <= set(vis(tab, "Połączenie"))
    tab.state = "stopped"
    tab._set_buttons()
    tab.shutdown()


def test_switch_is_part_of_the_interface_configuration_and_menu_separators_follow_the_font(app, tmp_path):
    from s7trace.ui import theme
    t = theme.normalize({"panel": {"autohide": {"Trigger": False, "Połączenie": True}}})
    assert t["panel"]["autohide"]["Trigger"] is False
    path = str(tmp_path / "interface.json")
    theme.save_profile(path, t)
    assert '"panel_autohide"' in open(path, encoding="utf-8").read()                      # one parameter in the interface profile file
    assert theme.load_profile(path)["panel"]["autohide"]["Trigger"] is False
    qss = theme.build_qss(theme.normalize({"menu_text": "#123456"}))
    assert "QMenu::separator" in qss and "background: #123456" in qss.split("QMenu::separator")[1].split("}")[0]   # the colour of the menu text


def test_the_switch_travels_with_the_main_window_theme(app, tmp_path):
    from s7trace.ui.main_window import MainWindow
    w = MainWindow(config_file=str(tmp_path / "c.json"))
    try:
        w.theme = {**w.theme, "panel": {**w.theme["panel"], "autohide": {**w.theme["panel"]["autohide"], "Trigger": False}}}
        tab = w.tabs.widget(0)
        tab.apply_panel(w.theme["panel"])
        assert tab.panel_state()["autohide"]["Trigger"] is False
        w._apply_layouts(tab)
        assert w.theme["panel"]["autohide"]["Trigger"] is False and w._config_dict()["ui"]["theme"]["panel"]["autohide"]["Trigger"] is False
    finally:
        w.close()
