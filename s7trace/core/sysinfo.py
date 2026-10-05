"""CPU load of the computer the program runs on (Qt-free). Windows: GetSystemTimes (idle / kernel / user) deltas; elsewhere unknown."""
from __future__ import annotations

import sys
import time

_prev: tuple[int, int, int] | None = None
_last: tuple[float, float | None] = (0.0, None)           # (monotonic time of the last measurement, percent)
MIN_INTERVAL = 0.9                                          # [s] shorter intervals reuse the last value (every tab asks, one clock)


def _times() -> tuple[int, int, int] | None:
    """(idle, kernel, user) in 100 ns units since boot; kernel includes idle."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        a, b, c = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(a), ctypes.byref(b), ctypes.byref(c)):
            return None
        return tuple((f.dwHighDateTime << 32) | f.dwLowDateTime for f in (a, b, c))
    except Exception:
        return None


def cpu_percent() -> float | None:
    """Load of all processors [%] since the previous call (None = not known yet / not available)."""
    global _prev, _last
    now = time.monotonic()
    if now - _last[0] < MIN_INTERVAL:
        return _last[1]
    cur = _times()
    pct = None
    if cur is not None and _prev is not None:
        di, dk, du = (c - p for c, p in zip(cur, _prev))
        total = dk + du
        if total > 0:
            pct = max(0.0, min(100.0, 100.0 * (1.0 - di / total)))
    if cur is not None:
        _prev = cur
    _last = (now, pct if pct is not None else _last[1])
    return _last[1]


# ------------------------------------------------------------------ the load this program itself puts on the computer
_app_prev: dict[int, int] = {}                              # pid -> CPU time (100 ns units) at the last measurement
_app_last: tuple[float, float, float | None] = (0.0, 0.0, None)   # (monotonic time, wall time of the interval start, percent)
_app_state: dict = {"t": 0.0}


def _child_pids(parent: int) -> list[int]:
    """Processes started by `parent` (the acquisition processes of the tabs), via a ToolHelp snapshot."""
    import ctypes
    from ctypes import wintypes

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x2, 0)                # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out, e = [], ENTRY()
    e.dwSize = ctypes.sizeof(ENTRY)
    try:
        ok = k.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(e))
        while ok:
            if e.th32ParentProcessID == parent:
                out.append(int(e.th32ProcessID))
            ok = k.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(e))
    finally:
        k.CloseHandle(wintypes.HANDLE(snap))
    return out


def _process_time(pid: int) -> int | None:
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(0x1000, False, pid)                     # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        c, x, kt, ut = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(x), ctypes.byref(kt), ctypes.byref(ut)):
            return None
        return sum((f.dwHighDateTime << 32) | f.dwLowDateTime for f in (kt, ut))
    finally:
        k.CloseHandle(h)


def app_cpu_percent() -> float | None:
    """CPU load [% of the whole computer, like cpu_percent()] caused by this program: its own process plus its child processes
    (the acquisition processes) since the previous call; None = not known yet / not available."""
    global _app_last
    import os
    now = time.monotonic()
    if now - _app_last[0] < MIN_INTERVAL:
        return _app_last[2]
    if sys.platform != "win32":
        return None
    try:
        me = os.getpid()
        times = {}
        for pid in [me] + _child_pids(me):
            t = _process_time(pid)
            if t is not None:
                times[pid] = t
        pct = _app_last[2]
        if _app_prev and _app_state["t"]:
            wall = now - _app_state["t"]
            used = sum(max(0, t - _app_prev.get(pid, 0)) for pid, t in times.items()) / 1e7        # CPU seconds in the interval
            if wall > 0:
                pct = max(0.0, min(100.0, 100.0 * used / (wall * (os.cpu_count() or 1))))
        _app_prev.clear()
        _app_prev.update(times)
        _app_state["t"] = now
        _app_last = (now, 0.0, pct)
        return pct
    except Exception:
        return None
