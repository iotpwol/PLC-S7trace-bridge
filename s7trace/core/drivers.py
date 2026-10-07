"""Communication drivers other than S7comm: OPC UA, Siemens Web API (JSON-RPC) and Modbus TCP.

Every driver has the interface of the snap7 client used by Acquirer: connect(host, rack, slot, port), disconnect(),
plus read(signals) -> list[float] (NaN = not readable). Optional libraries are imported lazily."""
from __future__ import annotations

import json
import socket
import ssl
import struct
import urllib.request
from datetime import datetime, timezone

from .types import Signal

CONN_TYPES = [("auto", "Automatycznie (rozpoznaj)"), ("s7", "S7comm (snap7, PUT/GET)"), ("opcua", "OPC UA"),
              ("webapi", "Web API (S7-1500 / S7-1200)"), ("modbus", "Modbus TCP")]
CONN_LABEL = dict(CONN_TYPES)
SOURCE_OF = {"s7": ("I", "Q", "M", "DB"), "opcua": ("OPC",), "webapi": ("WEB",), "modbus": ("MBH", "MBI", "MBC", "MBD")}


def conn_defaults() -> dict:
    return {"opcua_port": 4840, "opcua_security": "None", "opcua_anonymous": True, "username": "", "password": "",
            "remember_password": False, "cert": "", "key": "", "web_port": 443, "web_https": True,
            "web_verify": False, "modbus_port": 502, "modbus_unit": 1, "modbus_wordswap": False}


def family_of(signals: list[Signal]) -> str | None:
    """'s7' / 'opcua' / 'webapi' / 'modbus' when all fetched signals use one family of sources, else None."""
    fams = {k for s in signals if s.enabled for k, srcs in SOURCE_OF.items() if s.source in srcs}
    return fams.pop() if len(fams) == 1 else None


class DriverError(Exception):
    pass


def _num(v) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return float(v)


# --------------------------------------------------------------------------- Modbus TCP
_FC = {"MBH": 3, "MBI": 4, "MBC": 1, "MBD": 2}
_MB_EXC = {1: "niedozwolona funkcja", 2: "niedozwolony adres", 3: "niedozwolona wartość", 4: "błąd urządzenia",
           6: "urządzenie zajęte", 11: "brak odpowiedzi bramki"}


