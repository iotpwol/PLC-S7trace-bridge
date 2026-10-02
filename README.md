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
* Wykres przesuwa się w czasie rzeczywistym: najnowsze próbki po prawej, szerokość = „Okno czasu” (wpisana w sekundach albo wybrana z listy: 5 s … 24 godz.).
  Przeciągnięcie / zoom myszą wstrzymuje widok (zbieranie trwa); „Wznów” wraca do trybu na żywo.
  Pasek pod wykresem = cała nagrana historia, żółty obszar = widoczne okno (można go przesuwać).
* Tryby komunikacji: bloki grupowane (scala sąsiednie adresy), pojedyncze, multi-read (1 zapytanie).
* Odczyt PLC działa w osobnym procesie, więc rysowanie wykresu nie opóźnia cykli.
  Pasek statusu: opóźnienie odczytu (średnia z 50 / ostatnie), opóźnienie GUI, liczba i % pominiętych cykli.
* Utrata połączenia: automatyczne ponawianie co 2 s, w danych zostaje przerwa (NaN).
* Trigger: `==`, `>`, `<`, `between`, `rising edge`, `falling edge`, histereza, pretrigger.
  Akcje: Pauza, Zapis CSV, Pauza + zapis CSV. Porównywana jest wartość surowa (bez gain / offsetu Y).
  Dla sygnałów BOOL użyj progu A = 0,5 przy zboczach.
  Nazwa pliku (domyślnie `snapshot_{confname}_{ip}_{tab}_{date}_{time}.csv`): `{confname}`, `{ip}`, `{tab}`, `{date}`, `{time}`.
  Ścieżka względna (domyślnie `snapshots`, `rec`) oznacza folder w `Dokumenty\S7Trace` bieżącego użytkownika Windows,
  więc przy wielu kontach każdy ma własne pliki.
* REC: ciągły zapis wszystkich próbek; folder (domyślnie `rec`) i nazwa pliku (domyślnie
  `REC_{confname}_{ip}_{tab}_{date}_{time}.csv`) ustawia się w panelu po lewej pod blokiem Trigger.
* Punkty: znaczniki próbek. V / H znacznik: kliknięcie na wykresie stawia kursor (max 2), odczyt wartości i Δ.
* CSV: `Eksport okna → CSV`, `Import CSV → wykres` (CSV zapisuje definicje sygnałów w komentarzach `# signal:`).
* Symbole (Plik → Importuj symbole): tablica tagów TIA (.xlsx/.csv), źródło DB z TIA (.db/.scl) i XML,
  Step 7 (.sdf/.asc/.seq). Potem „Sygnały… → Z symboli…”.
  Offsety w DB liczone według zasad wyrównania S7 dla bloków nieoptymalizowanych.
