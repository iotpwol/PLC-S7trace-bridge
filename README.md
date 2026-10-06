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

## Tryb Web (serwer dla wielu użytkowników)

`Web-Serwer.bat` (albo `python -m s7trace.web --config <plik.json> --host 0.0.0.0 --tls`) uruchamia centralny serwer:
połączenia ze sterownikami działają na nim, a użytkownicy logują się przeglądarką (konta programu albo Windows / AD, role
podgląd / operator / administrator). Strona pokazuje, kto jest zalogowany (konto, komputer), jakie są połączenia i z jakimi
sterownikami (IP, nazwa stacji, moduł), wykres na żywo oraz Start/Stop. Szczegóły: [WEB.md](WEB.md).

## Sterownik

| CPU | Rack / Slot | Wymagania |
|---|---|---|
| S7-300 / 400 | 0 / 2 | — |
| S7-1200 / 1500 | 0 / 1 | CPU: „Permit access with PUT/GET”, DB bez „Optimized block access” |

IP można podać z portem (`host:port`). Adresowanie jest bezwzględne: `I`, `Q`, `M`, `DB` + bajt/bit.
Typy: BOOL, BYTE, SINT, USINT, WORD, INT, UINT, DWORD, DINT, UDINT, REAL, LREAL.

## Funkcje

* **Znaczniki na wykresie i wyszukiwarka danych** (desktop i tryb Web): znacznik = punkt albo zakres czasu z tytułem, opisem, uwagami, kolorem,
  priorytetem, stylem linii, przezroczystością obszaru, autorem i datami założenia / modyfikacji; dla wszystkich albo wybranych przebiegów; grupy
  znaczników, dymek przy najechaniu, przeciąganie myszą, ukrywanie nazwy na wykresie. Zmiany są robocze do polecenia **Zapisz znaczniki** (okno
  z wykazem nowych / zmienionych / usuwanych; przypomnienie przy zamykaniu wykresu). Znaczniki trzymane są w osobnej bazie SQLite, wyszukiwarka
  (menu **Znaczniki**, rząd przycisków „Znaczniki:” pod wykresem, Ctrl+F) znajduje sygnały po wartościach i godzinach w bieżących danych albo w nagraniu z bazy. Szczegóły: [BAZY_DANYCH.md](BAZY_DANYCH.md), rozdz. 13 (pełny opis: rodzaje, parametry, obsługa, zapis, wyszukiwarka) i [WEB.md](WEB.md), rozdz. 19.
* **Znaczniki REC** (desktop i Web): wykres sam rysuje numerowane linie **Start REC (n)** / **Stop REC (n)** (kolor, grubość i rodzaj linii w *Znaczniki → Wygląd znaczników…*, można wyłączyć);
  prawy przycisk na wykresie → **Manual Start REC / Manual Stop REC** zaznacza obszar już zebranych danych, który **Zapis Manual REC** (albo okno *Zapisz znaczniki*) zapisuje jako osobne nagranie;
  **Przesuń Start REC** (pulsujący „duch”) zmienia początek nagrania w bazie: dopisuje brakujące dane z bufora albo usuwa starsze (SQLite, InfluxDB, TimescaleDB; nie CSV).
* **Start po Stop kontynuuje wykres z przerwą** (zamiast go czyścić); nowy przycisk **Reset** (po lewej od REC) czyści wykres, a przytrzymany 4 s włącza **Auto-Reset** (każdy Start czyści wykres) – desktop i Web.
* **Znacznik wie, do którego nagrania należy** (kolumna „Zapis” w liście znaczników, filtr, Web też). Znaczniki istniejące tylko dla bufora wykresu program proponuje usunąć, gdy bufor znika (zamknięcie karty / programu, Start, wczytanie nagrania); przy trwałym usunięciu nagrania pyta o jego znaczniki.
* Zakładki = niezależne połączenia (dół okna, `+` dodaje). Kropka przy nazwie: zielona = praca, szara = stop.
* Wykres przesuwa się w czasie rzeczywistym: najnowsze próbki po prawej, szerokość = „Okno czasu” (wpisana w sekundach albo wybrana z listy: 5 s … 24 godz.).
  Przeciągnięcie / zoom myszą wstrzymuje widok (zbieranie trwa); „Wznów” wraca do trybu na żywo.
  Pasek pod wykresem = cała nagrana historia, żółty obszar = widoczne okno (można go przesuwać).
