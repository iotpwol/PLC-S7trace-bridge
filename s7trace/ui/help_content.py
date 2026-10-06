"""Treść pomocy „Pomoc → opis programu”.

Wszystkie rysunki w `s7trace/help/img` są zdjęciami RZECZYWISTEGO programu – robi je `tools/make_help_images.py`
(program uruchamiany na symulatorze sterownika). Gdy wygląd programu się zmieni, wystarczy uruchomić ten skrypt ponownie."""
from __future__ import annotations

import os

HELP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "help")


def _img(name: str, caption: str = "", width: int | None = None) -> str:
    """Rysunek (zdjęcie z programu) z opcjonalnym podpisem. Rozmiar i wygładzone skalowanie robi `ImageBrowser` (help_dialog.py);
    kliknięcie rysunku otwiera go w pełnej rozdzielczości (odnośnik `zoom:<nazwa>`)."""
    cap = f'<br><i style="font-size:small">{caption}</i>' if caption else ""
    return f'<p><a href="zoom:{name}"><img src="img/{name}.png"></a>{cap}</p>'


def _imgs(*pairs: tuple[str, str]) -> str:
    """Kilka rysunków jeden pod drugim (nazwa, podpis)."""
    return "".join(_img(n, c) for n, c in pairs)


def _table(rows: list[tuple[str, str]], head: tuple[str, str] = ("Element", "Znaczenie")) -> str:
    out = [f'<table border="1" cellspacing="0" cellpadding="5" width="100%"><tr><th align="left" width="28%">{head[0]}</th>'
           f'<th align="left">{head[1]}</th></tr>']
    for a, b in rows:
        out.append(f"<tr><td valign='top'><b>{a}</b></td><td valign='top'>{b}</td></tr>")
    out.append("</table>")
    return "".join(out)


def _swatch(bg: str, fg: str, text: str) -> str:
    return f'<span style="background-color:{bg}; color:{fg};">&nbsp;{text}&nbsp;</span>'


def _limits(key: str) -> str:
    from ..core import detect
    return "</li><li>".join(detect.LIMITS[key])


