"""Test zapisu / odczytu do TimescaleDB (PostgreSQL) z wersji przenosnej S7Trace - np. na Windows Server 2016.

Uruchamiany przez Test-TimescaleDB.bat (pyta o adres serwera) albo z linii polecen:
    python diagnoza_timescale.py --host 10.0.0.5 --port 5432 --db s7 --user s7trace [--password ...] [--sslmode prefer]
          [--table s7trace_selftest] [--keep] [--events 50000] [--drivers psycopg,pg8000]

Co robi (kazdy krok osobno, z czasem i - przy bledzie - pelnym opisem):
  1. srodowisko: wersja Windows, Python, ustawienia proxy,
  2. sterowniki: czy laduja sie `psycopg` (libpq) i `pg8000`, ich wersje i sciezki DLL,
  3. siec: DNS i polaczenie TCP z serwerem,
  4. dla KAZDEGO sterownika: logowanie, wersja serwera, rozszerzenie timescaledb, uprawnienia,
  5. pelny cykl przez kod programu (TimescaleBackend + DbRecorder): zapis nagrania (zmiany stanu, NaN, klatka kluczowa),
     odczyt calosci i zakresu czasu ze stanem sprzed zakresu, porownanie z tym, co zapisano, hypertable i kompresja,
     przepustowosc zapisu, bufor na dysku przy zaniku serwera,
  6. sprzatanie (tabele testowe sa usuwane; --keep zostawia je do ogledu).

Wynik: diagnoza_timescale.txt i diagnoza_timescale.json obok S7Trace.bat (hasla NIE sa zapisywane). Plik .txt
wysylamy deweloperowi - na jego podstawie wiadomo, co poprawic. Kod wyjscia: 0 = wszystko OK, 1 = sa bledy.
"""
from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import platform
import socket
import sys
import tempfile
import time
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.dirname(HERE)):                      # package: app\ (s7trace next to this file); source tree: tools\
    if os.path.isdir(os.path.join(p, "s7trace")) and p not in sys.path:
        sys.path.insert(0, p)
ROOT = os.path.dirname(HERE) if os.path.basename(HERE).lower() == "app" else HERE
if os.path.basename(HERE).lower() == "tools":
    ROOT = os.path.dirname(HERE)

STEPS: list[dict] = []
LINES: list[str] = []


def out(s: str = "") -> None:
    print(s, flush=True)
    LINES.append(s)


class Step:
    """with Step('name') as s: ... - records OK / FAIL, duration and the traceback; never lets the exception out."""

    def __init__(self, name: str, driver: str = ""):
        self.rec = {"step": name, "driver": driver, "ok": True, "info": [], "error": "", "traceback": "", "seconds": 0.0}

    def __enter__(self):
        self.t0 = time.time()
        return self

    def note(self, text: str) -> None:
        self.rec["info"].append(text)
        out("      " + text)

    def __exit__(self, et, ev, tb):
        self.rec["seconds"] = round(time.time() - self.t0, 3)
        if ev is not None:
            self.rec["ok"] = False
            self.rec["error"] = f"{type(ev).__name__}: {ev}"
            self.rec["traceback"] = "".join(traceback.format_exception(et, ev, tb))
        STEPS.append(self.rec)
        tag = "OK   " if self.rec["ok"] else "BLAD "
        label = f"{self.rec['step']}" + (f" [{self.rec['driver']}]" if self.rec["driver"] else "")
        out(f"  {tag}{label}  ({self.rec['seconds']} s)")
        if ev is not None:
            out(f"        {self.rec['error']}")
        return True