* Tryby komunikacji: bloki grupowane (scala sąsiednie adresy), pojedyncze, multi-read (1 zapytanie).
* Odczyt PLC działa w osobnym procesie, więc rysowanie wykresu nie opóźnia cykli.
  Na dole lewego panelu dwie zakładki: **System** (godzina systemowa, obciążenie CPU, opóźnienie GUI) i **Sieć** (opóźnienie odczytu średnia z 50 / ostatnie, liczba i % pominiętych cykli, ping); pasek statusu pokazuje status REC i komunikaty.
  Pola lewego panelu (Połączenie, Sterownik, Zakres okna wykresu, Trigger, Nagrywanie REC) przeciągasz myszą **za nazwę pola** w górę / w dół; kolejność, zwinięte pola, ukryte elementy i aktywna zakładka dolna zapisują się w konfiguracji aplikacji i w pliku konfiguracji interfejsu (Widok → Interfejs, klucze `panel_*`). Prawy przycisk na nazwie elementu (np. „IP”) ukrywa go; prawy przycisk na nazwie pola (np. „Połączenie”) otwiera menu pola: zwiń / rozwiń, lista elementów z haczykami (ukryj / odkryj), „Pokaż wszystkie elementy”. Na dole pola „Sterownik” przycisk **Pobierz dane sterownika** czyta tylko dane i zegar PLC bez uruchamiania odczytu; zakładka „System” pokazuje też obciążenie CPU przez samą aplikację (z procesami odczytu). Obciążenie CPU jest liczone jak w Menedżerze zadań (licznik „Processor Utility” – uwzględnia częstotliwość procesora, więc bywa wyższe niż sam czas zajętości; tam, gdzie licznika brak, używany jest czas zajętości); „w tym ta aplikacja” to udział programu w tej samej skali.
