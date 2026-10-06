"""Configurable look of the application (colours + font), applied through palette + stylesheet."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QEvent, QObject, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView

from ..core import marker_look, panel_cfg
from ..core.config import app_dir

# key -> (label shown in the 'Interfejs' dialog, default dark colour)
COLOR_KEYS: dict[str, tuple[str, str]] = {
    "window_bg": ("Tło okna", "#2b2b2b"),
    "panel_bg": ("Tło paneli (ramki grup)", "#303030"),
    "text": ("Tekst", "#d0d0d0"),
    "edit_bg": ("Tło okienek edycyjnych", "#1e1e1e"),
    "edit_text": ("Tekst okienek edycyjnych", "#f0f0f0"),
    "button_bg": ("Tło przycisków", "#3a3a3a"),
    "button_text": ("Tekst przycisków", "#e8e8e8"),
    "table_bg": ("Tło tabeli", "#262626"),
    "table_text": ("Tekst tabeli", "#e0e0e0"),
    "header_bg": ("Kolor tła nagłówka tabeli", "#333333"),
    "header_text": ("Kolor czcionki nagłówka tabeli", "#d0d0d0"),
    "row_odd_bg": ("Kolor tła wierszy nieparzystych", "#262626"),
    "row_odd_text": ("Kolor czcionki wierszy nieparzystych", "#e0e0e0"),
    "row_even_bg": ("Kolor tła wierszy parzystych", "#2f2f2f"),
    "row_even_text": ("Kolor czcionki wierszy parzystych", "#e0e0e0"),
    "table_border": ("Kolor ramki tabeli", "#454545"),
    "menu_bg": ("Tło menu", "#2b2b2b"),
    "menu_text": ("Tekst menu", "#e0e0e0"),
    "tab_bg": ("Tło kart (zakładek)", "#333333"),
    "tab_selected": ("Aktywna karta: tło", "#1e66c8"),
    "tab_selected_text": ("Aktywna karta: tekst", "#ffe600"),
    "accent": ("Kolor zaznaczenia", "#2a82da"),
    "bar": ("Belki zmiany rozmiaru paneli: kolor", "#2a82da"),
    "status_bg": ("Pasek statusu: tło", "#2b2b2b"),
    "status_text": ("Pasek statusu: tekst", "#d0d0d0"),
    "plot_bg": ("Tło wykresu", "#000000"),
    "plot_fg": ("Osie i opisy wykresu", "#d0d0d0"),
    # control buttons under the chart
    "ctl_bg": ("Przyciski sterujące (wyłączone): tło", "#3a3a3a"),
    "ctl_text": ("Przyciski sterujące (wyłączone): tekst", "#e8e8e8"),
    "start_on_bg": ("Start załączony: tło", "#3a3a3a"),
    "start_on_text": ("Start załączony: tekst", "#ffe600"),
    "stop_on_bg": ("Stop załączony: tło", "#3a3a3a"),
    "stop_on_text": ("Stop załączony: tekst", "#b01818"),
    "pause_on_bg": ("Pauza załączona: tło", "#f2d600"),
    "pause_on_text": ("Pauza załączona: tekst", "#000000"),
    "rec_on_bg": ("REC załączony: tło", "#ff8c1a"),
    "rec_on_text": ("REC załączony: tekst", "#ffffff"),
    "rec_dot": ("REC: migająca kropka", "#ff2020"),
    "reset_on_bg": ("Auto-Reset załączony: tło", "#3a3a3a"),
    "reset_on_text": ("Auto-Reset załączony: tekst", "#4da3ff"),
    "mark_on_bg": ("V / H znacznik, Punkty załączone: tło", "#2a82da"),
    "mark_on_text": ("V / H znacznik, Punkty załączone: tekst", "#000000"),
    "help_on_bg": ("Przycisk „?” (tryb pomocy włączony): tło", "#ff9800"),
    "help_on_text": ("Przycisk „?” (tryb pomocy włączony): tekst", "#000000"),
}

DARK = {k: v[1] for k, v in COLOR_KEYS.items()}
DARK.update(profile="dark", font_family="", font_size=9, rec_blink_hz=0.5, bar_always=False, status_lines=1, status_align="right", legend_style="legend")

LIGHT = dict(DARK)
LIGHT.update(
    window_bg="#f0f0f0", panel_bg="#e6e6e6", text="#202020", edit_bg="#ffffff", edit_text="#101010",
    button_bg="#e1e1e1", button_text="#101010", table_bg="#ffffff", table_text="#101010",
    header_bg="#dcdcdc", header_text="#202020", row_odd_bg="#ffffff", row_odd_text="#101010", row_even_bg="#eeeeee",
    row_even_text="#101010", table_border="#c0c0c0", menu_bg="#f0f0f0", menu_text="#101010", tab_bg="#dcdcdc",
    tab_selected="#2a82da", tab_selected_text="#ffe600", accent="#2a82da", plot_bg="#ffffff", plot_fg="#303030",
    ctl_bg="#e1e1e1", ctl_text="#101010", start_on_bg="#e1e1e1", start_on_text="#8a6d00",
    stop_on_bg="#e1e1e1", stop_on_text="#a01010", pause_on_bg="#f2d600", pause_on_text="#000000",
    rec_on_bg="#ff8c1a", rec_on_text="#ffffff", rec_dot="#e01010", mark_on_bg="#2a82da", mark_on_text="#000000",
    reset_on_bg="#e1e1e1", reset_on_text="#0a58c8",
    status_bg="#f0f0f0", status_text="#202020", profile="light")

PRESETS = {"Ciemny (domyślny)": DARK, "Jasny": LIGHT}

# colour profile: dark / light follow the presets, system follows the Windows app mode, custom = own colours
PROFILES = [("dark", "Ciemny"), ("light", "Jasny"), ("system", "Systemowy"), ("custom", "Własny")]
PROFILE_KEYS = [k for k, _ in PROFILES]


def system_is_dark() -> bool:
    """Windows 'app mode' (Qt >= 6.5); older systems without a dark mode report light."""
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def profile_colors(profile: str) -> dict:
    """Colours of a built-in profile ('custom' -> none)."""
    if profile == "system":
        profile = "dark" if system_is_dark() else "light"
    preset = {"dark": DARK, "light": LIGHT}.get(profile)
    return {k: preset[k] for k in COLOR_KEYS} if preset else {}


def normalize(theme: dict | None) -> dict:
    """Theme with every key present and valid."""
    out = dict(DARK)
    for k, v in (theme or {}).items():
        if k in COLOR_KEYS and isinstance(v, str) and QColor(v).isValid():
            out[k] = v
    if theme:
        miss = lambda k: not (isinstance(theme.get(k), str) and QColor(theme[k]).isValid())
        if miss("header_text"):
            out["header_text"] = out["text"]
        if miss("row_odd_bg"):
            out["row_odd_bg"] = out["table_bg"]
        if miss("row_odd_text"):
            out["row_odd_text"] = out["table_text"]
        if miss("row_even_bg"):
            out["row_even_bg"] = alt_row(out["row_odd_bg"])
        if miss("row_even_text"):
            out["row_even_text"] = out["table_text"]
        if miss("table_border"):
            out["table_border"] = QColor(out["text"]).darker(250).name() if QColor(out["window_bg"]).lightness() < 128 else QColor(out["text"]).lighter(400).name()
    prof = (theme or {}).get("profile")
    out["profile"] = prof if prof in PROFILE_KEYS else ("custom" if theme else "dark")
    out.update(profile_colors(out["profile"]))       # dark / light / system override the stored colours
    if theme:
        out["font_family"] = str(theme.get("font_family", "") or "")
        try:
            out["font_size"] = max(6, min(32, int(theme.get("font_size", 9))))
        except (TypeError, ValueError):
            pass
        try:
            out["rec_blink_hz"] = max(0.1, min(5.0, float(theme.get("rec_blink_hz", 0.5))))
        except (TypeError, ValueError):
            pass
        out["bar_always"] = bool(theme.get("bar_always", False))      # the resize bars stay visible (not only under the mouse)
        try:
            out["status_lines"] = max(1, min(10, int(theme.get("status_lines", 1))))   # most lines of the status bar
        except (TypeError, ValueError):
            pass
        out["status_align"] = "left" if theme.get("status_align") == "left" else "right"       # justification of the status bar text
        out["legend_style"] = "labels" if theme.get("legend_style") == "labels" else "legend"   # signal names: legend box / labels at the signals
    # the look of the marker lines belongs to the interface configuration (saved in a profile file, switched with it)
    out["marker_look"] = marker_look.normalize((theme or {}).get("marker_look"))
    # and so does the layout of the left panel (order of the groups, folded groups, the bottom tab)
    out["panel"] = panel_cfg.normalize((theme or {}).get("panel"))
    return out


# ----------------------------------------------------- saved configurations (.json, one parameter per line)
def profiles_dir() -> str:
    d = os.path.join(app_dir(), "interfejs")
    os.makedirs(d, exist_ok=True)
    return d


def list_profiles() -> list[tuple[str, str]]:
    """(name, path) of every *.json in the configurations folder, sorted by name."""
    d = profiles_dir()
    return sorted(((os.path.splitext(f)[0], os.path.join(d, f)) for f in os.listdir(d)
                   if f.lower().endswith(".json")), key=lambda x: x[0].lower())


def save_profile(path: str, theme: dict) -> None:
    t = normalize(theme)
    ordered = {"profile": t["profile"], "font_family": t["font_family"], "font_size": t["font_size"],
               "rec_blink_hz": t["rec_blink_hz"], "bar_always": t["bar_always"],
               "status_lines": t["status_lines"], "status_align": t["status_align"], "legend_style": t["legend_style"]}
    ordered.update({k: t[k] for k in COLOR_KEYS})
    ordered.update({"marker_" + k: v for k, v in t["marker_look"].items()})          # one flat parameter per line
    ordered.update({"panel_" + k: v for k, v in t["panel"].items()})
    with open(path, "w", encoding="utf-8") as f:
        f.write("{\n" + ",\n".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in ordered.items()) + "\n}\n")   # one parameter per line


def load_profile(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("plik nie zawiera konfiguracji interfejsu")
    look = {k[len("marker_"):]: v for k, v in data.items() if k.startswith("marker_")}
    panel = {k[len("panel_"):]: v for k, v in data.items() if k.startswith("panel_")}
    t = normalize({**data, "marker_look": look, "panel": panel})
    if not look:                                     # a file of an older version: leave the current marker look as it is
        t.pop("marker_look")
    if not panel:                                    # (and the layout of the left panel)
        t.pop("panel")
    return t


def _disabled(c: str) -> str:
    col = QColor(c)
    col.setAlpha(110)
    return f"rgba({col.red()},{col.green()},{col.blue()},{col.alpha()})"


def alt_row(table_bg: str) -> str:
    """Colour of every second table row: a little lighter than a dark table, a little darker than a light one."""
    c = QColor(table_bg)
    return (c.lighter(125) if c.lightness() < 128 else c.darker(107)).name()


def build_qss(t: dict) -> str:
    return f"""
