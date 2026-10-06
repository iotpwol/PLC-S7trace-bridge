"""Axis titles without a margin of their own, the legend over a marker area, 'Otwórz Manual REC' in the menu of a saved area."""
import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsItem

from s7trace.core import rec_marks as rmk
from s7trace.ui.markers_ui import TabMarkers
from s7trace.ui.theme import apply_dark
from test_rec_marks_ui import db_tab, feed, pump


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


class Ev:
    """A scene click: right button at a scene position."""
    def __init__(self, pos, button=Qt.RightButton, double=False):
        self._pos, self._b, self._d, self.accepted = pos, button, double, False

    def button(self):
        return self._b

    def scenePos(self):
        return self._pos

    def screenPos(self):
        return QPointF(5, 5)

    def double(self):
        return self._d

    def accept(self):
        self.accepted = True


def test_axis_titles_take_no_space_and_can_be_dragged(app, tmp_path):
    tab = db_tab(tmp_path)
    tab.show()
    pump(lambda: False, 0.2)
    pv = tab.plot
    for t in (pv.title_x, pv.title_y):
        assert t.flags() & QGraphicsItem.ItemStacksBehindParent                 # the numbers cover the title, not the other way round
    assert pv.plot.getAxis("left").labelText == "" and pv.plot.getAxis("bottom").labelText == ""      # no pyqtgraph label = no reserved room
    assert pv.axis_y.width() <= 64 and pv.title_y.toPlainText() == "Sygnały"
    y0, f0 = pv.title_y.pos().y(), pv.title_y.frac
    ev = Ev(pv.axis_y.mapToScene(QPointF(5, pv.axis_y.boundingRect().height() * 0.2)), Qt.LeftButton)
    pv.title_y.mouseMoveEvent(ev)
    assert pv.title_y.frac < f0 and pv.title_y.pos().y() < y0                    # moved up along the axis
    pv.title_y.mouseMoveEvent(Ev(pv.axis_y.mapToScene(QPointF(5, -500)), Qt.LeftButton))
    assert pv.title_y.frac == 0.0                                               # kept inside the axis
    x0 = pv.title_x.pos().x()
    ax = pv.plot.getAxis("bottom")
    band = ax.mapRectToScene(QRectF(QPointF(0, 0), ax.size()))
    tr = pv.title_x.sceneBoundingRect()
    assert band.top() - 1 <= tr.top() and tr.bottom() <= band.bottom() + 4                # "Czas" sits in the band of the horizontal axis, not over the plot
    ly = pv.title_y.sceneBoundingRect()
    assert pv.axis_y.mapRectToScene(QRectF(QPointF(0, 0), pv.axis_y.size())).left() - 1 <= ly.left() and ly.right() <= pv.axis_y.sceneBoundingRect().right()
    y_before = pv.title_x.pos().y()
    pv.title_x.mouseMoveEvent(Ev(ax.mapToScene(QPointF(ax.boundingRect().width() * 0.1, 3)), Qt.LeftButton))
    assert pv.title_x.pos().x() < x0 and pv.title_x.pos().y() == y_before                # moves along the horizontal axis only
    tab.cb_ylayout.setCurrentIndex(tab.cb_ylayout.findData("offset"))
    assert pv.title_y.toPlainText() == "Offset"
    tab.shutdown()