* Pole „Sterownik” pokazuje dane **wiersz po wierszu**: Rodzina, Model, Firmware, Nazwa stacji, Nazwa modułu, **Czas PLC** (data i godzina; gdy zegara nie udało się odczytać: „nie odczytano”, powód w podpowiedzi) – a po odkryciu także Numer katalogowy (MLFB), Numer seryjny, Producent / copyright, Stan CPU i Długość PDU. Każdy wiersz (także w zakładkach „System” i „Sieć” i sam przycisk „Pobierz dane sterownika”) ukrywa się prawym przyciskiem myszy na nazwie, a odkrywa z menu prawego przycisku na nazwie pola; ukryty przycisk „Pobierz dane sterownika” jest dalej w tym menu. Zakładka „System” zaczyna się od **systemu operacyjnego** (np. Windows Server 2019). Zegar PLC jest czytany własnym rozbiorem odpowiedzi S7 (a nie biblioteką, która przy błędzie podstawiała zegar komputera); bajt „wieku” (stałe 19 w niektórych sterownikach) jest ignorowany – rok 26 to 2026, nie 1926. Różnice zegarów są podawane jako dni i godziny (np. −1 d 02:00:00), nie jako ogromna liczba sekund. „Pobierz dane sterownika” przy odmowie sesji S7 (np. WinError 10054) próbuje kolejnych par rack/slot (0/2, 0/1, 0/0, 1/2, 0/3), a pasującą wpisuje do ustawień; gdy żadna nie pasuje, pokazuje polskie wyjaśnienie (rack/slot, PUT/GET, optimized block access, zasoby połączeń, poziom ochrony).
* Zasada w całym programie i w Web: **dane w zdaniach** (liczby z jednostkami: 19.8%, 25 ms, ≥ 45 ms; adres IP w oknie kreatora; czas) są **pogrubione**, reszta zdania normalna (`core/richtext.py`, w Web `boldNums`). Wartości w polach edycji (także godzina offsetu osi) są pogrubione.
* **Jeden standard tabel** (wzorzec: okno „Sygnały do śledzenia”): szerokość każdej kolumny zmieniasz przeciągając granicę nagłówka (także w „Przeglądzie nagrań”, liście programów, wynikach kreatora, diagnostyce), ostatnia kolumna wypełnia resztę, początkowa szerokość = zawartość, wiersze są naprzemiennie jaśniejsze / ciemniejsze, linie siatki i nagłówków cienkie, tekst w komórce ma stałe wcięcie. Kolory tabel ustawisz w Widok → Interfejs: kolor tła i czcionki nagłówka, tła i czcionki wierszy nieparzystych i parzystych oraz kolor ramki tabeli (zapisują się w konfiguracji interfejsu i jej pliku: `header_bg`, `header_text`, `row_odd_bg`, `row_odd_text`, `row_even_bg`, `row_even_text`, `table_border`). W Web te same zasady dla tabel list (przeciąganie granic nagłówka, paski naprzemienne), a te same siedem kolorów jest w przycisku „Interfejs” w nagłówku strony (zapis na koncie).
* **Pasek statusu**: prawy przycisk myszy na pasku otwiera menu – maksymalna liczba wierszy, kolor tła, kolor tekstu, justowanie tekstu (do lewej / do prawej). Te same ustawienia (z justowaniem) są w Widok → Interfejs i zapisują się w pliku konfiguracji interfejsu (`status_lines`, `status_bg`, `status_text`, `status_align`). W Web ten sam pasek (stan połączenia nad wykresem) ma to samo menu; ustawienia są zapisane na koncie.
* Przycisk „?” (tryb pomocy) **świeci na pomarańczowo**, gdy tryb jest włączony; kolory tła i tekstu zmienisz w Widok → Interfejs („Przycisk „?” …”, zapisują się w pliku konfiguracji interfejsu). Pozycja menu Pomoc → „Tryb pomocy” ma „ptaszek” przy włączonym trybie.
* Nagranie ma pola **Tytuł, Opis, Uwagi, Tagi** (okno nagrania, „Przegląd nagrań”, Web); dymek znacznika podpisuje opis („Opis:”).
* Utrata połączenia: automatyczne ponawianie co 2 s, w danych zostaje przerwa (NaN).
* Trigger: `==`, `>`, `<`, `between`, `rising edge`, `falling edge`, histereza, pretrigger.
  Akcje: Pauza, Zapis CSV, Pauza + zapis CSV. Porównywana jest wartość surowa (bez gain / offsetu Y).
  Dla sygnałów BOOL użyj progu A = 0,5 przy zboczach.
  Nazwa pliku (domyślnie `snapshot_{confname}_{ip}_{tab}_{date}_{time}.csv`): `{confname}`, `{ip}`, `{tab}`, `{date}`, `{time}`.
  Ścieżka względna (domyślnie `snapshots`, `rec`) oznacza folder w `Dokumenty\S7Trace` bieżącego użytkownika Windows,
  więc przy wielu kontach każdy ma własne pliki.
