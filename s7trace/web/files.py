"""Files written by the web server for an account: trigger snapshots and CSV recordings. Every account has its own
folder (connections without an owner use the shared one); browsers never choose a path, only a file-name template."""
from __future__ import annotations

import os
import re
from datetime import datetime

from ..core.trigger import DEFAULT_REC_NAME, DEFAULT_SNAPSHOT_NAME

KINDS = ("snapshots", "rec")                       # sub-folders of an account folder
DEFAULT_NAME = {"snapshots": DEFAULT_SNAPSHOT_NAME, "rec": DEFAULT_REC_NAME}
PLACEHOLDERS = ("confname", "ip", "tab", "date", "time")


def sanitize(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s).strip("_") or "x"


def account_dir(root: str, owner: str) -> str:
    """`<root>/<account>` (the shared connections: `<root>/_shared`)."""
    if not root:
        raise ValueError("Serwer nie ma folderu na pliki.")
    return os.path.join(root, "u_" + sanitize(owner.lower()) if owner else "_shared")


def check_template(template: str) -> str:
    """The file-name template as typed by a user: no path, only the known {placeholders}."""
    t = (template or "").strip()
    if len(t) > 120:
        raise ValueError("Szablon nazwy pliku: najwyżej 120 znaków.")
    if re.search(r"[\\/:*?\"<>|]", t) or ".." in t:
        raise ValueError("Szablon nazwy pliku nie może zawierać znaków ścieżki ani \\ / : * ? \" < > |.")
    for ph in re.findall(r"\{([^{}]*)\}", t):
        if ph not in PLACEHOLDERS:
            raise ValueError("Szablon nazwy pliku: nieznany znacznik {" + ph + "} (dozwolone: "
                             + ", ".join("{" + p + "}" for p in PLACEHOLDERS) + ").")
    if t.count("{") != t.count("}"):
        raise ValueError("Szablon nazwy pliku: niedomknięty nawias klamrowy.")
    return t


class _Names(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def new_path(root: str, owner: str, kind: str, template: str, *, confname: str, ip: str, tab: str,
             now: datetime | None = None) -> str:
    """A free file path in the account folder: template filled in, `.csv` ensured, `_1`, `_2`… when it exists."""
    now = now or datetime.now()
    folder = os.path.join(account_dir(root, owner), kind)
    os.makedirs(folder, exist_ok=True)
    name = (template or DEFAULT_NAME[kind]).format_map(_Names(
        confname=sanitize(confname), ip=sanitize(ip), tab=sanitize(tab), date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H-%M-%S")))
    name = sanitize_filename(name)
    if not name.lower().endswith(".csv"):
        name += ".csv"
    path = os.path.join(folder, name)
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        path = f"{base}_{n}{ext}"
        n += 1
    return path


def sanitize_filename(n: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", n)


def listing(root: str, owner: str) -> list[dict]:
    out = []
    for kind in KINDS:
        folder = os.path.join(account_dir(root, owner), kind)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for n in names:
            p = os.path.join(folder, n)
            if n.lower().endswith(".csv") and os.path.isfile(p):
                st = os.stat(p)
                out.append({"kind": kind, "name": n, "size": st.st_size, "modified": st.st_mtime})
    return sorted(out, key=lambda r: -r["modified"])


def resolve(root: str, owner: str, kind: str, name: str) -> str | None:
    """The path of an existing file of the account, or None (also for any attempt to leave the folder)."""
    if kind not in KINDS or not name or name != os.path.basename(name) or name.startswith("."):
        return None
    p = os.path.join(account_dir(root, owner), kind, name)
    return p if os.path.isfile(p) else None
