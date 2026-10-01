"""Zapisuje liste funkcji systemowych (dll,funkcja) importowanych przez biblioteki Qt w paczce.
Diagnoza.bat sprawdza ja na docelowym komputerze (GetProcAddress) - wskazuje WSZYSTKIE brakujace
funkcje naraz. Uzycie: python imports_list.py <folder python\\> <plik wyjsciowy.csv>
"""
import os
import sys

import pefile

SKIP_PREFIX = ("qt6", "shiboken", "pyside", "msvcp", "vcruntime", "python", "concrt", "libcrypto", "libssl")


def main(root, out):
    sp = os.path.join(root, "Lib", "site-packages")
    targets = []
    for sub in ("PySide6", "shiboken6"):
        d = os.path.join(sp, sub)
        targets += [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".dll", ".pyd"))]
    pairs = set()
    for path in targets:
        try:
            pe = pefile.PE(path, fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        except Exception:
            continue
        for imp in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            dll = imp.dll.decode().lower()
            if dll.startswith(SKIP_PREFIX):
                continue
            for f in imp.imports:
                if f.name:
                    pairs.add((dll, f.name.decode()))
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        for dll, fn in sorted(pairs):
            fh.write(f"{dll},{fn}\n")
    print(f"imports.csv: {len(pairs)} funkcji systemowych")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
