"""Background acquisition thread: cyclic PLC reads -> TraceBuffer."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from .buffer import TraceBuffer
from .planner import MODE_BLOCKS, MODE_MULTI, MAX_MULTI, ReadBlock, build_plan, decode_blocks
from .types import Signal

try:  # snap7 is imported lazily-safe so the rest of the package works without it
    import snap7
    from snap7.type import Area
    _AREA = {"I": Area.PE, "Q": Area.PA, "M": Area.MK, "DB": Area.DB}
except Exception:  # pragma: no cover
    snap7 = None
    _AREA = {}


def parse_host(text: str) -> tuple[str, int]:
    """'10.0.0.1' or '10.0.0.1:1102' -> (host, port)."""
    text = text.strip()
    if text.count(":") == 1:
        host, port = text.split(":")
        return host.strip(), int(port)
    return text, 102


class Stats:
    def __init__(self):
        self.lag_window = deque(maxlen=50)
        self.last_lag = 0.0
        self.samples = 0
        self.missed = 0
        self.gui_lag_ms = 0.0

    @property
    def n(self) -> int:
        return len(self.lag_window)

    @property
    def avg_lag(self) -> float:
        return sum(self.lag_window) / len(self.lag_window) if self.lag_window else 0.0

    @property
    def missed_pct(self) -> float:
        tot = self.samples + self.missed
        return 100.0 * self.missed / tot if tot else 0.0


class Acquirer(threading.Thread):
    """Reads `signals` every `cycle_ms` and appends (t, values) to `buffer`.

    t is seconds since start() (monotonic). Reconnects automatically if the
    connection drops after the first successful connect; a NaN row marks the gap.
    `on_state(state, text)` is called from the worker thread with state in
    {"connecting","running","reconnecting","stopped","error"}.
    """

    def __init__(self, host: str, rack: int, slot: int, cycle_ms: float,
                 signals: list[Signal], mode: str, buffer: TraceBuffer | None,
                 on_state: Callable[[str, str], None] | None = None,
                 on_sample: Callable[[float, list[float]], None] | None = None,
                 client_factory: Callable[[], object] | None = None):
        super().__init__(daemon=True, name="S7Acquirer")
        self.host, self.port = parse_host(host)
        self.rack, self.slot = rack, slot
        self.cycle = max(cycle_ms, 1.0) / 1000.0
        self.signals = [Signal.from_dict(s.to_dict()) for s in signals]
        self.mode = mode
        self.buffer = buffer
        self.on_state = on_state or (lambda *_: None)
        self.on_sample = on_sample
        self.stats = Stats()
        self.t0 = 0.0
        self._stop_evt = threading.Event()
        self._factory = client_factory or (lambda: snap7.client.Client())
        self.plan: list[ReadBlock] = build_plan(self.signals, mode)
        self._new_signals: list[Signal] | None = None

    # ------------------------------------------------------------------ io
    def _connect(self):
        c = self._factory()
        c.connect(self.host, self.rack, self.slot, self.port)
        return c

    def _read_all(self, client) -> list[float]:
        if self.mode == MODE_MULTI and len(self.plan) > 1:
            data: list = []
            for i in range(0, len(self.plan), MAX_MULTI):
                chunk = self.plan[i: i + MAX_MULTI]
                items = [{"area": _AREA[b.source], "db_number": b.db,
                          "start": b.start, "size": b.size} for b in chunk]
                res, out = client.read_multi_vars(items)
                if res != 0:
                    raise RuntimeError(f"read_multi_vars error {res}")
                data.extend(out)
        else:
            data = [client.read_area(_AREA[b.source], b.db, b.start, b.size) for b in self.plan]
        return decode_blocks(self.signals, self.plan, data)

    def _emit(self, t: float, vals: list[float]) -> None:
        if self.buffer is not None:
            self.buffer.append(t, vals)
        if self.on_sample:
            self.on_sample(t, vals)

    def _sleep_until(self, target: float) -> bool:
        """Precise sleep (time.sleep is high-res on Windows, Event.wait is ~15 ms).
        Returns True if stop was requested."""
        while True:
            if self._stop_evt.is_set():
                return True
            rem = target - time.perf_counter()
            if rem <= 0:
                return False
            time.sleep(min(rem, 0.05))

    def update_signals(self, signals: list[Signal]) -> None:
        """Replace the signal list on the fly (signals may only be appended); applied before the next read."""
        self._new_signals = [Signal.from_dict(s.to_dict()) for s in signals]

    def _apply_new_signals(self) -> None:
        new, self._new_signals = self._new_signals, None
        if new:
            self.plan = build_plan(new, self.mode)
            self.signals = new

    # ------------------------------------------------------------ lifecycle
    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        self.on_state("connecting", f"Łączenie z {self.host}:{self.port}…")
        try:
            client = self._connect()
        except Exception as e:
            self.on_state("error", f"Nie można połączyć z {self.host}:{self.port} — {e}")
            return
        self.t0 = time.perf_counter()
        self.on_state("running", f"Połączono z {self.host} (rack={self.rack}, slot={self.slot}).")
        k = 0
        try:
            while not self._stop_evt.is_set():
                sched = self.t0 + k * self.cycle
                if self._sleep_until(sched):
                    break
                if self._new_signals is not None:
                    self._apply_new_signals()
                a = time.perf_counter()
                try:
                    vals = self._read_all(client)
                except Exception as e:
                    client = self._reconnect(client, e)
                    if client is None:
                        return
                    k = int((time.perf_counter() - self.t0) / self.cycle) + 1
                    continue
                b = time.perf_counter()
                lag = (b - a) * 1000.0
                self.stats.lag_window.append(lag)
                self.stats.last_lag = lag
                self.stats.samples += 1
                t = (a + b) / 2 - self.t0
                self._emit(t, vals)
                # ticks that elapsed while we were reading are counted as missed
                m = int((b - self.t0) / self.cycle)
                if m > k:
                    self.stats.missed += m - k
                    k = m + 1
                else:
                    k += 1
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
            self.on_state("stopped", "Rozłączono.")

    def _reconnect(self, client, err):
        """Mark gap with NaN, retry every 2 s until stop. Returns new client or None."""
        self._emit(time.perf_counter() - self.t0, [float("nan")] * len(self.signals))
        self.on_state("reconnecting", f"Utracono połączenie ({err}) — ponawiam…")
        try:
            client.disconnect()
        except Exception:
            pass
        while not self._stop_evt.is_set():
            if self._stop_evt.wait(2.0):
                break
            try:
                c = self._connect()
                self.on_state("running", f"Połączono z {self.host} (rack={self.rack}, slot={self.slot}).")
                return c
            except Exception as e:
                self.on_state("reconnecting", f"Ponawiam połączenie… ({e})")
        return None
