"""Pomoc → opis programu: spis treści + opisy z rysunkami (QTextBrowser)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLineEdit, QListWidget, QPushButton, QSplitter, QTextBrowser,
                               QVBoxLayout, QWidget)

HELP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "help")


def _img(name: str, width: int | None = None, caption: str = "") -> str:
    w = f' width="{width}"' if width else ""
    cap = f'<br><i style="font-size:small">{caption}</i>' if caption else ""
    return f'<p><img src="img/{name}.png"{w}>{cap}</p>'


def _table(rows: list[tuple[str, str]], head: tuple[str, str] = ("Element", "Znaczenie")) -> str:
    out = [f'<table border="1" cellspacing="0" cellpadding="5" width="100%"><tr><th align="left" width="28%">{head[0]}</th>'
           f'<th align="left">{head[1]}</th></tr>']
    for a, b in rows:
        out.append(f"<tr><td valign='top'><b>{a}</b></td><td valign='top'>{b}</td></tr>")
    out.append("</table>")
    return "".join(out)


def _swatch(bg: str, fg: str, text: str) -> str:
    return f'<span style="background-color:{bg}; color:{fg};">&nbsp;{text}&nbsp;</span>'


def sections() -> list[tuple[str, str]]:
    s: list[tuple[str, str]] = []

    s.append(("1. Szybki start", """
<h2>Szybki start</h2>
<ol>
<li>Wpisz <b>adres IP</b> sterownika (tylko IPv4, np. <tt>192.168.0.1</tt>) i <b>Rack / Slot</b>
(S7-300/400: 0 / 2, S7-1200/1500: 0 / 1) w panelu „Połączenie”.</li>
<li>Kliknij <b>Sygnały…</b> i dodaj zmienne: źródło (I, Q, M, DB), typ, adres (DB, bajt, bit), kolor.
Można też zaimportować symbole z TIA / Step 7 (Plik → Importuj symbole) i dodać je przyciskiem „Z symboli…”.</li>
<li>Kliknij <b>Start</b>. Wykres przesuwa się w czasie rzeczywistym – najnowsze próbki są po prawej stronie.</li>
<li>Przeciągnięcie lub powiększenie wykresu myszą wstrzymuje widok (zbieranie danych trwa dalej);
<b>Wznów</b> wraca do trybu na żywo.</li>
<li><b>REC</b> zapisuje wszystkie próbki do pliku CSV, <b>Trigger</b> zapisuje / wstrzymuje wykres po spełnieniu warunku.</li>
</ol>
<p>Program łączy się ze sterownikiem protokołem S7comm (biblioteka snap7) i tylko <b>czyta</b> dane – nigdy nie zapisuje do PLC.
S7-1200/1500 wymagają w CPU: „Permit access with PUT/GET communication” oraz bloków DB bez „Optimized block access”.</p>
"""))

    s.append(("2. Układ okna", """
<h2>Układ okna</h2>
<ul>
<li><b>Pasek menu</b> (Plik / Widok / Pomoc) i – po jego prawej stronie – <b>karty</b> (każda karta to osobne połączenie).</li>
<li><b>Panel ustawień</b> po lewej: Połączenie, Zakres okna wykresu, Trigger, Nagrywanie REC.</li>
<li><b>Wykres główny</b> i pod nim <b>pasek podglądu</b> całej historii.</li>
<li><b>Przyciski sterujące</b> pod wykresem, przyciski <b>Sygnały… / Eksport / Import</b> po prawej, na dole <b>pasek statusu</b>.</li>
</ul>
<h3>Zmiana proporcji okna</h3>
<ul>
<li><b>Szerokość panelu ustawień</b> – chwyć pionowy pasek między panelem a wykresem i przeciągnij w lewo / w prawo.</li>
<li><b>Wysokość paska podglądu</b> – chwyć poziomy pasek między wykresem głównym a paskiem podglądu i przeciągnij w górę / w dół.</li>
<li><b>Legenda</b> – przeciągnij ją myszą w dowolne miejsce wykresu albo wybierz narożnik w Widok → Położenie legendy (ta karta). Każda karta pamięta własne położenie legendy; podwójne kliknięcie legendy otwiera okno „Sygnały…”.</li>
</ul>
<p>Wszystkie te ustawienia (oraz położenie i rozmiar okna, motyw, kolumny okna sygnałów) są zapamiętywane
i przywracane po ponownym uruchomieniu (<tt>%APPDATA%\\S7Trace\\config.json</tt>, autozapis co 20 s i przy zamknięciu).</p>
""" + _img("zal17", 90, "Panel ustawień (po lewej) – jego szerokość zmieniasz przeciągając pasek podziału")))

    s.append(("3. Menu Plik", """
<h2>Menu Plik</h2>
""" + _img("zal07") + _table([
        ("Nowa karta (Ctrl+T)", "Dodaje kartę z nowym, niezależnym połączeniem."),
        ("Zmień nazwę karty… (F2)", "Nadaje nazwę karcie (puste = pokazuj adres IP). Dwuklik na karcie robi to samo."),
        ("Duplikuj kartę", "Kopiuje ustawienia i sygnały bieżącej karty do nowej karty (bez danych)."),
        ("Zamknij kartę (Ctrl+W)", "Zamyka kartę (przy aktywnym połączeniu pyta o potwierdzenie)."),
        ("Zapisz konfigurację…", "Zapisuje do pliku .json konfigurację <b>bieżącej karty</b>: połączenie, sygnały, trigger, zakresy. "
         "Domyślna nazwa to <tt>s7trace_signals</tt>; jeśli plik już istnieje, dodawany jest numer "
         "(<tt>s7trace_signals_001</tt>). Gdy konfiguracja miała już nazwę (np. <tt>L1_Oven_output_Signals</tt>), "
         "podpowiadane jest <tt>L1_Oven_output_Signals_001</tt>."),
        ("Wczytaj konfigurację…", "Wczytuje plik konfiguracji do <b>bieżącej karty</b> (karta zachowuje swoją nazwę). "
         "Zatrzymane musi być tylko połączenie bieżącej karty – inne karty pracują dalej. "
         "Plik z kilkoma kartami: pierwsza trafia do bieżącej karty, pozostałe otwierają się jako nowe karty."),
        ("Eksport okna → CSV…", "Zapisuje widoczny fragment wykresu do pliku CSV."),
        ("Import CSV → wykres…", "Wczytuje plik CSV (także zapisany przez program) i pokazuje go na wykresie. Tylko przy zatrzymanym połączeniu."),
        ("Importuj symbole…", "Wczytuje tablicę tagów TIA (.xlsx/.csv), źródło DB z TIA (.db/.scl, XML) lub Step 7 (.sdf/.asc/.seq). "
         "Symbole dodasz w oknie Sygnały przyciskiem „Z symboli…”."),
        ("Wyczyść symbole", "Usuwa wszystkie zaimportowane symbole."),
        ("Wyjście (Ctrl+Q)", "Zamyka program (konfiguracja zapisywana jest automatycznie)."),
    ])))

    s.append(("4. Menu Widok", """
<h2>Menu Widok</h2>
""" + _img("zal08") + _table([
        ("Dopasuj widok do całości (Ctrl+0)", "Pokazuje całą nagraną historię na wykresie."),
        ("Legenda / Siatka", "Włącza lub wyłącza legendę i siatkę wykresu."),
        ("Położenie legendy (ta karta)", "Narożnik wykresu bieżącej karty, w którym stoi legenda (można ją też przeciągnąć myszą). Położenie jest zapisywane osobno dla każdej karty, w jej konfiguracji."),
    ])))

    s.append(("4a. Menu Ustawienia", """
