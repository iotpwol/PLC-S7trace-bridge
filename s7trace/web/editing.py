"""Editing of a connection's configuration from the browser: the editable view of a TabConfig and a validated patch.
Every value coming from the network is checked here (types, ranges, lengths) before it reaches the acquisition."""
from __future__ import annotations

import os
import re

from ..core import planner, store as store_mod, trigger as trig
from ..core.config import GAP_MODES, GAP_PX_MAX, GAP_PX_MIN, TabConfig, conn_defaults
from ..core.drivers import CONN_TYPES, SOURCE_OF
from ..core.types import ALL_SOURCES, DEFAULT_COLORS, FORMATS, TIME_OFFSET_MAX, TYPES, Signal
from . import files

MAX_SIGNALS = 200
CONN_KINDS = [k for k, _ in CONN_TYPES]
MODES = [planner.MODE_BLOCKS, planner.MODE_SINGLE, planner.MODE_MULTI]
# changing these while the connection runs would not reach the running acquisition process
STRUCTURAL = ("ip", "rack", "slot", "cycle_ms", "conn_type", "conn", "mode", "signals")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_HOST = re.compile(r"[A-Za-z0-9_.:\-\[\]]{1,100}")
_CONN_KEYS = {k: type(v) for k, v in conn_defaults().items()}
_SECRET = ("password", "key")


class EditError(ValueError):
    """A message that may be shown to the user as it is."""


def _num(d: dict, key: str, lo: float, hi: float, label: str, kind=int):
    try:
        v = kind(d[key])
    except (TypeError, ValueError):
        raise EditError(f"{label}: podaj liczbę.") from None
    if not lo <= v <= hi or v != v:
        raise EditError(f"{label}: dozwolony zakres {lo}…{hi}.")
    return v


def _text(d: dict, key: str, maxlen: int, label: str, required: bool = False) -> str:
    v = d[key]
    if not isinstance(v, str):
        raise EditError(f"{label}: podaj tekst.")
    v = v.strip()
    if required and not v:
        raise EditError(f"{label}: nie może być puste.")
    if len(v) > maxlen:
        raise EditError(f"{label}: najwyżej {maxlen} znaków.")
    return v


def view(cfg: TabConfig, web: dict | None = None, targets: list[str] | None = None) -> dict:
    """What the editor shows. Passwords are never sent back (only whether one is stored)."""
    conn = {k: v for k, v in cfg.conn.items() if k not in _SECRET}
    conn["has_password"] = bool(cfg.conn.get("password"))
    t = cfg.trigger
    return {"name": cfg.name, "ip": cfg.ip, "rack": cfg.rack, "slot": cfg.slot, "cycle_ms": cfg.cycle_ms,
            "conn_type": cfg.conn_type, "conn": conn, "mode": cfg.mode, "window_s": cfg.window_s,
            "legend_mode": cfg.legend_mode, "legend_style": cfg.legend_style, "time_axis": cfg.time_axis, "time_offset": cfg.time_offset, "y_layout": cfg.y_layout, "auto_y": cfg.auto_y, "y_min": cfg.y_min, "y_max": cfg.y_max, "show_points": cfg.show_points, "auto_reset": cfg.auto_reset, "gap_mode": cfg.gap_mode, "gap_px": cfg.gap_px,
            "signals": [s.to_dict() for s in cfg.signals],
            "trigger": {"enabled": t.enabled, "signal": t.signal, "mode": t.mode, "a": t.a, "b": t.b, "hysteresis": t.hysteresis,
                        "pretrigger": t.pretrigger, "action": t.action, "filename": t.filename,
                        "target": t.target, "place": t.place, "db_file": t.db_file},
            "rec": {"target": (web or {}).get("rec_target", "csv"), "mode": cfg.store.mode, "filename": cfg.rec_filename},
            "options": {"conn_types": CONN_TYPES, "modes": MODES, "sources": ALL_SOURCES, "dtypes": list(TYPES),
                        "formats": FORMATS, "source_of": SOURCE_OF, "trigger_modes": trig.MODES, "trigger_actions": trig.ACTIONS,
                        "rec_targets": ["csv", "sqlite"] + list(targets or []), "rec_modes": store_mod.MODES,
                        "placeholders": list(files.PLACEHOLDERS)}}


