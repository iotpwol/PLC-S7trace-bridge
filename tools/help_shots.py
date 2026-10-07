"""The list of pictures made by make_help_images.py (one function per part of the program).

Every step runs on its own: a step that fails is reported and the others still run (so one changed dialog never loses the rest)."""
from __future__ import annotations

import os
import time
import traceback

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QWidget

H: dict = {}                       # the helpers handed over by make_help_images.py


def pump(n=6, ms=30):
    H["pump"](n, ms)


def shot(w, name, margin=0):
    H["shot"](w, name, margin)


def rect(win, widgets, name, pad=4):
    H["shot_rect"](win, widgets, name, pad)


ONLY = set(filter(None, os.environ.get("HELP_ONLY", "").split(",")))           # e.g. HELP_ONLY=left panel   (steps that start the program always run)
ALWAYS = {"start"}


def step(title, fn, *a):
    if ONLY and title not in ONLY and title not in ALWAYS:
        return
    print(f"{title} ...")
    try:
        fn(*a)
    except Exception:                                      # noqa: BLE001 - a failed picture must not stop the others
        print("  !! FAILED:", title)
        traceback.print_exc()


# ------------------------------------------------------------------------------------------------ menus that block (QMenu.exec)
class ShotMenu(QMenu):
    """A QMenu whose exec() photographs the menu instead of waiting for a click (the name is taken from NAME)."""
    NAME = ["menu"]

    def exec(self, *args):
        pos = next((a for a in args if isinstance(a, QPoint)), QPoint(160, 160))
        self.popup(pos)
        pump(4)
        H["save"](self.grab(), ShotMenu.NAME[0])
        self.hide()
        pump(2)
        return None


def patch_menus():
    from s7trace.ui import main_window, markers_ui, plotview, signals_dialog, store_dialog, trace_tab
    for m in (main_window, markers_ui, plotview, signals_dialog, store_dialog, trace_tab):
        if hasattr(m, "QMenu"):
            m.QMenu = ShotMenu
    markers_ui.TabMarkers._run_menu = staticmethod(lambda menu, pos: (setattr(menu, "_p", 1), _grab_popup(menu, pos)))


def _grab_popup(menu, pos):
    menu.popup(pos if isinstance(pos, QPoint) else QPoint(200, 200))
    pump(4)
    H["save"](menu.grab(), ShotMenu.NAME[0])
    menu.hide()
    pump(2)


def named(name):
    ShotMenu.NAME[0] = name


def popup_of(combo, name, extra=0):
    """The drop-down list of a combo box."""
    combo.showPopup()
    pump(5)
    v = combo.view()
    H["save"](v.window().grab(), name)
    combo.hidePopup()
    pump(2)


def dlg_shot(dlg, name, w=None, h=None, hide=True):
    if w and h:
        dlg.resize(w, h)
    dlg.show()
    pump(8)
    shot(dlg, name)
    if hide:
        dlg.hide()
        pump(2)


# ------------------------------------------------------------------------------------------------ the run
def run(app, win, tab, sim, *, tmp, **helpers) -> None:
    H.update(helpers)
    H["tmp"] = tmp
    H["ip"] = tab.ed_ip.text() or "127.0.0.1:11102"
    H["app"], H["win"], H["tab"] = app, win, tab
    patch_menus()
    step("stopped state", stopped_state)
    step("menus", menus)
    step("start", start_live)
    step("window", main_window)
    step("left panel", left_panel)
    step("combo lists", combo_lists)
    step("panel menus", panel_menus)
    step("chart", chart)
    step("trigger", trigger_state)
    step("markers", markers)
    step("rec marks", rec_marks)
    step("status bar", status_bar)
    step("recordings", recordings)
    step("buttons states", button_states)
    step("dialogs", dialogs)
    step("trigger firings", trigger_firings)
    step("inactive fields", inactive_fields)
    step("tray menu", tray_menu)
    step("pauses", pauses)
    step("diagnostics", diagnostics)
    step("interface dialog", interface_dialog)
    step("wizard + connection", wizard_and_connection)
    step("help window", help_window)


# ------------------------------------------------------------------------------------------------ stage 0: stopped
def stopped_state():
    win, tab = H["win"], H["tab"]
    pump(4)
    shot(win, "okno_glowne_stop")
    for name, file in (("Połączenie", "grp_polaczenie_stop"), ("Sterownik", "grp_sterownik_brak")):
        grp_shot(tab, name, file)
    # the controller box with a message in place of the data (the read failed)
    tab._set_dev_msg("Nie udało się pobrać danych sterownika: Sterownik zerwał połączenie zaraz po jego nawiązaniu (port 102 jest otwarty, odrzucona została sesja S7; próbowano rack/slot: 0/2, 0/1, 0/0, 1/2, 0/3).")
    pump(4)
    grp_shot(tab, "Sterownik", "grp_sterownik_blad")
    tab._dev_msg = ""
    tab._show_device()
    pump(3)
    # an incomplete address: red frame, Start blocked
    keep = tab.ed_ip.text()
    tab.ed_ip.setText("127.0.0")
    pump(3)
    rect(win, [tab.ed_ip], "pole_ip_blad", pad=6)
    tab.ed_ip.setText(keep)
    # the history list of addresses
    from s7trace.core import ip_history
    for a in ("10.12.91.1", "192.168.0.10", "172.16.4.20"):
        ip_history.add(a)
    try:
        tab.ed_ip.showPopup()
        pump(5)
        H["save"](tab.ed_ip.view().window().grab(), "pole_ip_historia")
        tab.ed_ip.hidePopup()
        pump(8)                                            # the popup's own close handling blanks the field once more
    except Exception:                                      # noqa: BLE001
        traceback.print_exc()
    tab.ed_ip.setText(keep)
    pump(3)