<h2>Menu Ustawienia</h2>
""" + _table([
        ("Metoda połączenia i dane logowania…", "Ręczny wybór metody (Automatycznie, S7comm, OPC UA, Web API, Modbus TCP) oraz porty, "
         "użytkownik / hasło, certyfikat klienta OPC UA, Unit ID Modbus. Przycisk „Testuj” sprawdza wybraną metodę."),
        ("Kreator połączenia (rozpoznawanie metody)…", "Rozpoznaje, która metoda działa, i podaje zalecenia – patrz rozdział „Metody połączenia i kreator”."),
        ("Informacje o sterowniku i czas…", "Model, numer katalogowy, firmware, numer seryjny, stan, ochrona CPU oraz czas sterownika "
         "i jego różnica względem czasu komputera."),
        ("Diagnostyka połączenia… (Ctrl+D)", "Okno szczegółowej diagnostyki łącza bieżącej karty (opóźnienia, utracone cykle, ping, przepustowość)."),
        ("Aktywne sesje programu…", "Kto (konto Windows, sesja RDP) ma uruchomiony program na tym komputerze, od kiedy oraz które karty "
         "skanują sterowniki (IP, stan, od kiedy). Lista odświeża się na żywo; wpis znika po zamknięciu programu. "
         "Przy Start na sterownik, który już skanuje inny użytkownik, program tylko ostrzega (nie blokuje)."),
        ("Wymagania, ograniczenia i blokady…", "Opis ograniczeń każdej metody oraz ograniczeń systemowych i sieciowych."),
        ("Interfejs…, Zapisane konfiguracje interfejsu, Profil kolorów", "Kolory, czcionki, profile ciemny / jasny / systemowy i zapisane konfiguracje wyglądu."),
        ("Tryb pomocy („?”, Shift+F1)", "W prawym górnym rogu każdego okna (obok „X”) i w pasku menu głównego okna jest przycisk „?”. Po jego włączeniu najedź kursorem na dowolny element – przycisk, pole, nazwę kolumny albo wiersza, tytuł pola – a pojawi się dymek: co to jest, do czego służy, jak ustawić i zakres. Esc albo ponowne „?” kończy tryb. Gdy tryb jest włączony, przycisk „?” świeci na pomarańczowo (kolory tła i tekstu: Widok → Interfejs), a pozycja „Tryb pomocy” w menu Pomoc ma „ptaszek”."),
        ("Zwijane pola panelu", "Kliknięcie tytułu pola („Połączenie”, „Sterownik”, „Zakres okna wykresu”, „Trigger”, „Nagrywanie REC”) zwija lub rozwija jego zawartość; trójkąt za nazwą (w prawo = zwinięte, w dół = rozwinięte) obraca się płynnie. Stan jest pamiętany."),
        ("O programie", "Autor, wersja i data programu (wersja rośnie o 0,01 z każdą zmianą)."),
        ("Zapisz / Wczytaj konfigurację karty…", "To samo co w menu Plik."),
    ])))

    s.append(("5. Menu Pomoc", """
<h2>Menu Pomoc</h2>
""" + _img("zal09") + _table([
        ("Pomoc – opis programu… (F1)", "To okno."),
        ("Adresowanie, rack/slot, S7-1200/1500", "Krótka ściąga o wartościach rack/slot i ustawieniach CPU wymaganych przez S7-1200/1500."),
        ("O programie", "Informacja o programie."),
    ])))

    s.append(("6. Karty", """
<h2>Karty (zakładki)</h2>
""" + _img("zal10") + """
<p>Karty są po prawej stronie paska menu. <b>Każda karta jest niezależnym połączeniem</b> z własnym IP, sygnałami, triggerem,
zakresem i wykresem; kilka kart może pracować jednocześnie (np. kilka sterowników).</p>
<ul>
<li><b>Kolorowa kropka</b> przy nazwie to stan połączenia:
<span style="color:#4cd964">●</span> praca,
<span style="color:#ffcc00">●</span> łączenie,
<span style="color:#ff9500">●</span> ponawianie po utracie połączenia,
<span style="color:#8a8a8a">●</span> zatrzymana,
<span style="color:#ff453a">●</span> błąd.</li>
<li><b>Aktywna karta</b> ma niebieskie tło i żółtą czcionkę (kolory zmienisz w Widok → Interfejs).</li>
<li>Karta jest tak szeroka, by pokazać całą nazwę; gdy kart jest za dużo, nazwy są skracane do miejsca, gdzie kończy się menu „Pomoc”.
Pełna nazwa i stan pokazują się w podpowiedzi po najechaniu.</li>
<li><b>Dwuklik</b> lub F2 – zmiana nazwy; <b>prawy przycisk</b> – zmień nazwę / duplikuj / zamknij; przeciąganie zmienia kolejność;
<b>+</b> – nowa karta; <b>×</b> – zamknięcie.</li>
</ul>
"""))

    s.append(("7. Panel „Połączenie”", """
<h2>Panel „Połączenie”</h2>
""" + _img("zal06", 230) + _table([
        ("IP", "Adres IPv4 sterownika, opcjonalnie z portem (<tt>127.0.0.1:1102</tt> – symulator). Pole ma cztery niezależne "
         "pola liczbowe z nieruchomymi kropkami (puste pola są dozwolone; Backspace i Delete kasują tylko cyfry, zaznaczenie + "
         "Delete lub Spacja czyści cały adres). Lista rozwijana pokazuje historię adresów, z którymi się połączono "
         "(najnowsze u góry, osobno dla każdego użytkownika Windows). Niepełny adres jest obramowany na czerwono i blokuje Start. IPv6 i nazwy hostów nie są obsługiwane "
         "(S7comm działa wyłącznie po IPv4)."),
        ("Rack / Slot", "Położenie CPU: S7-300/400 – 0 / 2 (w S7-400 slot zależy od konfiguracji), S7-1200/1500 – 0 / 1. "
         "Przycisk „?” otwiera podpowiedź."),
        ("Cykle [ms]", "Okres odczytu, 1–60000 ms. Realny czas odpowiedzi PLC podaje pasek statusu (jeśli odczyt trwa dłużej "
         "niż cykl, pominięte cykle są zliczane jako „Missed”)."),
        ("Tryb komunik.", "<b>Bloki (grupowane)</b> – sąsiednie adresy są scalane w jeden odczyt (zwykle najszybciej). "
         "<b>Pojedyncze</b> – osobny odczyt dla każdego sygnału. <b>Multi-read</b> – wiele pozycji w jednym zapytaniu (do 20)."),
    ], ("Pole", "Opis")) + """
<p>W czasie pracy pola połączenia są zablokowane (zmiana po Stop). Odczyt PLC działa w osobnym procesie,
dlatego rysowanie wykresu nie opóźnia cykli. Po utracie połączenia program ponawia próby co 2 s, a w danych zostaje przerwa.</p>
"""))

    s.append(("8. Panel „Zakres okna wykresu”", """
