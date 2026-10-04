"""Markers store and the value search (Qt-free core)."""
import threading

import numpy as np
import pytest

from s7trace.core import markers as mk
from s7trace.core import search as sr


@pytest.fixture
def store(tmp_path):
    return mk.MarkerStore(str(tmp_path / "m.db"))


def test_add_get_update_delete(store):
    m = store.add(1_700_000_000_000_000, author="jan", computer="PC1", title="Awaria", description="stop linii",
                  notes="sprawdzić czujnik", color="#FF0000", priority=3, conn="Linia 1")
    assert m.id and m.author == "jan" and m.modified_by == "jan" and m.created_us == m.modified_us
    assert m.color == "#ff0000" and m.priority == 3 and m.computer == "PC1"
    got = store.get(m.id)
    assert got == m
    u = store.update(m.id, {"title": "Awaria 2", "notes": "", "priority": 2}, by="ola")
    assert u.title == "Awaria 2" and u.notes == "" and u.priority == 2
    assert u.author == "jan" and u.modified_by == "ola" and u.modified_us >= m.modified_us
    assert u.created_us == m.created_us and u.description == "stop linii"
    assert store.delete(m.id) and not store.delete(m.id)
    assert store.get(m.id) is None
    with pytest.raises(KeyError):
        store.update(m.id, {"title": "x"})


def test_validation(store):
    with pytest.raises(mk.MarkerError):
        store.add(1_700_000_000_000_000, color="red")
    with pytest.raises(mk.MarkerError):
        store.add(1_700_000_000_000_000, priority=9)
    with pytest.raises(mk.MarkerError):
        store.add(0)
    with pytest.raises(mk.MarkerError):
        store.add(1_700_000_000_000_000, title="x" * 201)
    with pytest.raises(mk.MarkerError):
        store.add(1_700_000_000_000_000, title=5)
    m = store.add(1_700_000_000_000_000)
    assert m.title == "" and m.color == mk.DEFAULT_COLOR and m.priority == mk.DEFAULT_PRIORITY


def test_search(store):
    base = 1_700_000_000_000_000
    a = store.add(base + 10, author="jan", title="Żółty alarm", notes="Łódź", color="#ffd24a", priority=2, conn="L1")
    b = store.add(base + 20, author="ola", title="Start pompy", description="ręczny", priority=0, conn="L2")
    c = store.add(base + 30, author="jan", title="Koniec", priority=3, conn="L1", rec_id="r1")
    ids = lambda r: [m.id for m in r]
    assert ids(store.search()) == [a.id, b.id, c.id]
    assert ids(store.search("żółty")) == [a.id]
    assert ids(store.search("ŁÓDŹ")) == [a.id]              # Polish letters are case-folded
    assert ids(store.search("jan koniec")) == [c.id]         # every word, also in the author
    assert ids(store.search("100%")) == []
    assert ids(store.search(t0_us=base + 15, t1_us=base + 25)) == [b.id]
    assert ids(store.search(min_priority=2)) == [a.id, c.id]
    assert ids(store.search(priorities=[0])) == [b.id]
    assert ids(store.search(colors=["#FFD24A"])) == [a.id]
    assert ids(store.search(authors=["ola"])) == [b.id]
    assert ids(store.search(conn="L1", rec_id="")) == [a.id]
    assert ids(store.search(order="priority")) == [c.id, a.id, b.id]
    assert ids(store.search(limit=2)) == [a.id, b.id]
    store.update(a.id, {"title": "zmieniony"})
    assert ids(store.search(order="modified"))[0] == a.id
    assert store.authors() == ["jan", "ola"] and store.conns() == ["L1", "L2"]


def test_data_version_sees_other_connection(store, tmp_path):
    v0 = store.data_version()
    other = mk.MarkerStore(str(tmp_path / "m.db"))
    other.add(1_700_000_000_000_000, title="z drugiego programu")
    assert store.data_version() != v0
    assert store.count() == 1


def _mat(vals):
    t = np.arange(len(vals), dtype=float)
    return t, np.array(vals, dtype=float).reshape(len(vals), -1)


