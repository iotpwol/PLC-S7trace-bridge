"""Markers (bookmarks) on the chart and the search window.

`TabMarkers` is the part of a TraceTab that deals with markers (drawing the lines of the visible range, the right-click menus,
adding / editing / deleting, jumping to a time). `MarkerEditDialog` edits one marker, `MarkersDialog` lists / searches them,
`SearchDialog` looks for times and values in the data of the tab or in a recording of the database.
"""
from __future__ import annotations

import html
import platform
import sqlite3
import threading
from datetime import datetime

import numpy as np
from PySide6.QtCore import QDateTime, Qt, QTimer, Signal as QtSignal
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QDateTimeEdit,
                               QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMenu, QMessageBox, QInputDialog, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSlider, QSpinBox,
                               QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..core import markers as mk
from ..core.marker_draft import MarkerDraft
from ..core import search as sr
from ..core.store import current_user, to_us
from .dialog_kit import dialog_info

STAMP = "yyyy-MM-dd HH:mm:ss.zzz"


def fmt_us(us, ms: bool = True) -> str:
    if not us:
        return "–"
    d = datetime.fromtimestamp(us / 1e6)
    return d.strftime("%Y-%m-%d %H:%M:%S") + (f".{d.microsecond // 1000:03d}" if ms else "")


