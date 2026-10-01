"""Symbol tables: map names to absolute S7 addresses.

Supported imports (best effort, tested on synthetic samples):
  * TIA Portal PLC tag table export (.xlsx / .csv) - I/Q/M tags
  * TIA Portal DB source (.db / .scl) and SimaticML XML - structure -> offsets
    (classic, NON-optimized DBs only: offsets are computed with S7 alignment rules)
  * Step 7 Classic symbol export (.sdf / .asc / .seq)
"""
from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

from .types import TYPES, Signal


@dataclass
class Symbol:
    name: str
    source: str       # I / Q / M / DB
    dtype: str
    db: int = 0
    byte: int = 0
    bit: int = 0
    comment: str = ""

    @property
    def address(self) -> str:
        return Signal(source=self.source, dtype=self.dtype, db=self.db,
                      byte=self.byte, bit=self.bit).address

    def to_signal(self) -> Signal:
        return Signal(name=self.name, source=self.source, dtype=self.dtype,
                      db=self.db, byte=self.byte, bit=self.bit)


# ------------------------------------------------------------------ helpers
_TYPE_ALIASES = {
    "BOOL": "BOOL", "BYTE": "BYTE", "CHAR": "BYTE", "SINT": "SINT", "USINT": "USINT",
    "INT": "INT", "UINT": "UINT", "WORD": "WORD", "DINT": "DINT", "UDINT": "UDINT",
    "DWORD": "DWORD", "REAL": "REAL", "LREAL": "LREAL", "TIME": "DINT", "S5TIME": "WORD",
    "DATE": "WORD", "TIME_OF_DAY": "UDINT", "TOD": "UDINT", "COUNTER": "WORD",
}


def norm_type(t: str) -> str | None:
    return _TYPE_ALIASES.get(t.strip().upper().replace('"', ""))


_AREA_MAP = {"I": "I", "E": "I", "PI": "I", "PE": "I", "Q": "Q", "A": "Q", "PQ": "Q", "PA": "Q", "M": "M"}
_OPERAND = re.compile(
    r"^%?(?:(?P<db>DB\s*(?P<dbn>\d+)\s*\.\s*DB)|(?P<area>PI|PQ|PE|PA|I|E|Q|A|M))"
    r"\s*(?P<size>[XBWD]?)\s*(?P<byte>\d+)(?:\.(?P<bit>\d))?$", re.I)


def parse_address(text: str, dtype_hint: str | None = None) -> tuple[str, str, int, int, int] | None:
    """'%I0.0' / 'MW10' / 'E 1.2' / 'DB1.DBX0.0' -> (source, dtype, db, byte, bit)."""
    t = text.strip().replace(" ", "")
    m = _OPERAND.match(t)
    if not m:
        return None
    size = m.group("size").upper()
    byte = int(m.group("byte"))
    bit = int(m.group("bit")) if m.group("bit") is not None else 0
    if m.group("db"):
        source, db = "DB", int(m.group("dbn"))
    else:
        source, db = _AREA_MAP[m.group("area").upper()], 0
    if not size:
        size = "X" if m.group("bit") is not None else "B"
    dtype = {"X": "BOOL", "B": "BYTE", "W": "WORD", "D": "DWORD"}[size]
    hint = norm_type(dtype_hint) if dtype_hint else None
    if hint and hint != "BOOL" and TYPES[hint][0] == TYPES[dtype][0] and dtype != "BOOL":
        dtype = hint
    return source, dtype, db, byte, bit


# -------------------------------------------------------------- tag tables
def _rows_from_xlsx(path: str):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            yield ["" if c is None else str(c) for c in row]


def _rows_from_csv(path: str):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    sep = max([",", ";", "\t"], key=text[:2000].count)
    yield from csv.reader(text.splitlines(), delimiter=sep)


