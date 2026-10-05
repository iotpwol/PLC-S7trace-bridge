"""REC marks (Start REC / Stop REC lines, Manual REC areas, moving the start of a recording): core logic, databases."""
import dataclasses
import os
import threading
import time
from datetime import datetime

import numpy as np
import pytest

from s7trace.core import marker_look, rec_marks, rec_ops, store
from s7trace.core.rec_marks import RecMarks
from s7trace.core.store import DbRecorder, StoreConfig, StoreError
from s7trace.core.types import Signal
from test_store import INFLUX_CFGS, FakeInflux, pg  # noqa: F401  (fixtures)

START = datetime(2026, 10, 5, 12, 0, 0)
SIGS = [Signal(name="A", dtype="BOOL"), Signal(name="B", dtype="REAL")]


def data():
    """20 s at 10 Hz: A toggles every 3 s, B ramps (changes at every sample)."""
    t = np.round(np.arange(0, 20, 0.1), 3)
    v = np.column_stack([((t // 3) % 2).astype(float), t * 2.0])
    return t, v


def us(t):
    return store.to_us(START, t)


# ------------------------------------------------------------------------------ marks
def test_marker_look_has_the_rec_settings():
    d = marker_look.normalize({})
    assert d["rec_show"] == 1 and d["rec_color"] == "#ff8c1a" and d["rec_width"] == 2 and d["rec_style"] == "solid" and d["rec_opacity"] == 24
    n = marker_look.normalize({"rec_show": 0, "rec_color": "#00FF00", "rec_width": 99, "rec_style": "dash", "rec_opacity": -5})
    assert n["rec_show"] == 0 and n["rec_color"] == "#00ff00" and n["rec_width"] == 12 and n["rec_style"] == "dash" and n["rec_opacity"] == 0
    bad = marker_look.normalize({"rec_color": "red", "rec_style": "wavy"})
    assert bad["rec_color"] == "#ff8c1a" and bad["rec_style"] == "solid"


def test_pseudo_ids_never_look_like_markers():
    assert rec_marks.parse(5) is None and rec_marks.parse(-7) is None             # saved / draft markers
    for kind in (rec_marks.AUTO_START, rec_marks.AUTO_STOP, rec_marks.MANUAL):
        assert rec_marks.parse(rec_marks.pid(kind, 12)) == (kind, 12)


def test_auto_marks_are_numbered_and_follow_the_look():
    rm = RecMarks()
    assert rm.started(5.0, "s1") == 1
    rm.stopped(9.0)
    assert rm.started(12.0, "s2") == 2
    look = marker_look.normalize({})
    items = rm.items(look)
    titles = [it["title"] for it in items]
    assert titles == ["Start REC (1)", "Stop REC (1)", "Start REC (2)"]               # the second recording is still running
    assert all(it["color"] == "#ff8c1a" and it["width"] == 2 and it["kind"] == "point" for it in items)
    assert "czas nagrywania 4.0 s" in items[1]["tip"] and "nagrywanie trwa" in items[2]["tip"]
    assert rm.items({**look, "rec_show": 0}) == []                                    # switched off in the configuration
    rm.reset()
    assert rm.items(look) == [] and rm.started(1.0) == 1                              # a new run numbers from 1 again


def test_reopened_recorder_keeps_the_same_numbers():
    rm = RecMarks()
    rm.started(1.0, "a")
    rm.hold = True                                    # new signals were added: the recorder is closed and opened again
    rm.stopped(5.0)
    assert rm.started(5.0, "b") == 1
    rm.hold = False
    assert len(rm.auto) == 1 and rm.auto[0]["t1"] is None and rm.auto[0]["sid"] == "b"


def test_manual_areas():
    rm = RecMarks()
    assert rm.place_manual(8.0) == (1, "start")
    assert [it["title"] for it in rm.items({})] == ["Manual Start REC (1)"]           # just the line until the stop is put
    assert rm.unsaved() == []
    assert rm.place_manual(3.0) == (1, "stop")                                       # the ends are put in time order
    m = rm.manual_get(1)
    assert (m["a"], m["b"]) == (3.0, 8.0) and rm.unsaved() == [m]
    it = rm.items(marker_look.normalize({}))[0]
    assert it["kind"] == "range" and (it["x0"], it["x1"]) == (3.0, 8.0) and it["title2"] == "Manual Stop REC (1)" and it["opacity"] == 24
    assert rm.place_manual(10.0) == (2, "start")
    with pytest.raises(ValueError):
        rm.place_manual(10.0)
    rm.mark_saved(1, "plik.csv")
    assert rm.unsaved() == [] and "plik.csv" in rm.items({})[0]["tip"]
    rm.move_manual(1, 2.0, 9.0)
    assert rm.unsaved() == [rm.manual_get(1)]                                         # moved: has to be saved again
    rm.remove_manual(1)
    assert rm.manual_get(1) is None and rm.next_manual_n() == 3


# ------------------------------------------------------------------------------ rows / manual recording
def test_rows_for_range_start_with_the_full_state():
    t, v = data()
    rows, end_us, first = rec_ops.rows_for_range(START, t, v, 5.05, 8.0, "changes", 2)
    assert first == 5.05 and rows[0][0] == us(5.05) and rows[0][2] is True and set(rows[0][1]) == {0, 1}
    assert rows[0][1][0] == 1.0 and rows[0][1][1] == pytest.approx(10.0)             # the state of the sample at 5.0
    assert rows[-1][0] <= us(8.0) and end_us <= us(8.0) + 1
    assert all(1 in r[1] for r in rows[1:])                                          # B changes at every sample
    assert any(set(r[1]) == {0, 1} for r in rows[1:])                                # A toggles at 6.0
    only_b = [r for r in rows[1:] if set(r[1]) == {1}]
    assert len(only_b) > 20
    rows_all, *_ = rec_ops.rows_for_range(START, t, v, 5.0, 6.0, "all", 2)
    assert all(set(r[1]) == {0, 1} for r in rows_all) and len(rows_all) == 11


def _read(cfg, sid, base=""):
    b = store.open_backend(cfg, base)
    try:
        meta, tt, m = b.read(sid)
        return b.sessions(), meta, tt, m
    finally:
        b.close()


def test_manual_rec_is_saved_as_a_recording_of_its_own(tmp_path):
    t, v = data()
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "rec.db"), mode="changes")
    where, sid = rec_ops.save_range_recording(cfg, SIGS, START, t, v, 5.0, 10.0, {"title": "Manual REC (1)", "ip": "10.0.0.1"}, str(tmp_path))
    assert sid and "nagranie" in where
    sessions, meta, tt, m = _read(cfg, sid, str(tmp_path))
    assert meta["title"] == "Manual REC (1)" and meta["start_us"] == us(5.0) and meta["end_us"] <= us(10.0)
    assert tt[0] == us(5.0) and tt[-1] <= us(10.0) and len(sessions) == 1
    k = np.searchsorted(t, 7.0)
    j = np.searchsorted(tt, us(7.0))
    assert m[j, 1] == pytest.approx(v[k, 1]) and m[j, 0] == v[k, 0]
    csv_path = str(tmp_path / "manual.csv")
    where, sid = rec_ops.save_range_recording(cfg, SIGS, START, t, v, 2.0, 4.0, {}, str(tmp_path), csv_path=csv_path)
    assert where == csv_path and sid == ""
    from s7trace.core.csvio import read_csv
    _sigs, ct, cv = read_csv(csv_path)
    assert ct[0] == pytest.approx(2.0) and ct[-1] <= 4.0 + 1e-9 and cv.shape[1] == 2


# ------------------------------------------------------------------------------ moving the start
def live_recording(cfg, base, t0=10.0, upto=20.0, mode=None):
    """A recording that began at t0 (REC pressed there) and ran to `upto`; returns (session id, backend meta)."""
    t, v = data()
    rec = DbRecorder(cfg, SIGS, START, {"title": "Nagranie"}, base_dir=base, t0=t0)
    for i, tt in enumerate(t):
        if t0 <= tt < upto:
            rec.write(float(tt), [float(x) for x in v[i]])
    rec.close()
    return rec.session


def test_move_start_earlier_fills_in_the_missing_part(tmp_path):
    t, v = data()
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "rec.db"), mode="changes", keyframe_min=0)
    sid = live_recording(cfg, str(tmp_path), t0=10.0)
    b = store.open_backend(cfg, str(tmp_path))
    meta = next(s for s in b.sessions() if s["id"] == sid)
    assert meta["start_us"] == us(10.0)
    rows, _end, first = rec_ops.rows_for_range(START, t, v, 4.0, 10.0, "changes", 2)
    rec_ops.move_start(b, meta, us(4.0), rows)
    meta2, tt, m = b.read(sid)
    b.close()
    assert meta2["start_us"] == us(4.0) and tt[0] == us(4.0)
    j = np.searchsorted(tt, us(6.0))
    k = np.searchsorted(t, 6.0)
    assert m[j, 1] == pytest.approx(v[k, 1]) and m[j, 0] == v[k, 0]                  # the part that was not recorded before is there now
    assert tt[-1] >= us(19.0)                                                         # the live part is untouched