def test_the_legend_gets_the_click_over_a_marker_area(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    tab.show()
    feed(tab, 0.0, 20.0)
    pv = tab.plot
    pv.refresh(force=True)
    pump(lambda: False, 0.2)
    class _NoMenu:                                                               # the real menus must not block the test
        def exec(self, *a):
            return None
    monkeypatch.setattr(tab, "_build_legend_menu", lambda: _NoMenu())
    legend, hits = pv.legend, []
    pv.legendContextMenu.connect(lambda pos: hits.append("legend"))
    pv.markerMenu.connect(lambda mid, pos: hits.append("marker"))
    assert legend.isVisible()
    inside = legend.sceneBoundingRect().center()
    ev = Ev(inside)
    pv._marker_clicked(rmk.pid(rmk.MANUAL, 1), ev)                               # the click that a marker area under the legend receives
    assert hits == ["legend"] and ev.accepted
    r = pv.vb.sceneBoundingRect()                                                 # elsewhere the marker menu opens as before
    far = next(p for p in (r.topLeft() + QPointF(4, 4), r.topRight() + QPointF(-4, 4), r.bottomLeft() + QPointF(4, -4), r.bottomRight() - QPointF(4, 4))
               if not legend.sceneBoundingRect().contains(p) and pv._tag_row_at(p) is None)
    pv._marker_clicked(rmk.pid(rmk.MANUAL, 1), Ev(far))
    assert hits == ["legend", "marker"]
    tab.shutdown()


def test_saved_manual_rec_menu_ends_with_the_info_and_opens_the_recording(app, tmp_path, monkeypatch):
    tab = db_tab(tmp_path)
    feed(tab, 0.0, 20.0)
    ctl = tab.mk
    ctl.rec.m.place_manual(5.0)
    ctl.rec.m.place_manual(12.0)
    ctl.rec.save_manual(1, wait=True)
    assert pump(lambda: ctl.rec.m.manual_get(1)["saved"] not in ("", "zapisuję…"))
    m = ctl.rec.m.manual_get(1)
    assert m["rid"] and m["b_us"] > m["a_us"]
    menus = []
    monkeypatch.setattr(TabMarkers, "_run_menu", staticmethod(lambda menu, pos: menus.append(menu)))
    ctl.rec.marker_menu(rmk.pid(rmk.MANUAL, 1), None)
    texts = [a.text() for a in menus[-1].actions() if not a.isSeparator()]
    assert texts[0] == "Zapis Manual REC (1)" and texts[1].startswith("Zmień pozycję") and texts[2] == "Przenieś Manual REC (1)" and texts[3] == "Usuń Manual REC (1)"
    assert texts[4].startswith("zapisano:") and texts[5] == f"Otwórz Manual REC (1): nagranie {m['rid']}"      # the info and 'open' at the end
    opened = []
    monkeypatch.setattr(type(tab), "open_recording_at", lambda self, rid, a, b, w, sess=None: opened.append((rid, a, b, w)))
    next(a for a in menus[-1].actions() if a.text().startswith("Otwórz")).trigger()
    assert opened == [(m["rid"], m["a_us"], m["b_us"], pytest.approx(7.0, abs=0.01))]
    tab.shutdown()


def test_saving_the_same_manual_rec_again_asks(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    tab = db_tab(tmp_path)
    feed(tab, 0.0, 20.0)
    rec = tab.mk.rec
    rec.m.place_manual(5.0)
    rec.m.place_manual(12.0)
    asked = []
    answer = {"v": QMessageBox.No}
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or answer["v"]))
    assert rec.save_manual(1, wait=True)
    assert pump(lambda: rec.m.manual_get(1)["saved"] not in ("", "zapisuję…")) and not asked      # the first save does not ask
    assert rec.save_manual(1, wait=True) is False and len(asked) == 1                              # the same area again: asked, answer No
    assert "jeszcze raz" in asked[0]
    answer["v"] = QMessageBox.Yes
    assert rec.save_manual(1, wait=True) and len(asked) == 2                                       # Yes: a second recording is written
    assert pump(lambda: rec.m.manual_get(1)["saved"] not in ("", "zapisuję…"))
    rec.m.move_manual(1, 6.0, 12.0)                                                                # a moved area is another recording: no question
    assert rec.save_manual(1, wait=True) and len(asked) == 2
    pump(lambda: rec.m.manual_get(1)["saved"] not in ("", "zapisuję…"))
    tab.shutdown()


def test_recorded_stretch_has_a_translucent_area(app, tmp_path):
    from s7trace.core import marker_look
    m = rmk.RecMarks()
    n = m.started(2.0, "sid1", "x")
    items = lambda: m.items(marker_look.normalize({}))
    assert [i for i in items() if rmk.parse(i["id"])[0] == rmk.AUTO_AREA] == []                    # still recording: no area yet
    m.stopped(9.0)
    area = [i for i in items() if rmk.parse(i["id"])[0] == rmk.AUTO_AREA]
    assert len(area) == 1 and (area[0]["x0"], area[0]["x1"]) == (2.0, 9.0) and area[0]["passive"] and area[0]["opacity"] > 0
    tab = db_tab(tmp_path)
    tab.plot.set_markers(items())
    cur = tab.plot.mitems[area[0]["id"]]
    assert cur["main"].acceptedMouseButtons() == Qt.NoButton                                      # a click goes through to the chart / the lines
    tab.shutdown()


