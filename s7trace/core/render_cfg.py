"""Settings of the chart rendering (Ustawienia -> Renderowanie wykresu): everything that decides how much CPU the chart
needs. Defaults are the economical ones; on a faster computer they can be raised. Saved in the UI section of the config."""
from __future__ import annotations

# key -> (label, min, max, unit, default, description). bool defaults have no limits.
PARAMS: dict[str, tuple] = {
    "fps": ("Odświeżanie wykresu", 1, 60, "Hz", 20,
            "Ile razy na sekundę wykres jest przerysowywany. Odczyt ze sterownika działa niezależnie (własnym cyklem), więc "
            "mniej klatek nie gubi danych – wykres tylko rzadziej nadąża za ostatnią próbką. Obciążenie procesora rośnie "
            "proporcjonalnie do tej liczby."),
    "pause_hidden": ("Nie rysuj niewidocznych kart", None, None, "", True,
                     "Karta, której nie widać (inna karta na wierzchu albo zminimalizowane okno), nie przelicza wykresu. Dane są "
                     "nadal zbierane, trigger i REC działają, a po powrocie wykres jest od razu aktualny."),
    "curve_points": ("Maks. punktów krzywej", 500, 100_000, "pkt", 6000,
                     "Ile punktów ma najwyżej jedna krzywa na wykresie głównym. Więcej danych jest zmniejszane (dla każdego przedziału "
                     "zostaje minimum i maksimum, więc szpilki nie znikają). Mniej = szybciej, ale mniej szczegółów."),
    "points_max": ("Punkty: limit w oknie", 0, 20_000, "pkt", 800,
                   "Przycisk „Punkty” rysuje znaczniki próbek tylko wtedy, gdy w widocznym oknie jest ich najwyżej tyle na sygnał "
                   "(po przybliżeniu). Przy większej liczbie rysowanie kropek bardzo obciąża procesor i niczego nie pokazuje. "
                   "0 = punkty nigdy nie są rysowane."),
    "point_size": ("Punkty: rozmiar", 1, 12, "px", 4,
                   "Średnica znacznika próbki. Mniejsze kropki rysują się szybciej."),
    "overview_s": ("Wykres przeglądowy: odświeżanie co", 0.2, 30.0, "s", 1.0,
                   "Jak często przeliczany jest pasek podglądu całego nagrania. Przeliczenie obejmuje całą zebraną historię, więc "
                   "przy długich nagraniach to najdroższa operacja – im rzadziej, tym lżej."),
    "overview_points": ("Wykres przeglądowy: maks. punktów", 200, 20_000, "pkt", 2000,
                        "Ile punktów ma najwyżej jedna krzywa na pasku podglądu."),
    "antialias": ("Wygładzanie linii", None, None, "", False,
                  "Wygładza krawędzie linii (ładniejsze skosy). Zwiększa obciążenie procesora; wyłączone jest szybsze."),
}
ORDER = list(PARAMS)
DEFAULTS: dict = {k: v[4] for k, v in PARAMS.items()}


def normalize(d) -> dict:
    """Every key present and inside its limits (unknown / invalid values fall back to the defaults)."""
    out = dict(DEFAULTS)
    if isinstance(d, dict):
        for k, (_label, lo, hi, _unit, default, _desc) in PARAMS.items():
            v = d.get(k)
            if isinstance(default, bool):
                if isinstance(v, bool):
                    out[k] = v
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = type(default)(min(max(v, lo), hi))
    return out