def sections() -> list[tuple[str, str]]:
    s: list[tuple[str, str]] = []

    # ------------------------------------------------------------------------------------------------------------ 1
    s.append(("1. Szybki start", """
<h2>Szybki start</h2>
<p>S7Trace to rejestrator / wykres w czasie rzeczywistym dla sterowników Siemens S7 (oraz – przez inne metody – OPC UA, Web API
i Modbus TCP). Czyta zmienne ze sterownika w zadanym cyklu, rysuje je jak oscyloskop, potrafi je nagrywać (plik CSV albo baza danych)
i wyzwalać zapis po spełnieniu warunku. Program <b>tylko czyta</b> – nigdy nie zapisuje do sterownika.</p>
""" + _img("okno_glowne", "Okno programu w czasie pracy (połączenie z symulatorem sterownika)") + """
<ol>
<li>W panelu <b>Połączenie</b> wpisz <b>adres IP</b> sterownika (tylko IPv4, np. <tt>192.168.0.1</tt>) i <b>Rack / Slot</b>
(S7-300/400: 0 / 2, S7-1200/1500: 0 / 1). Metodę połączenia możesz zostawić na „Automatycznie” – po połączeniu program pokaże w polu
<b>Metoda</b>, której użył (np. <b>Auto: S7comm (snap7, PUT/GET)</b>).</li>
<li>Kliknij <b>Sygnały…</b> i dodaj zmienne: źródło (I, Q, M, DB), typ, adres (DB, bajt, bit), kolor.
Zmienne można też zaimportować z symboli TIA / Step 7 (Plik → Importuj symbole…) i dodać przyciskiem „Z symboli…”.</li>
<li>Kliknij <b>Start</b>. Wykres przesuwa się w czasie rzeczywistym – najnowsze próbki są po prawej stronie.</li>
<li>Przeciągnięcie lub powiększenie wykresu myszą wstrzymuje widok (zbieranie danych trwa dalej); <b>Wznów</b> wraca do trybu na żywo.</li>
<li><b>REC</b> nagrywa wszystkie próbki do pliku CSV albo do bazy, <b>Trigger</b> zapisuje / wstrzymuje wykres po spełnieniu warunku,
<b>Znaczniki</b> pozwalają opisać ważne miejsca wykresu.</li>
</ol>
<p><b>Wymagania sterownika (S7comm):</b> w CPU S7-1200/1500 musi być włączone „Permit access with PUT/GET communication” i bloki DB
nie mogą mieć „Optimized block access”. Szczegóły i inne metody: rozdział „Metody połączenia i kreator”.</p>
<p><b>Jak korzystać z tej pomocy:</b> po lewej jest spis rozdziałów, u góry – wyszukiwarka. Każdy rozdział zawiera <b>zdjęcia z działającego
programu</b> (menu, pola, okna) i opis: co to jest, do czego służy, jak się zachowuje i od czego zależy. Dodatkowo w programie działa
<b>tryb pomocy „?”</b> (rozdział „Menu Pomoc i tryb pomocy”): dymek z opisem przy każdym elemencie.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 2
    s.append(("2. Układ okna", """
<h2>Układ okna</h2>
""" + _img("okno_glowne_stop", "Okno przed uruchomieniem połączenia (wykres pusty, panel Sterownik bez danych)") + """
<ul>
<li><b>Pasek menu</b> (Plik, Widok, Diagnostyka, Znaczniki, Ustawienia, Pomoc) i – po jego prawej stronie – <b>karty</b> oraz przycisk <b>?</b> (tryb pomocy).</li>
<li><b>Panel ustawień</b> po lewej – pięć zwijanych pól: Połączenie, Sterownik, Zakres okna wykresu, Trigger, Nagrywanie REC; pod nimi zakładki <b>System / Sieć</b>.</li>
<li><b>Wykres główny</b> i pod nim <b>pasek podglądu</b> całej historii.</li>
<li><b>Przyciski sterujące</b> (Start, Stop, Pauza, REC) i <b>przyciski znaczników</b> pod wykresem, po prawej <b>Sygnały…</b> i <b>Diagnostyka…</b>, na dole <b>pasek statusu</b>.</li>
</ul>
<h3>Zmiana proporcji okna</h3>
<ul>
<li><b>Szerokość panelu ustawień</b> – chwyć cienki pionowy pasek między panelem a wykresem i przeciągnij. Pasek jest widoczny dopiero po najechaniu kursorem
(kolor i opcję „zawsze widoczny” ustawisz w Ustawienia → Interfejs).</li>
<li><b>Wysokość paska podglądu</b> – chwyć poziomy pasek między wykresem głównym a paskiem podglądu.</li>
<li><b>Legenda</b> – przeciągnij ją myszą albo wybierz narożnik w Widok → Położenie legendy; podwójne kliknięcie otwiera okno „Sygnały…”.</li>
</ul>
<p>Położenie i rozmiar okna, motyw, układ panelu, kolumny okien i podziały są zapamiętywane i przywracane po ponownym uruchomieniu
(<tt>%APPDATA%\\S7Trace\\config.json</tt>, autozapis co 20 s i przy zamknięciu).</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 3
    s.append(("3. Menu Plik", """
<h2>Menu Plik</h2>
""" + _img("menu_plik") + _table([
        ("Nowa karta (Ctrl+T)", "Dodaje kartę z nowym, niezależnym połączeniem."),
        ("Zmień nazwę karty… (F2)", "Nadaje nazwę karcie (puste = pokazuj adres IP). Dwuklik na karcie robi to samo."),
        ("Duplikuj kartę", "Kopiuje ustawienia i sygnały bieżącej karty do nowej karty (bez danych)."),
        ("Zamknij kartę (Ctrl+W)", "Zamyka kartę (przy aktywnym połączeniu pyta o potwierdzenie; przy niezapisanych znacznikach – pokazuje ich wykaz)."),
        ("Zapisz konfigurację…", "Zapisuje do pliku .json konfigurację <b>bieżącej karty</b>: połączenie, sygnały, trigger, zakresy. "
         "Domyślna nazwa to <tt>s7trace_signals</tt>; jeśli plik już istnieje, dodawany jest numer (<tt>s7trace_signals_001</tt>)."),
        ("Wczytaj konfigurację…", "Wczytuje plik konfiguracji do <b>bieżącej karty</b> (karta zachowuje swoją nazwę). Połączenie tej karty musi być zatrzymane – "
         "inne karty pracują dalej. Plik z kilkoma kartami: pierwsza trafia do bieżącej karty, pozostałe otwierają się jako nowe."),
        ("Eksport okna → CSV…", "Zapisuje <b>widoczny</b> fragment wykresu do pliku CSV. Plik zawiera definicje sygnałów w komentarzach <tt># signal:</tt>, więc można go później zaimportować."),
        ("Import CSV → wykres…", "Wczytuje plik CSV (także zapisany przez program) i pokazuje go na wykresie wraz z definicjami sygnałów. Tylko przy zatrzymanym połączeniu."),
        ("Przegląd nagrań w bazach (SQLite / InfluxDB / TimescaleDB)…", "Okno z listą nagrań zapisanych w bazie danych (rozdział „Zapis do baz danych i przegląd nagrań”)."),
        ("Importuj symbole (TIA / Step 7)…", "Wczytuje tablicę tagów TIA (.xlsx/.csv), źródło DB z TIA (.db/.scl, XML) lub Step 7 (.sdf/.asc/.seq). Symbole dodasz w oknie Sygnały przyciskiem „Z symboli…”."),
        ("Wyczyść symbole", "Usuwa wszystkie zaimportowane symbole."),
        ("Wyjście (Ctrl+Q)", "Zamyka program (konfiguracja zapisywana jest automatycznie; przy niezapisanych znacznikach program pyta, co z nimi zrobić)."),
    ]) + """
<p>Dostępność poleceń zależy od stanu: polecenia zmieniające konfigurację karty (wczytanie, import CSV) są wyszarzone, gdy połączenie tej karty pracuje.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 4
    s.append(("4. Menu Widok", """
<h2>Menu Widok</h2>
""" + _img("menu_widok") + _table([
        ("Dopasuj widok do całości (Ctrl+0)", "Pokazuje całą nagraną historię na wykresie głównym (wstrzymuje widok na żywo)."),
        ("Legenda", "Włącza lub wyłącza nazwy sygnałów na wykresie – legendę albo opisy przy sygnałach (zależnie od stylu poniżej). Ustawienie wspólne dla kart."),
        ("Nazwy sygnałów na wykresie (ta karta)", "Styl nazw sygnałów <b>tylko na bieżącej karcie</b>: <b>Legenda (ramka z listą w rogu)</b> albo <b>Opisy przy sygnałach</b>. Poniżej dwie pozycje „Wszystkie otwarte karty: …” ustawiają ten sam styl na każdej karcie – patrz rozdział „Wykres główny”."),
        ("Przerwy Stop → Start (ta karta)", "Jak wykres pokazuje pauzę między <b>Stop</b> a <b>Start</b> odczytu (ustawienie karty): <b>Pusta przerwa w pełnej długości</b> (domyślnie), <b>Wytnij przerwę z wykresu (jeden znacznik)</b> – pauza nie zajmuje miejsca, krzywe się stykają, stoi tam jeden znacznik, a opisy osi przeskakują (np. „30 s | 50 s”) – albo <b>Przerwa o stałej szerokości (w pikselach)</b> – pauza to pas o stałej szerokości niezależnie od czasu jej trwania; szerokość ustawia pozycja <b>Szerokość przerwy [px]…</b>. Patrz „Start po Stop” w rozdziale „Przyciski sterujące”."),
        ("Siatka", "Włącza lub wyłącza siatkę wykresu."),
        ("Punkty (znaczniki próbek na krzywych, ta karta)", "Pokazuje znaczniki pojedynczych próbek na krzywych (ustawienie karty). Gdy w oknie jest więcej próbek niż limit z Ustawienia → Renderowanie wykresu, punkty są ukrywane – przybliż wykres."),
        ("Położenie legendy (ta karta)", "Narożnik wykresu, w którym stoi legenda (można ją też przeciągnąć myszą). Zapamiętywane osobno dla każdej karty."),
    ]) + _imgs(("menu_widok_nazwy", "Podmenu „Nazwy sygnałów na wykresie”"), ("menu_widok_legenda", "Podmenu „Położenie legendy” (działa w stylu „Legenda”)")) + """
<p>Kolory, czcionki i wygląd tabel ustawia się w <b>Ustawienia → Interfejs…</b> (rozdział „Interfejs: kolory, czcionka, tabele”).</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 5
    s.append(("5. Menu Diagnostyka", """
<h2>Menu Diagnostyka</h2>
""" + _img("menu_diagnostyka") + _table([
        ("Diagnostyka połączenia… (Ctrl+D)", "Okno szczegółowych statystyk łącza z bieżącym sterownikiem – patrz rozdział „Diagnostyka połączenia”."),
        ("Informacje o sterowniku i czas…", "Model, numer katalogowy, firmware, numer seryjny, stan, ochrona CPU oraz czas sterownika i jego różnica względem komputera."),
        ("Aktywne sesje programu…", "Kto (konto Windows, sesja RDP) ma uruchomiony program na tym komputerze i które karty skanują sterowniki – rozdział „Sesje i serwer Web”."),
        ("Zaległe bufory zapisu do baz…", "Lista plików buforu dyskowego, które czekają na dosłanie do bazy (gdy serwer bazy był niedostępny w czasie REC). "
         "Pozwala je dosłać, zachować albo usunąć – patrz „Zapis do baz danych i przegląd nagrań”."),
    ]) + """
<p>Dane diagnostyczne zbierane są tylko podczas pracy połączenia (Start); po Stop zostają widoczne do następnego Start.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 6
    s.append(("6. Menu Znaczniki", """
<h2>Menu Znaczniki</h2>
""" + _img("menu_znaczniki") + _table([
        ("Dodaj znacznik teraz (Ctrl+Shift+M)", "Zakłada znacznik na najnowszej próbce (na żywo) albo w środku widocznego zakresu."),
        ("Lista znaczników… (Ctrl+M)", "Okno z listą znaczników, z wyszukiwaniem i sortowaniem."),
        ("Zapisz znaczniki… (Ctrl+Shift+S)", "Zapisuje do bazy znaczników wszystkie zmiany robocze (nowe, zmienione, usunięte) w jednej operacji."),
        ("Wyszukiwarka danych (po wartościach i godzinach)… (Ctrl+F)", "Wyszukiwarka wartości w danych wykresu albo w nagraniu z bazy."),
        ("Znacznik poziomu sygnału (kliknij na wykresie; maks. 2 poziome kursory)", "Przełącza tryb stawiania poziomych kursorów wartości (rozdział „Wykres główny”)."),
        ("Wygląd znaczników (linie, REC)…", "Grubość linii znaczników (cztery wartości) oraz wygląd znaczników REC: włączenie, kolor, grubość, rodzaj linii, przezroczystość obszaru „Manual REC” – część motywu interfejsu."),
    ]) + """
<p>Znaczniki, ich zapis roboczy i wyszukiwarka są opisane w rozdziale „Znaczniki i wyszukiwanie w danych”.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 7
    s.append(("7. Menu Ustawienia", """
<h2>Menu Ustawienia</h2>
""" + _img("menu_ustawienia") + _table([
        ("Metoda połączenia i dane logowania…", "Ręczny wybór metody (Automatycznie, S7comm, OPC UA, Web API, Modbus TCP) oraz porty, "
         "użytkownik / hasło, certyfikat klienta OPC UA, Unit ID Modbus. Przycisk „Testuj” sprawdza wybraną metodę. Rozdział „Metody połączenia i kreator”."),
        ("Kreator połączenia (rozpoznawanie metody)…", "Rozpoznaje, która metoda działa, i podaje zalecenia."),
        ("Serwer Web (zgłaszanie sesji i wspólny rejestr)…", "Zgłaszanie sesji centralnemu serwerowi Web (wspólny rejestr dla wielu komputerów)."),
        ("Zapis nagrań w bazach danych (SQLite / InfluxDB / TimescaleDB)…", "Ustawienia celu zapisu REC (SQLite, InfluxDB, TimescaleDB), czasy, bufory, nagrania i użytkownicy."),
        ("Ikona programu (pasek zadań / przy zegarze)", "Gdzie ma być ikona programu: <b>Pasek zadań</b> (domyślnie), <b>Obszar powiadomień (przy zegarze)</b> albo <b>oba miejsca</b>. W trybie „przy zegarze” zminimalizowane okno znika z paska zadań, a kliknięcie ikony przy zegarze przywraca je; prawy przycisk na ikonie: „Pokaż S7Trace” i „Zakończ”. Gdy system nie ma obszaru powiadomień, program zostaje na pasku zadań. Wybór jest zapamiętywany."),
        ("Renderowanie wykresu (odświeżanie, punkty, obciążenie CPU)…", "Odświeżanie, limity punktów, wygładzanie – decyduje o obciążeniu procesora przez wykres."),
        ("Interfejs (kolory, czcionki)…", "Kolory, czcionki, tabele, pasek statusu, belki podziału, migająca kropka REC."),
        ("Zapisane konfiguracje interfejsu", "Lista zapisanych wyglądów – wybór wczytuje wygląd."),
        ("Profil kolorów", "Ciemny / Jasny / Systemowy (zgodny z trybem Windows)."),
        ("Wymagania, ograniczenia i blokady…", "Opis ograniczeń każdej metody oraz ograniczeń systemowych i sieciowych."),
        ("Zapisz konfigurację karty… / Wczytaj konfigurację do karty…", "To samo co w menu Plik."),
    ]) + _imgs(("menu_ustawienia_zapisane", "Podmenu „Zapisane konfiguracje interfejsu”"),
               ("menu_ustawienia_profil", "Podmenu „Profil kolorów”")) + """
"""))

    # ------------------------------------------------------------------------------------------------------------ 8
    s.append(("8. Menu Pomoc i tryb pomocy", """
<h2>Menu Pomoc i tryb pomocy „?”</h2>
""" + _img("menu_pomoc") + _table([
        ("Pomoc – opis programu… (F1)", "To okno: spis rozdziałów, wyszukiwarka i opisy ze zdjęciami programu."),
        ("Tryb pomocy („?”, Shift+F1)", "Włącza / wyłącza tryb pomocy kontekstowej (niżej). Gdy tryb jest włączony, pozycja ma „ptaszek”."),
        ("Adresowanie, rack/slot, S7-1200/1500", "Krótka ściąga o wartościach rack/slot i ustawieniach CPU wymaganych przez S7-1200/1500."),
        ("O programie", "Autor, wersja i data programu (wersja rośnie o 0,01 z każdą zmianą)."),
    ]) + _img("okno_o_programie") + """
<h3>Tryb pomocy „?”</h3>
""" + _img("pasek_menu_tryb_pomocy", "Przycisk „?” w prawym górnym rogu okna głównego (tu włączony – świeci)") + """
<p>W prawym górnym rogu okna głównego oraz każdego okna dialogowego (obok „X”) jest przycisk <b>?</b>. Po jego włączeniu (albo Shift+F1) najedź kursorem
na dowolny element – przycisk, pole, nazwę kolumny lub wiersza, tytuł pola, pozycję menu – a pojawi się dymek: <b>co to jest, do czego służy, jak ustawić
i jaki jest zakres</b>. Esc albo ponowne „?” kończy tryb. Gdy tryb jest włączony, przycisk „?” jest podświetlony (kolory tła i tekstu: Ustawienia → Interfejs).
Teksty dymków są wspólne dla programu i trybu Web.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 9
    s.append(("9. Karty", """
<h2>Karty (zakładki)</h2>
""" + _img("pasek_menu_karty", "Pasek menu i karty – aktywna karta ma niebieskie tło i żółtą czcionkę") + """
<p>Karty są po prawej stronie paska menu. <b>Każda karta jest niezależnym połączeniem</b> z własnym IP, sygnałami, triggerem,
zakresem, nagrywaniem i wykresem; kilka kart może pracować jednocześnie (np. kilka sterowników).</p>
<ul>
<li><b>Kolorowa kropka</b> przy nazwie to stan połączenia:
<span style="color:#4cd964">●</span> praca,
<span style="color:#ffcc00">●</span> łączenie,
<span style="color:#ff9500">●</span> ponawianie po utracie połączenia,
<span style="color:#8a8a8a">●</span> zatrzymana,
<span style="color:#ff453a">●</span> błąd.</li>
<li><b>Aktywna karta</b> ma niebieskie tło i żółtą czcionkę (kolory: Ustawienia → Interfejs).</li>
<li>Karta jest tak szeroka, by pokazać całą nazwę; gdy kart jest za dużo, nazwy są skracane. Pełna nazwa i stan pokazują się w podpowiedzi po najechaniu.</li>
<li><b>Dwuklik</b> lub F2 – zmiana nazwy; przeciąganie zmienia kolejność; <b>+</b> – nowa karta; <b>×</b> – zamknięcie.</li>
</ul>
""" + _img("menu_karta", "Menu prawego przycisku na karcie") + """
<p>Menu karty: zmień nazwę, duplikuj, zamknij. Zamknięcie karty z niezapisanymi znacznikami lub aktywnym połączeniem wymaga potwierdzenia.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 10
    s.append(("10. Panel „Połączenie”", """
<h2>Panel „Połączenie”</h2>
""" + _img("grp_polaczenie", "Połączenie aktywne – pola są zablokowane, w polu „Metoda” widać wynik rozpoznawania") + _img("grp_polaczenie_stop", "Połączenie zatrzymane – pola można edytować") + _table([
        ("IP", "Adres IPv4 sterownika, opcjonalnie z portem (<tt>127.0.0.1:1102</tt> – symulator). Pole ma cztery niezależne pola liczbowe z nieruchomymi kropkami "
         "(puste pola są dozwolone; Backspace i Delete kasują tylko cyfry, zaznaczenie + Delete lub Spacja czyści cały adres). "
         "Niepełny adres jest obramowany na <b>czerwono</b> i blokuje Start. IPv6 i nazwy hostów nie są obsługiwane (S7comm działa wyłącznie po IPv4)."),
        ("Rack / Slot", "Położenie CPU: S7-300/400 – 0 / 2 (w S7-400 slot zależy od konfiguracji), S7-1200/1500 – 0 / 1. Przycisk obok otwiera podpowiedź. "
         "Przy „Pobierz dane sterownika” oraz w kreatorze program sam próbuje par 0/1, 0/2, 0/0, 1/2, 0/3 – działającą wpisuje w pola."),
        ("Cykle [ms]", "Okres odczytu, 1–60000 ms. Realny czas odpowiedzi PLC podaje zakładka „Sieć”; jeśli odczyt trwa dłużej niż cykl, cykle są pomijane i zliczane jako „Missed”."),
        ("Tryb komunik.", "Sposób grupowania odczytów (lista niżej)."),
        ("Metoda", "<b>Tylko do odczytu.</b> Pokazuje, jaką metodą program <b>faktycznie</b> się połączył. Przy wyborze „Automatycznie (rozpoznawaj)” po połączeniu widać "
         "np. <b>Auto: S7comm (snap7, PUT/GET)</b>; przy ręcznym wyborze – nazwę wybranej metody. Wybór metody: Ustawienia → Metoda połączenia…"),
    ], ("Pole", "Opis")) + """
<h3>Pole IP – szczegóły</h3>
""" + _imgs(("pole_ip", "Poprawny adres z portem"), ("pole_ip_blad", "Niepełny adres – czerwona ramka, przycisk Start zablokowany"),
            ("pole_ip_historia", "Lista rozwijana: historia adresów, z którymi się połączono (najnowsze u góry, osobno dla każdego użytkownika Windows)")) + """
<h3>Rack / Slot, Cykle, Metoda</h3>
""" + _imgs(("pole_rack_slot", "Rack / Slot"), ("pole_cykl", "Cykl odczytu"), ("pole_metoda", "Pole „Metoda”")) + _img("okno_rack_slot", "Podpowiedź o wartościach rack / slot") + """
<h3>Tryb komunikacji</h3>
""" + _img("lista_tryb_komunikacji") + _table([
        ("Bloki (grupowane)", "Sąsiednie adresy są scalane w jeden odczyt (zwykle najszybciej)."),
        ("Pojedyncze", "Osobny odczyt dla każdego sygnału – prostsze, ale wolniejsze."),
        ("Multi-read", "Wiele pozycji w jednym zapytaniu (do 20 na zapytanie)."),
    ], ("Tryb", "Działanie")) + """
<p>W czasie pracy pola połączenia są zablokowane (zmiana po Stop). Odczyt PLC działa w <b>osobnym procesie</b>, dlatego rysowanie wykresu
nie opóźnia cykli. Po utracie połączenia program ponawia próby co 2 s, a w danych zostaje przerwa.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 11
    s.append(("11. Panel „Sterownik”", """
<h2>Panel „Sterownik”</h2>
""" + _img("grp_sterownik", "Dane odczytane ze sterownika po połączeniu (symulator)") + """
<p>Pokazuje <b>dane identyfikacyjne sterownika</b>: rodzinę, model CPU, numer katalogowy, firmware, numer seryjny, nazwę stacji i modułu, stan CPU, ochronę oraz
<b>Czas PLC</b> (data i godzina). Dane są czytane po każdym (ponownym) połączeniu. Każda informacja to osobny wiersz; wiersze bez danych są
ukryte. Czas PLC jest czytany raz przy połączeniu, potem liczony z zegara komputera i odświeżany co sekundę.</p>
""" + _img("grp_sterownik_brak", "Przed połączeniem: pole z przyciskiem „Pobierz dane sterownika”") + _table([
        ("Pobierz dane sterownika", "Jednorazowo łączy się ze sterownikiem i czyta <b>tylko jego dane</b> (model, firmware, nazwy) oraz zegar – bez uruchamiania odczytu sygnałów i wykresu. "
         "Połączenie musi być zatrzymane, metoda S7comm. Program próbuje kilku par rack/slot i wpisuje działającą w pola „Połączenie”."),
        ("Czas PLC", "Zegar sterownika (zegar komputera + różnica odczytana przy połączeniu). Różnica ≥ 1 doby jest zgłaszana w pasku statusu z propozycją offsetu osi czasu."),
    ]) + _img("grp_sterownik_blad", "Gdy odczyt się nie uda, w miejscu danych pojawia się komunikat z przyczyną (po polsku) i listą wypróbowanych par rack/slot") + _img("menu_pole_sterownik", "Prawy przycisk w polu: ukrywanie wierszy i przycisk odczytu") + """
<p>Zegar PLC jest odczytywany własnym parserem odpowiedzi S7 (biblioteka snap7 3.x przy niemożności odczytu zwraca czas komputera).
Różnice czasu są pokazywane jako <b>dni + godziny:minuty:sekundy</b>, osobno względem czasu lokalnego i UTC.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 12
    s.append(("12. Panel „Zakres okna wykresu”", """
<h2>Panel „Zakres okna wykresu”</h2>
""" + _img("grp_zakres") + _table([
        ("Okno czasu [s]", "Szerokość widocznego fragmentu wykresu (0,1–86400 s). Wartość można <b>wpisać</b> (w sekundach, Enter zatwierdza) albo <b>wybrać z listy</b> (niżej). "
         "Przy pracy na żywo wykres pokazuje ostatnie N sekund. Najwęższe okno to 0,1 s."),
        ("Oś czasu", "Sposób opisu osi poziomej: sekundy od startu albo zegar <tt>HH:MM:SS.mmm</tt> – <b>czas aplikacji</b> (komputera) lub <b>czas PLC</b> (zegar sterownika)."),
        ("Offset osi", "Korekta pokazywanego czasu: <b>znak</b> (+ / −), <b>dni</b> (pełne doby) i <b>godzina HH:MM:SS.mmm</b>. Zakres ±10 lat. "
         "Nie zmienia danych ani znaczników – tylko opis osi. Prawy przycisk na polu wyrównuje oś do zegara komputera."),
        ("Układ osi Y", "„Pasma wg Share” (domyślnie) albo „Offset + Gain” – patrz niżej."),
        ("Auto Y", "Oś Y dopasowuje się do danych (układ „Offset + Gain”). Po wyłączeniu zakres wpisujesz w Y min / Y max (lub ustawiasz myszą)."),
        ("Y min / Y max", "Ręczny zakres osi pionowej (aktywne tylko przy wyłączonym Auto Y i układzie „Offset + Gain”)."),
    ]) + """
<p>Wartości aktualizują się też, gdy powiększasz lub przesuwasz wykres myszą.</p>
<h3>Okno czasu – lista</h3>
""" + _img("lista_okno_czasu", "Gotowe wartości: 5, 10, 15, 30, 60, 90 s; 2, 3, 5, 10, 15, 30, 60, 90 min; 2, 3, 4, 6, 8, 12, 16, 24 godz.") + """
<h3>Oś czasu i offset</h3>
""" + _img("lista_os_czasu", "Lista „Oś czasu”") + _img("pole_offset", "Offset osi: znak, dni, godzina") + """
<p>Offset przydaje się przy diagnostyce sygnałów albo gdy w sterowniku nie ustawiono daty. Gdy zegar PLC różni się od komputera o dobę lub więcej,
program to zgłasza w pasku statusu.</p>
<h3>Układ osi Y</h3>
""" + _img("lista_uklad_osi_y") + _table([
        ("Pasma wg Share", "Każdy sygnał dostaje własne pasmo pionowe (od góry – w kolejności wierszy w oknie Sygnały); wysokość jest proporcjonalna do <b>Share</b>. "
         "Sygnał skalowany do MIN…MAX w widocznym oknie (BOOL: 0…1); etykiety MIN / MAX stoją na dolnej i górnej krawędzi pasma."),
        ("Offset + Gain", "Jedna wspólna skala (oś „Offset”): sygnały przesunięte o Offset Y i pomnożone przez Gain; działają Auto Y i Y min / Y max."),
    ], ("Układ", "Działanie")) + _imgs(("wykres_pasma", "Układ „Pasma wg Share”"), ("wykres_offset", "Układ „Offset + Gain”"))))

    # ------------------------------------------------------------------------------------------------------------ 13
    s.append(("13. Panel „Trigger”", """
<h2>Panel „Trigger”</h2>
<p>Trigger działa jak w oscyloskopie: obserwuje jeden sygnał i po spełnieniu warunku wykonuje akcję. Porównywana jest <b>wartość surowa</b>
sygnału (bez gain i offsetu Y).</p>
""" + _img("grp_trigger", "Trigger wyłączony – pola warunku i akcji są nieaktywne") + _img("grp_trigger_wlaczony", "Trigger włączony (uzbrojony)") + _table([
        ("Włącz trigger", "Uzbraja trigger (działa podczas pracy połączenia). Pola warunku są aktywne tylko po włączeniu."),
        ("Sygnał", "Obserwowany sygnał (spośród pobieranych)."),
        ("Tryb", "Rodzaj warunku (lista niżej)."),
        ("Wartość A / B", "Progi porównania (B tylko dla „between”)."),
        ("Histereza", "Pasmo wokół progu, które musi zostać opuszczone, aby trigger mógł zadziałać ponownie (odporność na szum)."),
        ("Pretrigger [s]", "Ile sekund <b>przed</b> wyzwoleniem ma znaleźć się w zapisie / widoku. Reszta okna czasu to dane po wyzwoleniu."),
        ("Akcja", "Co zrobić po wyzwoleniu (lista niżej)."),
        ("Folder", "Katalog zapisu. Nazwa względna (domyślnie <tt>snapshots</tt>) oznacza folder w Dokumentach bieżącego użytkownika Windows (<tt>Dokumenty\\S7Trace\\snapshots</tt>) – każde konto ma własne pliki. Przycisk „…” otwiera wybór folderu."),
        ("Nazwa pliku", "Szablon nazwy, domyślnie <tt>snapshot_{confname}_{ip}_{tab}_{date}_{time}.csv</tt>. Znaczniki: <tt>{confname}</tt> – nazwa konfiguracji "
         "(gdy jej brak, program zapyta o nazwę przy Start – tylko jeśli plik ma być zapisany), <tt>{ip}</tt> – adres IP, <tt>{tab}</tt> – nazwa karty, <tt>{date}</tt>, <tt>{time}</tt>. Istniejący plik nie jest nadpisywany (dodawany jest numer)."),
    ]) + """
<h3>Tryb warunku</h3>
""" + _img("lista_trigger_tryb") + _table([
        ("==", "Równe A (z tolerancją histerezy)."),
        (">  /  <", "Większe / mniejsze od A."),
        ("between", "Wartość między A i B."),
        ("rising edge / falling edge", "Zbocze narastające / opadające przez wartość A. Dla sygnałów BOOL użyj A = 0,5."),
    ], ("Tryb", "Warunek")) + """
<h3>Akcja</h3>
""" + _img("lista_trigger_akcja") + _table([
        ("Pauza", "Wstrzymuje widok na zdarzeniu (Wznów = ponowne uzbrojenie)."),
        ("Zapis CSV", "Zapisuje okno do pliku i uzbraja się ponownie."),
        ("Pauza + zapis CSV", "Jedno i drugie."),
    ], ("Akcja", "Działanie")) + """
<h3>Gdzie trafia zapis (snapshot)</h3>
<p>Pole <b>Zapis do</b> wybiera cel zapisu wyzwalacza – tak jak w REC: <b>Plik CSV</b> (domyślnie), <b>SQLite</b>, <b>InfluxDB 1.x / 2.x</b> albo <b>TimescaleDB</b>. Tekst akcji zmienia się razem z celem („Zapis SQLite”, „Pauza + zapis InfluxDB 1.x”…).
Dla bazy snapshot jest <b>nagraniem</b> o tytule „Snapshot (trigger)” (widać go w „Przeglądzie nagrań”). Pole <b>Baza</b> mówi, dokąd:</p>
<ul>
<li><b>Ogólna (jak w REC)</b> – do tej samej bazy co nagrania REC; jej ustawienia (adres, baza, użytkownik / token) są tam, gdzie ustawień REC (przycisk „…” w polu REC → Zapis do);</li>
<li><b>Osobna</b> – dla SQLite: <b>własny plik w folderze snapshotów</b> (pola <b>Folder</b> i <b>Plik bazy</b>, domyślnie <i>snapshots.db</i>, jedna baza zbiera wszystkie snapshoty karty); dla InfluxDB / TimescaleDB: <b>osobna tabela albo measurement</b> (nazwa jak w REC z dopiskiem <i>_snapshots</i>) w tej samej bazie.</li>
</ul>
""" + _img("grp_trigger_sqlite", "Snapshot do osobnej bazy SQLite (aktywne pola: Zapis do, Baza, Folder, Plik bazy)") + """
<p>Pola <b>Folder</b> i <b>Nazwa pliku</b> dotyczą zapisu do pliku CSV; <b>Folder</b> i <b>Plik bazy</b> – osobnej bazy SQLite. Pola, które przy danym wyborze nie mają znaczenia, są wyszarzone. Zapis do bazy odbywa się w tle, wynik pojawia się w pasku statusu.</p>
<p>Moment wyzwolenia jest zaznaczany na wykresie pionową czerwoną linią <b>TRIG</b>:</p>
""" + _img("wykres_trigger", "Wykres po wyzwoleniu triggera") + _img("okno_glowne_trigger", "Całe okno z uzbrojonym triggerem")))

    # ------------------------------------------------------------------------------------------------------------ 14
    s.append(("14. Panel „Nagrywanie REC”", """
<h2>Panel „Nagrywanie REC”</h2>
""" + _img("grp_rec", "Zapis do pliku CSV") + _img("grp_rec_sqlite", "Zapis do bazy SQLite (dodatkowe pola celu)") + _table([
        ("Zapis do", "Cel nagrywania: <b>Plik CSV</b>, <b>SQLite</b>, <b>InfluxDB 1.x / 2.x</b>, <b>TimescaleDB</b>. Przycisk „…” obok otwiera ustawienia celu i test połączenia."),
        ("Próbki", "<b>Tylko zmiany stanu</b> (domyślnie): do pliku / bazy trafia wartość tylko wtedy, gdy różni się od poprzedniej (plus pierwsza wartość każdej zmiennej i pełny "
         "stan co N minut) – kilkadziesiąt razy mniej danych; wykres z takiego zapisu odtwarza się dokładnie (krzywa schodkowa). <b>Każda próbka</b> – pełny zapis."),
        ("Folder / Nazwa pliku", "Dla pliku CSV: folder (względny = w Dokumentach użytkownika, domyślnie <tt>rec</tt>) i szablon nazwy "
         "<tt>REC_{confname}_{ip}_{tab}_{date}_{time}.csv</tt>."),
    ]) + _imgs(("lista_rec_cel", "Lista „Zapis do”"), ("lista_rec_probki", "Lista „Próbki”")) + """
""" + _img("okno_glowne_rec", "Okno podczas nagrywania REC: przycisk REC świeci, w pasku statusu licznik zapisu") + """
<p>Zapis trwa do wyłączenia przycisku <b>REC</b> lub Stop. Dodanie zmiennej w trakcie zapisu zaczyna nowy plik (z dodatkową kolumną). Podczas zapisu miga czerwona
kropka w przycisku REC (częstotliwość: Ustawienia → Interfejs). Bazy zapisują w osobnym wątku (paczki co ok. 0,5 s, ponawianie przy zaniku serwera, bufor na dysku);
w pasku statusu widać licznik zapisanych wpisów. Szczegóły baz: rozdział „Zapis do baz danych i przegląd nagrań”.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 15
    s.append(("15. Zwijanie, przeciąganie i ukrywanie pól panelu", """
<h2>Zwijanie, przeciąganie i ukrywanie pól panelu</h2>
<p>Każde z pięciu pól lewego panelu (Połączenie, Sterownik, Zakres okna wykresu, Trigger, Nagrywanie REC) można dopasować do własnych potrzeb:</p>
<ul>
<li><b>Zwijanie</b> – kliknięcie nazwy pola zwija / rozwija jego zawartość; trójkąt za nazwą (w prawo = zwinięte, w dół = rozwinięte) obraca się płynnie.</li>
<li><b>Kolejność</b> – przeciągnij nazwę pola myszą w górę lub w dół.</li>
<li><b>Ukrywanie elementów</b> – prawy przycisk na nazwie elementu (np. „IP”, „Cykle [ms]”) ukrywa go; prawy przycisk na nazwie pola otwiera menu z listą wszystkich jego elementów (haczyki)
i „Pokaż wszystkie elementy”.</li>
</ul>
""" + _img("grp_zwiniete", "Zwinięte pola Połączenie i Sterownik – pozostałe pola przesunęły się do góry") + _imgs(
        ("menu_pole_polaczenie", "Prawy przycisk na nazwie pola: zwiń / rozwiń i lista elementów z haczykami"),
        ("menu_wiersz_ip", "Prawy przycisk na nazwie elementu: ukrycie tego elementu")) + """
<p>Kolejność pól, zwinięte pola, ukryte elementy i aktywna zakładka dolna wchodzą do <b>konfiguracji interfejsu</b> – zapisują się w pliku konfiguracji aplikacji
i w pliku konfiguracji interfejsu (Ustawienia → Interfejs → Zapisz jako… / Wczytaj z pliku…). Element, dla którego nie ma danych (np. numer seryjny sterownika, którego nie odczytano), jest
w każdym razie niewidoczny, niezależnie od ustawienia.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 16
    s.append(("16. Zakładki „System” i „Sieć”", """
<h2>Zakładki „System” i „Sieć” (dół panelu ustawień)</h2>
""" + _img("panel_dol_system", "Zakładka „System”") + _img("panel_dol_siec", "Zakładka „Sieć”") + _table([
        ("Godzina systemowa", "Zegar komputera."),
        ("System operacyjny", "Nazwa i numer kompilacji Windows."),
        ("Obciążenie CPU", "Obciążenie procesora komputera (jak „Wykorzystanie procesora” w Menedżerze zadań). Poniżej „w tym ta aplikacja” – ile zajmuje sam program razem z procesami odczytu, jako % całego komputera."),
        ("GUI lag", "Czas rysowania wykresu [ms]. Gdy jest duży, ogranicz okno czasu lub liczbę sygnałów albo zmniejsz odświeżanie w Ustawienia → Renderowanie wykresu."),
        ("Sieć: PLC comm lag Avg / Last / Missed", "Średni czas odczytu z ostatnich 50 cykli (n = liczba próbek), ostatni odczyt, cykle pominięte (odczyt trwał dłużej niż okres) i ich odsetek."),
        ("Sieć: ping i utrata pakietów", "Wyniki pingu ICMP do sterownika (gdy ping jest włączony w Diagnostyce)."),
    ], ("Wiersz", "Znaczenie")) + """
<p>Wiersze zakładek można ukrywać prawym przyciskiem myszy (jak pola panelu); aktywna zakładka jest zapamiętywana.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 17
    s.append(("17. Wykres główny", """
<h2>Wykres główny</h2>
""" + _img("wykres", "Wykres główny: siedem sygnałów w układzie „Pasma wg Share”") + """
<ul>
<li><b>Krzywe</b> rysowane są schodkowo (wartość utrzymuje się do następnej próbki). Każdy sygnał ma własny kolor, <b>Gain</b>, <b>Share</b> i <b>Offset Y</b> – ustawiane w oknie Sygnały.</li>
<li><b>Oś czasu</b>: sekundy od startu albo zegar (patrz panel „Zakres okna wykresu”); powyżej godziny g:mm:ss, przy bardzo małym oknie także ułamki sekundy.</li>
<li><b>Przesuwanie i zoom myszą</b>: przeciągnięcie przesuwa wykres w czasie, kółko myszy powiększa / zmniejsza okno czasu. Wstrzymuje to widok na żywo (zbieranie trwa dalej) – <b>Wznów</b> wraca do podglądu bieżących danych.
Widok nie wyjdzie poza zebrane dane; najwęższe okno to 0,1 s.</li>
<li><b>Legenda</b> – nazwy i kolory sygnałów. Przeciągnij, aby zmienić położenie; podwójne kliknięcie otwiera „Sygnały…”. Najechanie na pozycję pokazuje dymek (adres, typ, skala, opis, aktualna wartość). Zamiast legendy można włączyć <b>opisy przy sygnałach</b> (niżej).</li>
<li>Pionowa czerwona linia <b>TRIG</b> oznacza chwilę wyzwolenia triggera.</li>
</ul>
<h3>Nazwy sygnałów: legenda albo opisy przy sygnałach</h3>
<p>Nazwy sygnałów można pokazywać na dwa sposoby – wybierasz <b>osobno dla każdej karty</b> w <b>Widok → Nazwy sygnałów na wykresie (ta karta)</b> albo w prawym menu legendy / opisu. Te same menu mają dwie pozycje <b>Wszystkie otwarte karty: …</b>, które ustawiają wybrany styl na wszystkich kartach naraz. W <b>Ustawienia → Interfejs</b> („Nazwy sygnałów (domyślnie)”) wybierasz styl domyślny – dostają go karty, którym nie wybrano stylu osobno:</p>
<ul>
<li><b>Legenda (ramka z listą w rogu)</b> – jedna ramka ze wszystkimi nazwami; można ją przeciągnąć w dowolne miejsce, położenie jest zapamiętywane osobno dla każdej karty.</li>
<li><b>Opisy przy sygnałach</b> – legenda znika, a przy <b>każdym sygnale</b> pojawia się jego nazwa w półprzezroczystej ramce, <b>w połowie wysokości pasma</b> sygnału, tuż <b>po prawej stronie osi pionowej</b>. Ramka ma kolor tła wykresu z przezroczystością, a napis – kolor sygnału, dzięki temu litery nie mieszają się z pikselami krzywej o tym samym kolorze.
W układzie „Offset + Gain” (jedna wspólna skala) opis stoi przy krzywej, a bliskie sobie opisy są rozsuwane tak, żeby się nie nakładały i nie wychodziły poza wykres.</li>
</ul>
""" + _imgs(("wykres_opisy", "Opisy przy sygnałach zamiast legendy (nazwy sygnałów)"), ("wykres_opisy_adres", "Ten sam wykres po przełączeniu opisów na adres / węzeł OPC")) + """
<p><b>Prawy przycisk na legendzie albo na opisie</b> otwiera menu: <b>Sygnały…</b>, <b>Legenda pokazuje</b> (nazwa sygnału / adres – węzeł OPC; ustawienie karty), <b>Nazwy sygnałów na wykresie</b> (legenda / opisy), położenie legendy (tylko w stylu „Legenda”) i ukrycie. Podwójne kliknięcie opisu otwiera okno „Sygnały…”, a najechanie pokazuje ten sam dymek co przy legendzie.
Przełącznik <b>Widok → Legenda</b> ukrywa i pokazuje nazwy w obu stylach. Styl wybrany dla karty zapisuje się w konfiguracji tej karty; wartość domyślna – w konfiguracji interfejsu. W trybie Web lista „Nazwy sygnałów” w pasku narzędzi wykresu i prawy przycisk na opisie ustawiają styl <b>tego połączenia</b> (zapisywany przy połączeniu, jeśli możesz je edytować); „Wszystkie połączenia: …” ustawia go wszystkim Twoim połączeniom i jako domyślny dla konta.</p>
<p><b>Opisy osi</b> („Sygnały” z lewej, „Czas” na dole) nie zabierają miejsca wykresowi: leżą <b>pod liczbami osi</b> (liczby je zasłaniają) i można je <b>chwycić myszką i przesunąć</b> wzdłuż osi – „Sygnały” w górę i w dół, „Czas” w lewo i w prawo. Gdy pod kursorem leży <b>znacznik obszaru</b> (np. Manual REC), prawy przycisk na legendzie albo na opisie sygnału otwiera <b>menu legendy</b>, a nie menu znacznika.</p>
""" + _imgs(("menu_legenda", "Menu prawego przycisku na legendzie"), ("menu_opis_sygnalu", "To samo menu otwarte na opisie przy sygnale (styl „Opisy”)")) + """
<h3>Menu prawego przycisku na wykresie</h3>
<p>Polecenia menu są <b>pogrupowane poziomymi separatorami</b> według funkcji: dodawanie znaczników, polecenia REC (Manual Start / Stop REC, przenoszenie, usuwanie), zapis znaczników, lista i wyszukiwanie, widoczność znaczników z innych połączeń. W grupie REC jest rozwijane menu <b>Pokaż…</b> z wszystkimi znacznikami REC (Start REC (n), Stop REC (n), Manual Start / Stop REC (n), Stop / Start odczytu (n)), a obok listy – <b>Pokaż znacznik…</b> z pozostałymi znacznikami (do 40, od najwcześniejszego). Wybranie pozycji <b>zatrzymuje wykres (pauza)</b> i ustawia widok na wskazanym znaczniku (gdy leży w innym nagraniu – otwiera je).</p>
""" + _img("menu_wykres_prawy") + _table([
        ("Dodaj znacznik…", "Znacznik punktowy, zakres czasu albo różnica sygnału w miejscu kliknięcia (rozdział „Znaczniki”)."),
        ("Legenda pokazuje", "Przełącza napisy legendy: nazwa sygnału albo jego adres / węzeł OPC (ustawienie karty)."),
        ("Pozostałe pozycje", "Dopasowanie widoku, legenda, siatka, punkty – to samo co w menu Widok."),
    ]) + """
<h3>Punkty próbek</h3>
""" + _img("wykres_punkty", "Widok → Punkty: znaczniki pojedynczych próbek na krzywych") + """
<h3>Znacznik poziomu sygnału (kursor H)</h3>
<p>Menu Znaczniki → <b>Znacznik poziomu sygnału</b>: po włączeniu kliknięcie na wykresie stawia poziomy kursor (maks. 2, przesuwalny); w ramce wyświetlana jest wartość sygnału w pasie pod linią i różnica ΔY.</p>
""" + _img("wykres_poziom_sygnalu") + """
<p>Znaczniki (punkt, zakres, różnica sygnału) opisuje rozdział „Znaczniki i wyszukiwanie w danych”.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 18
    s.append(("18. Pasek podglądu", """
<h2>Pasek podglądu (mały wykres na dole)</h2>
<ul>
<li>Pokazuje <b>całą nagraną historię</b> (do ok. 2 mln próbek na kartę; starsze próbki są przycinane).</li>
<li><b>Żółty obszar</b> to fragment widoczny na wykresie głównym. Przeciągnij go, aby przesunąć widok, albo rozciągnij jego brzegi, aby zmienić okno czasu.</li>
<li>Wysokość paska zmieniasz, chwytając poziomy pasek podziału między wykresami (ustawienie jest zapamiętywane).</li>
<li>Jak często i z ilu punktów pasek jest przeliczany – Ustawienia → Renderowanie wykresu.</li>
</ul>
""" + _img("okno_glowne", "Pasek podglądu to dolny wykres z żółtym zaznaczeniem widocznego okna")))

    # ------------------------------------------------------------------------------------------------------------ 19
    s.append(("19. Przyciski sterujące i znaczników", """
<h2>Przyciski sterujące pod wykresem</h2>
""" + _img("przyciski_sterujace") + _table([
        ("Start", "Łączy ze sterownikiem i rozpoczyna zbieranie danych (wymaga poprawnego IP i co najmniej jednego pobieranego sygnału). Pyta o nazwę konfiguracji tylko wtedy, gdy ma być zapisany plik z jej nazwą w szablonie."),
        ("Stop", "Kończy połączenie. Dane pozostają na wykresie."),
        ("Pauza / Wznów", "Wstrzymuje widok (zbieranie trwa) i wraca do trybu na żywo."),
        ("Reset / Auto-Reset", "Kliknięcie czyści bufor i wykres. Przytrzymany 4 s zamienia się w „Auto-Reset”: każdy kolejny Start zaczyna wykres od nowa (szczegóły niżej)."),
        ("● REC", "Włącza ciągłe nagrywanie według panelu „Nagrywanie REC”. Po naciśnięciu program w tle sprawdza serwer bazy; gdy nie odpowiada, od razu pokazuje przyczynę („Przerwij REC” albo kontynuuj – dane czekają w buforze na dysku)."),
    ]) + _imgs(("przyciski_pauza", "Pauza włączona (przycisk „Wznów” świeci na żółto)"), ("przyciski_rec_aktywny", "REC aktywny – miga czerwona kropka"),
        ("przyciski_reset_odliczanie", "Reset przytrzymany 2 s: odliczanie „Reset (2s)”"), ("przyciski_auto_reset", "Auto-Reset załączony: przycisk wciśnięty, niebieski tekst")) + """
<h3>Start po Stop: przerwa w wykresie, Reset i Auto-Reset</h3>
<p>Domyślnie (Auto-Reset <b>wyłączony</b>) ponowny <b>Start</b> po <b>Stop</b> <b>nie czyści wykresu</b>: oś czasu biegnie dalej, a między ostatnią próbką sprzed Stop a pierwszą po Start
powstaje <b>przerwa (dziura) w krzywych</b> równa czasowi, który minął między Stop i Start (stara wartość nie jest „przedłużana” przez przerwę). Na początku i końcu przerwy wykres stawia numerowane, kropkowane znaczniki <b>Stop odczytu (n)</b> i <b>Start odczytu (n)</b> (włączane razem ze znacznikami REC w Znaczniki → Wygląd znaczników…). Znaczniki, znaczniki REC i przybliżanie wykresu zachowują swoje położenie.
<br><b>Przerwa na wykresie – trzy sposoby</b> (Widok → <b>Przerwy Stop → Start (ta karta)</b>, osobno dla każdej karty): <b>pusta przerwa w pełnej długości</b> (domyślnie); <b>wycięcie</b> – pauza nie zajmuje miejsca, krzywe się stykają, w tym miejscu stoi jeden znacznik <b>Stop / Start odczytu (n)</b>, a opisy osi czasu przeskakują („30 s | 50 s”); <b>stała szerokość</b> – pauza to półprzezroczysty pas o szerokości ustawionej w pikselach (pozycja <b>Szerokość przerwy [px]…</b>, 8 – 300), z długością pauzy wypisaną w pasie, znacznikami Stop i Start odczytu na jego brzegach i jednym opisem osi „30 s | 50 s” pośrodku; szerokość pasa nie zależy ani od czasu pauzy, ani od przybliżenia. Dane, nagrania i znaczniki zostają na prawdziwym czasie – zmienia się tylko rysowanie; okno czasu liczy się w czasie zeskanowanym (w trybie stałej szerokości – wraz z pasami).
Wykres jest kontynuowany tylko wtedy, gdy pobierane są <b>te same sygnały</b> (nazwa, adres, typ; kolor czy wysokość pasma mogą się zmienić) i na karcie nie ma wczytanego nagrania – w przeciwnym razie Start zaczyna wykres od nowa.</p>
<p><b>Reset</b> (przycisk po lewej od REC): <b>kliknięcie</b> czyści bufor i wykres. Gdy odczyt trwa, program <b>pyta o potwierdzenie</b> i o oś czasu: <b>Wyczyść i zeruj oś czasu</b> (wykres rusza od 0 s, nowy czas początkowy), <b>Wyczyść (oś czasu biegnie dalej)</b> albo <b>Anuluj</b>.
Jeśli w tym czasie trwa <b>REC</b>, nagrywanie <b>nie jest przerywane</b> – dalej zapisuje się do bazy / pliku wszystko, co odczytuje program (czyszczony jest tylko wykres, a znaczniki Start REC / Stop REC zostają na swoich czasach); wtedy oś czasu musi biec dalej (przycisk zerowania osi jest niedostępny), żeby nagranie miało ciągłe czasy.
Gdy połączenie pracuje i oś biegnie dalej, czas płynie (REC i znaczniki zachowują swoje czasy) i wykres zapełnia się od tej chwili;
na zatrzymanej karcie wykres zaczyna się od zera. Jeśli są zapisane znaczniki, które istnieją tylko dla czyszczonego bufora, program pyta, czy je usunąć.</p>
<p><b>Auto-Reset</b>: przytrzymaj Reset. Po 1 s pojawia się odliczanie <b>Reset (3s) → (2s) → (1s)</b>, a po 4 s przycisk zostaje wciśnięty jako <b>Auto-Reset</b> (niebieski tekst, tło bez zmian). Od tej chwili
<b>każdy Start czyści wykres</b> i zaczyna go od nowa (tak działał program dawniej). Puszczenie przycisku w trakcie odliczania <b>anuluje</b> (nic się nie dzieje); kliknięcie „Auto-Reset” wyłącza go (nie czyści wykresu).
Ustawienie jest zapamiętywane przy karcie.</p>
<h3>Kolory przycisków</h3>
<p>Wszystkie kolory ustawisz w Ustawienia → Interfejs. Ustawienia fabryczne:</p>
<table border="1" cellspacing="0" cellpadding="6">
<tr><th>Stan</th><th>Wygląd</th><th>Kiedy</th></tr>
<tr><td>Wyłączony (wszystkie)</td><td>""" + _swatch("#3a3a3a", "#e8e8e8", "Przycisk") + """</td><td>stan spoczynkowy</td></tr>
<tr><td>Start załączony</td><td>""" + _swatch("#3a3a3a", "#ffe600", "Start") + """</td><td>połączenie aktywne</td></tr>
<tr><td>Stop załączony</td><td>""" + _swatch("#3a3a3a", "#b01818", "Stop") + """</td><td>połączenie zatrzymane</td></tr>
<tr><td>Pauza załączona</td><td>""" + _swatch("#f2d600", "#000000", "Wznów") + """</td><td>widok wstrzymany</td></tr>
<tr><td>REC załączony</td><td>""" + _swatch("#ff8c1a", "#ffffff", "<span style='color:#ff2020'>●</span> REC") + """</td><td>trwa zapis; kropka miga (domyślnie 0,5 Hz)</td></tr>
<tr><td>Auto-Reset załączony</td><td>""" + _swatch("#3a3a3a", "#4da3ff", "Auto-Reset") + """</td><td>każdy Start czyści wykres; tło jak przycisku wyłączonego, zmienia się tylko kolor tekstu</td></tr>
</table>
<h2>Przyciski znaczników i okien</h2>
""" + _img("przyciski_znacznikow") + _img("przyciski_znacznikow_robocze", "Przy znacznikach roboczych „Zapisz znaczniki” staje się aktywny i pokazuje ich liczbę") + _table([
        ("Dodaj znacznik", "Zakłada znacznik na najnowszej próbce (na żywo) albo w środku widocznego zakresu."),
        ("Lista znaczników…", "Okno z listą znaczników."),
        ("Zapisz znaczniki", "Zapisuje zmiany robocze (wyszarzony, gdy nie ma czego zapisać)."),
        ("Szukaj w danych…", "Wyszukiwarka wartości."),
    ]) + _img("przyciski_sygnaly_diagnostyka") + _table([
        ("Sygnały…", "Okno konfiguracji sygnałów (rozdział „Okno Sygnały do śledzenia”). Działa także podczas pracy."),
        ("Diagnostyka…", "Okno diagnostyki połączenia (Ctrl+D)."),
    ])))

    # ------------------------------------------------------------------------------------------------------------ 20
    s.append(("20. Znaczniki i wyszukiwanie w danych", """
<h2>Znaczniki i wyszukiwanie w danych</h2>
<p>Znaczniki to adnotacje do wykresu: trzymają <b>czas bezwzględny</b>, więc pasują do wykresu na żywo, nagrania z bazy i pliku CSV. Leżą w osobnym pliku
(<tt>Dokumenty\\S7Trace\\markers.db</tt>), nigdy w nagraniach.</p>
""" + _img("wykres_znaczniki", "Znaczniki na wykresie: punktowy, zakres czasu (półprzezroczysty obszar) i różnica sygnału") + _img("okno_glowne_znaczniki", "Całe okno ze znacznikami roboczymi (do zapisania)") + """
<h3>Rodzaje</h3>
<ul>
<li><b>Punkt</b> – pionowa linia w jednej chwili.</li>
<li><b>Zakres czasu</b> – półprzezroczysty obszar między dwiema chwilami.</li>
<li><b>Różnica sygnału</b> – dla <b>jednego</b> sygnału: poziomy na obu końcach i różnica wartości.</li>
</ul>
<p>Znacznik może dotyczyć wszystkich przebiegów albo tylko wybranych; ma tytuł, opis, uwagi, kolor, priorytet, grupę, grubość i rodzaj linii, przezroczystość obszaru,
opcję pokazywania nazwy na wykresie, autora oraz daty założenia i modyfikacji.</p>
""" + _img("menu_znacznik", "Prawy przycisk na znaczniku") + _table([
        ("Edycja…", "Okno właściwości znacznika (niżej)."),
        ("Zmień pozycję znacznika", "Domyślnie znaczniki są <b>zablokowane</b> – przeciągnięcie przesuwa wykres. Po zaznaczeniu tej pozycji (można odznaczyć) znacznik można przeciągać myszą."),
        ("Pokaż / ukryj nazwę", "Etykieta znacznika na wykresie."),
        ("Grupy, cofnięcie, usunięcie", "Przypisanie do grupy znaczników, cofnięcie zmiany, usunięcie (robocze do zapisania)."),
    ]) + _img("okno_znacznik_edycja", "Okno edycji znacznika") + """
<h3>Zapis roboczy</h3>
<p>Wszystko, co robisz ze znacznikami, jest <b>robocze</b> (oznaczone gwiazdką), dopóki nie klikniesz <b>Zapisz znaczniki</b>. Zapis jest jedną operacją na bazie. Przy zamykaniu karty
lub programu z niezapisanymi znacznikami pojawia się wykaz zmian (Zapisz / Odrzuć / Wróć).</p>
""" + _img("okno_zapis_znacznikow", "Wykaz niezapisanych zmian: nowe, zmienione (z nazwami zmienionych pól), do usunięcia") + """
<h3>Lista znaczników</h3>
""" + _img("okno_lista_znacznikow") + """
<p>Kolumna <b>Zapis</b> pokazuje, do którego nagrania w bazie należy znacznik, albo <b>bufor (bez zapisu)</b> – znacznik istnieje wtedy tylko dla danych widocznych na wykresie. Przy tworzeniu znacznik dostaje
nagranie, które obejmuje jego czas (trwające REC, wczytane nagranie albo wcześniejszy zapis tego przebiegu); znaczniki leżące w obszarze „Manual REC” po jego zapisie oraz w fragmencie dopisanym przez „Zmień Start REC”
przechodzą do tego nagrania. Lista ma filtr <b>Zapis</b> (każdy / tylko bufor / tylko z nagraniem).</p>
""" + _img("okno_lista_znacznikow_zapis", "Lista z kolumną „Zapis”: nagrania i bufor") + """
<p>Przycisk <b>Usuń bez zapisu…</b> usuwa zapisane znaczniki bez nagrania (poza tymi, których wykres jest otwarty na jakiejś karcie) – to sposób na sprzątanie po zakończeniu programu przez system,
zanim zdążył zapytać o nie sam.</p>
<p>Znaczniki bez nagrania nie mają dokąd prowadzić, gdy znika bufor wykresu. Dlatego program <b>pyta</b>, czy je usunąć: przy zamykaniu karty lub programu, przy ponownym Start (bufor jest czyszczony)
i przy wczytywaniu nagrania zamiast wykresu. <b>Usuń znaczniki</b> kasuje je, <b>Zostaw</b> zostawia, trzeci przycisk wraca do wykresu (albo przerywa Start / wczytanie).
Pytanie nie pojawia się, gdy inna karta ma to samo połączenie. Przy trwałym usuwaniu nagrania (kosz → „Usuń trwale”) program pyta też, co zrobić z jego znacznikami.</p>
""" + _img("okno_znaczniki_bez_zapisu", "Pytanie przy zamykaniu karty ze znacznikami tylko dla bufora") + """
<p>Tabela ma ten sam standard co wszystkie tabele programu (rozdział „Tabele – jeden standard”): sortowanie po kliknięciu nagłówka, regulacja szerokości kolumn, naprzemienne cieniowanie wierszy.
Pole wyszukiwania filtruje po tytule, opisie, uwagach, autorze, grupie i kolorze. Pozycje robocze są oznaczone kolorem (nowe, zmienione, usunięte – przekreślone).</p>
<h3>Szukaj w danych</h3>
""" + _img("okno_szukaj") + """
<p>Wyszukiwarka wartości: sygnały o zadanej wartości, w przedziale, ze zmianą albo zboczem (do 3 warunków naraz – <b>wszystkie</b> muszą być spełnione w tej samej chwili; opcjonalnie minimalny czas trwania)
w danych bieżącego wykresu albo w wybranym nagraniu z bazy. Wynik pokazuje początek, czas trwania i wartości; „Pokaż” przechodzi na wykresie do wyniku, „Dodaj znacznik…” zakłada w tym miejscu znacznik.
Można też przejść do wpisanej daty i godziny.</p>
<h3>Znaczniki REC: Start REC, Stop REC, Manual REC</h3>
<p>Oprócz zwykłych znaczników wykres sam zaznacza, <b>kiedy w przebiegu włączono i wyłączono nagrywanie</b>. W jednym przebiegu (od Start do Stop połączenia) REC można włączać wiele razy,
dlatego linie są numerowane: <b>Start REC (1)</b>, <b>Stop REC (1)</b>, <b>Start REC (2)</b>, <b>Stop REC (2)</b> i tak dalej. Początkowy kolor to kolor tła załączonego przycisku REC (pomarańczowy);
kolor, grubość i rodzaj linii oraz samo włączenie tych znaczników ustawiasz w <b>Znaczniki → Wygląd znaczników…</b>. Znaczniki REC nie trafiają do pliku znaczników – wynikają z przebiegu nagrań
i znikają po ponownym Start. Okres między <b>Start REC (n)</b> a <b>Stop REC (n)</b> jest dodatkowo zaznaczony <b>półprzezroczystym obszarem</b> w tym samym kolorze (przezroczystość – jak przy Manual REC).</p>
""" + _img("wykres_rec_znaczniki", "Linie Start / Stop REC (numerowane) i ręczny obszar „Manual REC” (z lewej, półprzezroczysty)") + """
<h4>Manual REC – nagranie z już zebranych danych</h4>
<p>Gdy nagrywanie włączono za późno, a potrzebny fragment jest już na wykresie: zatrzymaj wykres (<b>Pauza</b>), przesuń go w potrzebne miejsce, kliknij prawym przyciskiem i wybierz
<b>Manual Start REC (n) tutaj</b>; potem w drugim miejscu <b>Manual Stop REC (n) tutaj</b>. Między liniami pojawia się półprzezroczysty obszar (podobny do znacznika zakresu czasu). Prawy przycisk na obszarze
otwiera menu: <b>Zapis Manual REC (n)</b> zapisuje ten fragment danych z bufora wykresu jako <b>osobne nagranie</b> (do bazy wybranej w panelu REC albo do pliku CSV), <b>Zmień pozycję</b> pozwala przeciągać brzegi, <b>Przenieś Manual REC (n)</b> (też <b>Przenieś Manual Start REC (n)</b> w menu pustego wykresu, gdy czeka sam początek) pokazuje <b>pulsującego „ducha”</b> linii początku – przeciągnij go w nowe miejsce i wybierz prawym przyciskiem na nim <b>Przenieś … tutaj</b> albo <b>Anuluj przenoszenie</b> (usuwa ducha); <b>Usuń</b> kasuje obszar. Na końcu menu zapisanego obszaru stoi informacja „zapisano: …” i pozycja <b>Otwórz Manual REC (n): nagranie …</b>, która otwiera zapisane nagranie (z zapytaniem: ta karta / nowa karta).
Gdy ten sam, niezmieniony obszar zapisujesz <b>drugi raz</b>, program pyta, czy na pewno zapisać dokładnie to samo nagranie jeszcze raz (przesunięcie obszaru unieważnia zapis, wtedy pytania nie ma).
Obszarów może być wiele naraz.</p>
""" + _img("menu_wykres_manual", "Prawy przycisk na pustym wykresie: Manual Start REC / Manual Stop REC") + _img("menu_manual_rec", "Prawy przycisk na obszarze Manual REC") + """
<p>Obszary czekające na zapis liczą się do przycisku <b>Zapisz znaczniki (n)</b>. Okno zapisu wylicza je w osobnej tabeli z polami wyboru – zaznaczone obszary zostaną zapisane jako nagrania
(to samo okno pokazuje się przy zamykaniu karty).</p>
""" + _img("okno_zapis_rec", "Okno „Zapisz znaczniki” z obszarem Manual REC do zapisania") + """
<h4>Przesunięcie Start REC (zmiana początku nagrania)</h4>
<p>Jeśli nagrywanie już trwa (albo się skończyło), a początek miał być wcześniej lub później: kliknij prawym przyciskiem linię <b>Start REC (n)</b> i wybierz <b>Przesuń Start REC (n)…</b>.
Wykres się zatrzymuje, a obok linii pojawia się jej <b>pulsujący „duch”</b> (zmienia kolor na biały i z powrotem). Przeciągnij go w nowe miejsce, kliknij na nim prawym przyciskiem i wybierz <b>Zmień Start REC (n)</b>.</p>
""" + _img("menu_rec_start", "Menu linii Start REC (n)") + _img("wykres_rec_duch", "Pulsujący duch znacznika Start REC (2) przeciągnięty w lewo") + _img("menu_rec_duch", "Menu ducha") + """
<ul>
<li><b>Wcześniej</b>: brakujący fragment (od nowego początku do dotychczasowego) jest <b>dopisywany do nagrania w bazie</b> z bufora wykresu – nagranie od razu jest dłuższe. Ogranicza to wielkość bufora: dalej niż sięgają zebrane dane nagrania nie da się uzupełnić.</li>
<li><b>Później</b>: dane nagrania sprzed nowego początku są <b>usuwane z bazy</b> (program prosi o potwierdzenie – tego nie da się cofnąć); stan sygnałów w nowym początku zostaje zachowany.</li>
<li>Działa dla <b>baz danych</b> (SQLite, InfluxDB, TimescaleDB) – także w trakcie nagrywania. Plik <b>CSV</b> jest zapisywany na bieżąco i nie da się go uzupełnić z przodu, więc dla CSV pozycja jest wyłączona
(Manual REC do CSV działa, bo tworzy nowy plik). W TimescaleDB usuwanie z bardzo starych, skompresowanych fragmentów może wymagać nowszej wersji bazy.</li>
</ul>
<h3>Wygląd linii</h3>
""" + _img("okno_wyglad_znacznikow") + """
<p>Menu Znaczniki → Wygląd znaczników…: cztery grubości linii (grubość 0 w znaczniku oznacza „z ustawień”) oraz wygląd znaczników REC: czy rysować Start / Stop REC, kolor, grubość i rodzaj linii, nieprzezroczystość obszaru Manual REC.
Ustawienia są częścią motywu interfejsu (zapisują się w pliku konfiguracji interfejsu; w Web – na koncie).</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 21
    s.append(("21. Okno „Sygnały do śledzenia”", """
<h2>Okno „Sygnały do śledzenia”</h2>
""" + _img("okno_sygnaly_stop", "Okno przy zatrzymanym połączeniu – wszystkie kolumny edytowalne") + """
<p>Każdy wiersz to jedna zmienna. Podczas pracy połączenia można <b>dodawać nowe zmienne</b> (pobierane od następnego cyklu, w starszych próbkach mają przerwę);
adres, pole „Pobierz”, kolejność i usuwanie istniejących wierszy zmienisz po Stop.</p>
""" + _img("okno_sygnaly_praca", "Przy działającym połączeniu: kolumna „Aktualna wartość” pokazuje wartości na żywo, adresy są zablokowane") + _table([
        ("(numer wiersza)", "Chwyć numer i przeciągnij wiersz w inne miejsce, aby zmienić kolejność (po Stop)."),
        ("Pobierz ✓", "Zaznaczona zmienna jest czytana z PLC (trafia do CSV i na wykres). Odznaczona – nie jest czytana."),
        ("Wykres ✓", "Zaznaczona zmienna jest rysowana na wykresie i w legendzie (można zmieniać także podczas pracy)."),
        ("Nazwa", "Dowolna nazwa. Powtórzone nazwy mają <span style='background-color:#9a2a2a;color:#fff'>&nbsp;czerwone&nbsp;</span> tło."),
        ("Aktualna wartość", "Bieżąca wartość (gdy zmienna jest pobierana), w formacie z kolumny „Sposób wyświetlania”."),
        ("Sposób wyświetlania", "Format wartości: Domyślnie, Dziesiętnie, HEX (<tt>16#…</tt>), BIN (<tt>2#…_…</tt>), TRUE/FALSE, Naukowo."),
        ("Źródło", "I (wejścia), Q (wyjścia), M (znaczniki), DB (blok danych); dla innych metod: OPC, WEB, MBH / MBI / MBC / MBD."),
        ("Typ", "BOOL, BYTE, SINT, USINT, WORD, INT, UINT, DWORD, DINT, UDINT, REAL, LREAL."),
        ("DB / Bajt / Bit", "Adres bezwzględny: numer DB (tylko dla źródła DB), numer bajtu, numer bitu (tylko BOOL). Powtórzony adres jest podświetlony <span style='background-color:#c9b030'>&nbsp;na żółto&nbsp;</span>."),
        ("Węzeł OPC / nazwa (Web API)", "NodeId (OPC UA) albo nazwa zmiennej (Web API) – dla S7comm nieaktywne."),
        ("Offset Y", "Przesunięcie krzywej w pionie (układ „Offset + Gain”)."),
        ("Gain", "Mnożnik wartości na wykresie (surowa wartość w tabeli i w triggerze pozostaje bez zmian)."),
        ("Share", "Udział sygnału w wysokości osi pionowej (układ „Pasma wg Share”). Sygnał ze Share = 2 ma pasmo dwa razy wyższe niż ze Share = 1."),
        ("Kolor", "Kolor krzywej – kliknij, by wybrać."),
        ("Opis", "Dowolny komentarz; pokazuje się w podpowiedzi wiersza i legendy."),
    ], ("Kolumna", "Znaczenie")) + """
<p><b>Sortowanie:</b> kliknij nagłówek kolumny, aby uporządkować wiersze po jej wartościach (ponowne kliknięcie odwraca kolejność; strzałka w nagłówku pokazuje kierunek). Sortowanie jest <b>widokowe</b> –
nie zmienia kolejności sygnałów na wykresie (ta wynika z numeru wiersza). Można je stosować także podczas pracy. Pola z listą rozwijaną i kolory w tabeli nie sortują się „tekstowo”, ale według swoich wartości.</p>
<h3>Przyciski</h3>
""" + _table([
        ("Dodaj", "Dopisuje nowy wiersz zawsze na końcu listy. Nazwa i adres kontynuują wiersz, w którym stoi kursor (<tt>D160B</tt> → <tt>D160C</tt>, <tt>123M1</tt> → <tt>123M2</tt>); zajęte nazwy są pomijane."),
        ("Z symboli…", "Dodaje zmienne z zaimportowanych symboli (okno poniżej)."),
        ("Z OPC UA…", "Przeglądarka drzewa zmiennych serwera OPC UA (aktywna przy metodzie OPC UA)."),
        ("Usuń", "Usuwa zaznaczone wiersze (podczas pracy – tylko dopiero co dodane)."),
        ("Zapisz listę… / Wczytaj listę…", "Zapis / odczyt samej listy zmiennych do pliku .json (przy wczytaniu: zastąp lub dołącz)."),
        ("Z innej karty…", "Kopiuje zmienne z innej karty."),
    ], ("Przycisk", "Opis")) + _img("okno_symbole", "Wybór z zaimportowanych symboli (filtr po nazwie lub adresie; tabela sortowana jak wszystkie") + """
<h3>Menu prawego przycisku na nagłówku kolumny</h3>
""" + _img("menu_naglowek_kolumny") + """
<ul>
<li><b>Ukryj kolumnę / Pokaż kolumnę</b> – dowolna kolumna (ustawienie jest zapamiętywane).</li>
<li><b>Offset Y</b>: „Skoryguj wszystkie Offset Y” (układa wszystkie wiersze od 0 według kroku) i „Zmień Offset Y…” (krok dla nowych zmiennych).</li>
<li><b>Nazwa</b>: auto-numerowanie włącz / wyłącz; nazwa z poprzedniej zmiennej albo własna (np. <tt>SIG1</tt>, <tt>SIG2</tt>…).</li>
</ul>
<p>Najechanie kursorem na wiersz pokazuje wszystkie dane zmiennej: adres, opis i aktualną wartość.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 22
    s.append(("22. Tabele – jeden standard", """
<h2>Tabele – jeden standard w całym programie</h2>
<p>Wszystkie tabele programu (Sygnały do śledzenia, Przegląd nagrań, Lista znaczników, wyniki wyszukiwania, Aktywne sesje, Zaległe bufory, wyniki kreatora, diagnostyka)
zachowują się i wyglądają tak samo:</p>
""" + _img("okno_przeglad_nagran", "Wzorzec: okno „Przegląd nagrań”") + _table([
        ("Nagłówek", "Kliknięcie sortuje tabelę po kolumnie (strzałka pokazuje kierunek; ponowne kliknięcie odwraca). Liczby i daty sortują się jako liczby i daty, a nie jako tekst (np. „2” przed „10”)."),
        ("Szerokość kolumn", "Chwyć krawędź nagłówka i przeciągnij. Ostatnia kolumna wypełnia resztę szerokości. Przy otwarciu kolumny są dopasowane do zawartości (nie szerzej niż ok. 380 px)."),
        ("Wiersze", "Naprzemienne cieniowanie: jasny / ciemny wiersz (nieparzyste i parzyste mają osobne kolory)."),
        ("Wartości", "Wartości w komórkach są pogrubione, nazwy parametrów – zwykłą czcionką; tekst ma stały wcięcie od lewej krawędzi (12 px), żeby nie dotykał ramki."),
        ("Ramka", "Cienka linia o kolorze „ramki tabeli”."),
        ("Klawiatura i mysz", "Strzałki, Home / End, PgUp / PgDn przesuwają zaznaczenie; kliknięcie zaznacza wiersz, Ctrl / Shift – wiele wierszy (tam, gdzie to ma sens)."),
    ], ("Cecha", "Zachowanie")) + """
<p>Kolory nagłówka, wierszy parzystych i nieparzystych oraz ramki zmienisz w <b>Ustawienia → Interfejs</b> (rozdział „Interfejs: kolory, czcionka, tabele”) – dotyczy to także trybu Web.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 23
    s.append(("23. Pasek statusu", """
<h2>Pasek statusu</h2>
""" + _img("pasek_statusu", "Pasek statusu: komunikat o połączeniu") + """
<p>Pasek na dole okna pokazuje komunikaty programu: stan połączenia, ścieżkę pliku REC / triggera, wynik eksportu, ostrzeżenia (np. o różnicy zegara PLC)
oraz <b>status nagrywania</b>. Liczby łącza i systemu są w zakładkach „System” / „Sieć” na dole lewego panelu.</p>
""" + _img("pasek_statusu_3_wiersze", "Kilka komunikatów w kilku liniach (liczba linii jest ustawiana)") + _img("pasek_statusu_rec", "Pasek podczas nagrywania REC") + """
<h3>Przesuwanie tekstu</h3>
<p>Tekst, który się nie mieści, <b>chwyć myszą i przeciągnij</b> w lewo / prawo (albo kółkiem myszy): w skrajnych położeniach koniec tekstu dochodzi do prawej krawędzi paska, a początek do lewej –
tekst nie ucieka poza pasek. Przy większej liczbie linii tekst przeciąga się w górę / w dół.</p>
<h3>Menu prawego przycisku na pasku</h3>
""" + _img("menu_pasek_statusu", "Menu paska statusu") + _table([
        ("Maksymalna liczba wierszy", "Pasek ma wysokość tylko tylu linii, ile potrzebuje tekst, nie więcej niż wybrana liczba (podmenu z listą liczb)."),
        ("Kolor tła…", "Kolor tła paska."),
        ("Kolor tekstu…", "Kolor tekstu paska."),
        ("Justowanie tekstu", "Rozwija się na <b>do lewej</b> i <b>do prawej</b> – położenie tekstu na pasku."),
    ]) + _imgs(("menu_pasek_wiersze", "Podmenu „Maksymalna liczba wierszy”"), ("menu_pasek_justowanie", "Podmenu „Justowanie tekstu”: do lewej / do prawej")) + """
<p>Te same ustawienia są w Ustawienia → Interfejs i zapisują się w pliku konfiguracji interfejsu oraz (w trybie Web) w ustawieniach konta.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 24
    s.append(("24. Diagnostyka połączenia", """
<h2>Diagnostyka połączenia (przycisk „Diagnostyka…”, menu Diagnostyka, Ctrl+D)</h2>
<p>Okno pokazuje na żywo (odświeżanie co 0,5 s) pełne statystyki łącza z bieżącą kartą i można je trzymać otwarte obok wykresu.
Na górze jest <b>ocena łącza</b> (Bardzo dobre / Dobre / Przeciętne / Słabe / Brak połączenia) wraz z <b>bargrafem</b> o 10 segmentach, lista konkretnych spostrzeżeń
i zaleceń (np. „zwiększ cykl do ≥ 41 ms”). Statystyki zerują się przy każdym Start; po Stop zostają widoczne do następnego Start.</p>
<h3>Zakładka „Opóźnienia”</h3>
""" + _img("okno_diagnostyka_opoznienia") + _table([
        ("Czas odczytu PLC", "Ile trwa jeden pełny cykl odczytu (wysłanie żądań i odebranie odpowiedzi) w ms: wartość <b>chwilowa</b>, średnia z ostatnich 10 s i 60 s, średnia od startu, min, max, odchylenie standardowe oraz percentyle P95 i P99."),
        ("Okres próbkowania", "Odstęp czasu między kolejnymi próbkami – powinien być równy ustawionemu cyklowi. Odchylenia to jitter."),
        ("Ping ICMP (RTT)", "Czas odpowiedzi samej sieci na ping do adresu sterownika, bez udziału protokołu S7."),
        ("Histogram", "Procent odczytów w przedziałach czasu (0–2, 2–5, 5–10 … ≥1000 ms) – pokazuje, czy opóźnienia są stałe, czy zdarzają się rzadkie piki."),
    ], ("Wielkość", "Znaczenie")) + """
<h3>Zakładka „Pakiety i niezawodność”</h3>
""" + _img("okno_diagnostyka_pakiety") + _table([
        ("Odebrane próbki / pominięte cykle [%]", "Pominięty cykl to taki, który minął, zanim skończył się poprzedni odczyt."),
        ("Odczyty dłuższe niż cykl", "Liczba i procent odczytów, które trwały dłużej niż ustawiony cykl."),
        ("Błędy odczytu / ponowne połączenia", "Liczba utraconych połączeń lub nieudanych odczytów i udanych powrotów, wraz z treścią ostatniego błędu."),
        ("Czas przerw / dostępność [%]", "Łączny czas bez połączenia i procent czasu, w którym łącze działało."),
        ("Czas nawiązania połączenia", "Jak długo trwało ostatnie połączenie z PLC (TCP + negocjacja S7)."),
        ("Ping: wysłane / odebrane / utracone", "Liczba pakietów ICMP i procent utraconych – wskaźnik <b>utraty pakietów w sieci</b>."),
    ], ("Wielkość", "Znaczenie")) + """
<p><b>Uwaga:</b> program nie widzi pojedynczych pakietów TCP – utratę na poziomie S7 pokazują błędy odczytu i zerwania połączenia, a utratę pakietów w sieci – ping ICMP
(jeśli zapora lub router blokuje ICMP, ping pokaże 100% utraty mimo działającego S7).</p>
<h3>Zakładka „Przepustowość”</h3>
""" + _img("okno_diagnostyka_przepustowosc") + _table([
        ("Częstotliwość oczekiwana / rzeczywista / maksymalna", "1000 / cykl, faktycznie osiągane próbkowanie oraz teoretyczny limit przy średnim czasie odczytu."),
        ("Zalecany najkrótszy cykl", "P99 czasu odczytu + 25% zapasu – poniżej tego cykl będzie często pomijany."),
        ("Dane na cykl / żądań na cykl", "Liczba bajtów i żądań S7 w jednym cyklu (zależy od sygnałów i trybu komunikacji)."),
        ("Przepustowość danych, żądania/s", "Faktyczny przepływ danych użytkowych ze sterownika."),
        ("Ruch w sieci – szacunek [kb/s]", "Dane plus ok. 150 B nagłówków na parę żądanie/odpowiedź – wartość orientacyjna."),
    ], ("Wielkość", "Znaczenie")) + """
<h3>Zakładka „Wykresy w czasie”</h3>
""" + _img("okno_diagnostyka_wykresy") + """
<p>Czas odczytu PLC i ping ICMP w funkcji czasu (zakres: 10 s … 60 min; dla zakresów powyżej 2 min wykres czasu odczytu pokazuje maksimum z każdej sekundy) z zaznaczonym ustawionym cyklem (czerwona linia).
Piki powyżej linii cyklu oznaczają pomijane próbki.</p>
<h3>Przyciski</h3>
""" + _table([
        ("Ping ICMP do sterownika", "Włącza wysyłanie jednego pingu na sekundę (nie zajmuje połączenia S7, więc nie obciąża sterownika). Działa także bez Start."),
        ("Test portu TCP…", "Jednorazowo łączy się z portem S7 (102 lub podanym po „:”) i mierzy czas – sprawdza routing i zaporę."),
        ("Resetuj statystyki", "Zeruje liczniki bez przerywania połączenia."),
        ("Kopiuj raport / Zapisz raport…", "Pełny raport tekstowy (ocena, wszystkie wartości) do schowka lub pliku – do dołączenia do zgłoszenia serwisowego."),
    ], ("Przycisk", "Działanie"))))

    # ------------------------------------------------------------------------------------------------------------ 25
    s.append(("25. Zapis do baz danych i przegląd nagrań", """
<h2>Zapis do baz danych i przegląd nagrań</h2>
<p>Poza plikiem CSV nagrywanie REC może pisać do bazy. Cel wybierasz w panelu „Nagrywanie REC” (pole „Zapis do”); ustawienia celu: przycisk „…” albo
Ustawienia → Zapis nagrań w bazach danych…. Pełny opis baz jest w pliku <tt>BAZY_DANYCH.md</tt>.</p>
<h3>Cele zapisu</h3>
""" + _table([
        ("Plik CSV", "Domyślny. Kolumny <tt>time_s</tt>, <tt>timestamp</tt> i po jednej na sygnał; w komentarzach <tt># signal:</tt> definicje sygnałów, <tt># device:</tt> dane sterownika."),
        ("SQLite", "Plik bazy na dysku (lokalnie, bez serwera). Obsługuje rotację plików (np. dobowo)."),
        ("InfluxDB 1.x / 2.x", "Baza szeregów czasowych przez HTTP (protokół liniowy). Dostępność sygnału trafia do pola <tt>&lt;sygnał&gt;__ok</tt> (Influx nie ma NaN)."),
        ("TimescaleDB (PostgreSQL)", "Serwer SQL; opcjonalna kompresja po zadanej liczbie dni (skompresowanych fragmentów nie da się łatwo usuwać)."),
    ], ("Cel", "Opis")) + """
<h3>Okno ustawień bazy</h3>
""" + _imgs(("okno_baza_sqlite_karta1", "SQLite – zakładka „Połączenie”"), ("okno_baza_sqlite_karta3", "Zakładka „Nagrania i użytkownicy”"), ("okno_baza_influx", "InfluxDB – adres, token, organizacja, bucket"),
            ("okno_baza_timescale", "TimescaleDB – serwer, baza, użytkownik, hasło, kompresja")) + """
<p>Hasła i tokeny są zapisywane w konfiguracji <b>tylko</b>, gdy zaznaczysz „Zapamiętaj”. Przycisk „Testuj połączenie” sprawdza serwer.</p>
<h3>Czasy i bufory</h3>
""" + _img("okno_baza_sqlite_karta2") + """
<p>Każdy parametr ma w oknie dokładny opis i wartość domyślną. Najważniejsze: <b>pełny stan co N minut</b> (w trybie zmian – domyślnie 10), wysyłka paczek (ok. 0,5 s),
ponawianie i limity czasu, <b>kolejka w pamięci</b> i <b>bufor na dysku</b> (lokalna kolejka SQLite, opróżniana po powrocie serwera; zaległe pliki dosyła kolejne uruchomienie albo okno
Diagnostyka → Zaległe bufory…), rotacja SQLite, kompresja TimescaleDB, limit punktów odczytu (przerzedzanie do min / max z przedziału).</p>
<h3>Zaległe bufory zapisu</h3>
""" + _img("okno_bufory_zapisu", "Diagnostyka → Zaległe bufory zapisu do baz…") + """
<p>Gdy serwer bazy był niedostępny, dane czekają w lokalnym buforze na dysku. Program dosyła je sam przy następnym nagraniu do tej samej bazy; w tym oknie można to zrobić od razu
(<b>Wyślij teraz</b>) albo usunąć bufor (<b>Usuń bufor</b>). Kolumny: nagranie, cel, liczba wpisów, rozmiar, „Ta baza?” (czy bufor pasuje do aktualnie wybranej bazy). Tabela ma standard opisany w rozdziale „Tabele – jeden standard”.</p>
<h3>Tytuł i opis nagrania</h3>
""" + _img("okno_opis_nagrania") + """
<p>Każde nagranie w bazie ma <b>tytuł, opis, uwagi, tagi, właściciela</b> (konto Windows), komputer i <b>dane sterownika</b> (model, numer katalogowy, firmware, numer seryjny, nazwa stacji).
Kiedy program pyta o tytuł, ustawia pole <b>Nazwa nagrania</b> na zakładce „Nagrania i użytkownicy”: <b>Na początku</b> (okno z tytułem, uwagami i tagami przed startem; Anuluj = bez nagrywania), <b>W trakcie</b> (nagrywanie rusza od razu, okno można wypełnić w dowolnej chwili), <b>Na końcu</b> (pytanie przy zatrzymaniu REC) albo <b>Nie pytaj</b> (tytuł nadasz później we Właściwościach). Pole <b>Przegląd nagrań pokazuje</b> decyduje, czy lista zawiera tylko Twoje nagrania, czy wszystkie.</p>
<h3>Przegląd nagrań</h3>
""" + _img("okno_przeglad_nagran") + _table([
        ("Baza / Ustawienia… / Odśwież listę", "Wybór bazy, jej ustawienia i ponowny odczyt listy."),
        ("Szukaj", "Filtruje po tytule, uwagach, tagach, konfiguracji, użytkowniku."),
        ("Pokaż", "Moje nagrania / wszystkie / wybrany użytkownik."),
        ("Kosz", "Pokazuje usunięte nagrania (przywracanie, usunięcie na stałe, retencja)."),
        ("Grupuj po dniach", "Nagłówki dni w liście."),
        ("Tylko zakres czasu", "Wczytanie tylko wybranego fragmentu nagrania (bardzo długie nagrania są przerzedzane do min / max z przedziału)."),
        ("Właściwości… / Sterownik… / Usuń", "Edycja tytułu, opisu, uwag i tagów; dane sterownika zapisane w nagraniu; przeniesienie do kosza."),
        ("Zapisz jako CSV…", "Eksportuje wszystkie wiersze nagrania do pliku."),
        ("Wczytaj", "Otwiera nagranie na wykresie tej lub nowej karty (adres, rack / slot, metoda i dane sterownika są przejmowane z nagrania)."),
    ], ("Element", "Działanie"))))

    # ------------------------------------------------------------------------------------------------------------ 26
    s.append(("26. Renderowanie wykresu", """
<h2>Ustawienia → Renderowanie wykresu</h2>
""" + _img("okno_renderowanie") + """
<p>Wszystko, co decyduje o obciążeniu procesora przez wykres, jest regulowane (zmiany działają od razu, „Anuluj” je cofa, „Domyślne” przywraca ustawienia oszczędne):</p>
<ul>
<li><b>odświeżanie</b> (Hz, domyślnie 20) – jak często wykres jest przerysowywany;</li>
<li><b>nie rysuj niewidocznych kart</b> – dane, trigger i REC działają dalej;</li>
<li><b>maks. punktów krzywej</b> – rozdzielczość krzywych;</li>
<li><b>punkty</b> – limit próbek w oknie, przy którym znaczniki są jeszcze rysowane, i ich rozmiar (przy większej liczbie pasek statusu informuje, że punkty są ukryte);</li>
<li><b>wykres przeglądowy</b> – jak często i z ilu punktów jest przeliczany;</li>
<li><b>wygładzanie linii</b> (antyaliasing).</li>
</ul>
<p>Na mocniejszym komputerze wartości można podkręcić; gdy „GUI lag” w zakładce „System” rośnie – zmniejszyć.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 27
    s.append(("27. Interfejs: kolory, czcionka, tabele", """
<h2>Ustawienia → Interfejs</h2>
""" + _img("okno_interfejs", "Okno „Interfejs – kolory i czcionka” (początek listy kolorów)") + """
<ul>
<li><b>Profil kolorów</b>: Ciemny, Jasny, Systemowy (zgodny z trybem Windows, przełącza się na żywo) lub Własny (ustawia się sam po ręcznej zmianie koloru).</li>
<li><b>Kolory</b>: tło okna i paneli, tekst, okienka edycyjne, przyciski, karty (w tym aktywna), kolor zaznaczenia, wykres oraz <b>przyciski sterujące</b> (Start, Stop, Pauza, REC, znaczniki – tło i tekst w każdym stanie, kolor kropki REC).</li>
<li><b>Tabele</b> – siedem kolorów wspólnych dla wszystkich tabel: <b>tło i czcionka nagłówka</b>, <b>tło i czcionka wierszy nieparzystych</b>, <b>tło i czcionka wierszy parzystych</b> oraz <b>kolor ramki tabeli</b>.
Starsze pliki konfiguracji bez tych kolorów dostają wartości wyliczone z dotychczasowych kolorów tabeli.</li>
</ul>
""" + _img("okno_interfejs_dol", "Dalsza część okna: czcionka, miganie REC, pasek statusu, belki podziału") + """
<ul>
<li><b>Czcionka</b>: rodzaj i rozmiar. <b>REC: częstotliwość migania</b> kropki (domyślnie 0,5 Hz).</li>
<li><b>Pasek statusu</b>: maksymalna liczba linii, kolor tła i tekstu, justowanie tekstu.</li>
<li><b>Nazwy sygnałów na wykresie</b>: „Legenda (ramka z listą)” albo „Opisy przy sygnałach” (rozdział „Wykres główny”).</li>
<li><b>Belki zmiany rozmiaru</b> (między panelem a wykresem i nad wykresem przeglądowym): kolor oraz „zawsze widoczne” – domyślnie belka jest cienka i pojawia się dopiero po najechaniu kursorem.</li>
<li>Zmiany widać na żywo; <b>Anuluj</b> przywraca poprzedni wygląd, <b>Domyślne</b> – ustawienia fabryczne.</li>
</ul>
<h3>Zapisane konfiguracje</h3>
<p>„Zapisz jako…” zapisuje wygląd do pliku .json (każdy parametr w osobnej linii) w <tt>%APPDATA%\\S7Trace\\interfejs\\</tt>; zapisane wybierasz z listy (także w Ustawienia → Zapisane konfiguracje interfejsu).
„Wczytaj z pliku…” otwiera plik z dowolnego miejsca. W pliku jest też <b>wygląd linii znaczników</b>, układ lewego panelu (kolejność, zwinięcia, ukryte elementy) i ustawienia paska statusu;
plik starszej wersji bez któregoś parametru zostawia bieżącą wartość.</p>
<p>W trybie Web te same ustawienia (kolory tabel, pasek statusu, układ panelu) są zapamiętywane <b>osobno dla każdego konta</b> na serwerze.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 28
    s.append(("28. Sesje i serwer Web", """
<h2>Aktywne sesje programu i serwer Web</h2>
<h3>Aktywne sesje programu (ten komputer)</h3>
""" + _img("okno_sesje") + """
<p>Lista programów S7Trace uruchomionych na tym komputerze przez wszystkich użytkowników Windows (także sesje RDP): kto, w której sesji Windows, od kiedy, która karta skanuje, który sterownik i od kiedy.
Lista odświeża się na żywo; wpis znika po zamknięciu programu (po ok. 10 s od ostatniego sygnału). Przy Start na sterownik, który już skanuje inny użytkownik, program <b>tylko ostrzega</b> (nie blokuje).</p>
<h3>Serwer Web</h3>
""" + _img("okno_serwer_web") + _table([
        ("Zgłaszaj sesję temu serwerowi", "Program raportuje serwerowi, kto go uruchomił i które sterowniki skanuje – wspólny rejestr dla wielu komputerów."),
        ("Adres serwera", "Adres centralnego serwera Web (np. <tt>https://serwer:8080</tt>)."),
        ("Token", "Token programu wystawiony przez administratora na stronie „Użytkownicy” serwera."),
        ("Sprawdzaj certyfikat serwera", "Odznacz tylko dla certyfikatu samopodpisanego."),
        ("Test połączenia", "Sprawdza adres i token."),
    ]) + """
<p>Dzięki temu ostrzeżenie przed Start działa także wtedy, gdy ten sam sterownik skanuje ktoś na innym komputerze.</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 29
    s.append(("29. Tryb Web", """
<h2>Tryb Web (centralny serwer)</h2>
<p>Poza programem desktopowym dostępny jest <b>serwer Web</b> (<tt>python -m s7trace.web</tt> albo <tt>Web-Serwer.bat</tt> w pakiecie): te same wykresy, nagrywanie, triggery, znaczniki i przegląd nagrań
w przeglądarce, bez instalacji programu na stanowisku. Pełny opis: plik <tt>WEB.md</tt>.</p>
<ul>
<li><b>Konta i role</b>: wyświetlający &lt; operator &lt; administrator; logowanie hasłem lub kontem Windows / AD (SSO).</li>
<li><b>Przegląd połączeń</b>, wykres na żywo (kanał SSE), Start / Stop, edycja połączeń i sygnałów, trigger, REC, pliki i cele baz (definiowane przez administratora).</li>
<li><b>Przegląd nagrań</b> z uprawnieniami wg właściciela i roli, kosz i retencja.</li>
<li><b>Zasada zgodności</b>: każda zmiana w programie desktopowym jest powielana w trybie Web – etykieta „Auto: …” w polu Metoda, podmenu paska statusu, sortowanie tabel po kliknięciu nagłówka, kolory tabel,
układ i ukrywanie pól panelu, pomoc „?” (te same teksty).</li>
</ul>
<p>Znane, zamierzone różnice względem programu desktopowego wymienia <tt>WEB.md</tt> (rozdział 15).</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 30
    s.append(("30. Metody połączenia i kreator", """
<h2>Metody połączenia i kreator połączenia</h2>
<p>Program potrafi czytać sterowniki czterema metodami. Metodę wybierasz w <b>Ustawienia → Metoda połączenia…</b> (per karta) albo zostawiasz <b>Automatycznie</b> –
przy każdym Start program sam rozpoznaje, co działa, a pole <b>Metoda</b> w panelu „Połączenie” pokazuje wynik (np. <b>Auto: S7comm (snap7, PUT/GET)</b>).</p>
""" + _img("okno_metoda_polaczenia", "Okno „Metoda połączenia” (S7comm / automatycznie)") + _table([
        ("S7comm (snap7)", "Najszybsza. Adres bezwzględny (I, Q, M, DB + bajt/bit). S7-1200/1500 wymagają PUT/GET i DB bez „Optimized block access”."),
        ("OPC UA", "Zmienne po nazwie (także zoptymalizowane). Źródło sygnału „OPC”, w polu „Węzeł” NodeId, np. <tt>ns=3;s=\"DB_Piec\".\"Temp\"</tt>. Przycisk „Z OPC UA…” w oknie Sygnały otwiera przeglądarkę drzewa zmiennych serwera."),
        ("Web API", "JSON-RPC po HTTP(S). Źródło „WEB”, w polu „Węzeł” nazwa zmiennej. Eksperymentalne – nietestowane na prawdziwym sterowniku."),
        ("Modbus TCP", "Rejestry i cewki udostępnione przez program PLC. Źródła MBH (rejestry holding), MBI (rejestry wejściowe), MBC (cewki), MBD (wejścia dyskretne); „Bajt” = numer rejestru / cewki, „DB” = Unit ID (0 = domyślny z ustawień)."),
    ], ("Metoda", "Opis")) + _imgs(("okno_metoda_opcua", "Ustawienia OPC UA: port, tryb zabezpieczeń, logowanie, certyfikat klienta"),
                                    ("okno_metoda_webapi", "Ustawienia Web API: port, użytkownik, hasło"),
                                    ("okno_metoda_modbus", "Ustawienia Modbus TCP: port i Unit ID")) + """
<h3>Tryb automatyczny – kolejność rozpoznawania</h3>
<ol><li>Ping ICMP (informacyjnie) i sprawdzenie portów TCP: 102, 4840, 443, 502 (równolegle).</li>
<li><b>S7comm</b>: połączenie (próby rack/slot 0/1, 0/2, 0/0, 1/2, 0/3), identyfikacja CPU, odczyt testowy pamięci M i kilku DB.</li>
<li><b>OPC UA</b>: pobranie listy zabezpieczeń i trybów logowania serwera, próba sesji, odczyt informacji o serwerze i jego czasu.</li>
<li><b>Web API</b>: zapytanie <tt>Api.Version</tt> (JSON-RPC).</li><li><b>Modbus TCP</b>: odczyt rejestru 0.</li></ol>
<p>Używana jest <b>pierwsza działająca</b> metoda zgodna ze źródłami sygnałów w karcie. Jeśli sygnały są S7, a działa tylko OPC UA, program informuje, że trzeba zmienić źródło sygnałów
albo włączyć PUT/GET. Gdy nic nie działa – kreator pokazuje raport z zaleceniem, <b>jaka metoda jest sugerowana</b> i co zmienić w TIA Portal.</p>
<h3>Kreator połączenia i dane o sterowniku</h3>
""" + _img("okno_kreator_wyniki", "Kreator: wynik każdego testu (✔ działa / ▲ ostrzeżenie / ✖ błąd)") + _imgs(
        ("okno_kreator_karta2", "Zakładka „Sterownik i czas”"), ("okno_kreator_karta3", "Zakładka „Ograniczenia i blokady”")) + """
<p>Na górze okna kreator podaje <b>zalecaną metodę</b>. Przyciski: <b>Uruchom ponownie</b> (powtarza wszystkie testy), <b>Użyj zalecanej metody</b> (ustawia ją w karcie) i <b>Kopiuj raport</b>. Wiersz „pominięto” oznacza, że test nie miał sensu (np. port zamknięty).</p>
<p>Zakładka „Sterownik i czas” – <b>rodzina, model CPU, numer katalogowy (MLFB), firmware, numer seryjny, nazwa stacji, stan CPU (Run/Stop), poziom ochrony</b>, dane serwera OPC UA oraz
<b>czas sterownika i różnica względem czasu komputera</b> (osobno do czasu lokalnego i do UTC – sterowniki często pracują w UTC). Raport można skopiować do schowka.</p>
<h3>Dane logowania</h3>
<p>OPC UA: dostęp anonimowy lub użytkownik / hasło; tryby zabezpieczone wymagają certyfikatu klienta (przycisk „Generuj certyfikat klienta…” tworzy parę plików w
<tt>%APPDATA%\\S7Trace\\certyfikaty</tt>; certyfikat trzeba zatwierdzić w sterowniku). Web API: użytkownik i hasło. Hasło jest zapisywane w konfiguracji <b>tylko</b>, gdy zaznaczysz „Zapamiętaj hasło” (jawnym tekstem).</p>
"""))

    # ------------------------------------------------------------------------------------------------------------ 31
    s.append(("31. Ograniczenia, blokady i wymagania", """
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
<li><b>S7comm:</b> """ + _limits("s7") + """</li>
<li><b>OPC UA:</b> """ + _limits("opcua") + """</li>
<li><b>Web API:</b> """ + _limits("webapi") + """</li>
<li><b>Modbus TCP:</b> """ + _limits("modbus") + """</li>
</ul>
<h3>Ograniczenia systemowe i sieciowe</h3>
<ul><li>""" + "</li><li>".join(__import__("s7trace.core.detect", fromlist=["SYSTEM_LIMITS"]).SYSTEM_LIMITS) + """</li>
<li>Windows Server 2016 / pakiet przenośny: biblioteki OPC UA (asyncua, cryptography) są dołączone; brak połączenia z internetem nie przeszkadza.</li>
<li>W jednej karcie wszystkie pobierane sygnały muszą używać jednej metody (np. tylko OPC); do łączenia kilku metod użyj osobnych kart.</li>
<li>Gdy pierwsze sprawdzenie portów trwa długo, zapora lub router „gubi” pakiety zamiast je odrzucać – test czeka do 1,5 s na port.</li>
</ul>
"""))

    # ------------------------------------------------------------------------------------------------------------ 32
    s.append(("32. Pliki CSV i skróty klawiszowe", """
<h2>Pliki CSV</h2>
<p>Pliki zawierają kolumny <tt>time_s</tt> (sekundy od startu), <tt>timestamp</tt> (data i godzina) i po jednej kolumnie na sygnał; w komentarzach <tt># signal:</tt> zapisane są definicje sygnałów.
Puste pole = brak danych (przerwa w połączeniu lub zmienna dodana później). Zapis „tylko zmiany stanu” zawiera wiersz tylko wtedy, gdy któraś wartość się zmieniła.</p>
<p>Znaczniki w nazwach plików (zapis wyzwolony triggerem i REC): <tt>{confname}</tt> – nazwa konfiguracji, <tt>{ip}</tt> – adres IP sterownika, <tt>{tab}</tt> – nazwa karty, <tt>{date}</tt> – data, <tt>{time}</tt> – godzina.</p>
<h2>Skróty klawiszowe</h2>
""" + _table([
        ("Ctrl+T", "Nowa karta"), ("Ctrl+W", "Zamknij kartę"), ("F2", "Zmień nazwę karty"),
        ("Ctrl+0", "Dopasuj widok do całości"), ("Ctrl+D", "Diagnostyka połączenia"),
        ("Ctrl+M", "Lista znaczników"), ("Ctrl+Shift+M", "Dodaj znacznik"), ("Ctrl+Shift+S", "Zapisz znaczniki"), ("Ctrl+F", "Szukaj w danych"),
        ("F1", "Pomoc – opis programu"), ("Shift+F1", "Tryb pomocy „?”"), ("Ctrl+Q", "Wyjście"),
    ], ("Skrót", "Działanie")) + """
<h2>Jak odtworzyć zdjęcia w tej pomocy</h2>
<p>Wszystkie rysunki są zdjęciami działającego programu (uruchomionego na symulatorze sterownika) – nie są rysowane ręcznie. Po zmianie wyglądu programu wystarczy uruchomić
<tt>python tools/make_help_images.py</tt>, a zdjęcia w <tt>s7trace\\help\\img</tt> zostaną wygenerowane od nowa.</p>
"""))
    return s