def test_find_hits_states_and_events():
    t, v = _mat([0, 0, 5, 5, 5, 0, 7, 7, 0])
    h = sr.find_hits(t, v, [sr.Cond(0, ">=", 5)])
    assert [(x.t0, x.t1) for x in h] == [(2, 5), (6, 8)]
    assert h[0].duration == 3 and h[0].values == [5.0] and h[1].vmax == 7
    assert [x.t0 for x in sr.find_hits(t, v, [sr.Cond(0, "==", 7)])] == [6]
    assert len(sr.find_hits(t, v, [sr.Cond(0, "between", 4, 6)])) == 1
    assert [x.t0 for x in sr.find_hits(t, v, [sr.Cond(0, "changes")])] == [2, 5, 6, 8]
    assert [x.t0 for x in sr.find_hits(t, v, [sr.Cond(0, "rises")])] == [2, 6]
    assert [x.t0 for x in sr.find_hits(t, v, [sr.Cond(0, "falls")])] == [5, 8]
    assert [x.t0 for x in sr.find_hits(t, v, [sr.Cond(0, ">=", 5)], min_duration=2.5)] == [2]
    assert sr.find_hits(t, v, [sr.Cond(0, ">", 100)]) == []
    with pytest.raises(ValueError):
        sr.find_hits(t, v, [sr.Cond(3, ">", 1)])


def test_find_hits_two_conditions_and_nan():
    t, v = _mat([[1, 5], [1, 0], [0, 5], [1, 5], [np.nan, 5]])
    h = sr.find_hits(t, v, [sr.Cond(0, "==", 1), sr.Cond(1, ">", 3)])
    assert [x.t0 for x in h] == [0, 3] and h[1].values == [1.0, 5.0]
    assert [x.t0 for x in sr.find_hits(t, v, [sr.Cond(0, "nan")])] == [4]
    assert [x.t0 for x in sr.find_hits(t, v, [sr.Cond(0, "!=", 1)])] == [2]      # NaN is never 'different'


class FakeBackend:
    """read() like a database: matrix of the asked range; refuses more than max_rows (-> the search halves the slice)."""
    def __init__(self, t_us, v, max_rows=10**9):
        self.t, self.v, self.max_rows = t_us, v, max_rows
        self.reads = 0

    def read(self, sid, a, b, max_points=0):
        from s7trace.core.store import StoreError
        self.reads += 1
        m = (self.t >= a) & (self.t <= b)
        if m.sum() > self.max_rows:
            raise StoreError("Za dużo danych do wczytania naraz")
        return {"id": sid}, self.t[m], self.v[m]


def test_search_backend_slices_and_merges():
    t = (np.arange(0, 3600) * 1_000_000 + 1_700_000_000_000_000).astype(np.int64)
    val = np.zeros((3600, 1))
    val[100:2000, 0] = 1                       # a long run that crosses several 10-minute slices
    val[3000:3003, 0] = 1
    be = FakeBackend(t, val)
    prog = []
    hits, meta = sr.search_backend(be, "x", [sr.Cond(0, "==", 1)], int(t[0]), int(t[-1]), slice_s=600, progress=prog.append)
    assert len(hits) == 2 and be.reads >= 6 and prog[-1] == 1.0 and meta["id"] == "x"
    assert hits[0].t0 == t[100] and hits[0].t1 == t[2000]
    assert hits[1].t0 == t[3000]
    be2 = FakeBackend(t, val, max_rows=300)    # too big for one slice -> halved
    hits2, _ = sr.search_backend(be2, "x", [sr.Cond(0, "==", 1)], int(t[0]), int(t[-1]), slice_s=1800)
    assert [(h.t0, h.t1) for h in hits2] == [(h.t0, h.t1) for h in hits]
    ev = threading.Event()
    ev.set()
    assert sr.search_backend(be, "x", [sr.Cond(0, "==", 1)], int(t[0]), int(t[-1]), cancel=ev)[0] == []
    long_only, _ = sr.search_backend(be, "x", [sr.Cond(0, "==", 1)], int(t[0]), int(t[-1]), min_duration=100.0)
    assert len(long_only) == 1


