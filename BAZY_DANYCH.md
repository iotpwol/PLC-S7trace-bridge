# S7Trace – zapis i odczyt przebiegów w bazach danych

Ten dokument opisuje, **jak program zapisuje i odczytuje nagrania (REC)**: w jakich formatach i bazach, jakie one mają
możliwości, zalety i wady, jakie funkcje wprowadzono oraz **wszystkie parametry czasowe i buforowe** z wartościami
domyślnymi. Kod: `s7trace/core/store.py` (bez Qt), okna: `s7trace/ui/store_dialog.py`, panel REC: `s7trace/ui/trace_tab.py`.

Spis treści: 1. Jak zapisywane są dane · 2. Dostępne cele zapisu i ich porównanie · 3. Tryb próbek (zmiany / każda) ·
4. Szczegóły każdej bazy · 5. Parametry czasowe i buforowe · 6. Niezawodność (test, ponawianie, bufor na dysku) ·
7. Odczyt i import · 8. Rotacja plików SQLite · 9. Eksport do CSV · 10. Menu i okna · 11. Czego nie sprawdzono · 12. Mapa kodu i testów · 13. Znaczniki i wyszukiwarka danych

---

## 1. Jak zapisywane są dane

### 1.1. Model: nagrania (sesje) i zdarzenia

Każde naciśnięcie **REC** (przy działającym zbieraniu) tworzy **nagranie** (w kodzie: *sesję*) z unikalnym identyfikatorem.
Opis nagrania (metadane) zawiera: **tytuł, opis, uwagi i tagi** (nadawane przez użytkownika, p. 7.4; „opis” = pole `description`, w starszych nagraniach puste), **właściciela** (konto Windows) i **komputer**, z którego powstało, nazwę/kartę, adres IP, nazwę konfiguracji (`{confname}`), czas początku i końca, tryb próbek, interwał pełnego stanu, znacznik kosza oraz **listę sygnałów** (nazwa, typ, adres, kolor itd. – pełna definicja, żeby przy odczycie odtworzyć wykres).

Same dane to **zdarzenia** `(czas, numer sygnału, wartość)`:

* czas – mikrosekundy od epoki (UTC), liczone z czasu początku nagrania + czas próbki,
* numer sygnału – indeks na liście sygnałów nagrania (nazwy nie są powtarzane w każdym wierszu),
* wartość – liczba zmiennoprzecinkowa (BOOL = 0/1); brak wartości (sygnał chwilowo nieczytelny) = `NaN`/`NULL`.

Dzięki temu ten sam model działa we wszystkich bazach (tabela w SQL / punkt w InfluxDB), a odczyt umie z niego odbudować
macierz „czas × sygnały” i narysować wykres.

### 1.2. Droga danych

```
sterownik → proces akwizycji → bufor wykresu → rejestrator REC
                                                 ├─ CsvRecorder  (plik CSV, zapis ciągły)
                                                 └─ DbRecorder   (osobny wątek: filtr zmian → kolejka → paczki → baza)
```

`DbRecorder` ma ten sam interfejs co `CsvRecorder`, ale pracuje we **własnym wątku**: wykres i akwizycja nigdy nie czekają
na bazę. Próbki trafiają do kolejki w pamięci, wątek wysyła je paczkami (do 20 000 wierszy), a przy zaniku serwera ponawia
wysyłkę i – jeśli włączono – odkłada dane na dysk (p. 6).

### 1.3. Gdzie ustawia się cel zapisu

W panelu **„Nagrywanie REC”** (lewy panel karty): lista **„Zapis do:”** (Plik CSV, SQLite, InfluxDB 1.x / 2.x,
TimescaleDB), lista **„Próbki:”** (domyślnie *Tylko zmiany stanu*) i przycisk **„...”** (ustawienia bazy). Wybór jest
zapamiętywany w konfiguracji **każdej karty osobno** (`TabConfig.store`).

### 1.4. Dane sterownika w nagraniu

Do opisu **każdego nagrania w każdej bazie** (SQLite, InfluxDB, TimescaleDB) zapisywane są też **dane sterownika PLC**, z którego pochodzą dane – żeby
nagranie dało się powiązać z właściwym sterownikiem (np. gdy kilka linii ma ten sam adres albo sterownik został wymieniony): adres, sposób połączenia
(rack / slot) oraz tabela „Informacje o sterowniku” – rodzina, model CPU, numer katalogowy (MLFB), wersja firmware, numer seryjny, nazwa stacji, nazwa modułu,
producent / copyright, stan i ochrona CPU, długość PDU (przy OPC UA / Web API także produkt i wersja serwera). W SQLite i TimescaleDB to kolumna `device`
(JSON, tekst), w InfluxDB pole `device` w pomiarze `<nazwa>_sessions`; starsze pliki SQLite i tabele TimescaleDB dostają kolumnę przy pierwszym otwarciu,
a nagrania bez danych (powstałe w starszej wersji, albo gdy sterownik jeszcze nie odpowiedział) mają puste `device`.
Dane są zapisywane przy naciśnięciu REC, a po ponownym połączeniu ze sterownikiem (nowszy odczyt) – aktualizowane w opisie nagrania. W plikach CSV z REC dane są
w komentarzu `# device: {json}` na początku pliku (program czyta CSV, pomijając tę linię).
Przegląd: w oknie „Przegląd nagrań” kolumny **Sterownik** (model + nazwa stacji) i **Nr seryjny**, przycisk **Sterownik…** (cała tabela) i wyszukiwanie po tych
danych; w trybie Web ta sama kolumna na liście nagrań i opis sterownika nad wykresem (patrz `WEB.md`).

---

## 2. Dostępne cele zapisu i porównanie

| Cel | Gdzie leżą dane | Serwer? | Biblioteka | Odczyt do wykresu |
|---|---|---|---|---|
| **Plik CSV** | plik `.csv` w folderze `rec` (`Dokumenty\S7Trace\rec`) | nie | wbudowana | Plik → Import CSV |
| **SQLite** | jeden plik `.db` (domyślnie `Dokumenty\S7Trace\s7trace.db`) | nie | wbudowana (`sqlite3`) | Plik → Import z bazy |
| **InfluxDB 1.x** | baza (`database`) na serwerze, HTTP `/write` | tak | wbudowana (`urllib`) | Import z bazy |
| **InfluxDB 2.x** | bucket w organizacji, HTTP `/api/v2/write`, token | tak | wbudowana | Import z bazy (Flux) |
| **TimescaleDB** | tabele PostgreSQL (hypertable) | tak | `psycopg` albo `pg8000` | Import z bazy |

### 2.1. Zalety i wady

**Plik CSV**
* (+) Najprostszy, czytelny w Excelu i każdym narzędziu, nie wymaga niczego instalować, zachowuje definicje sygnałów w
  komentarzach `# signal:` (powrót na wykres przez Import CSV).
* (−) Tekst = duże pliki przy godzinach/dniach nagrania, brak zapytań o zakres czasu (cały plik trzeba wczytać), brak
  mechanizmu dosyłania przy awarii, brak wielu nagrań w jednym pliku. Wydajny dopiero w trybie „tylko zmiany”.

**SQLite**
* (+) Jeden plik, zero instalacji i konfiguracji, transakcyjny (odporny na awarię zasilania – tryb WAL), szybki zapis i
  odczyt zakresu czasu (indeks), wiele nagrań w jednym pliku, łatwe kopiowanie i archiwizacja, rotacja plików.
* (−) Brak dostępu sieciowego (plik lokalny; przez udział sieciowy SQLite jest zawodny), jeden zapisujący proces naraz
  na plik, brak wbudowanej kompresji, bardzo duże pliki (dziesiątki GB) trudniej obsługiwać – stąd rotacja.

**InfluxDB 1.x / 2.x**
* (+) Baza szeregów czasowych zaprojektowana do ciągłego zapisu, kompresja danych, polityki retencji, gotowe wykresy
  (Grafana, Chronograf), dostęp sieciowy z wielu komputerów, wiele programów może zapisywać do jednej bazy.
* (−) Wymaga serwera i administracji (token/hasło, retencja), **nie ma wartości NaN** (rozwiązanie: pole `__ok`, p. 4.3),
  różne API w każdej wersji (v1 InfluxQL, v2 Flux – program obsługuje obie), zapytania odczytu są
  wolniejsze niż w SQLite przy dużych zakresach, **nie sprawdzono na prawdziwym serwerze** (p. 11).

