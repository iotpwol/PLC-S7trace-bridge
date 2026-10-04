"""Unsaved marker changes (draft), the batch write of the store and the in-memory marker selection."""
import pytest

from s7trace.core import marker_draft as md
from s7trace.core import markers as mk

BASE = 1_700_000_000_000_000


@pytest.fixture
def store(tmp_path):
    return mk.MarkerStore(str(tmp_path / "m.db"))


def ids(res):
    return [m.id for m in res]


def test_matches_agrees_with_the_store_search(store):
    a = store.add(BASE, author="Jan", title="Alarm Łódź", priority=3, color="#ff0000", conn="c1", group_name="G", signals=["T"])
    b = store.add(BASE + 10, kind="range", end_us=BASE + 50, author="ola", title="Start", conn="c2", description="ręczny")
    c = store.add(BASE + 100, author="ola", rec_id="r1", notes="x")
    allm = store.search()
    crits = [{}, {"text": "łódź"}, {"text": "ręczny start"}, {"t0_us": BASE + 40, "t1_us": BASE + 60}, {"t0_us": BASE + 60},
             {"colors": ["#FF0000"]}, {"min_priority": 2}, {"priorities": [1]}, {"authors": ["ola"]}, {"conn": "c1"}, {"rec_id": "r1"},
             {"group": "G"}, {"group": ""}, {"visible_to": ("jan", ["c2"])}, {"text": "t"}, {"created_from": 0, "created_to": 1}]
    for cr in crits:
        want = ids(store.search(**cr))
        got = [m.id for m in allm if mk.matches(m, **cr)]
        assert got == want, cr


def test_store_apply_is_one_transaction(store):
    old = store.add(BASE, title="stary", author="jan")
    gone = store.add(BASE + 1, title="do usunięcia", author="jan")
    rep = store.apply([{"at_us": BASE + 5, "title": "nowy", "conn": "c1"}], [(old.id, {"title": "zmieniony"})], [gone.id, 999], by="ola",
                      computer="PC")
    assert rep["updated"] == 1 and rep["deleted"] == 1 and rep["missing"] == [999] and len(rep["added"]) == 1
    n = store.get(rep["added"][0])
    assert (n.title, n.author, n.computer, n.conn) == ("nowy", "ola", "PC", "c1")
    assert store.get(old.id).title == "zmieniony" and store.get(old.id).modified_by == "ola" and store.get(gone.id) is None
    before = store.count()
    with pytest.raises(mk.MarkerError):                                  # one bad change: nothing at all is written
        store.apply([{"at_us": BASE, "title": "dobry"}, {"at_us": BASE, "color": "zły"}], [], [])
    assert store.count() == before
    with pytest.raises(mk.MarkerError):
        store.apply([], [(old.id, {"priority": 9})], [old.id])
    assert store.get(old.id) is not None


def test_show_label_field(store):
    m = store.add(BASE, title="x")
    assert m.show_label == 1
    assert store.update(m.id, {"show_label": 0}).show_label == 0
    assert store.update(m.id, {"show_label": True}).show_label == 1
    assert store.add(BASE, show_label=False).show_label == 0
    for bad in ("tak", 2, None, 0.5):
        with pytest.raises(mk.MarkerError):
            store.update(m.id, {"show_label": bad})