def grp_shot(tab, name, file):
    """A group of the left panel, cut below its last row (the box is stretched by the panel layout)."""
    g = tab.folds[name]
    pump(3)
    bottom = 0
    for w in g.findChildren(QWidget):
        if w.isVisibleTo(g) and w.height() > 0:
            bottom = max(bottom, w.mapTo(g, QPoint(0, w.height())).y())
    pm = g.grab()
    h = int(min(g.height(), bottom + 8) * pm.devicePixelRatio())
    H["save"](pm.copy(0, 0, pm.width(), min(pm.height(), h)), file)


# ------------------------------------------------------------------------------------------------ menus
def menus():
    win = H["win"]
    names = {"Plik": "menu_plik", "Widok": "menu_widok", "Diagnostyka": "menu_diagnostyka", "Znaczniki": "menu_znaczniki",
             "Ustawienia": "menu_ustawienia", "Pomoc": "menu_pomoc"}
    for title, file in names.items():
        H["shot_menu"](H["menu_by_title"](win, title), file)
    H["shot_menu"](H["sub_menu"](H["menu_by_title"](win, "Widok"), "Położenie legendy (ta karta)"), "menu_widok_legenda")
    H["shot_menu"](H["sub_menu"](H["menu_by_title"](win, "Widok"), "Nazwy sygnałów na wykresie (ta karta)"), "menu_widok_nazwy")
    st = H["menu_by_title"](win, "Ustawienia")
    H["shot_menu"](H["sub_menu"](st, "Zapisane konfiguracje interfejsu"), "menu_ustawienia_zapisane")
    H["shot_menu"](H["sub_menu"](st, "Profil kolorów"), "menu_ustawienia_profil")


# ------------------------------------------------------------------------------------------------ start
def start_live():
    tab = H["tab"]
    tab.ed_ip.setText(H["ip"])                              # the address tests above played with the field
    pump(2)
    tab.start()
    pump(70, 100)
    pump(1)                                                  # ~7 s of live data from the simulator (above)


def main_window():
    win, tab = H["win"], H["tab"]
    shot(win, "okno_glowne")
    rect(win, [win.menuBar(), win.tabs.bar], "pasek_menu_karty", pad=0)
    rect(win, [tab.btn_start, tab.btn_stop, tab.btn_pause, tab.btn_reset, tab.btn_rec], "przyciski_sterujace", pad=6)
    rect(win, [tab.btn_madd, tab.btn_mrk, tab.btn_msave, tab.btn_find], "przyciski_znacznikow", pad=6)
    rect(win, [tab.btn_sig, tab.btn_diag], "przyciski_sygnaly_diagnostyka", pad=6)
    rect(win, [tab.plot], "wykres", pad=0)               # a grab of the window part: the legend samples keep their colours
    # the tab: a context menu of the tab bar
    bar = win.tabs.bar
    named("menu_karta")
    try:
        win._tab_menu(bar.tabRect(0).center())             # may not exist under this name
    except Exception:                                      # noqa: BLE001
        pass


# ------------------------------------------------------------------------------------------------ left panel
def left_panel():
    tab, win = H["tab"], H["win"]
    win.resize(1500, 1500)                                      # tall enough that no group is squeezed by the scroll area
    pump(8)
    for name, file in (("Połączenie", "grp_polaczenie"), ("Sterownik", "grp_sterownik"), ("Zakres okna wykresu", "grp_zakres"),
                       ("Trigger", "grp_trigger"), ("Nagrywanie REC", "grp_rec")):
        grp_shot(tab, name, file)
    shot(tab.info_tabs, "panel_dol_system")
    tab.info_tabs.setCurrentIndex(1)
    pump(5)
    shot(tab.info_tabs, "panel_dol_siec")
    tab.info_tabs.setCurrentIndex(0)
    # single rows
    rect(tab.folds["Połączenie"], [tab.ed_ip], "pole_ip", pad=6)
    rect(tab.folds["Połączenie"], [tab.sp_rack, tab.sp_slot], "pole_rack_slot", pad=6)
    rect(tab.folds["Połączenie"], [tab.sp_cycle], "pole_cykl", pad=6)
    rect(tab.folds["Połączenie"], [tab.lbl_method], "pole_metoda", pad=6)
    rect(tab.folds["Zakres okna wykresu"], [tab.sp_toff], "pole_offset", pad=6)
    # folded groups
    for n in ("Połączenie", "Sterownik"):
        tab.folds[n].set_folded(True, animate=False)
    pump(6)
    rect(win, [tab._left_scroll], "grp_zwiniete", pad=2)
    for n in ("Połączenie", "Sterownik"):
        tab.folds[n].set_folded(False, animate=False)
    win.resize(1500, 900)
    pump(6)


