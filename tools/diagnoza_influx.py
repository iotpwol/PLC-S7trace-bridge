"""Test zapisu / odczytu / usuwania w InfluxDB 1.x i 2.x z wersji przenosnej S7Trace.

Uruchamiany przez Test-InfluxDB.bat (pyta o adres i dane logowania) albo z linii polecen:
    python diagnoza_influx.py --version 2 --url http://10.0.0.5:8086 --org moja --bucket s7 --token TOKEN [--keep]
    python diagnoza_influx.py --version 1 --url http://10.0.0.5:8086 --db s7 --user u --password p [--keep]

Co robi (kazdy krok osobno, z czasem i - przy bledzie - pelnym opisem):
  1. srodowisko, siec (DNS, TCP), wersja serwera i logowanie,
  2. zapis nagrania przez kod programu (DbRecorder: zmiany stanu, NaN, klatki kluczowe) i porownanie odczytu z zapisem,
  3. odczyt zakresu czasu: ze stanem sprzed zakresu z klatek kluczowych ORAZ (nagranie bez klatek) zapytaniem "ostatnia
     wartosc przed zakresem" - to ono zalezy od skladni zapytan serwera,
  4. odczyt bardzo duzego zakresu w kawalkach (zmniejszanie danych, szpilka musi zostac),
  5. tytul / uwagi / kosz (punkty o tym samym czasie musza sie scalic, nie dublowac),
  6. USUWANIE nagrania (v1: DROP SERIES, v2: /api/v2/delete): znika tylko wskazane nagranie, drugie zostaje,
  7. przepustowosc zapisu,
  8. sprzatanie (dane testowe sa usuwane; --keep zostawia je do ogledu).

Dane testowe maja swoj pomiar (measurement) `s7trace_selftest_<losowe>`; nic innego w bazie nie jest zmieniane.
Wynik: diagnoza_influx.txt i diagnoza_influx.json (tokeny i hasla NIE sa zapisywane). Kod wyjscia: 0 = OK, 1 = bledy.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
from datetime import datetime, timedelta
from urllib import error as urlerror
from urllib import parse, request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import diagnoza_timescale as dt  # noqa: E402  (shared helpers: Step, out, network, test data)

Step, out = dt.Step, dt.out

HINTS = [
    ("401", "Odmowa dostepu: zly token (v2) albo uzytkownik / haslo (v1). Token musi miec prawo zapisu I odczytu (i usuwania) w buckecie."),
    ("403", "Brak uprawnien. Dla usuwania w v1 (DROP SERIES) konto musi byc administratorem; w v2 token musi miec prawo zapisu do bucketu."),
    ("unauthorized", "Odmowa dostepu: sprawdz token / uzytkownika i haslo."),
    ("bucket", "Nie ma takiego bucketu albo organizacji: sprawdz nazwy (v2) - utworz bucket w InfluxDB."),
    ("organization", "Nie ma takiej organizacji: sprawdz nazwe (v2)."),
    ("database not found", "Nie ma takiej bazy (v1): utworz ja (CREATE DATABASE) albo daj kontu prawo jej tworzenia."),
    ("retention policy", "Baza ma krotka polityke retencji - dane testowe z biezacym czasem powinny przejsc; sprawdz retencje."),
    ("timed out", "Brak odpowiedzi w limicie czasu: firewall / zly adres / port (domyslnie 8086)."),
    ("brak połączenia", "Serwer nie odpowiada: sprawdz adres, port (domyslnie 8086) i zapore."),
    ("getaddrinfo failed", "Nazwa serwera nie jest rozpoznawana (DNS) - uzyj adresu IP."),
    ("syntax", "Serwer odrzucil zapytanie - skladnia zapytania w programie nie pasuje do tej wersji. Wyslij ten plik deweloperowi."),
    ("error parsing query", "Serwer odrzucil zapytanie - skladnia zapytania w programie nie pasuje do tej wersji. Wyslij ten plik deweloperowi."),
]


def hint_for(text: str) -> str:
    low = text.lower()
    for key, h in HINTS:
        if key.lower() in low:
            return h
    return ""


def build_cfg(a, measurement: str):
    from s7trace.core.store import StoreConfig
    kind = f"influx{a.version}"
    return StoreConfig(kind=kind, url=a.url, database=a.db, user=a.user, password=a.password, org=a.org, bucket=a.bucket,
                       token=a.token, measurement=measurement, remember=True, mode="changes", keyframe_min=0.05, batch_s=0.1,
                       close_grace_s=20.0, spool_mb=0)


def server_check(cfg) -> bool:
    from s7trace.core import store
    ok = True
    with Step("adres serwera i wersja") as s:
        req = request.Request(cfg.url.rstrip("/") + ("/ping" if cfg.kind == "influx1" else "/health"))
        try:
            with request.urlopen(req, timeout=cfg.http_timeout_s) as r:
                ver = r.headers.get("X-Influxdb-Version") or r.headers.get("X-Influxdb-Build") or ""
                body = r.read(300).decode("utf-8", "replace")
        except urlerror.HTTPError as e:
            ver, body = e.headers.get("X-Influxdb-Version", ""), f"HTTP {e.code}"
            if e.code >= 500:
                raise
        s.note(f"odpowiedz: {body.strip()[:120]!r}; wersja serwera: {ver or 'nie podana w naglowkach'}")
        want = "1." if cfg.kind == "influx1" else "2."
        if ver and not ver.startswith(("v" + want, want)):
            raise RuntimeError(f"wybrano InfluxDB {cfg.kind[-1]}.x, a serwer podaje wersje {ver} - zly wybor wersji")
    ok &= STEPS_OK()
    with Step("logowanie i prawo zapisu") as s:
        b = store.open_backend(cfg)
        try:
            s.note(b.ping())
            b._write_lp([f"{cfg.measurement}_probe,session=probe v=1 {int(time.time() * 1e9)}"])
            s.note("zapis testowego punktu: OK")
        finally:
            b.close()
    ok &= STEPS_OK()
    return bool(ok)


def STEPS_OK() -> bool:
    return dt.STEPS[-1]["ok"]


def make_sigs():
    from s7trace.core.types import Signal
    return [Signal(name="A", dtype="BOOL"), Signal(name="B", dtype="REAL"), Signal(name="C", dtype="INT"),
            Signal(name="D", dtype="REAL")]


def raw_count(cfg, session: str, meas: str | None = None) -> int:
    """How many points the server still holds for a recording (independent of the program's own read code)."""
    from s7trace.core import store
    b = store.open_backend(cfg)
    m = meas or cfg.measurement
    try:
        if cfg.kind == "influx1":
            res = b._query(f'SELECT count(*) FROM "{m}" WHERE "session"=\'{session}\'', "")
            rows = b._rows(res)
            return sum(int(v) for r in rows for k, v in r.items() if k.startswith("count") and v is not None) if rows else 0
        flux = (f'from(bucket: "{cfg.bucket}") |> range(start: -3650d) |> filter(fn: (r) => r._measurement == "{m}" '
                f'and r.session == "{session}") |> count()')
        return sum(int(float(r["_value"])) for r in b._query("", flux) if r.get("_value") not in (None, ""))
    finally:
        b.close()


def drop_measurements(cfg, names) -> None:
    from s7trace.core import store
    b = store.open_backend(cfg)
    try:
        for m in names:
            if cfg.kind == "influx1":
                b._http("POST", "/query", {"db": cfg.database, "q": f'DROP MEASUREMENT "{m}"'})
            else:
                body = json.dumps({"start": "1970-01-01T00:00:00Z", "stop": "2200-01-01T00:00:00Z",
                                   "predicate": f'_measurement="{m}"'}).encode()
                b._http("POST", "/api/v2/delete", {"org": cfg.org, "bucket": cfg.bucket}, body,
                        {"Content-Type": "application/json"})
    finally:
        b.close()


def full_cycle(cfg, keep: bool, events: int) -> None:
    from s7trace.core import store
    tmp = tempfile.mkdtemp(prefix="s7t_influx_selftest_")
    sigs = make_sigs()
    start = datetime.now().replace(microsecond=0) - timedelta(minutes=10)           # recent: a short retention is no problem
    rows = dt.expected_rows(1200)                                                    # 60 s of data at 50 ms
    meas = cfg.measurement
    old_max = store.MAX_READ_ROWS
    ids: dict[str, str] = {}
    try:
        with Step("zapis nagrania z klatkami kluczowymi (DbRecorder)") as s:
            rec = store.DbRecorder(cfg, sigs, start, {"name": "selftest", "ip": "0.0.0.0", "tab": "T", "conf": "selftest",
                                                      "title": "T0"}, base_dir=tmp)
            for t, v in rows:
                rec.write(t, v)
            rec.close()
            ids["kf"] = rec.session
            s.note(f"zapisano wpisow: {rec.written}, utracono: {rec.dropped}, w kolejce: {rec.q.qsize()}")
            if rec.last_error:
                raise RuntimeError(rec.last_error)
            if rec.written < 40 or rec.dropped:
                raise RuntimeError("nie wszystkie dane trafily do bazy")
        with Step("zapis nagrania BEZ klatek kluczowych (do proby zapytania 'ostatnia wartosc przed zakresem')") as s:
            c2 = type(cfg).from_dict({**cfg.to_dict(), "keyframe_min": 0.0})
            rec = store.DbRecorder(c2, sigs, start, {"name": "selftest2", "conf": "selftest2"}, base_dir=tmp)
            for t, v in rows:
                rec.write(t, v)
            rec.close()
            ids["nokf"] = rec.session
            if rec.last_error or rec.dropped:
                raise RuntimeError(rec.last_error or "utracono dane")
            s.note(f"zapisano wpisow: {rec.written}")
        if len(ids) < 2:
            return
        with Step("odczyt calych nagran i porownanie z zapisanym") as s:
            b = store.open_backend(cfg)
            try:
                listed = {x["id"] for x in b.sessions()}
                if not set(ids.values()) <= listed:
                    raise RuntimeError("nagran nie ma na liscie sesji")
                for key, sid in ids.items():
                    meta, t, m = b.read(sid)
                    bad = dt.check_matrix(t, m, rows)
                    s.note(f"{key}: wierszy {len(t)}, probek rozbieznych z zapisem: {bad} z {len(rows)}")
                    if bad:
                        raise RuntimeError(f"{key}: {bad} probek rozni sie od zapisanych")
            finally:
                b.close()
        with Step("odczyt zakresu czasu: stan sprzed zakresu (z klatek kluczowych i zapytaniem wstecz)") as s:
            b = store.open_backend(cfg)
            try:
                lo, hi = store.to_us(start, 20.0), store.to_us(start, 40.0)
                for key, sid in ids.items():
                    meta, t, m = b.read(sid, lo, hi)
                    cs = sorted(set(m[:, 2].tolist())) if len(t) else []
                    s.note(f"{key}: wierszy {len(t)}, kolumna C (stala) = {cs}")
                    if not len(t) or cs != [7.0]:
                        raise RuntimeError(f"{key}: zakres nie zawiera stanu sprzed zakresu (C powinno byc 7.0 od pierwszego wiersza)")
                    if t[0] < lo or t[-1] > hi:
                        raise RuntimeError(f"{key}: wiersze poza zadanym zakresem")
            finally:
                b.close()
        with Step("odczyt bardzo duzego zakresu w kawalkach (zmniejszanie danych)") as s:
            b = store.open_backend(cfg)
            try:
                big = start - timedelta(hours=4)                      # 4 hours of data, 3000 points, one spike
                b.begin({"id": "selftest_big", "name": "big", "start_us": store.to_us(big, 0), "mode": "all",
                         "signals": [x.to_dict() for x in sigs[:1]], "fields": ["A"]})
                data = [(store.to_us(big, i * 4.8), {0: 5000.0 if i == 1700 else float(i % 9)}) for i in range(3000)]
                for k in range(0, len(data), 1000):
                    b.write(data[k:k + 1000])
                b.end(store.to_us(big, 3000 * 4.8))
                ids["big"] = "selftest_big"
                store.MAX_READ_ROWS = 400
                meta, t, m = b.read("selftest_big", max_points=300)
                s.note(f"odczyt w kawalkach: {len(t)} wierszy z 3000; maksimum {m[:, 0].max()}")
                if not len(t) or len(t) >= 1500 or m[:, 0].max() != 5000.0:
                    raise RuntimeError("odczyt w kawalkach zgubil szpilke albo nie zmniejszyl danych")
            finally:
                store.MAX_READ_ROWS = old_max
                b.close()
        with Step("tytul, uwagi, kosz (punkty o tym samym czasie maja sie scalic)") as s:
            b = store.open_backend(cfg)
            try:
                sid = ids["kf"]
                b.update_session(sid, {"title": "T1", "notes": "uwaga", "tags": "x"})
                lst = [x for x in b.sessions() if x["id"] == sid]
                if len(lst) != 1:
                    raise RuntimeError(f"po zmianie opisu nagranie wystepuje {len(lst)} razy na liscie (powinno 1) - punkty sie nie scalily")
                x = lst[0]
                if (x["title"], x["notes"], x["tags"]) != ("T1", "uwaga", "x"):
                    raise RuntimeError(f"edycja opisu nie zadzialala: {x['title']!r} {x['notes']!r} {x['tags']!r}")
                b.update_session(sid, {"deleted_us": 123})
                if [y for y in b.sessions() if y["id"] == sid][0]["deleted_us"] != 123:
                    raise RuntimeError("znacznik kosza nie zapisal sie")
                b.update_session(sid, {"deleted_us": None})
                x = [y for y in b.sessions() if y["id"] == sid][0]
                if x["deleted_us"]:
                    raise RuntimeError(f"przywrocenie z kosza nie zadzialalo: deleted_us={x['deleted_us']}")
                s.note("opis, kosz i przywracanie: OK, nagranie nadal jedno na liscie, dane nietkniete")
                meta, t, m = b.read(sid)
                if dt.check_matrix(t, m, rows):
                    raise RuntimeError("po zmianie opisu dane nagrania sie zmienily")
            finally:
                b.close()
        with Step("USUWANIE nagrania: znika wskazane, drugie zostaje") as s:
            b = store.open_backend(cfg)
            try:
                victim, keep_id = ids["kf"], ids["nokf"]
                n_keep = raw_count(cfg, keep_id)
                n_victim = raw_count(cfg, victim)
                s.note(f"przed usunieciem: wskazane {n_victim} punktow, drugie {n_keep} punktow (liczone przez serwer)")
                if not n_victim or not n_keep:
                    raise RuntimeError("serwer nie zwraca liczby punktow (zapytanie zliczajace) - nie da sie sprawdzic usuwania")
                t0 = time.time()
                try:
                    b.delete_session(victim)
                except Exception as e:
                    raise RuntimeError(f"serwer odrzucil usuwanie (InfluxDB {cfg.kind[-1]}.x): {e}") from e
                s.note(f"polecenie usuwania: {time.time() - t0:.2f} s")
                if victim in {x["id"] for x in b.sessions()}:
                    raise RuntimeError("usuniete nagranie nadal jest na liscie sesji")
                after = raw_count(cfg, victim)
                after_meta = raw_count(cfg, victim, meas=meas + "_sessions")
                s.note(f"po usunieciu serwer zwraca dla wskazanego: {after} punktow danych, {after_meta} opisu; drugie: {raw_count(cfg, keep_id)}")
                if after or after_meta:
                    raise RuntimeError(f"po usunieciu serwer nadal zwraca {after} punktow danych i {after_meta} opisu tego nagrania")
                if raw_count(cfg, keep_id) != n_keep:
                    raise RuntimeError("usuniecie ZNISZCZYLO punkty drugiego nagrania")
                if keep_id not in {x["id"] for x in b.sessions()}:
                    raise RuntimeError("usuniecie zniszczylo opis drugiego nagrania")
                if cfg.kind == "influx2":
                    s.note("uwaga: v2 oznacza dane jako usuniete od razu, a z dysku znikaja przy kolejnej kompakcji - to normalne")
            finally:
                b.close()
        with Step(f"przepustowosc zapisu ({events} wpisow)") as s:
            b = store.open_backend(cfg)
            try:
                b.begin({"id": "selftest_speed", "name": "speed", "start_us": store.to_us(start, 0), "mode": "all",
                         "signals": [x.to_dict() for x in sigs], "fields": ["A", "B", "C", "D"]})
                data = [(store.to_us(start, 400 + i * 0.001), {0: 1.0, 1: float(i), 2: 7.0, 3: 0.5}) for i in range(events // 4)]
                t0 = time.time()
                for k in range(0, len(data), 5000):
                    b.write(data[k:k + 5000])
                dtm = max(time.time() - t0, 1e-6)
                s.note(f"{events / dtm:,.0f} wpisow/s ({dtm:.2f} s) - potrzeba zwykle ponizej 1 000 wpisow/s")
            finally:
                b.close()
    finally:
        store.MAX_READ_ROWS = old_max
        if not keep:
            with Step("sprzatanie (usuniecie danych testowych)") as s:
                drop_measurements(cfg, [meas, meas + "_sessions", meas + "_probe"])
                s.note(f"usunieto pomiary {meas}, {meas}_sessions, {meas}_probe")
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", type=int, choices=(1, 2))
    ap.add_argument("--url")
    ap.add_argument("--db", help="InfluxDB 1.x: baza")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default=None)
    ap.add_argument("--org", help="InfluxDB 2.x: organizacja")
    ap.add_argument("--bucket", help="InfluxDB 2.x: bucket")
    ap.add_argument("--token", default=None)
    ap.add_argument("--measurement", default=None)
    ap.add_argument("--events", type=int, default=20000)
    ap.add_argument("--keep", action="store_true", help="nie usuwaj danych testowych")
    ap.add_argument("--no-server", action="store_true", help="tylko kroki bez serwera")
    ap.add_argument("--report", default=os.path.join(dt.ROOT, "diagnoza_influx"))
    a = ap.parse_args(argv)

    dt.STEPS.clear()
    dt.LINES.clear()
    out("=== S7Trace - test InfluxDB 1.x / 2.x ===")
    out(f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}   komputer: {platform.node()}")
    dt.environment()
    if not a.no_server:
        interactive = a.version is None
        a.version = a.version or int(dt.ask("Wersja InfluxDB (1 lub 2)", "2"))
        a.url = a.url or dt.ask("Adres serwera (URL)", "http://127.0.0.1:8086")
        if a.version == 1:
            a.db = a.db or dt.ask("Baza (database)", "s7trace")
            a.user = a.user or dt.ask("Uzytkownik (puste = bez logowania)", "")
            if a.user and a.password is None:
                a.password = dt.ask("Haslo (nie bedzie widoczne ani zapisane)", "", secret=True) if interactive else ""
            a.org, a.bucket, a.token = a.org or "", a.bucket or "", a.token or ""
        else:
            a.org = a.org or dt.ask("Organizacja (org)", "")
            a.bucket = a.bucket or dt.ask("Bucket", "s7trace")
            if a.token is None:
                a.token = os.environ.get("INFLUX_TOKEN") or (dt.ask("Token (nie bedzie widoczny ani zapisany)", "", secret=True)
                                                              if interactive else "")
            a.db = a.db or ""
        a.password = a.password or ""
        meas = a.measurement or "s7trace_selftest_" + os.urandom(3).hex()
        cfg = build_cfg(a, meas)
        pu = parse.urlparse(cfg.url)
        out(f"Serwer: {cfg.url}  wersja: {a.version}.x  " + (f"baza: {a.db}" if a.version == 1 else f"org: {a.org}  bucket: {a.bucket}")
            + f"  pomiar testowy: {meas}")
        out("== 3. Siec i serwer")
        if dt.network(pu.hostname or "127.0.0.1", pu.port or (443 if pu.scheme == "https" else 8086), 5.0):
            if server_check(cfg):
                out("== 4. Pelny cykl przez kod programu")
                full_cycle(cfg, a.keep, a.events)
            else:
                out("  (pelny cykl pominiety: nie ma polaczenia / uprawnien)")
        else:
            out("  Serwer nieosiagalny - kroki z serwerem pominiete.")

    failed = [x for x in dt.STEPS if not x["ok"]]
    out("")
    out("=== PODSUMOWANIE ===")
    out(f"Krokow: {len(dt.STEPS)}, bledow: {len(failed)}")
    for x in failed:
        out(f"- {x['step']}: {x['error']}")
        h = hint_for(x["error"])
        if h:
            out(f"    wskazowka: {h}")
    if failed:
        out("")
        out("=== SZCZEGOLY BLEDOW (traceback) ===")
        for x in failed:
            out(f"--- {x['step']}")
            out(x["traceback"].rstrip())
    else:
        out("Wszystko dziala.")
    with open(a.report + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(dt.LINES) + "\n")
    with open(a.report + ".json", "w", encoding="utf-8") as f:
        json.dump({"date": datetime.now().isoformat(timespec="seconds"), "host": platform.node(),
                   "platform": platform.platform(), "python": sys.version, "steps": dt.STEPS}, f, ensure_ascii=False, indent=1)
    out(f"Raport: {a.report}.txt  (oraz .json)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