def qdt(us: int) -> QDateTime:
    return QDateTime.fromMSecsSinceEpoch(int(us // 1000))


def color_icon(col: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(col))
    return QIcon(pm)


def marker_tip(m: mk.Marker, state: str = "", changed=frozenset(), look: dict | None = None) -> str:
    """The bubble over a marker. `changed` = internal names of the fields changed since the saved version: they are
    highlighted yellow. Times are in a monospaced font in a table, so the digits of two dates are one under the other."""
    e = html.escape
    changed = set(changed)

    def hl(text: str, *fields: str) -> str:
        return f"<span style='background-color:#ffd24a;color:#000000'>&nbsp;{text}&nbsp;</span>" if changed & set(fields) else text

    mono = "font-family:Consolas,\"Courier New\",monospace"
    rows = [hl(f"<b>{e(m.title or '(bez tytułu)')}</b>", "title") + "  " + hl(f"<span style='color:{m.color}'>■</span>", "color")]
    if state:
        rows.append(f"<span style='color:#e0a030'>* niezapisany ({'nowy' if state == 'new' else 'zmieniony'}) – "
                    "użyj „Zapisz znaczniki”</span>")
    if m.kind in mk.SPAN_KINDS:
        rows.append(hl(f"{mk.KINDS[m.kind]} ({_dur((m.end_us - m.at_us) / 1e6)}):", "kind", "at_us", "end_us") +
                    f"<table cellspacing='0' cellpadding='0'><tr><td>Od:&nbsp;</td><td style='{mono}'>"
                    f"{hl(fmt_us(m.at_us), 'at_us', 'kind')}</td></tr><tr><td>Do:&nbsp;</td><td style='{mono}'>"
                    f"{hl(fmt_us(m.end_us), 'end_us', 'kind')}</td></tr></table>")
    else:
        rows.append(hl(f"Czas: <span style='{mono}'>{fmt_us(m.at_us)}</span>", "at_us", "kind"))
    rows.append(hl(f"Priorytet: {mk.PRIORITIES.get(m.priority, m.priority)}", "priority"))
    width = f"{m.line_width} px" if m.line_width else (f"{look['width_all']} px (wg ustawień)" if look else "wg ustawień")
    rows.append(hl(f"Linia: {width}, {mk.LINE_STYLES.get(m.line_style, m.line_style)}"
                   + (f"; przezroczystość obszaru {100 - m.opacity} %" if m.kind == "range" else ""),
                   "line_width", "line_style", "opacity"))
    rows.append(hl("Dotyczy: " + (e(", ".join(m.signals)) if m.signals else "wszystkich przebiegów"), "signals"))
    if m.group_name or "group_name" in changed:
        rows.append(hl(f"Grupa: <b>{e(m.group_name) or '(brak)'}</b>", "group_name"))
    if not m.show_label or "show_label" in changed:
        rows.append(hl("Nazwa na wykresie: " + ("pokazywana" if m.show_label else "ukryta"), "show_label"))
    if m.description:
        rows.append(hl(e(m.description).replace("\n", "<br>"), "description"))
    elif "description" in changed:
        rows.append(hl("(opis usunięty)", "description"))
    if m.notes:
        rows.append(hl("<i>Uwagi:</i> " + e(m.notes).replace("\n", "<br>"), "notes"))
    elif "notes" in changed:
        rows.append(hl("(uwagi usunięte)", "notes"))
    rows.append(f"Autor: {e(m.author or '–')}")
    rows.append(f"Założono: {fmt_us(m.created_us, False)}")
    rows.append(f"Zmodyfikował: {e(m.modified_by) if m.modified_by else '–'}")
    rows.append(f"Zmieniono: {fmt_us(m.modified_us, False)}")
    return "<br>".join(rows)


class ColorCombo(QComboBox):
    """Colour of a marker: the palette plus 'Inny…' (colour dialog)."""

    def __init__(self, color: str = mk.DEFAULT_COLOR, parent=None):
        super().__init__(parent)
        for name, c in mk.PALETTE.items():
            self.addItem(color_icon(c), name, c)
        self.addItem("Inny kolor…", "")
        self._last = 0
        self.set_color(color)
        self.activated.connect(self._picked)

    def _picked(self, i: int) -> None:
        if self.itemData(i) == "":
            c = QColorDialog.getColor(QColor(self.itemData(self._last) or mk.DEFAULT_COLOR), self, "Kolor znacznika")
            if c.isValid():
                self.set_color(c.name())
            else:
                self.setCurrentIndex(self._last)
        else:
            self._last = i

    def set_color(self, col: str) -> None:
        col = (col or mk.DEFAULT_COLOR).lower()
        i = self.findData(col)
        if i < 0:                                                  # a colour outside the palette: an own entry before 'Inny…'
            self.insertItem(self.count() - 1, color_icon(col), col, col)
            i = self.findData(col)
        self.setCurrentIndex(i)
        self._last = i

    def color(self) -> str:
        return self.currentData() or self.itemData(self._last) or mk.DEFAULT_COLOR


def priority_combo(value: int = mk.DEFAULT_PRIORITY, any_label: str = "") -> QComboBox:
    cb = QComboBox()
    if any_label:
        cb.addItem(any_label, None)
    for k, name in mk.PRIORITIES.items():
        cb.addItem(f"{k} – {name}", k)
    cb.setCurrentIndex(max(cb.findData(value), 0))
    return cb


# ------------------------------------------------------------------------------------------------- one marker
@dialog_info("Znacznik", "Tytuł, opis i uwagi pozwalają później odnaleźć ten punkt na wykresie; kolor i priorytet ułatwiają "
                         "ich rozróżnianie.")
class MarkerEditDialog(QDialog):
    def __init__(self, marker: mk.Marker, new: bool, parent=None, names: list[str] | None = None,
                 groups: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Nowy znacznik" if new else "Edycja znacznika")
        self.marker, self.new = marker, new
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_title = QLineEdit(marker.title)
        self.ed_title.setMaxLength(mk.LIMITS["title"])
        self.ed_desc = QPlainTextEdit(marker.description)
        self.ed_desc.setFixedHeight(80)
        self.ed_notes = QPlainTextEdit(marker.notes)
        self.ed_notes.setFixedHeight(80)
        self.cb_color = ColorCombo(marker.color)
        self.cb_prio = priority_combo(marker.priority)
        self.sp_width = QSpinBox()
        self.sp_width.setRange(0, mk.MAX_WIDTH)
        self.sp_width.setSpecialValueText("wg ustawień")
        self.sp_width.setSuffix(" px")
        self.sp_width.setValue(marker.line_width)
        self.cb_style = QComboBox()
        for k, label in mk.LINE_STYLES.items():
            self.cb_style.addItem(label, k)
        self.cb_style.setCurrentIndex(max(self.cb_style.findData(marker.line_style), 0))
        self.chk_label = QCheckBox("Pokazuj nazwę znacznika na wykresie")
        self.chk_label.setChecked(bool(marker.show_label))
        self.sl_transp = QSlider(Qt.Horizontal)                    # transparency of the area = 100 - how much it covers
        self.sl_transp.setRange(0, 100)
        self.sl_transp.setValue(100 - marker.opacity)
        self.lbl_transp = QLabel()
        self.sl_transp.valueChanged.connect(lambda v: self.lbl_transp.setText(f"{v} %"))
        self.lbl_transp.setText(f"{self.sl_transp.value()} %")
        self.dt = QDateTimeEdit(qdt(marker.at_us))
        self.dt2 = QDateTimeEdit(qdt(marker.end_us or marker.at_us))
        for d in (self.dt, self.dt2):
            d.setDisplayFormat(STAMP)
            d.setCalendarPopup(True)
        self.cb_kind = QComboBox()
        for k, label in mk.KINDS.items():
            self.cb_kind.addItem(label, k)
        self.cb_kind.setCurrentIndex(max(self.cb_kind.findData(marker.kind), 0))
        self.lbl_dt2 = QLabel("Do:")
        self.cb_kind.currentIndexChanged.connect(self._kind_changed)
        self.cb_group = QComboBox()
        self.cb_group.setEditable(True)
        self.cb_group.setInsertPolicy(QComboBox.NoInsert)
        self.cb_group.addItem("")
        self.cb_group.addItems([g for g in (groups or []) if g])
        self.cb_group.setCurrentText(marker.group_name)
        self.cb_group.lineEdit().setPlaceholderText("(bez grupy) – wpisz nazwę albo wybierz istniejącą grupę")
        self.rb_all = QRadioButton("Wszystkie przebiegi")
        self.rb_sel = QRadioButton("Wybrane przebiegi:")
        self.rb_all.setChecked(not marker.signals)
        self.rb_sel.setChecked(bool(marker.signals))
        self.lst = QListWidget()
        self.lst.setMaximumHeight(110)
        all_names = list(names or [])
        for n in marker.signals:                                  # signals that are not in this tab keep their assignment
            if n not in all_names:
                all_names.append(n)
        for n in all_names:
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if n in marker.signals else Qt.Unchecked)
            self.lst.addItem(it)
        self.lst.setEnabled(bool(marker.signals))
        self.rb_sel.toggled.connect(self.lst.setEnabled)
        self.lst.itemChanged.connect(self._single_signal)
        form.addRow("Tytuł:", self.ed_title)
        form.addRow("Opis:", self.ed_desc)
        form.addRow("Uwagi:", self.ed_notes)
        row = QHBoxLayout()
        row.addWidget(self.cb_color, 1)
        row.addWidget(QLabel("Priorytet:"))
        row.addWidget(self.cb_prio, 1)
        form.addRow("Kolor:", row)
        form.addRow("", self.chk_label)
        row2 = QHBoxLayout()
        row2.addWidget(self.sp_width, 1)
        row2.addWidget(QLabel("Rodzaj linii:"))
        row2.addWidget(self.cb_style, 1)
        form.addRow("Grubość linii:", row2)
        row3 = QHBoxLayout()
        row3.addWidget(self.sl_transp, 1)
        row3.addWidget(self.lbl_transp)
        self.w_transp = QWidget()
        self.w_transp.setLayout(row3)
        row3.setContentsMargins(0, 0, 0, 0)
        self.lbl_transp_name = QLabel("Przezroczystość obszaru:")
        form.addRow(self.lbl_transp_name, self.w_transp)
        form.addRow("Rodzaj:", self.cb_kind)
        form.addRow("Czas (od):", self.dt)
        form.addRow(self.lbl_dt2, self.dt2)
        form.addRow("Dotyczy:", self.rb_all)
        form.addRow("", self.rb_sel)
        form.addRow("", self.lst)
        form.addRow("Grupa:", self.cb_group)
        lay.addLayout(form)
        self._kind_changed()
        info = []
        if not new:
            info = [f"Założono: <b>{fmt_us(marker.created_us, False)}</b>, autor: <b>{html.escape(marker.author or '–')}</b>"
                    + (f" (komputer {html.escape(marker.computer)})" if marker.computer else ""),
                    f"Zmieniono: <b>{fmt_us(marker.modified_us, False)}</b>, przez: <b>{html.escape(marker.modified_by or '–')}</b>"]
            if marker.conn or marker.rec_id:
                info.append(f"Połączenie: <b>{html.escape(marker.conn or '–')}</b>"
                            + (f", nagranie: {html.escape(marker.rec_id)}" if marker.rec_id else ""))
        else:
            info = [f"Autor: <b>{html.escape(marker.author or current_user())}</b>; data założenia i modyfikacji "
                    "zapiszą się automatycznie."]
        self.lbl_info = QLabel("<br>".join(info))
        self.lbl_info.setTextFormat(Qt.RichText)
        self.lbl_info.setWordWrap(True)
        lay.addWidget(self.lbl_info)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("Zapisz")
        ok.setDefault(True)
        cancel = QPushButton("Anuluj")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

    def _kind_changed(self) -> None:
        kind = self.cb_kind.currentData()
        r = kind in mk.SPAN_KINDS
        self.dt2.setVisible(r)
        self.lbl_dt2.setVisible(r)
        self.w_transp.setVisible(kind == "range")                  # only an area has transparency
        self.lbl_transp_name.setVisible(kind == "range")
        delta = kind == "delta"                                    # the difference of ONE signal: its plot has to be chosen
        self.rb_all.setEnabled(not delta)
        if delta:
            self.rb_sel.setChecked(True)
            self._single_signal()

    def _single_signal(self, item=None) -> None:
        """'Różnica sygnału' takes exactly one plot: ticking another one unticks the rest."""
        if self.cb_kind.currentData() != "delta":
            return
        checked = [self.lst.item(i) for i in range(self.lst.count()) if self.lst.item(i).checkState() == Qt.Checked]
        keep = item if item is not None and item.checkState() == Qt.Checked else (checked[0] if checked else None)
        self.lst.blockSignals(True)
        for it in checked:
            if it is not keep:
                it.setCheckState(Qt.Unchecked)
        self.lst.blockSignals(False)

    @staticmethod
    def _us(edit: QDateTimeEdit, old: int) -> int:
        ms = edit.dateTime().toMSecsSinceEpoch()
        return old if ms == old // 1000 else ms * 1000                 # a time that was not edited keeps its µs

    def values(self) -> dict:
        kind = self.cb_kind.currentData()
        at = self._us(self.dt, self.marker.at_us)
        sig = [self.lst.item(i).text() for i in range(self.lst.count()) if self.lst.item(i).checkState() == Qt.Checked] \
            if self.rb_sel.isChecked() else []
        return {"title": self.ed_title.text().strip(), "description": self.ed_desc.toPlainText(),
                "notes": self.ed_notes.toPlainText(), "color": self.cb_color.color(), "priority": self.cb_prio.currentData(),
                "kind": kind, "at_us": at, "end_us": self._us(self.dt2, self.marker.end_us or at) if kind in mk.SPAN_KINDS else 0,
                "signals": sig, "group_name": self.cb_group.currentText().strip(), "line_width": self.sp_width.value(),
                "line_style": self.cb_style.currentData(), "opacity": 100 - self.sl_transp.value(),
                "show_label": int(self.chk_label.isChecked())}


# ------------------------------------------------------------------------------------------ the tab's side
STATE_PL = {"new": "nowy", "edited": "zmieniony", "deleted": "do usunięcia"}
STATE_COLOR = {"new": "#2e7d32", "edited": "#b8860b", "deleted": "#c62828"}


@dialog_info("Zapisz znaczniki", "Znaczniki założone, zmienione lub usunięte na wykresie są tylko robocze, dopóki ich nie zapiszesz.")
class PendingDialog(QDialog):
    """The list of what saving is going to do: new markers, changed ones (with what changed), markers to be deleted.
    mode 'save' (button 'Zapisz znaczniki'): Zapisz / Anuluj; mode 'close' (the chart is being closed): Zapisz / Odrzuć / Anuluj.
    The answer is in `choice`: 'save', 'discard' or 'cancel'."""

    def __init__(self, changes, mode: str, parent=None):
        super().__init__(parent)
        self.choice = "cancel"
        self.setWindowTitle("Zapisz znaczniki" if mode == "save" else "Niezapisane znaczniki")
        self.resize(780, 420)
        n = {s: sum(1 for c in changes if c.state == s) for s in STATE_PL}
        lay = QVBoxLayout(self)
        intro = ("Do zapisania: " if mode == "save" else "Na tym wykresie są niezapisane znaczniki. Zapisać je przed zamknięciem? Razem: ") + \
            f"<b>{n['new']}</b> nowych, <b>{n['edited']}</b> zmienionych, <b>{n['deleted']}</b> do usunięcia."
        self.lbl = QLabel(intro)
        self.lbl.setTextFormat(Qt.RichText)
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        self.table = QTableWidget(len(changes), 4)
        self.table.setHorizontalHeaderLabels(["Zmiana", "Znacznik", "Czas", "Szczegóły"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, c in enumerate(changes):
            m = c.marker
            when = fmt_us(m.at_us) + (f" → {fmt_us(m.end_us)}" if m.kind in mk.SPAN_KINDS else "")
            if c.state == "new":
                detail = mk.KINDS[m.kind].lower() + (f"; grupa „{m.group_name}”" if m.group_name else "")
            elif c.state == "edited":
                detail = "zmieniono: " + ", ".join(c.fields)
            else:
                detail = "zostanie usunięty z pliku znaczników"
            cells = [STATE_PL[c.state], m.blurb(), when, detail]
            for j, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setForeground(QBrush(QColor(STATE_COLOR[c.state])) if j == 0 else QBrush())
                if c.state == "deleted":
                    f = it.font()
                    f.setStrikeOut(j == 1)
                    it.setFont(f)
                if j == 0:
                    it.setIcon(color_icon(m.color))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table, 1)
        b = QHBoxLayout()
        b.addStretch()
        ok = QPushButton("Zapisz znaczniki" if mode == "save" else "Zapisz")
        ok.setDefault(True)
        ok.clicked.connect(lambda: self._done("save"))
        b.addWidget(ok)
        if mode == "close":
            disc = QPushButton("Odrzuć zmiany")
            disc.clicked.connect(lambda: self._done("discard"))
            b.addWidget(disc)
        cancel = QPushButton("Anuluj" if mode == "save" else "Wróć do wykresu")
        cancel.clicked.connect(lambda: self._done("cancel"))
        b.addWidget(cancel)
        lay.addLayout(b)

    def _done(self, choice: str) -> None:
        self.choice = choice
        self.accept() if choice != "cancel" else self.reject()

    def ask(self) -> str:
        self.exec()
        return self.choice


class TabMarkers:
    """Markers of one TraceTab. Time on the chart = seconds since the tab's start_wall; a marker keeps absolute time.
    Everything the user does with markers goes into a draft (core/marker_draft.py); 'Zapisz znaczniki' writes it."""

    def __init__(self, tab, store: mk.MarkerStore | None = None):
        self.tab = tab
        self._store = store
        self._draft: MarkerDraft | None = None
        self.show_all = False                    # markers of other connections too
        self.hi_group = ""                       # group whose markers are drawn highlighted
        self._sig = None
        self.dlg: MarkersDialog | None = None
        self.search_dlg: SearchDialog | None = None
        p = tab.plot
        p.markerRequested.connect(self.chart_menu)
        p.markerMenu.connect(self.marker_menu)
        p.markerMoved.connect(self.moved)
        p.markerPlaced.connect(self.placed)
        p.markerOpened.connect(self.opened)
        p.markerEdit.connect(self.edit)                  # double click on a marker opens its edit window

    # ---- basics
    @property
    def store(self) -> mk.MarkerStore | None:
        if self._store is None:
            try:
                self._store = mk.default_store()
            except Exception as e:                                       # unwritable folder: the program works without
                self.tab.status_msg = f"Znaczniki niedostępne: {e}"
                return None
        return self._store

    @property
    def draft(self) -> MarkerDraft | None:
        st = self.store
        if st is None:
            return None
        if self._draft is None or self._draft.store is not st:
            self._draft = MarkerDraft(st)
        return self._draft

    def pending(self) -> int:
        return self._draft.count() if self._draft is not None else 0

    def key(self) -> str:
        info = getattr(self.tab, "loaded", None)
        if info and info.get("meta"):
            return (info["meta"].get("tab") or info["meta"].get("conf") or "").strip()
        return self.tab.title()

    def rec_id(self) -> str:
        info = getattr(self.tab, "loaded", None)
        return str(info["meta"].get("id", "")) if info and info.get("meta") else ""

    def to_wall(self, t: float) -> int:
        return to_us(self.tab.start_wall, t)

    def to_rel(self, us: int) -> float:
        return us / 1e6 - self.tab.start_wall.timestamp()

    def data_span_us(self) -> tuple[int, int] | None:
        b = self.tab.buffer
        if len(b) == 0:
            return None
        return self.to_wall(b.first_time()), self.to_wall(b.last_time())

    # ---- drawing
    def sync(self, force: bool = False) -> None:
        st, dr = self.store, self.draft
        if st is None or dr is None:
            return
        x0, x1 = self.tab.plot.view_range()
        sig = (round(x0, 3), round(x1, 3), st.version, st.data_version(), dr.version, self.tab.start_wall, self.show_all, self.key())
        if sig == self._sig and not force:
            return
        self._sig = sig
        self._update_save_button()
        try:
            found = dr.search(t0_us=self.to_wall(x0), t1_us=self.to_wall(x1), limit=400)
        except Exception:
            return
        if not self.show_all:
            key = self.key()
            found = [m for m in found if m.conn in ("", key)]
        items = []
        for m in found:
            state = dr.state(m.id)
            label = (m.title if m.show_label else "")
            items.append({"id": m.id, "kind": m.kind, "x0": self.to_rel(m.at_us),
                          "x1": self.to_rel(m.end_us) if m.kind in mk.SPAN_KINDS else self.to_rel(m.at_us),
                          "color": m.color, "width": m.line_width, "style": m.line_style, "opacity": m.opacity,
                          "priority": m.priority, "title": ("* " + label) if (label and state) else label,
                          "tip": marker_tip(m, state, dr.changed_fields(m.id), self.tab.plot.mlook), "signals": list(m.signals)})
        self.tab.plot.set_markers(items)
        if self.hi_group:                                                # the group chosen with 'Podświetl grupę'
            self.tab.plot.set_marker_highlight({m.id for m in found if m.group_name == self.hi_group})

    def _update_save_button(self) -> None:
        n = self.pending()
        b = getattr(self.tab, "btn_msave", None)
        if b is not None:
            b.setText(f"Zapisz znaczniki ({n})" if n else "Zapisz znaczniki")
            b.setEnabled(n > 0)

    # ---- the actions (all of them change the draft only)
    def _who(self) -> str:
        return current_user()

    def signal_names(self) -> list[str]:
        return [s.name for s in (self.tab._run_signals or self.tab.display_signals())]

    def group_names(self) -> list[str]:
        dr = self.draft
        return [g for g, _n in dr.groups()] if dr else []

    def _changed(self, message: str = "") -> None:
        self.sync(True)
        self._refresh_dialog()
        if message:
            self.tab.status_msg = message

    def add_at_us(self, at_us: int, title: str = "", description: str = "", end_us: int | None = None,
                  signals: list[str] | None = None, group: str = "", kind: str | None = None) -> mk.Marker | None:
        """Opens the window of a new marker (a range when end_us is given, or `kind`); a confirmed marker joins the draft."""
        dr = self.draft
        if dr is None:
            return None
        m = mk.Marker(kind=kind or ("range" if end_us else "point"), at_us=int(at_us), end_us=int(end_us or 0), title=title,
                      description=description, signals=list(signals or []), group_name=group, author=self._who(),
                      computer=platform.node(), conn=self.key(), rec_id=self.rec_id())
        d = MarkerEditDialog(m, True, self.tab, self.signal_names(), self.group_names())
        if not d.exec():
            return None
        try:
            vals = d.values()
            new = dr.add(vals.pop("at_us"), author=m.author, computer=m.computer, conn=m.conn, rec_id=m.rec_id, **vals)
        except mk.MarkerError as e:
            QMessageBox.warning(self.tab, "S7Trace", str(e))
            return None
        self._changed(f"Nowy znacznik „{new.blurb()}” ({fmt_us(new.at_us)}) – niezapisany. Zapisz znaczniki, żeby go zachować.")
        return new

    def add_now(self) -> None:
        """Marker at the newest sample (live data) or at the middle of the visible range."""
        if self.tab.state in ("running", "reconnecting") and len(self.tab.buffer):
            t = self.tab.buffer.last_time()
        else:
            x0, x1 = self.tab.plot.view_range()
            t = (x0 + x1) / 2
        self.add_at_us(self.to_wall(t))

    def _update(self, mid: int, fields: dict, message: str = "") -> mk.Marker | None:
        dr = self.draft
        if dr is None:
            return None
        try:
            m = dr.update(mid, fields, by=self._who())
        except (mk.MarkerError, KeyError) as e:
            QMessageBox.warning(self.tab, "S7Trace", str(e) if isinstance(e, mk.MarkerError) else "Znacznik już nie istnieje.")
            return None
        self._changed(message)
        return m

    def edit(self, mid: int) -> None:
        dr = self.draft
        m = dr.get(mid) if dr else None
        if m is None:
            return
        d = MarkerEditDialog(m, False, self.tab, self.signal_names(), self.group_names())
        if d.exec():
            self._update(mid, d.values(), f"Zmieniono znacznik „{m.blurb()}” – niezapisany.")

    def delete(self, mid: int, ask: bool = False) -> None:
        dr = self.draft
        m = dr.get(mid) if dr else None
        if m is None:
            return
        if ask and QMessageBox.question(self.tab, "Usuń znacznik", f"Usunąć znacznik „{m.blurb()}”?") != QMessageBox.Yes:
            return
        was_new = dr.state(mid) == "new"
        dr.delete(mid)
        self._changed(f"Znacznik „{m.blurb()}” " + ("usunięty." if was_new else "oznaczony do usunięcia (zapisz znaczniki)."))

    def revert(self, mid: int) -> None:
        if self.draft is not None:
            self.draft.revert(mid)
            self._changed()

    def toggle_label(self, mid: int) -> None:
        """Hides / shows the name written next to the marker on the chart."""
        dr = self.draft
        m = dr.get(mid) if dr else None
        if m is not None:
            self._update(mid, {"show_label": 0 if m.show_label else 1})

    def moved(self, mid: int, x0: float, x1: float) -> None:
        """A marker was dragged on the chart (a range: its edges or the whole area)."""
        dr = self.draft
        m = dr.get(mid) if dr else None
        if m is None:
            return
        f = {"at_us": self.to_wall(x0)}
        if m.kind in mk.SPAN_KINDS:
            f["end_us"] = self.to_wall(x1)
        self._update(mid, f)

    def placed(self, mid: int, x: float) -> None:
        """'Zmień pozycję': a point goes where the chart was clicked, a range gets its middle there (length unchanged)."""
        dr = self.draft
        m = dr.get(mid) if dr else None
        if m is None:
            return
        at = self.to_wall(x)
        f = {"at_us": at}
        if m.kind in mk.SPAN_KINDS:
            half = (m.end_us - m.at_us) // 2
            f = {"at_us": at - half, "end_us": at + (m.end_us - m.at_us - half)}
        self._update(mid, f, f"Przesunięto znacznik „{m.blurb()}” (niezapisany).")

    def set_movable(self, mid: int, on: bool) -> None:
        """'Zmień pozycję znacznika' (a tick in the marker menu): only an unlocked marker can be dragged with the mouse; a drag that
        starts on a locked one pans the chart. The tick is cleared the same way."""
        self.tab.plot.set_marker_movable(mid, on)
        dr = self.draft
        m = dr.get(mid) if dr else None
        self.tab.status_msg = (f"Znacznik „{m.blurb() if m else ''}” odblokowany – przeciągnij go myszą (zakres: krawędzie lub całość). "
                               "Odznacz „Zmień pozycję znacznika” w jego menu, aby go zablokować." if on else
                               "Znacznik zablokowany – przeciąganie przesuwa wykres.")
        self.tab._update_status()

    def start_move(self, mid: int) -> None:
        self.tab.plot.start_marker_placement(mid)
        self.tab.status_msg = ("Zmiana pozycji znacznika: kliknij na wykresie nowe miejsce (prawy przycisk – anuluj). "
                               "Zakres ustawia się środkiem w klikniętym punkcie.")
        self.tab._update_status()

    # ---- saving
    def save(self) -> bool:
        """'Zapisz znaczniki': shows what is going to be saved (new / changed / to delete) and writes it after the confirmation."""
        dr = self.draft
        if dr is None:
            return False
        if not dr.dirty():
            QMessageBox.information(self.tab, "S7Trace", "Nie ma niezapisanych znaczników.")
            return True
        return self._commit(PendingDialog(dr.changes(), "save", self.tab).ask() == "save")

    def _commit(self, go: bool) -> bool:
        dr = self.draft
        if not go or dr is None:
            return False
        try:
            rep = dr.commit(by=self._who(), computer=platform.node())
        except (mk.MarkerError, OSError, sqlite3.Error) as e:
            QMessageBox.warning(self.tab, "S7Trace", f"Nie udało się zapisać znaczników (nic nie zostało zapisane): {e}")
            return False
        msg = f"Zapisano znaczniki: nowych {len(rep['added'])}, zmienionych {rep['updated']}, usuniętych {rep['deleted']}."
        if rep["missing"]:
            msg += f" Pominięto {len(rep['missing'])} (zniknęły z pliku w międzyczasie)."
        self._changed(msg)
        return True

    def confirm_close(self) -> bool:
        """Called before the tab (or the program) is closed: reminds about unsaved markers and lists them. False = stay."""
        dr = self._draft
        if dr is None or not dr.dirty():
            return True
        choice = PendingDialog(dr.changes(), "close", self.tab).ask()
        if choice == "save":
            return self._commit(True)
        if choice == "discard":
            dr.discard()
            self._changed()
            return True
        return False

    # ---- groups
    def add_to_group(self, ids: list[int]) -> None:
        """Asks for a group (an existing one or a new name) and puts the markers into it."""
        dr = self.draft
        if dr is None or not ids:
            return
        names = self.group_names()
        first = dr.get(ids[0])
        cur = names.index(first.group_name) if first and first.group_name in names else 0
        name, ok = QInputDialog.getItem(self.tab, "Grupa znaczników",
                                        "Wybierz grupę albo wpisz nazwę nowej (np. nazwę zdarzenia):", names or [""], cur, True)
        name = name.strip()
        if not ok or not name:
            return
        try:
            for i in ids:
                if dr.get(i) is not None:
                    dr.update(i, {"group_name": name}, by=self._who())
        except mk.MarkerError as e:
            QMessageBox.warning(self.tab, "S7Trace", str(e))
            return
        self.hi_group = name
        self._changed(f"Znaczniki ({len(ids)}) trafiły do grupy „{name}” (niezapisane).")

    def leave_group(self, ids: list[int]) -> None:
        dr = self.draft
        if dr is not None and ids:
            for i in ids:
                if dr.get(i) is not None:
                    dr.update(i, {"group_name": ""}, by=self._who())
            self._changed()

    def rename_group(self, name: str) -> None:
        new, ok = QInputDialog.getText(self.tab, "Nazwa grupy", f"Nowa nazwa grupy „{name}”:", text=name)
        new = new.strip()
        dr = self.draft
        if not ok or not new or new == name or dr is None:
            return
        try:
            for m in dr.search(group=name, limit=100000):
                dr.update(m.id, {"group_name": new}, by=self._who())
        except mk.MarkerError as e:
            QMessageBox.warning(self.tab, "S7Trace", str(e))
            return
        if self.hi_group == name:
            self.hi_group = new
        self._changed()

    def highlight_group(self, name: str) -> None:
        self.hi_group = name
        if not name:
            self.tab.plot.set_marker_highlight(None)
        self.sync(True)

    def step_in_group(self, mid: int, direction: int) -> None:
        """Jumps to the next / previous marker of the same group (by time)."""
        dr = self.draft
        m = dr.get(mid) if dr else None
        if m is None or not m.group_name:
            return
        mates = [x for x in dr.search(group=m.group_name, limit=5000) if x.conn in ("", self.key()) or self.show_all]
        mates.sort(key=lambda x: (x.at_us, x.id))
        i = next((k for k, x in enumerate(mates) if x.id == mid), -1)
        j = i + direction
        if not (0 <= j < len(mates)):
            self.tab.status_msg = "To " + ("ostatni" if direction > 0 else "pierwszy") + f" znacznik grupy „{m.group_name}”."
            self.tab._update_status()
            return
        t = mates[j]
        if not self.goto_us(t.at_us, t.last_us):
            if t.rec_id and t.id > 0:
                self.tab.open_recording_at(t.rec_id, t.at_us, t.last_us, self.tab.plot.window)
            else:
                self.tab.status_msg = "Następny znacznik grupy leży poza danymi tej karty."

    def opened(self, mid: int) -> None:
        dr = self.draft
        m = dr.get(mid) if dr else None
        if m:
            when = fmt_us(m.at_us) + (f" → {fmt_us(m.end_us)}" if m.kind in mk.SPAN_KINDS else "")
            self.tab.status_msg = f"Znacznik „{m.blurb()}” – {when}" + (f": {m.description}" if m.description else "")
            self.tab._update_status()

    def goto_us(self, a_us: int, b_us: int | None = None) -> bool:
        """Shows [a, b] (or the point a) in the middle of the chart. False = the data of the tab do not cover it."""
        span = self.data_span_us()
        if span is None:
            return False
        b_us = a_us if b_us is None else b_us
        if b_us < span[0] - 500_000 or a_us > span[1] + 500_000:
            return False
        w = max(self.tab.plot.window, (b_us - a_us) / 1e6 * 1.6, 0.1)
        mid = (a_us + b_us) / 2
        x0 = self.to_rel(int(mid)) - w / 2
        if self.tab.state in ("running", "reconnecting") and not self.tab.btn_pause.isChecked():
            self.tab.btn_pause.setChecked(True)                          # the live view would scroll away
        x0, x1 = self.tab.plot.clamp_view(x0, x0 + w)
        self.tab.plot.set_view(x0, x1)
        self.tab.plot.window = x1 - x0
        self.tab._on_zoomed(x1 - x0)
        self.sync(True)
        return True

    # ---- menus
    @staticmethod
    def _run_menu(menu: QMenu, pos) -> None:
        menu.exec(pos)

    def chart_menu(self, t: float, pos) -> None:
        m = QMenu(self.tab)
        m.addAction("Dodaj znacznik (punkt) tutaj…", lambda: self.add_at_us(self.to_wall(t)))
        w = max(self.tab.plot.window * 0.1, 0.5)
        m.addAction("Dodaj znacznik zakresu czasu tutaj…", lambda: self.add_at_us(self.to_wall(t), end_us=self.to_wall(t + w)))
        sig = self.level_signal()
        a = m.addAction("Dodaj znacznik różnicy poziomu…", lambda: self.add_at_us(self.to_wall(t), end_us=self.to_wall(t + w),
                                                                                 signals=[sig], kind="delta"))
        a.setEnabled(bool(sig))
        if self.hi_group:
            m.addAction(f"Wyłącz podświetlenie grupy „{self.hi_group}”", lambda: self.highlight_group(""))
        m.addSeparator()
        n = self.pending()
        a = m.addAction(f"Zapisz znaczniki ({n})…" if n else "Zapisz znaczniki")
        a.setEnabled(n > 0)
        a.triggered.connect(lambda: self.save())
        m.addAction("Lista znaczników…", self.open_list)
        m.addAction("Szukaj w danych…", self.open_search)
        a = m.addAction("Pokaż też znaczniki z innych połączeń")
        a.setCheckable(True)
        a.setChecked(self.show_all)
        a.toggled.connect(self._set_show_all)
        self._run_menu(m, pos)

    def level_signal(self) -> str:
        """The plot a level / difference marker set at the last right click is for: the lane under the click (lane layout),
        otherwise the first plotted signal; '' when nothing is plotted."""
        plot = self.tab.plot
        hit = plot._lane_value(plot.ctx_y) if plot.y_layout == "lanes" else None
        if hit:
            return hit[0]
        return next((s.name for s in plot.signals if s.plot), "")

    def _set_show_all(self, on: bool) -> None:
        self.show_all = on
        self.sync(True)

    def marker_menu(self, mid: int, pos) -> None:
        m = QMenu(self.tab)
        dr = self.draft
        mk_ = dr.get(mid) if dr else None
        if mk_ is None:
            return
        m.addAction("Edytuj znacznik…", lambda: self.edit(mid))
        a = m.addAction("Zmień pozycję znacznika")
        a.setCheckable(True)
        a.setChecked(mid in self.tab.plot.mmovable)
        a.toggled.connect(lambda on: self.set_movable(mid, on))
        m.addAction("Ukryj nazwę znacznika na wykresie" if mk_.show_label else "Pokaż nazwę znacznika na wykresie",
                    lambda: self.toggle_label(mid))
        g = m.addMenu("Grupa znaczników")
        g.addAction("Dodaj do grupy…" if not mk_.group_name else "Przenieś do innej grupy…", lambda: self.add_to_group([mid]))
        if mk_.group_name:
            gn = mk_.group_name
            g.addAction(f"Usuń z grupy „{gn}”", lambda: self.leave_group([mid]))
            g.addSeparator()
            g.addAction("Podświetl całą grupę", lambda: self.highlight_group(gn))
            g.addAction("Przejdź do następnego znacznika grupy", lambda: self.step_in_group(mid, 1))
            g.addAction("Przejdź do poprzedniego znacznika grupy", lambda: self.step_in_group(mid, -1))
            g.addAction("Zmień nazwę grupy…", lambda: self.rename_group(gn))
        if dr.state(mid):
            m.addAction("Cofnij zmiany tego znacznika (niezapisane)", lambda: self.revert(mid))
        m.addAction("Usuń znacznik", lambda: self.delete(mid))
        m.addAction("Pokaż na liście", lambda: self.open_list(select=mid))
        self._run_menu(m, pos)

    # ---- windows
    def open_list(self, select: int | None = None) -> None:
        if self.dlg is None:
            self.dlg = MarkersDialog(self)
        self.dlg.refresh()
        if select:
            self.dlg.select(select)
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def open_search(self) -> None:
        if self.search_dlg is None:
            self.search_dlg = SearchDialog(self)
        self.search_dlg.reload_signals()
        self.search_dlg.show()
        self.search_dlg.raise_()
        self.search_dlg.activateWindow()

    def _refresh_dialog(self) -> None:
        if self.dlg is not None and self.dlg.isVisible():
            self.dlg.refresh()

    def shutdown(self) -> None:
        for d in (self.dlg, self.search_dlg):
            if d is not None:
                d.shutdown()
                d.close()


# ------------------------------------------------------------------------------------------------ the list window
@dialog_info("Znaczniki", "Wszystkie znaczniki z tego komputera i konta: szukaj po tytule, opisie, uwagach, autorze; "
                          "dwuklik przechodzi do punktu na wykresie.")
class MarkersDialog(QDialog):
    COLS = ["Czas", "Tytuł", "Rodzaj", "Priorytet", "Dotyczy", "Grupa", "Autor", "Połączenie", "Zmieniono", "Stan"]

    def __init__(self, ctl: TabMarkers):
        super().__init__(ctl.tab)
        self.ctl = ctl
        self.setWindowTitle("Znaczniki")
        self.setWindowFlag(Qt.Window, True)
        self.resize(940, 560)
        self._rows: list[mk.Marker] = []
        lay = QVBoxLayout(self)
        f = QHBoxLayout()
        self.ed_text = QLineEdit()
        self.ed_text.setPlaceholderText("Szukaj w tytule, opisie, uwagach, autorze…")
        self.ed_text.setClearButtonEnabled(True)
        self.cb_prio = priority_combo(-1, "Priorytet: każdy")
        self.cb_prio.setItemText(0, "Priorytet: każdy")
        self.cb_color = QComboBox()
        self.cb_color.addItem("Kolor: każdy", None)
        for name, c in mk.PALETTE.items():
            self.cb_color.addItem(color_icon(c), name, c)
        self.cb_author = QComboBox()
        self.cb_scope = QComboBox()
        self.cb_scope.addItem("Ta karta (to połączenie)", "tab")
        self.cb_scope.addItem("Wszystkie połączenia", "all")
        self.cb_group = QComboBox()
        self.cb_order = QComboBox()
        for k, label in (("at", "wg czasu znacznika"), ("modified", "wg ostatniej zmiany"), ("priority", "wg priorytetu")):
            self.cb_order.addItem("Sortuj: " + label, k)
        lay.addWidget(self.ed_text)
        for w in (self.cb_prio, self.cb_color, self.cb_author, self.cb_group, self.cb_scope, self.cb_order):
            f.addWidget(w, 1)
        lay.addLayout(f)
        r = QHBoxLayout()
        self.chk_range = QCheckBox("Tylko od")
        self.dt0 = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1))
        self.dt1 = QDateTimeEdit(QDateTime.currentDateTime())
        for d in (self.dt0, self.dt1):
            d.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            d.setCalendarPopup(True)
            d.setEnabled(False)
        self.chk_range.toggled.connect(self.dt0.setEnabled)
        self.chk_range.toggled.connect(self.dt1.setEnabled)
        self.chk_vis = QCheckBox("Tylko widoczny zakres wykresu")
        r.addWidget(self.chk_range)
        r.addWidget(self.dt0)
        r.addWidget(QLabel("do"))
        r.addWidget(self.dt1)
        r.addSpacing(12)
        r.addWidget(self.chk_vis)
        r.addStretch()
        lay.addLayout(r)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)      # several markers at once -> 'Grupuj zaznaczone'
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.table.itemDoubleClicked.connect(lambda *_: self.go())
        lay.addWidget(self.table, 3)
        self.detail = QTextBrowser()
        self.detail.setMaximumHeight(130)
        lay.addWidget(self.detail, 1)
        self.lbl = QLabel("")
        lay.addWidget(self.lbl)
        b = QHBoxLayout()
        self.btn_add = QPushButton("Dodaj teraz")
        self.btn_add.setToolTip("Dodaje znacznik w ostatniej próbce (dane na żywo) albo na środku widocznego zakresu")
        self.btn_go = QPushButton("Przejdź do punktu")
        self.btn_edit = QPushButton("Edytuj…")
        self.btn_del = QPushButton("Usuń")
        self.btn_grp = QPushButton("Grupuj zaznaczone…")
        self.btn_grp.setToolTip("Łączy zaznaczone znaczniki (Ctrl / Shift + klik) w grupę, np. jedno zdarzenie")
        self.btn_ungrp = QPushButton("Wyjmij z grupy")
        self.btn_undo = QPushButton("Cofnij zmianę")
        self.btn_undo.setToolTip("Cofa niezapisaną zmianę zaznaczonego znacznika (nowy znika, zmieniony i usunięty wracają do stanu zapisanego)")
        self.btn_save = QPushButton("Zapisz znaczniki…")
        close = QPushButton("Zamknij")
        for x in (self.btn_add, self.btn_go, self.btn_edit, self.btn_del, self.btn_grp, self.btn_ungrp, self.btn_undo, self.btn_save):
            b.addWidget(x)
        b.addStretch()
        b.addWidget(close)
        lay.addLayout(b)
        self.btn_add.clicked.connect(lambda: ctl.add_now())
        self.btn_go.clicked.connect(self.go)
        self.btn_edit.clicked.connect(self.edit)
        self.btn_del.clicked.connect(self.delete)
        self.btn_grp.clicked.connect(lambda: self.ctl.add_to_group(self._selected_ids()))
        self.btn_ungrp.clicked.connect(lambda: self.ctl.leave_group(self._selected_ids()))
        self.btn_undo.clicked.connect(self.undo)
        self.btn_save.clicked.connect(lambda: self.ctl.save())
        close.clicked.connect(self.close)
        self._timer = QTimer(self)                       # typing in the search box: query after a short pause
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        self.ed_text.textChanged.connect(lambda *_: self._timer.start())
        for w in (self.cb_prio, self.cb_color, self.cb_author, self.cb_group, self.cb_scope, self.cb_order):
            w.currentIndexChanged.connect(lambda *_: self.refresh())
        for w in (self.chk_range, self.chk_vis):
            w.toggled.connect(lambda *_: self.refresh())
        for d in (self.dt0, self.dt1):
            d.dateTimeChanged.connect(lambda *_: self.refresh())
        self._buttons()

    def _buttons(self) -> None:
        on = self._current() is not None
        for x in (self.btn_go, self.btn_edit, self.btn_del):
            x.setEnabled(on)
        for x in (self.btn_grp, self.btn_ungrp):
            x.setEnabled(bool(self._selected_ids()))
        dr = self.ctl.draft
        self.btn_undo.setEnabled(bool(dr and any(dr.state(i) for i in self._selected_ids())))

    def _selected_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._rows[r].id for r in rows if 0 <= r < len(self._rows)]

    def _current(self) -> mk.Marker | None:
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def refresh(self) -> None:
        st, dr = self.ctl.store, self.ctl.draft
        if st is None or dr is None:
            return
        keep = self._current().id if self._current() else None
        a = self.cb_author.currentData()
        self.cb_author.blockSignals(True)
        self.cb_author.clear()
        self.cb_author.addItem("Autor: każdy", None)
        for name in st.authors():
            self.cb_author.addItem(name, name)
        self.cb_author.setCurrentIndex(max(self.cb_author.findData(a), 0))
        self.cb_author.blockSignals(False)
        g = self.cb_group.currentData()
        self.cb_group.blockSignals(True)
        self.cb_group.clear()
        self.cb_group.addItem("Grupa: każda", None)
        self.cb_group.addItem("(bez grupy)", "")
        for name, n in dr.groups():
            self.cb_group.addItem(f"{name} ({n})", name)
        self.cb_group.setCurrentIndex(max(self.cb_group.findData(g), 0))
        self.cb_group.blockSignals(False)
        t0 = t1 = None
        if self.chk_vis.isChecked():
            x0, x1 = self.ctl.tab.plot.view_range()
            t0, t1 = self.ctl.to_wall(x0), self.ctl.to_wall(x1)
        elif self.chk_range.isChecked():
            t0, t1 = self.dt0.dateTime().toMSecsSinceEpoch() * 1000, self.dt1.dateTime().toMSecsSinceEpoch() * 1000
        gsel = self.cb_group.currentData()
        col = self.cb_color.currentData()
        rows = dr.search(with_deleted=True, text=self.ed_text.text(), t0_us=t0, t1_us=t1, colors=[col] if col else None,
                         group=gsel, priorities=[self.cb_prio.currentData()] if self.cb_prio.currentData() is not None else None,
                         authors=[self.cb_author.currentData()] if self.cb_author.currentData() else None,
                         order=self.cb_order.currentData(), limit=2000)
        if self.cb_scope.currentData() == "tab":
            key = self.ctl.key()
            rows = [m for m in rows if m.conn in ("", key)]
        self._rows = rows
        self.table.setRowCount(len(rows))
        for i, m in enumerate(rows):
            state = dr.state(m.id)
            cells = [fmt_us(m.at_us), m.title or "(bez tytułu)",
                     mk.KINDS[m.kind] + (f" ({_dur((m.end_us - m.at_us) / 1e6)})" if m.kind in mk.SPAN_KINDS else ""),
                     mk.PRIORITIES.get(m.priority, str(m.priority)), ", ".join(m.signals) or "wszystkie", m.group_name,
                     m.author, m.conn, fmt_us(m.modified_us, False), "zapisany" if not state else "* " + STATE_PL[state]]
            for j, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if j == 1:
                    it.setIcon(color_icon(m.color))
                if state:
                    it.setForeground(QBrush(QColor(STATE_COLOR[state])))
                    if state == "deleted":
                        f = it.font()
                        f.setStrikeOut(True)
                        it.setFont(f)
                self.table.setItem(i, j, it)
        self.table.resizeColumnToContents(0)
        n = dr.count()
        self.lbl.setText(f"Znaczników: <b>{len(rows)}</b> z {st.count()} w pliku {st.path}"
                         + (f" · <span style='color:#e0a030'><b>niezapisanych zmian: {n}</b></span>" if n else ""))
        self.btn_save.setEnabled(n > 0)
        self.btn_save.setText(f"Zapisz znaczniki ({n})…" if n else "Zapisz znaczniki…")
        if keep is not None:
            self.select(keep)
        self._buttons()
        self._show_detail()

    def select(self, mid: int) -> None:
        for i, m in enumerate(self._rows):
            if m.id == mid:
                self.table.selectRow(i)
                return

    def _show_detail(self) -> None:
        self._buttons()
        m = self._current()
        self.detail.setHtml(marker_tip(m) if m else "")

    def go(self) -> None:
        m = self._current()
        if m is None:
            return
        if not self.ctl.goto_us(m.at_us, m.last_us):
            if m.rec_id:
                self.ctl.tab.open_recording_at(m.rec_id, m.at_us, m.last_us, self.ctl.tab.plot.window)
            else:
                QMessageBox.information(self, "S7Trace", "Punkt leży poza danymi tej karty (nie ma ich na wykresie).")

    def edit(self) -> None:
        m = self._current()
        if m:
            self.ctl.edit(m.id)

    def delete(self) -> None:
        m = self._current()
        if m:
            self.ctl.delete(m.id)

    def undo(self) -> None:
        for i in self._selected_ids():
            self.ctl.draft.revert(i)
        self.ctl._changed()

    def shutdown(self) -> None:
        self._timer.stop()


