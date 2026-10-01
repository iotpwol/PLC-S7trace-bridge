import math
import time

import numpy as np
import pytest

from s7trace.core import planner, symbols
from s7trace.core.acquisition import Acquirer
from s7trace.core.buffer import TraceBuffer
from s7trace.core.csvio import read_csv, write_csv
from s7trace.core.trigger import TriggerConfig, TriggerEngine
from s7trace.core.types import Signal


def test_addresses():
    assert Signal(source="DB", dtype="BOOL", db=1, byte=160, bit=2).address == "DB1.DBX160.2"
    assert Signal(source="M", dtype="INT", byte=10).address == "MW10"
    assert Signal(source="I", dtype="BOOL", byte=0, bit=3).address == "I0.3"
    assert Signal(source="DB", dtype="REAL", db=5, byte=8).address == "DB5.DBD8"


def test_decode():
    raw = bytes([0b00000100, 0xFF, 0xFE, 0x42, 0x28, 0x00, 0x00])
    assert Signal(dtype="BOOL", bit=2).decode(raw, 0) == 1.0
    assert Signal(dtype="BOOL", bit=1).decode(raw, 0) == 0.0
    assert Signal(dtype="INT").decode(raw, 1) == -2
    assert Signal(dtype="REAL").decode(raw, 3) == pytest.approx(42.0)


def test_plan_blocks_merge_and_split():
    sigs = [Signal(dtype="BOOL", byte=160, bit=i) for i in range(5)] + [
        Signal(dtype="INT", byte=170), Signal(dtype="BOOL", db=2, byte=0),
        Signal(source="M", dtype="BYTE", byte=0)]
    plan = planner.build_plan(sigs, planner.MODE_BLOCKS)
    keys = {(b.source, b.db) for b in plan}
    assert keys == {("DB", 1), ("DB", 2), ("M", 0)}
    db1 = next(b for b in plan if b.source == "DB" and b.db == 1)
    assert db1.start == 160 and db1.size == 12
    assert len(planner.build_plan(sigs, planner.MODE_SINGLE)) == len(sigs)
    far = [Signal(byte=0), Signal(byte=100)]
    assert len(planner.build_plan(far, planner.MODE_BLOCKS)) == 2


def test_buffer_grow_and_snapshot():
    b = TraceBuffer(2, max_samples=100000)
    for i in range(10000):
        b.append(i * 0.1, [i, -i])
    t, v = b.snapshot(10.0, 20.0)
    assert t[0] <= 10.0 and t[-1] >= 20.0
    assert v.shape[1] == 2
    assert len(b) == 10000


def test_buffer_trim():
    b = TraceBuffer(1, max_samples=4096)
    for i in range(5000):
        b.append(float(i), [i])
    assert len(b) < 5000 and b.dropped > 0
    assert b.last_time() == 4999.0


def feed(cfg, seq):
    eng = TriggerEngine(cfg)
    return [i for i, v in enumerate(seq) if eng.feed(v)]


def test_trigger_modes():
    seq = [0, 0, 1, 1, 0, 0, 1, 0]
    assert feed(TriggerConfig(mode="rising edge", a=0.5), seq) == [2, 6]
    assert feed(TriggerConfig(mode="falling edge", a=0.5), seq) == [4, 7]
    assert feed(TriggerConfig(mode="==", a=1), seq) == [2, 6]
    assert feed(TriggerConfig(mode=">", a=0.5), seq) == [2, 6]
    assert feed(TriggerConfig(mode="<", a=0.5), [1, 1, 0, 0, 1, 0]) == [2, 5]
    assert feed(TriggerConfig(mode="between", a=2, b=4), [0, 3, 3, 5, 3]) == [1, 4]


def test_trigger_hysteresis_and_initial_state():
    # noisy around threshold: hysteresis 1 suppresses re-triggers
    seq = [0, 5.1, 4.9, 5.1, 4.9, 5.1, 3.0, 5.1]
    assert feed(TriggerConfig(mode=">", a=5, hysteresis=1), seq) == [1, 7]
    # condition already true at start -> no immediate fire
    assert feed(TriggerConfig(mode="==", a=1), [1, 1, 0, 1]) == [3]


def test_csv_roundtrip(tmp_path):
    sigs = [Signal(name="A", color="#ff0000", offset_y=0), Signal(name="B", offset_y=-1.1, gain=2.0)]
    t = np.array([0.0, 0.025, 0.05])
    v = np.array([[0, 1.5], [1, np.nan], [0, 3.0]])
    p = str(tmp_path / "x.csv")
    write_csv(p, sigs, t, v)
    s2, t2, v2 = read_csv(p)
    assert [s.name for s in s2] == ["A", "B"]
    assert s2[1].gain == 2.0 and s2[0].color == "#ff0000"
    assert np.allclose(t2, t) and np.isnan(v2[1, 1]) and v2[2, 1] == 3.0


def test_csv_import_plain(tmp_path):
    p = tmp_path / "plain.csv"
    p.write_text("time;X;Y\n0;1;2\n1;3;4\n", encoding="utf-8")
    s, t, v = read_csv(str(p))
    assert [x.name for x in s] == ["X", "Y"] and v[1, 1] == 4


# ---- symbols
def test_parse_address():
    assert symbols.parse_address("%I0.3") == ("I", "BOOL", 0, 0, 3)
    assert symbols.parse_address("%MW10") == ("M", "WORD", 0, 10, 0)
    assert symbols.parse_address("%QD4", "Real")[1] == "REAL"
    assert symbols.parse_address("E 1.2") == ("I", "BOOL", 0, 1, 2)
    assert symbols.parse_address("DB1.DBX160.0") == ("DB", "BOOL", 1, 160, 0)
    assert symbols.parse_address("garbage") is None


