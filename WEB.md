# S7Trace – tryb Web: pełny opis

Dokument opisuje serwer Web S7Trace od uruchomienia po szczegóły działania: co robi, jak i dlaczego tak, jakie ma ograniczenia, co zostało
sprawdzone (i czym), a co trzeba jeszcze sprawdzić na prawdziwym sprzęcie. Stan: commit `8d7fffd` i późniejsze (2026-10-04).

Spis treści: 1. Po co i jak to działa · 2. Uruchomienie · 3. Pierwsze kroki · 4. Konta, role, logowanie · 5. Przestrzeń konta i edycja
połączeń · 6. Podgląd na żywo · 7. Wyzwalacz · 8. REC, pliki, cele zapisu · 9. Przegląd nagrań · 10. Kreator połączenia ·
11. Programy okienkowe zgłaszają sesje · 12. Logowanie SSO · 13. Co gdzie leży na dysku · 14. Bezpieczeństwo · 15. Ograniczenia i różnice
względem programu okienkowego · 16. Co zostało sprawdzone · 17. Co trzeba sprawdzić na prawdziwym sprzęcie · 18. Dodatek: API.

---

## 1. Po co i jak to działa

**Problem.** Program okienkowy S7Trace jest jedną instancją na komputer (jedną sesją Windows). Gdy ten sam sterownik chce oglądać wiele
osób, każda otwierałaby własne połączenie (S7 ma ograniczoną liczbę połączeń na CPU i każdy skan go obciąża), a przebiegi i konfiguracje
byłyby rozproszone po komputerach.

**Rozwiązanie – centralny serwer.** Jeden komputer („serwer”) uruchamia proces `python -m s7trace.web`. To on łączy się ze sterownikami
i zbiera dane; użytkownicy otwierają stronę w zwykłej przeglądarce (Edge, Chrome, Firefox), logują się własnym kontem i widzą to, do czego
mają prawo. Dlaczego tak:

- **Akwizycja nie zależy od przeglądarki.** Odczyt trwa w osobnym procesie potomnym (ten sam mechanizm co w programie okienkowym:
  `ProcAcquirer`), więc zamknięcie karty nie przerywa ani wyzwalacza, ani nagrywania.
- **Jedno połączenie z PLC, wielu widzów.** Obciążenie sterownika nie rośnie z liczbą oglądających.
- **Własna przestrzeń konta + wspólny rejestr.** Każdy ma swoje połączenia i pliki, a administrator widzi kto jest zalogowany, z jakiego
  komputera, jakie połączenia są otwarte i z którymi sterownikami (IP, nazwa stacji, moduł).
- **Tylko biblioteka standardowa Pythona** (`http.server`, SQLite, `ctypes`), bez nowych zależności i bez bibliotek z internetu
  (wykres to czysty `canvas`, brak CDN) – paczka przenośna nie rośnie, działa w sieciach bez dostępu do internetu i na
  Windows Server 2016 (do którego przypięty jest PySide6 6.7.3).
- **Dane na żywo przez Server-Sent Events** (jednokierunkowy strumień HTTP) – wystarcza do podglądu, przechodzi przez proste proxy
  i nie wymaga WebSocketów; polecenia idą zwykłymi żądaniami JSON.

Schemat: `przeglądarka ⇄ HTTP(S) ⇄ serwer Web ⇄ proces akwizycji ⇄ sterownik PLC`. Serwer to osobny byt od programu okienkowego –
może działać na tym samym komputerze, ale nie musi; program okienkowy zostaje bez zmian (z opcjonalnym zgłaszaniem sesji, p. 11).

---

## 2. Uruchomienie

### 2.1. Z paczki przenośnej (zalecane na serwerze)
1. Rozpakuj cały folder `S7Trace` pod krótką ścieżką (np. `C:\Dev\S7Trace`). Nic się nie instaluje.
2. Uruchom **`Web-Serwer.bat`** (opcjonalnie z plikiem konfiguracji: `Web-Serwer.bat moja_konfiguracja.json`).
   Skrypt startuje `python -m s7trace.web --host 0.0.0.0 --tls --sso` – serwer słucha na wszystkich interfejsach, port **8080**, HTTPS
   z certyfikatem samopodpisanym, logowanie SSO włączone.
3. Odblokuj port **8080/TCP** w Zaporze Windows na serwerze.
4. Na komputerze użytkownika wejdź na `https://<adres-serwera>:8080` i zaakceptuj ostrzeżenie o certyfikacie samopodpisanym
   (jest normalne – certyfikat nie jest wystawiony przez znany urząd; zob. p. 14).

### 2.2. Z kodu (środowisko deweloperskie)
```
.venv\Scripts\python -m s7trace.web [opcje]
```

| Opcja | Znaczenie |
|---|---|
| `--config plik.json` | Plik konfiguracji S7Trace (z `%APPDATA%\S7Trace` lub zapisany z programu). **Każda zakładka = jedno wspólne połączenie** serwera. Można podać kilka razy. Połączenia są importowane raz (te same nazwa+adres+rack+slot nie dublują się po ponownym starcie). |
| `--host adres` | Adres nasłuchu. Domyślnie **`127.0.0.1`** (tylko ten komputer – bezpieczny domyślnie). `0.0.0.0` udostępnia serwer w sieci. |
| `--port N` | Port, domyślnie 8080. |
| `--data folder` | Folder danych serwera (p. 13). Domyślnie `<Dokumenty>\S7Trace\web` użytkownika, który uruchamia serwer. |
| `--tls` | HTTPS z certyfikatem samopodpisanym (tworzony przy pierwszym uruchomieniu w folderze danych, ważny 10 lat). |
| `--cert plik.pem --key plik.pem` | Własny certyfikat (np. z firmowego urzędu) zamiast samopodpisanego. |
| `--sso` | Włącza logowanie kontem Windows bez hasła (p. 12). Tylko Windows. |
| `--autostart` | Uruchamia wszystkie połączenia od razu po starcie serwera (jako użytkownik „autostart”). Bez tego po restarcie połączenia są zatrzymane. |
| `--add-user NAZWA` | Dodaje konto administratora (hasło pytane w konsoli) i kończy – np. gdy zgubiono hasło ostatniego administratora. |

**Dlaczego domyślnie `127.0.0.1` i HTTP:** serwer bez ochrony transportu nie powinien być widoczny w sieci przez przypadek. Udostępniasz go
świadomie (`--host 0.0.0.0`) i wtedy używasz `--tls`, bo inaczej hasła idą otwartym tekstem.

### 2.3. Zatrzymanie i restart
`Ctrl+C` w oknie serwera (albo zamknięcie okna) zatrzymuje połączenia i zamyka nagrania. Po restarcie:
konta, połączenia (konfiguracje), pliki, nagrania w bazach i tokeny programów **zostają**; **znikają**: zalogowane sesje (trzeba się zalogować
ponownie), stan uruchomienia połączeń (są zatrzymane, chyba że `--autostart`), bufory przebiegu w pamięci, lista zgłoszonych programów
okienkowych (wróci w ciągu kilku sekund) i znaczniki wyzwalacza. Przy twardym zabiciu procesu trwające nagranie zostaje „niezamknięte”
(w bazie bez czasu końca, CSV niedokończony – dane do tego momentu są zapisane).

---

## 3. Pierwsze kroki

1. Wejdź na adres serwera. Gdy nie ma jeszcze żadnego konta, strona prosi o utworzenie **pierwszego administratora** (nazwa + hasło min. 8 znaków).
   Ta możliwość działa tylko wtedy, gdy kont jest zero (potem `/api/setup` zwraca 403).
2. Jako administrator wejdź w „Użytkownicy” i dodaj konta osób (p. 4).
3. Każdy operator tworzy swoje połączenie: „Przegląd” → „+ Nowe połączenie” (p. 5) – albo administrator przygotowuje wspólne połączenia
   plikiem `--config`.
4. „Start” na liście połączeń → „Podgląd” / „Podgląd na żywo”.

---

## 4. Konta, role, logowanie

### 4.1. Rodzaje kont
- **Konto programu** – nazwa + hasło. Hasło jest zapisywane wyłącznie jako skrót PBKDF2-SHA256 (200 000 iteracji, losowa sól 16 B).
  Minimum 8 znaków. Nazwa 1–64 znaków (litery, cyfry, `_ . @ \ -`), unikalna bez względu na wielkość liter.
- **Konto Windows / AD** – nazwa w postaci `DOMENA\jan`, `jan@domena` albo samo `jan` (konto lokalne serwera). Hasło **nie jest zapisywane**:
  sprawdza je sam Windows (`LogonUserW`), albo konto loguje się przez SSO (p. 12). Konto musi być **wcześniej dodane** przez administratora –
  stąd bierze rolę; sam fakt posiadania konta w domenie nie daje wstępu.

### 4.2. Role
| Rola | Przegląd i wykres na żywo | Start/Stop | Tworzenie i edycja połączeń | Trigger, REC | Przegląd nagrań | Użytkownicy, tokeny, cele zapisu |
|---|---|---|---|---|---|---|
| **podgląd** (viewer) | tylko wspólne połączenia | nie | nie | nie | tak, tylko odczyt | nie |
| **operator** | swoje + wspólne | swoje + wspólne | swoje | swoje + wspólne (start/stop REC, wznowienie triggera); ustawienia – tylko swoich | tak (swoje) | nie |
| **administrator** | wszystkie | wszystkie | wszystkie | wszystkie | wszystkie źródła | tak |

### 4.3. Zabezpieczenia logowania
- Po **5 błędnych hasłach** para (konto, adres klienta) jest blokowana na **60 s** (także dla właściwego hasła w tym czasie).
- Dla nieistniejącego konta serwer wykonuje podobne obliczenia jak dla istniejącego i odpowiada tym samym komunikatem – nie ujawnia,
  które konta istnieją.
