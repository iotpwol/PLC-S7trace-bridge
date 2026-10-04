"""Accounts of the web server: own accounts (password hashed with PBKDF2) and Windows / Active Directory accounts
(the password is checked by Windows itself with LogonUserW; the account must be known to the server)."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import sys
import threading
import time

ROLES = ("viewer", "operator", "admin")                  # in the order of rights
ROLE_LABEL = {"viewer": "podgląd", "operator": "operator", "admin": "administrator"}
KINDS = ("local", "windows")
KIND_LABEL = {"local": "konto programu", "windows": "konto Windows / AD"}
ITERATIONS = 200_000
MAX_FAILS, LOCK_S = 5, 60                                # lock a (user, address) pair for a minute after 5 wrong passwords
_NAME = re.compile(r"[A-Za-z0-9_.@\\-]{1,64}")


class AuthError(Exception):
    """A message that may be shown to the user as it is."""


def role_allows(role: str, need: str) -> bool:
    return ROLES.index(role) >= ROLES.index(need) if role in ROLES and need in ROLES else False


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return salt.hex(), h.hex()


def check_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        _s, h = hash_password(password, bytes.fromhex(salt_hex))
    except ValueError:
        return False
    return hmac.compare_digest(h, hash_hex)


def windows_logon(username: str, password: str) -> bool:
    """True when Windows accepts the password of this local / domain account ('DOMAIN\\user' or 'user@domain')."""
    if sys.platform != "win32" or not username or not password:
        return False
    import ctypes
    from ctypes import wintypes
    if "\\" in username:
        domain, user = username.split("\\", 1)
    elif "@" in username:
        user, domain = username, None                                   # the UPN form: the domain is part of the name
    else:
        domain, user = ".", username                                    # '.' = the local computer
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    handle = wintypes.HANDLE()
    ok = adv.LogonUserW(user, domain, password, 3, 0, ctypes.byref(handle))      # LOGON32_LOGON_NETWORK, default provider
    if ok:
        ctypes.WinDLL("kernel32").CloseHandle(handle)
    return bool(ok)


class UserStore:
    """SQLite file with the accounts. Every method is thread-safe (the server answers requests in threads)."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.execute("CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, kind TEXT NOT NULL, salt TEXT, hash TEXT,"
                        " role TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, display TEXT, created_us INTEGER,"
                        " last_login_us INTEGER)")
        self.db.commit()
        self._fails: dict[tuple[str, str], list[float]] = {}
        self.windows_check = windows_logon                                # replaceable (tests)

    # ---- accounts
    def _norm(self, username: str) -> str:
        username = (username or "").strip()
        if not _NAME.fullmatch(username):
            raise AuthError("Nazwa użytkownika: 1–64 znaków (litery, cyfry, _ . @ \\ -).")
        return username

    def add(self, username: str, role: str, kind: str = "local", password: str = "", display: str = "") -> None:
        username = self._norm(username)
        if role not in ROLES or kind not in KINDS:
            raise AuthError("Nieznana rola albo rodzaj konta.")
        salt = h = None
        if kind == "local":
            if len(password) < 8:
                raise AuthError("Hasło musi mieć co najmniej 8 znaków.")
            salt, h = hash_password(password)
        with self._lock:
            if self.db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
                raise AuthError("Takie konto już istnieje.")
            self.db.execute("INSERT INTO users(username,kind,salt,hash,role,display,created_us) VALUES(?,?,?,?,?,?,?)",
                            (username, kind, salt, h, role, display, int(time.time() * 1e6)))
            self.db.commit()

    def get(self, username: str) -> dict | None:
        with self._lock:
            r = self.db.execute("SELECT username,kind,role,disabled,display,created_us,last_login_us FROM users "
                                "WHERE lower(username)=lower(?)", (username or "",)).fetchone()
        return dict(zip(("username", "kind", "role", "disabled", "display", "created_us", "last_login_us"), r)) if r else None

    def list(self) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT username,kind,role,disabled,display,created_us,last_login_us FROM users "
                                   "ORDER BY lower(username)").fetchall()
        return [dict(zip(("username", "kind", "role", "disabled", "display", "created_us", "last_login_us"), r)) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self.db.execute("SELECT count(*) FROM users").fetchone()[0]

    def _admins_left(self, without: str) -> int:
        with self._lock:
            return self.db.execute("SELECT count(*) FROM users WHERE role='admin' AND disabled=0 AND lower(username)<>lower(?)",
                                   (without,)).fetchone()[0]

    def set_role(self, username: str, role: str) -> None:
        if role not in ROLES:
            raise AuthError("Nieznana rola.")
        if role != "admin" and (self.get(username) or {}).get("role") == "admin" and self._admins_left(username) == 0:
            raise AuthError("Nie można odebrać roli ostatniemu administratorowi.")
        with self._lock:
            self.db.execute("UPDATE users SET role=? WHERE lower(username)=lower(?)", (role, username))
            self.db.commit()

    def set_disabled(self, username: str, disabled: bool) -> None:
        if disabled and (self.get(username) or {}).get("role") == "admin" and self._admins_left(username) == 0:
            raise AuthError("Nie można zablokować ostatniego administratora.")
        with self._lock:
            self.db.execute("UPDATE users SET disabled=? WHERE lower(username)=lower(?)", (1 if disabled else 0, username))
            self.db.commit()

    def set_password(self, username: str, password: str) -> None:
        u = self.get(username)
        if u is None or u["kind"] != "local":
            raise AuthError("Hasło można ustawić tylko dla konta programu.")
        if len(password) < 8:
            raise AuthError("Hasło musi mieć co najmniej 8 znaków.")
        salt, h = hash_password(password)
        with self._lock:
            self.db.execute("UPDATE users SET salt=?, hash=? WHERE lower(username)=lower(?)", (salt, h, username))
            self.db.commit()

    def delete(self, username: str) -> None:
        if (self.get(username) or {}).get("role") == "admin" and self._admins_left(username) == 0:
            raise AuthError("Nie można usunąć ostatniego administratora.")
        with self._lock:
            self.db.execute("DELETE FROM users WHERE lower(username)=lower(?)", (username,))
            self.db.commit()

    # ---- login
    def _locked(self, key) -> bool:
        now = time.time()
        fails = [t for t in self._fails.get(key, []) if now - t < LOCK_S]
        self._fails[key] = fails
        return len(fails) >= MAX_FAILS

    def authenticate(self, username: str, password: str, address: str = "") -> dict:
        """The account (dict) when the password is right; AuthError with a safe message otherwise."""
        key = ((username or "").lower(), address)
        with self._lock:
            if self._locked(key):
                raise AuthError(f"Za dużo błędnych prób – spróbuj za {LOCK_S} s.")
            r = self.db.execute("SELECT username,kind,salt,hash,role,disabled FROM users WHERE lower(username)=lower(?)",
                                (username or "",)).fetchone()
        ok = False
        if r is not None and not r[5]:
            if r[1] == "local":
                ok = check_password(password or "", r[2] or "", r[3] or "")
            else:
                ok = bool(self.windows_check(r[0], password or ""))
        else:
            check_password(password or "", "00" * 16, "00" * 32)             # (about the same time for an unknown account)
        if not ok:
            with self._lock:
                self._fails.setdefault(key, []).append(time.time())
            raise AuthError("Nieprawidłowa nazwa użytkownika lub hasło.")
        with self._lock:
            self._fails.pop(key, None)
            self.db.execute("UPDATE users SET last_login_us=? WHERE username=?", (int(time.time() * 1e6), r[0]))
            self.db.commit()
        return self.get(r[0])

    def close(self) -> None:
        with self._lock:
            self.db.close()


def new_password() -> str:
    return secrets.token_urlsafe(12)