def import_tag_table(path: str) -> list[Symbol]:
    rows = _rows_from_xlsx(path) if path.lower().endswith((".xlsx", ".xlsm")) else _rows_from_csv(path)
    out: list[Symbol] = []
    cols: dict[str, int] = {}
    for row in rows:
        low = [c.strip().lower() for c in row]
        if not cols:
            if "name" in low and any(("address" in c or "adres" in c) for c in low):
                cols = {"name": low.index("name")}
                for i, c in enumerate(low):
                    if "address" in c or "adres" in c:
                        cols["addr"] = i
                    elif c in ("data type", "datatype", "typ danych", "typ"):
                        cols["type"] = i
                    elif c in ("comment", "komentarz"):
                        cols["comment"] = i
            continue
        if len(row) <= max(cols["name"], cols["addr"]):
            continue
        name, addr = row[cols["name"]].strip(), row[cols["addr"]].strip()
        if not name or not addr:
            continue
        hint = row[cols["type"]] if "type" in cols and cols["type"] < len(row) else None
        p = parse_address(addr, hint)
        if p:
            src, dt, db, by, bi = p
            cm = row[cols["comment"]] if "comment" in cols and cols["comment"] < len(row) else ""
            out.append(Symbol(name, src, dt, db, by, bi, cm))
    return out


# ------------------------------------------------------------ Step 7 classic
def import_step7(path: str) -> list[Symbol]:
    out: list[Symbol] = []
    with open(path, encoding="latin-1") as f:
        lines = f.read().splitlines()
    for line in lines:
        if not line.strip():
            continue
        name = addr = dt = cm = ""
        if '"' in line:
            f_ = next(csv.reader([line]))
            if len(f_) >= 3:
                name, addr, dt = f_[0], f_[1], f_[2]
                cm = f_[3] if len(f_) > 3 else ""
        elif line.count(",") >= 3 and re.match(r"^\s*\d+,", line):      # .seq
            f_ = [x.strip() for x in line.split(",", 4)]
            name, addr, dt, cm = f_[1], f_[2], f_[3], (f_[4] if len(f_) > 4 else "")
        else:                                                            # .asc fixed width
            name, addr, dt, cm = line[:24].strip(), line[24:36].strip(), line[36:46].strip(), line[46:].strip()
        if not name or not addr:
            continue
        p = parse_address(addr, dt)
        if p:
            out.append(Symbol(name, p[0], p[1], p[2], p[3], p[4], cm))
    return out


# ----------------------------------------------------------- DB structure
class _Layout:
    """S7 classic (non-optimized) offset allocator."""

    def __init__(self):
        self.byte = 0
        self.bit = 0       # next free bit in current byte when bit > 0

    def _close_bits(self):
        if self.bit:
            self.byte += 1
            self.bit = 0

    def align_even(self):
        self._close_bits()
        if self.byte % 2:
            self.byte += 1

    def alloc(self, dtype: str, count: int = 1) -> list[tuple[int, int]]:
        res = []
        if dtype == "BOOL":
            for _ in range(count):
                res.append((self.byte, self.bit))
                self.bit += 1
                if self.bit == 8:
                    self.byte += 1
                    self.bit = 0
            return res
        size = TYPES[dtype][0]
        self._close_bits()
        if size > 1 or count > 1:
            self.align_even()
        for _ in range(count):
            res.append((self.byte, 0))
            self.byte += size
        return res


_DECL = re.compile(r'^\s*"?([^":;]+?)"?\s*:\s*(.+?)\s*(?::=.*)?;\s*(?://.*)?$')
_STRUCT_OPEN = re.compile(r'^\s*"?([^":;]+?)"?\s*:\s*Struct\s*$', re.I)
_ARRAY = re.compile(r"^Array\s*\[\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\]\s*of\s+(.+)$", re.I)
_STRING = re.compile(r"^W?String\s*(?:\[\s*(\d+)\s*\])?$", re.I)