- Nie da się **usunąć, zablokować ani zdegradować ostatniego administratora**.
- Zablokowanie konta, zmiana hasła i usunięcie konta kończą jego trwające sesje.
- Sesja: losowy token (`secrets.token_urlsafe`), ciasteczko `HttpOnly; SameSite=Strict` (+ `Secure` przy TLS), wygasa po **8 godzinach
  bezczynności**; otwarty wykres podtrzymuje sesję.
- Każdy POST wymaga nagłówka `X-S7Trace: 1` (ochrona przed CSRF – formularz z obcej strony go nie ustawi, a przeglądarka zablokuje
  żądanie z obcego źródła z własnym nagłówkiem).

### 4.4. Zarządzanie kontami (administrator, zakładka „Użytkownicy”)
Dodanie konta (rodzaj, rola, hasło), zmiana roli, zablokowanie/odblokowanie, nowe hasło (tylko konta programu), usunięcie. Jeśli ktoś
zapomni hasła: administrator ustawia nowe; gdy zapomni ostatni administrator: `python -m s7trace.web --add-user ...` na serwerze.

---

## 5. Przestrzeń konta i edycja połączeń

### 5.1. Własna przestrzeń konta – dlaczego
Każde konto ma **swoje połączenia** (odpowiednik zakładek programu okienkowego), zapisane osobno w `<folder danych>\workspaces\u_<konto>.json`.
Inni użytkownicy ich nie widzą (odpowiedź „nie ma takiego połączenia”, bez ujawniania istnienia). Połączenia z `--config` nie mają właściciela
i są **wspólne** (`_shared.json`): widzą je wszyscy, uruchamia operator i administrator, edytuje tylko administrator.
Po usunięciu konta jego połączenia zostają w pliku i widzi je administrator.

### 5.2. Co można ustawić (przycisk „+ Nowe połączenie” / „Edytuj”)
- Nazwa, adres IP (ew. `:port`, np. `127.0.0.1:1102`), rack, slot, cykl [ms], okno czasu [s].
- **Sposób połączenia:** automatycznie, S7comm (snap7), OPC UA, Web API (S7-1200/1500), Modbus TCP; **tryb odczytu** (bloki / pojedyncze /
  multi-read); parametry sterowników nie-S7 (porty, login, tryb zabezpieczeń…).
- **Tabela sygnałów:** nazwa, źródło (I, Q, M, DB, OPC, WEB, MBH/MBI/MBC/MBD), typ (BOOL … LREAL), DB, bajt, bit, węzeł/zmienna (OPC UA/Web API),
  Share (wysokość pasa), kolor, „Pobieraj”, „Wykres”, opis. Pola, których tabela nie pokazuje (wzmocnienie, offset, sposób wyświetlania),
  zostają bez zmian.
- Sekcje **Wyzwalacz** i **REC** (p. 7, 8) oraz przycisk **Kreator** (p. 10).

### 5.3. Reguły i limity
- Zmiany adresu, rack/slot, cyklu, trybu, sposobu połączenia i sygnałów – **tylko przy zatrzymanym połączeniu** (działający proces odczytu
  ich nie przejmie). Nazwę, okno czasu i ustawienia wyzwalacza można zmieniać zawsze; ustawień REC nie da się zmienić w trakcie nagrywania.
- Usunąć można tylko zatrzymane połączenie. Limity: **30 połączeń na konto**, **200 sygnałów na połączenie**.
- **Walidacja po stronie serwera** (nie ufamy przeglądarce): typy, zakresy (rack 0–7, slot 0–31, cykl 5–60000 ms, DB/bajt 0–65535, bit 0–7,
  Share 0,1–100), długości tekstów, kolor `#rrggbb`, unikalne nazwy sygnałów (bez względu na wielkość liter), adres tylko ze znaków
  dozwolonych. Odrzucona zmiana nie zmienia **nic** (wszystko albo nic).
- Hasła OPC UA / Web API **nigdy nie wracają do przeglądarki**; na serwerze zapisują się w pliku konta tylko przy zaznaczeniu „zapamiętaj hasło”
  (bez tego po restarcie serwera trzeba je podać ponownie). Ścieżki certyfikatów (`cert`, `key`) przeglądarka nie ustawia.

---

## 6. Podgląd na żywo

- Strona „Przegląd”: tabela połączeń (nazwa, właściciel, adres, rack/slot, stan z komunikatem, rodzina/model/firmware CPU, nazwa stacji,
  nazwa modułu, metoda, kto i kiedy uruchomił, kto ogląda, uwagi) oraz tabela zalogowanych użytkowników (konto, rodzaj konta, rola, adres
  komputera, przeglądarka, od kiedy, bezczynność, co ogląda). Odświeża się co 3 s. Dane o sterowniku (model, numer zamówieniowy, firmware,
  nazwa stacji, nazwa modułu) serwer odczytuje po każdym (ponownym) połączeniu tą samą procedurą co kreator w programie okienkowym.
- Strona „Podgląd na żywo”: wybór połączenia i okna (30 s, 1, 5, 15 min). Dane płyną strumieniem SSE ok. 10 razy na sekundę
  (najpierw ostatnie N sekund, potem nowe próbki). Wykres: **po jednym pasie na sygnał**, skalowanym do min…maks widocznego okna,
  krzywa schodkowa (wartość trzyma się do kolejnej zmiany), legenda z kolorami. Jeśli kolory sygnałów się powtarzają (np. wszystkie
  domyślne), przeglądarka użyje własnej palety.
- Serwer wysyła do 4000 punktów na zapytanie (przerzedzanie równomierne); brakujące odczyty (przerwa w łączności) to przerwa w linii.
- Przy rozłączeniu proces odczytu sam ponawia połączenie (stan „ponawianie”); wykres pokazuje przerwę.
- **Narzędzia wykresu** (pasek nad wykresem; te same na „Podgląd na żywo” i w „Nagrania”, odpowiednik programu okienkowego):
  - **Oś czasu / Offset** – opisy osi: „wg połączenia”, „Względna” (jak dotąd: −N s … teraz), „Czas aplikacji” (zegar serwera) albo „Czas PLC” (zegar sterownika = serwer + różnica z chwili połączenia); zegar ma postać `HH:MM:SS.mmm` z tylu częściami, ile wynika z powiększenia, w strefie czasowej serwera (nagrania: przeglądarki). Offset to znak, data (pełne doby, 0–3650) i godzina `HH:MM:SS.mmm` (dotyczy osi zegarowych); domyślną oś i offset połączenia ustawia edytor („Zakres okna wykresu”). W edytorze tabela „Sterownik” ma szóstą linię **Czas PLC** (data i godzina, czytana raz przy połączeniu, dalej liczona z zegara serwera, odświeżana co sekundę); różnica o dobę lub więcej jest zgłaszana z przyciskiem „Wyrównaj oś „Czas PLC” do serwera”;
  - **Znacznik poziomu sygnału** – poziome kursory wartości (najwyżej 2): w układzie pasm wartość w pasie pod linią (albo „poza pasmem sygnału”), ΔY; w układzie offset – wartość na osi Y;
  - **przybliżanie i przesuwanie:** Ctrl + kółko myszy przybliża / oddala wokół kursora, przeciągnięcie przesuwa, Shift + przeciągnięcie = przybliżenie do zaznaczonego zakresu
    (najmniejsze okno 0,1 s). Na żywo widok zostaje w miejscu (dane dalej napływają), przycisk „Wróć do danych na żywo” przywraca okno kroczące; w nagraniach serwer
    czyta wtedy wybrany zakres dokładniej, „Cały przebieg” wraca do całości;
  - **pasek przeglądowy** pod wykresem: cały zapamiętany przebieg z ramką bieżącego zakresu – przeciągnij ramkę (przesuwanie), jej brzeg (zmiana zakresu) albo kliknij obok (wyśrodkowanie);
  - **Punkty** – pokazuje punkty próbek na krzywych (do 3000 widocznych naraz);
  - **Układ** – „Pasma wg Share” (domyślny) albo „Offset Y + wzmocnienie” (jedna oś Y: wartość × wzmocnienie + offset; zakres Y z „Auto Y” albo z pól Y min / Y maks).
    Wybór w pasku jest tylko dla oglądającego; wartość domyślną (układ, Auto Y, Y min / maks, punkty) ustawia się w edycji połączenia (pola „Układ wykresu” …),
    także w trakcie pracy połączenia. Nagrania w bazach nie niosą układu – używają „Pasma”, offset sygnału jest zapisany w nagraniu.