QMainWindow, QDialog {{ background: {t['window_bg']}; }}
QGroupBox {{ border: 1px solid rgba(128,128,128,90); border-radius: 3px; margin-top: 14px; padding-top: 6px;
    background: {t['panel_bg']}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; top: -2px; color: {t['text']}; }}
QLabel {{ color: {t['text']}; padding-left: 3px; }}
QLabel[val="true"] {{ font-weight: bold; }}
QCheckBox {{ color: {t['text']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {t['edit_bg']}; color: {t['edit_text']}; border: 1px solid rgba(128,128,128,110);
    border-radius: 2px; padding: 2px 4px 2px 10px; selection-background-color: {t['accent']}; }}    /* one left margin for all edit fields and drop-downs */
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {_disabled(t['edit_text'])}; }}
QComboBox {{ padding-left: 11px; }}                      /* optically level with the spin boxes */
QLineEdit[invalid="true"], QComboBox[invalid="true"] {{ border: 1px solid #e04040; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit, QDateTimeEdit, QComboBox, QComboBox QAbstractItemView {{ font-weight: bold; }}    /* values are bold */
QComboBox QAbstractItemView {{ background: {t['edit_bg']}; color: {t['edit_text']};
    selection-background-color: {t['accent']}; }}
QPushButton {{ background: {t['button_bg']}; color: {t['button_text']}; border: 1px solid rgba(128,128,128,110);
    border-radius: 2px; padding: 4px 12px; }}
QPushButton:hover {{ border-color: {t['accent']}; }}
QPushButton:pressed, QPushButton:checked {{ background: {t['accent']}; color: #ffffff; }}
QPushButton:disabled {{ color: {_disabled(t['button_text'])}; }}
QToolButton {{ background: {t['button_bg']}; color: {t['button_text']}; border: 1px solid rgba(128,128,128,110);
    border-radius: 2px; padding: 2px 8px; }}
QToolButton#helpBtn:checked {{ background: {t['help_on_bg']}; color: {t['help_on_text']}; font-weight: bold; }}   /* help mode is on */
QListWidget {{ background: {t['table_bg']}; color: {t['table_text']}; }}
QTableWidget {{ background: {t['row_odd_bg']}; color: {t['row_odd_text']}; gridline-color: {t['table_border']};
    alternate-background-color: {t['row_even_bg']}; border: 1px solid {t['table_border']}; }}      /* rows alternate: odd / even (text colour of the even ones: IndentDelegate) */
QTableWidget::item {{ padding-left: 0px; }}                 /* the text indent is IndentDelegate's job (CELL_INDENT) */
QListWidget::item {{ padding-left: 6px; }}
QHeaderView::section {{ background: {t['header_bg']}; color: {t['header_text']}; border: 0px solid {t['table_border']};
    border-right-width: 1px; border-bottom-width: 1px; padding: 3px 3px 3px 6px; }}      /* one thin line between the cells, not a doubled frame */
QMenuBar {{ background: {t['menu_bg']}; color: {t['menu_text']}; }}
QMenuBar::item:selected {{ background: {t['accent']}; }}
QMenu {{ background: {t['menu_bg']}; color: {t['menu_text']}; border: 1px solid rgba(128,128,128,110); }}
QMenu::item:selected {{ background: {t['accent']}; color: #ffffff; }}
QMenu::item:disabled {{ color: {_disabled(t['menu_text'])}; }}
QMenu::separator {{ height: 1px; background: {t['menu_text']}; margin: 4px 6px; }}
QTabBar::tab {{ background: {t['tab_bg']}; color: {t['text']}; padding: 4px 12px;
    border: 1px solid rgba(128,128,128,110); border-bottom: none; margin-left: 1px; }}
QTabBar::tab {{ min-width: 70px; }}
QTabBar::tab:selected {{ background: {t['tab_selected']}; color: {t['tab_selected_text']}; font-weight: bold; }}
QTabBar::close-button {{ subcontrol-position: right; }}
QPushButton[ctl="true"] {{ background: {t['ctl_bg']}; color: {t['ctl_text']}; }}
QPushButton[ctl="true"]:disabled {{ color: {_disabled(t['ctl_text'])}; }}
QPushButton[role="start"][on="true"], QPushButton[role="start"][on="true"]:disabled
    {{ background: {t['start_on_bg']}; color: {t['start_on_text']}; font-weight: bold; }}
QPushButton[role="stop"][on="true"], QPushButton[role="stop"][on="true"]:disabled
    {{ background: {t['stop_on_bg']}; color: {t['stop_on_text']}; font-weight: bold; }}
QPushButton[role="pause"][on="true"] {{ background: {t['pause_on_bg']}; color: {t['pause_on_text']}; }}
QPushButton[role="rec"][on="true"] {{ background: {t['rec_on_bg']}; color: {t['rec_on_text']}; }}
QPushButton[role="reset"][on="true"] {{ background: {t['reset_on_bg']}; color: {t['reset_on_text']}; font-weight: bold; }}
QPushButton[role="mark"][on="true"] {{ background: {t['mark_on_bg']}; color: {t['mark_on_text']}; }}
QSplitter::handle {{ background: rgba(128,128,128,70); }}
QSplitter::handle:hover {{ background: {t['accent']}; }}
QToolTip {{ background: {t['edit_bg']}; color: {t['edit_text']}; border: 1px solid rgba(128,128,128,150); }}
QScrollArea {{ background: transparent; }}
QFrame#dlgHeader {{ background: {t['panel_bg']}; border-bottom: 2px solid {t['accent']}; }}
QLabel#dlgTitle {{ font-weight: bold; font-size: {t['font_size'] + 3}pt; color: {t['text']}; }}
QLabel#dlgText {{ color: {t['text']}; }}
"""


ROW_TEXT = {"odd": DARK["row_odd_text"], "even": DARK["row_even_text"]}      # set by apply_theme: font colours of the odd / even table rows
CELL_INDENT = 12                 # left margin of the text in every table cell [px] - as in the edit fields (10 px + the frame)


class IndentDelegate(QStyledItemDelegate):
    """Draws the text of a cell CELL_INDENT px from the left edge, whatever the style sheet does with `::item` padding (the cell itself,
    its background and selection stay full width). Cells with an icon / check box are drawn by the stock delegate."""

    def sizeHint(self, option, index):
        o = QStyleOptionViewItem(option)
        o.font.setBold(True)                                      # the text of a cell is bold (like the values in every field)
        s = super().sizeHint(o, index)
        s.setWidth(s.width() + CELL_INDENT)                       # room for the indent (column auto-fit)
        return s

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if opt.features & (QStyleOptionViewItem.HasDecoration | QStyleOptionViewItem.HasCheckIndicator) or not opt.text:
            return super().paint(painter, option, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        text = opt.text
        opt.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)               # background, selection, focus frame
        r = QRect(opt.rect).adjusted(CELL_INDENT, 0, -4, 0)
        group = QPalette.Active if opt.state & QStyle.State_Active else QPalette.Inactive
        role = QPalette.HighlightedText if opt.state & QStyle.State_Selected else QPalette.Text
        painter.save()
        bold = QFont(opt.font)
        bold.setBold(True)                                       # the text of a cell is bold
        painter.setFont(bold)
        pen = opt.palette.color(group if opt.state & QStyle.State_Enabled else QPalette.Disabled, role)
        if role == QPalette.Text and opt.state & QStyle.State_Enabled and index.data(Qt.ForegroundRole) is None:
            pen = QColor(ROW_TEXT["even" if opt.features & QStyleOptionViewItem.Alternate else "odd"])           # the row colours of the theme
        painter.setPen(pen)
        flags = int(opt.displayAlignment)
        if opt.features & QStyleOptionViewItem.WrapText:
            painter.drawText(r, flags | int(Qt.TextWordWrap), text)
        else:
            painter.drawText(r, flags, QFontMetrics(bold).elidedText(text, opt.textElideMode, r.width()))
        painter.restore()


class _IndentInstaller(QObject):
    """Gives every table the IndentDelegate when it is first shown (unless the table has a delegate of its own)."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Polish and isinstance(obj, QTableView):
            obj.setAlternatingRowColors(True)                       # the standard look of every table (see table_kit)
            if type(obj.itemDelegate()) is QStyledItemDelegate:
                obj.setItemDelegate(IndentDelegate(obj))
        return False


_INSTALLER: _IndentInstaller | None = None


def apply_theme(app: QApplication, theme: dict | None) -> dict:
    global _INSTALLER
    if _INSTALLER is None:
        _INSTALLER = _IndentInstaller(app)
        app.installEventFilter(_INSTALLER)
    t = normalize(theme)
    app.setStyle("Fusion")
    p = QPalette()
    c = QColor
    p.setColor(QPalette.Window, c(t["window_bg"]))
    p.setColor(QPalette.WindowText, c(t["text"]))
    p.setColor(QPalette.Base, c(t["edit_bg"]))
    p.setColor(QPalette.AlternateBase, c(t["table_bg"]))
    p.setColor(QPalette.Text, c(t["edit_text"]))
    p.setColor(QPalette.Button, c(t["button_bg"]))
    p.setColor(QPalette.ButtonText, c(t["button_text"]))
    p.setColor(QPalette.Highlight, c(t["accent"]))
    p.setColor(QPalette.HighlightedText, c("#ffffff"))
    p.setColor(QPalette.ToolTipBase, c(t["edit_bg"]))
    p.setColor(QPalette.ToolTipText, c(t["edit_text"]))
    p.setColor(QPalette.Disabled, QPalette.Text, c("#808080"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, c("#808080"))
    app.setPalette(p)
    font = QFont(app.font())
    if t["font_family"]:
        font.setFamily(t["font_family"])
    font.setPointSize(t["font_size"])
    app.setFont(font)
    ROW_TEXT["odd"], ROW_TEXT["even"] = t["row_odd_text"], t["row_even_text"]
    app.setStyleSheet(build_qss(t))
    return t


def apply_dark(app: QApplication) -> None:      # backward compatible helper
    apply_theme(app, DARK)
