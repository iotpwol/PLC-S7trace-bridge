"""Scope-style trigger state machine. Evaluated on raw decoded signal values."""
from __future__ import annotations

from dataclasses import dataclass

MODES = ["==", ">", "<", "between", "rising edge", "falling edge"]
ACTIONS = ["Pauza", "Zapis CSV", "Pauza + zapis CSV"]
DEFAULT_SNAPSHOT_DB = "snapshots.db"            # a separate SQLite file for the snapshots (folder = TriggerConfig.folder)
PLACES = ("shared", "own")                      # snapshots go to the general database (as REC) or to a separate one


def action_label(action: str, target_label: str) -> str:
    """The text of an action for the chosen target: 'Zapis CSV' -> 'Zapis SQLite' (the stored value stays 'Zapis CSV')."""
    return action.replace("CSV", target_label)


def saves(action: str) -> bool:
    return "CSV" in action                       # every action that writes the snapshot (whatever the target)


OLD_SNAPSHOT_NAME = "snapshot_{tab}_{date}_{time}.csv"
DEFAULT_SNAPSHOT_NAME = "snapshot_{confname}_{ip}_{tab}_{date}_{time}.csv"
DEFAULT_REC_NAME = "REC_{confname}_{ip}_{tab}_{date}_{time}.csv"


@dataclass
class TriggerConfig:
    enabled: bool = False
    signal: str = ""
    mode: str = "=="
    a: float = 0.0
    b: float = 0.0
    hysteresis: float = 0.0
    pretrigger: float = 0.0
    action: str = "Pauza"
    folder: str = "snapshots"
    filename: str = DEFAULT_SNAPSHOT_NAME
    target: str = "csv"                         # where a snapshot goes: "csv" (file) or a database kind (sqlite / influx1 / influx2 / timescale; Web: a target name)
    place: str = "shared"                       # databases: "shared" = the general database (as REC), "own" = a separate one (SQLite file in `folder`, else a separate table / measurement)
    db_file: str = DEFAULT_SNAPSHOT_DB          # separate SQLite file (name in `folder`)


class TriggerEngine:
    """feed(value) -> True on the sample where the trigger fires.

    Level modes fire on the false->true transition of the condition and re-arm
    once the condition has been false (beyond the hysteresis band).
    Edge modes fire when the signal crosses A in the given direction after it
    was previously beyond A -/+ hysteresis.
    """

    def __init__(self, cfg: TriggerConfig):
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self.armed = False
        self.prev: float | None = None

    def _condition(self, v: float) -> bool | None:
        c = self.cfg
        if c.mode == "==":
            return abs(v - c.a) <= c.hysteresis
        if c.mode == ">":
            return v > c.a
        if c.mode == "<":
            return v < c.a
        if c.mode == "between":
            lo, hi = sorted((c.a, c.b))
            return lo <= v <= hi
        return None

    def _rearm_ok(self, v: float) -> bool:
        c, h = self.cfg, self.cfg.hysteresis
        if c.mode == "==":
            return abs(v - c.a) > c.hysteresis
        if c.mode == ">":
            return v < c.a - h
        if c.mode == "<":
            return v > c.a + h
        if c.mode == "between":
            lo, hi = sorted((c.a, c.b))
            return v < lo - h or v > hi + h
        if c.mode == "rising edge":
            return v < c.a - h
        if c.mode == "falling edge":
            return v > c.a + h
        return False

    def feed(self, v: float) -> bool:
        c = self.cfg
        if v != v:  # NaN (connection gap)
            return False
        fired = False
        if c.mode in ("rising edge", "falling edge"):
            if self.armed:
                if c.mode == "rising edge" and v >= c.a:
                    fired = True
                elif c.mode == "falling edge" and v <= c.a:
                    fired = True
            if fired:
                self.armed = False
            elif not self.armed and self._rearm_ok(v):
                self.armed = True
        else:
            cond = self._condition(v)
            if self.armed and cond:
                fired = True
                self.armed = False
            elif not self.armed and self._rearm_ok(v):
                self.armed = True
            # initial state: if condition already true at start, wait for it to go false
            if self.prev is None and not cond:
                self.armed = True
        self.prev = v
        return fired
