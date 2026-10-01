"""CSV export / import. Values are raw (before gain / offset).

Format:
    # s7trace v1
    # signal: {json}         (one line per signal, restores colour/offset/gain)
    time_s,timestamp,SIG1,SIG2,...
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta

import numpy as np

from .types import Signal, DEFAULT_COLORS


def write_csv(path: str, signals: list[Signal], t: np.ndarray, v: np.ndarray,
              start_wall: datetime | None = None) -> None:
    start_wall = start_wall or datetime.now()
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# s7trace v1\n")
        for s in signals:
            f.write("# signal: " + json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
        w = csv.writer(f)
        w.writerow(["time_s", "timestamp"] + [s.name for s in signals])
        for ti, row in zip(t, v):
            ts = (start_wall + timedelta(seconds=float(ti))).isoformat(timespec="milliseconds")
            w.writerow([f"{ti:.4f}", ts] + ["" if x != x else f"{x:.10g}" for x in row])


class CsvRecorder:
    """Streaming writer for the REC button (flushes periodically)."""

    def __init__(self, path: str, signals: list[Signal], start_wall: datetime | None = None):
        self.start_wall = start_wall or datetime.now()
        self._f = open(path, "w", newline="", encoding="utf-8")
        self._f.write("# s7trace v1\n")
        for s in signals:
            self._f.write("# signal: " + json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
        self._w = csv.writer(self._f)
        self._w.writerow(["time_s", "timestamp"] + [s.name for s in signals])
        self._n = 0
        self.path = path

    def write(self, t: float, values) -> None:
        ts = (self.start_wall + timedelta(seconds=t)).isoformat(timespec="milliseconds")
        self._w.writerow([f"{t:.4f}", ts] + ["" if x != x else f"{x:.10g}" for x in values])
        self._n += 1
        if self._n % 40 == 0:
            self._f.flush()

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass


def read_csv(path: str) -> tuple[list[Signal], np.ndarray, np.ndarray]:
    sigs_meta: dict[str, dict] = {}
    rows: list[list[str]] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        header = None
        for line in f:
            if line.startswith("#"):
                if line.startswith("# signal:"):
                    try:
                        d = json.loads(line[len("# signal:"):])
                        sigs_meta[d["name"]] = d
                    except Exception:
                        pass
                continue
            if header is None:
                sep = ";" if line.count(";") > line.count(",") else ","
                header = next(csv.reader([line], delimiter=sep))
                continue
            rows.append(next(csv.reader([line], delimiter=sep)))
    if header is None or not rows:
        raise ValueError("Plik CSV nie zawiera danych.")
    names = [h.strip() for h in header]
    tcol = names.index("time_s") if "time_s" in names else 0
    skip = {tcol}
    ts_col = names.index("timestamp") if "timestamp" in names else None
    if ts_col is not None:
        skip.add(ts_col)
    sig_cols = [i for i in range(len(names)) if i not in skip]
    t = np.empty(len(rows))
    v = np.full((len(rows), len(sig_cols)), np.nan)
    t_wall0 = None
    for r, row in enumerate(rows):
        if "time_s" in names or ts_col is None:
            t[r] = float(row[tcol].replace(",", ".")) if row[tcol] else np.nan
        else:
            dt = datetime.fromisoformat(row[ts_col])
            t_wall0 = t_wall0 or dt
            t[r] = (dt - t_wall0).total_seconds()
        for j, c in enumerate(sig_cols):
            if c < len(row) and row[c].strip() != "":
                try:
                    v[r, j] = float(row[c].replace(",", "."))
                except ValueError:
                    pass
    signals = []
    for j, c in enumerate(sig_cols):
        name = names[c]
        if name in sigs_meta:
            s = Signal.from_dict(sigs_meta[name])
        else:
            s = Signal(name=name, color=DEFAULT_COLORS[j % len(DEFAULT_COLORS)],
                       offset_y=round(-1.1 * j, 3))
        signals.append(s)
    return signals, t, v