# ------------------------------------------------------------------------------------------------ the search window
class _Row:
    """One condition: [x] signal  operator  a  [b]  ± tolerance."""

    def __init__(self, signals: list[str], first: bool):
        self.on = QCheckBox()
        self.on.setChecked(first)
        self.sig = QComboBox()
        self.sig.addItems(signals)
        self.op = QComboBox()
        for k, (label, *_r) in sr.OPS.items():
            self.op.addItem(label, k)
        self.a, self.b, self.tol = QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox()
        for s in (self.a, self.b):
            s.setRange(-1e12, 1e12)
            s.setDecimals(6)
            s.setMinimumWidth(110)
        self.tol.setRange(0, 1e9)
        self.tol.setDecimals(6)
        self.tol.setPrefix("± ")
        self.tol.setMinimumWidth(90)
        self.op.currentIndexChanged.connect(self._ops)
        self.on.toggled.connect(self._ops)
        self._ops()

    def widgets(self):
        return [self.on, self.sig, self.op, self.a, self.b, self.tol]

    def _ops(self) -> None:
        k = self.op.currentData()
        n = sr.OPS[k][1]
        e = self.on.isChecked()
        self.sig.setEnabled(e)
        self.op.setEnabled(e)
        self.a.setEnabled(e and n >= 1)
        self.b.setEnabled(e and n >= 2)
        self.tol.setEnabled(e and k in ("==", "!="))

    def cond(self) -> sr.Cond | None:
        if not self.on.isChecked() or self.sig.currentIndex() < 0:
            return None
        return sr.Cond(self.sig.currentIndex(), self.op.currentData(), self.a.value(), self.b.value(), self.tol.value())


