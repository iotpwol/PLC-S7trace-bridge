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
<li><b>Panel ustawień</b> po lewej: Połączenie, Zakres, Trigger.</li>
<li><b>Wykres główny</b> i pod nim <b>pasek podglądu</b> całej historii.</li>
<li><b>Przyciski sterujące</b> pod wykresem, przyciski <b>Sygnały… / Eksport / Import</b> po prawej, na dole <b>pasek statusu</b>.</li>
</ul>
<h3>Zmiana proporcji okna</h3>
<ul>
<li><b>Szerokość panelu ustawień</b> – chwyć pionowy pasek między panelem a wykresem i przeciągnij w lewo / w prawo.</li>
<li><b>Wysokość paska podglądu</b> – chwyć poziomy pasek między wykresem głównym a paskiem podglądu i przeciągnij w górę / w dół.</li>
<li><b>Legenda</b> – przeciągnij ją myszą w dowolne miejsce wykresu albo wybierz narożnik w Widok → Położenie legendy.</li>
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
        ("Interfejs…", "Okno kolorów i czcionek (patrz rozdział „Interfejs”)."),
        ("Zapisane konfiguracje interfejsu", "Lista konfiguracji wyglądu zapisanych w plikach .json – kliknięcie wczytuje wybraną; "
         "„Zapisz bieżącą jako…” i „Wczytaj z pliku…” działają na dowolnym pliku."),
        ("Profil kolorów", "Ciemny / Jasny / Systemowy (zgodny z trybem aplikacji w Windows, przełącza się też na żywo)."),
        ("Położenie legendy", "Narożnik wykresu, w którym stoi legenda (można ją też przeciągnąć myszą)."),
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
        ("IP", "Adres IPv4 sterownika, opcjonalnie z portem (<tt>127.0.0.1:1102</tt> – symulator). Pole blokuje niedozwolone znaki "
         "podczas pisania; błędny adres jest obramowany na czerwono i blokuje Start. IPv6 i nazwy hostów nie są obsługiwane "
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

    s.append(("8. Panel „Zakres”", """
<h2>Panel „Zakres”</h2>
""" + _table([
        ("Okno czasu [s]", "Szerokość widocznego fragmentu wykresu (0,05–86400 s). Przy pracy na żywo wykres pokazuje ostatnie N sekund."),
        ("Auto Y", "Oś Y dopasowuje się do danych. Po wyłączeniu zakres wpisujesz w polach Y min / Y max (lub ustawiasz myszą)."),
        ("Y min / Y max", "Ręczny zakres osi pionowej (aktywne tylko przy wyłączonym Auto Y)."),
    ]) + """
<p>Wartości w „Zakres” aktualizują się też, gdy powiększasz lub przesuwasz wykres myszą.</p>
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
        ("Folder", "Katalog zapisu (względny liczony od katalogu uruchomienia). Przycisk „…” otwiera wybór folderu."),
        ("Nazwa pliku", "Szablon nazwy, domyślnie <tt>snapshot_{tab}_{date}_{time}.csv</tt>. Znaczniki: <tt>{tab}</tt> – nazwa karty, "
         "<tt>{confname}</tt> – nazwa konfiguracji (gdy jej brak, program zapyta o nazwę; bez odpowiedzi użyje <tt>no_name</tt>), "
         "<tt>{date}</tt> – data, <tt>{time}</tt> – godzina. Istniejący plik nie jest nadpisywany (dodawany jest numer)."),
    ]) + _img("zal06", 230, "Panel ustawień z sekcją Trigger")))

    s.append(("10. Wykres główny", """
<h2>Wykres główny</h2>
""" + _img("zal11", 640) + """
<ul>
<li><b>Krzywe</b> rysowane są schodkowo (wartość utrzymuje się do następnej próbki). Każdy sygnał ma własny kolor, <b>Offset Y</b> (przesunięcie
w pionie, by sygnały BOOL nie nakładały się) i <b>Gain</b> (mnożnik) – ustawiane w oknie Sygnały.</li>
<li><b>Oś czasu</b> pokazuje sekundy od startu (powyżej godziny: g:mm:ss).</li>
<li><b>Przesuwanie i zoom myszą</b>: przeciągnięcie przesuwa wykres w czasie, kółko myszy powiększa / zmniejsza okno czasu.
Wstrzymuje to widok na żywo (zbieranie trwa dalej) – <b>Wznów</b> wraca do podglądu bieżących danych.</li>
<li><b>Legenda</b> (lewy górny róg) – pokazuje nazwy i kolory sygnałów widocznych na wykresie. Przeciągnij ją myszą, aby zmienić położenie,
albo wybierz narożnik w Widok → Położenie legendy. Pozycja jest zapamiętywana.</li>
<li><b>V znacznik / H znacznik</b>: kliknięcie na wykresie stawia pionowy / poziomy kursor (maks. 2, przesuwalne);
w ramce wyświetlane są wartości sygnałów w miejscu kursora, Δt (z częstotliwością) i ΔY.</li>
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
        ("● REC", "Ciągły zapis wszystkich próbek do pliku <tt>rec_{tab}_{date}_{time}.csv</tt>. Zapis trwa do wyłączenia przycisku lub Stop. "
         "Dodanie zmiennej w trakcie zapisu zaczyna nowy plik (z dodatkową kolumną). Podczas zapisu miga czerwona kropka."),
        ("Punkty", "Pokazuje znaczniki pojedynczych próbek na krzywych."),
        ("V znacznik / H znacznik", "Tryb stawiania kursorów pionowych / poziomych (patrz „Wykres główny”)."),
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
<tr><td>V / H znacznik, Punkty</td><td>""" + _swatch("#2a82da", "#000000", "V znacznik") + """</td><td>tryb włączony</td></tr>
</table>
"""))

    s.append(("13. Sygnały / Eksport / Import", """
<h2>Przyciski: Sygnały…, Eksport okna → CSV, Import CSV → wykres</h2>
""" + _img("zal14") + _table([
        ("Sygnały…", "Otwiera okno konfiguracji sygnałów (patrz następny rozdział). Działa także podczas pracy."),
        ("Eksport okna → CSV", "Zapisuje <b>widoczny</b> fragment wykresu do pliku CSV (nazwa wg szablonu z panelu Trigger). "
         "Plik zawiera definicje sygnałów w komentarzach <tt># signal:</tt>, więc można go później zaimportować."),
        ("Import CSV → wykres", "Wczytuje plik CSV na wykres wraz z definicjami sygnałów. Dostępne tylko przy zatrzymanym połączeniu."),
    ])))

    s.append(("14. Pasek statusu", """
<h2>Pasek statusu</h2>
""" + _img("zal15", 640) + _table([
        ("PLC comm lag Avg", "Średni czas odczytu ze sterownika [ms] z ostatnich 50 cykli (n = liczba próbek w średniej)."),
        ("Last", "Czas ostatniego odczytu [ms]."),
        ("GUI lag", "Czas rysowania wykresu [ms] – gdy jest duży, ogranicz okno czasu lub liczbę sygnałów."),
        ("Missed", "Liczba cykli pominiętych, bo odczyt trwał dłużej niż ustawiony okres, i ich odsetek."),
        ("Komunikat", "Bieżący stan: łączenie, utrata połączenia, ścieżka pliku REC / triggera, wynik eksportu."),
    ], ("Pole", "Znaczenie"))))

    s.append(("15. Okno „Sygnały do śledzenia”", """
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

    s.append(("16. Interfejs (kolory i czcionki)", """
<h2>Widok → Interfejs</h2>
<ul>
<li><b>Profil kolorów</b>: Ciemny, Jasny, Systemowy (zgodny z trybem Windows, przełącza się na żywo) lub Własny
(ustawia się sam po ręcznej zmianie koloru).</li>
<li><b>Kolory</b>: tło okna i paneli, tekst, okienka edycyjne, przyciski, tabele, nagłówki, menu, karty (w tym aktywna karta), kolor zaznaczenia,
wykres oraz <b>przyciski sterujące</b> (Start, Stop, Pauza, REC, znaczniki – tło i tekst w każdym stanie, kolor kropki REC).</li>
<li><b>Czcionka</b>: rodzaj i rozmiar. <b>REC: częstotliwość migania</b> kropki (domyślnie 0,5 Hz).</li>
<li>Zmiany widać na żywo; <b>Anuluj</b> przywraca poprzedni wygląd, <b>Domyślne</b> – ustawienia fabryczne.</li>
<li><b>Zapisane konfiguracje</b>: „Zapisz jako…” zapisuje wygląd do pliku .json (każdy parametr w osobnej linii) w
<tt>%APPDATA%\\S7Trace\\interfejs\\</tt>; zapisane wybierasz z listy (także w Widok → Zapisane konfiguracje interfejsu).
„Wczytaj z pliku…” otwiera plik z dowolnego miejsca.</li>
</ul>
"""))

    s.append(("17. Pliki CSV i skróty", """
<h2>Pliki CSV</h2>
<p>Pliki zawierają kolumny <tt>time_s</tt> (sekundy od startu), <tt>timestamp</tt> (data i godzina) i po jednej kolumnie na sygnał;
w komentarzach <tt># signal:</tt> zapisane są definicje sygnałów. Puste pole = brak danych (przerwa w połączeniu lub zmienna dodana później).</p>
<p>Znaczniki w nazwach plików: <tt>{tab}</tt> – nazwa karty, <tt>{confname}</tt> – nazwa konfiguracji, <tt>{date}</tt> – data, <tt>{time}</tt> – godzina.</p>
<h2>Skróty klawiszowe</h2>
""" + _table([
        ("Ctrl+T", "Nowa karta"), ("Ctrl+W", "Zamknij kartę"), ("F2", "Zmień nazwę karty"),
        ("Ctrl+0", "Dopasuj widok do całości"), ("F1", "Pomoc"), ("Ctrl+Q", "Wyjście"),
    ], ("Skrót", "Działanie"))))
    return s


class HelpDialog(QDialog):
    def __init__(self, parent=None):
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
