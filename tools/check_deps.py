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


def scan(folder):
    """Names of the DLL / PYD files in `folder` (and its *.libs sibling) that need something missing on Server 2016."""
    bad = []
    for d in (folder, folder + ".libs"):
        if not os.path.isdir(d):
            continue
        for dll in sorted(f for f in os.listdir(d) if f.lower().endswith((".dll", ".pyd"))):
            dlls, funcs = imports(os.path.join(d, dll))
            hit = (dlls & FORBIDDEN) | (funcs & FORBIDDEN_FUNCS)
            if hit:
                bad.append((dll, sorted(hit)))
    return bad


def main(root):
    site = os.path.join(root, "Lib", "site-packages")
    bad = scan(os.path.join(site, "PySide6"))
    for dll, hit in bad:
        print(f"BLAD: {dll} wymaga {hit}")
    print("zaleznosci Qt OK (Server 2016 / Win10 1607)" if not bad else "Paczka nie ruszy na Windows Server 2016")
    # PostgreSQL driver (TimescaleDB target): psycopg-binary brings libpq.dll. Not fatal - without it the program falls
    # back to the pure-Python pg8000 (store._psycopg) - but the builder should know which driver Server 2016 will get.
    pg = scan(os.path.join(site, "psycopg_binary"))
    if pg:
        for dll, hit in pg:
            print(f"UWAGA: {dll} (psycopg) wymaga {hit} - na Server 2016 TimescaleDB pojdzie przez pg8000")
    elif os.path.isdir(os.path.join(site, "psycopg_binary")):
        print("psycopg-binary OK (Server 2016 / Win10 1607)")
    print("pg8000 (zapas dla psycopg): " + ("jest" if os.path.isdir(os.path.join(site, "pg8000")) else "BRAK"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
