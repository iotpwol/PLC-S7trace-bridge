# S7Trace

Rejestrator przebiegów z PLC Siemens S7 (S7comm przez `python-snap7`, wykresy `pyqtgraph`, GUI `PySide6`).

## Uruchomienie

```
run.bat            # tworzy .venv przy pierwszym starcie i uruchamia aplikację
run_sim.bat        # lokalny symulator PLC na 127.0.0.1:1102 (do prób bez sterownika)
.venv\Scripts\python -m pytest tests -q
```

## Wersja przenośna (bez Pythona na komputerze)

```
powershell -ExecutionPolicy Bypass -File build-portable.ps1
```

Skrypt (na komputerze z internetem) składa `dist\S7Trace\` (ok. 190 MB) i `dist\S7Trace-portable-<data>.zip` (ok. 70 MB):
`python\` (Python 3.12 „embeddable” z już zainstalowanymi pakietami), `app\` (kod), `S7Trace.bat`,
`S7Trace-debug.bat` (z konsolą, pokazuje błędy), `Symulator.bat`, `CZYTAJ.txt`.
Na docelowym komputerze wystarczy rozpakować cały folder i uruchomić `S7Trace.bat` — bez Pythona i bez internetu.
Domyślnie używa ZIP-a Pythona z `NOTE_VIS` (`-EmbedZip` pozwala wskazać inny).
Do `dist\` nic nie jest commitowane (`.gitignore`). Uwaga: `C:\Dev\Python-3.14.8` to źródła CPythona, nie binarki.

`run.bat` to wariant deweloperski (wymaga zainstalowanego Pythona 3; sam odtwarza `.venv` skopiowany z innego komputera).

Symulator: w aplikacji wpisz IP `127.0.0.1:1102`, rack 0, slot 2; sygnały: DB1 bajt 160 bit 0–4 (BOOL),
DB1 bajt 170 (INT, licznik), DB1 bajt 172 (REAL, sinus).

## Sterownik

| CPU | Rack / Slot | Wymagania |
|---|---|---|
| S7-300 / 400 | 0 / 2 | — |
| S7-1200 / 1500 | 0 / 1 | CPU: „Permit access with PUT/GET”, DB bez „Optimized block access” |

IP można podać z portem (`host:port`). Adresowanie jest bezwzględne: `I`, `Q`, `M`, `DB` + bajt/bit.
Typy: BOOL, BYTE, SINT, USINT, WORD, INT, UINT, DWORD, DINT, UDINT, REAL, LREAL.

## Funkcje

* Zakładki = niezależne połączenia (dół okna, `+` dodaje). Kropka przy nazwie: zielona = praca, szara = stop.
* Wykres przesuwa się w czasie rzeczywistym: najnowsze próbki po prawej, szerokość = „Okno czasu”.
  Przeciągnięcie / zoom myszą wstrzymuje widok (zbieranie trwa); „Wznów” wraca do trybu na żywo.
  Pasek pod wykresem = cała nagrana historia, żółty obszar = widoczne okno (można go przesuwać).
* Tryby komunikacji: bloki grupowane (scala sąsiednie adresy), pojedyncze, multi-read (1 zapytanie).
* Odczyt PLC działa w osobnym procesie, więc rysowanie wykresu nie opóźnia cykli.
  Pasek statusu: opóźnienie odczytu (średnia z 50 / ostatnie), opóźnienie GUI, liczba i % pominiętych cykli.
* Utrata połączenia: automatyczne ponawianie co 2 s, w danych zostaje przerwa (NaN).
* Trigger: `==`, `>`, `<`, `between`, `rising edge`, `falling edge`, histereza, pretrigger.
  Akcje: Pauza, Zapis CSV, Pauza + zapis CSV. Porównywana jest wartość surowa (bez gain / offsetu Y).
  Dla sygnałów BOOL użyj progu A = 0,5 przy zboczach.
  Nazwa pliku: `{tab}`, `{date}`, `{time}`. Ścieżka względna liczona od katalogu uruchomienia.
* REC: ciągły zapis wszystkich próbek do `rec_{tab}_{date}_{time}.csv`.
* Punkty: znaczniki próbek. V / H znacznik: kliknięcie na wykresie stawia kursor (max 2), odczyt wartości i Δ.
* CSV: `Eksport okna → CSV`, `Import CSV → wykres` (CSV zapisuje definicje sygnałów w komentarzach `# signal:`).
* Symbole (Plik → Importuj symbole): tablica tagów TIA (.xlsx/.csv), źródło DB z TIA (.db/.scl) i XML,
  Step 7 (.sdf/.asc/.seq). Potem „Sygnały… → Z symboli…”.
  Offsety w DB liczone według zasad wyrównania S7 dla bloków nieoptymalizowanych.
* Konfiguracja zapisywana przy zamknięciu w `%APPDATA%\S7Trace\config.json` (zakładki, sygnały, trigger).
