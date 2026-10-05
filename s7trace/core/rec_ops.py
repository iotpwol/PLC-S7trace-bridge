"""Recording operations on data that the program holds in its buffer (Qt-free; used by the desktop tab and by the web server).

* `save_range_recording` - 'Zapis Manual REC': a chosen piece of the chart becomes a recording of its own (CSV file or database).
* `move_start` - 'Zmień Start REC': the start of a recording that is running (or finished) is moved: earlier = the missing part is
  filled in from the buffer, later = the data before the new start are deleted (databases only; a CSV file cannot be changed).
Times given as `t` are seconds since `start_wall` (the chart time).
"""
from __future__ import annotations

import dataclasses
import math
from datetime import datetime

import numpy as np

from . import store
from .csvio import CsvRecorder
from .store import ChangeFilter, StoreConfig, StoreError, to_us

CHUNK = 5000


def rows_for_range(start_wall: datetime, t, v, a: float, b: float, mode: str, n: int, key_s: float = 0.0) -> tuple[list, int, float]:
    """The samples of [a, b] as database rows (us, {signal: value}[, True]) + the end of the data in us + the time the first row has.
    The first row is the full state at `a` (the last sample at or before it), then only what changed ('changes' mode) or every sample."""
    t = np.asarray(t, dtype=float)
    if not len(t) or n <= 0:
        return [], 0, a
    i0 = max(int(np.searchsorted(t, a, "right")) - 1, 0)
    first = max(float(t[i0]), a) if t[i0] <= b else float(t[i0])
    filt = ChangeFilter(n, mode)
    cols = min(n, v.shape[1])

    def vals(j) -> list:
        row = [float(x) for x in v[j, :cols]]
        return row + [math.nan] * (n - cols)

    rows = []
    cur = vals(i0)
    idx = filt.changed(cur, force=True)
    rows.append((to_us(start_wall, first), {i: cur[i] for i in idx}, True))
    nxt = first + key_s if key_s > 0 else float("inf")
    last = first
    for j in range(i0 + 1, len(t)):
        tj = float(t[j])
        if tj > b:
            break
        key = tj >= nxt
        if key:
            nxt = tj + key_s
        cur = vals(j)
        idx = filt.changed(cur, force=key)
        last = tj
        if idx:
            rows.append((to_us(start_wall, tj), {i: cur[i] for i in idx}) + ((True,) if key else ()))
    return rows, to_us(start_wall, max(min(b, float(t[-1])), last)), first


def covers(first_time: float, t0: float) -> bool:
    """The buffer still holds the data from `t0` on (samples older than the buffer limit are gone)."""
    return first_time <= t0 + 1e-6


def save_range_recording(cfg: StoreConfig, signals, start_wall: datetime, t, v, a: float, b: float, meta_extra: dict,
                         base_dir: str = "", csv_path: str = "") -> tuple[str, str]:
    """Writes [a, b] of the buffered data as a NEW recording: a CSV file (`csv_path`) or a record of the database target `cfg`.
    Returns (where it went - text for the user, session id or ''). Raises StoreError / OSError."""
    n = len(signals)
    t = np.asarray(t, dtype=float)
    if not len(t):
        raise StoreError("Brak danych w buforze.")
    if csv_path:
        rec = CsvRecorder(csv_path, signals, start_wall, cfg.mode, meta_extra.get("device"))
        try:
            i0 = max(int(np.searchsorted(t, a, "right")) - 1, 0)
            rec.write(max(float(t[i0]), a), [float(x) for x in v[i0, :n]])
            for j in range(i0 + 1, len(t)):
                if t[j] > b:
                    break
                rec.write(float(t[j]), [float(x) for x in v[j, :n]])
        finally:
            rec.close()
        return csv_path, ""
    if cfg.kind == "sqlite":
        cfg = dataclasses.replace(cfg, sqlite_path=store.rotated_sqlite_path(cfg, base_dir, start_wall))     # the same file as live recordings
    key_s = max(cfg.keyframe_min, 0.0) * 60.0 if cfg.mode == "changes" else 0.0
    rows, end_us, first = rows_for_range(start_wall, t, v, a, b, cfg.mode, n, key_s)
    meta = store.make_session_meta(cfg, signals, start_wall, meta_extra, first, key_s)
    be = store.open_backend(cfg, base_dir)
    try:
        be.begin(meta)
        for i in range(0, len(rows), CHUNK):
            be.write(rows[i:i + CHUNK])
        be.end(end_us)
    finally:
        be.close()
    return f"{cfg.describe()} (nagranie {meta['id']})", meta["id"]


def move_start(backend: store.Backend, meta: dict, new_us: int, rows: list) -> None:
    """Moves the start of the recording described by `meta` (as `Backend.sessions()` lists it) to `new_us`.
    Earlier: `rows` (the buffered data from the new start to the old one, first row = full state) are added. Later: `rows` is the full state
    at the new start; it is written first, then everything older is deleted. The recording's description gets the new start last."""
    sid, old = meta["id"], int(meta["start_us"])
    if new_us == old:
        return
    if getattr(backend, "sid", "") != sid:
        backend.attach(meta)
    if rows:
        backend.write(rows)
    if new_us > old:
        backend.delete_before(sid, new_us)
    backend.set_start(sid, new_us)


def plan_move(buf, start_wall: datetime, span: dict, new_t: float, mode: str, key_s: float, n_sig: int) -> dict:
    """Checks a move of the start of recording `span` (RecMarks.auto item) to `new_t` against the buffer and prepares the rows.
    Returns {rows, new_us, first (the new start, chart s), earlier, clamped (the buffer does not reach `new_t`)}; raises ValueError
    with a message for the user."""
    old = span["t0"]
    end = span["t1"] if span["t1"] is not None else buf.last_time()
    if len(buf) == 0:
        raise ValueError("Brak danych na wykresie.")
    if abs(new_t - old) < 1e-3:
        raise ValueError("Nowy początek jest taki sam jak obecny.")
    if new_t >= end - 0.05:
        raise ValueError("Nowy początek musi leżeć przed końcem nagrania.")
    clamped = False
    if new_t < old and not covers(buf.first_time(), new_t):
        new_t, clamped = buf.first_time(), True
        if new_t >= old:
            raise ValueError("Bufor wykresu nie zawiera danych sprzed obecnego początku nagrania.")
    a, b = (new_t, old) if new_t < old else (new_t, new_t)
    t, v = buf.snapshot(a, b)
    rows, _end_us, first = rows_for_range(start_wall, t, v, a, b, mode, n_sig, key_s)
    if not rows:
        raise ValueError("Brak danych w buforze dla tego miejsca.")
    return {"rows": rows, "new_us": rows[0][0], "first": first, "earlier": new_t < old, "clamped": clamped}
