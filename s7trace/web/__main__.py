"""Command line of the web server:  python -m s7trace.web --config <config.json> [--host 0.0.0.0] [--port 8080] ..."""
from __future__ import annotations

import argparse
import datetime
import getpass
import os
import sys
import time

from ..core.config import data_dir
from .auth import AuthError
from .hosted import HostManager
from .server import App, WebServer


def self_signed_cert(folder: str, host: str = "localhost") -> tuple[str, str]:
    """A self-signed certificate (created once, kept in `folder`) - the browser asks to trust it at the first visit."""
    cert, key = os.path.join(folder, "web_cert.pem"), os.path.join(folder, "web_key.pem")
    if os.path.isfile(cert) and os.path.isfile(key):
        return cert, key
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host or "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
         .not_valid_after(now + datetime.timedelta(days=3650))
         .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.DNSName(host or "localhost")]), False)
         .sign(k, hashes.SHA256()))
    os.makedirs(folder, exist_ok=True)
    with open(key, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                serialization.NoEncryption()))
    with open(cert, "wb") as f:
        f.write(c.public_bytes(serialization.Encoding.PEM))
    return cert, key


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="s7trace.web", description="S7Trace - serwer trybu Web")
    p.add_argument("--config", action="append", default=[], help="plik konfiguracji S7Trace (każda zakładka = jedno połączenie); można podać kilka razy")
    p.add_argument("--host", default="127.0.0.1", help="adres nasłuchu (0.0.0.0 = wszystkie interfejsy; domyślnie tylko ten komputer)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--data", default="", help="folder danych serwera (konta, certyfikat); domyślnie <Dokumenty>\\S7Trace\\web")
    p.add_argument("--tls", action="store_true", help="HTTPS z certyfikatem samopodpisanym")
    p.add_argument("--cert", default="", help="własny certyfikat PEM (z --key) zamiast samopodpisanego")
    p.add_argument("--key", default="")
    p.add_argument("--sso", action="store_true", help="logowanie kontem Windows bez hasła (Negotiate / Kerberos / NTLM, tylko Windows)")
    p.add_argument("--autostart", action="store_true", help="uruchom wszystkie połączenia od razu")
    p.add_argument("--add-user", metavar="NAZWA", help="dodaj konto administratora (hasło zostanie zapytane) i zakończ")
    a = p.parse_args(argv)

    folder = a.data or os.path.join(data_dir(), "web")
    hosts = HostManager(os.path.join(folder, "workspaces"))
    for path in a.config:
        ids = hosts.load_config(path)
        print(f"Wczytano {len(ids)} połączeń z {path}")
    app = App(folder, hosts)
    if a.add_user:
        pw = getpass.getpass(f"Hasło dla {a.add_user}: ")
        try:
            app.users.add(a.add_user, "admin", "local", pw)
        except AuthError as e:
            print(e)
            return 1
        print("Konto administratora dodane.")
        return 0

    if a.sso:
        from . import sso
        app.sso = sso.available()
        print("Logowanie SSO (konto Windows): " + ("włączone" if app.sso else "niedostępne na tym systemie"))
    tls = None
    if a.cert and a.key:
        tls = (a.cert, a.key)
    elif a.tls:
        tls = self_signed_cert(folder, a.host if a.host not in ("0.0.0.0", "::") else "localhost")
    srv = WebServer(app, a.host, a.port, tls)
    srv.start()
    print(f"Serwer S7Trace Web: {srv.url}   (dane: {folder})  Ctrl+C = koniec")
    if not app.users.count():
        print("Nie ma jeszcze kont - pierwszą osobę (administratora) utworzysz w przeglądarce.")
    if a.autostart:
        for h in hosts.all():
            try:
                h.start("autostart")
            except ValueError as e:
                print(f"{h.name}: {e}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Zatrzymywanie…")
    finally:
        srv.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