**TimescaleDB (PostgreSQL)**
* (+) Pełny SQL, hypertable (automatyczne dzielenie na fragmenty czasu), kompresja kolumnowa starszych danych, dostęp
  sieciowy, dojrzałe narzędzia administracji i kopii zapasowych, działa też na zwykłym PostgreSQL (bez hypertable).
* (−) Wymaga serwera PostgreSQL z rozszerzeniem, administracji i uprawnień (`CREATE TABLE`, opcjonalnie `CREATE EXTENSION`),
  najcięższe w instalacji; sterownik `psycopg` zawiera DLL `libpq` (na Windows Server 2016 mógłby się nie załadować –
  wtedy program używa czystego Pythona `pg8000`, p. 4.4).

**Parquet** – świadomie odłożony (decyzja użytkownika); nie ma go w programie.

### 2.2. Którą bazę wybrać (wskazówka)

* Jedno stanowisko, godziny–dni, bez serwera → **SQLite** (z rotacją dzienną).
* Wiele stanowisk, wspólny podgląd i Grafana → **InfluxDB** (2.x) lub **TimescaleDB**.
* Szybka wymiana pliku z innymi narzędziami, krótkie nagrania → **CSV** (tryb „zmiany”).

---

## 3. Tryb próbek: tylko zmiany stanu albo każda próbka

Lista **„Próbki:”** dotyczy wszystkich celów (także CSV). Domyślnie: **Tylko zmiany stanu**.

### 3.1. „Tylko zmiany stanu” (domyślnie)

* Zapisywana jest wartość sygnału **tylko wtedy, gdy różni się od poprzedniej**; pierwsza wartość każdego sygnału jest
  zapisywana zawsze. Porównanie robi `ChangeFilter` (NaN równa się NaN – brak zapisu, dopóki brak trwa).
* Przy zapisie godzin i dni daje to **kilkadziesiąt razy mniej danych** (sygnały stałe, np. stan zaworu, zapisują się raz).
* Odczyt **odtwarza krzywą schodkową**: `events_to_matrix` przenosi ostatnią znaną wartość każdego sygnału do przodu aż do
  jego następnej zmiany – wykres wygląda tak samo jak z zapisu każdej próbki (nie widać natomiast szumu między zmianami,
  których nie zapisano, bo ich nie było).
* **Pełny stan co N minut** (*klatka kluczowa*, domyślnie 10 min): co N minut zapisywane są wartości **wszystkich** sygnałów,
  nawet niezmienione. Po co: (1) odczyt zakresu godzin zaczyna się od pełnego stanu, (2) widać, że zapis **żył** w czasie, gdy
  nic się nie zmieniało (a nie że komputer padł), (3) ogranicza skutki ewentualnej utraty pojedynczych wpisów. 0 = wyłączone.

### 3.2. „Każda próbka”

* Każda próbka każdego sygnału jest zapisywana, bez filtra i bez klatek kluczowych.
* Zalety: pełny, surowy zapis (np. do analizy szumu, dokładnej częstotliwości próbkowania). Wady: wielokrotnie więcej
  danych – przy godzinach i dniach baza szybko rośnie.

---

## 4. Szczegóły każdej bazy

### 4.1. Plik CSV

* Nagłówek: `# s7trace v1`, po jednym wierszu `# signal: {json}` na sygnał, potem kolumny `time_s`, `timestamp` i sygnały.
* Domyślna nazwa: `REC_{confname}_{ip}_{tab}_{date}_{time}.csv` w folderze `rec` (względna ścieżka = `Dokumenty\S7Trace`
  bieżącego użytkownika Windows). Pola folder/nazwa dotyczą **tylko CSV** (przy bazach są wyszarzone).
* W trybie „zmiany” wiersz powstaje tylko, gdy zmieniła się choć jedna wartość (pierwszy wiersz zawsze).
* Dodanie zmiennej w trakcie zapisu zaczyna nowy plik (z dodatkową kolumną).

### 4.2. SQLite

* Dwie tabele: `sessions` (opis nagrania: id, name, start_us, end_us, ip, tab, conf, mode, signals, fields) i
  `samples (session, sig, ts_us, value)` z kluczem głównym `(session, sig, ts_us)` – `WITHOUT ROWID`, więc klucz jest
  jednocześnie indeksem (szybki odczyt zakresu czasu pojedynczego sygnału).
* Tryb WAL + `synchronous=NORMAL`: szybki zapis, odporność na przerwanie zasilania.
* Ścieżka względna = folder `Dokumenty\S7Trace` bieżącego użytkownika. Jeden plik może mieć wiele nagrań.
* Błędna ścieżka jest zgłaszana **od razu** przy REC (plik lokalny otwierany synchronicznie).
* Rotacja pliku: p. 8.

### 4.3. InfluxDB (1.x, 2.x)

* Zapis: HTTP, **line protocol**, znaczniki czasu w nanosekundach, paczki do 5000 linii.
* Pomiar (*measurement*) o nazwie z ustawień (domyślnie `s7trace`): tag `session`, pola = nazwy sygnałów (powtórzone nazwy
  dostają sufiks `_2`, `_3`…). Opis nagrania: osobny pomiar `<nazwa>_sessions`.
* Różnice wersji:
  * **1.x** – `/write` + `/query` (InfluxQL), baza (`database`), użytkownik i hasło (Basic). Baza jest tworzona, jeśli konto ma
    uprawnienia.
  * **2.x** – `/api/v2/write` + `/api/v2/query` (Flux), organizacja + bucket + token (`Authorization: Token …`).
  * **3.x – nieobsługiwana.** InfluxDB 3 (Core) nie umożliwia usuwania nagrań, a to jest wymaganie programu, więc obsługę
    usunięto. Zapisany wcześniej cel „InfluxDB 3.x” po wczytaniu konfiguracji wraca do „Plik CSV”.
* **Brak NaN w InfluxDB:** line protocol nie ma wartości „brak”. Gdy sygnał staje się nieczytelny, pole z wartością jest
  pomijane, a **dostępność zapisuje się w osobnym polu `<sygnał>__ok`** (0 = nieczytelny, 1 = znów czytelny) – **przy zmianie dostępności
  oraz w każdym pełnym stanie (klatce kluczowej)** (nie w każdej próbce). Odczyt zamienia `__ok = 0` na przerwę (NaN) w krzywej.
* **Odczyt zakresu czasu** (np. godz. 14–15) dla trybu „zmiany” wymaga stanu sprzed zakresu. Program zagląda **wstecz o dwa interwały pełnego stanu** (domyślnie 20 min), bierze najświeższą wartość każdego sygnału (z dokładnym czasem) i wstawia ją na początek zakresu. Dzięki klatkom kluczowym każdy sygnał występuje w tym oknie. Jeśli czegoś w nim brakuje (np. pełny stan był wyłączony), program używa wolniejszego zapytania „ostatnia wartość przed zakresem” (v1: `SELECT LAST(*)`, v2: Flux `last()`).

### 4.4. TimescaleDB (PostgreSQL)

* Tabele: `<tabela>` `(time timestamptz, session text, sig integer, value double precision)` oraz `<tabela>_sessions`
  (opis nagrania). Domyślna nazwa tabeli `s7_samples`; dozwolone tylko litery, cyfry i podkreślenia (ochrona przed
  wstrzyknięciem SQL).
* Tabele i indeks `(session, sig, time DESC)` tworzą się automatycznie. Jeśli rozszerzenie `timescaledb` jest dostępne:
  **hypertable** po czasie i **kompresja po N dniach** (domyślnie 7, segmentacja `session, sig`; N ustawia się w oknie bazy,
  zakładka „Czasy i bufory”, pole „Kompresja danych starszych niż”, **0 = bez kompresji**, p. 7.5). Zmiana N przy kolejnym połączeniu
  zastępuje politykę na serwerze; to, co już skompresowano, zostaje skompresowane. Na zwykłym PostgreSQL wszystko działa
  bez hypertable (błąd tych kroków jest ignorowany).
* Sterownik: `psycopg` (wersja 3, z `libpq`). Gdy się nie załaduje (np. Windows Server 2016), program używa **`pg8000`**
  (czysty Python, dołączony do paczki). Parametry połączenia: serwer, port (5432), baza, użytkownik, hasło, `sslmode`
  (`disable`/`prefer`/`require`/`verify-ca`/`verify-full`).
* Odczyt: `DISTINCT ON (sig)` dla stanu sprzed zakresu, potem zdarzenia z zakresu.

### 4.5. Hasła i tokeny