def test_manual_rec_can_be_moved_with_a_ghost_and_the_chart_menu_is_grouped(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    tab = db_tab(tmp_path)
    feed(tab, 0.0, 20.0)
    ctl = tab.mk
    menus = []
    monkeypatch.setattr(TabMarkers, "_run_menu", staticmethod(lambda menu, pos: menus.append(menu)))
    ctl.rec.m.place_manual(5.0)                                                    # an open Manual Start REC (1)
    ctl.chart_menu(8.0, QPoint(1, 1))
    items = [("-" if a.isSeparator() else a.text()) for a in menus[-1].actions()]
    assert items == ["Dodaj znacznik (punkt) tutaj…", "Dodaj znacznik zakresu czasu tutaj…", "Dodaj znacznik różnicy poziomu…", "-",
                     "Manual Stop REC (1) tutaj", "Przenieś Manual Start REC (1)", "Usuń Manual Start REC (1)", "Pokaż…", "-",
                     "Zapisz znaczniki", "-", "Pokaż znacznik…", "Lista znaczników…", "Szukaj w danych…", "-", "Pokaż też znaczniki z innych połączeń"]     # one group per function
    show = next(a for a in menus[-1].actions() if a.text() == "Pokaż…").menu()
    assert [a.text().split(" – ")[0] for a in show.actions()] == ["Manual Start REC (1)"]              # every REC mark can be shown
    next(a for a in menus[-1].actions() if a.text().startswith("Przenieś")).trigger()
    assert ctl.rec.m.ghost == {"n": 1, "t": 5.0, "kind": "manual"} and tab.plot.ghost is not None
    tab.plot.ghost.setValue(3.0)
    ctl.rec._ghost_moved(3.0)
    ctl.rec._ghost_menu(QPoint(1, 1))
    gm = [("-" if a.isSeparator() else a.text()) for a in menus[-1].actions()]
    assert gm == ["Przenieś Manual Start REC (1) tutaj", "-", "Anuluj przenoszenie (usuń pulsujący znacznik)"]
    next(a for a in menus[-1].actions() if a.text().startswith("Anuluj")).trigger()
    assert ctl.rec.m.ghost is None and tab.plot.ghost is None and ctl.rec.m.manual_get(1)["a"] == 5.0          # cancelled: nothing moved
    ctl.rec.m.place_manual(12.0)                                                   # a complete area 5..12
    ctl.rec.marker_menu(rmk.pid(rmk.MANUAL, 1), None)
    texts = [a.text() for a in menus[-1].actions() if not a.isSeparator()]
    assert texts[:4] == ["Zapis Manual REC (1)", "Zmień pozycję (przeciągnij brzegi / obszar)", "Przenieś Manual REC (1)", "Usuń Manual REC (1)"]
    ctl.rec.begin_manual_ghost(1)
    tab.plot.ghost.setValue(8.0)
    ctl.rec._ghost_moved(8.0)
    ctl.rec.apply_ghost()                                                          # 'Przenieś … tutaj'
    m = ctl.rec.m.manual_get(1)
    assert (m["a"], m["b"]) == (8.0, 12.0) and ctl.rec.m.ghost is None and not m["saved"]
    tab.shutdown()


def test_web_manual_rec_ghost_and_grouped_menu():
    import os
    base = os.path.join(os.path.dirname(__import__("s7trace.web.server", fromlist=["x"]).__file__), "static")
    rm, mk = (open(os.path.join(base, f), encoding="utf-8").read() for f in ("recmarks.js", "markers.js"))
    assert "function recmGhostManual" in rm and "Przenieś Manual REC (" in rm and "Anuluj przenoszenie (usuń pulsujący znacznik)" in rm
    assert 'label: "Pokaż znacznik…"' in mk and "function recmPlaces" in rm and 'label: "Pokaż…"' in rm and        '"-", { label: "Lista znaczników…"' not in mk and '...(ctx.kind === "live" ? ["-", { label: (ctx.showAll' in mk


def test_show_menu_pauses_the_chart_and_moves_the_view(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    tab = db_tab(tmp_path)
    feed(tab, 0.0, 60.0)
    ctl = tab.mk
    ctl.rec.m.place_manual(30.0)
    ctl.rec.m.place_manual(40.0)
    ctl.rec.m.add_gap(10.0, 20.0)
    assert [n for n, _t in ctl.rec.m.places()] == ["Stop odczytu (1)", "Start odczytu (1)", "Manual Start REC (1)", "Manual Stop REC (1)"]
    menus = []
    monkeypatch.setattr(TabMarkers, "_run_menu", staticmethod(lambda menu, pos: menus.append(menu)))
    tab.plot.window = 10.0
    ctl.chart_menu(5.0, QPoint(1, 1))
    show = next(a for a in menus[-1].actions() if a.text() == "Pokaż…").menu()
    next(a for a in show.actions() if a.text().startswith("Manual Stop REC (1)")).trigger()
    x0, x1 = tab.plot.view_range()
    assert x0 < 40.0 < x1 and abs((x0 + x1) / 2 - 40.0) < 1.0                            # the view is centred on the mark
    # the other markers: 'Pokaż znacznik…' lists them by time
    ctl.store.add(ctl.to_wall(15.0), title="Alarm", conn=ctl.key())
    ctl.sync(True)
    ctl.chart_menu(5.0, QPoint(1, 1))
    sub = next(a for a in menus[-1].actions() if a.text() == "Pokaż znacznik…").menu()
    assert len(sub.actions()) == 1 and "Alarm" in sub.actions()[0].text()
    sub.actions()[0].trigger()
    x0, x1 = tab.plot.view_range()
    assert x0 < 15.0 < x1
    tab.shutdown()