def signal_from(d) -> Signal:
    if not isinstance(d, dict):
        raise EditError("Sygnał: niepoprawne dane.")
    label = f"Sygnał „{str(d.get('name', ''))[:30]}”"
    out = {}
    if "name" in d:
        out["name"] = _text(d, "name", 64, "Nazwa sygnału", True)
    if "source" in d:
        if d["source"] not in ALL_SOURCES:
            raise EditError(f"{label}: nieznane źródło.")
        out["source"] = d["source"]
    if "dtype" in d:
        if d["dtype"] not in TYPES:
            raise EditError(f"{label}: nieznany typ.")
        out["dtype"] = d["dtype"]
    for k, lo, hi in (("db", 0, 65535), ("byte", 0, 65535), ("bit", 0, 7)):
        if k in d:
            out[k] = _num(d, k, lo, hi, f"{label}: {k}")
    for k, lo, hi in (("offset_y", -1e9, 1e9), ("gain", -1e9, 1e9), ("share", 0.1, 100)):
        if k in d:
            out[k] = _num(d, k, lo, hi, f"{label}: {k}", float)
    if "color" in d:
        if not isinstance(d["color"], str) or not _COLOR.fullmatch(d["color"]):
            raise EditError(f"{label}: kolor w postaci #rrggbb.")
        out["color"] = d["color"].lower()
    if "comment" in d:
        out["comment"] = _text(d, "comment", 200, "Opis")
    if "node" in d:
        out["node"] = _text(d, "node", 500, "Węzeł / zmienna")
    if "fmt" in d:
        if d["fmt"] not in FORMATS:
            raise EditError(f"{label}: nieznany sposób wyświetlania.")
        out["fmt"] = d["fmt"]
    for k in ("enabled", "plot"):
        if k in d:
            out[k] = bool(d[k])
    return Signal.from_dict(out)


