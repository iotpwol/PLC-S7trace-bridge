"""Local S7 simulator for trying the app without a PLC.

    python -m s7trace.sim            # listens on 127.0.0.1:1102
Then in S7trace use IP "127.0.0.1:1102", rack 0, slot 2 and add signals e.g.
DB1 byte 160 bit 0..4 BOOL, DB1 byte 170 INT (counter), DB1 byte 172 REAL (sine).
"""
from __future__ import annotations

import math
import struct
import sys
import threading
import time

from snap7.server import Server
from snap7.type import SrvArea


class Simulator:
    def __init__(self, port: int = 1102):
        self.port = port
        self.db1 = bytearray(400)
        self.pe = bytearray(64)
        self.pa = bytearray(64)
        self.mk = bytearray(64)
        self.server = Server()
        self._stop = threading.Event()

    def start(self) -> None:
        self.server.register_area(SrvArea.DB, 1, self.db1)
        self.server.register_area(SrvArea.PE, 0, self.pe)
        self.server.register_area(SrvArea.PA, 0, self.pa)
        self.server.register_area(SrvArea.MK, 0, self.mk)
        self.server.start(tcp_port=self.port)
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.server.stop()
        self.server.destroy()

    def _loop(self) -> None:
        t0 = time.time()
        n = 0
        while not self._stop.is_set():
            t = time.time() - t0
            b = 0
            # bit i toggles with its own period (1.5 s, 3 s, 4.5 s ...)
            for i in range(5):
                if int(t / (1.5 * (i + 1))) % 2 == 0 and (i != 0 or (t % 6.0) < 1.0):
                    b |= 1 << i
            self.db1[160] = b
            n = (n + 1) % 30000
            struct.pack_into(">h", self.db1, 170, n)
            struct.pack_into(">f", self.db1, 172, math.sin(t) * 50.0)
            self.mk[0] = b
            self.pe[0] = b ^ 0xFF
            time.sleep(0.01)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1102
    sim = Simulator(port)
    sim.start()
    print(f"S7 simulator on 127.0.0.1:{port} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sim.stop()
