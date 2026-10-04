# Tryb Web (etap 1)

Centralny serwer S7Trace: **jeden komputer** trzyma połączenia ze sterownikami (odczyt w osobnym procesie, jak w programie
okienkowym), a **wielu użytkowników** loguje się do niego przeglądarką z innych komputerów. Etap 1 to: logowanie, przegląd
kto jest zalogowany i jakie są połączenia, podgląd wykresu na żywo, Start/Stop połączeń i zarządzanie kontami.

## Uruchomienie

Z paczki: `Web-Serwer.bat [plik_konfiguracji.json]` (nasłuch na wszystkich interfejsach, HTTPS z certyfikatem samopodpisanym).
Z kodu (`.venv`):

```
.venv\Scripts\python -m s7trace.web --config <konfiguracja.json> [--host 0.0.0.0] [--port 8080] [--data <folder>] [--tls] [--autostart]
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

## Co widać na stronie „Przegląd”

- **Połączenia i sterowniki:** nazwa, adres IP, rack/slot, stan, rodzina i model CPU z firmware, nazwa stacji, nazwa modułu,
  metoda (S7comm / OPC UA / Web API / Modbus), kto uruchomił i kiedy, kto aktualnie ogląda.
- **Zalogowani użytkownicy:** konto, rodzaj konta, rola, adres komputera, przeglądarka, od kiedy zalogowany, bezczynność,
  które połączenie ogląda.

## Bezpieczeństwo (w skrócie)

Ciasteczko sesji `HttpOnly; SameSite=Strict` (+ `Secure` przy TLS), każdy POST wymaga nagłówka `X-S7Trace: 1` (ochrona przed
CSRF), sesja wygasa po 8 h bezczynności. Serwer używa tylko biblioteki standardowej (`http.server`, Server-Sent Events).

## Czego jeszcze nie ma / co nie było sprawdzone

- Zweryfikowane: testy (`tests/test_web.py`, symulator snap7) i ręcznie w przeglądarce (logowanie, przegląd, Start/Stop,
  wykres, użytkownicy).
- **Nie sprawdzone:** logowanie kontem Windows/AD na prawdziwej domenie, praca z wielu komputerów naraz, certyfikat TLS
  w różnych przeglądarkach, Windows Server 2016.
- Etapy późniejsze: edycja sygnałów / wyzwalacza / REC i nagrań z przeglądarki, kreator połączeń, zgłaszanie sesji
  programu okienkowego do serwera (wspólny rejestr, ostrzeżenie o skanowaniu tego samego sterownika z innego komputera).
