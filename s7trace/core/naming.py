"""Naming of newly added signals: 'D160B' -> 'D160C', '123M1' -> '123M2', 'SIG' + number."""
from __future__ import annotations

import re

NAME_PREV = "prev"     # derive from the reference (previous / current) signal
NAME_OWN = "own"       # own base name + number (SIG1, SIG2, ...)


def _letters_inc(s: str) -> str:
    """Excel-like increment of a letter run: B->C, Z->AA, az->ba (case preserved)."""
    chars = list(s)
    i = len(chars) - 1
    while i >= 0:
        c = chars[i]
        if c in "zZ":
            chars[i] = "a" if c == "z" else "A"
            i -= 1
        else:
            chars[i] = chr(ord(c) + 1)
            return "".join(chars)
    return ("a" if s[0].islower() else "A") + "".join(chars)


def next_name(name: str) -> str:
    """Next name in sequence."""
    if not name:
        return "SIG1"
    m = re.match(r"^(.*?)(\d+)$", name)
    if m:
        head, num = m.groups()
        return f"{head}{int(num) + 1:0{len(num)}d}"
    m = re.match(r"^(.*?)([A-Za-z]+)$", name)
    if m:
        head, run = m.groups()
        # 'D160B' / 'A' look like a letter index; plain words ('Motor') just get a number
        if len(run) <= 2 and (head == "" or head[-1].isdigit()):
            return head + _letters_inc(run)
        return name + "2"
    return name + "1"


def new_signal_name(ref_name: str | None, existing: list[str], autonumber: bool,
                    mode: str = NAME_PREV, own: str = "SIG") -> str:
    """Name for a signal appended to a list that already holds `existing`."""
    taken = set(existing)
    own = own or "SIG"
    if mode == NAME_OWN or not ref_name:
        if not autonumber:
            return f"{own}1"
        n = len(existing) + 1
        while f"{own}{n}" in taken:
            n += 1
        return f"{own}{n}"
    if not autonumber:
        return ref_name
    name = next_name(ref_name)
    for _ in range(100000):
        if name not in taken:
            return name
        name = next_name(name)
    return name
