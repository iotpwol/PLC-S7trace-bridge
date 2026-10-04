"""Single sign-on with the Windows account of the browser user (HTTP "Negotiate": Kerberos / NTLM through SSPI, ctypes only).
The server never sees a password: Windows (the domain controller or the local SAM) proves who the client is. The account must
still be registered by an administrator (kind "Windows / AD"), which is where the role comes from."""
from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import wintypes

OK, CONTINUE = 0x00000000, 0x00090312
SECPKG_CRED_INBOUND, SECPKG_CRED_OUTBOUND = 1, 2
SECURITY_NATIVE_DREP = 0x10
SECBUFFER_TOKEN = 2
ASC_REQ_ALLOCATE_MEMORY = 0x100
ISC_REQ_ALLOCATE_MEMORY, ISC_REQ_CONNECTION = 0x100, 0x800
SECPKG_ATTR_NAMES = 1


def available() -> bool:
    return sys.platform == "win32"


class SecHandle(ctypes.Structure):
    _fields_ = [("lower", ctypes.c_size_t), ("upper", ctypes.c_size_t)]


class SecBuffer(ctypes.Structure):
    _fields_ = [("cb", wintypes.ULONG), ("type", wintypes.ULONG), ("ptr", ctypes.c_void_p)]


class SecBufferDesc(ctypes.Structure):
    _fields_ = [("ver", wintypes.ULONG), ("count", wintypes.ULONG), ("buffers", ctypes.POINTER(SecBuffer))]


class _Names(ctypes.Structure):
    _fields_ = [("name", ctypes.c_void_p)]


class Timestamp(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.LONG)]


def _lib():
    sp = ctypes.WinDLL("secur32", use_last_error=True)
    sp.AcquireCredentialsHandleW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(SecHandle), ctypes.POINTER(Timestamp)]
    sp.AcceptSecurityContext.argtypes = [ctypes.POINTER(SecHandle), ctypes.POINTER(SecHandle), ctypes.POINTER(SecBufferDesc),
                                         wintypes.ULONG, wintypes.ULONG, ctypes.POINTER(SecHandle), ctypes.POINTER(SecBufferDesc),
                                         ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(Timestamp)]
    sp.InitializeSecurityContextW.argtypes = [ctypes.POINTER(SecHandle), ctypes.POINTER(SecHandle), wintypes.LPCWSTR, wintypes.ULONG,
                                              wintypes.ULONG, wintypes.ULONG, ctypes.POINTER(SecBufferDesc), wintypes.ULONG,
                                              ctypes.POINTER(SecHandle), ctypes.POINTER(SecBufferDesc), ctypes.POINTER(wintypes.ULONG),
                                              ctypes.POINTER(Timestamp)]
    sp.QueryContextAttributesW.argtypes = [ctypes.POINTER(SecHandle), wintypes.ULONG, ctypes.c_void_p]
    sp.FreeContextBuffer.argtypes = [ctypes.c_void_p]
    sp.DeleteSecurityContext.argtypes = [ctypes.POINTER(SecHandle)]
    sp.FreeCredentialsHandle.argtypes = [ctypes.POINTER(SecHandle)]
    for f in ("AcquireCredentialsHandleW", "AcceptSecurityContext", "InitializeSecurityContextW", "QueryContextAttributesW",
              "FreeContextBuffer", "DeleteSecurityContext", "FreeCredentialsHandle"):
        getattr(sp, f).restype = ctypes.c_uint32
    return sp


def _out_token(buf: SecBuffer, sp) -> bytes:
    data = ctypes.string_at(buf.ptr, buf.cb) if buf.ptr and buf.cb else b""
    if buf.ptr:
        sp.FreeContextBuffer(buf.ptr)
    return data