def test_move_start_later_deletes_what_came_before(tmp_path):
    t, v = data()
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "rec.db"), mode="changes", keyframe_min=0)
    sid = live_recording(cfg, str(tmp_path), t0=5.0)
    b = store.open_backend(cfg, str(tmp_path))
    meta = next(s for s in b.sessions() if s["id"] == sid)
    rows, *_ = rec_ops.rows_for_range(START, t, v, 12.0, 12.0, "changes", 2)          # the full state at the new start
    rec_ops.move_start(b, meta, us(12.0), rows)
    meta2, tt, m = b.read(sid)
    b.close()
    assert meta2["start_us"] == us(12.0) and tt[0] == us(12.0) and tt[-1] >= us(19.0)
    k = np.searchsorted(t, 12.0)
    assert m[0, 0] == v[k, 0] and m[0, 1] == pytest.approx(v[k, 1])                   # the state at the new start was kept


def test_running_recorder_runs_the_move_in_its_writer_thread(tmp_path):
    t, v = data()
    cfg = StoreConfig(kind="sqlite", sqlite_path=str(tmp_path / "rec.db"), mode="changes", keyframe_min=0)
    rec = DbRecorder(cfg, SIGS, START, {}, base_dir=str(tmp_path), t0=10.0)
    for i, tt in enumerate(t):
        if 10.0 <= tt < 15.0:
            rec.write(float(tt), [float(x) for x in v[i]])
    done = threading.Event()
    result = []
    rows, *_ = rec_ops.rows_for_range(START, t, v, 6.0, 10.0, "changes", 2)

    def job(be):
        meta = next(s for s in be.sessions() if s["id"] == rec.session)
        rec_ops.move_start(be, meta, us(6.0), rows)

    rec.submit(job, lambda err: (result.append(err), done.set()))
    for i, tt in enumerate(t):                                                       # the recording goes on meanwhile
        if 15.0 <= tt < 18.0:
            rec.write(float(tt), [float(x) for x in v[i]])
    assert done.wait(5.0) and result == [""]
    rec.close()
    b = store.open_backend(cfg, str(tmp_path))
    meta, tt, m = b.read(rec.session)
    b.close()
    assert meta["start_us"] == us(6.0) and tt[0] == us(6.0) and tt[-1] >= us(17.5)


