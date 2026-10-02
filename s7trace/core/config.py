"""Persistent application / tab configuration (JSON in %APPDATA%\\S7Trace)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from .drivers import conn_defaults
from .planner import MODE_BLOCKS
from .trigger import DEFAULT_REC_NAME, OLD_SNAPSHOT_NAME, DEFAULT_SNAPSHOT_NAME, TriggerConfig
from .types import Signal


def _known_documents() -> str:
    """Windows 'Documents' folder, also when it is redirected (OneDrive, network share); '' when unavailable."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from uuid import UUID
        guid = (ctypes.c_ubyte * 16).from_buffer_copy(UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le)
        buf = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(buf)) == 0:
            val = buf.value or ""
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return val
    except Exception:
        pass
    return ""


def data_dir() -> str:
    """Per-user folder for the files the program writes (snapshots, REC): <Documents>\\S7Trace.
    Relative folders from the settings are resolved against it, so every Windows account has its own place."""
    return os.path.join(_known_documents() or os.path.join(os.path.expanduser("~"), "Documents"), "S7Trace")


def app_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "S7Trace")
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class TabConfig:
    name: str = ""                 # tab title; empty = use the IP
    conf_name: str = ""            # name of the saved configuration ({confname} in file names)
    conn_type: str = "auto"        # auto / s7 / opcua / webapi / modbus
    conn: dict = field(default_factory=conn_defaults)    # login, ports, security ... of the non-S7 drivers
    ip: str = "192.168.0.1"
    rack: int = 0
    slot: int = 2
    cycle_ms: int = 25
    mode: str = MODE_BLOCKS
    window_s: float = 200.0
    auto_y: bool = True
    y_min: float = 0.0
    y_max: float = 10.0
    show_points: bool = False
    autonumber: bool = True        # numbering of new signal names (D160B -> D160C)
    name_mode: str = "prev"        # "prev" = from previous signal, "own" = SIG1, SIG2, ...
    own_name: str = "SIG"
    offset_step: float = -1.1      # Offset Y step for newly added signals
    y_layout: str = "lanes"        # "lanes" = every signal in its own band (Share), "offset" = Offset Y + Gain
    legend_pos: list = field(default_factory=lambda: [0.0, 0.0])    # per tab: (0,0) top-left ... (1,1) bottom-right
    rec_folder: str = "rec"        # REC recordings
    rec_filename: str = DEFAULT_REC_NAME
    signals: list[Signal] = field(default_factory=lambda: [Signal(name="SIG1")])
    trigger: TriggerConfig = field(default_factory=TriggerConfig)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signals"] = [s.to_dict() for s in self.signals]
        if not self.conn.get("remember_password"):
            d["conn"] = {**self.conn, "password": ""}      # the password is stored only when asked for
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TabConfig":
        c = cls()
        if isinstance(d.get("conn"), dict):
            c.conn = {**conn_defaults(), **d["conn"]}
        for k in ("name", "conf_name", "conn_type", "ip", "rack", "slot", "cycle_ms", "mode", "window_s", "auto_y",
                  "y_min", "y_max", "show_points", "autonumber", "name_mode", "own_name", "offset_step",
                  "y_layout", "legend_pos", "rec_folder", "rec_filename"):
            if k in d:
                setattr(c, k, d[k])
        if d.get("signals"):
            c.signals = [Signal.from_dict(s) for s in d["signals"]]
        if isinstance(d.get("trigger"), dict):
            known = {k: v for k, v in d["trigger"].items() if k in TriggerConfig.__dataclass_fields__}
            c.trigger = TriggerConfig(**known)
        if c.trigger.filename == OLD_SNAPSHOT_NAME:                  # the former default -> the new default
            c.trigger.filename = DEFAULT_SNAPSHOT_NAME
        if not (isinstance(c.legend_pos, (list, tuple)) and len(c.legend_pos) == 2):
            c.legend_pos = [0.0, 0.0]
        if c.y_layout not in ("lanes", "offset"):
            c.y_layout = "lanes"
        return c


def config_path() -> str:
    return os.path.join(app_dir(), "config.json")


def symbols_path() -> str:
    return os.path.join(app_dir(), "symbols.json")


def load_app_config(path: str | None = None) -> dict:
    try:
        with open(path or config_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_app_config(data: dict, path: str | None = None) -> None:
    with open(path or config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
