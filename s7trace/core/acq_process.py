"""Runs the Acquirer in a separate process so GUI work (GIL) can never delay PLC reads.

Parent-side API mirrors Acquirer: start(), stop(), join(), stats, t0, plus the same
on_state / on_sample callbacks (invoked from a reader thread in the parent).
"""
from __future__ import annotations

import multiprocessing as mp
import threading
import time
from typing import Callable

from .acquisition import Acquirer
from .buffer import TraceBuffer
from .types import Signal

FLUSH_S = 0.02      # child sends sample batches at most every 20 ms


class RemoteStats:
    def __init__(self):
        self.avg_lag = 0.0
        self.last_lag = 0.0
        self.n = 0
        self.samples = 0
        self.missed = 0
        self.gui_lag_ms = 0.0

    @property
    def missed_pct(self) -> float:
        tot = self.samples + self.missed
        return 100.0 * self.missed / tot if tot else 0.0


def _child_main(params: dict, conn) -> None:
    batch: list = []
    last = [time.perf_counter()]
    acq_ref: list[Acquirer] = []

    def flush(force=False):
        now = time.perf_counter()
        if batch and (force or now - last[0] >= FLUSH_S):
            st = acq_ref[0].stats
            conn.send(("batch", batch[:], (st.avg_lag, st.last_lag, st.n, st.samples, st.missed)))
            batch.clear()
            last[0] = now

    def on_state(state, msg):
        flush(True)
        conn.send(("state", state, msg, acq_ref[0].t0 if acq_ref else 0.0))

    def on_sample(t, vals):
        batch.append((t, vals))
        flush()

    acq = Acquirer(params["host"], params["rack"], params["slot"], params["cycle_ms"],
                   [Signal.from_dict(d) for d in params["signals"]], params["mode"], None,
                   on_state=on_state, on_sample=on_sample)
    acq_ref.append(acq)
    acq.start()
    # main thread of the child: wait for a stop command (or parent death)
    while acq.is_alive():
        try:
            if conn.poll(0.05):
                msg = conn.recv()
                if msg and msg[0] == "stop":
                    acq.stop()
        except (EOFError, OSError):
            acq.stop()
            break
    acq.join(5)
    flush(True)
    try:
        conn.close()
    except OSError:
        pass


class ProcAcquirer:
    def __init__(self, host: str, rack: int, slot: int, cycle_ms: float,
                 signals: list[Signal], mode: str, buffer: TraceBuffer,
                 on_state: Callable[[str, str], None] | None = None,
                 on_sample: Callable[[float, list[float]], None] | None = None):
        self.buffer = buffer
        self.on_state = on_state or (lambda *_: None)
        self.on_sample = on_sample
        self.stats = RemoteStats()
        self.t0 = 0.0
        self._params = dict(host=host, rack=rack, slot=slot, cycle_ms=cycle_ms,
                            signals=[s.to_dict() for s in signals], mode=mode)
        ctx = mp.get_context("spawn")
        self._conn, child = ctx.Pipe(duplex=True)
        self._proc = ctx.Process(target=_child_main, args=(self._params, child), daemon=True)
        self._child_conn = child
        self._reader = threading.Thread(target=self._read_loop, daemon=True, name="S7AcqReader")
        self._final = False

    def start(self) -> None:
        self._proc.start()
        self._child_conn.close()
        self._reader.start()

    def stop(self) -> None:
        try:
            self._conn.send(("stop",))
        except (OSError, ValueError):
            pass

    def is_alive(self) -> bool:
        return self._reader.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self._reader.join(timeout)
        self._proc.join(0.5 if timeout is None else max(timeout / 4, 0.2))
        if self._proc.is_alive():
            self._proc.terminate()

    def _read_loop(self) -> None:
        try:
            while True:
                msg = self._conn.recv()
                if msg[0] == "batch":
                    _, rows, st = msg
                    s = self.stats
                    s.avg_lag, s.last_lag, s.n, s.samples, s.missed = st
                    for t, vals in rows:
                        self.buffer.append(t, vals)
                        if self.on_sample:
                            self.on_sample(t, vals)
                else:
                    _, state, text, t0 = msg
                    if t0:
                        self.t0 = t0
                    self.on_state(state, text)
                    if state in ("stopped", "error"):
                        self._final = True
                        break
        except (EOFError, OSError):
            if not self._final:
                self.on_state("error", "Proces akwizycji zakończył się nieoczekiwanie.")
