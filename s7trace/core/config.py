"""Persistent application / tab configuration (JSON in %APPDATA%\\S7Trace)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from .planner import MODE_BLOCKS
from .trigger import TriggerConfig
from .types import Signal


def app_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "S7Trace")
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class TabConfig:
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
    signals: list[Signal] = field(default_factory=lambda: [Signal(name="SIG1")])
    trigger: TriggerConfig = field(default_factory=TriggerConfig)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signals"] = [s.to_dict() for s in self.signals]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TabConfig":
        c = cls()
        for k in ("ip", "rack", "slot", "cycle_ms", "mode", "window_s", "auto_y",
                  "y_min", "y_max", "show_points"):
            if k in d:
                setattr(c, k, d[k])
        if d.get("signals"):
            c.signals = [Signal.from_dict(s) for s in d["signals"]]
        if isinstance(d.get("trigger"), dict):
            known = {k: v for k, v in d["trigger"].items() if k in TriggerConfig.__dataclass_fields__}
            c.trigger = TriggerConfig(**known)
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
