"""Texts of the help mode ('?' button of every window): what an element is, what it is for, how to set it and the range. Keyed by the
visible caption of the element (normalised by `norm`), so the desktop program and the Web page share them (`/api/help`). Qt-free."""
from __future__ import annotations


def norm(text: str) -> str:
    t = (text or "").replace("&", "").replace(" ", " ").strip().lower()
    while t and t[-1] in ":….?":
        t = t[:-1].rstrip()
    return " ".join(t.split())


def _e(what: str, why: str, how: str = "", rng: str = "") -> str:
    parts = [("Co to jest", what), ("Do czego służy", why), ("Jak ustawić", how), ("Zakres", rng)]
    return "\n".join(f"{k}: {v}" for k, v in parts if v)


_RAW: dict[str, str] = {
    # ---- group boxes of the left panel
    "Połączenie": _e("Ustawienia połączenia ze sterownikiem.", "Wskazuje, z którym sterownikiem i jak program się łączy.", "Wpisz adres IP, rack i slot, cykl odczytu.", "Klik w tytuł zwija / rozwija pole."),
    "Sterownik": _e("Dane odczytane ze sterownika po połączeniu (rodzina, model, firmware, nazwa stacji…).", "Pozwala sprawdzić, z jakim urządzeniem pracujesz.", "Wypełniają się same po pierwszym połączeniu; pełna tabela: Diagnostyka → Informacje o sterowniku."),
    "Zakres okna wykresu": _e("Ustawienia widocznego okna czasu i osi Y.", "Decydują, ile czasu widać na wykresie i jak są skalowane krzywe.", "Wybierz okno czasu i układ osi Y."),
    "Trigger": _e("Wyzwalacz: warunek na jednym sygnale.", "Zatrzymuje wykres albo zapisuje plik, gdy sygnał spełni warunek.", "Włącz trigger, wybierz sygnał, tryb i wartości progowe."),
    "Nagrywanie REC": _e("Ustawienia nagrywania przebiegu do pliku lub bazy.", "Określają gdzie i jak zapisywane są próbki po naciśnięciu REC.", "Wybierz cel zapisu, folder i nazwę pliku oraz tryb próbek."),
    # ---- connection
    "IP": _e("Adres IPv4 sterownika (opcjonalnie :port).", "Do tego adresu program się łączy.", "Wpisz cztery liczby w kolejnych polach; lista rozwijana pamięta ostatnio używane adresy.", "0–255 w każdym polu; IPv6 i nazwy hostów nie są obsługiwane."),
    "Rack / Slot": _e("Numer szafy (rack) i gniazda (slot) procesora CPU w sterowniku.", "Jest potrzebny do połączenia S7comm.", "S7-300/400: rack 0, slot 2 (zwykle). S7-1200/1500: rack 0, slot 1. Przycisk „?” obok pokazuje wskazówki.", "Rack 0–7, slot 0–31."),
    "Rack": _e("Numer szafy sterownika.", "Część adresu połączenia S7comm.", "Zwykle 0.", "0–7"),
    "Slot": _e("Numer gniazda procesora CPU.", "Część adresu połączenia S7comm.", "S7-300/400: 2; S7-1200/1500: 1.", "0–31"),
    "Cykle [ms]": _e("Czas jednego cyklu odczytu.", "Co ile milisekund program pobiera próbkę ze sterownika.", "Mniejszy cykl = gęstsze próbki, ale większe obciążenie sieci i sterownika. Diagnostyka podpowiada bezpieczną wartość.", "1–60000 ms"),
    "Cykl [ms]": _e("Czas jednego cyklu odczytu.", "Co ile milisekund pobierana jest próbka ze sterownika.", "Mniejszy cykl = gęstsze próbki, większe obciążenie. Diagnostyka podpowiada bezpieczną wartość.", "5–60000 ms (Web)"),
    "Tryb komunik": _e("Sposób odczytu zmiennych: bloki (grupowane) albo pojedynczo.", "Wpływa na szybkość odczytu.", "Bloki grupowane są szybsze; pojedynczo – dla trudnych sterowników.", ""),
    "Tryb odczytu": _e("Sposób odczytu zmiennych: bloki (grupowane) albo pojedynczo.", "Wpływa na szybkość odczytu.", "Bloki grupowane są szybsze."),
    "Metoda": _e("Metoda komunikacji (S7comm, OPC UA, Web API, Modbus).", "Pokazuje, jakiego protokołu użyto.", "Zmiana: Ustawienia → Metoda połączenia… (domyślnie rozpoznawana automatycznie)."),
    "Sposób połączenia": _e("Protokół połączenia ze sterownikiem.", "Określa, jak program rozmawia ze sterownikiem.", "„auto” rozpoznaje na podstawie sygnałów; można wymusić S7, OPC UA, Web API, Modbus."),
    "Rodzina": _e("Rodzina sterowników (np. S7-300, S7-1500).", "Informacja o urządzeniu.", "Odczytywana automatycznie."),
    "Model": _e("Model procesora CPU.", "Informacja o urządzeniu.", "Odczytywany automatycznie."),
    "Firmware": _e("Wersja oprogramowania sterownika.", "Informacja o urządzeniu.", "Odczytywana automatycznie."),
    "Nazwa stacji": _e("Nazwa stacji z projektu sterownika.", "Pozwala rozpoznać sterownik w instalacji.", "Odczytywana automatycznie."),
    "Nazwa modułu": _e("Nazwa modułu CPU z projektu.", "Informacja o urządzeniu.", "Odczytywana automatycznie."),
    # ---- chart window
    "Okno czasu [s]": _e("Szerokość widocznego okna czasu.", "Ile sekund historii widać na wykresie na żywo.", "Wybierz z listy albo wpisz własną wartość; można też przybliżać kółkiem myszy.", "0,1 s – bufor (dziesiątki minut)."),
    "Układ osi Y": _e("Sposób rozmieszczenia krzywych.", "„Pasma wg Share”: każdy sygnał w swoim pasie, skala min…maks okna. „Offset”: wspólna oś Y, wartość × gain + offset.", "Wybierz z listy."),
    "Układ wykresu": _e("Sposób rozmieszczenia krzywych.", "„Pasma wg Share” – każdy sygnał w swoim pasie; „Offset” – wspólna oś Y.", "Wybierz z listy."),
    "Auto Y": _e("Automatyczna skala osi Y (układ offset).", "Dopasowuje zakres Y do widocznych danych.", "Wyłącz, aby ręcznie podać Y min i Y max."),
    "Y min": _e("Dolna granica osi Y.", "Ręczna skala w układzie offset.", "Aktywne po wyłączeniu Auto Y."),
    "Y max": _e("Górna granica osi Y.", "Ręczna skala w układzie offset.", "Aktywne po wyłączeniu Auto Y."),
    "Y maks": _e("Górna granica osi Y.", "Ręczna skala w układzie offset.", "Aktywne po wyłączeniu Auto Y."),
    "Punkty": _e("Przełącznik punktów próbek.", "Pokazuje punkty na krzywych (przy dużej liczbie próbek są pomijane).", "Zaznacz, aby włączyć."),
    "V znacznik": _e("Kursory pionowe (czas).", "Pomiar czasu, różnicy czasu i częstotliwości oraz wartości sygnałów w danej chwili.", "Włącz i klikaj na wykresie – maksymalnie 2 kursory, można je przeciągać."),
    "H znacznik": _e("Kursory poziome (wartość).", "Pomiar wartości i różnicy wartości.", "Włącz i klikaj na wykresie – maksymalnie 2 kursory."),
    "Kursory V": _e("Kursory pionowe (czas).", "Pomiar czasu, Δt i częstotliwości oraz wartości sygnałów.", "Włącz i klikaj na wykresie (maks. 2)."),
    "Kursory H": _e("Kursory poziome (wartość).", "Pomiar wartości i ΔY.", "Włącz i klikaj na wykresie (maks. 2)."),
    "Legenda": _e("Lista sygnałów z kolorami.", "Po najechaniu na pozycję pokazuje opis sygnału; można wybrać, czy pokazywać nazwę, czy adres.", "W programie: prawy przycisk na legendzie → „Legenda pokazuje”."),
    "Legenda pokazuje": _e("Co wyświetla legenda: nazwę sygnału albo jego adres (węzeł OPC).", "Ułatwia rozpoznanie sygnałów po adresie.", "Wybierz z listy."),
    # ---- trigger
    "Włącz trigger": _e("Włącznik wyzwalacza.", "Aktywuje wyzwalanie warunkiem na wybranym sygnale.", "Zaznacz, a następnie ustaw sygnał, tryb i wartości."),
    "Włączony": _e("Włącznik wyzwalacza.", "Aktywuje wyzwalanie warunkiem na sygnale.", "Zaznacz i ustaw sygnał oraz warunek."),
    "Sygnał": _e("Sygnał, na którym sprawdzany jest warunek wyzwalacza.", "Wskazuje, co ma wyzwolić akcję.", "Wybierz z listy sygnałów."),
    "Tryb": _e("Warunek wyzwalacza (np. ==, >, <, zbocze, między).", "Określa, kiedy wyzwalacz zadziała.", "Wybierz z listy; Wartość B jest potrzebna tylko dla warunków „między”."),
    "Warunek": _e("Warunek wyzwalacza (np. ==, >, <, zbocze, between).", "Określa, kiedy wyzwalacz zadziała.", "Wybierz z listy."),
    "Wartość A": _e("Pierwsza wartość progowa.", "Próg porównania dla warunku.", "Liczba w jednostkach sygnału."),
    "Wartość B": _e("Druga wartość progowa.", "Używana tylko dla warunków przedziałowych.", "Liczba w jednostkach sygnału."),
    "A": _e("Pierwsza wartość progowa.", "Próg porównania dla warunku.", "Liczba w jednostkach sygnału."),
    "B (dla „between”)": _e("Druga wartość progowa.", "Używana tylko dla warunku „between”.", "Liczba."),
    "Histereza": _e("Margines wokół progu.", "Zapobiega wielokrotnemu wyzwalaniu przy drganiach sygnału.", "0 = brak histerezy.", "≥ 0"),
    "Pretrigger [s]": _e("Czas historii zapisywany przed wyzwoleniem.", "Pozwala zobaczyć, co działo się przed zdarzeniem.", "Wpisz liczbę sekund.", "≥ 0"),
    "Przedtrigger [s]": _e("Czas historii zapisywany przed wyzwoleniem.", "Pozwala zobaczyć, co działo się przed zdarzeniem.", "Liczba sekund.", "≥ 0"),
    "Akcja": _e("Co robi wyzwalacz po zadziałaniu.", "Np. zatrzymanie wykresu, zapis CSV, oba naraz.", "Wybierz z listy."),
    # ---- REC
    "Folder": _e("Folder zapisu plików (migawki, REC).", "Wskazuje, gdzie trafiają pliki.", "Ścieżka względna oznacza folder w Dokumenty\\S7Trace bieżącego użytkownika; przycisk „…” otwiera wybór."),
    "Nazwa pliku": _e("Szablon nazwy pliku.", "Pliki dostają nazwę z podstawionych znaczników.", "Dostępne: {confname} {ip} {tab} {date} {time}."),
    "Nazwa pliku CSV": _e("Szablon nazwy pliku CSV.", "Nazwa pliku nagrania.", "Znaczniki: {confname} {ip} {tab} {date} {time}."),
    "Nazwa pliku zapisu": _e("Szablon nazwy pliku zapisu triggera.", "Nazwa pliku migawki.", "Znaczniki: {confname} {ip} {tab} {date} {time}."),
    "Zapis do": _e("Cel zapisu REC: plik CSV, SQLite, InfluxDB lub TimescaleDB.", "Wybiera, gdzie trafia nagranie.", "Dla baz użyj przycisku „…” (ustawienia bazy)."),
    "Cel zapisu": _e("Cel nagrywania: CSV, SQLite lub baza z listy administratora.", "Gdzie trafia nagranie.", "Wybierz z listy."),
    "Próbki": _e("Tryb zapisu próbek: tylko zmiany stanu albo każda próbka.", "Tryb zmian oszczędza miejsce – wykres odtwarza się dokładnie.", "Domyślnie „tylko zmiany stanu”."),
    "Tryb zapisu": _e("Tryb zapisu próbek.", "Tylko zmiany albo wszystkie próbki.", "Domyślnie tylko zmiany."),
    # ---- buttons of the tab
    "Start": _e("Przycisk uruchomienia odczytu.", "Łączy się ze sterownikiem i zaczyna zbierać dane.", "Naciśnij; Stop kończy odczyt."),
    "Stop": _e("Przycisk zatrzymania odczytu.", "Kończy zbieranie danych i rozłącza.", "Naciśnij."),
    "Pauza": _e("Wstrzymuje przewijanie wykresu.", "Pozwala obejrzeć dane bez zatrzymywania zbierania.", "Naciśnij ponownie, aby wrócić do danych na żywo."),
    "REC": _e("Przycisk nagrywania.", "Zapisuje przebieg do wybranego celu (plik / baza).", "Naciśnij podczas odczytu; ponowne naciśnięcie kończy nagranie."),
    "Sygnały": _e("Okno listy sygnałów.", "Dodawanie, edycja i usuwanie zmiennych odczytywanych ze sterownika.", "Naciśnij; przy aktywnym odczycie lista jest zablokowana."),
    "Diagnostyka": _e("Okno diagnostyki połączenia.", "Opóźnienia, utracone cykle, ping, przepustowość – do szukania przyczyn przerw.", "Naciśnij."),
    "Eksport okna → CSV": _e("Zapis widocznego okna do pliku CSV.", "Wyniki do dalszej analizy w arkuszu.", "Naciśnij i wskaż plik."),
    "Import CSV → wykres": _e("Wczytanie pliku CSV na wykres.", "Oglądanie wcześniej zapisanych danych.", "Naciśnij i wybierz plik."),
    "Dodaj znacznik": _e("Znacznik na wykresie.", "Oznacza ważną chwilę (punkt albo zakres czasu) z tytułem i opisem.", "Naciśnij; w dowolnym miejscu: prawy przycisk na wykresie."),
    "Lista znaczników": _e("Okno listy znaczników.", "Przeglądanie, filtrowanie i edycja wszystkich znaczników.", "Naciśnij (Ctrl+M)."),
    "Zapisz znaczniki": _e("Zapis roboczych zmian znaczników.", "Zmiany znaczników są robocze, dopóki ich nie zapiszesz.", "Naciśnij (Ctrl+Shift+S); okno wylicza zmiany."),
    "Szukaj w danych": _e("Wyszukiwarka wartości sygnałów.", "Znajduje chwile, gdy sygnał miał daną wartość lub się zmienił.", "Naciśnij (Ctrl+F)."),
    "Znaczniki": _e("Pasek przycisków znaczników.", "Dodawanie, lista, zapis i wyszukiwarka danych.", ""),
    "Xg": _e("Wzmocnienie (gain) wykresu.", "Skaluje krzywe pionowo.", ""),
    # ---- signals window columns / buttons
    "Pobierz": _e("Kolumna: czy sygnał jest odczytywany ze sterownika.", "Wyłączone sygnały nie obciążają łącza.", "Zaznacz, aby odczytywać."),
    "Pobieraj": _e("Czy sygnał jest odczytywany ze sterownika.", "Wyłączone nie obciążają łącza.", "Zaznacz."),
    "Wykres": _e("Kolumna: czy sygnał jest rysowany na wykresie.", "Można pobierać sygnał bez rysowania.", "Zaznacz, aby pokazać."),
    "Nazwa": _e("Nazwa sygnału.", "Pojawia się w legendzie, w plikach CSV i bazach.", "Wpisz unikalną nazwę.", "Do 64 znaków."),
    "Źródło": _e("Obszar pamięci sterownika (I, Q, M, DB, …).", "Wskazuje, skąd czytana jest zmienna.", "Wybierz z listy; „DB” wymaga numeru bloku."),
    "Typ": _e("Typ danych zmiennej (BOOL, BYTE, INT, DINT, REAL…).", "Określa rozmiar i sposób interpretacji bajtów.", "Wybierz zgodny z projektem sterownika."),
    "DB": _e("Numer bloku danych.", "Adresuje zmienną w bloku DB.", "Używane tylko dla źródła „DB”.", "1–65535"),
    "Bajt": _e("Numer bajtu (offset) zmiennej.", "Adres zmiennej w obszarze pamięci.", "Wpisz offset z projektu.", "≥ 0"),
    "Bit": _e("Numer bitu w bajcie.", "Dotyczy zmiennych typu BOOL.", "0–7."),
    "Węzeł OPC / nazwa (Web API)": _e("Identyfikator węzła OPC UA albo nazwa zmiennej Web API.", "Adresuje zmienną dla tych protokołów.", "Wpisz ręcznie albo użyj „Z OPC UA…”."),
    "Węzeł / zmienna": _e("Identyfikator węzła OPC UA albo nazwa zmiennej Web API.", "Adresuje zmienną dla tych protokołów.", "Wpisz lub wybierz z przeglądarki OPC."),
    "Share": _e("Względna wysokość pasa sygnału na wykresie.", "Pozwala dać ważnym sygnałom więcej miejsca.", "1 = standard; 2 = dwa razy wyższy pas.", "0,1–100"),
    "Kolor": _e("Kolor krzywej sygnału.", "Odróżnia sygnały na wykresie i w legendzie.", "Kliknij kolorowe pole i wybierz kolor."),
    "Opis": _e("Opis sygnału.", "Notatka dla użytkownika, widoczna w dymku sygnału.", "Dowolny tekst."),
    "Aktualna wartość": _e("Ostatnia odczytana wartość.", "Podgląd bieżącej wartości w wybranym formacie.", "Tylko do odczytu; widoczna przy działającym odczycie."),
    "Sposób wyświetlania": _e("Format wartości w kolumnie „Aktualna wartość”.", "Domyślnie, dziesiętnie, HEX, BIN, TRUE/FALSE, naukowo.", "Wybierz z listy."),
    "Offset Y": _e("Przesunięcie pionowe krzywej w układzie offset.", "Rozsuwa krzywe, by się nie nakładały.", "Liczba w jednostkach sygnału."),
    "Gain": _e("Mnożnik wartości na wykresie.", "Skaluje krzywą (wartość × gain).", "1 = bez zmiany."),
    "Dodaj": _e("Przycisk dodania sygnału.", "Dodaje nowy wiersz na liście.", "Naciśnij; nazwy numerowane wg ustawień."),
    "Z symboli": _e("Import sygnałów z tabeli symboli.", "Szybkie dodanie zmiennych z projektu TIA.", "Naciśnij i wybierz symbole."),
    "Z OPC UA": _e("Przeglądarka węzłów serwera OPC UA.", "Wybór zmiennych bezpośrednio ze sterownika.", "Wymaga połączenia OPC UA."),
    "Usuń": _e("Przycisk usunięcia.", "Usuwa zaznaczony element.", "Zaznacz element i naciśnij."),
    "Zapisz listę": _e("Zapis listy sygnałów do pliku.", "Pozwala użyć listy w innej karcie lub na innym komputerze.", "Naciśnij i wskaż plik."),
    "Wczytaj listę": _e("Wczytanie listy sygnałów z pliku.", "Odtwarza zapisaną listę.", "Naciśnij i wybierz plik."),
    "Z innej karty": _e("Kopiowanie sygnałów z innej karty.", "Szybkie przeniesienie listy.", "Naciśnij i wybierz kartę."),
    "OK": _e("Zatwierdzenie zmian i zamknięcie okna.", "Zapisuje wprowadzone ustawienia.", "Naciśnij."),
    "Anuluj": _e("Zamknięcie okna bez zapisu.", "Odrzuca zmiany.", "Naciśnij."),
    "Zamknij": _e("Zamknięcie okna.", "Kończy pracę z oknem.", "Naciśnij."),
    "Zapisz": _e("Zapisanie zmian.", "Zatwierdza wprowadzone dane.", "Naciśnij."),
    "Odśwież": _e("Odczyt listy od nowa.", "Pokazuje aktualny stan.", "Naciśnij."),
    "Wczytaj": _e("Wczytanie wybranego nagrania.", "Otwiera nagranie na wykresie.", "Wybierz nagranie i naciśnij."),
    "Właściwości": _e("Tytuł, uwagi i tagi nagrania.", "Opis ułatwia późniejsze szukanie.", "Wybierz nagranie i naciśnij."),
    "Sterownik…": _e("Dane sterownika zapisane z nagraniem.", "Wiąże dane z właściwym sterownikiem (model, MLFB, firmware, numer seryjny).", "Wybierz nagranie i naciśnij."),
    "Przywróć": _e("Przywrócenie nagrania z kosza.", "Cofa usunięcie.", "Wybierz w widoku kosza."),
    "Opróżnij kosz": _e("Trwałe usunięcie nagrań z kosza.", "Zwalnia miejsce – nie można cofnąć.", "Naciśnij w widoku kosza."),
    "Zapisz jako CSV": _e("Eksport nagrania do CSV.", "Dane do arkusza.", "Wybierz nagranie i naciśnij."),
    "Początek": _e("Kolumna: czas rozpoczęcia nagrania.", "Sortowanie i identyfikacja.", "Kliknij nagłówek, aby sortować."),
    "Czas trwania": _e("Kolumna: długość nagrania.", "", ""),
    "Tytuł": _e("Tytuł nagrania lub znacznika.", "Krótka nazwa ułatwiająca odnalezienie.", "Wpisz tekst."),
    "Tagi": _e("Słowa kluczowe nagrania.", "Filtrowanie i wyszukiwanie.", "Oddziel przecinkami."),
    "Uwagi": _e("Dłuższe notatki.", "Opis okoliczności.", "Dowolny tekst."),
    "Użytkownik": _e("Konto, które wykonało nagranie.", "Pozwala filtrować cudze i własne nagrania.", ""),
    "Komputer": _e("Komputer, z którego powstało nagranie.", "", ""),
    "Konfiguracja": _e("Nazwa konfiguracji / połączenia.", "", ""),
    "Karta": _e("Karta programu, z której powstało nagranie.", "", ""),
    "Nr seryjny": _e("Numer seryjny sterownika.", "Wiąże nagranie z konkretnym urządzeniem.", "Zapisywany automatycznie z nagraniem."),
    "Wpisy": _e("Liczba zapisanych wpisów (zdarzeń).", "", ""),
    "Sygnały (kolumna)": _e("Liczba sygnałów w nagraniu.", "", ""),
    # ---- diagnostics
    "Odśwież": _e("Odczyt od nowa.", "Aktualizuje widok.", "Naciśnij."),
    "Ping sterownika": _e("Jednorazowy ping ICMP sterownika.", "Sprawdza dostępność sieciową i opóźnienie.", "Naciśnij."),
    "Chwilowo": _e("Ostatni pomiar.", "", ""),
    "P95": _e("95. percentyl czasu odczytu.", "95% odczytów trwa nie dłużej.", ""),
    "P99": _e("99. percentyl czasu odczytu.", "Podstawa zalecanego cyklu.", ""),
    "Odch. std.": _e("Odchylenie standardowe.", "Rozrzut pomiarów.", ""),
}

HELP: dict[str, str] = {norm(k): v for k, v in _RAW.items()}


def lookup(caption: str) -> str:
    """The help text for a visible caption (empty when there is none)."""
    return HELP.get(norm(caption), "")


def generic(kind: str, caption: str) -> str:
    """Fallback for an element without its own text: what kind of element it is and what the caption says."""
    what = {"button": "Przycisk", "check": "Pole wyboru", "combo": "Lista rozwijana", "edit": "Pole do wpisania wartości", "spin": "Pole liczbowe",
            "table": "Tabela", "header": "Nagłówek kolumny", "group": "Pole z ustawieniami", "tab": "Karta", "label": "Opis pola"}.get(kind, "Element")
    cap = f" „{caption.strip()}”" if caption and caption.strip() else ""
    return f"{what}{cap}.\nPo najechaniu na element z opisem (podpowiedzią) widać, do czego służy; pełny opis całego programu: Pomoc."
