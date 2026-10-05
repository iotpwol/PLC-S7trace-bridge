"""Interface settings of a Web account (the counterpart of the desktop 'konfiguracja interfejsu'): kept on the server per account, so
they follow the user to every browser and computer. Qt-free; it holds the look of the marker lines and the layout of the settings
panel (order / folded groups / bottom tab, like the desktop interface configuration)."""
from __future__ import annotations

import json
import os
import re
import threading

from ..core import marker_look, panel_cfg


class Prefs:
    def __init__(self, folder: str):
        self.folder = folder
        self._lock = threading.Lock()

    def _path(self, user: str) -> str:
        return os.path.join(self.folder, "u_" + re.sub(r"[^A-Za-z0-9_.@-]", "_", user.lower()) + ".json")

    def get(self, user: str) -> dict:
        try:
            with open(self._path(user), encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        raw = raw if isinstance(raw, dict) else {}
        return {"marker_look": marker_look.normalize(raw.get("marker_look")), "panel": panel_cfg.normalize(raw.get("panel"), panel_cfg.WEB_ROWS)}

    def update(self, user: str, patch: dict) -> dict:
        """Merges the known keys of `patch` (validated) into the account's settings; returns the result."""
        with self._lock:
            cur = self.get(user)
            if isinstance(patch.get("marker_look"), dict):
                cur["marker_look"] = marker_look.normalize(patch["marker_look"])
            if isinstance(patch.get("panel"), dict):
                cur["panel"] = panel_cfg.normalize(patch["panel"], panel_cfg.WEB_ROWS)
            os.makedirs(self.folder, exist_ok=True)
            tmp = self._path(user) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path(user))
            return cur