* Okno „Sygnały…”: kolumny Pobierz ✓ / Wykres ✓ / Nazwa / Aktualna wartość / Sposób wyświetlania
  (Domyślnie, Dziesiętnie, HEX 16#…, BIN 2#…, TRUE/FALSE, Naukowo) / Źródło / Typ / DB / Bajt / Bit / Offset Y / Gain / Share / Kolor / Opis.
  „Dodaj” dopisuje wiersz zawsze na końcu; nazwa idzie za wierszem z kursorem (`D160B`→`D160C`, `123M1`→`123M2`).
  Zdublowane nazwy: czerwone tło. Zdublowane adresy (źródło, typ, DB, bajt, bit): żółte tło.
  Najechanie na wiersz pokazuje wszystkie dane zmiennej (z opisem i bieżącą wartością).
  Prawy przycisk na nagłówku: ukryj / pokaż kolumnę; „Offset Y”: skoryguj wszystkie, zmień krok;
  „Nazwa”: auto-numerowanie, nazwa z poprzedniej zmiennej / własna. „Zapisz/Wczytaj listę”, „Z innej karty…”.
  Kolejność wierszy zmieniasz chwytając numer wiersza (lewa kolumna) i przeciągając go na inny wiersz.
  Podczas trwającego połączenia można DODAWAĆ nowe zmienne (Dodaj / Z symboli…) — po OK są pobierane od następnego
  cyklu, w starszych próbkach mają przerwę; istniejących wierszy (adres, kolejność, usuwanie) nie zmienisz do Stop.
  Jeśli trwa REC, po dodaniu zmiennej zapis przechodzi do nowego pliku (z nową kolumną).
* Karty są na górze po prawej (w wierszu menu), tak szerokie, by pokazać pełne nazwy (aż do końca menu „Pomoc”);
  kropka-ikona = stan połączenia, aktywna karta: niebieskie tło i żółta czcionka (kolory w Widok → Interfejs).
  Dwuklik / F2 = zmiana nazwy, prawy przycisk = duplikuj, zamknij.
* Plik → Zapisz / Wczytaj konfigurację dotyczy BIEŻĄCEJ karty; wczytanie sprawdza tylko jej połączenie
  (inne karty pracują dalej). Domyślna nazwa `s7trace_signals`, istniejąca → `_001`, `_002`…
  W nazwach plików (trigger) znacznik `{confname}` = nazwa konfiguracji (brak → program pyta, potem `no_name`).
* Przyciski sterujące mają konfigurowalne kolory stanów (Start/Stop/Pauza/REC/znaczniki), kropka REC miga (domyślnie 0,5 Hz).
* Podziały można przeciągać: panel ustawień ↔ wykres oraz wykres główny ↔ pasek podglądu; legendę przeciągniesz myszą
  lub ustawisz w Widok → Położenie legendy (ta karta); położenie jest osobne dla każdej karty. Podwójne kliknięcie legendy otwiera okno Sygnały.
* Układ osi Y (panel Zakres okna wykresu): „Pasma wg Share” (domyślnie) – każdy sygnał ma własne pasmo, wysokość proporcjonalna do kolumny Share,
  skalowanie do MIN…MAX widocznego okna, oś pokazuje wartości MIN / pośrednie / MAX; „Offset + Gain” – wspólna skala jak dawniej.
  Najwęższe okno czasu to 0,1 s (kółko myszy dalej nie powiększa).
* Diagnostyka połączenia (przycisk „Diagnostyka…”, Ustawienia → Diagnostyka połączenia…, Ctrl+D): ocena łącza, czas odczytu (chwilowy / średni 10 s, 60 s, od startu /
  min / max / odch. std. / P95 / P99), jitter próbkowania, histogram, pominięte cykle i błędy, zerwania, dostępność, przepustowość,
  ping ICMP z procentem utraty pakietów, test portu TCP, wykresy w czasie, raport do schowka / pliku.
* Metody połączenia (menu Ustawienia): S7comm (snap7), OPC UA (asyncua), Web API (JSON-RPC, eksperymentalne), Modbus TCP.
  „Automatycznie” rozpoznaje przy każdym Start kolejno S7comm → OPC UA → Web API → Modbus i używa pierwszej działającej metody
  zgodnej ze źródłami sygnałów (I/Q/M/DB, OPC, WEB, MBH/MBI/MBC/MBD). Kreator połączenia pokazuje wynik każdego testu, sugerowaną metodę
  i zalecenia, dane sterownika (model, MLFB, firmware, numer seryjny, stan, ochrona) oraz czas sterownika z różnicą do czasu komputera.
  Ustawienia → Metoda połączenia: wybór ręczny, porty, login/hasło, certyfikat klienta OPC UA. Przeglądarka zmiennych OPC UA: „Z OPC UA…”
  w oknie Sygnały. Ograniczenia i blokady: Ustawienia → Wymagania, ograniczenia i blokady… (oraz Pomoc F1).
* Pomoc (F1): opis wszystkich paneli, menu, przycisków i okna sygnałów z rysunkami (`s7trace/help/`).
* Widok → Interfejs…: kolory (okna, pola edycyjne, tabele, menu, wykres…) i czcionka, z podglądem na żywo.
  Profil kolorów: Ciemny / Jasny / Systemowy (podąża za trybem aplikacji w Windows, także na żywo) / Własny
  (ustawia się sam po ręcznej zmianie koloru; też w Widok → Profil kolorów).
  Konfiguracje interfejsu: „Zapisz jako…” tworzy plik .json (każdy parametr w osobnej linii) w
  `%APPDATA%\S7Trace\interfejs\`; zapisane wybierasz z listy w oknie Interfejs albo z Widok → Zapisane konfiguracje
  interfejsu (tuż pod „Interfejs…”); „Wczytaj z pliku…” otwiera plik z dowolnego miejsca.
* Pole „Sterownik” pod blokiem Połączenie pokazuje dane z ostatniego połączenia (rodzina, model, firmware, nazwa stacji, nazwa modułu);
  jest puste do pierwszego połączenia i czyszczone po zmianie adresu IP. Kliknięcie otwiera pełne informacje („Sterownik i czas”).
* Pole IP przyjmuje tylko IPv4 (opcjonalnie `:port`), błędny adres jest podświetlony i blokuje Start.
* Pamiętane: karty, sygnały, trigger, widok, motyw, rozmiar i położenie okna, kolumny okna sygnałów
  (autozapis co 20 s i przy zamknięciu).
* Konfiguracja zapisywana przy zamknięciu w `%APPDATA%\S7Trace\config.json` (zakładki, sygnały, trigger).