def combo_lists():
    tab = H["tab"]
    for combo, name in ((tab.cb_mode, "lista_tryb_komunikacji"), (tab.sp_window, "lista_okno_czasu"), (tab.cb_taxis, "lista_os_czasu"),
                        (tab.cb_ylayout, "lista_uklad_osi_y"), (tab.cb_tmode, "lista_trigger_tryb"), (tab.cb_tact, "lista_trigger_akcja"),
                        (tab.cb_rkind, "lista_rec_cel"), (tab.cb_rmode, "lista_rec_probki")):
        try:
            popup_of(combo, name)
        except Exception:                                  # noqa: BLE001
            print("  !! no list for", name)
            traceback.print_exc()


def panel_menus():
    tab = H["tab"]
    named("menu_pole_polaczenie")
    tab._group_menu("Połączenie", QPoint(300, 200))
    named("menu_pole_sterownik")
    tab._group_menu("Sterownik", QPoint(300, 200))
    named("menu_wiersz_ip")
    tab._row_menu("Połączenie", "Adres IP" if "Adres IP" in tab._row_keys.get("Połączenie", []) else "IP", QPoint(300, 200))


# ------------------------------------------------------------------------------------------------ chart
def chart():
    tab, win = H["tab"], H["win"]
    rect(win, [tab.plot], "wykres_pasma", pad=0)               # a grab of the window part: the legend samples keep their colours
    tab.cb_ylayout.setCurrentIndex(1)                      # Offset + Gain
    pump(10, 80)
    rect(win, [tab.plot], "wykres_offset", pad=0)               # a grab of the window part: the legend samples keep their colours
    tab.cb_ylayout.setCurrentIndex(0)
    pump(8, 60)
    try:                                                   # the points of the samples
        tab.act_pts.setChecked(True)
        tab.sp_window.setValue(2.0) if hasattr(tab.sp_window, "setValue") else None
        pump(10, 80)
        rect(win, [tab.plot], "wykres_punkty", pad=0)               # a grab of the window part: the legend samples keep their colours
    finally:
        tab.act_pts.setChecked(False)
        tab.sp_window.setValue(20.0) if hasattr(tab.sp_window, "setValue") else None
        pump(6)
    # the overview strip alone
    ov = getattr(tab.plot, "ov_widget", None) or getattr(tab.plot, "ov", None)
    if ov is not None and hasattr(ov, "grab"):
        shot(ov, "pasek_podgladu")


def trigger_state():
    tab, win = H["tab"], H["win"]
    tab.chk_trig.setChecked(True)
    tab.cb_tsig.setCurrentIndex(max(0, tab.cb_tsig.findText("D160E")))
    tab.cb_tmode.setCurrentIndex(max(0, tab.cb_tmode.findText("rising edge")))
    tab.sp_ta.setValue(0.5)
    tab.sp_tpre.setValue(3.0)
    tab.cb_tact.setCurrentIndex(0)                         # pause
    pump(3)
    grp_shot(tab, "Trigger", "grp_trigger_wlaczony")
    tab.cb_tact.setCurrentIndex(2)                         # the snapshot into a database: the target and its separate SQLite file
    tab.cb_ttarget.setCurrentIndex(tab.cb_ttarget.findData("sqlite"))
    tab.cb_tplace.setCurrentIndex(tab.cb_tplace.findData("own"))
    pump(3)
    grp_shot(tab, "Trigger", "grp_trigger_sqlite")
    tab.cb_ttarget.setCurrentIndex(tab.cb_ttarget.findData("csv"))
    tab.cb_tplace.setCurrentIndex(tab.cb_tplace.findData("shared"))
    tab.cb_tact.setCurrentIndex(0)
    for _ in range(150):                                   # wait for the firing (D160E rises every 4.5 s)
        pump(1, 100)
        if tab.paused:
            break
    pump(10, 100)
    rect(win, [tab.plot], "wykres_trigger", pad=0)               # a grab of the window part: the legend samples keep their colours
    shot(H["win"], "okno_glowne_trigger")
    rect(H["win"], [tab.btn_start, tab.btn_stop, tab.btn_pause, tab.btn_reset, tab.btn_rec], "przyciski_pauza", pad=6)
    tab.btn_pause.setChecked(False)                        # back to live
    tab.chk_trig.setChecked(False)
    pump(10, 100)