def test_db_source_layout(tmp_path):
    src = '''DATA_BLOCK "Data"
{ S7_Optimized_Access := 'FALSE' }
VERSION : 0.1
   STRUCT
      b0 : Bool;
      b1 : Bool;
      by : Byte;
      w : Int;
      r : Real;
      st : Struct
         x : Bool;
         y : Word;
      END_STRUCT;
      arr : Array[0..2] of Int;
   END_STRUCT;
BEGIN
END_DATA_BLOCK
'''
    p = tmp_path / "d.db"
    p.write_text(src)
    got = {s.name: (s.byte, s.bit, s.dtype) for s in symbols.import_db_source(str(p), 7)}
    assert got["Data.b0"] == (0, 0, "BOOL")
    assert got["Data.b1"] == (0, 1, "BOOL")
    assert got["Data.by"] == (1, 0, "BYTE")
    assert got["Data.w"] == (2, 0, "INT")
    assert got["Data.r"] == (4, 0, "REAL")
    assert got["Data.st.x"] == (8, 0, "BOOL")
    assert got["Data.st.y"] == (10, 0, "WORD")
    assert got["Data.arr[2]"] == (16, 0, "INT")


def test_db_optimized_rejected(tmp_path):
    p = tmp_path / "o.db"
    p.write_text("DATA_BLOCK \"X\"\n{ S7_Optimized_Access := 'TRUE' }\nSTRUCT\n a : Int;\nEND_STRUCT;\nBEGIN\nEND_DATA_BLOCK")
    with pytest.raises(ValueError):
        symbols.import_db_source(str(p), 1)


def test_tag_table_csv(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("Name,Path,Data Type,Logical Address,Comment\nMotor,Default,Bool,%I0.1,run\nSpeed,Default,Int,%MW20,\n")
    got = symbols.import_tag_table(str(p))
    assert (got[0].name, got[0].source, got[0].byte, got[0].bit) == ("Motor", "I", 0, 1)
    assert (got[1].dtype, got[1].byte) == ("INT", 20)


def test_step7_sdf(tmp_path):
    p = tmp_path / "s.sdf"
    p.write_text('"Motor","E 0.1","BOOL","c"\n"Cnt","MW 20","INT",""\n')
    got = symbols.import_step7(str(p))
    assert got[0].source == "I" and got[1].dtype == "INT"


# ---- end-to-end against the snap7 server
@pytest.fixture(scope="module")
def sim():
    from s7trace.sim import Simulator
    s = Simulator(11102)
    s.start()
    time.sleep(0.5)
    yield s
    s.stop()


@pytest.mark.parametrize("mode", planner.MODES)
def test_acquire_from_simulator(sim, mode):
    sim.db1[100] = 0b00000101
    sim.db1[110:112] = (1234).to_bytes(2, "big")
    sigs = [Signal(name="b0", dtype="BOOL", db=1, byte=100, bit=0),
            Signal(name="b1", dtype="BOOL", db=1, byte=100, bit=1),
            Signal(name="b2", dtype="BOOL", db=1, byte=100, bit=2),
            Signal(name="i", dtype="INT", db=1, byte=110),
            Signal(name="m", source="M", dtype="BYTE", byte=5)]
    sim.mk[5] = 77
    buf = TraceBuffer(len(sigs))
    states = []
    a = Acquirer("127.0.0.1:11102", 0, 2, 25, sigs, mode, buf, on_state=lambda s, m: states.append(s))
    a.start()
    time.sleep(1.0)
    a.stop()
    a.join(3)
    assert "running" in states and states[-1] == "stopped"
    assert len(buf) > 10
    t, v = buf.snapshot()
    assert list(v[-1]) == [1.0, 0.0, 1.0, 1234.0, 77.0]
    assert a.stats.samples == len(buf)
    assert a.stats.avg_lag > 0


def test_connect_failure():
    buf = TraceBuffer(1)
    states = []
    a = Acquirer("127.0.0.1:11999", 0, 2, 25, [Signal()], planner.MODE_BLOCKS, buf,
                 on_state=lambda s, m: states.append(s))
    a.start()
    a.join(10)
    assert states[-1] == "error"


# ---- render helpers
def test_render_step_and_compress():
    from s7trace.core import render
    t = np.arange(10, dtype=float)
    y = np.array([0, 0, 0, 1, 1, 1, 1, 0, 0, 0], dtype=float)
    t2, y2 = render.compress_runs(t, y)
    assert list(t2) == [0, 2, 3, 6, 7, 9]
    xs, ys = render.make_step(t2, y2)
    assert xs[0] == 0 and xs[-1] == 9 and ys[-1] == 0
    # steps are vertical: at x=3 value goes 0 -> 1
    i = list(xs).index(3.0)
    assert ys[i] == 0 and ys[i + 1] == 1
    xs, ys = render.make_step(t2, y2, x_end=12)
    assert xs[-1] == 12 and ys[-1] == 0


def test_peak_decimate_keeps_extremes():
    from s7trace.core import render
    t = np.arange(100000, dtype=float)
    y = np.zeros(100000)
    y[54321] = 9.0
    t2, y2 = render.peak_decimate(t, y, 500)
    assert len(t2) <= 1100 and y2.max() == 9.0


def test_peak_decimate_nan_gap_and_speed():
    import time as _t
    from s7trace.core import render
    t = np.arange(50000, dtype=float)
    y = np.sin(t / 100)
    y[20000:20010] = np.nan
    t0 = _t.perf_counter()
    t2, y2 = render.peak_decimate(t, y, 1000)
    assert _t.perf_counter() - t0 < 0.05
    assert np.isnan(y2).any() and np.all(np.diff(t2) > 0)
