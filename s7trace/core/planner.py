"""Builds the list of PLC read requests for a set of signals."""
from __future__ import annotations

from dataclasses import dataclass, field

from .types import Signal

MODE_BLOCKS = "Bloki (grupowane)"
MODE_SINGLE = "Pojedyncze (per sygnał)"
MODE_MULTI = "Multi-read (1 zapytanie)"
MODES = [MODE_BLOCKS, MODE_SINGLE, MODE_MULTI]

MAX_BLOCK = 200      # bytes per request (fits in one 240 B PDU)
MAX_GAP = 16         # merge ranges separated by <= this many unused bytes
MAX_MULTI = 20       # items per multi-read request


@dataclass
class ReadBlock:
    source: str
    db: int
    start: int
    size: int
    items: list[tuple[int, int]] = field(default_factory=list)  # (signal idx, offset in block)


def _sig_range(s: Signal) -> tuple[tuple[str, int], int, int]:
    return (s.source, s.db if s.source == "DB" else 0), s.byte, s.byte + s.size


def build_plan(signals: list[Signal], mode: str = MODE_BLOCKS) -> list[ReadBlock]:
    """Return read blocks covering every signal. Pure function, no I/O."""
    if mode == MODE_SINGLE:
        blocks = []
        for i, s in enumerate(signals):
            (src, db), a, b = _sig_range(s)
            blocks.append(ReadBlock(src, db, a, b - a, [(i, 0)]))
        return blocks

    max_gap = MAX_GAP if mode == MODE_BLOCKS else 0
    max_block = MAX_BLOCK if mode == MODE_BLOCKS else MAX_BLOCK
    order = sorted(range(len(signals)), key=lambda i: (_sig_range(signals[i])[0], signals[i].byte))
    blocks: list[ReadBlock] = []
    cur: ReadBlock | None = None
    cur_key = None
    for i in order:
        key, a, b = _sig_range(signals[i])
        if (cur is not None and key == cur_key and a - (cur.start + cur.size) <= max_gap
                and max(b, cur.start + cur.size) - cur.start <= max_block):
            cur.size = max(b, cur.start + cur.size) - cur.start
            cur.items.append((i, a - cur.start))
        else:
            cur = ReadBlock(key[0], key[1], a, b - a, [(i, 0)])
            cur_key = key
            blocks.append(cur)
    return blocks


def decode_blocks(signals: list[Signal], blocks: list[ReadBlock],
                  data: list[bytes | bytearray]) -> list[float]:
    out = [0.0] * len(signals)
    for blk, raw in zip(blocks, data):
        for idx, off in blk.items:
            out[idx] = signals[idx].decode(raw, off)
    return out