# ------------------------------------------------------------------------------------------------ markers
def markers():
    tab, win = H["tab"], H["win"]
    from s7trace.core import markers as mk
    ctl = tab.mk
    dr = ctl.draft
    span = ctl.data_span_us()
    a, b = span
    who = dict(author="OT-engineer", computer="PL-NOW-ADS01", conn=ctl.key(), rec_id=ctl.rec_id())
    x0, x1 = tab.plot.view_range()                           # the markers go inside the visible part of the chart
    w = x1 - x0
    m1 = dr.add(ctl.to_wall(x0 + w * 0.30), kind="point", title="Start nagrzewania", description="Czujnik B zmienił stan na 1",
                color="#ffb347", **who)
    m2 = dr.add(ctl.to_wall(x0 + w * 0.50), end_us=ctl.to_wall(x0 + w * 0.72), kind="range", title="Okno pomiarowe",
                description="Zakres czasu do analizy", notes="Sprawdzić po kalibracji.", color="#4eb8f0", **who)
    m3 = dr.add(ctl.to_wall(x0 + w * 0.76), end_us=ctl.to_wall(x0 + w * 0.90), kind="delta", title="Różnica sinusa", signals=["Sinus"],
                description="Zmiana wartości między dwoma momentami", color="#ff6b6b", **who)
    ctl._changed("Nowy znacznik „Okno pomiarowe” – niezapisany.")
    pump(10, 80)
    rect(win, [tab.plot], "wykres_znaczniki", pad=0)               # a grab of the window part: the legend samples keep their colours
    shot(win, "okno_glowne_znaczniki")
    # horizontal level markers of the chart (menu Znaczniki -> Znacznik poziomu sygnału)
    tab.act_hlev.setChecked(True)
    vr = tab.plot.vb.viewRange()[1]
    tab.plot._add_marker(tab.plot.hmarks, vr[0] + (vr[1] - vr[0]) * 0.07, 0)
    tab.plot._add_marker(tab.plot.hmarks, vr[0] + (vr[1] - vr[0]) * 0.17, 0)
    tab.plot.update_readout()
    pump(8, 80)
    rect(win, [tab.plot], "wykres_poziom_sygnalu", pad=0)               # a grab of the window part: the legend samples keep their colours
    tab.act_hlev.setChecked(False)
    pump(4)
    rect(win, [tab.btn_madd, tab.btn_mrk, tab.btn_msave, tab.btn_find], "przyciski_znacznikow_robocze", pad=6)
    # names of the signals as labels beside the signals instead of the legend box
    named("menu_legenda")
    tab._legend_menu(QPoint(500, 400))
    win._edit_theme({"legend_style": "labels"})
    pump(8, 80)
    rect(win, [tab.plot], "wykres_opisy", pad=0)
    tab.set_legend_mode("address")
    pump(6, 80)
    rect(win, [tab.plot], "wykres_opisy_adres", pad=0)
    tab.set_legend_mode("name")
    named("menu_opis_sygnalu")
    tab._legend_menu(QPoint(500, 400))
    win._edit_theme({"legend_style": "legend"})
    pump(6, 80)
    named("menu_wykres_prawy")
    ctl.chart_menu(3.0, QPoint(500, 400))
    named("menu_znacznik")
    ctl.marker_menu(m2.id, QPoint(500, 400))
    from s7trace.ui.markers_ui import MarkerEditDialog, PendingDialog
    d = MarkerEditDialog(m2, False, win, ctl.signal_names(), ctl.group_names())
    dlg_shot(d, "okno_znacznik_edycja")
    pd = PendingDialog(dr.changes() if hasattr(dr, "changes") else [], "save", win)
    dlg_shot(pd, "okno_zapis_znacznikow")
    ctl.open_list()
    pump(8)
    shot(ctl.dlg, "okno_lista_znacznikow")
    ctl.dlg.hide()
    ctl.open_search()
    pump(8)
    shot(ctl.search_dlg, "okno_szukaj")
    ctl.search_dlg.hide()
    pump(4)