<h2>Panel „Zakres okna wykresu”</h2>
""" + _table([
        ("Okno czasu [s]", "Szerokość widocznego fragmentu wykresu (0,1–86400 s). Wartość można <b>wpisać</b> (w sekundach, Enter zatwierdza) albo "
         "<b>wybrać z listy rozwijanej</b>: 5, 10, 15, 30, 60, 90 s; 2, 3, 5, 10, 15, 30, 60, 90 min; 2, 3, 4, 6, 8, 12, 16, 24 godz. "
         "Przy pracy na żywo wykres pokazuje ostatnie N sekund."),
        ("Auto Y", "Oś Y dopasowuje się do danych. Po wyłączeniu zakres wpisujesz w polach Y min / Y max (lub ustawiasz myszą)."),
        ("Y min / Y max", "Ręczny zakres osi pionowej (aktywne tylko przy wyłączonym Auto Y)."),
    ]) + """
<p>Wartości w „Zakres okna wykresu” aktualizują się też, gdy powiększasz lub przesuwasz wykres myszą.</p>
"""))

    s.append(("9. Panel „Trigger”", """
<h2>Panel „Trigger”</h2>
<p>Trigger działa jak w oscyloskopie: obserwuje jeden sygnał i po spełnieniu warunku wykonuje akcję.
Porównywana jest <b>wartość surowa</b> sygnału (bez gain i offsetu Y).</p>
""" + _table([
        ("Włącz trigger", "Uzbraja trigger (działa podczas pracy połączenia)."),
        ("Sygnał", "Obserwowany sygnał (spośród pobieranych)."),
        ("Tryb", "<tt>==</tt> (równe A, z tolerancją histerezy), <tt>&gt;</tt>, <tt>&lt;</tt>, <tt>between</tt> (od A do B), "
         "<tt>rising edge</tt> / <tt>falling edge</tt> (zbocze narastające / opadające przez wartość A). "
         "Dla sygnałów BOOL przy zboczach użyj A = 0,5."),
        ("Wartość A / B", "Progi porównania (B tylko dla „between”)."),
        ("Histereza", "Pasmo wokół progu, które musi zostać opuszczone, aby trigger mógł zadziałać ponownie (odporność na szum)."),
        ("Pretrigger [s]", "Ile sekund <b>przed</b> wyzwoleniem ma znaleźć się w zapisie / widoku. Reszta okna czasu to dane po wyzwoleniu."),
        ("Akcja", "<b>Pauza</b> – wstrzymuje widok na zdarzeniu (Wznów = ponowne uzbrojenie); <b>Zapis CSV</b> – zapisuje okno do pliku "
         "i uzbraja się ponownie; <b>Pauza + zapis CSV</b> – jedno i drugie."),
        ("Folder", "Katalog zapisu. Nazwa względna (domyślnie <tt>snapshots</tt>) oznacza folder w Dokumentach bieżącego użytkownika Windows: "
         "<tt>Dokumenty\\S7Trace\\snapshots</tt> – każde konto ma więc własne pliki. Przycisk „…” otwiera wybór folderu."),
        ("Nazwa pliku", "Szablon nazwy, domyślnie <tt>snapshot_{confname}_{ip}_{tab}_{date}_{time}.csv</tt>. Znaczniki: "
         "<tt>{confname}</tt> – nazwa konfiguracji (gdy jej brak, program zapyta o nazwę; bez odpowiedzi użyje <tt>no_name</tt>), "
         "<tt>{ip}</tt> – adres IP sterownika, <tt>{tab}</tt> – nazwa karty, "
         "<tt>{date}</tt> – data, <tt>{time}</tt> – godzina. Istniejący plik nie jest nadpisywany (dodawany jest numer)."),
    ]) + _img("zal06", 230, "Panel ustawień z sekcją Trigger")))

    s.append(("10. Wykres główny", """
<h2>Wykres główny</h2>
""" + _img("zal11", 640) + """
<ul>
<li><b>Krzywe</b> rysowane są schodkowo (wartość utrzymuje się do następnej próbki). Każdy sygnał ma własny kolor, <b>Gain</b> (mnożnik), <b>Share</b> (udział w wysokości osi) i <b>Offset Y</b> – ustawiane w oknie Sygnały.</li>
<li><b>Układ osi Y</b> (panel Zakres okna wykresu): <b>Pasma wg Share</b> (domyślnie) – każdy sygnał dostaje własne pasmo na osi pionowej, od góry w kolejności
wierszy w oknie Sygnały; wysokość pasma jest proporcjonalna do Share (trzy sygnały ze Share 1, 1 i 2 mają pasma 25%, 25% i 50% wysokości),
a sygnał jest skalowany do swojego MIN…MAX w widocznym oknie czasu (BOOL: 0…1). Oś pionowa pokazuje, kolorem sygnału, wartość
MIN i MAX, a w wyższych pasmach także wartości pośrednie. <b>Offset + Gain</b> – jedna wspólna skala (oś „Offset”), sygnały przesunięte
o Offset Y i pomnożone przez Gain; wtedy działają też Auto Y i Y min / Y max.</li>
<li><b>Oś czasu</b> pokazuje sekundy od startu (powyżej godziny: g:mm:ss; przy bardzo małym oknie także ułamki sekundy).
Najwęższe okno to <b>0,1 s</b> – kółko myszy dalej nie powiększa.</li>
<li><b>Przesuwanie i zoom myszą</b>: przeciągnięcie przesuwa wykres w czasie, kółko myszy powiększa / zmniejsza okno czasu.
Wstrzymuje to widok na żywo (zbieranie trwa dalej) – <b>Wznów</b> wraca do podglądu bieżących danych.</li>
<li><b>Legenda</b> (lewy górny róg) – pokazuje nazwy i kolory sygnałów widocznych na wykresie. Przeciągnij ją myszą, aby zmienić położenie,
albo wybierz narożnik w Widok → Położenie legendy (ta karta). Pozycja jest zapamiętywana osobno dla każdej karty.
Podwójne kliknięcie legendy otwiera okno „Sygnały…”. Po najechaniu kursorem na pozycję legendy pojawia się dymek z opisem sygnału (jak w oknie „Sygnały…”: adres, typ, skala, opis, aktualna wartość), a prawy przycisk → „Legenda pokazuje” przełącza napisy między nazwą sygnału a jego adresem / węzłem OPC (ustawienie karty).</li>
<li><b>Znacznik poziomu sygnału</b> (menu Znaczniki): po włączeniu kliknięcie na wykresie stawia poziomy kursor (maks. 2, przesuwalny);
w ramce wyświetlana jest wartość sygnału w pasie pod linią i różnica ΔY. <b>Różnica sygnału</b> (prawy przycisk → „Dodaj znacznik różnicy poziomu…”)
pokazuje różnicę wartości jednego sygnału między dwoma momentami.</li>
<li><b>Oś czasu</b> (panel Zakres okna wykresu): sekundy od startu albo zegar <tt>HH:MM:SS.mmm</tt> – <b>czas aplikacji</b> (komputera) lub <b>czas PLC</b>
(zegar sterownika = zegar komputera + różnica odczytana przy połączeniu); pokazywane są tylko te części czasu, które wynikają z powiększenia.
<b>Offset osi</b> (znak, data = pełne doby, godzina HH:MM:SS.mmm) koryguje pokazywany czas w lewo / w prawo – przy diagnostyce sygnałów albo gdy w sterowniku nie ustawiono daty; nie zmienia danych ani znaczników. Gdy zegar PLC różni się od komputera o dobę lub więcej, program to zgłasza w pasku statusu, a prawy przycisk na polu offsetu wyrównuje oś do zegara komputera. Pole „Sterownik” pokazuje w szóstej linii <b>Czas PLC</b> (data i godzina; czas czytany raz przy połączeniu, potem liczony z zegara komputera i odświeżany co sekundę).</li>
<li>Pionowa czerwona linia <b>TRIG</b> oznacza chwilę wyzwolenia triggera.</li>
</ul>
"""))

    s.append(("11. Pasek podglądu", """