class Negotiate:
    """The server side of one authentication exchange (one HTTP connection). `step(token)` -> (status, token to send back,
    account name once finished): status "continue" / "ok" / "fail"."""

    def __init__(self):
        self.sp = _lib()
        self.cred, self.ctx, self.has_ctx = SecHandle(), SecHandle(), False
        r = self.sp.AcquireCredentialsHandleW(None, "Negotiate", SECPKG_CRED_INBOUND, None, None, None, None,
                                              ctypes.byref(self.cred), ctypes.byref(Timestamp()))
        if r != OK:
            raise OSError(f"SSPI: AcquireCredentialsHandle 0x{r:08X}")

    def step(self, token: bytes) -> tuple[str, bytes, str]:
        tin = ctypes.create_string_buffer(token, len(token))
        inb = SecBuffer(len(token), SECBUFFER_TOKEN, ctypes.cast(tin, ctypes.c_void_p))
        outb = SecBuffer(0, SECBUFFER_TOKEN, None)
        din, dout = SecBufferDesc(0, 1, ctypes.pointer(inb)), SecBufferDesc(0, 1, ctypes.pointer(outb))
        attrs = wintypes.ULONG()
        r = self.sp.AcceptSecurityContext(ctypes.byref(self.cred), ctypes.byref(self.ctx) if self.has_ctx else None,
                                          ctypes.byref(din), ASC_REQ_ALLOCATE_MEMORY, SECURITY_NATIVE_DREP, ctypes.byref(self.ctx),
                                          ctypes.byref(dout), ctypes.byref(attrs), ctypes.byref(Timestamp()))
        out = _out_token(outb, self.sp)
        if r in (OK, CONTINUE):
            self.has_ctx = True
        if r == CONTINUE:
            return "continue", out, ""
        if r != OK:
            return "fail", b"", ""
        names = _Names()
        if self.sp.QueryContextAttributesW(ctypes.byref(self.ctx), SECPKG_ATTR_NAMES, ctypes.byref(names)) != OK:
            return "fail", out, ""
        name = ctypes.wstring_at(names.name) if names.name else ""
        if names.name:
            self.sp.FreeContextBuffer(names.name)
        return "ok", out, name

    def close(self) -> None:
        if self.has_ctx:
            self.sp.DeleteSecurityContext(ctypes.byref(self.ctx))
            self.has_ctx = False
        if self.cred.lower or self.cred.upper:
            self.sp.FreeCredentialsHandle(ctypes.byref(self.cred))
            self.cred = SecHandle()


class NegotiateClient:
    """The client side with the credentials of the current Windows user (used by tests and tools; browsers do this themselves)."""

    def __init__(self, target: str = ""):
        self.sp, self.target = _lib(), target
        self.cred, self.ctx, self.has_ctx = SecHandle(), SecHandle(), False
        r = self.sp.AcquireCredentialsHandleW(None, "Negotiate", SECPKG_CRED_OUTBOUND, None, None, None, None,
                                              ctypes.byref(self.cred), ctypes.byref(Timestamp()))
        if r != OK:
            raise OSError(f"SSPI: AcquireCredentialsHandle 0x{r:08X}")

    def step(self, token: bytes | None = None) -> tuple[bool, bytes]:
        """(done, token to send)."""
        outb = SecBuffer(0, SECBUFFER_TOKEN, None)
        dout = SecBufferDesc(0, 1, ctypes.pointer(outb))
        din = None
        if token:
            tin = ctypes.create_string_buffer(token, len(token))
            inb = SecBuffer(len(token), SECBUFFER_TOKEN, ctypes.cast(tin, ctypes.c_void_p))
            din = SecBufferDesc(0, 1, ctypes.pointer(inb))
        attrs = wintypes.ULONG()
        r = self.sp.InitializeSecurityContextW(ctypes.byref(self.cred), ctypes.byref(self.ctx) if self.has_ctx else None, self.target,
                                               ISC_REQ_ALLOCATE_MEMORY | ISC_REQ_CONNECTION, 0, SECURITY_NATIVE_DREP,
                                               ctypes.byref(din) if din is not None else None, 0, ctypes.byref(self.ctx),
                                               ctypes.byref(dout), ctypes.byref(attrs), ctypes.byref(Timestamp()))
        out = _out_token(outb, self.sp)
        if r in (OK, CONTINUE):
            self.has_ctx = True
        if r not in (OK, CONTINUE):
            raise OSError(f"SSPI: InitializeSecurityContext 0x{r:08X}")
        return r == OK, out

    def close(self) -> None:
        if self.has_ctx:
            self.sp.DeleteSecurityContext(ctypes.byref(self.ctx))
        if self.cred.lower or self.cred.upper:
            self.sp.FreeCredentialsHandle(ctypes.byref(self.cred))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def match_account(name: str, lookup) -> dict | None:
    """The registered Windows account for the name SSPI returned ('DOMAIN\\user'): by the full name, and for a local account of
    this computer also by the bare user name (administrators may register 'jan' for COMPUTER\\jan)."""
    acc = lookup(name)
    if acc is not None:
        return acc
    domain, _, user = name.partition("\\")
    if user and domain.lower() == os.environ.get("COMPUTERNAME", "").lower():
        return lookup(user)
    return None
