"""Connection wizard backend: recognises which way of reading a Siemens PLC works and collects device data.

Order of the automatic mode: S7comm -> OPC UA -> Web API -> Modbus TCP. No test changes anything in the PLC
(read-only: identification, state, clock and one-byte test reads)."""
from __future__ import annotations

import json
import socket
import ssl
import struct
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from . import diagnostics as dg
from .drivers import CONN_LABEL, conn_defaults

ORDER = ["s7", "opcua", "webapi", "modbus"]
PORTS = {"s7": 102, "opcua": 4840, "webapi": 443, "modbus": 502}

# ---------------------------------------------------------------- limitations (shown in the wizard and in the help)
LIMITS = {
    "s7": ["S7-1200/1500: w TIA Portal włącz „Permit access with PUT/GET communication from remote partner” "
           "(właściwości CPU → Protection & Security → Connection mechanisms) i poziom ochrony „Full access” bez hasła "
           "lub z hasłem dla PUT/GET.",
           "Bloki DB muszą mieć wyłączone „Optimized block access” (adresowanie bezwzględne); zmienne zoptymalizowane są niedostępne.",
           "S7-300/400 zwykle działają bez zmian (chyba że CPU ma ochronę hasłem poziomu 2/3).",
           "Zabezpieczenie systemowe: PUT/GET obniża bezpieczeństwo (każdy w sieci może czytać i zapisywać pamięć) – używaj tylko w sieci zaufanej."],
    "opcua": ["Serwer OPC UA w CPU musi być włączony (S7-1500; S7-1200 od nowszego firmware) i zwykle wymaga licencji runtime w CPU.",
              "Zmienne muszą być udostępnione (DB: „Accessible from HMI/OPC UA”), a uprawnienia użytkownika dopuszczać odczyt.",
              "Tryb zabezpieczony wymaga zaufania do certyfikatu klienta po stronie CPU (TIA: Server → Security → Trusted clients) "
              "lub dostępu gościa (anonimowego) / użytkownika z hasłem.",
              "Wymaga biblioteki asyncua (jest w pakiecie). Próbkowanie wolniejsze niż S7comm (zwykle kilkadziesiąt ms)."],
    "webapi": ["S7-1500 (nowsze firmware) i S7-1200 (nowsze firmware): włącz serwer WWW i Web API w CPU oraz użytkownika z prawem odczytu.",
               "Zwykle HTTPS z certyfikatem samopodpisanym (program domyślnie go akceptuje). Najwolniejsza metoda.",
               "Implementacja nie była testowana na prawdziwym sterowniku – traktuj jako eksperymentalną."],
    "modbus": ["Program PLC musi udostępniać dane przez serwer Modbus TCP (np. blok MB_SERVER) – nie ma dostępu do zmiennych po nazwie, "
               "tylko do rejestrów i cewek po numerze.",
               "Adresy rejestrów ustalasz w programie PLC; zmienne trzeba mapować ręcznie."],
}
SYSTEM_LIMITS = [
    "Wymagane są uprawnienia sieciowe: zapora Windows nie może blokować wychodzących połączeń na porty 102, 4840, 443/80, 502.",
    "Ping (ICMP) może być zablokowany w sieci – brak odpowiedzi na ping nie oznacza braku komunikacji.",
    "Routing / VPN: sterownik musi być osiągalny po IPv4 (routing S7 przez CP/CPU nie jest obsługiwany, tylko zwykły routing IP).",
    "Liczba jednoczesnych połączeń S7 w CPU jest ograniczona (S7-1200: kilka) – test zajmuje jedno połączenie na ułamek sekundy.",
    "Program nie obchodzi zabezpieczeń: nie włączy PUT/GET ani OPC UA zdalnie, nie łamie haseł i nie zna licencji CPU.",
    "Czas sterownika jest porównywany z czasem systemowym tego komputera; sterowniki Siemensa często pracują w UTC – "
    "podawane są obie różnice (względem czasu lokalnego i UTC).",
]


@dataclass
class Step:
    key: str                     # ping / port-s7 / s7 / opcua / webapi / modbus
    title: str
    status: str = "skip"         # ok / fail / warn / skip
    detail: str = ""
    ms: float = 0.0


@dataclass
class DetectResult:
    host: str = ""
    steps: list = field(default_factory=list)
    methods: dict = field(default_factory=dict)      # method -> {"ok": bool, "note": str}
    info: dict = field(default_factory=dict)         # device data (model, order number, firmware, serial, state, ...)
    plc_time: datetime | None = None
    plc_time_utc: bool = False
    time_diff_local: float | None = None
    time_diff_utc: float | None = None
    recommended: str | None = None
    advice: list = field(default_factory=list)
    rack: int = 0
    slot: int = 2

    def step(self, key: str) -> Step | None:
        return next((s for s in self.steps if s.key == key), None)


