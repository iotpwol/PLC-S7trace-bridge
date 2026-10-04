"""Recording targets (databases) of the server. Defined by an administrator, who also keeps the connection secrets;
users only pick a target by name and never see its address-level secrets (passwords / tokens)."""
from __future__ import annotations

import dataclasses
import json
import os
import re
import threading

from ..core.store import KINDS, MODES, PARAMS, StoreConfig

DB_KINDS = [k for k in KINDS if k != "csv"]
_NAME = re.compile(r"[\w .\-]{1,40}")
RESERVED = ("csv", "sqlite")                           # the built-in targets (CSV file / SQLite file of the account)
# what an administrator may set (the rest of StoreConfig keeps its defaults; the time parameters are in PARAMS)
FIELDS = ("kind", "mode", "sqlite_path", "url", "database", "org", "bucket", "user", "password", "token", "measurement", "host",
          "port", "pg_database", "pg_user", "pg_password", "pg_sslmode", "table", "compress_days", "view_scope", "delete_others",
          "trash_days", "retention_days") + tuple(PARAMS)


class TargetError(ValueError):
    """A message that may be shown to the user as it is."""


class Targets:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self.items: dict[str, dict] = {}
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.items = {str(k): v for k, v in d.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self.items, key=str.lower)

    def get(self, name: str) -> StoreConfig | None:
        with self._lock:
            d = self.items.get(name)
        if d is None:
            return None
        c = StoreConfig.from_dict({**d, "remember": True})
        c.remember = True
        return c

    def public(self, name: str, admin: bool) -> dict:
        """What a browser may see: the kind and a description for everybody; the editable fields (without secrets,
        only "is set") for the administrator."""
        c = self.get(name)
        row = {"name": name, "kind": c.kind, "label": c.describe()}
        if admin:
            d = dataclasses.asdict(c)
            row["fields"] = {k: d[k] for k in FIELDS if k not in StoreConfig.SECRETS}
            row["secrets_set"] = {k: bool(d[k]) for k in StoreConfig.SECRETS}
        return row

    def listing(self, admin: bool) -> list[dict]:
        return [self.public(n, admin) for n in self.names()]

    def put(self, name: str, fields: dict) -> None:
        name = (name or "").strip()
        if not _NAME.fullmatch(name) or name.lower() in RESERVED:
            raise TargetError("Nazwa celu: 1–40 znaków (litery, cyfry, spacja, . _ -); „csv” i „sqlite” są zajęte.")
        with self._lock:
            old = dict(self.items.get(name) or {})
            new = {**old}
            for k, v in (fields or {}).items():
                if k not in FIELDS:
                    continue
                if k in StoreConfig.SECRETS and v in ("", None):
                    continue                                        # an empty secret field = keep the stored secret
                new[k] = v
            c = StoreConfig.from_dict({**new, "remember": True})
            if c.kind not in DB_KINDS:
                raise TargetError("Rodzaj celu: sqlite, influx1, influx2 albo timescale.")
            if c.mode not in MODES:
                raise TargetError("Nieznany tryb zapisu.")
            d = dataclasses.asdict(c)
            self.items[name] = {k: d[k] for k in FIELDS} | {"remember": True}
            self._save()

    def delete(self, name: str) -> None:
        with self._lock:
            if name in self.items:
                del self.items[name]
                self._save()