- **Nazwy sygnałów** (lista „Nazwy sygnałów” w pasku narzędzi: „wg połączenia” / Legenda / Opisy; wybór zapisuje się przy połączeniu – `legend_style` w konfiguracji, `POST /api/connections/<id>/config`, także w czasie pracy – gdy konto może je edytować; prawy przycisk na opisie ma też „Wszystkie połączenia: …”, co ustawia styl wszystkim edytowalnym połączeniom konta i jako domyślny konta (`/api/prefs` `legend_style`); pierwszeństwo: wybór widza → styl połączenia → domyślny konta): „Legenda (lista)” albo „Opisy przy sygnałach” – nazwa w półprzezroczystej ramce w połowie pasma każdego sygnału, po prawej stronie osi pionowej (przy układzie „Offset Y + wzmocnienie” przy krzywej, ramki są rozsuwane); prawy przycisk na opisie przełącza nazwę / adres i styl; w stylu opisów lista pod wykresem jest ukryta.
- **Legenda** pod wykresem: po najechaniu na pozycję dymek z opisem sygnału (nazwa, adres, źródło, typ, skala, opis i ostatnia wartość); lista „Legenda” w pasku narzędzi (albo „Legenda pokazuje” w edycji połączenia) przełącza napisy między nazwą a adresem / węzłem OPC.
- **Pola zwijane** w edycji połączenia (Połączenie, Sterownik, Zakres okna wykresu, Trigger, Nagrywanie REC): klik w tytuł zwija pole, trójkąt za nazwą (w prawo = zwinięte, w dół = rozwinięte) obraca się o 90°; **przeciągnięcie tytułu w górę / w dół zmienia kolejność pól**. Kolejność, zwinięte pola i aktywna zakładka „System / Sieć” są pamiętane **na koncie na serwerze** (`prefs\`, `/api/prefs` klucz `panel`), więc idą za użytkownikiem do każdej przeglądarki (tak jak konfiguracja interfejsu w programie okienkowym). Tabela „Sygnały” jest teraz pod wszystkimi polami. **Prawy przycisk myszy** na nazwie elementu (np. „Adres IP”, „Cykl [ms]”) ukrywa go, na tytule pola otwiera menu pola (zwiń / rozwiń, lista elementów z haczykami, „Pokaż wszystkie elementy”); ukryte elementy też są w `prefs\` konta (`panel.hidden`; nazwy elementów = atrybuty `data-row` w `index.html`, lista `panel_cfg.WEB_ROWS`). Plik `prefs\u_<konto>.json` jest odpowiednikiem pliku konfiguracji interfejsu programu okienkowego. Na dole pola „Sterownik” jest przycisk **Pobierz dane sterownika** (`POST /api/connections/<id>/read-device`): serwer jednorazowo łączy się z PLC (z zapisanej konfiguracji, połączenie zatrzymane, S7comm) i odczytuje tylko dane sterownika i jego zegar – bez odczytu sygnałów. Pole „Sterownik” pokazuje dane sterownika połączenia.
- **Zakładki „System” i „Sieć”** pod wykresem „Podgląd na żywo” (odpowiednik zakładek na dole lewego panelu programu): System = godzina, obciążenie CPU **komputera serwera** (liczone jak w Menedżerze zadań – „Processor Utility”) i część, którą zajmuje sam serwer S7Trace wraz z procesami odczytu (`/api/sysinfo`), Sieć = czas odczytu (śr. / ostatni), pominięte cykle i ping z serwera wybranego połączenia (z `/diag?ping=1`, co 1,5 s).
- **Tabele**: wiersze naprzemiennie jaśniejsze / ciemniejsze i kolumny tabel list (połączenia, nagrania, znaczniki, konta, sygnały…) o szerokości ustawianej przez przeciągnięcie prawej granicy nagłówka – jak w programie okienkowym (`tableResizable` w app.js).
- **Kolory tabel** (przycisk „Interfejs” w nagłówku): kolor tła i czcionki nagłówka, wierszy nieparzystych i parzystych oraz ramki; to samo co w programie (Widok → Interfejs), zapis na koncie (`/api/prefs`, klucz `table`), puste = kolor strony.
- **Pasek statusu** (wiersz stanu połączenia nad wykresem, `#c-state`): prawy przycisk myszy – maksymalna liczba wierszy, kolor tła i tekstu (domyślnie jak strona), justowanie tekstu; ustawienia zapisują się na koncie (`/api/prefs`, klucz `status`) i są takie same w każdej przeglądarce. Odpowiednik paska statusu programu okienkowego.
- **Pobieranie danych sterownika** (Web = ta sama logika co w programie): przy odmowie sesji S7 serwer próbuje innych par rack/slot i zapisuje pasującą w ustawieniach połączenia (komunikat w polu pod przyciskiem), a błąd jest po polsku; różnica zegarów to dni i godziny (`diff_text`), rok z zegara PLC bez bajtu „wieku”.
- **Elementy pola „Sterownik”** są osobnymi wierszami (Rodzina, Model, Numer katalogowy (MLFB), Firmware, Numer seryjny, Nazwa stacji, Nazwa modułu, Producent / copyright, Stan CPU, Długość PDU [B], Czas PLC; pierwsze pięć z tych drugiej połowy jest domyślnie ukryte) – ten sam zestaw i te same nazwy co w programie; „Czas PLC” pokazuje „nie odczytano”, gdy zegara nie udało się odczytać (powód w podpowiedzi). Każdy wiersz, także wiersze zakładek „System” i „Sieć” pod wykresem (System zaczyna się od systemu operacyjnego serwera) i przycisk „Pobierz dane sterownika”, ukrywa się prawym przyciskiem myszy; ukryty przycisk zostaje w menu prawego przycisku. Dane w zdaniach (liczby z jednostkami w ocenie łącza) są pogrubione (`boldNums`). Opis nagrania („Opis”) jest w oknie REC, w „Nagraniach” i w edycji nagrania. Przycisk „?” świeci na pomarańczowo przy włączonym trybie pomocy (kolor stały – w programie okienkowym konfigurowalny).
- **Przycisk „?”** w nagłówku strony włącza tryb pomocy (Shift+F1, Esc kończy): najechanie na przycisk, pole, nazwę kolumny albo tytuł pokazuje dymek – co to, do czego, jak ustawić, zakres (teksty z `/api/help`, wspólne z programem okienkowym). „O programie” w nagłówku: autor, wersja, data (`/api/version`).
- **Strona „Diagnostyka”** (v1.22: nagłówek „Diagnostyka połączenia za adresem IP: …, port: …”, tabela „Obciążenie sieci i sterownika przez ten serwer (szacunek)” – chwilowo / 10 s / 60 s / całość, przycisk „Kto łączy się ze sterownikiem” = połączenia TCP z TEGO serwera do sterownika; obciążenia procesora sterownika i listy jego rozmówców nie widać z zewnątrz) (odpowiednik menu Diagnostyka programu okienkowego): wybór połączenia; ocena łącza (pasek i opis przyczyn), czasy odczytu i okresy próbkowania
  (chwilowo, średnie 10 s / 60 s / całość, min, maks, odchylenie, P95, P99), cykl ustawiony i rzeczywisty, pominięte cykle, błędy i zerwania, dostępność, przepustowość,
  **tabela „Informacje o sterowniku”** i czas sterownika (z chwili połączenia) z różnicą do zegara serwera, przycisk „Ping sterownika” (ICMP z serwera), lista
  **kto jeszcze odczytuje ten sterownik** (programy okienkowe zgłaszające się do serwera i inne połączenia serwera) oraz – dla administratora – **zaległe bufory zapisu**
  nagrań do baz sieciowych (tylko lista; dane są dosyłane przy następnym nagraniu do tej samej bazy, usuwanie bufora jest w programie okienkowym). Odświeża się co 2 s.

---

### 6.1. Start po Stop, Reset i Auto-Reset

**Przerwy Stop → Start na wykresie (v1.17 / v1.18):** lista **Przerwy Stop → Start** nad wykresem (pozycje „wg połączenia” / „Pełna przerwa” / „Wytnij z wykresu” / „Pas o stałej szerokości”) i pole **px** (szerokość pasa, 8 – 300); wybór zapisuje się przy połączeniu, jeśli konto może je edytować – klucze `gap_mode` (`full` / `join` / `fixed`) i `gap_px` w `/config` i w `series.layout`. Jak w programie okienkowym (Widok → „Przerwy Stop → Start (ta karta)”): **wycięcie** = zerowa szerokość, krzywe się stykają, jeden znacznik „Stop / Start odczytu (n)”, opisy osi (zegarowej albo w sekundach) przeskakują („30 s | 50 s”); **pas o stałej szerokości** = półprzezroczysty pas o `gap_px` pikselach niezależnie od czasu pauzy i przybliżenia (szerokość w jednostkach wykresu wynika z widocznego zakresu: `gmFit`), z długością pauzy w pasie, znacznikami Stop / Start odczytu na brzegach i jednym podwójnym opisem osi pośrodku; czas wewnątrz pasa jest mapowany proporcjonalnie (znacznik w pauzie stoi tam, gdzie jego czas; kliknięcie w pasie daje proporcjonalny czas). Dane, znaczniki i nagrania zostają na prawdziwym czasie; przeciąganie, Ctrl + kółko, pasek podglądu i okno czasu liczą się w jednostkach wykresu (`gmD` / `gmR` / `cxX` / `cxT` w `chartx.js` = odpowiednik `core/gapmap.py`). Dotyczy tylko podglądu na żywo (nagrania z bazy nie mają przerw rozpoznawanych przez serwer).

**Wygląd pasa przerwy (v1.19):** w oknie „Wygląd znaczników” (konto, zapisywane na serwerze razem z szerokością linii): kolor i nieprzezroczystość wypełnienia, opis długości (włączony, w pionie / w poziomie, kolor czcionki, u góry / pośrodku / na dole) – klucze `gap_*` w `/api/prefs` → `marker_look`. Linie „TRIG (n)”: `trig_show` / `trig_width` / `trig_color` / `trig_style` tamże; zdarzenia triggera w `/config` mają numer `n`.

**Elementy nieaktywne – ukrywane czy wyszarzone (v1.22):** okno „Kolory tabel i interfejsu” ma pole „Elementy nieaktywne (panel ustawień)”: Ukrywane (domyślnie) albo Wyszarzone; wybór zapisuje się na koncie (`/api/prefs` → `panel.inactive`) i wyłącza lub włącza poniższy mechanizm.

**Ukrywanie nieaktywnych (v1.21):** w edytorze połączenia pola wyszarzone przez inne ustawienia (np. „Zapis snapshotu do” przy akcji „Pauza”, „B” poza warunkiem „between”, „Y min” w układzie pasm) chowają się same. Menu prawego przycisku nad grupą (Połączenie, Zakres okna wykresu, Trigger, Nagrywanie REC) kończy się pozycją **„Ukrywanie nieaktywnych”** (włącz / wyłącz, osobno dla grupy, zapis na koncie: `/api/prefs` → `panel.autohide`); zaznaczenie ukrytego elementu pokazuje go mimo wyszarzenia – do następnej zmiany jego stanu. Pola zablokowane tylko na czas pracy połączenia nie liczą się jako nieaktywne.

Jak w programie okienkowym (Pomoc, rozdz. „Przyciski sterujące”). Domyślnie ponowny **Start** po **Stop** **nie czyści bufora połączenia**: oś czasu biegnie dalej, a w krzywych powstaje **przerwa** równa czasowi między Stop a Start
(serwer przesuwa czasy nowych próbek – `ProcAcquirer(anchor_ts=…)` – i wstawia dwa wiersze NaN: tuż po ostatniej próbce sprzed przerwy, żeby stara wartość nie była „przedłużana” przez przerwę, oraz w chwili Start). Przerwę znaczą linie **Stop odczytu (n)** / **Start odczytu (n)** (`rec.gaps` w opisie połączenia: `n`, `t0`, `t1`). Wykres jest kontynuowany tylko dla tych samych sygnałów (nazwa, adres, typ); przy zmianie sygnałów albo pustym buforze Start zaczyna od nowa.
Na stronie wykresu stoi przycisk **Reset** (po lewej od REC, tylko operator / administrator): **kliknięcie** czyści bufor (na pracującym połączeniu czas biegnie dalej, na zatrzymanym wykres zaczyna się od zera);
**przytrzymanie** pokazuje po 1 s odliczanie „Reset (3s)” … „(1s)”, a po 4 s załącza **Auto-Reset** (przycisk wciśnięty, niebieski tekst) – wtedy każdy Start zaczyna wykres od nowa. Puszczenie w trakcie odliczania anuluje, kliknięcie „Auto-Reset” go wyłącza.
Ustawienie `auto_reset` jest w konfiguracji połączenia (zapisywane na koncie; edytowalne też w edytorze połączenia) i w opisie połączenia (`auto_reset`). Kolory załączonego przycisku (tło, tekst) są w oknie „Interfejs” (przycisk „Interfejs” – tabele)
i zapisują się na koncie razem z kolorami tabel (`/api/prefs`, klucz `table`: `reset_on_bg`, `reset_on_text`). Przy trwającym odczycie przeglądarka pyta najpierw „Czy na pewno wyczyścić wykres?”, a potem (gdy nie trwa REC) „Zacząć też oś czasu od zera?” (`POST …/reset` z `{"axis": true}`; REC trwa = oś biegnie dalej, nagranie nie jest przerywane). Przeglądarka pyta o znaczniki tylko dla bufora (OK = usuń, Anuluj = zostaw) przy Reset oraz przy Start, gdy Auto-Reset jest włączony.
Testy: `tests/test_web_reset.py`.

## 7. Wyzwalacz (trigger)

Ta sama maszyna stanów co w programie okienkowym (`TriggerEngine`): warunki `==`, `>`, `<`, `between`, zbocze narastające/opadające, histereza,
przedtrigger, akcje **Pauza**, **Zapis CSV**, **Pauza + zapis CSV**. Działa **na serwerze**, w wątku odbierającym próbki, więc nie zależy
od otwartej przeglądarki i nie traci próbek.

- Stany: wyłączony → uzbrojony → zbieranie próbek po wyzwoleniu (okno − przedtrigger) → (po akcji) uzbrojony albo wstrzymany.
- **Zapis CSV:** zakres `[t − przedtrigger, t − przedtrigger + okno czasu]` z bufora trafia do pliku konta w `files\u_<konto>\snapshots`.
- **Pauza:** wykres każdego przeglądającego zamraża okno wokół wyzwolenia (linia „TRIG (n)”) aż do „Wznów (uzbrój wyzwalacz)”
  (wstrzymanie dotyczy wyzwalacza i widoku, nie akwizycji ani REC). Linie „TRIG (n)” (n = numer wyzwolenia w tym przebiegu; kolor / grubość / rodzaj: „Wygląd znaczników”) widać też przy akcji „Zapis CSV” (do 20 ostatnich zdarzeń).
- **Zapis do bazy** (`trigger.target`: `csv` / `sqlite` (baza konta `recordings.db`) / nazwa celu admina; `trigger.place`: `shared` = ta sama baza co REC, `own` = osobna: plik `snapshots/<db_file>` w folderze konta albo osobna tabela / measurement `…_snapshots` celu sieciowego): snapshot jest nagraniem „Snapshot (trigger)” (`rec_ops.save_range_recording`, zapis w osobnym wątku, wynik w notatce wyzwalacza). Pola w edytorze: „Zapis snapshotu do”, „Baza snapshotów”, „Plik bazy snapshotów”.
- Zmiana ustawień wyzwalacza podczas pracy restartuje maszynę stanów (uzbraja od nowa).
- Nazwa pliku: szablon ze znacznikami `{confname} {ip} {tab} {date} {time}` (bez ścieżek i znaków `\ / : * ? " < > |`);
  folder jest zawsze folderem konta. `{confname}` = nazwa konfiguracji albo nazwa połączenia (serwer nigdy nie pyta w oknie dialogowym).

---

## 8. REC, pliki, cele zapisu

### 8.1. REC
Przycisk „● REC / ■ Stop REC” (operator, administrator) na stronie podglądu. Nagrywanie działa na serwerze, nie wymaga otwartej przeglądarki,
kończy się samo przy zatrzymaniu połączenia (i przy zamknięciu serwera). Wymaga stanu „praca”.

| Cel | Gdzie trafiają dane |
|---|---|
| `csv` | plik CSV w `files\u_<konto>\rec` (format jak w programie okienkowym – da się go tam wczytać) |
| `sqlite` | plik `recordings.db` w folderze konta |
| nazwa celu z listy administratora | TimescaleDB / PostgreSQL, InfluxDB 1.x, InfluxDB 2.x lub wspólny plik SQLite (p. 8.3) |

Tryb **„tylko zmiany”** (domyślny; zapis tylko zmienionych wartości + pełny stan co N minut) albo **„wszystkie próbki”**. Dla celów bazodanowych
w polu obok przycisku REC można podać **nazwę nagrania**, a w trakcie – zmienić ją (uwagi i tagi też przez API/ przegląd nagrań).
Nagranie w bazie ma jako właściciela konto z przeglądarki i jako komputer „Web <adres klienta>”. Dla baz sieciowych działa ten sam mechanizm
niezawodności co w programie okienkowym (kolejka w pamięci, **bufor na dysku** w `<folder danych>\spool`, ponawianie, dosyłanie po powrocie serwera
bazy); błąd zapisu widać przy przycisku REC.

### 8.2. Pliki konta
Przycisk „Pliki” na stronie podglądu: lista CSV (zapisy triggera i nagrania do CSV), pobieranie, a dla właściciela/administratora usuwanie.
Przeglądarka nigdy nie wybiera ścieżki, tylko szablon nazwy; próby wyjścia poza folder (`..`, ukryte pliki, obce foldery) kończą się „nie ma
takiego pliku”. Pliki konta są niedostępne dla innych kont.

### 8.3. Cele zapisu (administrator)
Zakładka „Cele zapisu”: nazwa, rodzaj (TimescaleDB / InfluxDB 2.x / InfluxDB 1.x / SQLite wspólny), parametry połączenia, kompresja TimescaleDB,
widoczność nagrań, kosz, auto-kosz, przycisk **Test**. **Dlaczego tak:** hasła i tokeny baz nie powinny trafiać do każdego użytkownika; wpisuje
je raz administrator, a użytkownicy wybierają cel po nazwie i widzą tylko nazwę i opis (np. „TimescaleDB db1:5432 / s7trace”). Parametry czasowe
i niezawodnościowe (partie, ponawianie, bufor, rotacja SQLite…) mają wartości domyślne jak w programie okienkowym; zmienia się je w pliku
`web_targets.json` (nazwy pól jak w `StoreConfig`). Opis baz i ich parametrów: `BAZY_DANYCH.md`.

---

## 9. Przegląd nagrań (zakładka „Nagrania”)

Odpowiednik okna „Przegląd nagrań” programu okienkowego.

- **Źródła:** „Moje nagrania” (SQLite konta), „Wspólne połączenia” (SQLite wspólnych połączeń – widoczne dla wszystkich), cele z listy administratora,
  a dla administratora pliki SQLite innych kont. Nagrania zapisane w CSV są w „Plikach”, nie w tym przeglądzie.
- **Lista:** tytuł, uwagi, start, czas trwania, właściciel, komputer, połączenie, **sterownik** (model i nazwa stacji, pod spodem numer seryjny; dymek z całą tabelą), sygnały, tagi; wyszukiwanie po wszystkim naraz (także po danych sterownika). Dane sterownika są zapisywane z każdym nagraniem w każdej bazie (patrz `BAZY_DANYCH.md`, p. 1.4); po wczytaniu nagrania widać je nad wykresem.
- **Wczytaj:** wykres z pasami jak na żywo; długie nagrania zmniejszane do ok. 6000 punktów metodą min/maks (szczyty nie znikają); przeciągnięcie
  myszą po wykresie przesuwa, Ctrl + kółko albo Shift + przeciągnięcie przybliża zakres (serwer czyta wtedy ten zakres dokładniej), pasek przeglądowy i „Cały przebieg” wracają do całości; dostępne są też kursory, punkty i układ (p. 6). W nagraniach „tylko zmiany” ostatnia
  wartość trzyma się do końca zakresu.
- **CSV:** wszystkie wiersze nagrania lub widocznego zakresu (bez przerzedzania), format zgodny z programem okienkowym.
- **Opis:** tytuł, uwagi, tagi (właściciela nie da się zmienić).
- **Kosz:** „Do kosza” → zakładka „kosz” → „Przywróć” / „Usuń trwale” (trwale tylko z kosza). Kosz opróżnia się sam po `Kosz: dni` celu (domyślnie 30,
  0 = kasuj od razu), „Auto-kosz” celu przenosi własne stare nagrania do kosza. Zasady sprzątania wykonują się przy otwarciu listy.
- **Kto co widzi i zmienia:** we własnym pliku wszystko; we wspólnym pliku i w celach bazodanowych administrator wszystko, pozostali swoje
  (albo wszystkie, gdy cel ma „wszyscy widzą wszystkie”) i zmieniają swoje (albo cudze, gdy cel ma „zmieniać cudze”); „podgląd” tylko czyta;
  trwające nagranie jest zablokowane. Nagranie spoza zasięgu użytkownika jest dla niego „nie do odczytania”, nie tylko ukryte na liście.
- Bazy InfluxDB 3 nie są obsługiwane (usunięte z programu – nie da się w nich usuwać nagrań).

---

## 10. Kreator połączenia

W edytorze przycisk „Kreator: rozpoznaj sterownik”. Serwer sprawdza podany adres: ping, port S7 (102), S7comm, OPC UA, Web API, Modbus (albo tylko
wybraną metodę), odczytuje dane urządzenia i pokazuje raport z zaleceniem („Zalecana metoda…”, uwagi o PUT/GET, optymalizowanych DB itp.).
„Zastosuj zalecenia” ustawia sposób połączenia, rack, slot i – jeśli pole puste – nazwę połączenia z nazwy stacji. Zapis dopiero przyciskiem „Zapisz”.

Ograniczenia: dostęp operator/administrator; **jedno rozpoznawanie naraz na konto**; serwer łączy się z podanym adresem, więc nie dawaj tej roli
osobom, którym nie ufasz w sieci (mogą użyć serwera do sprawdzania adresów, które on widzi, a oni nie).

---

## 11. Programy okienkowe zgłaszają sesje (wspólny rejestr)

**Po co:** żeby administrator widział na jednej stronie, kto uruchomił S7Trace (konto Windows, komputer) i które sterowniki skanuje – także na innych
komputerach – oraz żeby przed Startem pojawiło się ostrzeżenie, gdy ktoś już skanuje ten sam sterownik.

1. Administrator: „Użytkownicy” → „Tokeny programów okienkowych” → „Utwórz token” (pokazuje się **raz**, na serwerze zostaje tylko jego skrót SHA-256).
2. W programie okienkowym: Ustawienia → „Serwer Web (zgłaszanie sesji i wspólny rejestr)…”: włącz, adres serwera (np. `https://serwer:8080`), token,
   „Sprawdzaj certyfikat” (odznacz tylko przy certyfikacie samopodpisanym), „Test połączenia”.
3. Program co ok. 5 s wysyła: użytkownika Windows, nazwę komputera, PID, czas uruchomienia i swoje karty (tytuł, adres, stan, od kiedy). Dane budowane są
   w wątku GUI, wysyła je osobny wątek – brak serwera nigdy nie przeszkadza programowi.
4. Serwer pokazuje programy na stronie „Przegląd” (tabela „Programy okienkowe zgłoszone do serwera”; aktywne = zgłosiły się w ciągu 20 s) oraz kolumnę
   „Uwagi” przy połączeniach serwera („także: jan (PC-HALA-1)”), gdy ten sam adres skanuje program okienkowy.
5. W odpowiedzi serwer odsyła programowi listę sterowników skanowanych przez innych (programy na innych komputerach i połączenia serwera). Program
   dołącza ją do dotychczasowego ostrzeżenia „sterownik jest już skanowany” (to samo okno co dla innego użytkownika tego samego komputera). Odpowiedź
   starsza niż 30 s nie jest używana. Własne sesje na tym samym komputerze nie dublują się.

Token jest tajemnicą programu: zapisany w konfiguracji programu użytkownika (`%APPDATA%\S7Trace\config.json`). Usunięcie tokenu w serwerze natychmiast
odcina program (pierwsze zgłoszenie dostaje 401).

---

## 12. Logowanie SSO kontem Windows (`--sso`)

Na stronie logowania pojawia się „Zaloguj kontem Windows (SSO)”. Przeglądarka przesyła konto Windows protokołem **Negotiate** (Kerberos lub NTLM),
serwer weryfikuje je przez **SSPI** (`secur32.dll`, `ctypes`) – hasło nigdy nie przechodzi przez serwer ani przez stronę.

- Konto musi być **zarejestrowane** (rodzaj „konto Windows / AD”, np. `DOMENA\jan`; dla konta lokalnego serwera można wpisać samo `jan`). Stąd bierze się rola.
- Zablokowane lub niezarejestrowane konto dostaje czytelny komunikat („Konto Windows … nie jest zarejestrowane w S7Trace Web…”) – nie 401, by przeglądarka
  nie zapętlała się w oknie hasła.
- Wymagany nagłówek `X-S7Trace` także dla tego żądania (przeciw logowaniu z obcej strony).
- Negocjacja NTLM wymaga tego samego połączenia TCP dla całej wymiany – serwer trzyma stan SSPI w obsłudze połączenia (stąd „Connection keep-alive”).
- Po stronie przeglądarki: adres serwera musi być w strefie **„Intranet”** (Edge/Chrome na Windows), a dla Firefoksa w
  `network.negotiate-auth.trusted-uris`; w innym razie przeglądarka nie wyśle poświadczeń i strona pokaże podpowiedź.
- Tylko Windows. Na innych systemach opcja jest niedostępna (serwer to zgłasza przy starcie).

---

## 13. Co gdzie leży na dysku (folder danych serwera)

| Ścieżka | Zawartość | Wrażliwość |
|---|---|---|
| `web_users.db` | konta (skróty haseł), tokeny programów (skróty) | wysoka – chroń uprawnieniami |
| `web_targets.json` | cele zapisu **z hasłami/tokenami baz (jawnie)** | **bardzo wysoka** – dostęp tylko dla konta serwisowego |
| `web_cert.pem`, `web_key.pem` | certyfikat i klucz prywatny TLS (przy `--tls`) | wysoka |
| `workspaces\u_<konto>.json`, `_shared.json` | połączenia kont (konfiguracje; hasła tylko przy „zapamiętaj”) | średnia |
| `files\u_<konto>\snapshots`, `\rec`, `recordings.db` | pliki CSV i SQLite konta; `files\_shared\…` dla wspólnych połączeń | dane pomiarowe |
| `prefs\u_<konto>.json` | ustawienia interfejsu konta (wygląd linii znaczników) | niska |
| `dbs\` | wspólne pliki SQLite celów | dane pomiarowe |
| `spool\` | bufory dyskowe nagrań do baz sieciowych | dane pomiarowe |

Zalecenie: folder danych na dysku serwera dostępny tylko dla konta, na którym działa serwer. Kopia zapasowa = kopia całego folderu (przy zatrzymanym serwerze).

---

## 14. Bezpieczeństwo – podsumowanie

**Co jest zrobione:** hasła tylko jako PBKDF2; blokada po błędach; ochrona ostatniego administratora; ciasteczka `HttpOnly`/`SameSite=Strict`/`Secure`;
nagłówek przeciw CSRF; uprawnienia sprawdzane **na serwerze** przy każdym żądaniu (przeglądarka tylko ukrywa przyciski); walidacja każdej wartości;
brak ścieżek od przeglądarki (szablony nazw, wybór celu po nazwie); zabezpieczenie przed wyjściem poza folder; sekrety baz i haseł połączeń nie wracają
do przeglądarki; tokeny programów trzymane jako skróty; certyfikat TLS (własny lub samopodpisany); domyślny nasłuch tylko lokalny; brak śladów stosu w konsoli
dla zamkniętych połączeń; nagłówki `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.

**Czego nie ma / na co uważać:**
- Certyfikat samopodpisany daje szyfrowanie, ale nie potwierdza tożsamości serwera (przeglądarka ostrzega). W firmie lepiej użyć własnego certyfikatu
  (`--cert/--key`) wystawionego przez firmowy urząd.
- To prosty serwer wątkowy (jedna wątek na połączenie, także na każdy otwarty wykres): przeznaczony do **sieci zakładowej**, nie do wystawiania
  do internetu. Do dostępu zdalnego użyj VPN lub zwrotnego proxy z uwierzytelnianiem (patrz temat „dostęp zdalny” w notatkach projektu).
- Brak dwuskładnikowego logowania, brak dziennika audytu zmian (poza tym, co widać w tabelach: kto uruchomił, kto ogląda), brak blokady konta globalnie (blokada
  jest per konto+adres).
- Wizard i połączenia serwera wykonują połączenia sieciowe z serwera – rola operatora oznacza zaufanie.
- `web_targets.json` zawiera hasła jawnie – to kompromis świadomy (serwer musi je znać, żeby łączyć się z bazą).

---

## 15. Ograniczenia i różnice względem programu okienkowego

Tryb Web **nie zastępuje** programu okienkowego, tylko go uzupełnia. Czego w przeglądarce nie ma (lub działa inaczej):

- **Napisy osi „Sygnały” / „Czas”** (v1.20: nieprzezroczyste tło nad liczbami osi, przeciągane wzdłuż osi) są tylko w programie okienkowym; wykres w przeglądarce nie ma tytułów osi (opisy znaczników stojących w tym samym czasie układa w osobnych rzędach).
- **Most do analizatora anomalii** (Ustawienia → Analizator anomalii, v1.26: serwer TCP na 127.0.0.1 przekazujący dane jednej karty zewnętrznemu programowi S7SignalAnalyzer) działa tylko w programie okienkowym; serwer Web nie ma odpowiednika (świadoma różnica na etapie wprowadzania funkcji).
- **Ikona programu przy zegarze** (Ustawienia → Ikona programu: pasek zadań / obszar powiadomień / oba) i jej menu (połączenia W / LU / AU, obciążenie, Pokaż / Ukryj, Przypnij do belki, Zakończ z pytaniem; v1.22) dotyczą tylko okna programu; strona w przeglądarce nie ma odpowiednika.
- **Wykres nagrania z bazy (v1.22):** rodzaj przerwy Stop → Start (pasek wykresu: „Przerwy Stop → Start”) działa też w widoku nagrania; przerwy są wykrywane z pustych wierszy nagrania (co najmniej 1 s), a nie z rejestru przebiegów serwera, więc przy mocnym przerzedzeniu danych (min / maks) bardzo krótka przerwa może zniknąć. Domyślny rodzaj przerwy dla nagrań to „pełna przerwa” (ustawienie połączenia dotyczy wykresu na żywo).

- Wykres: pasy na sygnał (wysokość wg „Share”, jak w programie) albo układ offset, etykiety osi w kolorze pasa, znacznik poziomu sygnału (H), oś czasu zegarowa z offsetem, przybliżanie i przesuwanie, pasek przeglądowy,
  „Punkty” (p. 6). **Różnice:** w osi „Względna” przeglądarka nie rysuje wartości (tylko „−N s … teraz”) i ignoruje offset; zegar serwera pokazywany jest w strefie czasowej serwera; przybliżanie kółkiem wymaga Ctrl (zwykłe kółko przewija stronę); zakres przesuwania na żywo ogranicza to, co strona zebrała od otwarcia
  wykresu; wyboru układu / punktów w pasku wykresu nie pamięta serwer (wartości domyślne są w konfiguracji połączenia); brak przeciągania legendy, motywów i profili kolorów interfejsu
  (wygląd linii znaczników jest pamiętany na koncie – `prefs\`, p. 19.2).
- Diagnostyka w przeglądarce (p. 6) pokazuje to samo co okno programu okienkowego, ale **bez wykresów opóźnień, bez zapisu raportu i bez ciągłego pingu** (jeden ping na żądanie, z serwera);
  nie ma też czasu sterownika odczytywanego na żądanie (jest z chwili połączenia) ani usuwania / dosyłania zaległych buforów. Brak importu symboli TIA, edycji formatu wyświetlania wartości, wzmocnienia i offsetu (zachowywane, ale
  nieedytowalne), wartości bieżących w tabeli sygnałów, edycji sygnałów **w trakcie** pracy połączenia (w programie okienkowym można dodać sygnał w locie).
- REC: brak pytania o nazwę „na początku / na końcu” (nazwa przy starcie lub w trakcie); parametry czasowe baz tylko przez plik celu.
- Nagrania w CSV nie mają przeglądu w przeglądarce (lista + pobranie w „Plikach”).
- Wspólne połączenia serwera są rozliczane jako „uruchomione przez” osobę, która nacisnęła Start; wszyscy operatorzy mogą je zatrzymać.
- Serwer jest **jedną instancją**: brak klastra, brak przełączania awaryjnego; jego awaria = brak akwizycji i nagrywania do czasu restartu
  (z `--autostart` połączenia wracają same, ale nagranie trzeba włączyć ponownie).
- Połączenia nie wznawiają się same po restarcie bez `--autostart`; REC nigdy nie wznawia się samo.
- Czasy w tabelach pokazuje przeglądarka w strefie czasowej użytkownika; znaczniki czasu nagrań w bazach to mikrosekundy epoki Unix (jak w programie okienkowym).
- Wydajność: przy wielu równoległych wykresach i szybkich cyklach obciążenie rośnie z liczbą otwartych strumieni (każdy to osobny wątek serwera i
  JSON ~10×/s). Nie zmierzono granicy – patrz p. 17.

---

## 16. Co zostało sprawdzone

### 16.1. Testy automatyczne (40 testów webowych w 4 plikach; cały zestaw projektu: 343 testy przechodzą + 1 pominięty; jeden test z poprzednich prac, `tests/test_diag.py::test_process_acquirer_collects_diagnostics`, bywa niestabilny w pełnych przebiegach przy dużym obciążeniu – nie dotyczy trybu Web)
Uruchomienie: `.venv\Scripts\python -m pytest tests/test_web.py tests/test_web_rec.py tests/test_web_recordings.py tests/test_web_more.py -q`.
Testy używają prawdziwego serwera HTTP na porcie losowym i symulatora PLC snap7 (`s7trace.sim`), z `urllib/http.client` jako przeglądarką.

| Plik | Co jest sprawdzone |
|---|---|
| `test_web.py` (19) | haszowanie haseł, role, blokada po błędach, ostatni administrator, konta Windows (z podstawionym sprawdzaniem hasła), pliki statyczne i zabezpieczenie przed `..`, konfiguracja pierwszego administratora, nagłówek CSRF, zarządzanie kontami i role, lista sesji, dane urządzenia w przeglądzie, start/stop prawdziwego połączenia z symulatorem, strumień SSE i śledzenie oglądających, walidacja edycji, przestrzenie kont (widoczność, 404 dla cudzych, wspólne, zapis i odczyt po restarcie, limity, nie edytowanie w trakcie pracy), certyfikat samopodpisany, `--add-user` |
| `test_web_rec.py` (11) | szablony i ścieżki plików, bezpieczeństwo ścieżek, cele zapisu (sekrety, walidacja), edycja wyzwalacza i REC, wyzwalacz z pauzą i zapisem CSV na prawdziwych próbkach (zawartość pliku, ponowne uzbrojenie), akcja bez pauzy, REC do CSV (zawartość), REC kończący się z połączeniem, REC do SQLite z właścicielem/komputerem/tytułem, nieznany cel, pełny przepływ HTTP (start/stop REC, trigger, pliki, pobranie, usunięcie, brak dostępu innych) i cele zapisu przez HTTP |
| `test_web_recordings.py` (5) | własny plik: lista, odczyt z przerzedzaniem i zakresem, CSV, edycja, kosz, przywracanie, usuwanie trwałe; rozdzielenie kont; widok administratora; wspólny plik i rola „podgląd”; reguły celów (widoczność, zmiana cudzych); sprzątanie kosza |
| `test_web_more.py` (5) | kreator na symulatorze (i na martwym porcie, walidacja, uprawnienia), tokeny i zgłoszenia programów, reporter i ostrzeżenie przed Startem (`sessions.REMOTE`), **logowanie SSO przez prawdziwe SSPI tego komputera** (konto niezarejestrowane → 403, zarejestrowane → sesja z rolą, zablokowane → 403, bez nagłówka → 403), dopasowanie nazw kont |

### 16.2. Sprawdzone ręcznie w przeglądarce (wbudowana przeglądarka, serwer + symulator)
Założenie pierwszego administratora, logowanie/wylogowanie, tworzenie połączenia w edytorze, Start, wykres na żywo, blokada pól strukturalnych przy działającym
połączeniu, trigger „rising edge” z „Pauza + zapis CSV” (zamrożone okno, linia „T”, „Wznów”), REC do CSV i do SQLite, lista plików, strona „Cele zapisu”,
przegląd nagrań (lista, wczytanie, przybliżanie, zmiana tytułu, kosz i przywracanie), kreator na symulatorze i „Zastosuj zalecenia”, tabela programów
okienkowych i kolumna „Uwagi” (reporter z osobnego procesu), komunikat błędu przy przycisku SSO.

### 16.3. Sprawdzone na paczce przenośnej
Z wnętrza paczki (osadzony Python 3.12) serwer uruchomił się z `--tls --sso`, wygenerował certyfikat i odpowiadał przez HTTPS (`/api/me`, `/`, `/static/app.js`).

---

## 17. Co trzeba sprawdzić na prawdziwym sprzęcie (nie było możliwe na komputerze deweloperskim)

Kolejność wg ryzyka:

1. **Prawdziwy sterownik** (S7-1200/1500, S7-300/400): start połączenia, odczyt wszystkich typów (REAL, DINT…), zachowanie przy utracie sieci (ponawianie),
   kreator na prawdziwym urządzeniu (OPC UA / Web API / Modbus wymagają realnych serwerów), poprawność nazwy stacji/modułu w tabeli.
2. **Prawdziwe bazy:** TimescaleDB (z rozszerzeniem: kompresja, usuwanie z skompresowanych chunków), PostgreSQL ze sterownikiem `psycopg`/`pg8000` w paczce na
   Windows Server 2016, InfluxDB 1.x i 2.x. Do tego służą `Test-TimescaleDB.bat` i `Test-InfluxDB.bat` z paczki oraz przycisk „Test” w „Cele zapisu”
   (w testach te bazy działają tylko na atrapach lub były sprawdzane wcześniej wyłącznie na lokalnym PostgreSQL bez rozszerzenia).
3. **SSO i konta Windows/AD na domenie:** logowanie hasłem konta domenowego (`LogonUserW`), SSO przeglądarką (Kerberos z SPN usługi, strefa Intranet,
   Edge/Chrome/Firefox). Test SSO przeszedł tylko na koncie lokalnym przez NTLM; wbudowana przeglądarka narzędzi nie wysyła poświadczeń, więc przycisk w przeglądarce
   nie był przetestowany końcowo.
4. **Praca wielu komputerów naraz:** kilku użytkowników z różnych komputerów, wiele równoległych wykresów, zachowanie sesji, blokady po błędach z różnych adresów.
5. **Zgłaszanie sesji z prawdziwych programów okienkowych na dwóch komputerach** (token, ostrzeżenie przed Startem, zachowanie przy utracie sieci do serwera).
6. **TLS w przeglądarkach i zaporze:** ostrzeżenia o certyfikacie, własny certyfikat firmowy, dostęp przez port 8080 przy włączonej Zaporze Windows.
7. **Windows Server 2016** (docelowy serwer): start `Web-Serwer.bat`, SSPI, certyfikaty, polskie znaki w nazwach, ścieżki w profilu użytkownika serwisowego
   (folder danych w jego Dokumentach – warto wskazać `--data` na stały folder).
8. **Wydajność i długotrwałość:** ile wykresów i połączeń jednocześnie, szybkie cykle (≤ 25 ms) z wieloma przeglądającymi, wielogodzinne nagrania do baz,
   zużycie pamięci bufora przy wielu połączeniach.
9. **Uprawnienia plików:** czy folder danych (z hasłami w `web_targets.json`) jest dostępny tylko dla konta serwisowego.

---

## 18. Dodatek: skrót API (dla integracji i testów)

Wszystkie odpowiedzi to JSON (poza plikami CSV, strumieniem SSE i plikami statycznymi). POST wymaga nagłówka `X-S7Trace: 1` i ciasteczka sesji
(poza `/api/agent/report`, który zamiast sesji używa nagłówka `X-S7Trace-Agent: <token>`). Błędy: `{"error": "komunikat po polsku"}` z kodem 400/401/403/404.

| Metoda i ścieżka | Rola | Działanie |
|---|---|---|
| GET `/`, `/static/*` | – | strona i zasoby |
| GET `/api/me` | – | kim jestem; przy braku sesji: `first_run`, `sso` |
| POST `/api/setup` | – (tylko przy 0 kont) | pierwszy administrator + zalogowanie |
| POST `/api/login`, `/api/logout` | – | logowanie (konto programu lub Windows z hasłem), wylogowanie |
| GET `/api/sso` | – (+ nagłówek) | Negotiate (SSPI); tylko z `--sso` |
| GET `/api/overview` | podgląd | połączenia (widoczne dla mnie), sesje, programy okienkowe, kolumna „others” |
| GET `/api/options` | podgląd | listy do edytora nowego połączenia |
| POST `/api/connections` | operator | utworzenie połączenia w mojej przestrzeni |
| GET `/api/connections/<id>` | podgląd | opis połączenia (stan, urządzenie, trigger, REC) |
| GET `/api/connections/<id>/config` | edycja | pełna konfiguracja do edytora |
| POST `/api/connections/<id>/config` | edycja | zmiana konfiguracji (walidacja „wszystko albo nic”) |
| POST `/api/connections/<id>/delete` | edycja | usunięcie (tylko zatrzymane) |
| POST `/api/connections/<id>/start`, `/stop` | operator (uruchamianie) | start/stop |
| POST `/api/connections/<id>/trigger` | operator | `{"action":"rearm"}` |
| POST `/api/connections/<id>/reset` | operator | `{}` = Reset (czyści bufor połączenia); `{"auto": true|false}` = Auto-Reset (zapisane w konfiguracji połączenia) |
| POST `/api/connections/<id>/rec` | operator | `{"action":"start"|"stop"|"info", "title":…}` |
| GET `/api/connections/<id>/series` | podgląd | dane: `seconds`, `since`, albo `from`+`to` |
| GET `/api/connections/<id>/stream` | podgląd | strumień SSE (`seconds`) |
| GET `/api/connections/<id>/diag` | podgląd | diagnostyka: ocena łącza, statystyki, tabela sterownika, czas PLC, kto jeszcze skanuje, (admin) bufory zapisu; `?ping=1` – jeden ping |
| GET `/api/help`, `/api/version` | – | teksty trybu pomocy; autor / wersja / data programu |
| GET/POST `/api/prefs` | podgląd | ustawienia interfejsu konta (`marker_look`), walidowane i zapisywane per konto |
| GET `/api/connections/<id>/files[/<rodzaj>/<nazwa>]` | podgląd | lista / pobranie pliku CSV konta |
| POST `/api/connections/<id>/files` | edycja | usunięcie pliku |
| GET `/api/recordings/sources`, `/api/recordings`, `/api/recordings/data`, `/api/recordings/csv` | podgląd | źródła, lista, odczyt, CSV |
| POST `/api/recordings` | operator | `update` / `trash` / `restore` / `purge` |
| GET/POST `/api/targets` | podgląd (lista) / admin (zmiany, test) | cele zapisu |
| GET `/api/markers` | podgląd | lista znaczników widocznych dla konta (filtry: `q`, `from`, `to`, `color`, `priority`, `author`, `group`, `conn`, `rec`, `order`, `limit`) + grupy i autorzy |
| POST `/api/markers` | operator | `add` / `update` / `delete` / `group` / `rename_group` / **`batch`** (zapis roboczych zmian jedną transakcją) |
| POST `/api/search` | podgląd | wyszukiwarka wartości w pamięci połączenia (`conn`) albo w nagraniu (`source`, `id`) |
| POST `/api/detect` | operator | kreator połączenia |
| GET/POST `/api/users` | admin | konta |
| GET/POST `/api/agent-tokens` | admin | tokeny programów okienkowych |
| POST `/api/agent/report` | token programu | zgłoszenie sesji programu okienkowego |

Kod: `s7trace/web/` (`server.py` – HTTP, `auth.py` – konta, `hosted.py` – połączenia/trigger/REC, `editing.py` – walidacja, `files.py`, `targets.py`,
`recordings.py`, `agents.py`, `sso.py`, `static/` – strona), strona programu okienkowego: `s7trace/core/web_agent.py`, `s7trace/ui/web_server_dialog.py`.

---

## 19. Znaczniki na wykresach i wyszukiwarka wartości

Ta sama funkcja istnieje w programie okienkowym (menu „Znaczniki” i rząd przycisków „Znaczniki:” pod wykresem) i w przeglądarce; oba korzystają z tego samego
modelu (`core/markers.py`, `core/marker_draft.py`, `core/search.py`), ale **mają osobne bazy**: program okienkowy – `Dokumenty\S7Trace\markers.db`
(konto Windows), serwer Web – `web_markers.db` w folderze danych serwera. Znaczniki nie leżą w nagraniach, więc kasowanie nagrania ich nie usuwa.

### 19.1. Znacznik

Pola: tytuł, opis, uwagi, kolor, priorytet (niski … krytyczny), **autor**, data założenia, data modyfikacji i kto zmienił, rodzaj (**punkt** albo
**zakres czasu**), lista przebiegów (pusta = wszystkie), grupa, grubość linii (0 = wg priorytetu), rodzaj linii (ciągła / kreskowana / kropkowana /
kreska-kropka), przezroczystość obszaru (tylko zakres), „pokazuj nazwę na wykresie”. Czas jest bezwzględny (mikrosekundy epoki), więc znacznik pasuje do
wykresu na żywo i do nagrania w bazie; znacznik założony na nagraniu zapamiętuje jego identyfikator (`źródło|id`), a założony na wykresie na żywo – połączenie.

### 19.2. Obsługa na wykresie (Podgląd na żywo i Nagrania)

- **Prawy przycisk na wykresie** – dodanie punktu albo zakresu czasu w tym miejscu (zakres: początek + 10 % widoku; można zmienić w oknie znacznika).
- **Najechanie myszą** na znacznik – dymek z tytułem, czasem, priorytetem, przebiegami, opisem, uwagami, autorem i datami.
- **Prawy przycisk na znaczniku** – menu: edycja (albo „Szczegóły”, gdy nie wolno edytować), zmiana pozycji (znacznik się podświetla, klik w nowe miejsce),
  ukrycie / pokazanie nazwy na wykresie, grupy (dodaj / przenieś / usuń z grupy, podświetl grupę, następny i poprzedni znacznik grupy, zmiana nazwy grupy),
  cofnięcie niezapisanej zmiany, usunięcie.
- Menu prawego przycisku zawiera też: **„Dodaj znacznik różnicy poziomu…”** (znacznik „Różnica sygnału” dla pasa pod kliknięciem: poziom na obu końcach, strzałka i Δ wartości), „Lista znaczników…” (lista z zakresem bieżącego połączenia), „Szukaj w danych…” oraz – na wykresie na żywo – przełącznik **„Pokaż też znaczniki z innych połączeń”**. Znacznik jest domyślnie **zablokowany** (przeciągnięcie przesuwa wykres); „Zmień pozycję znacznika” w jego menu (✓ = odblokowany, ponowny wybór blokuje) pozwala go przeciągać.
- **Skróty klawiszowe** (gdy jest otwarty wykres lub lista): Ctrl+M – lista znaczników, Ctrl+Shift+M – dodaj znacznik teraz (na żywo), Ctrl+Shift+S – zapisz znaczniki, Ctrl+F – wyszukiwarka danych (zastępuje wyszukiwanie przeglądarki tylko na tych stronach).
- **Dwuklik na znaczniku** – okno edycji (albo szczegółów, gdy nie wolno edytować).
- **Przeciąganie myszą** – punkt przesuwa się w całości, zakres można chwycić za brzeg albo za wnętrze.
- **Podświetlenie po najechaniu** – linia (punktu albo brzegu zakresu – ten sam standard) robi się grubsza i zachowuje kolor znacznika.
- **Dymek**: czas zakresu jako „Od:” i „Do:” jedno pod drugim (czcionka o stałej szerokości), potem Autor, Założono, Zmodyfikował, Zmieniono; pola zmienione od ostatniego zapisu są podświetlone na żółto.
- **Grubości linii** – przycisk „Wygląd znaczników…” (zakładka Znaczniki i menu wykresu): znacznik dla wszystkich przebiegów, wybrane przebiegi, cienka prowadnica przez pozostałe, linia podświetlona. Znacznik z własną grubością ją zachowuje (0 = wg ustawień; priorytet nie zmienia grubości). Ustawienia są pamiętane **na koncie, na serwerze** (`/api/prefs`, plik `prefs\u_<konto>.json`) – te same w każdej przeglądarce i na każdym komputerze; w programie okienkowym leżą w konfiguracji interfejsu (razem z plikiem „Zapisz konfigurację interfejsu”).
- Zakres jest półprzezroczystym obszarem koloru znacznika; znacznik dotyczący wybranych przebiegów rysuje się tylko w ich pasach.
- Zakładka **Znaczniki** – lista z wyszukiwaniem (tytuł, opis, uwagi, autor, grupa, przebieg), filtrami (priorytet, grupa, autor, **zakres: wszystkie połączenia / połączenie z wykresu**, zakres dat, kolejność; z wykresu lista otwiera się z zakresem jego połączenia – jak w programie, z menu – ze wszystkimi),
  przyciskami Pokaż / Edytuj / Usuń / Cofnij zmianę i grupowaniem zaznaczonych. „Pokaż” otwiera wykres, który zawiera znacznik (połączenie albo nagranie).

### 19.3. Zapis: znaczniki robocze

Znacznik założony, zmieniony albo usunięty na wykresie jest tylko **roboczy** (w stronie, oznaczony gwiazdką w nazwie i w dymku) – serwer o nim nie wie. Trwały
staje się dopiero po poleceniu **Zapisz znaczniki** (przycisk w nagłówku strony, w zakładce Znaczniki i w menu wykresu): okno wylicza „nowy / zmieniony
(z nazwami pól) / do usunięcia”, a po potwierdzeniu strona wysyła **jedną paczkę** (`POST /api/markers`, `{"action":"batch","adds":[…],"updates":[…],"deletes":[…]}`)
zapisywaną w jednej transakcji – albo wszystko, albo nic (sprawdzane są najpierw wszystkie prawa, potem poprawność pól; najwyżej 500 zmian naraz).
Przy **wyjściu z wykresu** (Podgląd na żywo / Nagrania → inna zakładka), **wylogowaniu** i zamknięciu karty przeglądarki (`beforeunload`) strona przypomina
o niezapisanych znacznikach i pokazuje ich wykaz (Zapisz / Odrzuć zmiany / Wróć do wykresu). Przypomnienie pojawia się też przy **zmianie połączenia** na wykresie na żywo, przy **wczytaniu innego nagrania** i przy zmianie źródła nagrań; wybór „Wróć”
zostawia wszystko bez zmian. Robocze znaczniki nie znikają same (licznik jest cały czas widoczny w nagłówku).

### 19.4. Kto co widzi i zmienia

- Znacznik widzą: jego autor, administratorzy oraz – gdy założono go na **wspólnym** połączeniu serwera – wszyscy, którzy mogą to połączenie oglądać.
- Zakładają operatorzy i administratorzy (rola „podgląd” tylko czyta); zmieniać i usuwać może autor i administrator.
- Autor, daty i połączenie są nadawane przez serwer (nie da się ich podmienić z przeglądarki). Limit: 20 000 znaczników na konto.

### 19.5. Wyszukiwarka wartości

W Podglądzie na żywo (sekcja „Wyszukiwarka danych”) i w Nagraniach (sekcja „Wyszukiwarka w tym nagraniu”): do 3 warunków naraz (**i**) na sygnałach:
`==` / `!=` (z tolerancją), `>`, `≥`, `<`, `≤`, w przedziale, poza przedziałem, **zmienia wartość**, **zbocze narastające / opadające**, brak wartości; opcjonalnie
minimalny czas trwania. Wynik: początek, czas trwania (albo „zdarzenie” dla zmian i zboczy), wartości na początku, min…maks (najwyżej 5000 wyników, w tabeli
pierwsze 500). „Pokaż” ustawia wykres na wynik (na żywo: zamrożony widok z przyciskiem powrotu), „Dodaj znacznik…” zakłada roboczy znacznik (zakres, gdy wynik
trwał) z listą przebiegów z warunków. W nagraniu serwer przeszukuje bazę kawałkami (przy zbyt dużym kawałku dzieli go na pół), a przy limicie czasu zwraca wynik
częściowy z adnotacją. Na górze panelu jest też **„Przejdź do daty i godziny”** (jak w programie okienkowym): na żywo pokazuje ten moment w danych zapamiętanych przez połączenie, w nagraniu – część nagrania wokół niego; poza danymi pojawia się komunikat.

### 19.6. Znaczniki REC: Start REC, Stop REC, Manual REC, zmiana początku nagrania

To samo, co w programie okienkowym (rozdział „Znaczniki REC” Pomocy), na wykresie **Podgląd na żywo**:

- **Start REC (n) / Stop REC (n)** – linie rysowane przez stronę w chwili włączenia i wyłączenia REC na serwerze (numer rośnie przy każdym kolejnym REC w przebiegu połączenia; nowy Start zaczyna od 1). Serwer podaje je w opisie połączenia
  (`rec.marks`: `n`, `t0`, `t1`, `db`) i w serii (`series.rec`). Nie są znacznikami zapisywanymi w bazie znaczników. Wygląd: **Wygląd znaczników…** – włączenie, kolor (początkowo kolor tła przycisku REC), grubość, rodzaj linii, nieprzezroczystość obszaru Manual REC;
  ustawienia są na koncie (`/api/prefs`, klucz `marker_look`: `rec_show`, `rec_color`, `rec_width`, `rec_style`, `rec_opacity`).
- **Manual REC** – prawy przycisk na pustym wykresie: „Manual Start REC (n) tutaj”, potem „Manual Stop REC (n) tutaj”; między liniami półprzezroczysty obszar. Obszary żyją w stronie (jak znaczniki robocze) do chwili zapisu: prawy przycisk na obszarze → **„Zapis Manual REC (n)”**
  albo przycisk **Zapisz znaczniki (n)** (okno wylicza obszary z polami wyboru). Menu „**Pokaż…**” (REC) i „**Pokaż znacznik…**” (zwykłe znaczniki widoczne na wykresie; do 40) przesuwa widok na wybrany znacznik (widok się zatrzymuje – „Na żywo” wraca do bieżących danych). **„Przenieś Manual REC (n)”** pokazuje pulsującego ducha linii początku (przeciągnij; prawy przycisk: „Przenieś … tutaj” / „Anuluj przenoszenie”); menu prawego przycisku jest pogrupowane separatorami. Ten sam, niezmieniony obszar zapisany po raz drugi wymaga potwierdzenia (identyczne nagranie); po zapisie menu obszaru kończy się pozycjami „zapisano: …” i **„Otwórz Manual REC (n): nagranie …”** (strona nagrań; odpowiedź `rec-range` zawiera `rec_id`, `a_us`, `b_us`). Między liniami **Start REC (n)** i **Stop REC (n)** rysowany jest półprzezroczysty obszar. Zapis = `POST /api/connections/<id>/rec-range` (`{a, b, title}`): serwer zapisuje ten przedział **swojego bufora** jako nowe nagranie w celu zapisu połączenia (plik CSV konta albo baza: SQLite konta / cel administratora).
  Obszary mają menu „Zmień pozycję” (przeciąganie brzegów) i „Usuń”.
- **Zmiana początku nagrania** – prawy przycisk na „Start REC (n)” → **„Przesuń Start REC (n)…”**: widok się zatrzymuje, a obok linii pojawia się pulsujący „duch”; po przeciągnięciu: prawy przycisk → **„Zmień Start REC (n)”** (`POST /api/connections/<id>/rec-start`, `{n, t}`).
  Wcześniej = brakujący fragment jest dopisywany do nagrania z bufora serwera; później = starsze dane są usuwane z bazy (po potwierdzeniu). Działa dla baz (SQLite, InfluxDB, TimescaleDB), także w trakcie nagrywania; dla plików CSV pozycja jest wyłączona.
  Ograniczenie: dane tylko tak daleko wstecz, jak sięga bufor serwera (to samo, co widać na wykresie).
- Testy: `tests/test_web_rec_marks.py` (serie, zapis zakresu, przesuwanie startu w trakcie nagrywania i po nim, CSV, prawa), `tests/test_rec_marks.py` (rdzeń: SQLite, InfluxDB 1/2 z atrapą serwera, TimescaleDB z atrapą psycopg). Strona sprawdzona ręcznie w wbudowanej przeglądarce (Chromium) na serwerze demonstracyjnym.

### 19.7. Do którego nagrania należy znacznik („Zapis”) i znaczniki tylko dla bufora

Jak w programie okienkowym (BAZY_DANYCH.md, rozdz. 13.12): znacznik założony na połączeniu na żywo dostaje od razu `rec_id` = `<źródło>|<id nagrania>` (serwer podstawia je w `/api/markers`, gdy czas znacznika
mieści się w REC tego połączenia; plik CSV: `csv|<nazwa>`; puste = tylko bufor). **Zapis Manual REC** i **Zmień Start REC** przenoszą znaczniki razem z danymi (`/rec-range`, `/rec-start`).
Lista znaczników ma kolumnę **Zapis**, filtr „Zapis” i przycisk **Usuń bez zapisu…** (znaczniki bez nagrania, których połączenie nie ma już danych w pamięci). `GET /api/markers?norec=1` zwraca tylko takie znaczniki,
każdy znacznik ma pole `buffered`. Przeglądarka pyta przed **Start** połączenia (OK = usuń znaczniki z bufora, który zostanie wyczyszczony; Anuluj = zostaw) i przed trwałym usunięciem nagrania (`Usuń trwale` albo `Usuń` przy wyłączonym koszu).
Różnica wobec programu okienkowego: okno `confirm` ma dwa przyciski, więc pytania nie da się użyć do przerwania Start; w Web nie ma też „zamykania karty” – bufor trzyma serwer, dopóki połączenie nie wystartuje ponownie.
Testy: `tests/test_web_marker_rec.py`.

### 19.8. Co zostało sprawdzone / czego nie

- Testy automatyczne: `tests/test_markers.py`, `tests/test_marker_draft.py`, `tests/test_markers_ui.py` (offscreen), `tests/test_web_markers.py` (prawdziwy serwer HTTP:
  widoczność, role, zakresy, grupy, style, walidacja, paczka `batch` – atomowość i prawa, wyszukiwarka w połączeniu i w nagraniu).
- Strona obsłużona ręcznie w wbudowanej przeglądarce (Chromium): dodanie / edycja / usunięcie roboczego znacznika, okno zapisu, zapis paczką, przypomnienie przy
  wyjściu, widok listy z oznaczeniem stanu. **Nie sprawdzono** w Edge / Firefox / Safari ani na ekranach dotykowych (przeciąganie myszą jest zdarzeniami `mouse*`).
- Wyszukiwarka w bazach sieciowych (InfluxDB, TimescaleDB) działa przez te same funkcje odczytu co przegląd nagrań; testowana była tylko SQLite i atrapy serwerów.