# ------------------------------------------------------------------------------------------------ REC marks
def rec_marks():
    """Start / Stop REC lines (two real recordings into a SQLite file), a Manual REC area and the ghost of a Start REC being moved."""
    tab, win = H["tab"], H["win"]
    from PySide6.QtCore import QPoint
    from s7trace.core import rec_marks as rmk
    from s7trace.core.store import StoreConfig
    from s7trace.ui.markers_ui import PendingDialog
    ctl = tab.mk
    ctl.draft.discard()
    ctl._changed()
    old_store, old_kind = tab.cfg.store, tab.cb_rkind.currentData()
    tab.cfg.store = StoreConfig(kind="sqlite", sqlite_path=os.path.join(H["tmp"], "rec_marks.db"), mode="changes", title_ask="off")
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("sqlite"))
    ctl.rec.new_run()
    for _ in range(2):                                                   # two recordings: Start REC (1) .. Stop REC (1), Start REC (2) .. Stop REC (2)
        tab.btn_rec.setChecked(True)
        pump(14, 100)
        tab.btn_rec.setChecked(False)
        pump(8, 100)
    tab.btn_rec.setChecked(True)
    pump(10, 100)
    x0, x1 = tab.plot.view_range()
    last = tab.buffer.last_time()
    a = ctl.rec.m.auto
    ctl.rec.place(max(x0, a[0]["t0"] - 3.0))                             # a Manual REC area before the first recording
    ctl.rec.place(max(x0, a[0]["t0"] - 3.0) + 1.6)
    pump(10, 80)
    rect(win, [tab.plot], "wykres_rec_znaczniki", pad=0)
    named("menu_rec_start")
    ctl.rec.marker_menu(rmk.pid(rmk.AUTO_START, 1), QPoint(500, 400))
    named("menu_manual_rec")
    ctl.rec.marker_menu(rmk.pid(rmk.MANUAL, 1), QPoint(500, 400))
    named("menu_wykres_manual")
    ctl.chart_menu(last - 1.0, QPoint(500, 400))
    pd = PendingDialog([], "save", win, ctl.rec.manual_rows())
    dlg_shot(pd, "okno_zapis_rec")
    ctl.rec.begin_ghost(2)                                               # the pulsing twin of Start REC (2) is dragged to the left
    tab.plot.ghost.setValue(max(tab.plot.view_range()[0] + 0.5, a[1]["t0"] - 1.3))
    ctl.rec._ghost_moved(float(tab.plot.ghost.value()))
    tab.plot._ghost_on = False
    tab.plot._ghost_pulse()
    pump(8, 80)
    rect(win, [tab.plot], "wykres_rec_duch", pad=0)
    named("menu_rec_duch")
    ctl.rec._ghost_menu(QPoint(500, 400))
    ctl.rec.cancel_ghost()
    # every marker knows its recording: the list with the 'Zapis' column and the question about markers that exist only for the buffer
    st, made = ctl.store, []
    for t, title in ((a[0]["t0"] + 0.4, "Pierwszy rozruch"), (a[1]["t0"] + 0.4, "Alarm temperatury"), (x0 + 0.2, "Obserwacja przed REC"),
                     (x0 + 0.5, "Test zaworu")):
        at = ctl.to_wall(t)
        made.append(st.add(at, author=ctl._who(), computer="PC-STEROWNIA", conn=ctl.key(), rec_id=ctl.rec_id_at(at), title=title))
    ctl.open_list()
    pump(8)
    shot(ctl.dlg, "okno_lista_znacznikow_zapis")
    ctl.dlg.hide()
    from PySide6.QtWidgets import QMessageBox
    real_exec = QMessageBox.exec

    def ask_shot(self):
        self.show()
        pump(8)
        shot(self, "okno_znaczniki_bez_zapisu")
        self.hide()
        next(b for b in self.buttons() if b.text().startswith("Zostaw")).click()
        return 0
    QMessageBox.exec = ask_shot
    try:
        ctl.confirm_buffer("close")
    finally:
        QMessageBox.exec = real_exec
    st.delete_many([m.id for m in made])
    ctl._changed()
    tab.btn_rec.setChecked(False)
    pump(8, 100)
    for m in list(ctl.rec.m.manual):
        ctl.rec.remove(m["n"])
    ctl.rec.new_run()
    tab.cfg.store = old_store
    tab.cb_rkind.setCurrentIndex(max(tab.cb_rkind.findData(old_kind), 0))
    pump(6, 80)


# ------------------------------------------------------------------------------------------------ status bar
def status_bar():
    tab, win = H["tab"], H["win"]
    shot(tab.lbl_status, "pasek_statusu")
    tab._status_menu(QPoint(400, 300))
    pump(4)
    menu = tab._status_popup
    H["save"](menu.grab(), "menu_pasek_statusu")
    for a in menu.actions():
        if a.menu() is not None:
            sub = a.menu()
            sub.popup(QPoint(520, 320))
            pump(4)
            H["save"](sub.grab(), "menu_pasek_" + ("wiersze" if "wierszy" in a.text() else "justowanie"))
            sub.hide()
    menu.close()
    pump(2)
    # a long message, three lines, left aligned
    win._edit_theme({"status_lines": 3, "status_align": "left"})
    tab.status_msg = ("Zegar PLC różni się od zegara komputera o -3650 d 00:00:00.000. W polu „Offset osi” (prawy przycisk → „Wyrównaj czas PLC do czasu "
                      "komputera”) możesz to skorygować na osi „Czas PLC”. Połączono z 127.0.0.1 (rack=0, slot=2). Zapis REC: 12 345 wpisów.")
    pump(6)
    rect(win, [tab.lbl_status], "pasek_statusu_3_wiersze", pad=2)
    win._edit_theme({"status_lines": 1, "status_align": "right"})
    tab.status_msg = "Połączono z 127.0.0.1 (rack=0, slot=2)."
    pump(4)