<h2>Pasek podglądu (mały wykres na dole)</h2>
""" + _img("zal12", 640) + """
<ul>
<li>Pokazuje <b>całą nagraną historię</b> (do ok. 2 mln próbek na kartę; starsze próbki są przycinane).</li>
<li><b>Żółty obszar</b> to fragment widoczny na wykresie głównym. Przeciągnij go, aby przesunąć widok, albo rozciągnij jego brzegi,
aby zmienić okno czasu.</li>
<li>Wysokość paska zmieniasz, chwytając poziomy pasek podziału między wykresami (ustawienie jest zapamiętywane).</li>
</ul>
""" + _img("zal18", 640, "Pasek podziału między wykresem głównym a paskiem podglądu")))

    s.append(("12. Przyciski sterujące", """
<h2>Przyciski sterujące pod wykresem</h2>
""" + _img("zal13") + _table([
        ("Start", "Łączy ze sterownikiem i rozpoczyna zbieranie danych (wymaga poprawnego IP i co najmniej jednego pobieranego sygnału)."),
        ("Stop", "Kończy połączenie. Dane pozostają na wykresie."),
        ("Pauza / Wznów", "Wstrzymuje widok (zbieranie trwa) i wraca do trybu na żywo."),
        ("● REC", "Ciągły zapis do pliku CSV albo do bazy danych według panelu „Nagrywanie REC”: „Zapis do” (plik CSV, SQLite, "
         "InfluxDB 1.x / 2.x, TimescaleDB; przycisk „...” obok to ustawienia bazy i test połączenia) oraz „Próbki” "
         "(<b>tylko zmiany stanu</b> – domyślnie, albo każda próbka). Przy zapisie zmian wartość trafia do pliku / bazy tylko wtedy, "
         "gdy różni się od poprzedniej (plus pierwsza wartość każdej zmiennej) – to kilkadziesiąt razy mniej danych przy zapisie "
         "godzin i dni; wykres z takiego zapisu odtwarza się dokładnie (krzywa schodkowa). Bazy zapisują w osobnym wątku "
         "(paczki co ok. 0,5 s, ponawianie przy zaniku serwera, w pasku statusu licznik zapisanych wpisów i błędy). "
         "Każde nagranie w bazie ma tytuł, uwagi, tagi, właściciela (konto Windows), komputer i dane sterownika (model, numer katalogowy, firmware, numer seryjny, nazwa stacji – kolumny „Sterownik” i „Nr seryjny” oraz przycisk „Sterownik…” w przeglądzie nagrań). Kiedy program pyta o nazwę (na początku, w trakcie, na końcu "
         "albo wcale) – ustawia się w „...” → zakładka „Nagrania i użytkownicy”. Przegląd, opisy, kosz i usuwanie: Plik → Przegląd nagrań w bazach…; "
         "zaległe bufory: Diagnostyka → Zaległe bufory zapisu do baz…. "
         "Odczyt: Plik → Przegląd nagrań w bazach… (lista nagrań, opcjonalnie wybrany zakres czasu; bardzo długie nagrania są "
         "zmniejszane do min/max z każdego przedziału; „Zapisz jako CSV…” eksportuje wszystkie wiersze). Wszystkie czasy zapisu "
         "(pełny stan co N minut w trybie zmian – domyślnie 10, wysyłka paczek, ponawianie, limity czasu, bufor na dysku, rotacja "
         "SQLite, limit punktów odczytu) ustawia się w „...” albo w menu Ustawienia → „Zapis nagrań w bazach danych…”, zakładka "
         "„Czasy i bufory” – każdy parametr ma tam dokładny opis i wartość domyślną. Po naciśnięciu REC program w tle sprawdza "
         "serwer; gdy nie odpowiada, od razu pokazuje przyczynę („Przerwij REC” albo kontynuuj – dane czekają w buforze na dysku i "
         "są dosyłane po powrocie serwera). Dla plików CSV (folder i nazwa, domyślnie "
         "<tt>REC_{confname}_{ip}_{tab}_{date}_{time}.csv</tt> w folderze <tt>rec</tt>). Zapis trwa do wyłączenia przycisku lub Stop. "
         "Dodanie zmiennej w trakcie zapisu zaczyna nowy plik (z dodatkową kolumną). Podczas zapisu miga czerwona kropka, "
         "przy wyłączonym REC kropka ma kolor napisu."),
        ("Widok → Punkty", "Pokazuje znaczniki pojedynczych próbek na krzywych (ustawienie karty)."),
        ("Znaczniki → Znacznik poziomu sygnału", "Tryb stawiania poziomych kursorów wartości (patrz „Wykres główny”)."),
        ("Dodaj znacznik", "Zakłada znacznik na najnowszej próbce (na żywo) albo w środku widocznego zakresu. Przyciski znaczników są w osobnym rzędzie pod wykresem, wszystkie te polecenia są też w menu <b>Znaczniki</b> (Ctrl+Shift+M – dodaj, Ctrl+M – lista, Ctrl+Shift+S – zapisz, Ctrl+F – wyszukiwarka)."),
        ("Lista znaczników…", "Lista znaczników z wyszukiwaniem (tytuł, opis, uwagi, autor, grupa, kolor, priorytet, czas). Znacznik zakładasz prawym "
         "przyciskiem myszy na wykresie: <b>punkt</b>, <b>zakres czasu</b> (półprzezroczysty obszar) albo <b>różnica sygnału</b> (dwa momenty jednego "
         "przebiegu; na wykresie poziom na obu końcach i różnica wartości), dla wszystkich przebiegów albo tylko "
         "wybranych. Ma tytuł, opis, uwagi, kolor, priorytet, grubość i rodzaj linii, przezroczystość obszaru, autora oraz daty założenia i "
         "modyfikacji. Najechanie kursorem pokazuje dymek z opisem; prawy przycisk na znaczniku otwiera jego menu (edycja, zmiana pozycji, "
         "ukrycie / pokazanie nazwy na wykresie, grupy znaczników, cofnięcie zmiany, usunięcie). Znacznik jest <b>zablokowany</b> – przeciągnięcie "
         "przesuwa wykres; dopiero zaznaczenie „Zmień pozycję znacznika” w jego menu (można odznaczyć) pozwala go przeciągać myszą. "
         "Znaczniki leżą w osobnym pliku (<tt>Dokumenty\\S7Trace\\markers.db</tt>) i trzymają czas bezwzględny, więc pasują do wykresu na żywo, "
         "nagrania z bazy i pliku CSV."),
        ("Zapisz znaczniki", "Znaczniki założone, zmienione lub usunięte na wykresie są <b>robocze</b> (oznaczone gwiazdką), dopóki ich nie "
         "zapiszesz. Przycisk pokazuje ich liczbę, a okno przed zapisem wylicza: nowe, zmienione (z nazwami zmienionych pól) i do usunięcia. "
         "Przy zamykaniu karty albo programu z niezapisanymi znacznikami program przypomina o nich i pokazuje ich wykaz (Zapisz / Odrzuć / Wróć)."),
        ("Szukaj w danych…", "Wyszukiwarka wartości: sygnały o zadanej wartości, w przedziale, ze zmianą albo zboczem (do 3 warunków naraz, opcjonalnie minimalny "
         "czas trwania) w danych bieżącego wykresu albo w wybranym nagraniu z bazy; wynik pokazuje początek, czas trwania i wartości, „Pokaż” "
         "przechodzi na wykresie do wyniku, „Dodaj znacznik…” zakłada znacznik w tym miejscu. Można też przejść do wpisanej daty i godziny."),
    ]) + """