Hasła i tokeny **nie są zapisywane** w pliku konfiguracji (`%APPDATA%\S7Trace`), chyba że zaznaczysz „Zapamiętaj hasło / token
w konfiguracji” – wtedy zapisują się **jawnym tekstem** (ostrzeżenie jest w oknie). Bez zapamiętania program prosi o dane
ponownie po ponownym uruchomieniu.

---

## 5. Parametry czasowe i buforowe

Wszystkie ustawia się w **ustawieniach bazy → zakładka „Czasy i bufory”** (przycisk „...” obok „Zapis do” albo menu
Ustawienia → „Zapis nagrań w bazach danych…”). Każde pole ma w oknie dokładny opis i wartość domyślną; „Przywróć wartości
domyślne” cofa wszystkie. Wartości są ograniczane do dozwolonego zakresu przy wczytywaniu konfiguracji. Definicje (zakresy i
teksty pomocy) są w jednym miejscu: `store.PARAMS`.

| Parametr | Domyślnie | Zakres | Baza | Znaczenie |
|---|---|---|---|---|
| **Pełny stan co** (`keyframe_min`) | 10 min | 0–1440 (0 = wył.) | wszystkie, tylko tryb „zmiany” | Co tyle minut zapis wszystkich sygnałów, nawet niezmienionych (p. 3.1). Mniej = więcej danych, ale szybszy odczyt zakresu i pewniejszy dowód ciągłości zapisu. |
| **Wysyłka paczek co** (`batch_s`) | 0,5 s | 0,05–60 | wszystkie | Co ile zebrane próbki idą do bazy jedną paczką. Mniej = świeższe dane w bazie, więcej zapytań; więcej = wydajniej przy bardzo wielu sygnałach. |
| **Najdłuższa przerwa między próbami** (`retry_max_s`) | 15 s | 1–600 | sieciowe | Gdy serwer nie odpowiada, ponawianie idzie z rosnącą przerwą 1 s, 2 s, 4 s… – to górna granica. |
| **Limit testu połączenia (REC)** (`test_timeout_s`) | 3 s | 0,5–60 | sieciowe | Po REC program w tle sprawdza serwer; tyle czeka na odpowiedź, zanim pokaże komunikat z przyczyną. Działa też w przycisku „Testuj połączenie”. |
| **Limit odpowiedzi serwera** (`http_timeout_s`) | 15 s | 1–300 | sieciowe | Jak długo czekać na odpowiedź przy zapisie/odczycie (jedno zapytanie HTTP InfluxDB / jedno łączenie z PostgreSQL). Dla wolnych łączy (VPN) warto zwiększyć. |
| **Dosyłanie po zatrzymaniu REC** (`close_grace_s`) | 10 s | 0–600 | wszystkie | Po Stop program tyle sekund próbuje jeszcze dostarczyć dane z kolejki; potem porzuca (lub zostawia w buforze na dysku). |
| **Kolejka w pamięci** (`queue_max`) | 300 000 wpisów | 1 000–50 000 000 | wszystkie | Ile zmian może czekać w pamięci, gdy baza jest daleko w tyle. Po przekroczeniu najstarsze są tracone (licznik „utracono”) – chyba że działa bufor na dysku. |
| **Bufor na dysku – limit** (`spool_mb`) | 500 MB | 0–100 000 (0 = wył.) | sieciowe | Rozmiar lokalnego bufora na dane, gdy serwer jest niedostępny (p. 6.3). Po przekroczeniu najstarsze dane są tracone. |
| **Kompresja danych starszych niż** (`compress_days`) | 7 dni | 0–3650 (0 = bez kompresji) | TimescaleDB | Serwer kompresuje fragmenty starsze niż tyle dni (zwykle kilka razy mniej miejsca). Skompresowane dane trudniej usunąć (p. 7.5); 0 = najprostsze usuwanie, ale pełny rozmiar tabeli. |
| **SQLite: nowy plik po** (`rotate_mb`) | 0 (nigdy) | 0–1 000 000 MB | SQLite | Po przekroczeniu rozmiaru kolejne nagrania idą do nowego pliku (p. 8). |
| **SQLite: nowy plik każdego dnia** (`rotate_daily`) | wyłączone | tak/nie | SQLite | Pierwsze nagranie danego dnia trafia do pliku z datą w nazwie (p. 8). |
| **Odczyt: maks. punktów na sygnał** (`read_max_points`) | 200 000 | 1 000–50 000 000 | wszystkie | Powyżej tej liczby wczytywane dane są zmniejszane (p. 7.3). |
| **Kosz: przechowuj** (`trash_days`) | 30 dni | 0–3650 (0 = bez kosza) | wszystkie | Usunięte nagranie jest ukryte i można je przywrócić; po tylu dniach znika na stałe (p. 7.5). 0 = usunięcie od razu trwałe. |
| **Automatyczne czyszczenie** (`retention_days`) | wyłączone | 0–36500 | wszystkie | Własne nagrania starsze niż tyle dni są przenoszone do kosza przy otwarciu przeglądu nagrań. |
| **Nazwa nagrania** (`title_ask`) | w trakcie | na początku / w trakcie / na końcu / nie pytaj | wszystkie | Kiedy program pyta o tytuł, uwagi i tagi (p. 7.4). |
| **Przegląd nagrań pokazuje** (`view_scope`) | tylko moje | moje / wszystkie | wszystkie | Domyślny filtr użytkownika w przeglądzie (p. 7.6). |
| **Usuwanie i edycja cudzych nagrań** (`delete_others`) | wyłączone | tak/nie | wszystkie | Bez zaznaczenia można zmieniać tylko własne nagrania (p. 7.6). |
| **SQLite: wspólny folder** (`sqlite_shared`) | wyłączone | tak/nie | SQLite | Ścieżka względna wskazuje na `ProgramData\S7Trace\data` zamiast Dokumentów konta (p. 7.6). |

Stałe niezmienne w oknie: paczka do 20 000 wierszy na jedną wysyłkę (5000 linii na jedno żądanie InfluxDB), stały limit
odczytu `MAX_READ_ROWS` = 5 000 000 wpisów w pamięci (p. 7.3), początkowa przerwa ponawiania 1 s.

Które pola widać dla której bazy: SQLite – pełny stan, paczki, dosyłanie, rotacja, limit odczytu; bazy sieciowe – wszystko
poza rotacją.

---

## 6. Niezawodność zapisu do bazy

### 6.1. Test połączenia przy naciśnięciu REC

REC **nie czeka** na serwer. Po naciśnięciu program w osobnym wątku robi test połączenia (limit: „Limit testu połączenia”).
Jeśli serwer nie odpowiada, od razu pojawia się **komunikat z przyczyną** (np. „brak połączenia z http://…”, „HTTP 401”,
błędne hasło) i przyciski **„Kontynuuj REC”** (domyślnie – dane czekają w kolejce lub buforze na dysku i zostaną wysłane po
powrocie serwera) oraz **„Przerwij REC”** (zatrzymuje nagrywanie, można poprawić ustawienia). Okno nie blokuje wykresu ani
zbierania. Dla SQLite błąd ścieżki zgłaszany jest natychmiast, bez testu w tle.

### 6.2. Ponawianie

Przy każdym błędzie zapisu (serwer wyłączony, sieć, pełny dysk) wątek zachowuje paczkę i ponawia z przerwą 1, 2, 4… s aż do
„Najdłuższej przerwy między próbami”. Błąd widać w pasku statusu („REC: zapisano N, w kolejce M, … – BŁĄD: …”).

### 6.3. Bufor na dysku (spool)

* Włączony, gdy cel jest bazą **sieciową** i „Bufor na dysku” > 0. Pliki: `Dokumenty\S7Trace\spool\spool_<id>.db`
  (lokalny SQLite: kolejka wpisów w kolejności zapisu + opis nagrania).
* Dopóki serwer działa, dane idą od razu do niego (bufor jest pusty). Gdy zawiedzie – paczki lądują na dysku, a po powrocie
  serwera są **dosyłane od najstarszych**, w oryginalnej kolejności; nowe dane w tym czasie dopisują się na koniec bufora.
* Przekroczenie limitu: usuwane jest ok. 20 % najstarszych wpisów (licznik „utracono” w statusie).
* Pasek statusu pokazuje „**na dysku N**” (liczbę wpisów oczekujących na wysłanie).
* **Przeżywa zamknięcie programu:** jeśli po Stop nie udało się dostarczyć wszystkiego w czasie „Dosyłanie po zatrzymaniu REC”,
  plik bufora zostaje. **Następne uruchomienie REC do tej samej bazy dosyła osierocone bufory** (tylko jeśli opis celu
  się zgadza), po czym je usuwa. Pusty bufor jest usuwany przy zakończeniu nagrania.