@pytest.mark.parametrize("ver", [1, 2])
def test_move_start_in_influx(ver):
    fake = FakeInflux()
    try:
        t, v = data()
        cfg = StoreConfig(url=fake.url, measurement="rec", mode="changes", keyframe_min=0, **INFLUX_CFGS[ver])
        sid = live_recording(cfg, "", t0=10.0)
        b = store.open_backend(cfg)
        meta = next(s for s in b.sessions() if s["id"] == sid)
        rows, *_ = rec_ops.rows_for_range(START, t, v, 7.0, 10.0, "changes", 2)
        rec_ops.move_start(b, meta, us(7.0), rows)
        sess = b.sessions()
        assert len(sess) == 1 and sess[0]["start_us"] == us(7.0)                        # still ONE session point, with the new start
        meta2, tt, m = b.read(sid)
        assert tt[0] == us(7.0) and tt[-1] >= us(19.0)
        rows2, *_ = rec_ops.rows_for_range(START, t, v, 14.0, 14.0, "changes", 2)
        meta3 = next(s for s in b.sessions() if s["id"] == sid)
        rec_ops.move_start(b, meta3, us(14.0), rows2)
        meta4, tt, m = b.read(sid)
        assert meta4["start_us"] == us(14.0) and tt[0] == us(14.0) and len(b.sessions()) == 1
        b.update_session(sid, {"title": "po zmianach"})                                  # later edits still hit the same point
        assert len(b.sessions()) == 1 and b.sessions()[0]["title"] == "po zmianach" and b.sessions()[0]["start_us"] == us(14.0)
    finally:
        fake.close()


def test_move_start_in_timescale(pg):
    cfg = StoreConfig(kind="timescale", host="db", pg_database="plant", table="rec_samples")
    b = store.open_backend(cfg)
    meta = {"id": "S1", "start_us": us(10.0), "signals": [s.to_dict() for s in SIGS]}
    rows, *_ = rec_ops.rows_for_range(START, *data(), 12.0, 12.0, "changes", 2)
    rec_ops.move_start(b, meta, us(12.0), rows)
    sql = [(s, p) for s, p in pg["conn"].log]
    ins = next(p for s, p in sql if s.startswith("INSERT INTO rec_samples("))
    assert ins[0][1] == "S1" and ins[0][0] == store.us_to_rfc3339(us(12.0))
    dele = next(p for s, p in sql if s.startswith("DELETE FROM rec_samples WHERE session=%s AND time <"))
    assert dele[0] == "S1" and dele[1] == store.us_to_rfc3339(us(12.0))
    up = next(p for s, p in sql if s.startswith("UPDATE rec_samples_sessions SET start_us=%s"))
    assert up == (us(12.0), "S1")
    assert [s for s, _p in sql].index(next(s for s, _p in sql if s.startswith("DELETE FROM rec_samples WHERE"))) > \
        [s for s, _p in sql].index(next(s for s, _p in sql if s.startswith("INSERT INTO rec_samples(")))      # the state is written first