<h3>Kolory przycisków</h3>
<p>Wszystkie kolory ustawisz w Widok → Interfejs. Ustawienia fabryczne:</p>
<table border="1" cellspacing="0" cellpadding="6">
<tr><th>Stan</th><th>Wygląd</th><th>Kiedy</th></tr>
<tr><td>Wyłączony (wszystkie)</td><td>""" + _swatch("#3a3a3a", "#e8e8e8", "Przycisk") + """</td><td>stan spoczynkowy</td></tr>
<tr><td>Start załączony</td><td>""" + _swatch("#3a3a3a", "#ffe600", "Start") + """</td><td>połączenie aktywne</td></tr>
<tr><td>Stop załączony</td><td>""" + _swatch("#3a3a3a", "#b01818", "Stop") + """</td><td>połączenie zatrzymane</td></tr>
<tr><td>Pauza załączona</td><td>""" + _swatch("#f2d600", "#000000", "Wznów") + """</td><td>widok wstrzymany</td></tr>
<tr><td>REC załączony</td><td>""" + _swatch("#ff8c1a", "#ffffff", "<span style='color:#ff2020'>●</span> REC") + """</td><td>trwa zapis; kropka miga (domyślnie 0,5 Hz)</td></tr>
</table>
"""))

    s.append(("13. Sygnały / Eksport / Import", """
<h2>Przyciski: Sygnały…, Diagnostyka… (eksport i import CSV: menu Plik)</h2>
""" + _img("zal14") + _table([
        ("Sygnały…", "Otwiera okno konfiguracji sygnałów (patrz rozdział „Okno Sygnały do śledzenia”). Działa także podczas pracy."),
        ("Diagnostyka…", "Otwiera okno szczegółowej diagnostyki połączenia (rozdział „Diagnostyka połączenia”). Skrót: Ctrl+D."),
        ("Plik → Eksport okna → CSV…", "Zapisuje <b>widoczny</b> fragment wykresu do pliku CSV (nazwa wg szablonu z panelu Trigger). "
         "Plik zawiera definicje sygnałów w komentarzach <tt># signal:</tt>, więc można go później zaimportować."),
        ("Plik → Import CSV → wykres…", "Wczytuje plik CSV na wykres wraz z definicjami sygnałów. Dostępne tylko przy zatrzymanym połączeniu."),
    ])))

    s.append(("14. Pasek statusu", """
<h2>Pasek statusu</h2>
""" + _img("zal15", 640) + _table([
        ("Zakładki „System” i „Sieć” (dół panelu ustawień)", "Parametry, które były w pasku statusu, są teraz w dwóch zakładkach na dole lewego panelu. System: godzina systemowa, obciążenie CPU komputera i GUI lag – czas rysowania wykresu [ms] (gdy jest duży, ogranicz okno czasu lub liczbę sygnałów albo zmniejsz odświeżanie w Ustawienia → Renderowanie wykresu). Sieć: PLC comm lag Avg (średni czas odczytu z ostatnich 50 cykli, n = liczba próbek), Last (ostatni odczyt), Missed (cykle pominięte, bo odczyt trwał dłużej niż okres, i ich odsetek) oraz ping i utrata pakietów."),
        ("Komunikat", "Bieżący stan: łączenie, utrata połączenia, ścieżka pliku REC / triggera, wynik eksportu."),
    ], ("Pole", "Znaczenie")) + """
<p>Pasek zawiera już tylko status nagrywania i komunikaty; liczby łącza i systemu są w zakładkach „System” / „Sieć” na dole lewego panelu.
Pola panelu (Połączenie, Sterownik, Zakres okna wykresu, Trigger, Nagrywanie REC) <b>przeciągasz myszą za nazwę pola w górę lub w dół</b>, aby zmienić kolejność (kliknięcie
nazwy zwija / rozwija pole). <b>Prawy przycisk myszy na nazwie elementu</b> (np. „IP”, „Cykle [ms]”) pozwala go <b>ukryć</b>; <b>prawy przycisk na nazwie pola</b> (np. „Połączenie”)
otwiera menu pola: zwiń / rozwiń oraz lista wszystkich jego elementów z haczykami (ukrywanie i odkrywanie) i „Pokaż wszystkie elementy”. Kolejność pól, zwinięte pola, ukryte elementy i aktywna zakładka dolna
wchodzą do <b>konfiguracji interfejsu</b> – zapisują się w pliku konfiguracji aplikacji i w pliku konfiguracji interfejsu (Widok → Interfejs → Zapisz / Wczytaj).</p>
<p>Pole <b>Sterownik</b> ma na dole przycisk <b>Pobierz dane sterownika</b>: jednorazowo łączy się ze sterownikiem i czyta tylko jego dane (model, firmware, nazwy) oraz zegar – bez uruchamiania odczytu sygnałów i wykresu (połączenie musi być zatrzymane, metoda S7comm). Zakładka „System” pokazuje też, ile procesora zajmuje sama aplikacja („w tym ta aplikacja”: program razem z procesami odczytu, jako % całego komputera).</p>
<p>Tekst, który się nie mieści, <b>chwyć myszą i przeciągnij</b> w lewo / prawo (albo kółkiem myszy): w skrajnych położeniach koniec tekstu
dochodzi do prawej krawędzi paska, a początek do lewej – tekst nie ucieka poza pasek. W <b>Widok → Interfejs</b> ustawisz
<b>maksymalną liczbę linii</b> paska (pasek ma wysokość tylko tylu linii, ile potrzebuje tekst; przy większej liczbie linii tekst przeciąga się w górę /
w dół) oraz jego <b>kolor tła i tekstu</b>.</p>"""))

    s.append(("15. Diagnostyka połączenia", """
<h2>Diagnostyka połączenia (przycisk „Diagnostyka…”, menu Diagnostyka → Diagnostyka połączenia…, Ctrl+D)</h2>
<p>Okno pokazuje na żywo (odświeżanie co 0,5 s) pełne statystyki łącza z bieżącą kartą i można je trzymać otwarte obok wykresu.
Na górze jest <b>ocena łącza</b> (Bardzo dobre / Dobre / Przeciętne / Słabe / Brak połączenia) oraz <b>poziomym paskiem (bargrafem)</b> o 10 segmentach, wraz z listą konkretnych spostrzeżeń
i zaleceń, np. „zwiększ cykl do ≥ 41 ms”. Statystyki zerują się przy każdym Start; po Stop zostają widoczne do następnego Start.</p>
<h3>Zakładka „Opóźnienia”</h3>
""" + _table([
        ("Czas odczytu PLC", "Ile trwa jeden pełny cykl odczytu (wysłanie żądań i odebranie odpowiedzi) w ms: wartość <b>chwilowa</b>, "
         "średnia z ostatnich 10 s i 60 s, średnia od startu, min, max, odchylenie standardowe oraz percentyle P95 i P99."),
        ("Okres próbkowania", "Odstęp czasu między kolejnymi próbkami – powinien być równy ustawionemu cyklowi. "
         "Odchylenia to jitter (nierówność próbkowania)."),
        ("Ping ICMP (RTT)", "Czas odpowiedzi samej sieci na ping do adresu sterownika (rozdzielczość 1 ms), bez udziału protokołu S7."),
        ("Histogram", "Procent odczytów w przedziałach czasu (0–2, 2–5, 5–10 … ≥1000 ms), z liczbą nad każdym niepustym słupkiem – pokazuje, czy opóźnienia są stałe, czy zdarzają się rzadkie piki."),
    ], ("Wielkość", "Znaczenie")) + """
