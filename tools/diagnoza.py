"""Diagnostyka wersji przenosnej S7Trace (tylko biblioteka standardowa).

Uruchamiana przez Diagnoza.bat. Sprawdza wersje Windows, systemowe DLL wymagane przez Qt,
biblioteki Visual C++, kompletnosc plikow (MANIFEST.csv) i probuje zaladowac Qt.
Wynik zapisuje do diagnoza.txt obok S7Trace.bat.
"""
import ctypes
import os
import platform
import sys
import traceback
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS = os.path.join(ROOT, "python", "Lib", "site-packages", "PySide6")
LINES = []


def out(s=""):
    print(s)
    LINES.append(s)


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.LoadLibraryExW.restype = wintypes.HMODULE
k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x800


def sys_dll(name):
    h = k32.LoadLibraryExW(name, None, LOAD_LIBRARY_SEARCH_SYSTEM32)
    return (True, 0) if h else (False, ctypes.get_last_error())


def file_version(path):
    try:
        v = ctypes.WinDLL("version", use_last_error=True)
        size = v.GetFileVersionInfoSizeW(path, None)
        if not size:
            return "?"
        buf = ctypes.create_string_buffer(size)
        v.GetFileVersionInfoW(path, 0, size, buf)
        p = ctypes.c_void_p()
        n = wintypes.UINT()
        v.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(n))

        class FFI(ctypes.Structure):
            _fields_ = [(f, wintypes.DWORD) for f in (
                "sig", "ver", "ms", "ls", "pms", "pls", "mask", "flags", "os", "type", "sub", "dms", "dls")]
        f = ctypes.cast(p, ctypes.POINTER(FFI)).contents
        return f"{f.ms >> 16}.{f.ms & 0xFFFF}.{f.ls >> 16}.{f.ls & 0xFFFF}"
    except Exception as e:
        return f"? ({e})"