@dialog_info("Wyszukiwarka", "Szuka momentów, w których sygnały miały zadane wartości (albo się zmieniały), w danych tej karty "
                             "albo w wybranym nagraniu z bazy; wynik pokazuje się na wykresie.")
class SearchDialog(QDialog):
    _done = QtSignal(object)
    _prog = QtSignal(float)
    ROWS = 3

    def __init__(self, ctl: TabMarkers):
        super().__init__(ctl.tab)
        self.ctl = ctl
        self.setWindowTitle("Wyszukiwarka danych")
        self.setWindowFlag(Qt.Window, True)
        self.resize(900, 640)
        self.sessions: list[dict] = []
        self.hits: list[sr.Hit] = []
        self._rec: dict | None = None                       # the recording the shown hits come from
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        lay = QVBoxLayout(self)
        g = QGroupBox("Gdzie szukać")
        gl = QVBoxLayout(g)
        self.rb_tab = QRadioButton("Dane tej karty (wykres: na żywo, wczytane z pliku lub z bazy)")
        self.rb_tab.setChecked(True)
        self.rb_db = QRadioButton("Nagranie z bazy danych (cel zapisu tej karty):")
        gl.addWidget(self.rb_tab)
        row = QHBoxLayout()
        row.addWidget(self.rb_db)
        self.cb_rec = QComboBox()
        self.cb_rec.setEnabled(False)
        self.cb_rec.setMinimumWidth(300)
        self.btn_reload = QPushButton("Odśwież listę")
        self.btn_reload.setEnabled(False)
        row.addWidget(self.cb_rec, 1)
        row.addWidget(self.btn_reload)
        gl.addLayout(row)
        lay.addWidget(g)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        # --- values
        w = QWidget()
        wl = QVBoxLayout(w)
        self.grid = QFormLayout()
        self.rows: list[_Row] = []
        self.grid_box = QVBoxLayout()
        wl.addLayout(self.grid_box)
        wl.addWidget(QLabel("Gdy zaznaczysz kilka warunków, wynik to chwile, w których spełnione są WSZYSTKIE naraz."))
        r = QHBoxLayout()
        self.chk_range = QCheckBox("Tylko od")
        self.dt0 = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1))
        self.dt1 = QDateTimeEdit(QDateTime.currentDateTime())
        for d in (self.dt0, self.dt1):
            d.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            d.setCalendarPopup(True)
            d.setEnabled(False)
        self.chk_range.toggled.connect(self.dt0.setEnabled)
        self.chk_range.toggled.connect(self.dt1.setEnabled)
        self.sp_min = QDoubleSpinBox()
        self.sp_min.setRange(0, 1e7)
        self.sp_min.setDecimals(3)
        self.sp_min.setSuffix(" s")
        r.addWidget(self.chk_range)
        r.addWidget(self.dt0)
        r.addWidget(QLabel("do"))
        r.addWidget(self.dt1)
        r.addSpacing(16)
        r.addWidget(QLabel("Trwa co najmniej:"))
        r.addWidget(self.sp_min)
        r.addStretch()
        wl.addLayout(r)
        self.tabs.addTab(w, "Wartości sygnałów")
        # --- time
        w2 = QWidget()
        tl = QVBoxLayout(w2)
        tl.addWidget(QLabel("Przejdź do wybranej daty i godziny:"))
        t = QHBoxLayout()
        self.dt_go = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_go.setDisplayFormat(STAMP)
        self.dt_go.setCalendarPopup(True)
        self.btn_goto = QPushButton("Przejdź")
        t.addWidget(self.dt_go)
        t.addWidget(self.btn_goto)
        t.addStretch()
        tl.addLayout(t)
        self.lbl_span = QLabel("")
        self.lbl_span.setWordWrap(True)
        tl.addWidget(self.lbl_span)
        tl.addStretch()
        self.tabs.addTab(w2, "Godzina")
        # --- buttons + results
        b = QHBoxLayout()
        self.btn_search = QPushButton("Szukaj")
        self.btn_search.setDefault(True)
        self.btn_stop = QPushButton("Przerwij")
        self.btn_stop.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        b.addWidget(self.btn_search)
        b.addWidget(self.btn_stop)
        b.addWidget(self.progress, 1)
        lay.addLayout(b)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Początek", "Trwa", "Wartości na początku", "Min … max (pierwszy warunek)"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemDoubleClicked.connect(lambda *_: self.go())
        lay.addWidget(self.table, 1)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        bb = QHBoxLayout()
        self.btn_go = QPushButton("Pokaż wynik na wykresie")
        self.btn_mark = QPushButton("Dodaj znacznik w tym miejscu…")
        close = QPushButton("Zamknij")
        bb.addWidget(self.btn_go)
        bb.addWidget(self.btn_mark)
        bb.addStretch()
        bb.addWidget(close)
        lay.addLayout(bb)
        self.rb_db.toggled.connect(self._source_changed)
        self.cb_rec.currentIndexChanged.connect(lambda *_: self._signals_changed())
        self.btn_reload.clicked.connect(self.load_sessions)
        self.btn_search.clicked.connect(self.run)
        self.btn_stop.clicked.connect(self._cancel.set)
        self.btn_go.clicked.connect(self.go)
        self.btn_mark.clicked.connect(self.mark)
        self.btn_goto.clicked.connect(self.goto_time)
        self.table.itemSelectionChanged.connect(self._buttons)
        close.clicked.connect(self.close)
        self._done.connect(self._finished)
        self._prog.connect(lambda x: self.progress.setValue(int(x * 1000)))
        self._build_rows([])
        self._buttons()

    # ---- the condition rows
    def _build_rows(self, names: list[str]) -> None:
        while self.grid_box.count():
            it = self.grid_box.takeAt(0)
            lay = it.layout()
            if lay is not None:
                while lay.count():
                    lay.takeAt(0)
        for r in getattr(self, "rows", []):
            for w in r.widgets():
                w.setParent(None)
                w.deleteLater()
        self.rows = [_Row(names, i == 0) for i in range(self.ROWS)]
        for i, r in enumerate(self.rows):
            h = QHBoxLayout()
            h.addWidget(QLabel("Gdy" if i == 0 else "oraz"))
            for w in r.widgets():
                h.addWidget(w, 3 if w is r.sig else 1)
            self.grid_box.addLayout(h)

    def _names(self) -> list[str]:
        if self.rb_db.isChecked():
            s = self._session()
            return [x.get("name", "") for x in s["signals"]] if s else []
        return [s.name for s in self.ctl.tab._run_signals or self.ctl.tab.display_signals()]

    def reload_signals(self) -> None:
        self._signals_changed()
        sp = self.ctl.data_span_us()
        self.lbl_span.setText("Dane tej karty: " + (f"od <b>{fmt_us(sp[0], False)}</b> do <b>{fmt_us(sp[1], False)}</b>."
                                                    if sp else "brak danych.") + " Dla nagrania z bazy zakres podaje lista nagrań.")
        if sp:
            self.dt_go.setDateTime(qdt((sp[0] + sp[1]) // 2))

    def _signals_changed(self) -> None:
        names = self._names()
        cur = [(r.sig.currentText(), r.op.currentData(), r.on.isChecked(), r.a.value(), r.b.value(), r.tol.value())
               for r in self.rows]
        self._build_rows(names)
        for r, (sig, op, on, a, b, tol) in zip(self.rows, cur):                 # keep what the user typed where it fits
            i = r.sig.findText(sig)
            if i >= 0:
                r.sig.setCurrentIndex(i)
            r.op.setCurrentIndex(max(r.op.findData(op), 0))
            r.on.setChecked(on and i >= 0 or r is self.rows[0])
            r.a.setValue(a)
            r.b.setValue(b)
            r.tol.setValue(tol)

    def _source_changed(self, on: bool) -> None:
        self.cb_rec.setEnabled(on)
        self.btn_reload.setEnabled(on)
        if on and not self.sessions:
            self.load_sessions()
        self._signals_changed()

    def load_sessions(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.sessions = sr.list_sessions(self.ctl.tab.cfg.store, self._base())
            err = ""
        except Exception as e:
            self.sessions, err = [], str(e)
        finally:
            QApplication.restoreOverrideCursor()
        self.cb_rec.blockSignals(True)
        self.cb_rec.clear()
        for s in self.sessions:
            label = f"{fmt_us(s['start_us'], False)} – {s.get('title') or s.get('tab') or s.get('conf') or s['id']}"
            if s.get("owner"):
                label += f" ({s['owner']})"
            self.cb_rec.addItem(label, s["id"])
        self.cb_rec.blockSignals(False)
        loaded = self.ctl.rec_id()
        i = self.cb_rec.findData(loaded) if loaded else -1
        self.cb_rec.setCurrentIndex(i if i >= 0 else 0)
        self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {err}" if err else
                         f"Nagrań w bazie: <b>{len(self.sessions)}</b>.")
        self._signals_changed()

    @staticmethod
    def _base() -> str:
        from ..core.config import data_dir
        return data_dir()

    def _session(self) -> dict | None:
        sid = self.cb_rec.currentData()
        return next((s for s in self.sessions if s["id"] == sid), None)

    def _conds(self) -> list[sr.Cond]:
        return [c for c in (r.cond() for r in self.rows) if c is not None]

    # ---- running
    def _range_us(self, lo: int, hi: int) -> tuple[int, int]:
        if self.chk_range.isChecked():
            lo = max(lo, self.dt0.dateTime().toMSecsSinceEpoch() * 1000)
            hi = min(hi, self.dt1.dateTime().toMSecsSinceEpoch() * 1000)
        return lo, hi

    def run(self) -> None:
        conds = self._conds()
        if not conds:
            self.lbl.setText("Zaznacz co najmniej jeden warunek (i wybierz sygnał).")
            return
        self.table.setRowCount(0)
        self.hits, self._rec = [], None
        if self.rb_db.isChecked():
            self._run_db(conds)
        else:
            self._run_tab(conds)

    def _run_tab(self, conds: list[sr.Cond]) -> None:
        t, v = self.ctl.tab.buffer.snapshot()
        if len(t) == 0:
            self.lbl.setText("Ta karta nie ma jeszcze danych.")
            return
        base = self.ctl.to_wall(0.0)
        lo, hi = self._range_us(self.ctl.to_wall(float(t[0])), self.ctl.to_wall(float(t[-1])))
        sel = (t >= (lo - base) / 1e6) & (t <= (hi - base) / 1e6)
        try:
            hits = sr.find_hits(t[sel], v[sel], conds, min_duration=self.sp_min.value())
        except ValueError as e:
            self.lbl.setText(str(e))
            return
        self._show([sr.Hit(base + h.t0 * 1e6, base + h.t1 * 1e6, h.values, h.vmin, h.vmax) for h in hits], None)

    def _run_db(self, conds: list[sr.Cond]) -> None:
        s = self._session()
        if s is None:
            self.lbl.setText("Wybierz nagranie z listy.")
            return
        from ..core import store as st
        c = s["_cfg"]
        base = self._base()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            b = st.open_backend(c, base)
            end = sr.session_end_us(b, s)
            b.close()
        except Exception as e:
            self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        lo, hi = self._range_us(int(s["start_us"]), end)
        self._cancel.clear()
        self.btn_search.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.lbl.setText("Szukam w bazie…")
        mind = self.sp_min.value()

        def work():
            try:
                b2 = st.open_backend(c, base)
                try:
                    hits, _m = sr.search_backend(b2, s["id"], conds, lo, hi, min_duration=mind,
                                                 progress=self._prog.emit, cancel=self._cancel)
                finally:
                    b2.close()
                self._done.emit((hits, s, ""))
            except Exception as e:
                self._done.emit(([], s, str(e)))

        self._thread = threading.Thread(target=work, daemon=True, name="MarkerSearch")
        self._thread.start()

    def _finished(self, res) -> None:
        hits, s, err = res
        self.btn_search.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        if err:
            self.lbl.setText(f"<span style='color:#e04040'><b>Błąd:</b></span> {err}")
            return
        self._show(hits, s, cancelled=self._cancel.is_set())

    def _show(self, hits: list[sr.Hit], rec: dict | None, cancelled: bool = False) -> None:
        self.hits, self._rec = hits, rec
        names = [self.rows[0].sig.itemText(i) for i in range(self.rows[0].sig.count())]
        conds = self._conds()
        self.table.setRowCount(len(hits))
        for i, h in enumerate(hits):
            vals = ", ".join(f"{names[c.signal] if c.signal < len(names) else c.signal}={x:g}" for c, x in zip(conds, h.values))
            dur = "zdarzenie" if h.t1 == h.t0 and any(sr.OPS[c.op][2] for c in conds) else _dur(h.duration / 1e6)
            rng = f"{h.vmin:g} … {h.vmax:g}" if h.vmin == h.vmin else "–"
            for j, text in enumerate((fmt_us(int(h.t0)), dur, vals, rng)):
                self.table.setItem(i, j, QTableWidgetItem(text))
        self.table.resizeColumnToContents(0)
        more = f" (pokazano pierwsze {sr.MAX_HITS})" if len(hits) >= sr.MAX_HITS else ""
        self.lbl.setText(("Przerwano. " if cancelled else "") + f"Znaleziono: <b>{len(hits)}</b>{more}."
                         + ("" if hits else " Brak wyników – zmień warunki albo zakres czasu."))
        if hits:
            self.table.selectRow(0)
        self._buttons()

    def _buttons(self) -> None:
        on = self.table.currentRow() >= 0 and self.table.currentRow() < len(self.hits)
        self.btn_go.setEnabled(on)
        self.btn_mark.setEnabled(on)

    def _hit(self) -> sr.Hit | None:
        r = self.table.currentRow()
        return self.hits[r] if 0 <= r < len(self.hits) else None

    # ---- results -> chart
    def go(self) -> None:
        h = self._hit()
        if h is None:
            return
        self._open(int(h.t0), int(h.t1))

    def _open(self, a: int, b: int) -> None:
        if self._rec is None or self._rec["id"] == self.ctl.rec_id():
            if not self.ctl.goto_us(a, b):
                self.lbl.setText("Ten moment leży poza danymi tej karty.")
            return
        if not self.ctl.goto_us(a, b):                      # the recording is not on the chart: open the part around the hit
            self.ctl.tab.open_recording_at(self._rec["id"], a, b, self.ctl.tab.plot.window, self._rec)

    def mark(self) -> None:
        h = self._hit()
        if h is None:
            return
        if self._rec is not None and self._rec["id"] != self.ctl.rec_id():
            QMessageBox.information(self, "S7Trace", "Najpierw pokaż wynik na wykresie (otworzy to nagranie), "
                                    "potem dodaj znacznik.")
            return
        conds = self._conds()
        names = [self.rows[0].sig.itemText(i) for i in range(self.rows[0].sig.count())]
        desc = "; ".join(f"{names[c.signal]} {sr.OPS[c.op][0]}" + (f" {c.a:g}" if sr.OPS[c.op][1] else "") for c in conds)
        used = list(dict.fromkeys(names[c.signal] for c in conds))
        event = any(sr.OPS[c.op][2] for c in conds)
        self.ctl.add_at_us(int(h.t0), title="Wynik wyszukiwania", description=desc, signals=used,
                           end_us=int(h.t1) if (not event and h.t1 > h.t0) else None)

    def goto_time(self) -> None:
        us = self.dt_go.dateTime().toMSecsSinceEpoch() * 1000
        if self.ctl.goto_us(us):
            self.lbl.setText(f"Pokazano {fmt_us(us)}.")
            return
        if self.rb_db.isChecked() and self._session():
            s = self._session()
            if s["start_us"] <= us <= (s.get("end_us") or us):
                self.ctl.tab.open_recording_at(s["id"], us, us, self.ctl.tab.plot.window, s)
                return
        self.lbl.setText("Tego momentu nie ma w danych tej karty. Wybierz „Nagranie z bazy danych”, żeby szukać w bazie.")

    def shutdown(self) -> None:
        self._cancel.set()


def _dur(sec: float) -> str:
    if sec < 1:
        return f"{sec * 1000:.0f} ms"
    if sec < 120:
        return f"{sec:.2f} s"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min {s:02d} s" if h else f"{m} min {s:02d} s"