* **Legenda wykresu:** po najechaniu na pozycję pokazuje dymek z opisem sygnału (jak w oknie „Sygnały…”); prawy przycisk → „Legenda pokazuje” przełącza napisy między nazwą a adresem / węzłem OPC (osobno dla każdej karty; w Web: lista w edycji połączenia i w pasku wykresu).
* **Tryb pomocy „?”:** przycisk obok „X” każdego okna (w oknie głównym w pasku menu, Shift+F1) – po włączeniu najechanie na element (przycisk, pole, nazwa kolumny / wiersza, tytuł pola) pokazuje dymek: co to, do czego, jak ustawić, zakres. Teksty: `s7trace/core/help_texts.py` (wspólne dla programu i Web, `/api/help`).
* **Nazwy sygnałów na wykresie:** Widok → „Nazwy sygnałów na wykresie” (albo prawy przycisk na legendzie, albo Ustawienia → Interfejs) przełącza **Legendę** (ramka z listą) na **Opisy przy sygnałach** – nazwa w półprzezroczystej ramce w połowie pasma każdego sygnału, po prawej stronie osi pionowej; prawy przycisk na opisie przełącza nazwę ↔ adres / węzeł OPC. Styl zapisuje się w pliku konfiguracji interfejsu, w Web – w ustawieniach konta (lista „Nazwy sygnałów” w pasku wykresu).
* **Zwijane pola** panelu bocznego (Połączenie, Sterownik, Zakres okna wykresu, Trigger, Nagrywanie REC; w Web – w edycji połączenia): klik w tytuł, trójkąt obraca się o 90°. Podpowiedzi nad kolorowymi polami mają zawsze czytelny kontrast. Menu Pomoc → „O programie”: autor, wersja, data (`s7trace/version.py`).
* REC – pełny opis baz danych, trybów, czasów i buforów: [BAZY_DANYCH.md](BAZY_DANYCH.md). Nagrania w bazach mają tytuł, uwagi, tagi, właściciela,
  komputer i **dane sterownika PLC** (model, numer katalogowy, firmware, numer seryjny, nazwa stacji…, żeby wiązać dane z właściwym sterownikiem; w CSV – linia `# device:`); **Plik → Przegląd nagrań…** pokazuje je z sortowaniem, wyszukiwaniem i filtrem użytkownika, pozwala edytować opis, usuwać do kosza
  (przywracanie, czas przechowywania w ustawieniach), usuwać trwale, eksportować do CSV i wczytywać na wykres. Kiedy program pyta o nazwę nagrania
  (na początku / w trakcie / na końcu / wcale) ustawia się w ustawieniach bazy, zakładka „Nagrania i użytkownicy”.
* REC: cel zapisu (panel „Nagrywanie REC”): plik CSV, SQLite, InfluxDB 1.x / 2.x (HTTP, line protocol) lub TimescaleDB
  (PostgreSQL, `psycopg`); próbki: **tylko zmiany stanu** (domyślnie) albo każda próbka. Zapis do bazy idzie w osobnym wątku
  (paczki, ponawianie, ograniczona kolejka). Odczyt: Plik → Import z bazy → wykres… (lista nagrań + zakres czasu).
  SQLite: tabele `sessions` / `samples` (jeden plik, wiele nagrań); Influx: pomiar `<nazwa>` + `<nazwa>_sessions`; Timescale: hypertable
  `<tabela>` + `<tabela>_sessions`, kompresja po N dniach (domyślnie 7, w opcjach; 0 = bez). Influx nie ma wartości NaN, więc niedostępność sygnału zapisywana jest
  w osobnym polu `<sygnał>__ok` (0/1, tylko przy zmianie) i odczyt odtwarza z niej przerwę w krzywej.
  **Ustawienia bazy** (przycisk „...” obok „Zapis do” albo Ustawienia → „Zapis nagrań w bazach danych…”) mają zakładkę
  „Czasy i bufory” z opisem każdego parametru czasowego (wartości domyślne w nawiasach):
  pełny stan co N min w trybie zmian (10; to „klatka kluczowa” – punkt startu dla odczytu zakresu i sygnał, że zapis żyje; 0 = wyłączony),
  wysyłka paczek co (0,5 s), najdłuższa przerwa między ponowieniami (15 s), limit testu połączenia po naciśnięciu REC (3 s),
  limit odpowiedzi serwera (15 s), dosyłanie po Stop (10 s), kolejka w pamięci (300 000 wpisów),
  bufor na dysku (500 MB; 0 = wyłączony), SQLite: nowy plik po przekroczeniu rozmiaru (0 = nigdy) lub każdego dnia,
  odczyt: maks. punktów na sygnał (200 000).
  Po naciśnięciu REC program sprawdza serwer w tle: gdy nie odpowiada, od razu pokazuje przyczynę (przycisk „Przerwij REC”),
  a nagrywanie trwa – dane czekają w buforze na dysku (`Dokumenty\S7Trace\spool`, z komunikatem „na dysku N” w pasku statusu)
  i są dosyłane po powrocie serwera, także po ponownym uruchomieniu programu.
  Odczyt bardzo długich nagrań zmniejsza liczbę punktów (min/max z każdego przedziału, szpilki nie znikają); okno importu ma
  też „Zapisz jako CSV…” (wybrane nagranie lub zakres, wszystkie wiersze) i widzi pliki SQLite rotowane po dacie / rozmiarze.
  TimescaleDB: sterownik `psycopg`; gdy się nie załaduje (np. Windows Server 2016), program używa czystego Pythona `pg8000`
  (build-portable.ps1 sprawdza, który działa w paczce).
