"""Signal definition, S7 data types and decoding of raw PLC bytes."""
from __future__ import annotations

import struct
from dataclasses import asdict, dataclass, field

SOURCES = ["I", "Q", "M", "DB"]

# type -> (size in bytes, struct format or None for BOOL)
TYPES: dict[str, tuple[int, str | None]] = {
    "BOOL": (1, None),
    "BYTE": (1, ">B"),
    "SINT": (1, ">b"),
    "USINT": (1, ">B"),
    "WORD": (2, ">H"),
    "INT": (2, ">h"),
    "UINT": (2, ">H"),
    "DWORD": (4, ">I"),
    "DINT": (4, ">i"),
    "UDINT": (4, ">I"),
    "REAL": (4, ">f"),
    "LREAL": (8, ">d"),
}

DEFAULT_COLORS = [
    "#ffb347", "#c8f04e", "#4ef04e", "#4ef0c0", "#4eb8f0",
    "#b48cff", "#ff6fa8", "#ff5a5a", "#f0e04e", "#8fd0ff",
]


@dataclass
class Signal:
    name: str = "SIG"
    source: str = "DB"          # I / Q / M / DB
    dtype: str = "BOOL"
    db: int = 1                 # only for source == DB
    byte: int = 0
    bit: int = 0                # only for BOOL
    offset_y: float = 0.0       # display offset
    gain: float = 1.0           # display gain
    color: str = DEFAULT_COLORS[0]

    @property
    def size(self) -> int:
        return TYPES[self.dtype][0]

    @property
    def address(self) -> str:
        """Human readable absolute address, e.g. DB1.DBX160.0 or MW10."""
        t = self.dtype
        if t == "BOOL":
            suffix, n = "X", f"{self.byte}.{self.bit}"
        else:
            letter = {1: "B", 2: "W", 4: "D", 8: "D"}[self.size]
            suffix, n = letter, str(self.byte)
        if self.source == "DB":
            return f"DB{self.db}.DB{suffix}{n}"
        return f"{self.source}{suffix}{n}" if t != "BOOL" else f"{self.source}{n}"

    def decode(self, raw: bytes | bytearray, base: int = 0) -> float:
        """Decode value from a block `raw` where this signal starts at `base`."""
        size, fmt = TYPES[self.dtype]
        if fmt is None:
            return float((raw[base] >> self.bit) & 1)
        return float(struct.unpack_from(fmt, raw, base)[0])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Signal":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        s = cls(**known)
        if s.source not in SOURCES:
            s.source = "DB"
        if s.dtype not in TYPES:
            s.dtype = "BOOL"
        return s


def default_signal(index: int, existing: list[Signal] | None = None) -> Signal:
    """New signal stacked below the previous ones (like digital channels)."""
    sig = Signal(name=f"SIG{index + 1}", color=DEFAULT_COLORS[index % len(DEFAULT_COLORS)])
    sig.offset_y = round(-1.1 * index, 3)
    if existing:
        last = existing[-1]
        sig.source, sig.dtype, sig.db = last.source, last.dtype, last.db
        sig.byte, sig.bit = last.byte, last.bit
        if sig.dtype == "BOOL":
            sig.bit = (last.bit + 1) % 8
            if sig.bit == 0:
                sig.byte = last.byte + 1
        else:
            sig.byte = last.byte + last.size
    return sig