def main():
    out("=== S7Trace - diagnostyka ===")
    out(f"Folder programu : {ROOT}  (dlugosc sciezki {len(ROOT)})")
    drive = os.path.splitdrive(ROOT)[0] + "\\"
    dtype = {0: "nieznany", 1: "brak", 2: "wymienny (USB)", 3: "dysk lokalny", 4: "SIECIOWY",
             5: "CD", 6: "RAM"}.get(k32.GetDriveTypeW(drive), "?")
    out(f"Typ dysku {drive:4}: {dtype}" + ("   <-- Qt moze nie ladowac sie z dysku sieciowego/wymiennego; skopiuj na C:" if dtype in ("SIECIOWY", "wymienny (USB)") else ""))
    wv = sys.getwindowsversion()
    out(f"Windows         : {platform.platform()}  (build {wv.build})")
    out(f"Python          : {sys.version.split()[0]} {platform.architecture()[0]}")
    if wv.build < 14393:
        out("  !!! Windows starszy niz Windows 10 1607 / Server 2016 - Qt 6 tu nie zadziala.")
    elif wv.build < 17763:
        out("  (Windows starszy niz 10 1809 / Server 2019 - Qt 6.8 nie jest tu oficjalnie wspierany, ale zwykle dziala.)")

    out("\n--- Systemowe DLL wymagane przez Qt ---")
    bad = []
    for n in ("d3d12.dll", "d3d11.dll", "dxgi.dll", "dwrite.dll", "dwmapi.dll", "uxtheme.dll",
              "authz.dll", "mpr.dll", "netapi32.dll", "userenv.dll", "winmm.dll", "version.dll", "ws2_32.dll",
              "ole32.dll", "oleaut32.dll", "shell32.dll", "gdi32.dll", "user32.dll"):
        ok, err = sys_dll(n)
        out(f"  {n:14} {'OK' if ok else 'BRAK (blad ' + str(err) + ')'}")
        if not ok:
            bad.append(n)
    if bad:
        out(f"  !!! Brakuje w systemie: {', '.join(bad)}")

    out("\n--- Biblioteki Visual C++ (wersje plikow) ---")
    sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for label, p in (("python\\vcruntime140.dll", os.path.join(ROOT, "python", "vcruntime140.dll")),
                     ("PySide6\\msvcp140.dll", os.path.join(PS, "msvcp140.dll")),
                     ("System32\\vcruntime140.dll", os.path.join(sysdir, "vcruntime140.dll")),
                     ("System32\\msvcp140.dll", os.path.join(sysdir, "msvcp140.dll"))):
        out(f"  {label:28} {file_version(p) if os.path.exists(p) else 'brak pliku'}")

    out("\n--- Funkcje systemowe wymagane przez Qt (imports.csv) ---")
    ip = os.path.join(ROOT, "imports.csv")
    if not os.path.exists(ip):
        out("  brak imports.csv - pomijam")
    else:
        k32.GetProcAddress.restype = ctypes.c_void_p
        k32.GetProcAddress.argtypes = [wintypes.HMODULE, ctypes.c_char_p]
        total, missing, no_dll = 0, [], set()
        mods = {}
        with open(ip, encoding="utf-8-sig") as f:
            for line in f:
                dll, _, fn = line.strip().partition(",")
                if not dll:
                    continue
                total += 1
                if dll not in mods:
                    mods[dll] = k32.LoadLibraryExW(dll, None, LOAD_LIBRARY_SEARCH_SYSTEM32) or None
                if not mods[dll]:
                    no_dll.add(dll)
                elif not k32.GetProcAddress(mods[dll], fn.encode()):
                    missing.append(f"{dll}!{fn}")
        out(f"  sprawdzono {total} funkcji; brakujacych: {len(missing)}; brakujacych bibliotek: {len(no_dll)}")
        for m in missing:
            out(f"    BRAK FUNKCJI  {m}")
        for m in sorted(no_dll):
            out(f"    BRAK BIBLIOTEKI  {m}")
        if missing or no_dll:
            out("  !!! Qt w tej wersji uzywa funkcji, ktorych ten Windows nie ma - program sie nie uruchomi.")

    out("\n--- Kompletnosc plikow (MANIFEST.csv) ---")
    mf = os.path.join(ROOT, "MANIFEST.csv")
    if not os.path.exists(mf):
        out("  brak MANIFEST.csv - pomijam")
    else:
        missing, wrong, total = [], [], 0
        with open(mf, encoding="utf-8-sig") as f:
            for line in f:
                rel, _, size = line.rstrip("\n").rpartition(",")
                if not rel:
                    continue
                total += 1
                p = os.path.join(ROOT, rel)
                if not os.path.exists(p):
                    missing.append(rel)
                elif os.path.getsize(p) != int(size):
                    wrong.append(rel)
        out(f"  plikow w manifescie: {total}, brakujacych: {len(missing)}, ze zmienionym rozmiarem: {len(wrong)}")
        for r in missing[:25]:
            out(f"    BRAK  {r}")
        for r in wrong[:25]:
            out(f"    ROZMIAR  {r}")

    out("\n--- Ladowanie bibliotek Qt ---")
    SB = os.path.join(os.path.dirname(PS), "shiboken6")
    if os.path.isdir(PS):
        os.add_dll_directory(PS)
        os.add_dll_directory(SB)
        for d, n in ((SB, "shiboken6.abi3.dll"), (PS, "Qt6Core.dll"), (PS, "Qt6Gui.dll"), (PS, "Qt6Widgets.dll")):
            try:
                ctypes.WinDLL(os.path.join(d, n))
                out(f"  {n:24} OK")
            except OSError as e:
                out(f"  {n:24} BLAD: {e}")
    else:
        out("  brak folderu PySide6 - niekompletna paczka")

    out("\n--- Importy Pythona ---")
    for mod in ("numpy", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "pyqtgraph", "snap7"):
        try:
            __import__(mod)
            out(f"  {mod:20} OK")
        except Exception as e:
            out(f"  {mod:20} BLAD: {e}")

    path = os.path.join(ROOT, "diagnoza.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(LINES))
        out(f"\nWynik zapisano w: {path}")
    except OSError as e:
        out(f"\nNie mozna zapisac diagnoza.txt: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
