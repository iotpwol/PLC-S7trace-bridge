"""Interface settings of a Web account (the counterpart of the desktop 'konfiguracja interfejsu'): kept on the server per account, so
they follow the user to every browser and computer. Qt-free; it holds the look of the marker lines and the layout of the settings
panel (order / folded groups / bottom tab, like the desktop interface configuration)."""
from __future__ import annotations

import json
import os
import re
import threading

from ..core import marker_look, panel_cfg

STATUS_LINES = (1, 2, 3, 4, 5, 6, 8, 10)
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


TABLE_KEYS = ("header_bg", "header_text", "odd_bg", "odd_text", "even_bg", "even_text", "border", "reset_on_bg", "reset_on_text")


def table_normalize(raw) -> dict:
    """Colours of the tables in the browser ('' = the colour of the page): the same seven settings as the desktop 'Interfejs', plus the
    two of the engaged 'Auto-Reset' button."""
    raw = raw if isinstance(raw, dict) else {}
    return {k: (raw[k].lower() if isinstance(raw.get(k), str) and _HEX.match(raw[k]) else "") for k in TABLE_KEYS}


def legend_style_normalize(raw) -> str:
    """How the chart shows the signal names: 'legend' (a list under the chart) or 'labels' (a boxed name at every signal)."""
    return "labels" if raw == "labels" else "legend"


def status_normalize(raw) -> dict:
    """The status bar of the chart page: most lines, colours ('' = the colour of the page), justification of the text."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        lines = max(1, min(10, int(raw.get("lines", 1))))
    except (TypeError, ValueError):
        lines = 1
    col = lambda v: v.lower() if isinstance(v, str) and _HEX.match(v) else ""
    return {"lines": lines, "bg": col(raw.get("bg")), "text": col(raw.get("text")), "align": "left" if raw.get("align") == "left" else "right"}


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
        return {"marker_look": marker_look.normalize(raw.get("marker_look")), "panel": panel_cfg.normalize(raw.get("panel"), panel_cfg.WEB_ROWS),
                "status": status_normalize(raw.get("status")), "table": table_normalize(raw.get("table")),
                "legend_style": legend_style_normalize(raw.get("legend_style"))}

    def update(self, user: str, patch: dict) -> dict:
        """Merges the known keys of `patch` (validated) into the account's settings; returns the result."""
        with self._lock:
            cur = self.get(user)
            if isinstance(patch.get("marker_look"), dict):
                cur["marker_look"] = marker_look.normalize(patch["marker_look"])
            if isinstance(patch.get("panel"), dict):
                cur["panel"] = panel_cfg.normalize(patch["panel"], panel_cfg.WEB_ROWS)
            if isinstance(patch.get("table"), dict):
                cur["table"] = table_normalize(patch["table"])
            if "legend_style" in patch:
                cur["legend_style"] = legend_style_normalize(patch["legend_style"])
            if isinstance(patch.get("status"), dict):
                cur["status"] = status_normalize(patch["status"])
            os.makedirs(self.folder, exist_ok=True)
            tmp = self._path(user) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path(user))
            return cur