# ------------------------------------------------------------------------------------------------ hints
HINTS = [
    ("DLL load failed", "psycopg nie zaladowal libpq (brak systemowej biblioteki?). Program uzyje pg8000; jesli pg8000 tez "
                        "zawodzi, wyslij ten plik. Sprawdz tez Diagnoza.bat (biblioteki Visual C++)."),
    ("libpq", "Problem z biblioteka libpq w psycopg - mozna wymusic pg8000 (czysty Python)."),
    ("password authentication failed", "Zle haslo albo uzytkownik. Sprawdz pg_hba.conf i haslo (scram-sha-256 dziala w obu sterownikach)."),
    ("no pg_hba.conf entry", "Serwer odrzuca ten komputer/uzytkownika/SSL: dopisz wpis w pg_hba.conf (host/hostssl) i przeladuj serwer."),
    ("timed out", "Brak odpowiedzi w limicie czasu: firewall / zly adres / port. Zwieksz 'Limit odpowiedzi serwera' w ustawieniach bazy."),
    ("10061", "Serwer nie nasluchuje na tym porcie albo zapora go blokuje: sprawdz port, listen_addresses i firewall."),
    ("odmawia", "Serwer nie nasluchuje na tym porcie albo zapora go blokuje: sprawdz port, listen_addresses i firewall."),
    ("Connection refused", "Serwer nie nasluchuje na tym porcie: sprawdz listen_addresses w postgresql.conf i firewall."),
    ("could not translate host name", "Nazwa serwera nie jest rozpoznawana (DNS) - uzyj adresu IP."),
    ("getaddrinfo failed", "Nazwa serwera nie jest rozpoznawana (DNS) - uzyj adresu IP."),
    ("SSL", "Problem z SSL: sprobuj --sslmode disable (siec zaufana) albo require / verify-full z poprawnym certyfikatem."),
    ("permission denied", "Brak uprawnien: konto potrzebuje CREATE w bazie (i opcjonalnie prawa do CREATE EXTENSION timescaledb)."),
    ("extension \"timescaledb\" is not available", "Na serwerze nie zainstalowano TimescaleDB - zapis dziala na zwyklym PostgreSQL bez hypertable."),
    ("does not exist", "Brak bazy albo obiektu: utworz baze (CREATE DATABASE) wskazana w --db."),
    ("operator does not exist", "Niezgodnosc typow w zapytaniu (np. timestamptz z tekstem) - blad programu, wyslij ten plik."),
    ("syntax error", "Blad skladni SQL po stronie programu - wyslij ten plik."),
]


def hint_for(text: str) -> str:
    low = text.lower()
    for key, h in HINTS:
        if key.lower() in low:
            return h
    return ""


# ------------------------------------------------------------------------------------------------ steps
def environment() -> None:
    out("== 1. Srodowisko")
    with Step("Windows i Python") as s:
        s.note(f"system: {platform.platform()}  (wersja: {platform.version()})")
        if hasattr(sys, "getwindowsversion"):
            v = sys.getwindowsversion()
            s.note(f"build Windows: {v.major}.{v.minor}.{v.build} (Server 2016 = 10.0.14393)")
        s.note(f"Python: {sys.version.split()[0]} {platform.architecture()[0]}  ({sys.executable})")
        s.note(f"folder: {ROOT} (dlugosc sciezki {len(ROOT)})")
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "PGHOST", "PGSSLMODE", "PGPASSFILE"):
            if os.environ.get(k):
                s.note(f"zmienna {k}={os.environ[k]}")
    with Step("Kod programu (store.py)") as s:
        from s7trace.core import store
        s.note(f"s7trace.core.store: {store.__file__}")


def drivers_check(wanted: list[str]) -> dict:
    out("== 2. Sterowniki PostgreSQL")
    found = {}
    if "psycopg" in wanted:
        with Step("import psycopg (libpq)", "psycopg") as s:
            import psycopg
            s.note(f"psycopg {psycopg.__version__}  ({psycopg.__file__})")
            try:
                from psycopg import pq
                s.note(f"implementacja: {pq.__impl__}, libpq: {pq.version()}")
            except Exception as e:
                s.note(f"libpq: nie da sie odczytac ({e})")
            found["psycopg"] = psycopg
    if "pg8000" in wanted:
        with Step("import pg8000 (czysty Python)", "pg8000") as s:
            import pg8000.dbapi as dbapi
            s.note(f"pg8000 {getattr(dbapi, '__version__', '?')}  ({dbapi.__file__})")
            found["pg8000"] = dbapi
    with Step("wybor sterownika przez program (store._psycopg)") as s:
        from s7trace.core import store
        s.note(f"program wybierze: {store.pg_driver_name() or 'ZADEN'}")
    return found


