"""REC marks of one chart (Qt-free): the lines the chart draws by itself when the recording starts / stops, the 'Manual REC' areas the
user puts on already collected data, and the 'ghost' of a Start REC that is being moved.

Nothing here is saved in the marker file: the marks follow from what happened during this run (Start .. Stop of the connection).
Times are seconds on the chart (since the connection's start). A mark is described to `PlotView.set_markers` as an item dict with a
pseudo id (<= -BASE) that can never collide with a real / draft marker id.
"""
from __future__ import annotations

from typing import Callable

BASE = 1_000_000
AUTO_START, AUTO_STOP, MANUAL = 1, 2, 3        # kinds of pseudo marker


def pid(kind: int, n: int) -> int:
    """Pseudo id of the mark of `kind` number `n`."""
    return -(BASE + n * 10 + kind)


def parse(mid) -> tuple[int, int] | None:
    """(kind, n) of a pseudo id, None for a real marker."""
    if not isinstance(mid, int) or mid > -BASE:
        return None
    k = -mid - BASE
    return k % 10, k // 10


def is_rec(mid) -> bool:
    return parse(mid) is not None


class RecMarks:
    def __init__(self):
        self.version = 0
        self.reset()

    def reset(self) -> None:
        self.auto: list[dict] = []          # {n, t0, t1 (None while recording), sid (database recording), file (CSV file name)}
        self.manual: list[dict] = []        # {n, a, b (None until the stop is placed), saved (text of where it went or "")}
        self.ghost: dict | None = None      # {n, t}: the moved Start REC
        self.hold = False                   # True while a recorder is re-opened for the same recording (new signals added)
        self.version += 1

    # ---- automatic marks (driven by the recorder)
    def started(self, t: float, sid: str = "", file: str = "") -> int:
        if self.hold and self.auto:
            self.auto[-1]["sid"] = sid
            self.auto[-1]["file"] = file
            return self.auto[-1]["n"]
        n = max((a["n"] for a in self.auto), default=0) + 1
        self.auto.append({"n": n, "t0": float(t), "t1": None, "sid": sid, "file": file})
        self.version += 1
        return n

    def stopped(self, t: float) -> None:
        if self.hold:
            return
        for a in reversed(self.auto):
            if a["t1"] is None:
                a["t1"] = max(float(t), a["t0"])
                self.version += 1
                return

    def span(self, n: int) -> dict | None:
        return next((a for a in self.auto if a["n"] == n), None)

    def set_start(self, n: int, t: float) -> None:
        a = self.span(n)
        if a is not None:
            a["t0"] = float(t)
            self.version += 1

    # ---- ghost of a Start REC being moved
    def set_ghost(self, n: int | None, t: float = 0.0) -> None:
        self.ghost = None if n is None else {"n": n, "t": float(t)}
        self.version += 1

    # ---- manual areas
    def open_manual(self) -> dict | None:
        """The area that has its start but no stop yet."""
        return next((m for m in self.manual if m["b"] is None), None)

    def next_manual_n(self) -> int:
        return max((m["n"] for m in self.manual), default=0) + 1

    def place_manual(self, t: float) -> tuple[int, str]:
        """The 'Manual Start REC' / 'Manual Stop REC' of the chart menu: starts a new area, or closes the open one at `t`
        (the two ends are put in time order). Returns (n, 'start' | 'stop')."""
        m = self.open_manual()
        self.version += 1
        if m is None:
            n = self.next_manual_n()
            self.manual.append({"n": n, "a": float(t), "b": None, "saved": ""})
            return n, "start"
        if float(t) == m["a"]:
            raise ValueError("Start i Stop obszaru Manual REC muszą leżeć w różnych chwilach.")
        m["a"], m["b"] = sorted((m["a"], float(t)))
        return m["n"], "stop"

    def manual_get(self, n: int) -> dict | None:
        return next((m for m in self.manual if m["n"] == n), None)

    def remove_manual(self, n: int) -> None:
        self.manual = [m for m in self.manual if m["n"] != n]
        self.version += 1

    def move_manual(self, n: int, a: float, b: float | None) -> None:
        m = self.manual_get(n)
        if m is not None:
            m["a"], m["b"] = (min(a, b), max(a, b)) if b is not None else (a, None)
            m["saved"] = ""                       # another piece of the chart now: it has to be saved again
            self.version += 1

    def mark_saved(self, n: int, where: str) -> None:
        m = self.manual_get(n)
        if m is not None:
            m["saved"] = where
            self.version += 1

    def unsaved(self) -> list[dict]:
        """Complete areas that were not written to a recording yet."""
        return [m for m in self.manual if m["b"] is not None and not m["saved"]]

    # ---- names
    @staticmethod
    def name_start(n: int) -> str:
        return f"Start REC ({n})"

    @staticmethod
    def name_stop(n: int) -> str:
        return f"Stop REC ({n})"

    @staticmethod
    def name_manual(n: int) -> str:
        return f"Manual REC ({n})"

    # ---- what the chart draws
    def items(self, look: dict, fmt: Callable[[float], str] = lambda t: f"{t:.2f} s") -> list[dict]:
        """Items for PlotView.set_markers: Start / Stop REC lines (when switched on in the marker look) and the manual areas."""
        out: list[dict] = []
        col, width, style = look.get("rec_color", "#ff8c1a"), int(look.get("rec_width", 2)), look.get("rec_style", "solid")

        def line(kind: int, n: int, t: float, title: str, tip: str) -> dict:
            return {"id": pid(kind, n), "kind": "point", "x0": t, "x1": t, "color": col, "width": width, "style": style, "opacity": 0,
                    "priority": 3, "title": title, "tip": tip, "signals": []}

        if look.get("rec_show", 1):
            for a in self.auto:
                out.append(line(AUTO_START, a["n"], a["t0"], self.name_start(a["n"]),
                                f"<b>{self.name_start(a['n'])}</b><br>{fmt(a['t0'])}" + ("" if a["t1"] is not None else "<br>nagrywanie trwa")))
                if a["t1"] is not None:
                    dur = a["t1"] - a["t0"]
                    out.append(line(AUTO_STOP, a["n"], a["t1"], self.name_stop(a["n"]),
                                    f"<b>{self.name_stop(a['n'])}</b><br>{fmt(a['t1'])}<br>czas nagrywania {dur:.1f} s"))
        opacity = int(look.get("rec_opacity", 24))
        for m in self.manual:
            n = m["n"]
            saved = f"<br><i>zapisano: {m['saved']}</i>" if m["saved"] else "<br>niezapisany – prawy przycisk → „Zapis Manual REC”"
            if m["b"] is None:
                out.append({**line(MANUAL, n, m["a"], f"Manual Start REC ({n})", f"<b>Manual Start REC ({n})</b><br>{fmt(m['a'])}<br>czekam na „Manual Stop REC”"),
                            "style": "dash"})
            else:
                out.append({"id": pid(MANUAL, n), "kind": "range", "x0": m["a"], "x1": m["b"], "color": col, "width": width, "style": "dash",
                            "opacity": opacity, "priority": 3, "title": f"Manual Start REC ({n})", "title2": f"Manual Stop REC ({n})",
                            "tip": f"<b>{self.name_manual(n)}</b><br>od {fmt(m['a'])}<br>do {fmt(m['b'])}<br>czas {m['b'] - m['a']:.1f} s" + saved,
                            "signals": []})
        return out
