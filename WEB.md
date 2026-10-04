# Tryb Web (etapy 1, 2a, 2b, 2c i 3)

Centralny serwer S7Trace: **jeden komputer** trzyma połączenia ze sterownikami (odczyt w osobnym procesie, jak w programie
okienkowym), a **wielu użytkowników** loguje się do niego przeglądarką z innych komputerów. Etap 1: logowanie, przegląd
kto jest zalogowany i jakie są połączenia, podgląd wykresu na żywo, Start/Stop połączeń i zarządzanie kontami.
Etap 2a: **własna przestrzeń każdego konta** i edycja połączeń oraz sygnałów w przeglądarce.
Etap 2b: **wyzwalacz i REC** (CSV, SQLite, bazy z listy administratora) oraz pliki konta.
Etap 2c: **przegląd nagrań z baz** (lista, wykres z przybliżaniem, CSV, opis, kosz).
Etap 3: **kreator połączenia**, **rejestr programów okienkowych** z ostrzeżeniami o skanowaniu tego samego sterownika, **logowanie SSO**.

## Uruchomienie

Z paczki: `Web-Serwer.bat [plik_konfiguracji.json]` (nasłuch na wszystkich interfejsach, HTTPS z certyfikatem samopodpisanym).
Z kodu (`.venv`):

```
.venv\Scripts\python -m s7trace.web --config <konfiguracja.json> [--host 0.0.0.0] [--port 8080] [--data <folder>] [--tls] [--sso] [--autostart]
.venv\Scripts\python -m s7trace.web --add-user admin        # dodaje administratora (hasło pytane w konsoli) i kończy
```

- `--config` – zwykły plik konfiguracji S7Trace (z `%APPDATA%\S7Trace` albo zapisany z programu); **każda zakładka = jedno
  połączenie** na serwerze. Można podać kilka razy.
- `--host` – domyślnie `127.0.0.1` (tylko ten komputer). `0.0.0.0` udostępnia serwer w sieci – wtedy używaj `--tls`
  (albo własnego `--cert`/`--key`), bo inaczej hasła idą otwartym tekstem.
- `--data` – konta (`web_users.db`) i certyfikat; domyślnie `<Dokumenty>\S7Trace\web`.
- `--autostart` – uruchamia wszystkie połączenia od razu.

Przy pierwszym wejściu w przeglądarce (nie ma jeszcze kont) strona prosi o utworzenie pierwszego administratora.

## Konta i role

| Rola | Co może |
|---|---|
| podgląd (viewer) | przegląd, wykres na żywo |
| operator | + Start / Stop połączeń |
| administrator | + zakładka „Użytkownicy” (dodawanie, role, blokowanie, hasła, usuwanie) |

Dwa rodzaje kont: **konto programu** (hasło zapisane jako PBKDF2-SHA256, 200 tys. iteracji) i **konto Windows / Active
Directory** (`DOMENA\jan`, `jan@domena`, albo samo `jan` = konto lokalne serwera) – hasło sprawdza sam Windows
(`LogonUserW`), serwer go nie zapisuje; konto musi być wcześniej dodane przez administratora (to ono dostaje rolę).
Po 5 błędnych hasłach para (konto, adres) jest blokowana na 60 s. Nie da się usunąć / zablokować / zdegradować ostatniego
administratora.

## Własna przestrzeń konta (etap 2a)

Każde konto ma na serwerze swoje połączenia (odpowiednik zakładek programu okienkowego), zapisane osobno w
`<folder danych>\workspaces\u_<konto>.json`. Połączenia bez właściciela (z `--config`, plik `_shared.json`) są **wspólne**.

| Kto | Widzi | Edytuje | Start / Stop |
|---|---|---|---|
| podgląd | wspólne | nic | nic |
| operator | swoje + wspólne | swoje | swoje + wspólne |
| administrator | wszystkie | wszystkie | wszystkie |

- „+ Nowe połączenie” i „Edytuj” (strona Przegląd): nazwa, adres IP (ew. `:port`), rack, slot, cykl, okno czasu, sposób
  połączenia (S7 / OPC UA / Web API / Modbus), tryb odczytu oraz tabela sygnałów (nazwa, źródło, typ, DB, bajt, bit,
  węzeł, share, kolor, pobieraj, wykres, opis). Pola, których tabela nie pokazuje (wzmocnienie, offset, format), zostają bez zmian.
- Zmiany adresu, cyklu, trybu i sygnałów są możliwe tylko przy zatrzymanym połączeniu; nazwę i okno czasu można zmienić zawsze.
  Połączenie można usunąć tylko zatrzymane. Limit: 30 połączeń na konto, 200 sygnałów na połączenie.
- Serwer sprawdza każdą wartość (typy, zakresy, długości, unikalność nazw sygnałów); odrzucona zmiana nie zmienia nic.
  Hasła do OPC UA / Web API nigdy nie wracają do przeglądarki; zapisują się na serwerze tylko przy „zapamiętaj hasło”.
  Ścieżki certyfikatów na serwerze (`cert`, `key`) przeglądarka nie ustawia.