<h3>Zakładka „Pakiety i niezawodność”</h3>
""" + _table([
        ("Odebrane próbki / pominięte cykle [%]", "Pominięty cykl to taki, który minął, zanim skończył się poprzedni odczyt (łącze lub sterownik są wolniejsze niż cykl)."),
        ("Odczyty dłuższe niż cykl", "Liczba i procent odczytów, które trwały dłużej niż ustawiony cykl."),
        ("Błędy odczytu / ponowne połączenia", "Liczba utraconych połączeń lub nieudanych odczytów i udanych powrotów, wraz z treścią ostatniego błędu."),
        ("Czas przerw / dostępność [%]", "Łączny czas bez połączenia i procent czasu, w którym łącze działało."),
        ("Czas nawiązania połączenia", "Jak długo trwało ostatnie połączenie z PLC (TCP + negocjacja S7)."),
        ("Ping: wysłane / odebrane / utracone / utrata [%]", "Liczba pakietów ICMP i procent utraconych – wskaźnik <b>utraty pakietów w sieci</b>. "
         "Wraz z „kolejno utracone” i jitterem pingu pomaga odróżnić problem sieci od problemu sterownika."),
    ], ("Wielkość", "Znaczenie")) + """
<p><b>Uwaga:</b> program nie widzi pojedynczych pakietów TCP – utratę na poziomie S7 pokazują błędy odczytu i zerwania połączenia,
a utratę pakietów w sieci – ping ICMP (jeśli zapora lub router nie blokuje ICMP, ping pokaże 100% utraty mimo działającego S7).</p>
<h3>Zakładka „Przepustowość”</h3>
""" + _table([
        ("Częstotliwość oczekiwana / rzeczywista / maksymalna", "1000 / cykl, faktycznie osiągane próbkowanie (z ostatnich 10 s i od startu) "
         "oraz teoretyczny limit przy średnim czasie odczytu."),
        ("Zalecany najkrótszy cykl", "P99 czasu odczytu + 25% zapasu – poniżej tego cykl będzie często pomijany."),
        ("Dane na cykl / żądań na cykl", "Liczba bajtów i żądań S7 w jednym cyklu (zależy od sygnałów i trybu komunikacji)."),
        ("Przepustowość danych [B/s], żądania/s", "Faktyczny przepływ danych użytkowych ze sterownika."),
        ("Ruch w sieci – szacunek [kb/s]", "Dane plus ok. 150 B nagłówków na parę żądanie/odpowiedź – wartość orientacyjna."),
    ], ("Wielkość", "Znaczenie")) + """
<h3>Zakładka „Wykresy w czasie”</h3>
<p>Czas odczytu PLC i ping ICMP w funkcji czasu (zakres do wyboru: 10 s, 30 s, 1 min, 3 min, 10 min, 30 min, 60 min; dla zakresów powyżej 2 min wykres czasu odczytu pokazuje maksimum z każdej sekundy) z zaznaczonym ustawionym cyklem (czerwona linia).
Piki powyżej linii cyklu oznaczają pomijane próbki.</p>
<h3>Przyciski</h3>
""" + _table([
        ("Ping ICMP do sterownika", "Włącza wysyłanie jednego pingu na sekundę (nie zajmuje połączenia S7, więc nie obciąża sterownika). "
         "Działa także bez Start – możesz sprawdzić sieć przed uruchomieniem połączenia."),
        ("Test portu TCP…", "Jednorazowo łączy się z portem S7 (102 lub podanym po „:”) i mierzy czas – sprawdza routing i zaporę."),
        ("Resetuj statystyki", "Zeruje liczniki bez przerywania połączenia."),
        ("Kopiuj raport / Zapisz raport…", "Pełny raport tekstowy (ocena, wszystkie wartości) do schowka lub pliku – do dołączenia do zgłoszenia serwisowego."),
    ], ("Przycisk", "Działanie")) + """
<p>W pasku statusu, obok opóźnienia odczytu i pominiętych cykli, widać też bieżący ping i procent utraty pakietów (gdy ping jest włączony).</p>
"""))

    s.append(("16. Okno „Sygnały do śledzenia”", """
<h2>Okno „Sygnały do śledzenia”</h2>
""" + _img("zal16", 700) + """
<p>Każdy wiersz to jedna zmienna. Podczas pracy połączenia można <b>dodawać nowe zmienne</b> (są pobierane od następnego cyklu,
w starszych próbkach mają przerwę); adres, pole „Pobierz”, kolejność i usuwanie istniejących wierszy zmienisz po Stop.</p>
""" + _table([
        ("(numer wiersza)", "Chwyć numer i przeciągnij wiersz w inne miejsce, aby zmienić kolejność zmiennych (po Stop)."),
        ("Pobierz ✓", "Zaznaczona zmienna jest czytana z PLC (trafia do CSV i na wykres). Odznaczona – nie jest czytana."),
        ("Wykres ✓", "Zaznaczona zmienna jest rysowana na wykresie i w legendzie (można zmieniać także podczas pracy)."),
        ("Nazwa", "Dowolna nazwa. Powtórzone nazwy mają <span style='background-color:#9a2a2a;color:#fff'>&nbsp;czerwone&nbsp;</span> tło."),
        ("Aktualna wartość", "Bieżąca wartość (gdy zmienna jest pobierana), w formacie z kolumny „Sposób wyświetlania”."),
        ("Sposób wyświetlania", "Format wartości: Domyślnie, Dziesiętnie, HEX (<tt>16#…</tt>), BIN (<tt>2#…_…</tt>), TRUE/FALSE, Naukowo."),
        ("Źródło", "I (wejścia), Q (wyjścia), M (znaczniki), DB (blok danych)."),
        ("Typ", "BOOL, BYTE, SINT, USINT, WORD, INT, UINT, DWORD, DINT, UDINT, REAL, LREAL."),
        ("DB / Bajt / Bit", "Adres bezwzględny: numer DB (tylko dla źródła DB), numer bajtu, numer bitu (tylko BOOL). "
         "Powtórzony adres (źródło, typ, DB, bajt, bit) jest podświetlony <span style='background-color:#c9b030'>&nbsp;na żółto&nbsp;</span>."),
        ("Offset Y", "Przesunięcie krzywej w pionie (żeby sygnały nie nakładały się)."),
        ("Gain", "Mnożnik wartości na wykresie (surowa wartość w tabeli i w triggerze pozostaje bez zmian)."),
        ("Share", "Udział sygnału w wysokości osi pionowej (układ „Pasma wg Share”). Sygnał ze Share = 2 ma pasmo dwa razy wyższe niż "
         "sygnał ze Share = 1; wszystkie sygnały pokazane na wykresie dzielą oś proporcjonalnie do swoich wartości Share."),
        ("Kolor", "Kolor krzywej – kliknij, by wybrać."),
        ("Opis", "Dowolny komentarz; pokazuje się w podpowiedzi wiersza."),
    ], ("Kolumna", "Znaczenie")) + """