* Bez bufora (0 MB) działa wyłącznie kolejka w pamięci (`queue_max`), po jej zapełnieniu najstarsze wpisy są tracone.

### 6.4. Zamykanie

Po Stop program daje „Dosyłanie po zatrzymaniu REC” sekund na dostarczenie reszty, zapisuje czas końca nagrania i zamyka
połączenie. Czekanie nigdy nie blokuje okna dłużej niż ten czas + kilka sekund.

---

## 7. Przegląd nagrań, odczyt i import

### 7.1. Okno „Przegląd nagrań” (menu Plik → „Przegląd nagrań w bazach (SQLite / InfluxDB / TimescaleDB)…”)

Okno otwiera się zawsze (także podczas zbierania); **wczytanie na wykres** jest możliwe tylko, gdy karta jest zatrzymana.

* **Baza**, „Ustawienia…” (połączenie, czasy, nagrania i użytkownicy), „Odśwież listę”, „Zaległe bufory…” (widoczny, gdy są takie bufory, p. 7.7).
* **Szukanie** w tytule, uwagach, tagach, konfiguracji, karcie, IP, użytkowniku i komputerze (bez rozróżniania wielkości liter),
  filtr **użytkownika** (Moje / Wszystkie / konkretny użytkownik) i pole wyboru **Kosz**.
* **Tabela** z kolumnami: Początek, Czas trwania, Tytuł, Tagi, Uwagi, Użytkownik, Komputer, Konfiguracja, IP, Karta, Sterownik, Nr seryjny, Zapis, Sygnały,
  Wpisy. **Sortowanie** po każdej kolumnie (kliknięcie nagłówka; czas i liczby sortują się liczbowo), domyślnie najnowsze na górze.
  Liczba wpisów jest podawana dla SQLite i TimescaleDB (InfluxDB nie podaje jej tanio).
* **Grupuj po dniach:** nagłówek z datą i dniem tygodnia (oraz liczbą nagrań) nad nagraniami z każdego dnia, najnowsze dni na górze. Przy grupowaniu sortowanie po kolumnach jest wyłączone; nagłówków nie da się zaznaczyć.
* **Tylko zakres czasu:** zaznacz i ustaw od–do (po wybraniu nagrania domyślnie jego początek i koniec).
* Przyciski: **Właściwości…** (tytuł, uwagi, tagi), **Sterownik…** (dane sterownika zapisane z nagraniem, p. 1.4), **Usuń** (do kosza albo trwale, p. 7.5), **Zapisz jako CSV…**, **Wczytaj**
  (dwuklik też wczytuje) i – w widoku kosza – **Przywróć**, **Opróżnij kosz**.
* Pasek pod tabelą: liczba nagrań, nagrań w koszu, liczba wpisów, ostrzeżenie o zaległych buforach.

### 7.2. Jak odtwarzane są krzywe

Zdarzenia z zakresu + (dla trybu „zmiany”) stan sprzed zakresu są składane w macierz; wartości są przenoszone do przodu
do następnej zmiany (krzywa schodkowa); przerwy (`NaN`) pozostają przerwami. Gdy w zakresie jest zdarzenie dokładnie w chwili
początku, pierwszeństwo ma ono, a nie stan z wyszukiwania wstecz.

### 7.3. Długie nagrania: zmniejszanie liczby punktów

* Jeśli po wczytaniu jest więcej wierszy niż „Odczyt: maks. punktów na sygnał”, program **zmniejsza dane**: dzieli oś czasu na
  przedziały i z każdego zachowuje wiersze z **minimum i maksimum każdego sygnału**, pierwszy i ostatni wiersz oraz
  miejsca, gdzie sygnał staje się nieczytelny lub czytelny – **szpilki i przerwy nie znikają**. Pasek statusu podaje „zmniejszono
  z X do Y wierszy (min/max)”.
* Gdy zakres ma więcej niż 5 000 000 wpisów (stała `MAX_READ_ROWS`), dane nie mieszczą się w pamięci, więc:
  * **SQLite** i **TimescaleDB** liczą min/max **po stronie bazy** (SQL: `GROUP BY` przedziału, w Timescale `date_bin`, działa też na
    zwykłym PostgreSQL 14+),
  * **InfluxDB** (wszystkie wersje) czyta zakres **w plasterkach** (co najmniej 48, każdy min. 1 min), zmniejsza każdy plasterek i
    skleja wynik, przenosząc stan sygnałów z plasterka do plasterka. Cała treść i tak jest przesyłana przez sieć (wolniej niż w SQL),
    ale pamięć jest ograniczona. Jeśli jeden plasterek sam przekracza limit, program prosi o węższy zakres.
* Zmniejszanie dotyczy tylko wczytania na wykres; **eksport do CSV zawsze zapisuje wszystkie wiersze** (p. 9).

### 7.4. Tytuł, uwagi i tagi – kiedy program pyta

Ustawienie **„Nazwa nagrania”** (ustawienia bazy → zakładka „Nagrania i użytkownicy”; dotyczy zapisu do baz, nie do CSV):

| Wybór | Zachowanie |
|---|---|
| **Na początku** | Po naciśnięciu REC pojawia się okno (tytuł, uwagi, tagi); nagrywanie rusza po „Rozpocznij nagrywanie”. „Anuluj REC” = bez nagrywania. |
| **W trakcie** (domyślnie) | Nagrywanie rusza od razu; obok pojawia się niemodalne okno – można je wypełnić w dowolnej chwili („Zapisz”), albo pominąć. Dane nie czekają na odpowiedź. |
| **Na końcu** | Pytanie przy zatrzymaniu REC / Stop (tylko jeśli tytuł nie został nadany wcześniej). „Pomiń” = bez tytułu. |
| **Nie pytaj** | Tytuł można nadać później: przegląd nagrań → Właściwości… |

Tytuł domyślnie podpowiada nazwę konfiguracji (`{confname}`). Zmiany są zapisywane przez wątek zapisu (także przy chwilowo niedostępnym serwerze:
opis trafia do bufora na dysku razem z danymi). Dodanie zmiennej w trakcie zapisu zaczyna nowe nagranie z **tym samym tytułem**, bez nowego pytania.

### 7.5. Kosz i usuwanie nagrań

* **Usuń** (przegląd nagrań): po potwierdzeniu (z listą nagrań) nagranie trafia do **kosza** – jest ukryte, ale dane zostają. W widoku
  „Kosz” można je **przywrócić** albo usunąć **trwale** (też zaznaczone grupą) lub **opróżnić kosz**.
* Po „Kosz: przechowuj” dniach (domyślnie 30) nagranie z kosza znika na stałe – robi to program przy otwarciu przeglądu. 0 dni = bez kosza,
  usunięcie jest od razu trwałe. „Automatyczne czyszczenie” przenosi własne nagrania starsze niż N dni do kosza (domyślnie wyłączone).
* Nagrania, które właśnie trwa w tym programie, nie można usunąć ani edytować w przeglądzie (zmieniasz je oknem „nazwa nagrania”); nagrania innych instancji programu są rozpoznawane tylko po braku czasu końca (kolumna „Czas trwania”). **Czas trwania nagrania liczy się od chwili naciśnięcia REC do ostatniej zapisanej próbki** (a nie od Startu skanowania): nagranie 20-sekundowe, włączone po minucie skanowania, pokazuje 20 s. W trybie „tylko zmiany” koniec nagrania to ostatnia próbka, a nie ostatnia zmiana. Okno „Przegląd nagrań” samo odczytuje listę przy otwarciu i po zmianie pola „Baza:”.
* **Co dzieje się w bazie:**
  * **SQLite:** wiersze są kasowane, plik zmniejszany (`VACUUM`).
  * **TimescaleDB:** `DELETE` danych i opisu. Dane w skompresowanych fragmentach wymagają TimescaleDB 2.11+ (i są usuwane wolniej); błąd jest pokazywany. Jeśli ważne jest szybkie i pewne usuwanie, ustaw `compress_days` na 0.
  * **InfluxDB 1.x:** `DROP SERIES` po tagu sesji. **InfluxDB 2.x:** API `/api/v2/delete` z warunkiem na sesję. Wymaga uprawnień do usuwania.

### 7.6. Użytkownicy: czyje są nagrania