- Po usunięciu konta jego połączenia zostają w pliku (widzi je administrator).

## Wyzwalacz i REC w przeglądarce (etap 2b)

Ustawienia w edytorze połączenia (sekcje „Wyzwalacz” i „REC”), obsługa na stronie „Podgląd na żywo”. Działają na serwerze, więc
nie zależą od otwartej przeglądarki: wyzwalacz i nagrywanie trwają, gdy użytkownik zamknie kartę.

- **Wyzwalacz** – ta sama maszyna stanów co w programie okienkowym (warunki `==`, `>`, `<`, `between`, zbocza; histereza,
  przedtrigger, akcje „Pauza”, „Zapis CSV”, „Pauza + zapis CSV”). Przy „Pauza” wykres wszystkich przeglądających zamraża okno
  wokół wyzwolenia (czerwona przerywana linia „T”) do przycisku „Wznów (uzbrój wyzwalacz)”. Zapis CSV trafia do folderu konta
  (`<folder danych>\files\u_<konto>\snapshots`). Wyzwalacz można zmieniać także przy działającym połączeniu.
- **REC** – przycisk „● REC / ■ Stop REC” (operator i administrator); nagrywanie kończy się też samo przy zatrzymaniu połączenia.
  Cele zapisu: **csv** (plik w `...\u_<konto>\rec`), **sqlite** (plik `recordings.db` w folderze konta) oraz **cele z listy
  administratora** (TimescaleDB, InfluxDB 1.x / 2.x, wspólny SQLite). Tryb „tylko zmiany” / „wszystkie próbki”, szablon nazwy pliku
  CSV, nazwa i uwagi nagrania (przy celach bazodanowych, pole obok przycisku REC). Nagranie w bazie ma właściciela = konto
  w przeglądarce i komputer „Web <adres klienta>”. Ustawień REC nie da się zmienić w trakcie nagrywania.
- **Pliki** – przycisk „Pliki” pokazuje CSV konta (zapisy triggera i nagrania do CSV): pobieranie, a dla właściciela / administratora
  usuwanie. Przeglądarka nie wybiera ścieżek, tylko szablon nazwy ({confname} {ip} {tab} {date} {time}, bez `\ / : * ? " < > |`);
  pliki innych kont są niedostępne.
- **Cele zapisu (administrator)** – zakładka „Cele zapisu”: nazwa, rodzaj i parametry bazy (adres, baza, użytkownik, hasło / token,
  kompresja TimescaleDB…), przycisk „Test”. Hasła i tokeny zostają na serwerze (`web_targets.json` w folderze danych – chroń ten
  folder uprawnieniami systemu) i nigdy nie wracają do przeglądarki; użytkownik widzi tylko nazwę i opis celu.

## Przegląd nagrań w przeglądarce (etap 2c)

Zakładka „Nagrania” (dla każdego zalogowanego) pokazuje nagrania zapisane w bazach – odpowiednik okna „Przegląd nagrań” programu
okienkowego.

- **Źródła:** „Moje nagrania” (plik SQLite konta – cel REC `sqlite`), „Wspólne połączenia” (SQLite wspólnych połączeń; widoczne
  dla wszystkich), cele z listy administratora, a dla administratora także pliki SQLite innych kont.
- **Kto co widzi i zmienia:** we własnym pliku wszystko. We wspólnym pliku i w celach bazodanowych administrator widzi i zmienia
  wszystko; pozostali widzą swoje nagrania (albo wszystkie, gdy administrator ustawi cel na „wszyscy widzą wszystkie”) i zmieniają
  swoje (albo cudze, gdy cel ma „zmieniać cudze nagrania”). Rola „podgląd” tylko czyta. Nagrania, które właśnie trwają, nie
  da się zmienić ani usunąć.
- **Lista:** tytuł, uwagi, start, czas trwania, właściciel, komputer, połączenie, sygnały, tagi; wyszukiwanie po wszystkim naraz.
- **Wczytaj:** wykres z pasami (jak na żywo), długie nagrania są zmniejszane do ok. 6000 punktów metodą min/maks (szczyty nie
  znikają); przeciągnięcie myszą po wykresie przybliża wybrany zakres, „Cały przebieg” wraca. **CSV** pobiera każdy wiersz
  nagrania albo widocznego zakresu (format jak w programie okienkowym, da się go wczytać w programie).
- **Opis:** tytuł, uwagi, tagi. **Kosz:** „Do kosza” → zakładka „kosz” → „Przywróć” / „Usuń trwale”; kosz opróżnia się sam po
  `Kosz: dni` celu (domyślnie 30), a „Auto-kosz” celu przenosi własne stare nagrania do kosza. Przy `Kosz: 0` usuwanie jest od razu.