def split_host(text: str) -> tuple[str, int | None]:
    t = text.strip()
    if t.count(":") == 1:
        h, p = t.split(":")
        return h, int(p)
    return t, None


def _note_time(res: DetectResult, t: datetime, utc: bool = False) -> None:
    """Remember the PLC clock and its difference to this computer's clock (local and UTC)."""
    if res.plc_time is not None:
        return
    res.plc_time, res.plc_time_utc = t, utc
    if t.tzinfo is not None:
        res.time_diff_utc = (t - datetime.now(timezone.utc)).total_seconds()
        res.time_diff_local = res.time_diff_utc
    else:
        res.time_diff_local = (t - datetime.now()).total_seconds()
        res.time_diff_utc = (t - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()


# ----------------------------------------------------------------------------- S7comm
def _classify(err: str) -> str:
    e = err.lower()
    if any(k in e for k in ("function not available", "refused", "not permitted", "access denied", "function")):
        return "denied"
    if any(k in e for k in ("item not available", "address out of range", "object does not exist", "invalid address")):
        return "range"
    return "other"


def probe_s7(host: str, port: int, rack: int, slot: int, res: DetectResult) -> Step:
    t0 = time.perf_counter()
    st = Step("s7", "S7comm (port 102)")
    try:
        import snap7
        from snap7.type import Area, Block
    except Exception as e:
        st.status, st.detail = "fail", f"brak biblioteki snap7: {e}"
        res.methods["s7"] = {"ok": False, "note": st.detail}
        return st
    client, used, last_err = None, None, ""
    for r, s in [(rack, slot)] + [c for c in ((0, 1), (0, 2), (0, 0), (1, 2), (0, 3)) if c != (rack, slot)]:
        c = snap7.client.Client()
        try:
            c.connect(host, r, s, port)
            client, used = c, (r, s)
            break
        except Exception as e:
            last_err = str(e)
            try:
                c.disconnect()
            except Exception:
                pass
    if client is None:
        st.status, st.detail = "fail", f"nie można nawiązać połączenia S7 (próbowano rack/slot 0/1, 0/2, 0/0, 1/2, 0/3): {last_err}"
        st.ms = (time.perf_counter() - t0) * 1000
        res.methods["s7"] = {"ok": False, "note": "port 102 nie odpowiada lub CPU odrzuca połączenie"}
        return st
    res.rack, res.slot = used
    info = res.info
    notes = []

    def attempt(label, fn):
        try:
            return fn()
        except Exception as e:                                           # many functions are optional on 1200/1500
            notes.append(f"{label}: {e}")
            return None

    ci = attempt("informacje o CPU", client.get_cpu_info)
    if ci is not None:
        def txt(v):
            return v.decode("ascii", "ignore").strip("\x00 ") if isinstance(v, (bytes, bytearray)) else str(v)
        info.update(model=txt(ci.ModuleTypeName), serial=txt(ci.SerialNumber), plc_name=txt(ci.ASName),
                    module_name=txt(ci.ModuleName), copyright=txt(ci.Copyright))
    oc = attempt("numer katalogowy", client.get_order_code)
    if oc is not None:
        info["order_code"] = (oc.OrderCode.decode("ascii", "ignore") if isinstance(oc.OrderCode, (bytes, bytearray))
                              else str(oc.OrderCode)).strip("\x00 ")
        info["firmware"] = f"V{oc.V1}.{oc.V2}.{oc.V3}"
    info["state"] = attempt("stan CPU", client.get_cpu_state) or info.get("state", "")
    pr = attempt("poziom ochrony", client.get_protection)
    if pr is not None:
        info["protection"] = f"poziom ochrony CPU: {pr.sch_schal} (przełącznik: {pr.sch_par}, hasło: {pr.anl_sch})"
    pdu = attempt("PDU", client.get_pdu_length)
    if pdu:
        info["pdu"] = pdu
    t = attempt("czas sterownika", client.get_plc_datetime)
    if t is not None:
        _note_time(res, t)
    family = _family(info.get("model", ""), info.get("order_code", ""))
    if family:
        info["family"] = family

    # data access test: one byte of the M area (never optimized) and a few DBs
    access, detail = "unknown", ""
    try:
        client.read_area(Area.MK, 0, 0, 1)
        access = "ok"
    except Exception as e:
        access, detail = _classify(str(e)), str(e)
    dbs_ok = dbs_bad = 0
    if access == "ok":
        nums = attempt("lista DB", lambda: client.list_blocks_of_type(Block.DB, 20)) or []
        for n in list(nums)[:8]:
            try:
                client.read_area(Area.DB, n, 0, 1)
                dbs_ok += 1
            except Exception:
                dbs_bad += 1
    info["s7_access"], info["dbs_ok"], info["dbs_bad"] = access, dbs_ok, dbs_bad
    try:
        client.disconnect()
    except Exception:
        pass
    st.ms = (time.perf_counter() - t0) * 1000
    where = f"rack {used[0]} / slot {used[1]}"
    if access == "ok":
        st.status = "ok"
        st.detail = f"połączono ({where}), odczyt pamięci bezwzględnej działa"
        if dbs_bad:
            st.status = "warn"
            st.detail += f"; {dbs_bad} z {dbs_ok + dbs_bad} sprawdzonych DB nie daje się czytać (prawdopodobnie „Optimized block access”)"
        res.methods["s7"] = {"ok": True, "note": st.detail}
    else:
        st.status = "warn"
        why = {"denied": "CPU odmawia dostępu – PUT/GET jest najpewniej wyłączony lub ochrona wyższego poziomu",
               "range": "adres niedostępny – dane są zoptymalizowane lub poza zakresem",
               "other": "odczyt testowy nie powiódł się"}[access]
        st.detail = f"połączono ({where}), ale {why} ({detail})"
        res.methods["s7"] = {"ok": False, "note": why}
    if notes:
        st.detail += " | informacje pominięte: " + "; ".join(notes[:2])
    return st


def _family(model: str, order: str) -> str:
    s = f"{model} {order}".upper()
    for key, name in (("6ES7 5", "S7-1500"), ("6ES7 51", "S7-1500"), ("CPU 15", "S7-1500"), ("CPU 12", "S7-1200"),
                      ("6ES7 21", "S7-1200"), ("CPU 31", "S7-300"), ("6ES7 31", "S7-300"), ("CPU 41", "S7-400"),
                      ("6ES7 41", "S7-400")):
        if key in s:
            return name
    return ""


# ---------------------------------------------------------------------------- OPC UA
def probe_opcua(host: str, opts: dict, res: DetectResult) -> Step:
    t0 = time.perf_counter()
    port = int(opts.get("opcua_port", 4840))
    st = Step("opcua", f"OPC UA (port {port})")
    try:
        from asyncua.sync import Client
    except Exception as e:
        st.status, st.detail = "fail", f"brak biblioteki asyncua: {e}"
        res.methods["opcua"] = {"ok": False, "note": st.detail}
        return st
    url = f"opc.tcp://{host}:{port}"
    try:
        c = Client(url, timeout=4)
        eps = c.connect_and_get_server_endpoints()
    except Exception as e:
        st.status, st.detail = "fail", f"serwer OPC UA nie odpowiada: {e}"
        st.ms = (time.perf_counter() - t0) * 1000
        res.methods["opcua"] = {"ok": False, "note": "serwer OPC UA wyłączony, brak licencji lub port zablokowany"}
        return st
    pol = sorted({str(e.SecurityPolicyUri).rsplit("#", 1)[-1] for e in eps})
    toks = sorted({str(t.TokenType).rsplit(".", 1)[-1] for e in eps for t in (e.UserIdentityTokens or [])})
    res.info["opcua_policies"], res.info["opcua_tokens"] = pol, toks
    detail = f"serwer odpowiada; polityki: {', '.join(pol) or '?'}; uwierzytelnianie: {', '.join(toks) or '?'}"
    ok = False
    try:
        c2 = Client(url, timeout=4)
        if not opts.get("opcua_anonymous", True) and opts.get("username"):
            c2.set_user(opts["username"])
            c2.set_password(opts.get("password", ""))
        c2.connect()
        try:
            for key, nid in (("opcua_product", "i=2261"), ("opcua_version", "i=2264")):
                try:
                    res.info[key] = str(c2.get_node(nid).read_value())
                except Exception:
                    pass
            try:
                _note_time(res, c2.get_node("i=2258").read_value().replace(tzinfo=timezone.utc), utc=True)
            except Exception:
                pass
            ok = True
        finally:
            c2.disconnect()
        detail += "; sesja bez zabezpieczeń nawiązana"
    except Exception as e:
        detail += f"; logowanie nie powiodło się ({e}) – podaj użytkownika/hasło lub certyfikat w Ustawienia → Metoda połączenia"
    st.status = "ok" if ok else "warn"
    st.detail, st.ms = detail, (time.perf_counter() - t0) * 1000
    res.methods["opcua"] = {"ok": ok, "note": detail}
    return st


# ---------------------------------------------------------------------------- Web API
def probe_webapi(host: str, opts: dict, res: DetectResult) -> Step:
    t0 = time.perf_counter()
    st = Step("webapi", "Web API (HTTPS/HTTP)")
    last = ""
    for https in ([opts.get("web_https", True)] + [not opts.get("web_https", True)]):
        port = int(opts.get("web_port", 443)) if https == opts.get("web_https", True) else (443 if https else 80)
        url = f"{'https' if https else 'http'}://{host}:{port}/api/jsonrpc"
        try:
            ctx = ssl._create_unverified_context() if https else None
            body = json.dumps({"jsonrpc": "2.0", "method": "Api.Version", "id": 1}).encode()
            req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3, context=ctx) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            if "result" not in data:
                last = f"odpowiedź bez wyniku: {data.get('error', data)}"
                continue
            res.info["webapi_version"] = str(data["result"])
            st.status, st.detail = "ok", f"Web API odpowiada ({url}), wersja: {data['result']}"
            res.methods["webapi"] = {"ok": True, "note": st.detail}
            st.ms = (time.perf_counter() - t0) * 1000
            return st
        except Exception as e:
            last = str(e)
    st.status, st.detail = "fail", f"brak odpowiedzi Web API: {last}"
    st.ms = (time.perf_counter() - t0) * 1000
    res.methods["webapi"] = {"ok": False, "note": "Web API wyłączone lub niedostępne w tym sterowniku"}
    return st