* Każde nagranie zapamiętuje **konto Windows** (właściciel) i **komputer**. Stare nagrania bez właściciela są traktowane jak własne.
* **SQLite** domyślnie leży w `Dokumenty\S7Trace` bieżącego konta – każdy użytkownik ma więc własny, prywatny plik. Opcja **„wspólny folder”**
  przenosi plik (przy ścieżce względnej) do `ProgramData\S7Trace\data` (z prawem zapisu dla wszystkich kont), żeby kilka kont na jednym komputerze
  widziało te same nagrania; właściciel rozróżnia, czyje są. Nie używaj wspólnego pliku SQLite przez udział sieciowy.
* **InfluxDB i TimescaleDB** są ze swej natury wspólne dla wszystkich, którzy mają dostęp do serwera; właściciel w opisie pozwala je rozróżniać.
* **Przegląd nagrań** pokazuje domyślnie **tylko moje** (ustawienie „Przegląd nagrań pokazuje”; w oknie można przełączyć na Wszystkie albo wybranego
  użytkownika).
* **Prawa:** domyślnie można usuwać i edytować tylko **własne** nagrania. Opcja „Pozwól usuwać i edytować nagrania innych użytkowników” to
  zabezpieczenie przed pomyłką, nie system uprawnień – uprawnieniami rządzi konto bazy po stronie serwera.

### 7.7. Zaległe bufory zapisu

Bufory na dysku (p. 6.3), które nie zostały dosłane przed zamknięciem programu, widać w **Diagnostyka → „Zaległe bufory zapisu do baz…”** i w przeglądzie
nagrań (przycisk „Zaległe bufory…”). Dla każdego: opis nagrania, cel, liczba wpisów, rozmiar i informacja, czy dotyczy bieżącej bazy. **„Wyślij teraz”**
dosyła bufor od razu (tylko dla bieżącej bazy), **„Usuń bufor”** kasuje go. Bufory trwających nagrań nie są pokazywane.

## 8. Rotacja plików SQLite

Zapobiega rozrastaniu się jednego pliku przy nagraniach wielodniowych. Dwa niezależne warunki:

* **Każdego dnia** (`rotate_daily`): nowe nagranie trafia do pliku z datą: `nazwa_RRRR-MM-DD.db`.
* **Po rozmiarze** (`rotate_mb`): jeśli plik jest większy od limitu, nowe nagranie trafia do `nazwa_2.db`, `nazwa_3.db`… (pierwszy
  plik mniejszy od limitu).

Uwagi: **jedno nagranie zawsze zostaje w jednym pliku** (nagranie trwające kilka dni nie jest dzielone; rotacja działa w
momencie *rozpoczęcia* nagrania). Okno importu widzi **plik i wszystkie jego rotowane „rodzeństwo”** (`nazwa.db`,
`nazwa_2.db`, `nazwa_2026-10-03.db`) i łączy nagrania w jedną listę.

---

## 9. Eksport do CSV

W oknie importu przycisk **„Zapisz jako CSV…”** zapisuje wybrane nagranie (albo zaznaczony zakres czasu) do pliku CSV –
**wszystkie wiersze, bez zmniejszania** – w tym samym formacie co REC do CSV (można go potem wczytać przez Import CSV). Służy do
przekazania danych do Excela lub innych narzędzi.

---

## 10. Menu i okna – gdzie co jest

| Co | Gdzie |
|---|---|
| Cel zapisu i tryb próbek | panel „Nagrywanie REC”: „Zapis do”, „Próbki” |
| Ustawienia bazy (połączenie + czasy) | przycisk „...” obok „Zapis do” **albo** Ustawienia → „Zapis nagrań w bazach danych…” (dla bieżącej karty; przy zapisie do CSV pyta, którą bazę ustawić) |
| Test połączenia | „Testuj połączenie” w ustawieniach bazy; automatycznie przy REC |
| Przegląd, opisy, kosz, usuwanie, odczyt nagrań | Plik → „Przegląd nagrań w bazach (SQLite / InfluxDB / TimescaleDB)…” |
| Zaległe bufory zapisu, diagnostyka połączenia, informacje o sterowniku, aktywne sesje | menu **Diagnostyka** (kolejność menu: Plik, Widok, Diagnostyka, Znaczniki, Ustawienia, Pomoc) |
| Eksport do CSV | „Zapisz jako CSV…” w przeglądzie nagrań |
| Pomoc | F1 → „Przyciski sterujące” → REC |
| Znaczniki, zapis znaczników, wyszukiwarka | menu **Znaczniki** (Dodaj znacznik teraz, Znacznik poziomu sygnału, Lista znaczników…, Zapisz znaczniki…, Wyszukiwarka danych…) oraz rząd przycisków pod wykresem („Dodaj znacznik”, „Lista znaczników…”, „Zapisz znaczniki”, „Szukaj w danych…”); prawy przycisk na wykresie i na znaczniku (patrz rozdz. 13) |
| Folder plików CSV (snapshot, REC), baza znaczników | `Dokumenty\S7Trace` bieżącego użytkownika (patrz 13.9) |

---

## 11. Czego nie sprawdzono i znane ograniczenia (stan na 2026-10-03)

* **Prawdziwe serwery InfluxDB nie były dostępne.** Zapis i odczyt przetestowano na atrapie serwera HTTP (protokół v1/v2, linie protokołu,
  zapytania, usuwanie, scalanie punktów o tym samym czasie). Pierwsze uruchomienie na prawdziwym serwerze może ujawnić różnice w składni zapytań –
  zwłaszcza odczyt z zaglądaniem wstecz, `DROP SERIES` (v1) i `/api/v2/delete` (v2). Do sprawdzenia na prawdziwym serwerze służy `Test-InfluxDB.bat` (p. 11b).
* **TimescaleDB:** zapis, odczyt, opis, kosz, usuwanie i odczyt zagregowany sprawdzono na prawdziwym PostgreSQL 16 (sterowniki `psycopg` i
  `pg8000`), ale **bez rozszerzenia `timescaledb`** – hypertable, kompresja i usuwanie ze skompresowanych fragmentów nie były sprawdzone (służy do tego krok „kompresja” w `Test-TimescaleDB.bat`, p. 11a).
* **`psycopg` / `pg8000` na Windows Server 2016** – uruchom `Test-TimescaleDB.bat` z paczki (p. 11a).
* Liczba wpisów w przeglądzie jest podawana tylko dla SQLite i TimescaleDB (przy bardzo dużych tabelach Timescale liczenie może chwilę trwać).
* Wartości są liczbami zmiennoprzecinkowymi: 64-bitowe liczby całkowite powyżej 2^53 tracą dokładność (w danych ze sterownika praktycznie nie występują).
* Rotacja SQLite działa w chwili rozpoczęcia nagrania – nagranie wielodniowe nie jest dzielone między pliki.
* Program nie zastępuje uprawnień serwera: „tylko własne nagrania” to zabezpieczenie przed pomyłką (p. 7.6).

---

## 11a. Test TimescaleDB / PostgreSQL na docelowym komputerze (np. Windows Server 2016)

W paczce przenośnej jest **`Test-TimescaleDB.bat`** (skrypt `app\diagnoza_timescale.py`, źródło: `tools/diagnoza_timescale.py`).
Pyta o adres serwera, port, bazę, użytkownika, hasło i `sslmode`, a potem – **osobno dla `psycopg` i dla `pg8000`** – wykonuje:

1. środowisko (wersja Windows, Python, proxy), 2. import obu sterowników (wersje, libpq, błędy ładowania DLL),
3. DNS i połączenie TCP, 4. logowanie, wersję serwera, uprawnienia, rozszerzenie `timescaledb`,
5. pełny cykl przez kod programu: zapis nagrania (`DbRecorder`: zmiany, NaN, klatki kluczowe), odczyt całości i porównanie z zapisanym,
   odczyt zakresu czasu ze stanem sprzed zakresu, hypertable i kompresja, tytuł/uwagi/kosz/usuwanie i odczyt zagregowany, przepustowość zapisu, bufor na dysku przy zaniku serwera
   i dosyłanie po powrocie, 6. sprzątanie (tabele testowe `s7trace_selftest_…` są usuwane; `--keep` je zostawia).

Wynik: **`diagnoza_timescale.txt`** i `.json` obok `S7Trace.bat` – z czasami kroków, pełnym opisem i tracebackiem każdego błędu oraz
wskazówką (np. zły `pg_hba.conf`, DNS, SSL, brak uprawnień). **Hasło nie trafia do raportu.** Plik `.txt` wysyła się deweloperowi.
Z linii poleceń: `python diagnoza_timescale.py --host … --port … --db … --user … [--sslmode …] [--drivers pg8000] [--keep]`.
Kod wyjścia 0 = wszystko OK. Test sprawdzony na prawdziwym PostgreSQL 16.2 (Windows) z obydwoma sterownikami; **rozszerzenia
`timescaledb` tam nie było**, więc hypertable i kompresja nie były jeszcze sprawdzone na prawdziwym TimescaleDB.