def test_draft_new_edit_delete_are_not_written(store):
    s1 = store.add(BASE, title="zapisany 1", author="jan")
    s2 = store.add(BASE + 10, title="zapisany 2", author="jan")
    s3 = store.add(BASE + 20, title="zapisany 3", author="jan")
    d = md.MarkerDraft(store)
    assert not d.dirty() and d.count() == 0 and d.changes() == []
    n = d.add(BASE + 5, "jan", "PC", title="nowy", conn="c1")
    assert n.id < 0 and d.state(n.id) == "new" and store.count() == 3 and d.get(n.id) is n
    e = d.update(s1.id, {"title": "zapisany 1 (zm.)", "color": "#00ff00", "at_us": BASE + 1}, by="ola")
    assert d.state(s1.id) == "edited" and e.title.endswith("(zm.)") and e.modified_by == "ola"
    assert store.get(s1.id).title == "zapisany 1"                        # the file is untouched
    assert d.delete(s2.id) and d.state(s2.id) == "deleted" and d.get(s2.id) is None and d.get(s2.id, with_deleted=True).title == "zapisany 2"
    assert d.count() == 3 and d.dirty()
    # the overlay: new + edited in, deleted out
    assert [m.title for m in d.search()] == ["zapisany 1 (zm.)", "nowy", "zapisany 3"]
    assert [m.title for m in d.search(with_deleted=True)] == ["zapisany 1 (zm.)", "nowy", "zapisany 2", "zapisany 3"]
    assert [m.title for m in d.search(text="zm.")] == ["zapisany 1 (zm.)"]                 # a search sees the edited text
    assert [m.title for m in d.search(text="zapisany 1")] == ["zapisany 1 (zm.)"] and d.search(text="nowy")[0].id == n.id
    assert [m.title for m in d.search(colors=["#00ff00"])] == ["zapisany 1 (zm.)"]
    assert d.search(colors=["#ff9f1c"], text="zapisany") == [m for m in d.search(text="zapisany 3")]   # the edit left the old colour
    assert [m.title for m in d.search(limit=1)] == ["zapisany 1 (zm.)"]
    assert d.groups() == []
    # the list the save window shows
    ch = d.changes()
    assert [(c.state, c.marker.title) for c in ch] == [("new", "nowy"), ("edited", "zapisany 1 (zm.)"), ("deleted", "zapisany 2")]
    assert ch[1].fields == ["tytuł", "kolor", "czas"] and ch[1].before.title == "zapisany 1"
    # commit: one transaction, then the draft is empty and the file has everything
    rep = d.commit(by="jan", computer="PC")
    assert rep["updated"] == 1 and rep["deleted"] == 1 and len(rep["added"]) == 1 and rep["new_ids"] == {n.id: rep["added"][0]}
    assert not d.dirty() and d.changes() == []
    assert sorted(m.title for m in store.search()) == ["nowy", "zapisany 1 (zm.)", "zapisany 3"]
    saved = store.get(rep["added"][0])
    assert saved.conn == "c1" and saved.author == "jan" and saved.computer == "PC"
    assert store.get(s1.id).color == "#00ff00" and store.get(s3.id).title == "zapisany 3"


def test_draft_edit_rules(store):
    s1 = store.add(BASE, title="a", author="jan")
    d = md.MarkerDraft(store)
    d.update(s1.id, {"title": "b"})
    d.update(s1.id, {"title": "c", "priority": 3})                       # twice: still one edit, from the saved version
    assert d.count() == 1 and [c.fields for c in d.changes()] == [["tytuł", "priorytet"]]
    d.update(s1.id, {"title": "a", "priority": s1.priority})             # back to the saved state: no edit left
    assert d.count() == 0 and not d.dirty()
    # a new marker edited and deleted before saving leaves no trace; an edited saved marker that is deleted is only 'deleted'
    n = d.add(BASE + 1, title="n")
    d.update(n.id, {"title": "n2", "kind": "range", "end_us": BASE + 9})
    assert d.new[n.id].title == "n2" and d.new[n.id].kind == "range" and d.count() == 1
    assert d.delete(n.id) and d.count() == 0
    d.update(s1.id, {"title": "zmiana"})
    assert d.delete(s1.id) and d.state(s1.id) == "deleted" and not d.edited and d.changes()[0].marker.title == "a"
    assert not d.delete(s1.id) and not d.delete(9999)
    d.revert(s1.id)                                                      # 'Cofnij zmianę' brings it back as saved
    assert d.count() == 0 and d.get(s1.id).title == "a"
    with pytest.raises(KeyError):
        d.update(9999, {"title": "x"})
    with pytest.raises(mk.MarkerError):
        d.update(s1.id, {"color": "zły"})
    assert d.count() == 0
    d.update(s1.id, {"show_label": 0})                                   # hiding the name is an edit like any other
    assert [c.fields for c in d.changes()] == [["nazwa na wykresie"]]
    d.discard()
    assert d.count() == 0 and store.get(s1.id).show_label == 1


def test_draft_groups_and_commit_failure_keeps_the_draft(store):
    a = store.add(BASE, author="jan", group_name="G1")
    d = md.MarkerDraft(store)
    n = d.add(BASE + 1, group_name="G2")
    d.update(a.id, {"group_name": "G2"})
    assert d.groups() == [("G2", 2)]
    assert d.search(group="G1") == [] and sorted(ids(d.search(group="G2"))) == sorted([a.id, n.id])
    d.new[n.id].color = "#zzzzzz"                                        # (made invalid behind the draft's back)
    with pytest.raises(mk.MarkerError):
        d.commit(by="jan")
    assert d.count() == 2 and store.get(a.id).group_name == "G1" and store.count() == 1
