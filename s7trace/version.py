"""Program identity shown in 'O programie' (desktop) and in the Web page. Update VERSION (+0.01 with every change) and DATE
(dd-mm-yyyy) together whenever the program is changed - see CLAUDE.md."""
AUTHOR = "PWOL79 & CLAUDE"
VERSION = "1.21"
DATE = "06-10-2026"


def about_lines() -> list[str]:
    return ["S7Trace — rejestrator przebiegów z PLC Siemens S7", "(S7comm przez python-snap7, wykresy pyqtgraph).", "",
            f"Autor: {AUTHOR}", f"Wersja: {VERSION}", f"Data: {DATE}"]