# ------------------------------------------------------------------------------------------------ recordings in a database
def recordings():
    tab, win = H["tab"], H["win"]
    from PySide6.QtWidgets import QTabWidget
    from s7trace.core import store as st
    from s7trace.ui import store_dialog as sd
    data = os.path.join(H["tmp"], "documents")
    tab.cfg.store.sqlite_path = "nagrania.db"            # relative: the folder <Documents>\S7Trace of the user
    tab.cfg.store.title_ask = "off"
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("sqlite"))
    pump(4)
    grp_shot(tab, "Nagrywanie REC", "grp_rec_sqlite")
    for n in range(3):
        tab.btn_rec.setChecked(True)
        pump(50 if n else 40, 100)
        if n == 0:
            rect(win, [tab.btn_start, tab.btn_stop, tab.btn_pause, tab.btn_reset, tab.btn_rec], "przyciski_rec_aktywny", pad=6)
            shot(tab.lbl_status, "pasek_statusu_rec")
            shot(win, "okno_glowne_rec")
        tab.btn_rec.setChecked(False)
        pump(10, 100)
    b = st.open_backend(tab.cfg.store, data)
    try:
        ss = sorted(b.sessions(), key=lambda s: s["start_us"])
        meta = [("Próba nagrzewania", "Czujniki A–E, praca ciągła", "piec, test", "Nagranie wzorcowe po wymianie czujnika B."),
                ("", "", "", ""), ("Awaria wentylatora", "Zatrzymanie po alarmie", "alarm, wentylator", "Sprawdzić łożysko.")]
        for s, (title, desc, tags, notes) in zip(ss, meta):
            b.update_session(s["id"], {"title": title, "description": desc, "tags": tags, "notes": notes})
    finally:
        b.close()
    d = sd.StoreImportDialog(tab.cfg.store, win, can_load=True, base_dir=data)
    d.resize(1250, 640)
    d.show()
    pump(10)
    d.refresh()
    pump(10)
    shot(d, "okno_przeglad_nagran")
    d.hide()
    ri = sd.RecInfoDialog(title="Próba nagrzewania", notes="Nagranie wzorcowe po wymianie czujnika B.", tags="piec, test",
                          heading="Nagranie zakończone", ok_text="Zapisz", cancel_text="Pomiń", parent=win, description="Czujniki A–E, praca ciągła")
    dlg_shot(ri, "okno_opis_nagrania")
    for kind, label in (("sqlite", "baza_sqlite"), ("influx2", "baza_influx"), ("timescale", "baza_timescale")):
        try:
            dlg = sd.StoreDialog(tab.cfg.store, kind, win)
        except Exception:                                  # noqa: BLE001
            traceback.print_exc()
            continue
        tw = dlg.findChild(QTabWidget)
        dlg.show()
        pump(6)
        if tw is not None and kind == "sqlite":
            for i in range(tw.count()):
                tw.setCurrentIndex(i)
                pump(4)
                shot(dlg, f"okno_{label}_karta{i + 1}")
        else:
            shot(dlg, f"okno_{label}")
        dlg.hide()
    sp = sd.SpoolDialog(tab.cfg.store, data, win)
    dlg_shot(sp, "okno_bufory_zapisu")
    tab.cb_rkind.setCurrentIndex(tab.cb_rkind.findData("csv"))
    pump(3)


def button_states():
    tab, win = H["tab"], H["win"]
    tab.btn_pause.setChecked(True)
    pump(4)
    rect(win, [tab.btn_start, tab.btn_stop, tab.btn_pause, tab.btn_reset, tab.btn_rec], "przyciski_pauza", pad=6)
    tab.btn_pause.setChecked(False)
    pump(3)
    from s7trace.ui.reset_button import countdown_label
    tab.btn_reset.setText(countdown_label(2.05))                         # held for 2 s: 'Reset (2s)'
    pump(3)
    rect(win, [tab.btn_start, tab.btn_stop, tab.btn_pause, tab.btn_reset, tab.btn_rec], "przyciski_reset_odliczanie", pad=6)
    tab.btn_reset.set_auto(True)                                          # held for 4 s: latched as 'Auto-Reset' (blue text)
    pump(3)
    rect(win, [tab.btn_start, tab.btn_stop, tab.btn_pause, tab.btn_reset, tab.btn_rec], "przyciski_auto_reset", pad=6)
    tab.btn_reset.set_auto(False)
    pump(3)


