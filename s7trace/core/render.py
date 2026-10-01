"""Pure helpers turning sampled data into plottable step curves."""
from __future__ import annotations

import numpy as np


def compress_runs(t: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Drop samples inside constant runs (keeps first/last and every change)."""
    n = len(t)
    if n < 3:
        return t, y
    ynan = np.isnan(y)
    same_prev = (y[1:-1] == y[:-2]) & ~ynan[1:-1] & ~ynan[:-2]
    same_next = (y[1:-1] == y[2:]) & ~ynan[1:-1] & ~ynan[2:]
    keep = np.ones(n, dtype=bool)
    keep[1:-1] = ~(same_prev & same_next)
    return t[keep], y[keep]


def peak_decimate(t: np.ndarray, y: np.ndarray, buckets: int) -> tuple[np.ndarray, np.ndarray]:
    """Min/max decimation to ~2*buckets points, preserving time order (vectorised)."""
    n = len(t)
    if n <= buckets * 2:
        return t, y
    k = -(-n // buckets)                      # samples per bucket
    nb = -(-n // k)
    ii = np.minimum(np.arange(nb * k).reshape(nb, k), n - 1)
    seg = y[ii]
    nan = np.isnan(seg)
    rows = np.arange(nb)
    imin = ii[rows, np.where(nan, np.inf, seg).argmin(axis=1)]
    imax = ii[rows, np.where(nan, -np.inf, seg).argmax(axis=1)]
    parts = [imin, imax]
    if nan.any():                             # keep one NaN per bucket so gaps survive
        inan = ii[rows, nan.argmax(axis=1)]
        parts.append(inan[nan.any(axis=1)])
        parts.append(ii[:, 0])
    idx = np.unique(np.concatenate(parts))
    return t[idx], y[idx]


def make_step(t: np.ndarray, y: np.ndarray, x_end: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Sample-and-hold: value y[i] stays until t[i+1]; optionally extended to x_end."""
    if len(t) == 0:
        return t, y
    xs = np.repeat(t, 2)[1:]
    ys = np.repeat(y, 2)[:-1]
    if x_end is not None and x_end > t[-1]:
        xs = np.append(xs, x_end)
        ys = np.append(ys, y[-1])
    return xs, ys


def curve_data(t: np.ndarray, raw: np.ndarray, gain: float, offset: float,
               x_end: float | None, max_points: int = 6000) -> tuple[np.ndarray, np.ndarray]:
    y = raw * gain + offset
    t2, y2 = compress_runs(t, y)
    t2, y2 = peak_decimate(t2, y2, max_points // 2)
    return make_step(t2, y2, x_end)