def import_db_source(path: str, db_number: int) -> list[Symbol]:
    """Parse a TIA .db / .scl DATA_BLOCK source."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    if re.search(r"S7_Optimized_Access\s*:=\s*'TRUE'", text, re.I):
        raise ValueError("Ten DB ma 'Optimized block access' — adresy bezwzględne nie są dostępne. "
                         "Wyłącz optymalizację w TIA Portal (właściwości DB) i skompiluj ponownie.")
    m = re.search(r'DATA_BLOCK\s+"?([^"\s]+)"?', text, re.I)
    db_name = m.group(1) if m else f"DB{db_number}"
    lay = _Layout()
    out: list[Symbol] = []
    stack: list[tuple[str, _Layout | None]] = []   # path parts of nested structs
    path_parts: list[str] = []
    body = text[text.upper().find("STRUCT"):] if "STRUCT" in text.upper() else text
    lines = body.splitlines()[1:]
    for raw in lines:
        line = raw.split("//")[0].strip()
        if not line:
            continue
        up = line.upper()
        if up.startswith("BEGIN") or up.startswith("END_DATA_BLOCK"):
            break
        if up.startswith("END_STRUCT"):
            lay.align_even()
            if path_parts:
                path_parts.pop()
            continue
        sm0 = _STRUCT_OPEN.match(line)
        if sm0:
            lay.align_even()
            path_parts.append(sm0.group(1).strip())
            continue
        d = _DECL.match(line)
        if not d:
            continue
        name, typ = d.group(1).strip(), d.group(2).strip()
        full = ".".join([db_name] + path_parts + [name])
        count = 1
        am = _ARRAY.match(typ)
        if am:
            lo, hi, typ = int(am.group(1)), int(am.group(2)), am.group(3).strip()
            count = hi - lo + 1
        sm = _STRING.match(typ)
        if sm:
            n = int(sm.group(1)) if sm.group(1) else 254
            lay._close_bits()
            lay.byte += (n + 2) * count
            continue
        dt = norm_type(typ)
        if not dt:
            continue    # UDT / unsupported type: skipped (offset unknown)
        pos = lay.alloc(dt, count)
        for i, (by, bi) in enumerate(pos):
            nm = full if count == 1 else f"{full}[{i + (int(am.group(1)) if am else 0)}]"
            out.append(Symbol(nm, "DB", dt, db_number, by, bi))
    return out


def import_db_xml(path: str, db_number: int) -> list[Symbol]:
    """Parse SimaticML XML export of a DB (members -> offsets via S7 alignment)."""
    tree = ET.parse(path)
    root = tree.getroot()

    def tag(e):
        return e.tag.split("}")[-1]

    db_el = next((e for e in root.iter() if tag(e) in ("SW.Blocks.GlobalDB",)), root)
    name_el = next((e for e in db_el.iter() if tag(e) == "Name"), None)
    db_name = name_el.text if name_el is not None and name_el.text else f"DB{db_number}"
    opt = next((e for e in db_el.iter() if tag(e) == "MemoryLayout"), None)
    if opt is not None and (opt.text or "").lower() == "optimized":
        raise ValueError("Ten DB ma 'Optimized block access' — adresy bezwzględne nie są dostępne.")
    static = next((s for s in db_el.iter() if tag(s) == "Section" and s.get("Name") == "Static"), None)
    if static is None:
        raise ValueError("Nie znaleziono sekcji Static w XML.")
    lay = _Layout()
    out: list[Symbol] = []

    def walk(members, prefix: list[str]):
        for mem in members:
            if tag(mem) != "Member":
                continue
            nm, typ = mem.get("Name", ""), mem.get("Datatype", "")
            sub = [c for c in mem if tag(c) == "Member"]
            full = ".".join([db_name] + prefix + [nm])
            if typ.lower() == "struct":
                lay.align_even()
                walk(sub, prefix + [nm])
                lay.align_even()
                continue
            count, base = 1, typ.strip('"')
            am = _ARRAY.match(base)
            lo = 0
            if am:
                lo, hi, base = int(am.group(1)), int(am.group(2)), am.group(3).strip()
                count = hi - lo + 1
            sm = _STRING.match(base)
            if sm:
                n = int(sm.group(1)) if sm.group(1) else 254
                lay._close_bits()
                lay.byte += (n + 2) * count
                continue
            dt = norm_type(base)
            if not dt:
                continue
            for i, (by, bi) in enumerate(lay.alloc(dt, count)):
                out.append(Symbol(full if count == 1 else f"{full}[{i + lo}]", "DB", dt, db_number, by, bi))

    walk(list(static), [])
    return out


def import_symbols(path: str, db_number: int = 1) -> list[Symbol]:
    low = path.lower()
    if low.endswith((".xlsx", ".xlsm")):
        return import_tag_table(path)
    if low.endswith((".db", ".scl")):
        return import_db_source(path, db_number)
    if low.endswith(".xml"):
        return import_db_xml(path, db_number)
    if low.endswith((".sdf", ".asc", ".seq")):
        return import_step7(path)
    if low.endswith(".csv"):
        return import_tag_table(path)
    raise ValueError(f"Nieobsługiwany format pliku: {path}")


# ------------------------------------------------------------- persistence
def save_symbols(path: str, syms: list[Symbol]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in syms], f, ensure_ascii=False)


def load_symbols(path: str) -> list[Symbol]:
    try:
        with open(path, encoding="utf-8") as f:
            return [Symbol(**d) for d in json.load(f)]
    except (OSError, ValueError, TypeError):
        return []