# ---------------------------------------------------------------------------- Modbus
def probe_modbus(host: str, opts: dict, res: DetectResult) -> Step:
    t0 = time.perf_counter()
    port = int(opts.get("modbus_port", 502))
    st = Step("modbus", f"Modbus TCP (port {port})")
    try:
        with socket.create_connection((host, port), timeout=2) as s:
            s.settimeout(2)
            s.sendall(struct.pack(">HHHBBHH", 1, 0, 6, int(opts.get("modbus_unit", 1)), 3, 0, 1))
            resp = s.recv(16)
        ok = len(resp) >= 8 and resp[2:4] == b"\x00\x00"
        exc = bool(ok and resp[7] & 0x80)
        st.status = "ok" if ok else "warn"
        st.detail = ("serwer Modbus odpowiada" + (f" (wyjątek {resp[8]} dla rejestru 0 – to normalne, gdy adres nie jest udostępniony)"
                                                   if exc else "")) if ok else "port otwarty, ale odpowiedź nie jest ramką Modbus"
    except Exception as e:
        st.status, st.detail = "fail", f"brak serwera Modbus: {e}"
    st.ms = (time.perf_counter() - t0) * 1000
    res.methods["modbus"] = {"ok": st.status == "ok", "note": st.detail}
    return st


# ---------------------------------------------------------------------------- orchestration
def recommend(res: DetectResult, allowed: list[str] | None = None) -> None:
    """Fills res.recommended and res.advice from the method results (order: S7comm, OPC UA, Web API, Modbus)."""
    allowed = allowed or ORDER
    res.recommended = next((m for m in ORDER if m in allowed and res.methods.get(m, {}).get("ok")), None)
    adv = res.advice
    s7 = res.methods.get("s7")
    ping, p102 = res.step("ping"), res.step("port-s7")
    if res.recommended:
        adv.append(f"Zalecana metoda: {CONN_LABEL[res.recommended]}.")
        s7i = res.info
        if res.recommended != "s7" and s7 is not None and not s7["ok"] and s7i.get("s7_access"):
            adv.append("S7comm łączy się, ale nie czyta pamięci – metoda zapasowa jest wolniejsza; "
                       "aby użyć szybszego S7comm: " + LIMITS["s7"][0])
        return
    if p102 is not None and p102.status == "fail" and not any(res.methods.get(m, {}).get("ok") for m in ORDER):
        if ping is not None and ping.status == "fail":
            adv.append("Sterownik nie odpowiada na ping ani na porty usług. Sprawdź adres IP, kabel, routing/VPN i zaporę.")
        else:
            adv.append("Sterownik odpowiada w sieci, ale żaden port usługi (102, 4840, 443, 502) nie jest dostępny – "
                       "zapora/router blokuje porty albo usługi w CPU są wyłączone.")
    sug = None
    info = res.info
    if s7 is not None and info.get("s7_access") in ("denied", "range"):
        sug = "opcua" if info.get("family") in ("S7-1500", "S7-1200", "") else "s7"
        adv.append("Sugerowana metoda: " + ("włącz PUT/GET (szybki S7comm) albo OPC UA." if sug == "opcua" else CONN_LABEL[sug]))
        adv += ["S7comm: " + t for t in LIMITS["s7"][:2]]
    elif not any(m["ok"] for m in res.methods.values()):
        adv.append("Nie wykryto działającej metody komunikacji. Najczęstsze przyczyny: błędny adres IP/rack/slot, "
                   "wyłączone PUT/GET i brak serwera OPC UA, blokada zapory.")
        adv += ["S7comm: " + LIMITS["s7"][0], "OPC UA: " + LIMITS["opcua"][0]]
    res.recommended = None