* REC (CSV): ciągły zapis; folder (domyślnie `rec`) i nazwa pliku (domyślnie
  `REC_{confname}_{ip}_{tab}_{date}_{time}.csv`) ustawia się w panelu po lewej pod blokiem Trigger.
* Widok → Punkty: znaczniki próbek. Znaczniki → „Znacznik poziomu sygnału”: kliknięcie na wykresie stawia poziomy kursor (max 2), odczyt wartości i ΔY. Oś czasu (panel „Zakres okna wykresu”): sekundy od startu / czas aplikacji / czas PLC jako `HH:MM:SS.mmm` (zakres opisu zależy od powiększenia). „Offset osi” to trzy elementy obok siebie: znak, **data** (pełne doby, 0–3650) i **godzina** `HH:MM:SS.mmm` – do zgrania zegarów albo gdy w sterowniku nie ustawiono daty; prawy przycisk na polu: „Wyrównaj czas PLC do czasu komputera”. Pole „Sterownik” pokazuje w szóstej linii **Czas PLC** (data i godzina; czas czytany raz przy połączeniu, dalej liczony z zegara komputera i odświeżany co sekundę); różnicę zegarów o dobę lub więcej program zgłasza w pasku statusu. Znaczniki są domyślnie zablokowane (przeciągnięcie przesuwa wykres) – przeciągać można je po zaznaczeniu „Zmień pozycję znacznika” w ich menu.
* CSV: menu Plik → `Eksport okna → CSV`, `Import CSV → wykres` (CSV zapisuje definicje sygnałów w komentarzach `# signal:`). Wczytanie nagrania z bazy do karty ustawia też adres, rack/slot, metodę i dane sterownika zapisane w nagraniu.
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
* Zwijanie paneli: panel ustawień po lewej chowa się do lewej, wykres przeglądowy na dole chowa się w dół — dwukrotnym kliknięciem
  cienkiej belki rozdzielającej (belka pojawia się po najechaniu kursorem; jej kolor i „zawsze widoczna” — Widok → Interfejs;
  stan zwinięcia jest wspólny dla kart i zapamiętany). Panel ustawień nie jest węższy niż jego zawartość.
* Obciążenie procesora (Ustawienia → Renderowanie wykresu): odświeżanie wykresu (Hz), pomijanie niewidocznych kart, maks. punktów krzywej,
  limit i rozmiar „Punktów”, odświeżanie i rozdzielczość wykresu przeglądowego, wygładzanie linii — wszystko regulowane, domyślnie oszczędnie.
* Pasek statusu: tekst, który się nie mieści, przeciągasz myszą w lewo / prawo; maks. liczbę linii, kolor tła i tekstu ustawisz w Widok → Interfejs.
* Okna ustawień mają u góry pasek z nazwą funkcji i opisem; gdy nie mieszczą się na ekranie, zmniejszają się i mają paski przewijania.
* Przebieg z bazy (Plik → Przegląd nagrań) otwiera się w pustej karcie od razu, w karcie z danymi program pyta (nowa / bieżąca karta),
  przy aktywnym połączeniu zawsze w nowej karcie; karta przyjmuje tytuł przebiegu, a dymek nad kartą pokazuje dane przebiegu / połączenia i bazy.
* Prawy przycisk na legendzie: Sygnały…, położenie legendy (ta karta), Ukryj legendę.
* Ikona programu i nazwa „S7Trace” na pasku zadań Windows (własny identyfikator aplikacji zamiast „Python”).
* Aktywne sesje programu (Ustawienia → Aktywne sesje programu…): kto ma program otwarty na tym komputerze i które karty skanują
  sterowniki. Każde okno programu zapisuje co 2 s mały plik w `%ProgramData%\S7Trace\sessions` (albo `C:\Users\Public\S7Trace\sessions`);
  nieodświeżany wpis (zamknięty / zawieszony program) znika po ok. 10 s. Start na już skanowany sterownik tylko ostrzega. Zasięg: ten komputer.
