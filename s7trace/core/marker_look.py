"""Look of the marker lines on the chart (Znaczniki -> Wygląd znaczników): line widths for the different cases. A marker with its own
width (> 0) keeps it; markers with width 0 ('wg ustawień') use these values. Saved in the UI section of the config."""
from __future__ import annotations

# key -> (label, min, max, unit, default, description)
PARAMS: dict[str, tuple] = {
    "width_all": ("Linia: znacznik dla wszystkich przebiegów", 1, 12, "px", 2,
                  "Grubość linii znacznika (punktu i brzegów zakresu czasu), gdy w parametrze „Dotyczy” ma on „wszystkie przebiegi”. "
                  "Dotyczy znaczników, którym nie ustawiono własnej grubości."),
    "width_sel": ("Linia: wybrane przebiegi", 1, 12, "px", 3,
                  "Grubość linii znacznika w pasach przebiegów, które wskazano w parametrze „Dotyczy” (układ „Pasma wg Share”)."),
    "width_other": ("Linia: pozostałe przebiegi (cienka prowadnica)", 1, 12, "px", 1,
                    "Grubość cienkiej linii, która przechodzi przez pasy przebiegów NIE wskazanych w „Dotyczy” – tylko jako prowadnica "
                    "(półprzezroczysta), żeby było widać, gdzie leży znacznik."),
    "width_hover": ("Linia: podświetlona po najechaniu myszą", 1, 16, "px", 4,
                    "Grubość linii znacznika, gdy najedziesz na nią kursorem (punkt i brzegi zakresu mają ten sam standard). "
                    "Podświetlona linia zachowuje kolor znacznika."),
}
ORDER = list(PARAMS)
DEFAULTS: dict = {k: v[4] for k, v in PARAMS.items()}


def normalize(d) -> dict:
    """Every key present and inside its limits (unknown / invalid values fall back to the defaults)."""
    out = dict(DEFAULTS)
    if isinstance(d, dict):
        for k, (_label, lo, hi, _unit, default, _desc) in PARAMS.items():
            v = d.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = int(min(max(v, lo), hi))
    return out