- Ustawienia widoczności, kosza i auto-kosza ma formularz celu w zakładce „Cele zapisu”.

## Kreator, rejestr programów okienkowych, logowanie SSO (etap 3)

- **Kreator połączenia** – w edytorze przycisk „Kreator: rozpoznaj sterownik”: serwer sprawdza adres (ping, port, S7comm, OPC UA,
  Web API, Modbus – albo tylko wybraną metodę), pokazuje raport i zalecenie; „Zastosuj zalecenia” ustawia sposób połączenia,
  rack, slot i (gdy puste) nazwę połączenia. Dostępny dla operatora i administratora (serwer łączy się z podanym adresem, więc
  nie dawaj tej roli komuś, komu nie ufasz w sieci); jedno rozpoznawanie naraz na konto.
- **Rejestr programów okienkowych** – administrator tworzy na stronie „Użytkownicy” **token programu**. W programie okienkowym
  Ustawienia → „Serwer Web (zgłaszanie sesji i wspólny rejestr)…”: adres serwera, token, „Test połączenia”. Program co ok. 5 s
  zgłasza serwerowi: Windows-użytkownika, komputer i swoje karty (adres sterownika, stan). Strona „Przegląd” pokazuje tabelę
  „Programy okienkowe zgłoszone do serwera”, a przy połączeniu serwera kolumnę „Uwagi” („także: jan (PC-HALA)”), gdy ten sam
  sterownik skanuje program okienkowy. W drugą stronę program przed Startem ostrzega, gdy sterownik skanuje ktoś na innym komputerze
  albo połączenie serwera (to samo okno ostrzeżenia co dla innego użytkownika tego komputera). Serwer niedostępny = program działa
  bez zmian i bez ostrzeżeń z serwera. Token jest tajemnicą (zapisany w konfiguracji programu użytkownika; na serwerze tylko
  jego skrót); „Sprawdzaj certyfikat” odznacz tylko przy certyfikacie samopodpisanym.
- **Logowanie SSO kontem Windows** – serwer uruchomiony z `--sso` (tylko Windows; `Web-Serwer.bat` ma tę opcję) pokazuje na stronie
  logowania przycisk „Zaloguj kontem Windows (SSO)”. Przeglądarka przesyła konto przez Negotiate (Kerberos / NTLM, SSPI), hasło nie
  przechodzi przez serwer. Konto musi być wcześniej dodane przez administratora (rodzaj „konto Windows / AD”, np. `DOMENA\jan`;
  dla konta lokalnego serwera można podać samo `jan`) – stamtąd bierze się rola. Zablokowane lub niezarejestrowane konto dostaje
  czytelny komunikat. Przeglądarka musi chcieć wysłać poświadczenia: adres serwera w strefie „Intranet” (Edge / Chrome) albo
  zezwolenie na uwierzytelnianie zintegrowane; przy zwykłej nazwie komputera (bez kropek) zwykle działa od razu.

## Co widać na stronie „Przegląd”

- **Połączenia i sterowniki:** nazwa, adres IP, rack/slot, stan, rodzina i model CPU z firmware, nazwa stacji, nazwa modułu,
  metoda (S7comm / OPC UA / Web API / Modbus), kto uruchomił i kiedy, kto aktualnie ogląda.
- **Zalogowani użytkownicy:** konto, rodzaj konta, rola, adres komputera, przeglądarka, od kiedy zalogowany, bezczynność,
  które połączenie ogląda.

## Bezpieczeństwo (w skrócie)

Ciasteczko sesji `HttpOnly; SameSite=Strict` (+ `Secure` przy TLS), każdy POST wymaga nagłówka `X-S7Trace: 1` (ochrona przed
CSRF), sesja wygasa po 8 h bezczynności. Serwer używa tylko biblioteki standardowej (`http.server`, Server-Sent Events).

## Czego jeszcze nie ma / co nie było sprawdzone

- Zweryfikowane: testy (`tests/test_web.py`, `tests/test_web_rec.py`, symulator snap7; bazy sieciowe tylko na atrapach / SQLite) i ręcznie w przeglądarce (logowanie, przegląd, Start/Stop,
  wykres, użytkownicy).
- **Nie sprawdzone:** logowanie kontem Windows/AD na prawdziwej domenie, praca z wielu komputerów naraz, certyfikat TLS
  w różnych przeglądarkach, Windows Server 2016.
- **SSO:** serwer i protokół sprawdzone testem z prawdziwym SSPI na tym komputerze (konto lokalne); NIE sprawdzone w prawdziwej
  przeglądarce z domeną Active Directory / Kerberos (wbudowana przeglądarka narzędzi testowych nie wysyła poświadczeń).
- Zgłaszanie sesji programu okienkowego: sprawdzone testem (serwer + reporter) i na stronie; nie sprawdzone na dwóch prawdziwych komputerach.
- Etapy późniejsze: brak zaplanowanych.
