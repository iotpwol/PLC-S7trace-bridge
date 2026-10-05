"""Look of the marker lines on the chart (Znaczniki -> Wygląd znaczników): line widths for the different cases. A marker with its own
width (> 0) keeps it; markers with width 0 ('wg ustawień') use these values. Saved in the UI section of the config.

The same dialog holds the look of the REC marks ('Start REC (n)' / 'Stop REC (n)' lines the chart draws by itself when the recording starts /
stops, and the area of a 'Manual REC'): switched on / off, colour, width, line style, opacity of the manual area."""
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
    "rec_show": ("Znaczniki Start REC / Stop REC na wykresie", 0, 1, "", 1,
                 "Gdy włączone, wykres sam rysuje linię „Start REC (n)” w chwili załączenia nagrywania i „Stop REC (n)” w chwili jego "
                 "wyłączenia. Numer n rośnie przy każdym kolejnym załączeniu REC w tym przebiegu (od Start do Stop połączenia). "
                 "Ręczne obszary „Manual REC” są pokazywane zawsze (stawia je użytkownik)."),
    "rec_width": ("Linie REC: grubość", 1, 12, "px", 2, "Grubość linii „Start REC” / „Stop REC” i brzegów obszaru „Manual REC”."),
    "rec_opacity": ("Obszar „Manual REC”: nieprzezroczystość", 0, 100, "%", 24,
                    "Jak mocno zabarwiony jest obszar między „Manual Start REC” a „Manual Stop REC” (podobnie jak znacznik zakresu czasu)."),
}
FLAGS = ("rec_show",)                                  # 0 / 1 values shown as a check box
# text values: key -> (label, default, description)
STRINGS: dict[str, tuple] = {
    "rec_color": ("Linie REC: kolor", "#ff8c1a", "Kolor znaczników Start REC / Stop REC i obszaru Manual REC. Początkowo taki jak tło załączonego przycisku REC."),
    "rec_style": ("Linie REC: rodzaj linii", "solid", "Rodzaj linii znaczników Start REC / Stop REC: ciągła, kreskowana, kropkowana albo kreska-kropka."),
}
STYLES = ("solid", "dash", "dot", "dashdot")
ORDER = list(PARAMS)
DEFAULTS: dict = {**{k: v[4] for k, v in PARAMS.items()}, **{k: v[1] for k, v in STRINGS.items()}}


def _color_ok(c) -> bool:
    if not isinstance(c, str) or len(c) != 7 or c[0] != "#":
        return False
    try:
        int(c[1:], 16)
    except ValueError:
        return False
    return True


def normalize(d) -> dict:
    """Every key present and inside its limits (unknown / invalid values fall back to the defaults)."""
    out = dict(DEFAULTS)
    if isinstance(d, dict):
        for k, (_label, lo, hi, _unit, default, _desc) in PARAMS.items():
            v = d.get(k)
            if isinstance(v, bool):
                v = int(v)
            if isinstance(v, (int, float)):
                out[k] = int(min(max(v, lo), hi))
        c = d.get("rec_color")
        if _color_ok(c):
            out["rec_color"] = c.lower()
        if d.get("rec_style") in STYLES:
            out["rec_style"] = d["rec_style"]
    return out