<h3>Przyciski</h3>
""" + _table([
        ("Dodaj", "Dopisuje nowy wiersz zawsze na końcu listy. Nazwa i adres kontynuują wiersz, w którym stoi kursor "
         "(<tt>D160B</tt> → <tt>D160C</tt>, <tt>123M1</tt> → <tt>123M2</tt>); zajęte nazwy są pomijane."),
        ("Z symboli…", "Dodaje zmienne z zaimportowanych symboli (filtr po nazwie lub adresie)."),
        ("Usuń", "Usuwa zaznaczone wiersze (podczas pracy – tylko dopiero co dodane)."),
        ("Zapisz listę… / Wczytaj listę…", "Zapis / odczyt samej listy zmiennych do pliku .json (przy wczytaniu: zastąp lub dołącz)."),
        ("Z innej karty…", "Kopiuje zmienne z innej karty."),
    ], ("Przycisk", "Opis")) + """
<h3>Menu prawego przycisku na nagłówku kolumny</h3>
<ul>
<li><b>Ukryj kolumnę / Pokaż kolumnę</b> – dowolna kolumna (ustawienie jest zapamiętywane).</li>
<li><b>Offset Y</b>: „Skoryguj wszystkie Offset Y” (układa wszystkie wiersze od 0 według kroku) i „Zmień Offset Y…” (krok dla nowych zmiennych, np. −1,1 → −1,5).</li>
<li><b>Nazwa</b>: auto-numerowanie włącz / wyłącz; nazwa z poprzedniej zmiennej albo własna (np. <tt>SIG1</tt>, <tt>SIG2</tt>…).</li>
</ul>
<p>Najechanie kursorem na wiersz pokazuje wszystkie dane zmiennej: adres, opis i aktualną wartość.</p>
"""))

    s.append(("16a. Renderowanie wykresu", """
<h2>Ustawienia → Renderowanie wykresu</h2>
<p>Wszystko, co decyduje o obciążeniu procesora przez wykres, jest regulowane (zmiany działają od razu, „Anuluj” je cofa, „Domyślne” przywraca
ustawienia oszczędne): <b>odświeżanie</b> (Hz, domyślnie 20), <b>nie rysuj niewidocznych kart</b> (dane, trigger i REC działają dalej),
<b>maks. punktów krzywej</b>, <b>punkty</b> – limit próbek w oknie, przy którym znaczniki są jeszcze rysowane, i ich rozmiar (przy większej liczbie
pasek statusu informuje, że punkty są ukryte – przybliż wykres albo zwiększ limit), <b>wykres przeglądowy</b> – jak często i z ilu punktów jest
przeliczany oraz <b>wygładzanie linii</b>. Na mocniejszym komputerze wartości można podkręcić.</p>
"""))
    s.append(("17. Interfejs (kolory i czcionki)", """
<h2>Widok → Interfejs</h2>
<ul>
<li><b>Profil kolorów</b>: Ciemny, Jasny, Systemowy (zgodny z trybem Windows, przełącza się na żywo) lub Własny
(ustawia się sam po ręcznej zmianie koloru).</li>
<li><b>Kolory</b>: tło okna i paneli, tekst, okienka edycyjne, przyciski, tabele, nagłówki, menu, karty (w tym aktywna karta), kolor zaznaczenia,
wykres oraz <b>przyciski sterujące</b> (Start, Stop, Pauza, REC, znaczniki – tło i tekst w każdym stanie, kolor kropki REC).</li>
<li><b>Czcionka</b>: rodzaj i rozmiar. <b>REC: częstotliwość migania</b> kropki (domyślnie 0,5 Hz).</li>
<li><b>Pasek statusu</b>: maksymalna liczba linii, kolor tła i tekstu. <b>Belki zmiany rozmiaru</b> (między panelem ustawień a wykresem i nad
wykresem przeglądowym): kolor oraz „zawsze widoczne” – domyślnie belka jest cienka i pojawia się dopiero po najechaniu kursorem.</li>
<li>Zmiany widać na żywo; <b>Anuluj</b> przywraca poprzedni wygląd, <b>Domyślne</b> – ustawienia fabryczne.</li>
<li><b>Zapisane konfiguracje</b>: „Zapisz jako…” zapisuje wygląd do pliku .json (każdy parametr w osobnej linii) w
<tt>%APPDATA%\\S7Trace\\interfejs\\</tt>; zapisane wybierasz z listy (także w Widok → Zapisane konfiguracje interfejsu).
„Wczytaj z pliku…” otwiera plik z dowolnego miejsca. W pliku jest też <b>wygląd linii znaczników</b> (Znaczniki → Wygląd
znaczników…: cztery grubości linii) – wczytanie konfiguracji przywraca go; plik starszej wersji bez tych parametrów zostawia bieżące.</li>
</ul>
"""))

    s.append(("19. Metody połączenia i kreator", """
<h2>Metody połączenia i kreator połączenia</h2>
<p>Program potrafi czytać sterowniki Siemensa czterema metodami. Metodę wybierasz w <b>Ustawienia → Metoda połączenia…</b>
(per karta) albo zostawiasz <b>Automatycznie</b> – przy każdym Start program sam rozpoznaje, co działa.</p>
""" + _table([
        ("S7comm (snap7)", "Najszybsza. Adres bezwzględny (I, Q, M, DB + bajt/bit). S7-1200/1500 wymagają PUT/GET i DB bez „Optimized block access”."),
        ("OPC UA", "Zmienne po nazwie (także zoptymalizowane). Źródło sygnału „OPC”, w polu „Węzeł” NodeId, np. <tt>ns=3;s=\"DB_Piec\".\"Temp\"</tt>. "
         "Przycisk „Z OPC UA…” w oknie Sygnały otwiera przeglądarkę drzewa zmiennych serwera."),
        ("Web API", "JSON-RPC po HTTP(S). Źródło „WEB”, w polu „Węzeł” nazwa zmiennej. Eksperymentalne – nietestowane na prawdziwym sterowniku."),
        ("Modbus TCP", "Rejestry i cewki udostępnione przez program PLC. Źródła MBH (rejestry holding), MBI (rejestry wejściowe), MBC (cewki), "
         "MBD (wejścia dyskretne); „Bajt” = numer rejestru / cewki, „DB” = Unit ID (0 = domyślny z ustawień)."),
    ], ("Metoda", "Opis")) + """