class ModbusDriver:
    def __init__(self, opts: dict):
        self.o = opts
        self.sock: socket.socket | None = None
        self.tid = 0

    def connect(self, host, rack=0, slot=0, port=0):
        self.sock = socket.create_connection((host, int(self.o.get("modbus_port", 502))), timeout=3)
        self.sock.settimeout(3)

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _recv(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise DriverError("połączenie zamknięte przez urządzenie")
            buf += chunk
        return buf

    def request(self, unit: int, fc: int, addr: int, qty: int) -> bytes:
        self.tid = (self.tid + 1) & 0xFFFF
        self.sock.sendall(struct.pack(">HHHBBHH", self.tid, 0, 6, unit, fc, addr, qty))
        h = self._recv(7)
        ln = struct.unpack(">H", h[4:6])[0]
        body = self._recv(ln - 1)
        if body[0] & 0x80:
            raise DriverError(f"wyjątek Modbus {body[1]}: {_MB_EXC.get(body[1], '?')}")
        return body[2:]                                  # skip fc + byte count

    def read(self, signals: list[Signal]) -> list[float]:
        out = []
        for s in signals:
            unit = s.db or int(self.o.get("modbus_unit", 1))
            if s.source in ("MBC", "MBD"):
                out.append(float(self.request(unit, _FC[s.source], s.byte, 1)[0] & 1))
                continue
            regs = max(s.size // 2, 1)
            data = self.request(unit, _FC[s.source], s.byte, regs)
            if self.o.get("modbus_wordswap") and regs > 1:
                words = [data[i:i + 2] for i in range(0, len(data), 2)]
                data = b"".join(reversed(words))
            if s.dtype == "BOOL":
                out.append(float((struct.unpack(">H", data[:2])[0] >> s.bit) & 1))
            elif s.size == 1:
                out.append(s.decode(data[1:2] if s.dtype != "BYTE" else data[1:2]))
            else:
                out.append(s.decode(data))
        return out


# --------------------------------------------------------------------------------- OPC UA
class OpcUaDriver:
    def __init__(self, opts: dict):
        self.o = opts
        self.client = None
        self.nodes: dict[str, object] = {}

    def connect(self, host, rack=0, slot=0, port=0):
        from asyncua.sync import Client            # lazy: optional dependency
        from .opcua_loop import make_daemon
        make_daemon()
        o = self.o
        self.client = Client(f"opc.tcp://{host}:{int(o.get('opcua_port', 4840))}", timeout=5)
        if not o.get("opcua_anonymous", True) and o.get("username"):
            self.client.set_user(o["username"])
            self.client.set_password(o.get("password", ""))
        sec = o.get("opcua_security", "None")
        if sec != "None":
            if not (o.get("cert") and o.get("key")):
                raise DriverError("tryb zabezpieczony OPC UA wymaga certyfikatu i klucza klienta (Ustawienia → Metoda połączenia)")
            self.client.set_security_string(f"{sec},{o.get('cert')},{o.get('key')}")
        self.client.connect()

    def disconnect(self):
        if self.client is not None:
            try:
                self.client.disconnect()
            finally:
                self.client = None
                self.nodes.clear()

    def read(self, signals: list[Signal]) -> list[float]:
        nodes = []
        for s in signals:
            if s.node not in self.nodes:
                self.nodes[s.node] = self.client.get_node(s.node)
            nodes.append(self.nodes[s.node])
        return [_num(v) for v in self.client.read_values(nodes)]


def generate_client_cert(folder: str, host_uri: str = "urn:s7trace:client", days: int = 3650) -> tuple[str, str]:
    """Self-signed OPC UA client certificate (DER) + private key (PEM); returns (cert_path, key_path)."""
    import os
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "S7Trace OPC UA client")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now)
            .not_valid_after(now.replace(year=now.year + max(days // 365, 1)))
            .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(host_uri),
                                                        x509.DNSName(socket.gethostname())]), critical=False)
            .add_extension(x509.KeyUsage(True, True, True, True, True, False, False, False, False), critical=True)
            .sign(key, hashes.SHA256()))
    os.makedirs(folder, exist_ok=True)
    cp, kp = os.path.join(folder, "s7trace_client.der"), os.path.join(folder, "s7trace_client_key.pem")
    with open(cp, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.DER))
    with open(kp, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    return cp, kp


# -------------------------------------------------------------------- Siemens Web API (JSON-RPC)
class WebApiDriver:
    """S7-1500 / S7-1200 'Web API' (JSON-RPC over HTTP(S), /api/jsonrpc). Untested on real hardware."""

    def __init__(self, opts: dict):
        self.o = opts
        self.url = ""
        self.token = ""
        self._id = 0
        self.ctx = None

    def connect(self, host, rack=0, slot=0, port=0):
        o = self.o
        https = o.get("web_https", True)
        self.url = f"{'https' if https else 'http'}://{host}:{int(o.get('web_port', 443 if https else 80))}/api/jsonrpc"
        if https and not o.get("web_verify", False):
            self.ctx = ssl._create_unverified_context()          # PLCs use self-signed certificates
        if o.get("username"):
            res = self.call("Api.Login", {"user": o["username"], "password": o.get("password", "")})
            self.token = (res or {}).get("token", "")
        else:
            self.call("Api.Version")

    def disconnect(self):
        if self.token:
            try:
                self.call("Api.Logout")
            except Exception:
                pass
        self.token = ""

    def call(self, method: str, params: dict | None = None):
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method, "id": self._id}
        if params is not None:
            body["params"] = params
        return self._post(body)

    def _post(self, body):
        req = urllib.request.Request(self.url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        if self.token:
            req.add_header("X-Auth-Token", self.token)
        with urllib.request.urlopen(req, timeout=4, context=self.ctx) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        items = data if isinstance(data, list) else [data]
        for it in items:
            if "error" in it:
                e = it["error"]
                raise DriverError(f"Web API: {e.get('message', e)} ({e.get('code', '')})")
        return data if isinstance(data, list) else data.get("result")

    def read(self, signals: list[Signal]) -> list[float]:
        batch = [{"jsonrpc": "2.0", "method": "PlcProgram.Read", "id": i + 1, "params": {"var": s.node, "mode": "simple"}}
                 for i, s in enumerate(signals)]
        res = self._post(batch)
        by_id = {r["id"]: r for r in res}
        return [_num(by_id[i + 1]["result"]) for i in range(len(signals))]


def create_driver(kind: str, opts: dict):
    return {"opcua": OpcUaDriver, "webapi": WebApiDriver, "modbus": ModbusDriver}[kind](opts)
