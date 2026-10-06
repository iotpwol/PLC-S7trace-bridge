"""REC marks on the chart of one tab: 'Start REC (n)' / 'Stop REC (n)' lines drawn by the program, 'Manual REC' areas the user puts on the
collected data and saves as a recording, and the moving of a Start REC (the ghost). The state is `core.rec_marks.RecMarks`; the work on the
data is `core.rec_ops`; this class is the menus, the dialogs and the threads."""
from __future__ import annotations

import dataclasses
import os
import threading

from PySide6.QtWidgets import QMenu, QMessageBox

from ..core import rec_marks as rmk, rec_ops, store
from ..core.config import data_dir
from ..core.rec_marks import RecMarks
from ..core.store import DbRecorder, device_summary, to_us

NOT_DB = ("Nagrywanie do pliku CSV: przesuwanie początku działa tylko dla baz danych (SQLite, InfluxDB, TimescaleDB) – "
          "plik CSV jest zapisywany na bieżąco i nie da się go uzupełnić z przodu.")


def _plain(text: str) -> str:
    return text.replace("<br>", " – ").replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")


class TabRecMarks:
    def __init__(self, tab):
        self.tab = tab
        self.m = RecMarks()
        p = tab.plot
        p.ghostMoved.connect(self._ghost_moved)
        p.ghostMenu.connect(self._ghost_menu)
        tab._recOpDone.connect(self._done)
        self._linked: dict[int, tuple[str, int, str]] = {}

    # ---- helpers
    @property
    def mk(self):
        return self.tab.mk

    def _say(self, text: str) -> None:
        self.tab.status_msg = text
        self.tab._update_status()

    def _changed(self) -> None:
        try:
            self.mk.sync(True)
            self.mk._refresh_dialog()
            self.tab.mk._update_save_button()
        except RuntimeError:                                     # the tab is being closed: its widgets are already gone
            pass

    def _fmt(self, t: float) -> str:
        from .markers_ui import fmt_us
        return fmt_us(self.mk.to_wall(t))

    def items(self) -> list[dict]:
        return self.m.items(self.tab.plot.mlook, self._fmt)

    def unsaved(self) -> list[dict]:
        return self.m.unsaved()

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self.tab, "S7Trace", text)

    # ---- events of the tab
    def new_run(self) -> None:
        """The connection (re)started: the chart is empty again, so are the marks."""
        self.cancel_ghost()
        self.m.reset()
        self._changed()

    def rec_started(self) -> None:
        t = self.tab.buffer.last_time() if len(self.tab.buffer) else 0.0
        r = self.tab.recorder
        self.m.started(t, r.session if isinstance(r, DbRecorder) else "", os.path.basename(getattr(r, "path", "") or "") if not isinstance(r, DbRecorder) else "")
        self._changed()

    def rec_stopped(self) -> None:
        t = self.tab.buffer.last_time() if len(self.tab.buffer) else 0.0
        self.m.stopped(t)
        self._changed()

    # ---- menus
    def chart_menu(self, menu: QMenu, t: float) -> None:
        """The REC part of the right click menu of the empty chart."""
        menu.addSeparator()
        op = self.m.open_manual()
        have = len(self.tab.buffer) > 0
        if op is None:
            a = menu.addAction(f"Manual Start REC ({self.m.next_manual_n()}) tutaj", lambda: self.place(t))
        else:
            a = menu.addAction(f"Manual Stop REC ({op['n']}) tutaj", lambda: self.place(t))
            menu.addAction(f"Przenieś Manual Start REC ({op['n']})", lambda n=op["n"]: self.begin_manual_ghost(n))
            menu.addAction(f"Usuń Manual Start REC ({op['n']})", lambda n=op["n"]: self.remove(n))
        a.setEnabled(have)
        sub = menu.addMenu("Pokaż…")                             # jump to a REC mark: the chart pauses and shows it in the middle
        places = self.m.places()
        sub.setEnabled(bool(places))
        for name, at in places:
            sub.addAction(f"{name} – {self._fmt(at)}", lambda at=at: self.show_place(at))

    def show_place(self, t: float) -> None:
        """'Pokaż…': pauses the chart and moves the view to the REC mark at chart time `t`."""
        if not self.mk.goto_us(self.mk.to_wall(t)):
            self._say("Ten znacznik leży poza danymi tej karty.")

    def marker_menu(self, mid: int, pos) -> None:
        kind, n = rmk.parse(mid)
        menu = QMenu(self.tab)
        if kind == rmk.AUTO_START:
            ok, why = self.can_move(n)
            a = menu.addAction(f"Przesuń Start REC ({n})…", lambda: self.begin_ghost(n))
            a.setEnabled(ok)
            if not ok:
                a.setToolTip(why)
                menu.addAction("(przesuwanie niedostępne – najedź na pozycję, by zobaczyć powód)").setEnabled(False)
        elif kind in (rmk.SCAN_STOP, rmk.SCAN_START):
            g = next((x for x in self.m.gaps if x["n"] == n), None)
            if g is None:
                return
            stop = kind == rmk.SCAN_STOP
            menu.addAction(f"{'Stop' if stop else 'Start'} odczytu ({n}): {self._fmt(g['t0'] if stop else g['t1'])}").setEnabled(False)
            menu.addAction(f"przerwa w odczycie: {g['t1'] - g['t0']:.1f} s").setEnabled(False)
        elif kind == rmk.AUTO_STOP:
            menu.addAction(f"Stop REC ({n}): {self._fmt(self.m.span(n)['t1'])}").setEnabled(False)
        else:
            m = self.m.manual_get(n)
            if m is None:
                return
            done = m["b"] is not None
            a = menu.addAction(f"Zapis Manual REC ({n})", lambda: self.save_manual(n))
            a.setEnabled(done)
            mv = menu.addAction("Zmień pozycję (przeciągnij brzegi / obszar)")
            mv.setCheckable(True)
            mv.setChecked(mid in self.tab.plot.mmovable)
            mv.toggled.connect(lambda on: self.tab.plot.set_marker_movable(mid, on))
            menu.addAction(f"Przenieś Manual REC ({n})", lambda: self.begin_manual_ghost(n))
            menu.addAction(f"Usuń Manual REC ({n})", lambda: self.remove(n))
            if m["saved"]:
                menu.addSeparator()
                menu.addAction(f"zapisano: {m['saved']}").setEnabled(False)
                rid = m.get("rid", "")
                if rid and not rid.startswith("csv:"):               # a recording of the database: open it (the usual question: this tab / a new one)
                    menu.addAction(f"Otwórz Manual REC ({n}): nagranie {rid}", lambda: self.open_saved(n))
        self.mk._run_menu(menu, pos)

    def opened(self, mid: int) -> None:
        """Left click on a REC mark: the status bar tells what it is."""
        it = next((i for i in self.items() if i["id"] == mid), None)
        if it:
            self._say(_plain(it["tip"]))

    def moved(self, mid: int, x0: float, x1: float) -> None:
        kind, n = rmk.parse(mid)
        if kind == rmk.MANUAL:
            m = self.m.manual_get(n)
            if m is not None:
                self.m.move_manual(n, x0, x1 if m["b"] is not None else None)
                self._say(f"Manual REC ({n}) przesunięty – zapisz go ponownie (prawy przycisk → Zapis Manual REC albo „Zapisz znaczniki”).")
                self._changed()

    # ---- manual areas
    def place(self, t: float) -> None:
        try:
            n, what = self.m.place_manual(t)
        except ValueError as e:
            self._warn(str(e))
            return
        self._say(f"Manual Start REC ({n}) ustawiony – wybierz miejsce i dodaj „Manual Stop REC ({n})”." if what == "start" else
                  f"Obszar Manual REC ({n}) ustawiony: prawy przycisk na obszarze → „Zapis Manual REC ({n})” albo przycisk „Zapisz znaczniki”.")
        self._changed()

    def remove(self, n: int) -> None:
        self.tab.plot.set_marker_movable(rmk.pid(rmk.MANUAL, n), False)
        self.m.remove_manual(n)
        self._changed()

    def manual_rows(self) -> list[dict]:
        return [{"n": m["n"], "a": self._fmt(m["a"]), "b": self._fmt(m["b"]), "dur": m["b"] - m["a"]} for m in self.unsaved()]

    def open_saved(self, n: int) -> None:
        """'Otwórz Manual REC (n)': the recording the area was saved as, shown the way 'Przegląd nagrań' / a marker of a recording does."""
        m = self.m.manual_get(n)
        if m is None or not m.get("rid"):
            return
        a_us, b_us = m.get("a_us", 0), m.get("b_us", 0)
        self.tab.open_recording_at(m["rid"], a_us, b_us, max((b_us - a_us) / 1e6, 1.0))

    def save_selected(self, ns: list[int], wait: bool = False) -> None:
        for n in ns:
            self.save_manual(n, wait)

    def _ask_again(self, n: int, where: str) -> bool:
        """The area is saved already and has not moved since (moving clears 'saved'): the same data would become a second, identical recording."""
        return QMessageBox.question(
            self.tab, "Zapis Manual REC",
            f"Manual REC ({n}) został już zapisany jako nagranie:\n{where}\n\nTen sam obszar nie zmienił się od zapisu. "
            "Czy zapisać dokładnie to samo nagranie jeszcze raz?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def save_manual(self, n: int, wait: bool = False) -> bool:
        """'Zapis Manual REC (n)': the data of the area become a recording of their own (database of the tab / CSV file)."""
        tab, m = self.tab, self.m.manual_get(n)
        if m is None or m["b"] is None:
            self._warn("Ten obszar nie ma jeszcze końca – dodaj „Manual Stop REC”.")
            return False
        if m["saved"] == "zapisuję…":
            self._warn(f"Manual REC ({n}) jest właśnie zapisywany.")
            return False
        if m["saved"] and not self._ask_again(n, m["saved"]):
            return False
        buf = tab.buffer
        if len(buf) == 0:
            self._warn("Brak danych na wykresie.")
            return False
        a, b = max(m["a"], buf.first_time()), min(m["b"], buf.last_time())
        t, v = buf.snapshot(a, b)
        if b <= a or not ((t >= a) & (t <= b)).any():
            self._warn("W zaznaczonym obszarze nie ma zebranych próbek (poza zakresem danych wykresu).")
            return False
        c = tab._collect()
        cfg = dataclasses.replace(c.store)
        csv_path = ""
        if cfg.kind == "csv":
            from ..core.trigger import DEFAULT_REC_NAME
            base, ext = os.path.splitext(tab._file_name(c.rec_filename or DEFAULT_REC_NAME, "REC", c.rec_folder or "rec"))
            csv_path, k = f"{base}_manual{n}{ext}", 1
            while os.path.exists(csv_path):
                csv_path, k = f"{base}_manual{n}_{k}{ext}", k + 1
        meta = {"name": tab.title(), "ip": c.ip, "tab": tab.title(), "conf": c.conf_name, "title": rmk.RecMarks.name_manual(n),
                "device": device_summary(tab.device, c.ip),
                "notes": f"Ręcznie zaznaczony obszar wykresu: {self._fmt(a)} – {self._fmt(b)}"}
        sigs, start_wall, folder = list(tab._run_signals or tab.display_signals()), tab.start_wall, data_dir()
        m["saved"] = "zapisuję…"
        self._changed()

        def work():
            try:
                where, sid = rec_ops.save_range_recording(cfg, sigs, start_wall, t, v, a, b, meta, folder, csv_path)
                self._linked[n] = (sid or ("csv:" + os.path.basename(csv_path) if csv_path else ""), to_us(start_wall, a), to_us(start_wall, b))
                err = ""
            except Exception as e:                               # database away / disk full: the area stays unsaved
                where, err = "", str(e) or type(e).__name__
            try:
                tab._recOpDone.emit("manual", n, where, err)
            except RuntimeError:                                 # the tab is gone
                pass

        th = threading.Thread(target=work, daemon=True, name="ManualRec")
        th.start()
        if wait:
            th.join(120)
        return True

    # ---- moving a Start REC
    def can_move(self, n: int) -> tuple[bool, str]:
        span = self.m.span(n)
        if span is None:
            return False, "Nie ma takiego znacznika."
        if len(self.tab.buffer) == 0:
            return False, "Brak danych na wykresie."
        if not span["sid"]:
            return False, NOT_DB
        return True, ""

    def begin_ghost(self, n: int) -> None:
        span = self.m.span(n)
        if span is None:
            return
        tab = self.tab
        if tab.state in ("running", "reconnecting") and not tab.btn_pause.isChecked():
            tab.btn_pause.setChecked(True)                       # the live view would scroll away under the cursor
        look = tab.plot.mlook
        self.m.set_ghost(n, span["t0"])
        tab.plot.set_ghost(span["t0"], look["rec_color"], look["rec_width"], f"{RecMarks.name_start(n)} – nowy początek")
        self._say(f"Przeciągnij pulsujący znacznik tam, gdzie ma się zaczynać nagranie, potem prawy przycisk na nim → „Zmień Start REC ({n})”.")

    def begin_manual_ghost(self, n: int) -> None:
        """'Przenieś Manual REC (n)': a pulsing twin of its Start line appears; drag it, then right click on it -> 'Przenieś … tutaj' / cancel."""
        m = self.m.manual_get(n)
        if m is None:
            return
        tab = self.tab
        if tab.state in ("running", "reconnecting") and not tab.btn_pause.isChecked():
            tab.btn_pause.setChecked(True)                       # the live view would scroll away under the cursor
        self.cancel_ghost()
        look = tab.plot.mlook
        self.m.set_ghost(n, m["a"], "manual")
        tab.plot.set_ghost(m["a"], look["rec_color"], look["rec_width"], f"Manual Start REC ({n}) – nowa pozycja")
        self._say(f"Przeciągnij pulsujący znacznik w nowe miejsce, potem prawy przycisk na nim → „Przenieś Manual Start REC ({n}) tutaj” albo „Anuluj przenoszenie”.")

    def cancel_ghost(self) -> None:
        self.m.set_ghost(None)
        self.tab.plot.set_ghost(None)

    def _ghost_moved(self, x: float) -> None:
        if self.m.ghost is not None:
            self.m.ghost["t"] = x
            if self.m.ghost.get("kind") == "manual":
                self._say(f"Nowy początek Manual REC ({self.m.ghost['n']}): {self._fmt(x)} – prawy przycisk na pulsującym znaczniku → „Przenieś … tutaj”.")
            else:
                self._say(f"Nowy początek nagrania ({self.m.ghost['n']}): {self._fmt(x)} – prawy przycisk na pulsującym znaczniku → „Zmień Start REC”.")

    def _ghost_menu(self, pos) -> None:
        g = self.m.ghost
        if g is None:
            return
        menu = QMenu(self.tab)
        if g.get("kind") == "manual":
            menu.addAction(f"Przenieś Manual Start REC ({g['n']}) tutaj", self.apply_ghost)
            menu.addSeparator()
            menu.addAction("Anuluj przenoszenie (usuń pulsujący znacznik)", self.cancel_ghost)
        else:
            menu.addAction(f"Zmień Start REC ({g['n']})", self.apply_ghost)
            menu.addAction("Anuluj przesuwanie", self.cancel_ghost)
        self.mk._run_menu(menu, pos)

    def apply_ghost(self) -> None:
        g = self.m.ghost
        if g is None or self.tab.plot.ghost is None:
            return
        new_t = float(self.tab.plot.ghost.value())
        n = g["n"]
        kind = g.get("kind")
        self.cancel_ghost()
        if kind == "manual":                                     # only the Manual REC area itself moves (nothing is written yet)
            m = self.m.manual_get(n)
            if m is not None:
                self.m.move_manual(n, new_t, m["b"])
                self._say(f"Manual REC ({n}) przeniesiony – zapisz go (prawy przycisk → Zapis Manual REC albo „Zapisz znaczniki”).")
                self._changed()
            return
        self.change_start(n, new_t)

    def change_start(self, n: int, new_t: float) -> bool:
        """Moves the start of recording n to `new_t` (chart seconds): earlier = the missing part is filled in from the buffer, later = the
        data before the new start are deleted from the database. Runs in the background; the result comes back as `_recOpDone`."""
        ok, why = self.can_move(n)
        if not ok:
            self._warn(why)
            return False
        tab, span = self.tab, self.m.span(n)
        old = span["t0"]
        c = tab._collect()
        cfg = dataclasses.replace(c.store)
        key_s = max(cfg.keyframe_min, 0.0) * 60.0 if cfg.mode == "changes" else 0.0
        try:
            plan = rec_ops.plan_move(tab.buffer, tab.start_wall, span, new_t, cfg.mode, key_s, len(tab._run_signals))
        except ValueError as e:
            if "takiego samego" not in str(e):
                self._warn(str(e))
            return False
        rows, new_us, first = plan["rows"], plan["new_us"], plan["first"]
        note = (f"\n\nBufor wykresu sięga tylko do {self._fmt(first)} – nagranie zostanie uzupełnione od tego miejsca."
                if plan["clamped"] else "")
        if plan["earlier"]:
            ask = (f"Przesunąć {RecMarks.name_start(n)} wcześniej ({self._fmt(old)} → {self._fmt(first)})?\n\nDo nagrania w bazie zostanie "
                   f"dopisane {old - first:.1f} s danych z bufora wykresu.{note}")
        else:
            ask = (f"Przesunąć {RecMarks.name_start(n)} później ({self._fmt(old)} → {self._fmt(first)})?\n\nDane tego nagrania sprzed nowego "
                   f"początku ({first - old:.1f} s) zostaną USUNIĘTE z bazy – tego nie da się cofnąć.")
        if QMessageBox.question(tab, "Zmień Start REC", ask) != QMessageBox.Yes:
            return False
        sid, running = span["sid"], span["t1"] is None and isinstance(tab.recorder, DbRecorder) and tab.recorder.session == span["sid"]
        start_wall, folder = tab.start_wall, data_dir()

        def finish(err: str) -> None:
            try:
                tab._recOpDone.emit("start", n, repr(first), err)
            except RuntimeError:
                pass

        if running:                                              # the writer thread does it in step with the rows it writes
            def job(be):
                meta = next((s for s in be.sessions() if s["id"] == sid), None)
                if meta is None:
                    raise store.StoreError("Nie znaleziono nagrania w bazie.")
                rec_ops.move_start(be, meta, new_us, rows)
            tab.recorder.submit(job, finish)
        else:
            def work():
                err, be = "", None
                try:
                    use = cfg
                    if cfg.kind == "sqlite":
                        use = dataclasses.replace(cfg, sqlite_path=store.rotated_sqlite_path(cfg, folder, start_wall))
                    be = store.open_backend(use, folder)
                    meta = next((s for s in be.sessions() if s["id"] == sid), None)
                    if meta is None:
                        raise store.StoreError("Nie znaleziono nagrania w bazie (czy ustawienia bazy się nie zmieniły?).")
                    rec_ops.move_start(be, meta, new_us, rows)
                except Exception as e:
                    err = str(e) or type(e).__name__
                finally:
                    if be is not None:
                        be.close()
                finish(err)
            threading.Thread(target=work, daemon=True, name="MoveRecStart").start()
        self._say(f"Zmieniam {RecMarks.name_start(n)} w bazie…")
        return True

    # ---- results (GUI thread)
    def _done(self, kind: str, n: int, text: str, err: str) -> None:
        if kind == "manual":
            if err:
                self.m.mark_saved(n, "")
                self._warn(f"Nie udało się zapisać Manual REC ({n}):\n{err}")
            else:
                self.m.mark_saved(n, text)
                self._say(f"Zapisano Manual REC ({n}) → {text}")
                rid, a_us, b_us = self._linked.pop(n, ("", 0, 0))
                m = self.m.manual_get(n)
                if m is not None:
                    m["rid"], m["a_us"], m["b_us"] = rid, a_us, b_us   # what 'Otwórz Manual REC' needs
                self.tab.mk.link_range(rid, a_us, b_us)               # markers inside the area belong to the new recording
        elif kind == "start":
            if err:
                self._warn(f"Nie udało się zmienić {RecMarks.name_start(n)}:\n{err}")
            else:
                first = float(text)
                span = self.m.span(n)
                old, sid = (span["t0"], span["sid"] or ("csv:" + span.get("file", "") if span.get("file") else "")) if span else (first, "")
                self.m.set_start(n, first)
                if span is not None and sid:                                 # the markers follow the data that moved in / out of the recording
                    t = self.tab
                    if first < old:
                        t.mk.link_range(sid, to_us(t.start_wall, first), to_us(t.start_wall, old))
                    else:
                        t.mk.unlink_range(sid, to_us(t.start_wall, old), to_us(t.start_wall, first))
                self._say(f"{RecMarks.name_start(n)} przesunięty na {self._fmt(first)} (zmiana zapisana w bazie).")
        self._changed()
