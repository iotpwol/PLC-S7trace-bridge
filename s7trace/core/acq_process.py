"""Runs the Acquirer in a separate process so GUI work (GIL) can never delay PLC reads.

Parent-side API mirrors Acquirer: start(), stop(), join(), stats, t0, plus the same
on_state / on_sample callbacks (invoked from a reader thread in the parent).
"""
from __future__ import annotations

import multiprocessing as mp
import threading
import time
from typing import Callable

from .acquisition import Acquirer, DriverAcquirer
from .drivers import create_driver
from .buffer import TraceBuffer
from .diagnostics import LinkDiag, plan_cost
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
        self.errors = 0
        self.reconnects = 0
        self.last_error = ""
        self.connect_ms = 0.0

    def apply(self, d: dict) -> None:
        for k, v in d.items():
            setattr(self, k, v)

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
            conn.send(("batch", batch[:], dict(
                avg_lag=st.avg_lag, last_lag=st.last_lag, n=st.n, samples=st.samples, missed=st.missed,
                errors=st.errors, reconnects=st.reconnects, last_error=st.last_error, connect_ms=st.connect_ms)))
            batch.clear()
            last[0] = now

    def on_state(state, msg):
        flush(True)
        conn.send(("state", state, msg, acq_ref[0].t0 if acq_ref else 0.0))

    def on_sample(t, vals):
        gap = bool(vals) and all(v != v for v in vals)            # NaN row = connection-loss marker
        batch.append((t, vals, None if gap else acq_ref[0].stats.last_lag))
        flush()

    def on_info(d):
        try:
            conn.send(("info", d))
        except (OSError, ValueError):
            pass

    drv = params.get("driver") or {}
    sigs = [Signal.from_dict(d) for d in params["signals"]]
    if drv.get("type") and drv["type"] != "s7":
        acq = DriverAcquirer(params["host"], params["rack"], params["slot"], params["cycle_ms"], sigs,
                             params["mode"], None, on_state=on_state, on_sample=on_sample,
                             client_factory=lambda: create_driver(drv["type"], drv.get("opts", {})), on_info=on_info)
    else:
        acq = Acquirer(params["host"], params["rack"], params["slot"], params["cycle_ms"], sigs,
                       params["mode"], None, on_state=on_state, on_sample=on_sample, on_info=on_info)
    acq_ref.append(acq)
    acq.start()
    # main thread of the child: wait for a stop command (or parent death)
    while acq.is_alive():
        try:
            if conn.poll(0.05):
                msg = conn.recv()
                if msg and msg[0] == "stop":
                    acq.stop()
                elif msg and msg[0] == "signals":
                    acq.update_signals([Signal.from_dict(d) for d in msg[1]])
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
                 on_sample: Callable[[float, list[float]], None] | None = None,
                 driver: dict | None = None,
                 on_info: Callable[[dict], None] | None = None,
                 anchor_ts: float | None = None):
        """anchor_ts = wall-clock time (epoch seconds) of the chart time 0 when this run CONTINUES a chart that already holds data:
        the times of the new samples are shifted so that the chart keeps its time axis, and one NaN row is put into the gap
        (a break in the curves). None = a new chart: the times are seconds since this run's start."""
        self.buffer = buffer
        self.anchor_ts = anchor_ts
        self.time_offset = 0.0            # seconds added to the times of the samples (set when the child reports its start)
        self.gap_marked = False
        self.gap: tuple[float, float] | None = None   # (chart time of the last sample before the pause, of the first one after it); read once by the owner
        self.on_info = on_info
        self.on_state = on_state or (lambda *_: None)
        self.on_sample = on_sample
        self.stats = RemoteStats()
        self.mode = mode
        self.diag = LinkDiag(cycle_ms, *plan_cost(signals, mode), stats=self.stats)
        self.t0 = 0.0
        self._params = dict(host=host, rack=rack, slot=slot, cycle_ms=cycle_ms,
                            signals=[s.to_dict() for s in signals], mode=mode, driver=driver)
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

    def update_signals(self, signals: list[Signal]) -> None:
        """Hand a longer signal list (old ones first, new ones appended) to the running child process."""
        self.diag.set_plan(*plan_cost(signals, self.mode))
        try:
            self._conn.send(("signals", [s.to_dict() for s in signals]))
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
                    self.stats.apply(st)
                    off = self.time_offset
                    for row in rows:
                        t, vals = row[0], row[1]
                        self.diag.add_sample(t, row[2] if len(row) > 2 else None)
                        t += off
                        self.buffer.append(t, vals)
                        if self.on_sample:
                            self.on_sample(t, vals)
                elif msg[0] == "info":
                    if self.on_info:
                        self.on_info(msg[1])
                else:
                    _, state, text, t0 = msg
                    if t0:
                        self.t0 = t0
                        if self.anchor_ts is not None and not self.gap_marked:         # continuing a chart: keep its time axis
                            self.time_offset = time.time() - self.anchor_ts - (time.perf_counter() - t0)
                            if len(self.buffer):
                                last, nan = self.buffer.last_time(), [float("nan")] * self.buffer.n
                                if self.time_offset - last > 0.002:        # the pause: the old values must not be held across it
                                    self.buffer.append(last + 0.001, nan)
                                self.buffer.append(self.time_offset, nan)  # ... and the break ends where the new run begins
                                self.gap = (last, self.time_offset)          # (Stop, Start) on the chart: the owner draws the two marks
                            self.gap_marked = True
                    self.diag.note_state(state)
                    self.on_state(state, text)
                    if state in ("stopped", "error"):
                        self._final = True
                        break
        except (EOFError, OSError):
            if not self._final:
                self.on_state("error", "Proces akwizycji zakończył się nieoczekiwanie.")