# ------------------------------------------------------------------------------------------------ dialogs
def dialogs():
    tab, win = H["tab"], H["win"]
    from s7trace.core.symbols import Symbol
    from s7trace.ui import main_window as mw
    from s7trace.ui.marker_look_dialog import MarkerLookDialog
    from s7trace.ui.render_dialog import RenderDialog
    from s7trace.ui.sessions_dialog import SessionsDialog
    from s7trace.ui.signals_dialog import SignalsDialog, SymbolPicker
    from s7trace.ui.web_server_dialog import WebServerDialog
    opts = {"autonumber": tab.cfg.autonumber, "name_mode": tab.cfg.name_mode, "own_name": tab.cfg.own_name, "offset_step": tab.cfg.offset_step}
    d = SignalsDialog(tab.cfg.signals, True, tab.symbols, opts, tab.current_values, tab.other_tabs, {}, None, win)
    d.resize(1280, 520)
    d.show()
    pump(10)
    d.table.selectRow(2)
    shot(d, "okno_sygnaly_praca")
    named("menu_naglowek_kolumny")
    d._header_menu(QPoint(400, 300))
    d.hide()
    d2 = SignalsDialog(tab.cfg.signals, False, tab.symbols, opts, None, tab.other_tabs, {}, None, win)
    d2.resize(1280, 520)
    d2.show()
    pump(8)
    shot(d2, "okno_sygnaly_stop")
    d2.hide()
    syms = [Symbol(f"Czujnik_{i}", "DB", "BOOL", 1, 160, i % 8, "Czujnik z linii 1") for i in range(8)] + \
           [Symbol("Licznik_cykli", "DB", "INT", 1, 170, 0, "Licznik"), Symbol("Temperatura", "DB", "REAL", 1, 172, 0, "Temperatura pieca")]
    sp = SymbolPicker(syms, win)
    dlg_shot(sp, "okno_symbole", 620, 420)
    dlg_shot(RenderDialog(win.render_cfg, lambda c: None, win), "okno_renderowanie")
    dlg_shot(MarkerLookDialog(win.marker_look, lambda c: None, win), "okno_wyglad_znacznikow")
    H["tab"].ed_ip.setText(H["ip"])                             # (a recording loaded earlier may have changed it); the registry heartbeat is 2 s
    pump(30, 100)
    dlg_shot(SessionsDialog(win.registry, win), "okno_sesje", 900, 360)
    dlg_shot(WebServerDialog(win.web_cfg, win), "okno_serwer_web")
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Information, "O programie", "\n".join(mw.about_lines()), parent=win)
    box.show()
    pump(6)
    shot(box, "okno_o_programie")
    box.hide()
    box = QMessageBox(QMessageBox.Information, "Rack / Slot", mw.RACK_SLOT_HELP, parent=win)
    box.show()
    pump(6)
    shot(box, "okno_rack_slot")
    box.hide()


def diagnostics():
    tab, win = H["tab"], H["win"]
    from PySide6.QtWidgets import QTabWidget
    tab.open_diag()
    pump(12, 100)
    dlg = tab.diag_dlg
    dlg.resize(1000, 800)
    pump(8)
    tw = dlg.findChild(QTabWidget)
    names = ["opoznienia", "pakiety", "przepustowosc", "obciazenie", "wykresy"]
    for i in range(tw.count()):
        tw.setCurrentIndex(i)
        pump(8, 100)
        shot(dlg, f"okno_diagnostyka_{names[i] if i < len(names) else i}")
    tw.setCurrentIndex(0)
    dlg.close()


def interface_dialog():
    win = H["win"]
    from s7trace.ui.interface_dialog import InterfaceDialog
    d = InterfaceDialog(win.theme, lambda t: None, win)
    d.resize(760, 900)
    d.show()
    pump(10)
    shot(d, "okno_interfejs")
    from PySide6.QtWidgets import QScrollArea
    sc = d.findChildren(QScrollArea)
    if sc:
        sc[0].verticalScrollBar().setValue(sc[0].verticalScrollBar().maximum())
        pump(5)
        shot(d, "okno_interfejs_dol")
    d.hide()


def wizard_and_connection():
    tab, win = H["tab"], H["win"]
    from PySide6.QtWidgets import QTabWidget
    from s7trace.ui.conn_dialog import ConnectionDialog
    from s7trace.ui.wizard_dialog import WizardDialog
    tab.stop()
    pump(20, 100)
    tab.ed_ip.setText("127.0.0.1")                           # the wizard probes the standard ports (102 ...)
    c = ConnectionDialog(tab, win)
    c.show()
    pump(6)
    shot(c, "okno_metoda_polaczenia")
    for i, label in ((2, "opcua"), (3, "webapi"), (4, "modbus")):
        c.cb_type.setCurrentIndex(i)
        pump(4)
        shot(c, f"okno_metoda_{label}")
    c.hide()
    w = WizardDialog(tab, parent=win)
    w.show()
    for _ in range(300):
        pump(1, 100)
        if w.result is not None:
            break
    pump(8)
    tw = w.findChild(QTabWidget)
    shot(w, "okno_kreator_wyniki")
    if tw is not None:
        for i in range(1, tw.count()):
            tw.setCurrentIndex(i)
            pump(5)
            shot(w, f"okno_kreator_karta{i + 1}")
    w.hide()


def _wait_firings(tab, n, limit=400):
    """Waits (real time) until the trigger has fired `n` times."""
    for _ in range(limit):
        pump(1, 100)
        if tab.trig_n >= n:
            break