**Krok „kompresja” (tylko gdy na serwerze jest rozszerzenie `timescaledb`; bez niego krok jest pomijany):** sprawdza, że polityka kompresji
na serwerze zgadza się z `compress_days` (14 → 0 → wartość z linii poleceń, `--compress-days`, domyślnie 7); zapisuje dwa nagrania sprzed 30 dni,
wymusza kompresję ich fragmentów (`compress_chunk` – polityka serwera uruchamia się raz na dobę), podaje liczbę skompresowanych fragmentów
i rozmiar przed / po; odczytuje oba nagrania i zakres czasu **ze skompresowanych danych** i porównuje z zapisem; usuwa jedno nagranie
ze skompresowanych danych (wymaga TimescaleDB 2.11+) i sprawdza, że drugie zostało nietknięte. **Ten krok napisano bez dostępu do serwera
z rozszerzeniem – pierwsze uruchomienie na prawdziwym serwerze może ujawnić różnice między wersjami TimescaleDB** (nazwy widoków i funkcji).

## 11b. Test InfluxDB 1.x / 2.x na docelowym serwerze

Paczka ma **`Test-InfluxDB.bat`** (`app\diagnoza_influx.py`, źródło `tools/diagnoza_influx.py`). Pyta o wersję (1 lub 2), adres, bazę i
użytkownika (v1) albo organizację, bucket i token (v2). Dane testowe trafiają do osobnego pomiaru `s7trace_selftest_…`; nic innego w bazie nie jest zmieniane.
Kroki: środowisko, DNS i TCP, wersja serwera (czy zgadza się z wyborem), logowanie i prawo zapisu; zapis nagrania z klatkami kluczowymi
i bez nich; odczyt całości i porównanie z zapisem; **odczyt zakresu czasu ze stanem sprzed zakresu** – z klatek kluczowych i zapytaniem
„ostatnia wartość przed zakresem”; odczyt bardzo dużego zakresu w kawałkach (szpilka nie może zniknąć); tytuł / uwagi / kosz
(punkty o tym samym czasie muszą się scalić); **usuwanie** – serwer sam liczy punkty przed i po (`DROP SERIES` w v1, `/api/v2/delete` w v2),
wskazane nagranie ma zniknąć, drugie zostać; przepustowość zapisu; sprzątanie (`--keep` zostawia dane). Wynik: `diagnoza_influx.txt` i `.json`
(token i hasło nie trafiają do raportu), z wskazówkami (zły token, brak uprawnień administratora do `DROP SERIES`, zła nazwa bucketu).
Z linii poleceń: `python diagnoza_influx.py --version 2 --url … --org … --bucket … --token …` albo `--version 1 --url … --db … --user … --password …`.
Test sprawdzono wyłącznie na atrapie serwera HTTP – **jego pierwsze uruchomienie na prawdziwym InfluxDB jest właśnie tym brakującym sprawdzeniem.**

---

## 12. Mapa kodu i testów

| Element | Plik / symbol |
|---|---|
| Konfiguracja (`StoreConfig`, `PARAMS`) | `core/store.py` |
| Filtr zmian, odtwarzanie krzywych, zmniejszanie | `ChangeFilter`, `events_to_matrix`, `downsample_minmax` |
| Rotacja SQLite | `rotated_sqlite_path`, `sqlite_family` |
| Bazy | `SqliteBackend`, `InfluxBackend`, `TimescaleBackend`, `open_backend`, `test_connection` |
| Sterownik PostgreSQL | `_psycopg`, `_pg_connect`, `pg_driver_name` |
| Rejestrator i bufor na dysku | `DbRecorder`, `Spool` |
| Test połączenia przy REC | `TraceTab._probe_db`, `_on_db_probe` |
| Okna | `ui/store_dialog.py` (`StoreDialog`, `StoreImportDialog` = przegląd nagrań, `RecInfoDialog`, `SpoolDialog`) |
| Metadane, kosz, usuwanie | `Backend.update_session` / `delete_session` / `stats`, `norm_session`, `current_user`, `shared_data_dir` |
| Zaległe bufory | `scan_spools`, `deliver_spool`, `remove_spool` |
| Pytania o nazwę | `TraceTab._open_recorder`, `_show_info_dialog`, `_close_recorder(ask=…)` |
| Testy | `tests/test_store.py`, `tests/test_store_ui.py`, `tests/test_store_manage.py` (przegląd, kosz, pytania o nazwę, bufory), `tests/test_pg_diag.py` (atrapy: serwer Influx HTTP, `psycopg`) |
| Kontrola paczki | `tools/check_deps.py`, `build-portable.ps1` (sprawdza sterownik PostgreSQL) |

---

## 13. Znaczniki na wykresie i wyszukiwarka danych

Rozdział opisuje funkcje dodane do przeglądania zapisanych i bieżących przebiegów: **znaczniki** (zakładki na osi czasu, które pozwalają
wrócić do konkretnego momentu) i **wyszukiwarkę** (znajdowanie momentów po godzinie i wartościach sygnałów). Działają w programie okienkowym i w trybie Web
(opis przeglądarkowy: `WEB.md`, rozdz. 19). Kod: `s7trace/core/markers.py`, `core/marker_draft.py`, `core/search.py` (bez Qt), okna: `ui/markers_ui.py`,
rysowanie: `ui/plotview.py`, strona: `web/markers_api.py`, `web/static/markers.js`.

### 13.1. Do czego służą

Przy nagraniu liczonym w godzinach i dniach trudno odnaleźć „ten moment, kiedy pompa stanęła”. Znacznik oznacza moment (albo przedział czasu) na wykresie,
ma tytuł i opis, a potem można go znaleźć na liście, wyszukać po tekście, autorze, kolorze czy priorytecie i jednym kliknięciem wrócić na wykres w to miejsce –
także wtedy, gdy dane leżą w nagraniu w bazie. Wyszukiwarka robi to samo z drugiej strony: zamiast pamiętać godzinę, szuka się wartości („kiedy Temp > 80 i
Run = 1”), a wynik można od razu zamienić w znacznik.

### 13.2. Rodzaje znaczników

| Rodzaj | Wygląd na wykresie | Zastosowanie |
|---|---|---|
| **Punkt** | pionowa linia w jednym momencie (kolor, grubość i styl wg ustawień) | zdarzenie: alarm, ręczny start, zmiana nastaw |
| **Zakres czasu** | dwie linie brzegowe i **półprzezroczysty obszar** koloru znacznika między nimi (lekko przykrywa wykres) | przedział: trwanie awarii, cykl produkcyjny, okres testu |
| **Różnica sygnału** | dwie linie brzegowe w pasie **jednego** przebiegu, poziom sygnału na obu końcach (kropkowana linia odniesienia), strzałka między poziomami i opis „Δ = +x (a → b)” | zmiana wartości w czasie: wzrost temperatury, spadek ciśnienia |

Znacznik może dotyczyć **wszystkich przebiegów** (linia / obszar na całej wysokości wykresu) albo **tylko wybranych** (rysuje się wtedy tylko w pasach tych
sygnałów). Przypisanie do przebiegów można zmienić w edycji znacznika.

### 13.3. Parametry znacznika

| Parametr | Znaczenie |
|---|---|
| Tytuł (do 200 znaków) | krótka nazwa, wyświetlana przy znaczniku na wykresie |
| Opis (do 4000) | co się stało |
| Uwagi (do 8000) | dodatkowe notatki (osobne od opisu) |
| Rodzaj | punkt / zakres czasu |
| Czas (od, do) | dokładność do milisekundy; można wpisać lub zmienić w oknie znacznika |
| Kolor | paleta (pomarańczowy, czerwony, zielony, niebieski, fioletowy, żółty, turkusowy, biały) albo dowolny kolor |
| Priorytet | Niski, Normalny, Wysoki, Krytyczny (do sortowania i filtrów; nie zmienia grubości linii) |
| Grubość linii | 0 = wg ustawień (menu Znaczniki → „Wygląd znaczników”), 1–8 px – własna grubość zawsze wygrywa z ustawieniami |
| Rodzaj linii | ciągła, kreskowana, kropkowana, kreska-kropka |
| Przezroczystość obszaru | tylko dla zakresu; domyślnie 76 % (obszar ledwo widoczny), 0 % = pełny kolor |
| Dotyczy | wszystkie przebiegi albo lista wybranych (do 200) |
| Grupa (do 120) | nazwa zdarzenia łączącego znaczniki (patrz 13.5) |
| Pokazuj nazwę na wykresie | tak / nie – ukrywa napis przy znaczniku (znacznik i dymek zostają) |
| **Autor** | konto, które założyło znacznik (nadawany automatycznie, nie do edycji) |
| Data założenia, data modyfikacji, kto zmienił | nadawane automatycznie przy zapisie |
| Komputer | nazwa komputera, na którym założono znacznik |
| Połączenie / nagranie | znacznik założony na wykresie na żywo pamięta kartę (połączenie), założony na nagraniu z bazy – jego identyfikator, dzięki czemu „Przejdź do punktu” otwiera właściwe nagranie |

