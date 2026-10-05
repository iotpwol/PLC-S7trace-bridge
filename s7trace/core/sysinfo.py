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


def cpu_time_percent() -> float | None:
    """Classic load of all processors [%] ('% Processor Time': busy time / total time) since the previous call; None = not known yet."""
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


# ------------------------------------------------------------------ '% Processor Utility' = the number the Task Manager shows
# Task Manager (Windows 10 1709+ / Server 2019+) reports the frequency-scaled 'Processor Utility', which on a busy / turbo / virtual CPU is
# clearly higher than the plain busy time; PDH gives the same counter. Where it is not available the plain busy time is used.
_pdh: dict = {"q": None, "c": None, "tried": False, "t": 0.0, "v": None}


def _utility_percent() -> float | None:
    if sys.platform != "win32":
        return None
    now = time.monotonic()
    if _pdh["tried"] and _pdh["q"] is None:
        return None
    if now - _pdh["t"] < MIN_INTERVAL:
        return _pdh["v"]
    try:
        import ctypes
        from ctypes import wintypes
        pdh = ctypes.windll.pdh
        if not _pdh["tried"]:
            _pdh["tried"] = True
            q, c = ctypes.c_void_p(), ctypes.c_void_p()
            if pdh.PdhOpenQueryW(None, 0, ctypes.byref(q)) != 0:
                return None
            if pdh.PdhAddEnglishCounterW(q, r"\Processor Information(_Total)\% Processor Utility", 0, ctypes.byref(c)) != 0:
                pdh.PdhCloseQuery(q)
                return None
            _pdh["q"], _pdh["c"] = q, c
            pdh.PdhCollectQueryData(q)                         # the first sample only starts the interval
            _pdh["t"] = now
            return None
        pdh.PdhCollectQueryData(_pdh["q"])

        class VAL(ctypes.Structure):
            _fields_ = [("CStatus", wintypes.DWORD), ("pad", wintypes.DWORD), ("v", ctypes.c_double)]
        v, kind = VAL(), wintypes.DWORD()
        if pdh.PdhGetFormattedCounterValue(_pdh["c"], 0x200, ctypes.byref(kind), ctypes.byref(v)) == 0:       # PDH_FMT_DOUBLE
            _pdh["v"] = max(0.0, min(100.0, float(v.v)))
        _pdh["t"] = now
        return _pdh["v"]
    except Exception:
        _pdh["q"] = None
        return None


def cpu_percent() -> float | None:
    """Load of the computer [%] as the Task Manager shows it ('Processor Utility'); the plain busy time where that counter is missing."""
    u = _utility_percent()
    raw = cpu_time_percent()
    return u if u is not None else raw


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
        u, raw = _utility_percent(), _last[1]
        if pct is not None and u is not None and raw and raw > 0.3:        # the same scale as the Task Manager: share of the busy time x utility
            pct = min(u, pct * u / raw)
        _app_last = (now, 0.0, pct)
        return pct
    except Exception:
        return None


_os_name: str | None = None


def os_name() -> str:
    """The system the program runs under, e.g. 'Windows Server 2019 Standard (build 17763)'."""
    global _os_name
    if _os_name is None:
        import platform
        name = ""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
                name = str(winreg.QueryValueEx(k, "ProductName")[0])
                build = str(winreg.QueryValueEx(k, "CurrentBuildNumber")[0])
            if name.startswith("Windows 10") and build.isdigit() and int(build) >= 22000:
                name = "Windows 11" + name[len("Windows 10"):]            # the registry keeps the old product name on Windows 11
            name = f"{name} (build {build})"
        except Exception:
            name = platform.platform()
        _os_name = name
    return _os_name