def trigger_firings():
    """TRIG (n): the trigger fires several times in one run (action 'Zapis CSV' does not pause the chart) - every firing keeps its numbered line."""
    tab, win = H["tab"], H["win"]
    tab.mk.confirm_buffer = lambda *a, **k: True
    if tab.btn_rec.isChecked():
        tab.btn_rec.setChecked(False)
    tab.chk_trig.setChecked(False)
    tab.cb_tact.setCurrentIndex(1)                          # 'Zapis CSV': the chart goes on, the trigger arms itself again (pretrigger = window: no waiting after a firing)
    tab.ed_tfolder.setText(os.path.join(H["tmp"], "snapshots"))
    tab.cb_tsig.setCurrentIndex(max(0, tab.cb_tsig.findText("D160E")))
    tab.cb_tmode.setCurrentIndex(max(0, tab.cb_tmode.findText("rising edge")))
    tab.sp_ta.setValue(0.5)
    tab.sp_window.setValue(50.0)
    tab.sp_tpre.setValue(50.0)
    tab.chk_trig.setChecked(True)
    tab.trig_n = 0
    tab._clear_trig()
    _wait_firings(tab, 3, 900)
    pump(6, 100)
    rect(win, [tab.plot], "wykres_trigger_kilka", pad=0)
    tab.chk_trig.setChecked(False)
    tab.cb_tact.setCurrentIndex(0)
    pump(4)


def inactive_fields():
    """Fields that another setting switches off: hidden by default (v1.21), or greyed out (Interfejs -> Elementy nieaktywne)."""
    tab, win = H["tab"], H["win"]
    tab.chk_trig.setChecked(False)
    pump(4)
    grp_shot(tab, "Trigger", "grp_trigger_ukryte")
    tab.apply_panel({**tab.panel_state(), "inactive": "grey"})
    pump(6)
    grp_shot(tab, "Trigger", "grp_trigger_wyszarzone")
    named("menu_grupa_ukrywanie")
    tab._group_menu("Trigger", QPoint(300, 300))
    tab.apply_panel({**tab.panel_state(), "inactive": "hide"})
    pump(4)
    tab.cb_tmode.setCurrentIndex(max(0, tab.cb_tmode.findText("between")))
    pump(4)
    grp_shot(tab, "Trigger", "grp_trigger_between")
    tab.cb_tmode.setCurrentIndex(max(0, tab.cb_tmode.findText("rising edge")))
    tab.cb_tact.setCurrentIndex(1)
    pump(4)
    grp_shot(tab, "Trigger", "grp_trigger_zapis_csv")
    tab.cb_tact.setCurrentIndex(0)
    pump(3)


def tray_menu():
    """The menu of the program's icon next to the clock."""
    win = H["win"]
    tc = win.tray
    tc.refresh()
    pump(4)
    tc.menu.popup(QPoint(200, 200))
    pump(6)
    H["save"](tc.menu.grab(), "menu_zegar")
    tc.menu.hide()
    pump(2)


def pauses():
    """The three ways to show a pause between Stop and Start of the reading, and the dialog that sets them."""
    tab, win = H["tab"], H["win"]
    ctl = tab.mk
    ctl.confirm_buffer = lambda *a, **k: True
    if tab.btn_rec.isChecked():
        tab.btn_rec.setChecked(False)
        pump(6, 100)
    tab.chk_trig.setChecked(False)
    tab.sp_window.setValue(30.0)
    tab.btn_reset.set_auto(True)                           # a fresh chart for this part: the first Start clears it
    tab.stop()
    pump(6, 100)
    tab.start()
    pump(45, 100)
    tab.btn_reset.set_auto(False)                          # the next Start continues the chart and leaves a gap
    tab.stop()
    pump(60, 100)                                           # ~6 s of pause
    tab.start()
    pump(60, 100)
    tab.set_gap_mode("full", 40)
    pump(8, 80)
    rect(win, [tab.plot], "wykres_przerwa_pelna", pad=0)
    tab.set_gap_mode("join", 40)
    pump(8, 80)
    rect(win, [tab.plot], "wykres_przerwa_wyciecie", pad=0)
    tab.set_gap_mode("fixed", 60)
    pump(8, 80)
    rect(win, [tab.plot], "wykres_przerwa_pas", pad=0)
    H["shot_menu"](H["sub_menu"](H["menu_by_title"](win, "Widok"), "Przerwy Stop → Start (ta karta)"), "menu_widok_przerwy")
    from s7trace.ui.gap_dialog import GapDialog
    d = GapDialog(tab.cfg.gap_mode, tab.cfg.gap_px, win.marker_look, lambda m, p: None, lambda lk: None, win)
    dlg_shot(d, "okno_wyglad_przerw")
    tab.set_gap_mode("full", 40)
    pump(4)


def help_window():
    win = H["win"]
    win.help_mode.set_active(True)
    pump(6)
    rect(win, [win.menuBar()], "pasek_menu_tryb_pomocy", pad=0)
    win.help_mode.set_active(False)
