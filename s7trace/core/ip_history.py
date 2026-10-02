"""Per-user history of the addresses a connection was really established with (newest first)."""
from __future__ import annotations

import json
import os

from .config import app_dir
from .netaddr import ACCEPTABLE, ipv4_state

MAX_ITEMS = 20


def _path() -> str:
    return os.path.join(app_dir(), "ip_history.json")             # %APPDATA%\S7Trace of the current Windows user


def load() -> list[str]:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    items = data if isinstance(data, list) else []
    return [s for s in items if isinstance(s, str) and ipv4_state(s) == ACCEPTABLE][:MAX_ITEMS]


def add(addr: str) -> list[str]:
    """Moves `addr` to the top of the history (only complete addresses are stored) and saves it."""
    addr = addr.strip()
    items = load()
    if ipv4_state(addr) != ACCEPTABLE:
        return items
    items = [addr] + [s for s in items if s != addr]
    items = items[:MAX_ITEMS]
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except OSError:
        pass                                                      # a history that cannot be saved is not an error
    return items
