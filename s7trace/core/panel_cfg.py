"""Layout of the left settings panel (a part of the interface configuration): the order of its groups, which of them are folded, which
elements (rows) of a group are hidden and which of the two bottom tabs (System / Sieć) is shown. Qt-free; the same structure is kept
for a Web account (web/prefs.py) with the row names of the Web editor (WEB_ROWS)."""
from __future__ import annotations

GROUPS = ("Połączenie", "Sterownik", "Zakres okna wykresu", "Trigger", "Nagrywanie REC")
INFO_TABS = 2                                              # System, Sieć

# elements of every group = the labels of the rows (without the colon); a row without a label is named after its content
ROWS = {
    "Połączenie": ("IP", "Rack / Slot", "Cykle [ms]", "Tryb komunik.", "Metoda"),
    "Sterownik": ("Dane sterownika", "Pobierz dane"),
    "Zakres okna wykresu": ("Okno czasu [s]", "Oś czasu", "Offset osi", "Układ osi Y", "Auto Y", "Y min", "Y max"),
    "Trigger": ("Włącz trigger", "Sygnał", "Tryb", "Wartość A", "Wartość B", "Histereza", "Pretrigger [s]", "Akcja", "Folder", "Nazwa pliku"),
    "Nagrywanie REC": ("Zapis do", "Próbki", "Folder", "Nazwa pliku"),
}
WEB_ROWS = {                                               # the Web editor has its own field names (static/index.html, data-row)
    "Połączenie": ("Nazwa", "Adres IP", "Rack", "Slot", "Cykl [ms]", "Sposób połączenia", "Tryb odczytu", "Kreator"),
    "Sterownik": ("Dane sterownika", "Pobierz dane"),
    "Zakres okna wykresu": ("Okno czasu [s]", "Układ wykresu", "Auto Y", "Y min", "Y maks", "Punkty", "Legenda", "Oś czasu", "Offset osi"),
    "Trigger": ("Włączony", "Sygnał", "Warunek", "A", "B", "Histereza", "Przedtrigger [s]", "Akcja", "Nazwa pliku zapisu"),
    "Nagrywanie REC": ("Cel zapisu", "Tryb", "Nazwa pliku CSV"),
}

DEFAULTS = {"order": list(GROUPS), "folds": {g: False for g in GROUPS}, "hidden": {g: [] for g in GROUPS}, "info_tab": 0}


def normalize(raw, rows: dict = ROWS) -> dict:
    """Valid layout: every group exactly once (unknown names dropped, missing ones appended in the default order); hidden rows only
    from the known ones of `rows` (ROWS = program, WEB_ROWS = browser)."""
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
    for g in GROUPS:
        want = hid_in.get(g) if isinstance(hid_in.get(g), (list, tuple)) else []
        hidden[g] = [k for k in rows.get(g, ()) if k in want]            # known rows only, in the order of the panel
    try:
        tab = int(raw.get("info_tab", 0))
    except (TypeError, ValueError):
        tab = 0
    return {"order": order, "folds": folds, "hidden": hidden, "info_tab": tab if 0 <= tab < INFO_TABS else 0}
