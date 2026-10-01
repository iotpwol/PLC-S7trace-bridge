"""Link diagnostics: read-latency statistics, sampling jitter, lost cycles, reconnects, throughput,
ICMP ping probe and a one-shot TCP port check. Pure Python (no Qt) so it can be unit-tested."""
from __future__ import annotations

import math
import re
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable

import numpy as np

from .planner import MAX_MULTI, MODE_MULTI, build_plan
from .types import SOURCES, Signal

HIST_EDGES = [0, 2, 5, 10, 20, 50, 100, 200, 500, 1000]          # ms; the last bucket is open ended
S7_OVERHEAD_B = 150          # rough Ethernet+IP+TCP+TPKT+COTP+S7 bytes of one request/response pair (estimate)


def plan_cost(signals: list[Signal], mode: str) -> tuple[int, int]:
    """(payload bytes, requests) of one read cycle for the given signals."""
    if any(s.source not in SOURCES for s in signals):            # OPC UA / Web API / Modbus: no S7 read plan
        return sum(s.size for s in signals), (len(signals) if any(s.source.startswith("MB") for s in signals) else 1)
    plan = build_plan(signals, mode)
    reqs = -(-len(plan) // MAX_MULTI) if mode == MODE_MULTI else len(plan)
    return sum(b.size for b in plan), reqs


def _stats(a: np.ndarray) -> dict:
    if not len(a):
        return {}
    return {"min": float(a.min()), "max": float(a.max()), "avg": float(a.mean()), "std": float(a.std()),
            "p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99))}


class LinkDiag:
    """Collects per-cycle data of one connection. Fed from the reader thread, read from the GUI thread."""

    def __init__(self, cycle_ms: float = 25.0, bytes_per_cycle: int = 0, req_per_cycle: int = 0,
                 stats=None, keep: int = 20000):
        self._lock = threading.Lock()
        self.cycle_ms = cycle_ms
        self.stats = stats                      # acquirer counters (samples, missed, errors, reconnects ...)
        self.keep = keep
        self.bytes_per_cycle, self.req_per_cycle = bytes_per_cycle, req_per_cycle
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.lags: deque = deque(maxlen=self.keep)        # (t, lag_ms)
            self.dts: deque = deque(maxlen=self.keep)         # (t, interval_ms between consecutive samples)
            self.n = 0
            self.sum = self.sumsq = 0.0
            self.min, self.max = math.inf, 0.0
            self.hist = [0] * len(HIST_EDGES)
            self.overruns = 0                                  # reads that took longer than the cycle
            self.gap_rows = 0                                  # NaN rows = connection loss markers
            self._last_t: float | None = None
            self.t_first: float | None = None
            self.t_last: float | None = None
            self.wall_start = time.time()
            self.up_since: float | None = None
            self.down_since: float | None = None
            self.down_total = 0.0
            self.ended: float | None = None
            self.state = "stopped"

    def set_plan(self, bytes_per_cycle: int, req_per_cycle: int) -> None:
        self.bytes_per_cycle, self.req_per_cycle = bytes_per_cycle, req_per_cycle

    # ------------------------------------------------------------------ feed
    def add_sample(self, t: float, lag_ms: float | None) -> None:
        with self._lock:
            if lag_ms is None:                                 # connection-loss marker
                self.gap_rows += 1
                self._last_t = None
                return
            if self.t_first is None:
                self.t_first = t
            self.t_last = t
            self.n += 1
            self.sum += lag_ms
            self.sumsq += lag_ms * lag_ms
            self.min, self.max = min(self.min, lag_ms), max(self.max, lag_ms)
            i = max(k for k, e in enumerate(HIST_EDGES) if lag_ms >= e)
            self.hist[i] += 1
            if lag_ms > self.cycle_ms:
                self.overruns += 1
            self.lags.append((t, lag_ms))
            if self._last_t is not None:
                self.dts.append((t, (t - self._last_t) * 1000.0))
            self._last_t = t

    def note_state(self, state: str) -> None:
        now = time.time()
        with self._lock:
            self.state = state
            if state == "running":
                if self.up_since is None:
                    self.up_since = now
                if self.down_since is not None:
                    self.down_total += now - self.down_since
                    self.down_since = None
            elif state == "reconnecting":
                if self.down_since is None:
                    self.down_since = now
            elif state in ("stopped", "error"):
                if self.down_since is not None:
                    self.down_total += now - self.down_since
                    self.down_since = None
                self.ended = now

    # -------------------------------------------------------------- results
    def snapshot(self) -> dict:
        with self._lock:
            lags = np.array([x[1] for x in self.lags]) if self.lags else np.empty(0)
            lt = np.array([x[0] for x in self.lags]) if self.lags else np.empty(0)
            dts = np.array([x[1] for x in self.dts]) if self.dts else np.empty(0)
            dtt = np.array([x[0] for x in self.dts]) if self.dts else np.empty(0)
            n, s, ss = self.n, self.sum, self.sumsq
            t_first, t_last = self.t_first, self.t_last
            hist, overruns, gaps = list(self.hist), self.overruns, self.gap_rows
            mn, mx = self.min, self.max
            up_since, down_total, down_since, ended = self.up_since, self.down_total, self.down_since, self.ended
            state = self.state
            cycle, bpc, rpc = self.cycle_ms, self.bytes_per_cycle, self.req_per_cycle
        st = self.stats
        out: dict = {"state": state, "cycle_ms": cycle, "n": n, "hist": hist, "overruns": overruns, "gap_rows": gaps,
                     "bytes_per_cycle": bpc, "req_per_cycle": rpc,
                     "samples": getattr(st, "samples", n), "missed": getattr(st, "missed", 0),
                     "errors": getattr(st, "errors", 0), "reconnects": getattr(st, "reconnects", 0),
                     "last_error": getattr(st, "last_error", ""), "connect_ms": getattr(st, "connect_ms", 0.0)}
        tot = out["samples"] + out["missed"]
        out["missed_pct"] = 100.0 * out["missed"] / tot if tot else 0.0
        out["overrun_pct"] = 100.0 * overruns / n if n else 0.0

        lag: dict = {}
        if n:
            mean = s / n
            lag = {"last": float(lags[-1]) if len(lags) else mean, "avg": mean, "min": mn, "max": mx,
                   "std": math.sqrt(max(ss / n - mean * mean, 0.0))}
            ring = _stats(lags)
            lag.update({k: ring[k] for k in ("p50", "p95", "p99")})
            for w in (10, 60):
                m = lt >= t_last - w
                lag[f"avg{w}"] = float(lags[m].mean()) if m.any() else None
        out["lag"] = lag

        per: dict = {}
        if len(dts):
            ring = _stats(dts)
            per = {"last": float(dts[-1]), "avg": float(dts.mean()), "min": ring["min"], "max": ring["max"],
                   "std": ring["std"], "p50": ring["p50"], "p95": ring["p95"], "p99": ring["p99"]}
            for w in (10, 60):
                m = dtt >= (dtt[-1] - w)
                per[f"avg{w}"] = float(dts[m].mean()) if m.any() else None
            per["jitter"] = float(np.abs(np.diff(dts)).mean()) if len(dts) > 1 else 0.0
        out["period"] = per

        span = (t_last - t_first) if (t_first is not None and t_last is not None) else 0.0
        rate = n / span if span > 0 else 0.0
        rate10 = 0.0
        if len(lt) > 1:
            m = lt >= t_last - 10
            w = lt[m][-1] - lt[m][0] if m.sum() > 1 else 0.0
            rate10 = (m.sum() - 1) / w if w > 0 else 0.0
        out.update(rate=rate, rate10=rate10, expected_rate=1000.0 / cycle if cycle > 0 else 0.0)
        out["bytes_per_s"] = bpc * rate10
        out["req_per_s"] = rpc * rate10
        out["wire_bytes_per_s"] = (bpc + S7_OVERHEAD_B * rpc) * rate10
        avg = lag.get("avg")
        out["max_rate"] = 1000.0 / avg if avg else 0.0
        out["safe_cycle_ms"] = math.ceil(lag["p99"] * 1.25) if lag else 0

        now = ended or time.time()
        down = down_total + ((now - down_since) if down_since else 0.0)
        total = (now - up_since) if up_since else 0.0
        out["uptime_s"] = total
        out["down_s"] = down
        out["availability"] = 100.0 * max(total - down, 0.0) / total if total > 0 else 0.0
        return out

    def lag_series(self, seconds: float = 120.0) -> tuple[np.ndarray, np.ndarray]:
        """(sample times, lags) of the last `seconds` of data."""
        with self._lock:
            if not self.lags or self.t_last is None:
                return np.empty(0), np.empty(0)
            a = np.array(self.lags)
        m = a[:, 0] >= self.t_last - seconds
        return a[m, 0], a[m, 1]


# ---------------------------------------------------------------- ping probe
_RTT = re.compile(r"[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", re.I)


def parse_ping(output: str) -> float | None:
    """RTT [ms] from the output of the system `ping` (any Windows language); None = no echo reply."""
    if not re.search(r"\bTTL\s*=", output, re.I):             # replies carry TTL=; 'unreachable' / timeouts do not
        return None
    m = _RTT.search(output)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return 0.5 if "<" in m.group(0) and v <= 1 else v


def system_ping(host: str, timeout_ms: int = 1000) -> float | None:
    if sys.platform.startswith("win"):
        cmd, flags = ["ping", "-n", "1", "-w", str(timeout_ms), host], 0x08000000      # CREATE_NO_WINDOW
    else:
        cmd, flags = ["ping", "-c", "1", "-W", str(max(timeout_ms // 1000, 1)), host], 0
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout_ms / 1000 + 3, creationflags=flags)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"polecenie ping niedostępne: {e}")
    return parse_ping(r.stdout.decode("latin-1"))        # only TTL= and digits matter (any Windows language)


class PingProbe(threading.Thread):
    """Pings the PLC once per `interval` seconds (ICMP does not use any S7 connection resource)."""

    def __init__(self, host: str, interval: float = 1.0, timeout_ms: int = 1000,
                 runner: Callable[[str], float | None] | None = None):
        super().__init__(daemon=True, name="S7Ping")
        self.host, self.interval, self.timeout_ms = host, interval, timeout_ms
        self._runner = runner or (lambda h: system_ping(h, timeout_ms))
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self.error = ""
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.sent = self.recv = 0
            self.sum = 0.0
            self.min, self.max = math.inf, 0.0
            self.last: float | None = None
            self.jit_sum, self.jit_n, self._prev = 0.0, 0, None
            self.consec_lost = 0
            self.history: deque = deque(maxlen=3000)         # (perf_counter, rtt or None)

    def stop(self) -> None:
        self._stop_evt.set()

    def record(self, rtt: float | None) -> None:
        with self._lock:
            self.sent += 1
            self.history.append((time.perf_counter(), rtt))
            if rtt is None:
                self.consec_lost += 1
                self.last = None
                return
            self.recv += 1
            self.consec_lost = 0
            self.sum += rtt
            self.min, self.max, self.last = min(self.min, rtt), max(self.max, rtt), rtt
            if self._prev is not None:
                self.jit_sum += abs(rtt - self._prev)
                self.jit_n += 1
            self._prev = rtt

    def run(self) -> None:
        nxt = time.perf_counter()
        while not self._stop_evt.is_set():
            try:
                self.record(self._runner(self.host))
                self.error = ""
            except Exception as e:                           # ping.exe missing / blocked
                self.error = str(e)
                self.record(None)
            nxt += self.interval
            while not self._stop_evt.is_set():
                rem = nxt - time.perf_counter()
                if rem <= 0:
                    break
                time.sleep(min(rem, 0.1))

    def snapshot(self) -> dict:
        with self._lock:
            lost = self.sent - self.recv
            return {"sent": self.sent, "recv": self.recv, "lost": lost,
                    "loss_pct": 100.0 * lost / self.sent if self.sent else 0.0,
                    "last": self.last, "avg": self.sum / self.recv if self.recv else None,
                    "min": self.min if self.recv else None, "max": self.max if self.recv else None,
                    "jitter": self.jit_sum / self.jit_n if self.jit_n else None,
                    "consec_lost": self.consec_lost, "error": self.error}

    def series(self, seconds: float = 120.0) -> list[tuple[float, float | None]]:
        now = time.perf_counter()
        with self._lock:
            return [(t, r) for t, r in self.history if t >= now - seconds]


def tcp_probe(host: str, port: int = 102, timeout: float = 2.0) -> tuple[bool, float, str]:
    """One TCP connect to the S7 port: (ok, connect time ms, error text)."""
    t = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, (time.perf_counter() - t) * 1000.0, ""
    except OSError as e:
        return False, (time.perf_counter() - t) * 1000.0, str(e)


# --------------------------------------------------------------------- report
def verdict(d: dict, ping: dict | None = None) -> tuple[str, list[str]]:
    """Overall rating + the observations behind it."""
    notes: list[str] = []
    score = 0                                                 # 0 = very good ... higher = worse
    if d["state"] == "reconnecting":
        return "Brak połączenia", ["Połączenie ze sterownikiem jest przerwane – trwa ponawianie."]
    if not d["lag"]:
        return "Brak danych", ["Brak próbek – uruchom połączenie (Start)."]
    if d["reconnects"] or d["errors"]:
        score += 2
        notes.append(f"Zerwania połączenia: {d['reconnects']}, błędy odczytu: {d['errors']} "
                     f"(ostatni: {d['last_error'] or '—'}), łączny czas przerw {d['down_s']:.1f} s.")
    if d["missed_pct"] > 5:
        score += 2
        notes.append(f"Pominięte cykle: {d['missed_pct']:.1f}% – odczyt trwa dłużej niż ustawiony cykl "
                     f"({d['cycle_ms']:g} ms). Zwiększ cykl do ≥ {d['safe_cycle_ms']} ms lub ogranicz liczbę sygnałów.")
    elif d["missed_pct"] > 0.5:
        score += 1
        notes.append(f"Pominięte cykle: {d['missed_pct']:.1f}% – sporadyczne przekroczenia cyklu.")
    if d["lag"]["p99"] > d["cycle_ms"]:
        score += 1
        notes.append(f"99% odczytów mieści się w {d['lag']['p99']:.1f} ms, a cykl to {d['cycle_ms']:g} ms – "
                     f"zalecany cykl ≥ {d['safe_cycle_ms']} ms.")
    if d["period"] and d["period"]["jitter"] > 0.5 * d["cycle_ms"]:
        score += 1
        notes.append(f"Duży jitter próbkowania ({d['period']['jitter']:.1f} ms) – nierówne odstępy między próbkami.")
    if ping:
        if ping["sent"] and ping["loss_pct"] > 0:
            score += 2 if ping["loss_pct"] > 2 else 1
            notes.append(f"Ping: utracono {ping['lost']} z {ping['sent']} pakietów ({ping['loss_pct']:.1f}%).")
        if ping["avg"] and ping["avg"] > 50:
            score += 1
            notes.append(f"Wysokie opóźnienie sieci (ping śr. {ping['avg']:.0f} ms).")
    if not notes:
        notes.append("Brak zastrzeżeń: odczyty mieszczą się w cyklu, bez zerwań i utraty pakietów.")
    return ("Bardzo dobre", "Dobre", "Przeciętne", "Słabe", "Słabe", "Słabe", "Słabe")[min(score, 6)], notes


def _f(v, fmt="{:.1f}", dash="—") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) and v == v else dash


def format_report(d: dict, ping: dict | None, host: str = "", title: str = "") -> str:
    """Plain-text report (clipboard / file)."""
    L = [f"Raport diagnostyczny S7Trace – {title}", f"Czas: {datetime.now():%Y-%m-%d %H:%M:%S}", f"Sterownik: {host}", ""]
    rating, notes = verdict(d, ping)
    L += [f"Ocena łącza: {rating}"] + [f" - {n}" for n in notes] + [""]
    lg, pr = d["lag"], d["period"]
    L.append("Czas odczytu [ms]   chwilowo  śr.10s  śr.60s  śr.całość  min  max  odch.std  P95  P99")
    if lg:
        L.append("  " + "  ".join(_f(lg.get(k)) for k in ("last", "avg10", "avg60", "avg", "min", "max", "std", "p95", "p99")))
    L.append("Okres próbkowania [ms] (jitter = śr. zmiana okresu)")
    if pr:
        L.append("  " + "  ".join(_f(pr.get(k)) for k in ("last", "avg10", "avg60", "avg", "min", "max", "std", "p95", "p99"))
                 + f"  jitter {_f(pr.get('jitter'))}")
    L += ["",
          f"Cykl ustawiony: {d['cycle_ms']:g} ms | częstotliwość oczekiwana {_f(d['expected_rate'])} Hz, "
          f"rzeczywista {_f(d['rate10'])} Hz (10 s) / {_f(d['rate'])} Hz (całość), maks. możliwa {_f(d['max_rate'])} Hz",
          f"Próbki: {d['samples']}, pominięte cykle: {d['missed']} ({d['missed_pct']:.2f}%), "
          f"odczyty dłuższe niż cykl: {d['overruns']} ({d['overrun_pct']:.2f}%)",
          f"Błędy odczytu: {d['errors']}, ponowne połączenia: {d['reconnects']}, czas przerw: {d['down_s']:.1f} s, "
          f"dostępność: {d['availability']:.2f}%, czas nawiązania połączenia: {_f(d['connect_ms'])} ms",
          f"Dane na cykl: {d['bytes_per_cycle']} B w {d['req_per_cycle']} żądaniach; przepustowość: "
          f"{_f(d['bytes_per_s'], '{:.0f}')} B/s, {_f(d['req_per_s'])} żądań/s, "
          f"ruch w sieci ok. {_f(d['wire_bytes_per_s'] * 8 / 1000)} kb/s (szacunek)"]
    if ping:
        L += ["", f"Ping ICMP: wysłano {ping['sent']}, odebrano {ping['recv']}, utracono {ping['lost']} "
                  f"({ping['loss_pct']:.1f}%); ostatni {_f(ping['last'])} ms, śr. {_f(ping['avg'])}, "
                  f"min {_f(ping['min'])}, max {_f(ping['max'])}, jitter {_f(ping['jitter'])} ms"]
    return "\n".join(L) + "\n"