* Diagnostyka połączenia (przycisk „Diagnostyka…”, menu Diagnostyka → Diagnostyka połączenia…, Ctrl+D): ocena łącza, czas odczytu (chwilowy / średni 10 s, 60 s, od startu /
  min / max / odch. std. / P95 / P99), jitter próbkowania, histogram, pominięte cykle i błędy, zerwania, dostępność, przepustowość,
  ping ICMP z procentem utraty pakietów, test portu TCP, wykresy w czasie, raport do schowka / pliku.
* Metody połączenia (menu Ustawienia): S7comm (snap7), OPC UA (asyncua), Web API (JSON-RPC, eksperymentalne), Modbus TCP.
  „Automatycznie” rozpoznaje przy każdym Start kolejno S7comm → OPC UA → Web API → Modbus i używa pierwszej działającej metody
  zgodnej ze źródłami sygnałów (I/Q/M/DB, OPC, WEB, MBH/MBI/MBC/MBD). Kreator połączenia pokazuje wynik każdego testu, sugerowaną metodę
  i zalecenia, dane sterownika (model, MLFB, firmware, numer seryjny, stan, ochrona) oraz czas sterownika z różnicą do czasu komputera.
  Ustawienia → Metoda połączenia: wybór ręczny, porty, login/hasło, certyfikat klienta OPC UA. Przeglądarka zmiennych OPC UA: „Z OPC UA…”
  w oknie Sygnały. Ograniczenia i blokady: Ustawienia → Wymagania, ograniczenia i blokady… (oraz Pomoc F1).
* Pomoc (F1): pełny opis programu (32 rozdziały: menu i podmenu, panele, pola, przyciski, wykres, znaczniki, tabele, bazy, diagnostyka, metody połączenia, tryb Web…) ze **zdjęciami działającego programu** – każde menu, podmenu, pole i okno ma własne zdjęcie, a opis mówi, co to jest, do czego służy, jak się zachowuje i od czego zależy. Tekst: `s7trace/ui/help_content.py`; zdjęcia (`s7trace/help/img`) powstają automatycznie: `python tools/make_help_images.py` uruchamia program na symulatorze sterownika i fotografuje jego elementy – po zmianie wyglądu programu wystarczy uruchomić skrypt ponownie.
* Widok → Interfejs…: kolory (okna, pola edycyjne, tabele, menu, wykres…) i czcionka, z podglądem na żywo.
  Profil kolorów: Ciemny / Jasny / Systemowy (podąża za trybem aplikacji w Windows, także na żywo) / Własny
  (ustawia się sam po ręcznej zmianie koloru; też w Widok → Profil kolorów).
  Konfiguracje interfejsu: „Zapisz jako…” tworzy plik .json (każdy parametr w osobnej linii) w
  `%APPDATA%\S7Trace\interfejs\`; zapisane wybierasz z listy w oknie Interfejs albo z Widok → Zapisane konfiguracje
  interfejsu (tuż pod „Interfejs…”); „Wczytaj z pliku…” otwiera plik z dowolnego miejsca.
* Pole „Sterownik” pod blokiem Połączenie pokazuje dane z ostatniego połączenia (rodzina, model, firmware, nazwa stacji, nazwa modułu);
  jest puste do pierwszego połączenia i czyszczone po zmianie adresu IP. Kliknięcie otwiera pełne informacje („Sterownik i czas”).
* Pole IP to cztery niezależne pola liczbowe z nieruchomymi kropkami (`10 . 12 . 91 . 1`; pola mogą być puste, Backspace/Delete
  kasują tylko cyfry, zaznaczenie + Delete/Spacja czyści adres). Tylko IPv4 (opcjonalnie `:port`), niepełny adres jest podświetlony
  i blokuje Start. Lista rozwijana pokazuje historię adresów, z którymi się połączono (najnowsze u góry; osobna dla każdego
  użytkownika Windows, `%APPDATA%\S7Trace\ip_history.json`).
* Pamiętane: karty, sygnały, trigger, widok, motyw, rozmiar i położenie okna, kolumny okna sygnałów
  (autozapis co 20 s i przy zamknięciu).
* Konfiguracja zapisywana przy zamknięciu w `%APPDATA%\S7Trace\config.json` (zakładki, sygnały, trigger).
