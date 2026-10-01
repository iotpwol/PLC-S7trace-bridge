"""Sprawdza, czy Qt w paczce przenosnej nie wymaga systemowych DLL, ktorych brakuje na starszych
Windowsach (Server 2016 / Windows 10 1607). Uzycie: python check_deps.py <folder python\\ przenosnego>.
Kod wyjscia 1 = znaleziono niedozwolona zaleznosc.
"""
import os
import sys

import pefile

FORBIDDEN = {"icuuc.dll", "icu.dll", "icuin.dll"}   # tylko od Windows 10 1703 / 1903


FORBIDDEN_FUNCS = {"setthreaddescription", "getthreaddescription"}   # dodane po Windows 10 1607 / Server 2016


def imports(path):
    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    dlls, funcs = set(), set()
    for i in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        dlls.add(i.dll.decode().lower())
        funcs |= {(f.name or b"").decode().lower() for f in i.imports}
    return dlls, funcs


def main(root):
    ps = os.path.join(root, "Lib", "site-packages", "PySide6")
    bad = False
    for dll in sorted(f for f in os.listdir(ps) if f.lower().endswith((".dll", ".pyd"))):
        dlls, funcs = imports(os.path.join(ps, dll))
        hit = (dlls & FORBIDDEN) | (funcs & FORBIDDEN_FUNCS)
        if hit:
            print(f"BLAD: {dll} wymaga {sorted(hit)}")
            bad = True
    print("zaleznosci Qt OK (Server 2016 / Win10 1607)" if not bad else "Paczka nie ruszy na Windows Server 2016")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