Czas jest **bezwzględny** (mikrosekundy od 1970 r.), a nie „sekunda od startu wykresu”, więc ten sam znacznik pasuje do wykresu na żywo, nagrania z bazy i
zaimportowanego pliku CSV (program zapamiętuje w CSV czas rozpoczęcia).

### 13.4. Obsługa na wykresie (program okienkowy)

- **Gdzie to jest:** menu **Znaczniki** w pasku menu (skróty: Ctrl+Shift+M dodaj znacznik teraz, Ctrl+M lista, Ctrl+Shift+S zapisz, Ctrl+F wyszukiwarka) i osobny rząd przycisków pod wykresem (pod rzędem Start / Stop / REC). Znacznik w dowolnym miejscu zakładasz **prawym przyciskiem myszy na wykresie**.

- **Prawy przycisk na wykresie**: „Dodaj znacznik (punkt) tutaj…”, „Dodaj znacznik zakresu czasu tutaj…”, „Dodaj znacznik różnicy poziomu…” (dla przebiegu, w którego pasie
  kliknięto – okno otwiera się z wybranym tym jednym przebiegiem), „Zapisz znaczniki”, „Lista znaczników…”, „Szukaj w danych…”, przełącznik „Pokaż też znaczniki z innych połączeń”.
- **Najechanie kursorem na znacznik** otwiera **dymek** z tytułem, czasem (dla zakresu: „Od:” i „Do:” jedno pod drugim, czcionką o stałej szerokości, więc cyfra pod cyfrą), priorytetem, linią, przebiegami, grupą, opisem, uwagami oraz kolejno: Autor, Założono, Zmodyfikował, Zmieniono. Pola zmienione od ostatniego zapisu (niezapisana edycja) są w dymku **podświetlone na żółto**.
- **Podświetlenie po najechaniu**: linia (punktu i oba brzegi zakresu – ten sam standard) robi się grubsza i **zachowuje kolor znacznika**.
- **Prawy przycisk na znaczniku** otwiera menu: edycja; **zmiana pozycji** (znacznik się podświetla, klik na wykresie ustawia go w nowym miejscu, prawy przycisk anuluje;
  zakres zachowuje długość, a środek trafia w kliknięte miejsce); **ukryj / pokaż nazwę na wykresie**; grupy; cofnięcie niezapisanej zmiany; usunięcie; „Pokaż na liście”.
- **Dwuklik na znaczniku** otwiera okno edycji znacznika.
- **Przeciąganie myszą**: punkt – za linię; zakres – za brzeg (zmiana początku lub końca) albo za wnętrze (przesunięcie całości).
- Domyślnie widać znaczniki **tej karty** (połączenia) z widocznego zakresu czasu; znaczniki niezwiązane z żadną kartą widać zawsze.
- Przycisk „Lista znaczników…” otwiera **listę**: wyszukiwanie po tekście (tytuł, opis, uwagi, autor, grupa – bez względu na wielkość liter i polskie znaki), filtry
  (priorytet, kolor, autor, grupa, zakres czasu / dat, tylko widoczny zakres, ta karta / wszystkie połączenia), sortowanie (wg czasu znacznika, ostatniej zmiany,
  priorytetu), kolumny: czas, tytuł, rodzaj, priorytet, dotyczy, grupa, autor, połączenie, zmieniono, stan; dwuklik albo „Przejdź do punktu” wraca na wykres
  (w razie potrzeby otwiera nagranie z bazy).

**Grubości linii (menu Znaczniki → „Wygląd znaczników (grubość linii)…”)** – ustawiane globalnie, zapisywane **razem z konfiguracją interfejsu**: wchodzą do pliku „Zapisz konfigurację interfejsu” (Ustawienia → Interfejs; w pliku jako cztery parametry `marker_width_*`, po jednym w linii) i wracają przy jego wczytaniu; plik starszej wersji bez tych parametrów zostawia bieżące ustawienia:
linia znacznika „Dotyczy: wszystkie przebiegi” (domyślnie 2 px), linia w pasach przebiegów **wybranych** (3 px), cienka półprzezroczysta prowadnica przez pasy **pozostałych** przebiegów (1 px)
i linia **podświetlona** po najechaniu (4 px). Zakres czasu dla wybranych przebiegów ma w ich pasach także oba brzegi (grubość „wybranych przebiegów”).
**Różnica sygnału** dotyczy dokładnie jednego przebiegu (w oknie znacznika wybór „Dotyczy” przełącza się na „Wybrane przebiegi” i pozwala zaznaczyć jeden); wartości bierze z danych wykresu w obu momentach (ostatnia próbka do tej chwili).
**Blokada:** znaczniki są domyślnie zablokowane – przeciągnięcie myszą po znaczniku przesuwa wykres, nie znacznik. Zaznaczenie „Zmień pozycję znacznika” w menu prawego przycisku znacznika odblokowuje go (pole można odznaczyć, żeby znów zablokować).

Ten sam wygląd i zachowanie (dymek, podświetlenie, dwuklik, grubości linii, etykiety osi w pasach, czas trwania nagrania) ma tryb Web (`WEB.md`, rozdz. 15 i 19); różnica: ustawienia grubości linii w Web są pamiętane w przeglądarce.

### 13.5. Grupy znaczników

Podobne zdarzenia (np. kolejne awarie tej samej pompy) łączy się w grupę: menu znacznika → „Grupa znaczników” → dodaj do grupy (istniejącej albo nowej nazwy) /
przenieś / usuń z grupy / **podświetl całą grupę** (znaczniki grupy rysują się na biało) / przejdź do następnego i poprzedniego znacznika grupy (także między nagraniami) /
zmień nazwę grupy. W oknie listy można zaznaczyć wiele znaczników i użyć „Grupuj zaznaczone…” albo „Wyjmij z grupy”, a filtr „Grupa” pokazuje jedną grupę lub znaczniki bez grupy.

### 13.6. Zapis: znaczniki robocze i „Zapisz znaczniki”

Znacznik założony, zmieniony, przesunięty, zgrupowany albo usunięty na wykresie jest tylko **roboczy** – widać go na wykresie (z gwiazdką przy nazwie i
adnotacją „niezapisany” w dymku), ale **nie ma go jeszcze w pliku**. Trwały staje się po poleceniu **Zapisz znaczniki**:

1. Przycisk „Zapisz znaczniki (n)” (n = liczba niezapisanych zmian; nieaktywny, gdy nic nie ma do zapisania) albo pozycja w menu.
2. Okno **wylicza, co zostanie zapisane**: wiersze „nowy”, „zmieniony” (z nazwami zmienionych pól, np. „zmieniono: tytuł, kolor, czas”) i „do usunięcia” (przekreślone),
   z tytułem i czasem znacznika, oraz podsumowanie „x nowych, y zmienionych, z do usunięcia”.
3. Po potwierdzeniu wszystko trafia do pliku **jedną transakcją** (albo cała paczka, albo nic – błąd nie zostawia połowy zmian).
4. **Przypomnienie przy zamykaniu**: zamknięcie karty z wykresem albo całego programu przy niezapisanych znacznikach pokazuje to samo okno z wykazem i wyborem:
   Zapisz / Odrzuć zmiany / Wróć do wykresu.
5. Zmianę pojedynczego znacznika można cofnąć („Cofnij zmiany tego znacznika”, w liście „Cofnij zmianę”); usunięty znacznik trafia do wykazu „do usunięcia”
   i do chwili zapisu można go przywrócić. Zmiana, która przywraca stan zapisany, sama znika z wykazu. Nowy znacznik usunięty przed zapisem nie zostawia śladu.

### 13.7. Wyszukiwarka danych („Szukaj w danych…”)