def run_detection(host_text: str, opts: dict | None = None, rack: int = 0, slot: int = 2,
                  methods: list[str] | None = None, stop_at_first: bool = False,
                  progress: Callable[[Step], None] | None = None, cancel: threading.Event | None = None,
                  ping_runner: Callable[[str], float | None] | None = None) -> DetectResult:
    """Runs the probes (all, or until the first working one) and returns the full report."""
    opts = {**conn_defaults(), **(opts or {})}
    host, port = split_host(host_text)
    res = DetectResult(host=host, rack=rack, slot=slot)
    methods = methods or ORDER
    emit = progress or (lambda s: None)

    def add(st: Step):
        res.steps.append(st)
        emit(st)

    t0 = time.perf_counter()
    try:
        rtt = (ping_runner or dg.system_ping)(host)
        add(Step("ping", "Ping ICMP", "ok" if rtt is not None else "warn",
                 f"odpowiedź {rtt:.1f} ms" if rtt is not None else "brak odpowiedzi (ICMP może być zablokowany)",
                 (time.perf_counter() - t0) * 1000))
    except Exception as e:
        add(Step("ping", "Ping ICMP", "warn", str(e)))
    ports = {"s7": port or PORTS["s7"], "opcua": int(opts["opcua_port"]), "webapi": int(opts["web_port"]),
             "modbus": int(opts["modbus_port"])}
    open_ports = {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(methods)) as ex:         # all ports at once: closed ports time out in parallel
        futs = {m: ex.submit(dg.tcp_probe, host, ports[m], 1.5) for m in methods}
        for m in methods:
            ok, ms, err = futs[m].result()
            open_ports[m] = ok
            add(Step(f"port-{m}", f"Port TCP {ports[m]} ({CONN_LABEL[m].split(' (')[0]})", "ok" if ok else "fail",
                     f"otwarty, {ms:.1f} ms" if ok else f"zamknięty / brak odpowiedzi ({err})", ms))
    probes = {"s7": lambda: probe_s7(host, ports["s7"], rack, slot, res), "opcua": lambda: probe_opcua(host, opts, res),
              "webapi": lambda: probe_webapi(host, opts, res), "modbus": lambda: probe_modbus(host, opts, res)}
    for m in methods:
        if cancel is not None and cancel.is_set():
            return res
        if not open_ports.get(m):
            res.methods[m] = {"ok": False, "note": "port zamknięty"}
            add(Step(m, CONN_LABEL[m], "skip", "pominięto – port zamknięty"))
            continue
        try:
            add(probes[m]())
        except Exception as e:
            res.methods[m] = {"ok": False, "note": str(e)}
            add(Step(m, CONN_LABEL[m], "fail", f"błąd testu: {e}"))
        if stop_at_first and res.methods.get(m, {}).get("ok"):
            break
    recommend(res, methods)
    return res


def format_result(res: DetectResult) -> str:
    L = [f"Raport kreatora połączenia – {res.host} – {datetime.now():%Y-%m-%d %H:%M:%S}", ""]
    for s in res.steps:
        L.append(f"[{ {'ok': 'OK', 'fail': 'BŁĄD', 'warn': 'UWAGA', 'skip': '—'}[s.status] }] {s.title}: {s.detail}")
    L += ["", "Zalecana metoda: " + (CONN_LABEL[res.recommended] if res.recommended else "brak (patrz zalecenia)")]
    L += [f" - {a}" for a in res.advice]
    if res.info:
        L += ["", "Dane sterownika:"] + [f"  {k}: {v}" for k, v in res.info.items()]
    if res.plc_time:
        L.append(f"Czas sterownika: {res.plc_time:%Y-%m-%d %H:%M:%S}; różnica do czasu lokalnego {res.time_diff_local:+.1f} s, "
                 f"do UTC {res.time_diff_utc:+.1f} s")
    return "\n".join(L) + "\n"
