"""Search in recorded signal data: where did a signal have a value (or change), for how long.

Qt-free. `find_hits` works on a (t, v) matrix as held by TraceBuffer / returned by Backend.read; `search_backend` slices a long
recording of a database so that it never needs more than a slice in memory.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

OPS = {                       # key -> (label, number of values, is an event = a point in time rather than a state)
    "==": ("jest równe", 1, False), "!=": ("jest różne od", 1, False), ">": ("jest większe niż", 1, False),
    ">=": ("jest ≥", 1, False), "<": ("jest mniejsze niż", 1, False), "<=": ("jest ≤", 1, False),
    "between": ("jest w przedziale", 2, False), "outside": ("jest poza przedziałem", 2, False),
    "changes": ("zmienia wartość", 0, True), "rises": ("rośnie (zbocze narastające)", 0, True),
    "falls": ("maleje (zbocze opadające)", 0, True), "nan": ("brak wartości (niedostępny)", 0, False),
}
MAX_HITS = 5000


@dataclass
class Cond:
    signal: int                   # column of the matrix
    op: str = "=="
    a: float = 0.0
    b: float = 0.0
    tol: float = 0.0              # '==' / '!=': |v - a| <= tol counts as equal

    def check(self, ncols: int) -> None:
        if self.op not in OPS:
            raise ValueError(f"Nieznany operator: {self.op}")
        if not (0 <= self.signal < ncols):
            raise ValueError("Nie ma takiego sygnału.")


@dataclass
class Hit:
    t0: float                     # first sample of the run [same unit as t]
    t1: float                     # time the condition stopped being true (first sample after the run; the last sample otherwise)
    values: list                  # values of the searched signals at t0, in the order of the conditions
    vmin: float = float("nan")    # min / max of the FIRST searched signal during the run
    vmax: float = float("nan")
    open_start: bool = False      # the run goes on before the first sample of the searched part
    open_end: bool = False        # ... and after its last sample

    @property
    def duration(self) -> float:
        return max(self.t1 - self.t0, 0.0)


def _mask(c: Cond, col: np.ndarray) -> np.ndarray:
    nan = np.isnan(col)
    with np.errstate(invalid="ignore"):
        op = c.op
        if op == "==":
            m = np.abs(col - c.a) <= c.tol
        elif op == "!=":
            m = np.abs(col - c.a) > c.tol
        elif op == ">":
            m = col > c.a
        elif op == ">=":
            m = col >= c.a
        elif op == "<":
            m = col < c.a
        elif op == "<=":
            m = col <= c.a
        elif op in ("between", "outside"):
            lo, hi = min(c.a, c.b), max(c.a, c.b)
            m = (col >= lo) & (col <= hi)
            if op == "outside":
                m = ~m
        elif op == "nan":
            return nan
        else:                                            # events: compared with the previous sample
            m = np.zeros(len(col), dtype=bool)
            if len(col) > 1:
                a, b = col[:-1], col[1:]
                ok = ~(np.isnan(a) | np.isnan(b))
                if op == "changes":
                    m[1:] = ok & (a != b)
                elif op == "rises":
                    m[1:] = ok & (b > a)
                else:
                    m[1:] = ok & (b < a)
            return m
    return m & ~nan


def find_hits(t: np.ndarray, v: np.ndarray, conds: list[Cond], min_duration: float = 0.0,
              max_hits: int = MAX_HITS) -> list[Hit]:
    """Runs of samples in which ALL conditions hold at once. An event condition (changes / rises / falls) is true only at the
    sample where it happens. min_duration drops shorter runs. At most max_hits are returned (the earliest)."""
    n = len(t)
    if n == 0 or not conds:
        return []
    for c in conds:
        c.check(v.shape[1] if v.ndim == 2 else 0)
    m = np.ones(n, dtype=bool)
    for c in conds:
        m &= _mask(c, v[:, c.signal])
    if not m.any():
        return []
    if any(OPS[c.op][2] for c in conds):                  # events: every matching sample is a hit of its own
        starts = np.flatnonzero(m)
        ends = starts + 1
    else:
        d = np.diff(m.astype(np.int8), prepend=0, append=0)
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)   # run = [start, end)
    event = any(OPS[c.op][2] for c in conds)
    hits: list[Hit] = []
    first = conds[0].signal
    for s, e in zip(starts, ends):
        t0 = float(t[s])
        t1 = t0 if event else (float(t[e]) if e < n else float(t[n - 1]))
        if t1 - t0 < min_duration:
            continue
        seg = v[s:e, first]
        seg = seg[~np.isnan(seg)]
        hits.append(Hit(t0, t1, [float(v[s, c.signal]) for c in conds],
                        float(seg.min()) if len(seg) else float("nan"), float(seg.max()) if len(seg) else float("nan"),
                        open_start=bool(s == 0 and not event), open_end=bool(e == n and not event)))
        if len(hits) >= max_hits:
            break
    return hits


def merge_hits(prev: list[Hit], new: list[Hit]) -> list[Hit]:
    """Joins the result of the next slice to the previous ones: a run that was open at the end of one slice and open at the start
    of the next one is a single run."""
    if prev and new and prev[-1].open_end and new[0].open_start:
        a, b = prev[-1], new[0]
        a.t1, a.open_end = b.t1, b.open_end
        a.vmin = min(x for x in (a.vmin, b.vmin) if x == x) if (a.vmin == a.vmin or b.vmin == b.vmin) else a.vmin
        a.vmax = max(x for x in (a.vmax, b.vmax) if x == x) if (a.vmax == a.vmax or b.vmax == b.vmax) else a.vmax
        new = new[1:]
    return prev + new


def search_backend(backend, session_id: str, conds: list[Cond], t0_us: int, t1_us: int, min_duration: float = 0.0,
                   slice_s: float = 1800.0, max_hits: int = MAX_HITS, progress: Callable[[float], None] | None = None,
                   cancel: threading.Event | None = None) -> tuple[list[Hit], dict]:
    """Searches a recording of a database between two times (µs) in slices of slice_s seconds; hit times are µs. A slice that is
    too big for memory is halved. Returns (hits, meta). Hits whose condition continues over a slice boundary are merged."""
    from .store import StoreError
    hits: list[Hit] = []
    meta: dict = {}
    total = max(t1_us - t0_us, 1)
    step = max(int(slice_s * 1e6), 1_000_000)

    def one(a: int, b: int, depth: int = 0):
        nonlocal hits, meta
        if cancel is not None and cancel.is_set():
            return
        try:
            meta, t, v = backend.read(session_id, a, b, 0)
        except StoreError as e:
            if "Za dużo" in str(e) and b - a > 2_000_000 and depth < 12:
                mid = (a + b) // 2
                one(a, mid, depth + 1)
                one(mid, b, depth + 1)
                return
            raise
        if len(t):
            sel = (t >= a) & (t <= b)
            found = find_hits(t[sel], v[sel], conds, min_duration=0.0, max_hits=max_hits)
            hits = merge_hits(hits, found)

    a = t0_us
    while a <= t1_us and len(hits) < max_hits:
        if cancel is not None and cancel.is_set():
            break
        b = min(a + step, t1_us)
        one(a, b)
        if progress:
            progress(min((b - t0_us) / total, 1.0))
        a = b + 1
    if min_duration > 0:
        hits = [h for h in hits if h.t1 - h.t0 >= min_duration * 1e6]
    return hits[:max_hits], meta


# ----------------------------------------------------------------------------- recordings of the tab's database target
def store_sources(cfg, base_dir: str = "") -> list:
    """The StoreConfigs to look in: SQLite = the file and its rotated siblings, other targets = the target itself."""
    import dataclasses
    import os

    from . import store as st
    if cfg.kind != "sqlite":
        return [cfg]
    p = cfg.sqlite_path or "s7trace.db"
    p = p if os.path.isabs(p) else os.path.join(st.effective_base(cfg, base_dir), p)
    return [dataclasses.replace(cfg, sqlite_path=f) for f in st.sqlite_family(p) if os.path.exists(f)] or [cfg]


def list_sessions(cfg, base_dir: str = "", include_deleted: bool = False) -> list[dict]:
    """Recordings (newest first) of the target, every dict with the StoreConfig that holds it under '_cfg'."""
    from . import store as st
    out: list[dict] = []
    for c in store_sources(cfg, base_dir):
        b = st.open_backend(c, base_dir)
        try:
            for s in b.sessions():
                if include_deleted or not s.get("deleted_us"):
                    out.append({**s, "_cfg": c})
        finally:
            b.close()
    out.sort(key=lambda s: s["start_us"], reverse=True)
    return out


def session_end_us(backend, sess: dict) -> int:
    """End of a recording; a recording that was never closed properly has no end_us -> the time of its last sample."""
    end = sess.get("end_us")
    if end:
        return int(end)
    try:
        _m, t, _v = backend.read(sess["id"], int(sess["start_us"]), None, 2)      # (thinned; only the last time matters)
        if len(t):
            return int(t[-1])
    except Exception:
        pass
    return int(sess["start_us"])