Źródło: **bieżący odczyt na wykresie** (próbki z pamięci karty) albo **wybrane nagranie z bazy** (SQLite / InfluxDB / TimescaleDB; lista nagrań z bieżących ustawień bazy).

- **Warunki** (do 3 naraz, łączone „i”): sygnał + operator: `==` / `!=` (z tolerancją), `>`, `≥`, `<`, `≤`, w przedziale, poza przedziałem, **zmienia wartość**, **zbocze narastające**,
  **zbocze opadające**, brak wartości (NaN). Operatory „zmiany / zbocza” dają **zdarzenia** (punkty w czasie), pozostałe – **przedziały** (od kiedy do kiedy wszystkie warunki są spełnione).
- **Minimalny czas trwania** wyniku oraz ograniczenie zakresu czasu (dla nagrań: od–do).
- **Wynik**: początek, czas trwania, wartości sygnałów na początku, min…maks; najwyżej 5000 wyników. „Przejdź do” ustawia wykres na wyniku (na żywo – wstrzymuje przewijanie),
  dla nagrania otwiera jego fragment wokół wyniku; **„Dodaj znacznik…”** zakłada roboczy znacznik (zakres, gdy wynik trwał) z wpisanymi przebiegami z warunków.
- **Przejdź do daty i godziny**: pole z datą i godziną ustawia wykres w tym momencie.
- Nagranie jest przeszukiwane **kawałkami** (domyślnie 30 min) z możliwością przerwania; gdy kawałek jest za duży dla bazy, dzieli się go na pół;
  wyniki sąsiednich kawałków łączą się w jeden przedział. Wyszukiwanie w nagraniu trybu „tylko zmiany” działa na zdarzeniach (stan trzymany między nimi), tak jak odtwarzanie krzywej.

### 13.8. Gdzie znaczniki są przechowywane

- **Osobna baza SQLite, nie nagrania.** Program okienkowy: `Dokumenty\S7Trace\markers.db` (plik konta Windows); serwer Web: `web_markers.db` w folderze danych serwera.
  Dzięki temu znacznik przeżywa usunięcie, rotację i eksport nagrania, a jedna baza obsługuje wykres na żywo, każde nagranie i pliki CSV.
- Każdy wpis niesie autora, komputer i daty, więc w bazie wspólnej (Web) wiadomo, kto co zakładał; w programie okienkowym plik jest prywatny dla konta (folder `Dokumenty`).
- Odczyt jest tani (zapytania SQL po czasie i tekście), zapis – jedną transakcją; plik może być odczytywany przez kilka procesów (zmiana pliku jest wykrywana, lista odświeża się sama).

### 13.9. Jednolite foldery użytkownika (snapshot, REC, znaczniki)

Wszystko, co program zapisuje na dysku, ma jeden standard: **`Dokumenty\S7Trace` bieżącego użytkownika Windows** – pliki CSV z wyzwalacza (`snapshots`), pliki REC (`rec`), bufory na dysku,
pliki SQLite, baza znaczników. **Nazwa względna** w polu „Folder” (domyślnie `snapshots`, `rec`) oznacza podfolder tego katalogu, więc każde konto ma własne pliki, a konfiguracja
przenosi się między kontami i komputerami. Pola folderów pokazują w podpowiedzi pełną ścieżkę systemową, a wybranie folderu przyciskiem „...” wewnątrz `Dokumenty\S7Trace` zapisuje go
jako względny (poza nim – jako bezwzględny). Eksport okna → CSV i import CSV startują w tym samym folderze. W trybie Web pliki leżą w folderach kont na serwerze (`WEB.md`, rozdz. 8 i 13).

### 13.10. Ograniczenia i czego nie sprawdzono

- Po skasowaniu nagrania zostaje znacznik z nieaktualnym identyfikatorem (przejście do niego zgłosi, że nagrania nie ma).
- Rozdzielenie znaczników między konta (program okienkowy) wynika z osobnych plików w folderach `Dokumenty` kont; przy wspólnym folderze wszystkie konta widziałyby jeden plik.
- Wyszukiwarka w bazach sieciowych (InfluxDB, TimescaleDB) korzysta z tych samych funkcji odczytu co przegląd nagrań; w testach były tylko SQLite i atrapy serwerów.
- Wyszukiwanie nie przeszukuje wielu nagrań naraz (jedno wybrane nagranie albo bieżący wykres – decyzja projektowa).
- Strona Web sprawdzona ręcznie tylko w jednej przeglądarce (Chromium).

### 13.11. Znaczniki REC: Start / Stop REC, Manual REC, zmiana początku nagrania

- **Start REC (n) / Stop REC (n)**: wykres rysuje linie w chwili włączenia i wyłączenia REC (numeracja w obrębie przebiegu połączenia; stan w pamięci: `core/rec_marks.py` `RecMarks`, nie jest zapisywany w bazie znaczników). Wygląd i włączenie: *Znaczniki → Wygląd znaczników…* (`core/marker_look.py`: `rec_show`, `rec_color`, `rec_width`, `rec_style`, `rec_opacity`).
- **Manual REC**: obszar zaznaczony na zebranych danych (prawy przycisk na wykresie); **Zapis Manual REC (n)** zapisuje ten przedział bufora jako **nowe nagranie** (`core/rec_ops.py` `save_range_recording`: SQLite / InfluxDB / TimescaleDB albo nowy plik CSV; pierwszy wiersz = pełny stan sygnałów na początku obszaru, dalej tylko zmiany lub wszystkie próbki wg trybu REC).
- **Zmiana początku nagrania** (`rec_ops.move_start`, `plan_move`; metody `Backend.attach` / `set_start` / `delete_before`): wcześniej = do nagrania dopisywane są wiersze z bufora (stan w nowym początku + zmiany do dotychczasowego początku), później = zapisywany jest stan w nowym początku, potem **kasowane są starsze wiersze** i zmieniany jest `start_us` nagrania.
  W SQLite to zwykłe `INSERT` / `DELETE` / `UPDATE`; w TimescaleDB `DELETE … WHERE time < …` (w skompresowanych fragmentach wymaga TimescaleDB 2.11+); w InfluxDB 1.x `DELETE FROM … WHERE time < …`, w 2.x `/api/v2/delete`, a punkt opisu nagrania zostaje pod swoim pierwotnym czasem (zmienia się tylko pole `start_us`).
  Podczas trwającego nagrywania zmianę wykonuje wątek zapisujący (`DbRecorder.submit`), w kolejności z zapisywanymi wierszami. **Plik CSV** nie jest zmieniany (jest zapisywany na bieżąco) – pozycja jest wyłączona. Zasięg ograniczony buforem wykresu.
- Testy: `tests/test_rec_marks.py`, `tests/test_rec_marks_ui.py`, `tests/test_web_rec_marks.py`.

### 13.12. Mapa kodu i testów

| Element | Plik / symbol |
|---|---|
| Model znacznika, baza, walidacja | `core/markers.py`: `Marker`, `MarkerStore` (`add`, `update`, `delete`, `apply` = wiele zmian w jednej transakcji, `search`, `groups`), `default_path` |
| Zmiany robocze | `core/marker_draft.py`: `MarkerDraft` (`add`, `update`, `delete`, `revert`, `changes`, `commit`), `Change` |
| Wyszukiwarka | `core/search.py`: `find_hits`, `search_backend` (kawałkowanie nagrań), `Cond`, `OPS` |
| Rysowanie, dymek, przeciąganie | `ui/plotview.py`: `set_markers`, `start_marker_placement`, `_on_hover` |
| Obsługa na karcie, okna | `ui/markers_ui.py`: `TabMarkers`, `MarkerEditDialog`, `PendingDialog` (wykaz do zapisu), `MarkersDialog` (lista), `SearchDialog` |
| Przypomnienie przy zamykaniu | `ui/main_window.py`: `close_tab`, `closeEvent` → `TabMarkers.confirm_close` |
| Tryb Web | `web/markers_api.py` (`MarkerService`, `/api/markers`, `/api/search`), `web/static/markers.js`, `web/recordings.py` (`Library.search`) |
| Znaczniki REC | `core/rec_marks.py`, `core/rec_ops.py`, `ui/rec_marks_ui.py` (`TabRecMarks`), `web/static/recmarks.js`, `web/hosted.py` (`rec_save_range`, `rec_move_start`) |
| Testy | `tests/test_markers.py`, `tests/test_marker_draft.py`, `tests/test_markers_ui.py`, `tests/test_web_markers.py`, `tests/test_folders.py`, `tests/test_rec_marks.py`, `tests/test_rec_marks_ui.py`, `tests/test_web_rec_marks.py` |
