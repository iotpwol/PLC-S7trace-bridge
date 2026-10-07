"""Layout of the left settings panel (a part of the interface configuration): the order of its groups, which of them are folded, which
elements (rows) of a group are hidden and which of the two bottom tabs (System / Sieć) is shown. Qt-free; the same structure is kept
for a Web account (web/prefs.py) with the row names of the Web editor (WEB_ROWS)."""
from __future__ import annotations

GROUPS = ("Połączenie", "Sterownik", "Zakres okna wykresu", "Trigger", "Nagrywanie REC")
INFO_TABS = 2                                              # System, Sieć

INFO_GROUPS = ("System", "Sieć")                           # the two bottom tabs: their rows can be hidden too

# elements of every group = the labels of the rows (without the colon); a row without a label is named after its content
DEVICE_KEYS = (("Rodzina", "family"), ("Model", "model"), ("Numer katalogowy (MLFB)", "order_code"), ("Firmware", "firmware"),
               ("Numer seryjny", "serial"), ("Nazwa stacji", "plc_name"), ("Nazwa modułu", "module_name"),
               ("Producent / copyright", "copyright"), ("Stan CPU", "state"), ("Długość PDU [B]", "pdu"))       # row name -> device["info"] key
PLC_TIME_ROW = "Czas PLC"
ROWS = {
    "Połączenie": ("IP", "Rack / Slot", "Cykle [ms]", "Tryb komunik.", "Metoda"),
    "Sterownik": tuple(k for k, _ in DEVICE_KEYS) + (PLC_TIME_ROW, "Pobierz dane"),
    "Zakres okna wykresu": ("Okno czasu [s]", "Oś czasu", "Offset osi", "Układ osi Y", "Auto Y", "Y min", "Y max"),
    "Trigger": ("Włącz trigger", "Sygnał", "Tryb", "Wartość A", "Wartość B", "Histereza", "Pretrigger [s]", "Akcja", "Zapis do", "Baza", "Folder", "Nazwa pliku", "Plik bazy"),
    "Nagrywanie REC": ("Zapis do", "Próbki", "Folder", "Nazwa pliku"),
    "System": ("Godzina systemowa", "System operacyjny", "Obciążenie CPU", "w tym ta aplikacja", "GUI lag"),
    "Sieć": ("PLC comm lag Avg", "PLC comm lag Last", "Missed", "Ping"),
}
WEB_ROWS = {                                               # the Web editor has its own field names (static/index.html, data-row)
    "Połączenie": ("Nazwa", "Adres IP", "Rack", "Slot", "Cykl [ms]", "Sposób połączenia", "Tryb odczytu", "Kreator"),
    "Sterownik": tuple(k for k, _ in DEVICE_KEYS) + (PLC_TIME_ROW, "Pobierz dane"),
    "Zakres okna wykresu": ("Okno czasu [s]", "Układ wykresu", "Auto Y", "Y min", "Y maks", "Punkty", "Legenda", "Oś czasu", "Offset osi"),
    "Trigger": ("Włączony", "Sygnał", "Warunek", "A", "B", "Histereza", "Przedtrigger [s]", "Akcja", "Zapis snapshotu do", "Baza snapshotów", "Nazwa pliku zapisu", "Plik bazy snapshotów"),
    "Nagrywanie REC": ("Cel zapisu", "Tryb", "Nazwa pliku CSV"),
    "System": ("Godzina systemowa", "System operacyjny", "Obciążenie CPU", "w tym ten serwer"),
    "Sieć": ("Czas odczytu śr.", "Czas odczytu ost.", "Pominięte cykle", "Ping"),
}
# the controller box shows the basic data; the rest (the same data as in the wizard's 'Sterownik i czas' tab) is hidden until asked for
DEFAULT_HIDDEN = {"Sterownik": ["Numer katalogowy (MLFB)", "Numer seryjny", "Producent / copyright", "Stan CPU", "Długość PDU [B]"]}
ALL_GROUPS = GROUPS + INFO_GROUPS
# groups whose elements get greyed out when another setting makes them useless: with "Ukrywanie nieaktywnych" (per group, on by default) such an
# element is hidden automatically; the group's menu can show it anyway (until it becomes inactive again)
AUTOHIDE_GROUPS = ("Połączenie", "Zakres okna wykresu", "Trigger", "Nagrywanie REC")
INACTIVE_MODES = ("hide", "grey")                          # what an inactive element does: "hide" = disappears (default), "grey" = stays, greyed out (Interfejs)

DEFAULTS = {"order": list(GROUPS), "folds": {g: False for g in GROUPS},
            "hidden": {g: list(DEFAULT_HIDDEN.get(g, [])) for g in ALL_GROUPS}, "info_tab": 0, "autohide": {g: True for g in AUTOHIDE_GROUPS},
            "inactive": "hide"}


def normalize(raw, rows: dict = ROWS) -> dict:
    """Valid layout: every group exactly once (unknown names dropped, missing ones appended in the default order); hidden rows only
    from the known ones of `rows` (ROWS = program, WEB_ROWS = browser); a group without a saved list gets the default one."""
    raw = raw if isinstance(raw, dict) else {}
    order: list[str] = []
    for g in raw.get("order") or []:
        if g in GROUPS and g not in order:
            order.append(g)
    order += [g for g in GROUPS if g not in order]
    folds_in = raw.get("folds") if isinstance(raw.get("folds"), dict) else {}
    folds = {g: bool(folds_in.get(g, False)) for g in GROUPS}
    hid_in = raw.get("hidden") if isinstance(raw.get("hidden"), dict) else {}
    hidden = {}
    for g in ALL_GROUPS:
        want = hid_in.get(g) if isinstance(hid_in.get(g), (list, tuple)) else DEFAULT_HIDDEN.get(g, [])
        hidden[g] = [k for k in rows.get(g, ()) if k in want]            # known rows only, in the order of the panel
    try:
        tab = int(raw.get("info_tab", 0))
    except (TypeError, ValueError):
        tab = 0
    auto_in = raw.get("autohide") if isinstance(raw.get("autohide"), dict) else {}
    autohide = {g: bool(auto_in.get(g, True)) for g in AUTOHIDE_GROUPS}
    return {"order": order, "folds": folds, "hidden": hidden, "info_tab": tab if 0 <= tab < INFO_TABS else 0, "autohide": autohide,
            "inactive": raw.get("inactive") if raw.get("inactive") in INACTIVE_MODES else "hide"}