def network(host: str, port: int, timeout: float) -> bool:
    out("== 3. Siec")
    ok = True
    with Step("DNS") as s:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        s.note("adresy: " + ", ".join(sorted({i[4][0] for i in infos})))
    ok &= STEPS[-1]["ok"]
    with Step(f"TCP {host}:{port}") as s:
        t0 = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            s.note(f"polaczono w {1000 * (time.time() - t0):.0f} ms")
    ok &= STEPS[-1]["ok"]
    return bool(ok)


def server_check(name: str, mod, cfg) -> bool:
    from s7trace.core import store
    ok = True
    with Step("logowanie i wersja serwera", name) as s:
        conn = store._pg_connect(mod, cfg, int(cfg.http_timeout_s))
        cur = conn.cursor()
        cur.execute("SELECT version()")
        s.note(cur.fetchone()[0])
        cur.execute("SHOW server_encoding")
        s.note(f"kodowanie serwera: {cur.fetchone()[0]}")
        cur.execute("SELECT current_user, current_database(), has_database_privilege(current_database(), 'CREATE')")
        user, db, can_create = cur.fetchone()
        s.note(f"uzytkownik {user}, baza {db}, prawo CREATE w bazie: {can_create}")
        if not can_create:
            raise RuntimeError("permission denied: konto nie ma prawa CREATE w tej bazie")
        try:
            cur.execute("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            r = cur.fetchone()
            s.note(f"szyfrowanie SSL: {'tak' if r and r[0] else 'nie'}")
        except Exception:
            conn.rollback()
        conn.close()
    ok &= STEPS[-1]["ok"]
    with Step("rozszerzenie timescaledb", name) as s:
        conn = store._pg_connect(mod, cfg, int(cfg.http_timeout_s))
        cur = conn.cursor()
        cur.execute("SELECT extversion FROM pg_extension WHERE extname='timescaledb'")
        r = cur.fetchone()
        if r:
            s.note(f"zainstalowane w tej bazie, wersja {r[0]}")
        else:
            cur.execute("SELECT default_version FROM pg_available_extensions WHERE name='timescaledb'")
            r = cur.fetchone()
            s.note(f"dostepne na serwerze (wersja {r[0]}), jeszcze nie wlaczone w tej bazie - program wlaczy je sam (CREATE EXTENSION)"
                   if r else "NIE zainstalowane na serwerze - zapis zadziala jako zwykly PostgreSQL (bez hypertable i kompresji)")
        conn.close()
    return bool(ok)


def expected_rows(n: int):
    """The signal values fed to the recorder: A toggles, B ramps then holds, C constant, D has a gap (NaN)."""
    rows = []
    for i in range(n):
        t = i * 0.05
        rows.append((t, [float((i // 40) % 2), min(i, 60) * 0.5, 7.0, math.nan if 100 <= i < 130 else float(i % 5)]))
    return rows


def check_matrix(t_us, mat, rows) -> int:
    """Number of samples where the rebuilt step curves differ from what was fed in."""
    import numpy as np
    t = (t_us - t_us[0]) / 1e6
    bad = 0
    for tt, v in rows:
        k = int(np.searchsorted(t, tt + 1e-6, side="right")) - 1
        if k < 0 or not np.array_equal(np.isnan(mat[k]), np.isnan(v)) or not np.allclose(
                np.nan_to_num(mat[k]), np.nan_to_num(np.array(v)), atol=1e-9):
            bad += 1
    return bad


def full_cycle(name: str, mod, cfg_base, keep: bool, events: int) -> None:
    from s7trace.core import store
    from s7trace.core.types import Signal
    cfg = type(cfg_base).from_dict({**cfg_base.to_dict(), "pg_password": cfg_base.pg_password})
    cfg.remember = True
    cfg.kind, cfg.mode, cfg.keyframe_min = "timescale", "changes", 0.05            # keyframe every 3 s -> several in the test
    cfg.batch_s, cfg.close_grace_s, cfg.spool_mb = 0.1, 20.0, 50
    orig = store._psycopg
    store._psycopg = lambda: mod                                                   # force this driver
    tmp = tempfile.mkdtemp(prefix="s7t_selftest_")
    sigs = [Signal(name="A", dtype="BOOL"), Signal(name="B", dtype="REAL"), Signal(name="C", dtype="INT"),
            Signal(name="D", dtype="REAL")]
    start = datetime(2026, 10, 3, 8, 0, 0)
    rows = expected_rows(1200)                                                    # 60 s of data at 50 ms
    sid = {}
    try:
        with Step("zapis nagrania przez DbRecorder (zmiany + NaN + klatki kluczowe)", name) as s:
            rec = store.DbRecorder(cfg, sigs, start, {"name": "selftest", "ip": "0.0.0.0", "tab": "T", "conf": "selftest"},
                                   base_dir=tmp)
            for t, v in rows:
                rec.write(t, v)
            rec.close()
            sid["id"] = rec.session
            s.note(f"zapisano wpisow: {rec.written}, utracono: {rec.dropped}, w kolejce: {rec.q.qsize()}, na dysku: {rec.spooled}")
            if rec.last_error:
                raise RuntimeError(rec.last_error)
            if rec.written < 40 or rec.dropped or rec.spooled:
                raise RuntimeError("nie wszystkie dane trafily do bazy (patrz liczniki wyzej)")
        if not sid:
            return
        with Step("odczyt calego nagrania i porownanie z zapisanym", name) as s:
            b = store.open_backend(cfg, tmp)
            try:
                sess = [x for x in b.sessions() if x["id"] == sid["id"]]
                if len(sess) != 1:
                    raise RuntimeError("nagrania nie ma na liscie sesji")
                s.note(f"sesje w bazie: {len(b.sessions())}; sygnaly: {[x['name'] for x in sess[0]['signals']]}")
                meta, t, m = b.read(sid["id"])
                bad = check_matrix(t, m, rows)
                s.note(f"wierszy odczytanych: {len(t)}; probek rozbieznych z zapisem: {bad} z {len(rows)}")
                if bad:
                    raise RuntimeError(f"{bad} probek rozni sie od zapisanych")
            finally:
                b.close()
        with Step("odczyt zakresu czasu (stan sprzed zakresu)", name) as s:
            b = store.open_backend(cfg, tmp)
            try:
                lo, hi = store.to_us(start, 20.0), store.to_us(start, 40.0)
                meta, t, m = b.read(sid["id"], lo, hi)
                s.note(f"wierszy: {len(t)}, kolumna C (stala, zapisana raz): {sorted(set(m[:, 2].tolist())) if len(t) else '-'}")
                if not len(t) or set(m[:, 2].tolist()) != {7.0}:
                    raise RuntimeError("zakres nie zawiera stanu sprzed zakresu (stala C powinna byc 7.0 od pierwszego wiersza)")
                if t[0] < lo or t[-1] > hi:
                    raise RuntimeError("wiersze poza zadanym zakresem")
            finally:
                b.close()
        with Step("hypertable i kompresja (TimescaleDB)", name) as s:
            conn = store._pg_connect(mod, cfg, int(cfg.http_timeout_s))
            try:
                cur = conn.cursor()
                cur.execute("SELECT extversion FROM pg_extension WHERE extname='timescaledb'")
                if not cur.fetchone():
                    s.note("brak rozszerzenia timescaledb - zwykly PostgreSQL (to dozwolone, ale bez kompresji i podzialu na fragmenty)")
                else:
                    cur.execute("SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_name=%s",
                                (cfg.table,))
                    if not cur.fetchone():
                        raise RuntimeError(f"tabela {cfg.table} nie jest hypertable (create_hypertable nie powiodlo sie)")
                    s.note("tabela jest hypertable")
                    cur.execute("SELECT count(*) FROM timescaledb_information.jobs WHERE hypertable_name=%s "
                                "AND proc_name='policy_compression'", (cfg.table,))
                    s.note(f"polityka kompresji (po 7 dniach): {'jest' if cur.fetchone()[0] else 'BRAK'}")
            finally:
                conn.rollback()
                conn.close()
        with Step(f"przepustowosc zapisu ({events} wpisow)", name) as s:
            b = store.open_backend(cfg, tmp)
            try:
                b.begin({"id": "selftest_speed", "name": "speed", "start_us": store.to_us(start, 0), "mode": "all",
                         "signals": [x.to_dict() for x in sigs], "fields": ["A", "B", "C", "D"]})
                data = [(store.to_us(start, i * 0.001), {0: 1.0, 1: float(i), 2: 7.0, 3: 0.5}) for i in range(events // 4)]
                t0 = time.time()
                for k in range(0, len(data), 20000):
                    b.write(data[k:k + 20000])
                dt = max(time.time() - t0, 1e-6)
                s.note(f"{events / dt:,.0f} wpisow/s ({dt:.2f} s) - potrzeba zwykle ponizej 1 000 wpisow/s")
            finally:
                b.close()
        with Step("bufor na dysku przy zaniku serwera i dosylanie", name) as s:
            # the outage is simulated at the connect call, so the target (host/port/base/table) stays the same
            real_connect = store._pg_connect
            down = {"v": True}

            def flaky(pg, c, timeout):
                if down["v"]:
                    raise OSError("symulacja: serwer niedostepny")
                return real_connect(pg, c, timeout)
            store._pg_connect = flaky
            spool_cfg = type(cfg).from_dict({**cfg.to_dict(), "pg_password": cfg.pg_password})
            spool_cfg.kind, spool_cfg.retry_max_s, spool_cfg.close_grace_s = "timescale", 1, 0.5
            spool_dir = os.path.join(tmp, "spool")
            try:
                rec = store.DbRecorder(spool_cfg, sigs, start, {"conf": "selftest_spool"}, base_dir=tmp)
                for t, v in rows[:200]:
                    rec.write(t, v)
                deadline = time.time() + 15
                while rec.spooled == 0 and time.time() < deadline:
                    time.sleep(0.2)
                s.note(f"serwer niedostepny: na dysku {rec.spooled}, blad: {rec.last_error[:90]!r}")
                if rec.spooled == 0:
                    raise RuntimeError("dane nie trafily do bufora na dysku")
                rec.close()
                old_id = rec.session
                left = os.listdir(spool_dir) if os.path.isdir(spool_dir) else []
                s.note(f"plik bufora po zamknieciu (program zamkniety, serwer nadal niedostepny): {left}")
                if not left:
                    raise RuntimeError("bufor nie przetrwal zamkniecia")
                down["v"] = False                                                   # the server is back; next REC
                rec2 = store.DbRecorder(spool_cfg, sigs, start, {"conf": "selftest_spool2"}, base_dir=tmp)
                rec2.write(0.0, rows[0][1])
                deadline = time.time() + 20
                while time.time() < deadline and any(f.endswith(".db") and rec2.session not in f for f in os.listdir(spool_dir)):
                    time.sleep(0.3)
                rec2.close()
                left2 = os.listdir(spool_dir) if os.path.isdir(spool_dir) else []
                s.note(f"po powrocie serwera zostalo plikow bufora: {left2}")
                if left2:
                    raise RuntimeError("bufor nie zostal dosniety / usuniety po powrocie serwera")
                b = store.open_backend(spool_cfg, tmp)
                try:
                    meta, t, m = b.read(old_id)
                    s.note(f"dosniete nagranie z bufora: {len(t)} wierszy")
                    if len(t) < 5:
                        raise RuntimeError("nagranie z bufora nie dotarlo do bazy")
                finally:
                    b.close()
            finally:
                store._pg_connect = real_connect
    finally:
        store._psycopg = orig
        if not keep:
            with Step("sprzatanie (usuniecie tabel testowych)", name) as s:
                store._psycopg = lambda: mod
                try:
                    conn = store._pg_connect(mod, cfg, int(cfg.http_timeout_s))
                    cur = conn.cursor()
                    cur.execute(f"DROP TABLE IF EXISTS {cfg.table}")
                    cur.execute(f"DROP TABLE IF EXISTS {cfg.table}_sessions")
                    conn.commit()
                    conn.close()
                    s.note(f"usunieto {cfg.table} i {cfg.table}_sessions")
                finally:
                    store._psycopg = orig
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


# ------------------------------------------------------------------------------------------------ main
def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    try:
        if secret:
            return getpass.getpass(f"{prompt}: ") or default
        v = input(f"{prompt} [{default}]: ").strip()
        return v or default
    except (EOFError, KeyboardInterrupt):
        return default


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--db")
    ap.add_argument("--user")
    ap.add_argument("--password", help="(albo zmienna PGPASSWORD / pytanie na ekranie; haslo nie trafia do raportu)")
    ap.add_argument("--sslmode", default=None)
    ap.add_argument("--table", default=None)
    ap.add_argument("--drivers", default="psycopg,pg8000")
    ap.add_argument("--events", type=int, default=50000)
    ap.add_argument("--keep", action="store_true", help="nie usuwaj tabel testowych")
    ap.add_argument("--no-server", action="store_true", help="tylko kroki bez serwera (srodowisko, sterowniki)")
    ap.add_argument("--report", default=os.path.join(ROOT, "diagnoza_timescale"))
    a = ap.parse_args(argv)

    STEPS.clear()
    LINES.clear()
    out("=== S7Trace - test TimescaleDB / PostgreSQL ===")
    out(f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}   komputer: {platform.node()}")
    environment()
    wanted = [d.strip() for d in a.drivers.split(",") if d.strip()]
    found = drivers_check(wanted)

    if not a.no_server:
        interactive = a.host is None
        a.host = a.host or ask("Adres serwera PostgreSQL / TimescaleDB", "127.0.0.1")
        a.port = a.port or int(ask("Port", "5432"))
        a.db = a.db or ask("Baza (musi istniec)", "postgres")
        a.user = a.user or ask("Uzytkownik", "postgres")
        pw = a.password if a.password is not None else os.environ.get("PGPASSWORD")
        if pw is None:
            pw = ask("Haslo (nie bedzie widoczne ani zapisane)", "", secret=True) if interactive else ""
        ssl = a.sslmode or (ask("sslmode (disable / prefer / require / verify-full)", "prefer") if interactive else "prefer")
        table = a.table or "s7trace_selftest_" + os.urandom(3).hex()
        from s7trace.core.store import StoreConfig
        cfg = StoreConfig(kind="timescale", host=a.host, port=a.port, pg_database=a.db, pg_user=a.user,
                          pg_password=pw, pg_sslmode=ssl, table=table)
        out(f"Serwer: {a.host}:{a.port}  baza: {a.db}  uzytkownik: {a.user}  sslmode: {ssl}  tabela testowa: {table}")
        out("== 3. Siec i serwer")
        if network(a.host, a.port, 5.0):
            for name, mod in found.items():
                out(f"== 4/5. Sterownik {name}")
                if server_check(name, mod, cfg):
                    full_cycle(name, mod, cfg, a.keep, a.events)
                else:
                    out(f"  (pelny cykl pominiety: nie ma polaczenia / uprawnien przez {name})")
        else:
            out("  Serwer nieosiagalny - kroki z serwerem pominiete.")

    # ------------------------------------------------------------------ summary
    failed = [s for s in STEPS if not s["ok"]]
    out("")
    out("=== PODSUMOWANIE ===")
    out(f"Krokow: {len(STEPS)}, bledow: {len(failed)}")
    for s in failed:
        out(f"- {s['step']}" + (f" [{s['driver']}]" if s["driver"] else "") + f": {s['error']}")
        h = hint_for(s["error"])                                  # the message only: tracebacks mention "ssl" everywhere
        if h:
            out(f"    wskazowka: {h}")
    if failed:
        out("")
        out("=== SZCZEGOLY BLEDOW (traceback) ===")
        for s in failed:
            out(f"--- {s['step']} [{s['driver']}]")
            out(s["traceback"].rstrip())
    else:
        out("Wszystko dziala.")
    with open(a.report + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    with open(a.report + ".json", "w", encoding="utf-8") as f:
        json.dump({"date": datetime.now().isoformat(timespec="seconds"), "host": platform.node(),
                   "platform": platform.platform(), "python": sys.version, "steps": STEPS}, f, ensure_ascii=False, indent=1)
    out(f"Raport: {a.report}.txt  (oraz .json)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
