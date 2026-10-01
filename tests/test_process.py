import time

import pytest

from s7trace.core import planner
from s7trace.core.acq_process import ProcAcquirer
from s7trace.core.buffer import TraceBuffer
from s7trace.core.types import Signal


@pytest.fixture(scope="module")
def sim():
    from s7trace.sim import Simulator
    s = Simulator(11105)
    s.start()
    time.sleep(0.5)
    yield s
    s.stop()


def test_process_acquirer(sim):
    sim.db1[100] = 0b00000011
    sigs = [Signal(name="b0", dtype="BOOL", db=1, byte=100, bit=0),
            Signal(name="b1", dtype="BOOL", db=1, byte=100, bit=1)]
    buf = TraceBuffer(2)
    states = []
    a = ProcAcquirer("127.0.0.1:11105", 0, 2, 25, sigs, planner.MODE_BLOCKS, buf,
                     on_state=lambda s, m: states.append(s))
    a.start()
    time.sleep(2.5)
    a.stop()
    a.join(8)
    assert states[:2] == ["connecting", "running"] and states[-1] == "stopped"
    assert len(buf) > 20 and a.t0 > 0
    t, v = buf.snapshot()
    assert list(v[-1]) == [1.0, 1.0]
    assert a.stats.samples >= len(buf) - 5 and a.stats.avg_lag > 0
    assert not a._proc.is_alive()


def test_process_acquirer_connect_error():
    states = []
    a = ProcAcquirer("127.0.0.1:11998", 0, 2, 25, [Signal()], planner.MODE_BLOCKS, TraceBuffer(1),
                     on_state=lambda s, m: states.append(s))
    a.start()
    a.join(15)
    assert states[-1] == "error"