def test_range_markers_and_signal_assignment(store):
    base = 1_700_000_000_000_000
    p = store.add(base + 100, title="punkt")
    assert p.kind == "point" and p.end_us == 0 and p.signals == [] and p.applies_to("X") and p.last_us == base + 100
    r = store.add(base + 500, kind="range", end_us=base + 300, title="zakres", signals=["Temp", "Run", "Temp"])
    assert r.kind == "range" and (r.at_us, r.end_us) == (base + 300, base + 500)         # swapped into order
    assert r.signals == ["Temp", "Run"] and r.applies_to("Temp") and not r.applies_to("Inne") and r.last_us == base + 500
    assert store.get(r.id) == r
    with pytest.raises(mk.MarkerError):
        store.add(base, kind="range")                                                    # a range needs an end
    with pytest.raises(mk.MarkerError):
        store.add(base, kind="range", end_us=base)
    with pytest.raises(mk.MarkerError):
        store.add(base, kind="kropka")
    with pytest.raises(mk.MarkerError):
        store.add(base, signals="Temp")
    # a range counts when any part of it lies in the searched time range
    ids = lambda res: [m.id for m in res]
    assert ids(store.search(t0_us=base + 400, t1_us=base + 450)) == [r.id]
    assert ids(store.search(t0_us=base + 550)) == []
    assert ids(store.search(t0_us=base, t1_us=base + 200)) == [p.id]
    assert ids(store.search("run")) == [r.id]                                           # the assigned signals are searched too
    # change of the assignment and of the kind
    u = store.update(r.id, {"signals": []})
    assert u.signals == [] and u.kind == "range"
    u = store.update(r.id, {"kind": "point"})
    assert u.kind == "point" and u.end_us == 0
    u = store.update(r.id, {"kind": "range", "end_us": base + 900})
    assert u.kind == "range" and u.end_us == base + 900 and u.at_us == base + 300
    u = store.update(r.id, {"at_us": base + 1000})                                       # moved past the end -> still ordered
    assert u.at_us == base + 900 and u.end_us == base + 1000
    with pytest.raises(mk.MarkerError):
        store.update(r.id, {"end_us": u.at_us})


def test_visible_to_filter(store):
    base = 1_700_000_000_000_000
    a = store.add(base, author="Jan", conn="c1")
    b = store.add(base + 1, author="ola", conn="c2")
    c = store.add(base + 2, author="ola", conn="shared1")
    ids = lambda res: [m.id for m in res]
    assert ids(store.search(visible_to=("jan", []))) == [a.id]
    assert ids(store.search(visible_to=("jan", ["shared1"]))) == [a.id, c.id]
    assert ids(store.search(visible_to=("ola", ["c1"]))) == [a.id, b.id, c.id]


def test_groups(store):
    base = 1_700_000_000_000_000
    a = store.add(base, title="a", group_name="Awaria", author="jan")
    b = store.add(base + 1, title="b", author="jan")
    c = store.add(base + 2, title="c", group_name="Awaria", author="ola")
    d = store.add(base + 3, title="d", group_name="Start", author="ola")
    ids = lambda res: [m.id for m in res]
    assert store.groups() == [("Awaria", 2), ("Start", 1)]
    assert store.groups(visible_to=("jan", [])) == [("Awaria", 1)]
    assert ids(store.search(group="Awaria")) == [a.id, c.id] and ids(store.search(group="")) == [b.id]
    assert ids(store.search("awaria")) == [a.id, c.id]                              # the group name is searched as text too
    assert store.set_group([b.id, d.id], "Awaria", by="ola") == 2
    assert store.get(b.id).group_name == "Awaria" and store.get(b.id).modified_by == "ola"
    assert store.set_group([a.id], "") == 1 and store.get(a.id).group_name == ""
    assert store.rename_group("Awaria", "Awaria pompy 2") == 3
    assert store.groups() == [("Awaria pompy 2", 3)]
    assert store.rename_group("Awaria pompy 2", "Inna", only_ids=[b.id]) == 1
    assert store.groups() == [("Awaria pompy 2", 2), ("Inna", 1)]
    with pytest.raises(mk.MarkerError):
        store.set_group([a.id], "x" * 121)


def test_line_and_area_style(store):
    base = 1_700_000_000_000_000
    m = store.add(base, kind="range", end_us=base + 10)
    assert (m.line_width, m.line_style, m.opacity) == (0, "solid", mk.DEFAULT_OPACITY) and m.width_px() == 2
    u = store.update(m.id, {"line_width": 5, "line_style": "dashdot", "opacity": 80})
    assert (u.line_width, u.line_style, u.opacity, u.width_px()) == (5, "dashdot", 80, 5)
    assert store.get(m.id) == u
    q = store.add(base, priority=3)
    assert q.width_px() == 4
    for bad in ({"line_width": 9}, {"line_width": -1}, {"line_style": "falista"}, {"opacity": 101}, {"opacity": -1}, {"opacity": "x"}):
        with pytest.raises(mk.MarkerError):
            store.update(m.id, bad)
