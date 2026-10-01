"""Thread-safe growable sample store (time + N signal columns)."""
from __future__ import annotations

import threading

import numpy as np


class TraceBuffer:
    def __init__(self, n_signals: int = 0, max_samples: int = 2_000_000):
        self._lock = threading.Lock()
        self.max_samples = max_samples
        self.reset(n_signals)

    def reset(self, n_signals: int | None = None) -> None:
        with self._lock:
            if n_signals is not None:
                self.n = n_signals
            self._cap = 4096
            self._t = np.empty(self._cap, dtype=np.float64)
            self._v = np.empty((self._cap, max(self.n, 1)), dtype=np.float64)
            self._len = 0
            self.dropped = 0   # samples trimmed off the front
            self.version = 0

    def __len__(self) -> int:
        return self._len

    def append(self, t: float, values) -> None:
        with self._lock:
            if self._len == self._cap:
                if self._cap >= self.max_samples:
                    cut = self._cap // 4
                    self._t[: self._len - cut] = self._t[cut: self._len]
                    self._v[: self._len - cut] = self._v[cut: self._len]
                    self._len -= cut
                    self.dropped += cut
                else:
                    self._cap *= 2
                    self._t = np.resize(self._t, self._cap)
                    nv = np.empty((self._cap, self._v.shape[1]), dtype=np.float64)
                    nv[: self._len] = self._v[: self._len]
                    self._v = nv
            self._t[self._len] = t
            self._v[self._len, : self.n] = values
            self._len += 1
            self.version += 1

    def load(self, t: np.ndarray, v: np.ndarray) -> None:
        """Replace the whole content (CSV import)."""
        with self._lock:
            n = len(t)
            self.n = v.shape[1]
            self._cap = max(4096, n)
            self._t = np.empty(self._cap)
            self._v = np.empty((self._cap, max(self.n, 1)))
            self._t[:n] = t
            self._v[:n, : self.n] = v
            self._len = n
            self.dropped = 0
            self.version += 1

    def snapshot(self, t0: float | None = None, t1: float | None = None):
        """Copy of (t, v) restricted to [t0, t1] plus one sample on each side."""
        with self._lock:
            n = self._len
            t = self._t[:n]
            lo, hi = 0, n
            if t0 is not None:
                lo = max(0, int(np.searchsorted(t, t0, "left")) - 1)
            if t1 is not None:
                hi = min(n, int(np.searchsorted(t, t1, "right")) + 1)
            return t[lo:hi].copy(), self._v[lo:hi, : self.n].copy()

    def last_time(self) -> float:
        with self._lock:
            return float(self._t[self._len - 1]) if self._len else 0.0

    def first_time(self) -> float:
        with self._lock:
            return float(self._t[0]) if self._len else 0.0