def apply(cfg: TabConfig, patch: dict, running: bool, web: dict | None = None, recording: bool = False,
          targets: list[str] | None = None) -> list[str]:
    """Validates `patch` and applies it to `cfg` (all or nothing); returns the changed keys. `web` receives the
    settings that exist only in the web mode (REC target)."""
    if not isinstance(patch, dict):
        raise EditError("Niepoprawne dane.")
    new: dict = {}
    if "name" in patch:
        new["name"] = _text(patch, "name", 64, "Nazwa")
    if "ip" in patch:
        v = _text(patch, "ip", 100, "Adres IP", True)
        if not _HOST.fullmatch(v):
            raise EditError("Adres IP: dozwolone cyfry, litery, kropki i dwukropek (port).")
        new["ip"] = v
    if "rack" in patch:
        new["rack"] = _num(patch, "rack", 0, 7, "Rack")
    if "slot" in patch:
        new["slot"] = _num(patch, "slot", 0, 31, "Slot")
    if "cycle_ms" in patch:
        new["cycle_ms"] = _num(patch, "cycle_ms", 5, 60000, "Cykl [ms]")
    if "window_s" in patch:
        new["window_s"] = _num(patch, "window_s", 1, 86400, "Okno czasu [s]", float)
    if "y_layout" in patch:                                   # the look of the chart: allowed while running, too
        if patch["y_layout"] not in ("lanes", "offset"):
            raise EditError("Układ wykresu: „lanes” albo „offset”.")
        new["y_layout"] = patch["y_layout"]
    if "legend_mode" in patch:
        if patch["legend_mode"] not in ("name", "address"):
            raise EditError("Legenda: „name” albo „address”.")
        new["legend_mode"] = patch["legend_mode"]
    if "legend_style" in patch:                               # signal names on the chart: legend / labels ("" = the account's default)
        if patch["legend_style"] not in ("", "legend", "labels"):
            raise EditError("Nazwy sygnałów: „legend”, „labels” albo puste (domyślne).")
        new["legend_style"] = patch["legend_style"]
    if "time_axis" in patch:
        if patch["time_axis"] not in ("rel", "app", "plc"):
            raise EditError("Oś czasu: „rel”, „app” albo „plc”.")
        new["time_axis"] = patch["time_axis"]
    if "time_offset" in patch:
        new["time_offset"] = _num(patch, "time_offset", -TIME_OFFSET_MAX, TIME_OFFSET_MAX, "Offset osi czasu [s]", float)
    if "gap_mode" in patch:                                   # pauses of the chart: empty stretch / cut out / band of gap_px pixels
        if patch["gap_mode"] not in GAP_MODES:
            raise EditError("Przerwy na wykresie: „full”, „join” albo „fixed”.")
        new["gap_mode"] = patch["gap_mode"]
    if "gap_px" in patch:
        new["gap_px"] = int(_num(patch, "gap_px", GAP_PX_MIN, GAP_PX_MAX, "Szerokość przerwy [px]", float))
    for k in ("auto_y", "show_points", "auto_reset"):
        if k in patch:
            new[k] = bool(patch[k])
    for k in ("y_min", "y_max"):
        if k in patch:
            new[k] = _num(patch, k, -1e12, 1e12, "Zakres Y" , float)
    if "conn_type" in patch:
        if patch["conn_type"] not in CONN_KINDS:
            raise EditError("Nieznany sposób połączenia.")
        new["conn_type"] = patch["conn_type"]
    if "mode" in patch:
        if patch["mode"] not in MODES:
            raise EditError("Nieznany tryb odczytu.")
        new["mode"] = patch["mode"]
    if "conn" in patch:
        c = patch["conn"]
        if not isinstance(c, dict):
            raise EditError("Ustawienia połączenia: niepoprawne dane.")
        merged = dict(cfg.conn)
        for k, v in c.items():
            if k not in _CONN_KEYS or k == "has_password":
                continue
            want = _CONN_KEYS[k]
            if want is bool:
                v = bool(v)
            elif want is int:
                v = _num(c, k, 0, 65535, k)
            else:
                if k in ("cert", "key"):                    # paths of files on the server: set by an administrator only
                    continue
                v = _text(c, k, 200, k)
                if k == "password" and v == "":
                    continue                                # an empty password field = keep the stored one
            merged[k] = v
        new["conn"] = merged
    if "signals" in patch:
        sigs = patch["signals"]
        if not isinstance(sigs, list) or not 1 <= len(sigs) <= MAX_SIGNALS:
            raise EditError(f"Liczba sygnałów: 1…{MAX_SIGNALS}.")
        built = [signal_from({**Signal().to_dict(), "color": DEFAULT_COLORS[i % len(DEFAULT_COLORS)], **s}
                             if isinstance(s, dict) else s) for i, s in enumerate(sigs)]
        names = [s.name for s in built]
        if len(set(n.lower() for n in names)) != len(names):
            raise EditError("Nazwy sygnałów muszą być różne.")
        new["signals"] = built
    if "trigger" in patch:
        d = patch["trigger"]
        if not isinstance(d, dict):
            raise EditError("Wyzwalacz: niepoprawne dane.")
        names = [x.name for x in new.get("signals", cfg.signals)]
        out = {}
        if "enabled" in d:
            out["enabled"] = bool(d["enabled"])
        if "signal" in d:
            sig = _text(d, "signal", 64, "Sygnał wyzwalacza")
            if sig and sig not in names:
                raise EditError("Wyzwalacz: nie ma takiego sygnału.")
            out["signal"] = sig
        if "mode" in d:
            if d["mode"] not in trig.MODES:
                raise EditError("Wyzwalacz: nieznany warunek.")
            out["mode"] = d["mode"]
        for k, lo, hi in (("a", -1e12, 1e12), ("b", -1e12, 1e12), ("hysteresis", 0, 1e12), ("pretrigger", 0, 86400)):
            if k in d:
                out[k] = _num(d, k, lo, hi, f"Wyzwalacz: {k}", float)
        if "action" in d:
            if d["action"] not in trig.ACTIONS:
                raise EditError("Wyzwalacz: nieznana akcja.")
            out["action"] = d["action"]
        if "target" in d:                                           # where a snapshot goes: a CSV file, the account's SQLite or an admin's target
            if d["target"] not in ["csv", "sqlite"] + list(targets or []):
                raise EditError("Wyzwalacz: nieznany cel zapisu.")
            out["target"] = d["target"]
        if "place" in d:
            if d["place"] not in trig.PLACES:
                raise EditError("Wyzwalacz: baza „shared” (ogólna) albo „own” (osobna).")
            out["place"] = d["place"]
        if "db_file" in d:
            name = os.path.basename(str(d["db_file"]).strip()) or trig.DEFAULT_SNAPSHOT_DB
            if not re.fullmatch(r"[\w .\-]{1,80}", name):
                raise EditError("Wyzwalacz: nazwa pliku bazy – litery, cyfry, spacja, kropka, minus i podkreślenie.")
            out["db_file"] = name if name.lower().endswith((".db", ".sqlite", ".sqlite3")) else name + ".db"
        if "filename" in d:
            try:
                out["filename"] = files.check_template(str(d["filename"])) or trig.DEFAULT_SNAPSHOT_NAME
            except ValueError as e:
                raise EditError(str(e)) from None
        if out.get("enabled", cfg.trigger.enabled) and not out.get("signal", cfg.trigger.signal):
            raise EditError("Wyzwalacz: wybierz sygnał.")
        new["trigger"] = out
    if "rec" in patch:
        d = patch["rec"]
        if not isinstance(d, dict):
            raise EditError("REC: niepoprawne dane.")
        out = {}
        if "target" in d:
            if d["target"] not in ["csv", "sqlite"] + list(targets or []):
                raise EditError("REC: nieznany cel zapisu.")
            out["target"] = d["target"]
        if "mode" in d:
            if d["mode"] not in store_mod.MODES:
                raise EditError("REC: nieznany tryb zapisu.")
            out["mode"] = d["mode"]
        if "filename" in d:
            try:
                out["filename"] = files.check_template(str(d["filename"])) or trig.DEFAULT_REC_NAME
            except ValueError as e:
                raise EditError(str(e)) from None
        if recording and out:
            raise EditError("Zatrzymaj nagrywanie, aby zmienić ustawienia REC.")
        new["rec"] = out
    if running:
        bad = [k for k in new if k in STRUCTURAL]
        if bad:
            raise EditError("Zatrzymaj połączenie, aby zmienić: " + ", ".join(bad) + ".")
    for k, v in new.items():
        if k == "trigger":
            for f, x in v.items():
                setattr(cfg.trigger, f, x)
        elif k == "rec":
            if "target" in v and web is not None:
                web["rec_target"] = v["target"]
            if "mode" in v:
                cfg.store.mode = v["mode"]
            if "filename" in v:
                cfg.rec_filename = v["filename"]
        else:
            setattr(cfg, k, v)
    return list(new)