<h3>Tryb automatyczny – kolejność rozpoznawania</h3>
<ol><li>Ping ICMP (informacyjnie) i sprawdzenie portów TCP: 102, 4840, 443, 502 (równolegle).</li>
<li><b>S7comm</b>: połączenie (próby rack/slot 0/1, 0/2, 0/0, 1/2, 0/3), identyfikacja CPU, odczyt testowy pamięci M i kilku DB.</li>
<li><b>OPC UA</b>: pobranie listy zabezpieczeń i trybów logowania serwera, próba sesji, odczyt informacji o serwerze i jego czasu.</li>
<li><b>Web API</b>: zapytanie <tt>Api.Version</tt> (JSON-RPC).</li><li><b>Modbus TCP</b>: odczyt rejestru 0.</li></ol>
<p>Używana jest <b>pierwsza działająca</b> metoda zgodna ze źródłami sygnałów w karcie. Jeśli sygnały są S7, a działa tylko OPC UA, program
informuje, że trzeba zmienić źródło sygnałów (OPC UA) albo włączyć PUT/GET. Gdy nic nie działa – kreator pokazuje raport z zaleceniem,
<b>jaka metoda jest sugerowana</b> i co zmienić w TIA Portal.</p>
<h3>Kreator połączenia i dane o sterowniku</h3>
<p>Ustawienia → Kreator połączenia… pokazuje wynik każdego testu (✔ / ▲ / ✖), a zakładka „Sterownik i czas” – <b>rodzinę, model CPU, numer katalogowy (MLFB),
wersję firmware, numer seryjny, nazwę stacji, stan CPU (Run/Stop), poziom ochrony</b>, dane serwera OPC UA oraz <b>czas sterownika i różnicę względem czasu komputera</b>
(osobno do czasu lokalnego i do UTC – sterowniki często pracują w UTC). Raport można skopiować do schowka.</p>
<h3>Dane logowania</h3>
<p>OPC UA: dostęp anonimowy lub użytkownik/hasło; tryby zabezpieczone wymagają certyfikatu klienta (przycisk „Generuj certyfikat klienta…”
tworzy parę plików w <tt>%APPDATA%\\S7Trace\\certyfikaty</tt>; certyfikat trzeba zatwierdzić w sterowniku). Web API: użytkownik i hasło.
Hasło jest zapisywane w pliku konfiguracji <b>tylko</b>, gdy zaznaczysz „Zapamiętaj hasło” (jawnym tekstem).</p>
"""))

    s.append(("20. Ograniczenia, blokady i wymagania", """
<h2>Ograniczenia, blokady i wymagania</h2>
<h3>Czego program nie zrobi</h3>
<ul>
<li>Nie włączy PUT/GET ani serwera OPC UA w sterowniku i nie obejdzie zabezpieczeń – to ustawienia w TIA Portal.</li>
<li>Nie łamie haseł i nie odczyta licencji CPU: brak odpowiedzi serwera OPC UA może oznaczać wyłączony serwer albo brak licencji.</li>
<li>Rozpoznawanie jest <b>tylko do odczytu</b> – nic nie zmienia w sterowniku (identyfikacja, stan, zegar, odczyty testowe).</li>
<li>Rozróżnienie „PUT/GET wyłączony” i „blok zoptymalizowany” jest wnioskiem z odpowiedzi CPU – bywa niejednoznaczne (podawane jako „prawdopodobnie”).</li>
</ul>
<h3>Blokady po stronie sterownika</h3>
<ul>
<li><b>S7comm:</b> """ + "</li><li>".join(__import__("s7trace.core.detect", fromlist=["LIMITS"]).LIMITS["s7"]) + """</li>
<li><b>OPC UA:</b> """ + "</li><li>".join(__import__("s7trace.core.detect", fromlist=["LIMITS"]).LIMITS["opcua"]) + """</li>
<li><b>Web API:</b> """ + "</li><li>".join(__import__("s7trace.core.detect", fromlist=["LIMITS"]).LIMITS["webapi"]) + """</li>
<li><b>Modbus TCP:</b> """ + "</li><li>".join(__import__("s7trace.core.detect", fromlist=["LIMITS"]).LIMITS["modbus"]) + """</li>
</ul>
<h3>Ograniczenia systemowe i sieciowe</h3>
<ul><li>""" + "</li><li>".join(__import__("s7trace.core.detect", fromlist=["SYSTEM_LIMITS"]).SYSTEM_LIMITS) + """</li>
<li>Windows Server 2016 / pakiet przenośny: biblioteki OPC UA (asyncua, cryptography) są dołączone; brak połączenia z internetem nie przeszkadza.</li>
<li>W jednej karcie wszystkie pobierane sygnały muszą używać jednej metody (np. tylko OPC); do łączenia kilku metod użyj osobnych kart.</li>
<li>Gdy pierwsze sprawdzenie portów trwa długo, zapora lub router „gubi” pakiety zamiast je odrzucać – test czeka do 1,5 s na port.</li>
</ul>
"""))

    s.append(("18. Pliki CSV i skróty", """
<h2>Pliki CSV</h2>
<p>Pliki zawierają kolumny <tt>time_s</tt> (sekundy od startu), <tt>timestamp</tt> (data i godzina) i po jednej kolumnie na sygnał;
w komentarzach <tt># signal:</tt> zapisane są definicje sygnałów. Puste pole = brak danych (przerwa w połączeniu lub zmienna dodana później).</p>
<p>Znaczniki w nazwach plików (zapis wyzwolony triggerem i REC): <tt>{confname}</tt> – nazwa konfiguracji, <tt>{ip}</tt> – adres IP
sterownika, <tt>{tab}</tt> – nazwa karty, <tt>{date}</tt> – data, <tt>{time}</tt> – godzina.</p>
<h2>Skróty klawiszowe</h2>
""" + _table([
        ("Ctrl+T", "Nowa karta"), ("Ctrl+W", "Zamknij kartę"), ("F2", "Zmień nazwę karty"),
        ("Ctrl+0", "Dopasuj widok do całości"), ("Ctrl+D", "Diagnostyka połączenia"), ("F1", "Pomoc"), ("Ctrl+Q", "Wyjście"),
    ], ("Skrót", "Działanie"))))
    return s


class HelpDialog(QDialog):
    def __init__(self, parent=None, topic: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Pomoc – S7Trace")
        self.resize(1100, 760)
        self._sections = sections()
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Szukaj w pomocy…")
        self.search.returnPressed.connect(self._find)
        btn = QPushButton("Szukaj")
        btn.clicked.connect(self._find)
        top.addWidget(self.search, 1)
        top.addWidget(btn)
        lay.addLayout(top)
        split = QSplitter(Qt.Horizontal)
        self.toc = QListWidget()
        self.toc.addItems([t for t, _ in self._sections])
        self.toc.setMaximumWidth(300)
        self.view = QTextBrowser()
        self.view.setSearchPaths([HELP_DIR])
        self.view.setOpenExternalLinks(False)
        split.addWidget(self.toc)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 840])
        lay.addWidget(split, 1)
        close = QPushButton("Zamknij")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        self.toc.currentRowChanged.connect(self._show)
        self.toc.setCurrentRow(0)
        for i, (title, _) in enumerate(self._sections):
            if topic and topic.lower() in title.lower():
                self.toc.setCurrentRow(i)

    def _show(self, i: int) -> None:
        if 0 <= i < len(self._sections):
            self.view.setHtml(self._sections[i][1])

    def _find(self) -> None:
        """Jumps to the next section containing the text, highlighting the match."""
        q = self.search.text().strip().lower()
        if not q:
            return
        n = len(self._sections)
        start = self.toc.currentRow()
        if self.view.find(self.search.text()):                      # next match in the current section
            return
        for k in range(1, n + 1):
            i = (start + k) % n
            if q in self._sections[i][1].lower() or q in self._sections[i][0].lower():
                self.toc.setCurrentRow(i)
                self.view.find(self.search.text())
                return
