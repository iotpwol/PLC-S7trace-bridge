"""Application icon and Windows taskbar identity.

Without them Windows groups the window under the interpreter ("Python", the Python logo). Three things fix it:
  * an explicit AppUserModelID for the process (own taskbar group instead of python's),
  * the window / application icon drawn here (also written as .ico for the taskbar relaunch entry),
  * the relaunch properties of the window (display name "S7Trace", icon, command) set through its property store."""
from __future__ import annotations

import os
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

APP_ID = "PWOL.S7Trace.1"
APP_NAME = "S7Trace"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw_icon(size: int) -> QImage:
    """A dark rounded tile with three step traces (the program records PLC signals over time)."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0, QColor("#2a4058"))
    grad.setColorAt(1, QColor("#0f1a26"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(s * 0.03, s * 0.03, s * 0.94, s * 0.94), s * 0.2, s * 0.2)
    p.fillPath(path, grad)
    # step traces: (colour, y of the low level, [(x0, x1) of the high pulses])
    traces = (("#ffb347", 0.34, [(0.22, 0.40), (0.66, 0.80)]),
              ("#7be06a", 0.56, [(0.30, 0.58)]),
              ("#52c7ff", 0.78, [(0.14, 0.34), (0.50, 0.86)]))
    h = s * 0.13
    for col, y, pulses in traces:
        pen = QPen(QColor(col))
        pen.setWidthF(max(s * 0.055, 1.0))
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        pts = [QPointF(s * 0.12, s * y)]
        for a, b in pulses:
            pts += [QPointF(s * a, s * y), QPointF(s * a, s * y - h), QPointF(s * b, s * y - h), QPointF(s * b, s * y)]
        pts.append(QPointF(s * 0.88, s * y))
        p.drawPolyline(pts)
    p.end()
    return img


def app_icon() -> QIcon:
    icon = QIcon()
    for n in SIZES:
        icon.addPixmap(QPixmap.fromImage(draw_icon(n)))
    return icon


def ico_bytes() -> bytes:
    """The icon as an .ico file (PNG-compressed images, no extra Qt image plugin needed)."""
    blobs = []
    for n in SIZES:
        ba, buf = QByteArray(), QBuffer()
        buf.setBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        draw_icon(n).save(buf, "PNG")
        buf.close()
        blobs.append((n, bytes(ba)))
    out = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    body = b""
    for n, data in blobs:
        out += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    return out + body


def write_ico(path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(ico_bytes())
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ Windows taskbar identity
def set_app_id() -> None:
    """Call before the QApplication is created: the process gets its own taskbar group."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _pythonw() -> str:
    exe = sys.executable
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return w if os.path.exists(w) else exe


def set_taskbar_identity(hwnd: int, ico_path: str) -> bool:
    """Window property store: AppUserModel.ID + relaunch command / display name / icon, so the taskbar (and its
    pinned entry) shows 'S7Trace' with this icon instead of 'Python'. True when every property was stored."""
    if os.name != "nt" or not hwnd:
        return False
    try:
        import ctypes
        from ctypes import POINTER, Structure, WINFUNCTYPE, byref, c_ubyte, c_ulong, c_ushort, c_void_p, cast
        from ctypes import HRESULT, create_unicode_buffer
        from uuid import UUID

        class GUID(Structure):
            _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort), ("Data4", c_ubyte * 8)]

        class PROPERTYKEY(Structure):
            _fields_ = [("fmtid", GUID), ("pid", c_ulong)]

        class PROPVARIANT(Structure):                      # 24 bytes on 64-bit: vt + 3 reserved words + 16 data bytes
            _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                        ("p", c_void_p), ("q", c_void_p)]

        def guid(text: str) -> GUID:
            return GUID.from_buffer_copy(UUID(text).bytes_le)

        shell32 = ctypes.windll.shell32
        shell32.SHGetPropertyStoreForWindow.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
        shell32.SHGetPropertyStoreForWindow.restype = HRESULT
        ppv = c_void_p()
        shell32.SHGetPropertyStoreForWindow(hwnd, byref(guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")), byref(ppv))
        vtbl = cast(cast(ppv, POINTER(c_void_p))[0], POINTER(c_void_p))   # IPropertyStore vtable
        set_value = WINFUNCTYPE(HRESULT, c_void_p, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(vtbl[6])
        commit = WINFUNCTYPE(HRESULT, c_void_p)(vtbl[7])
        release = WINFUNCTYPE(c_ulong, c_void_p)(vtbl[2])

        fmt = guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")            # System.AppUserModel.*
        script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
        values = ((5, APP_ID),                                         # ID
                  (2, f'"{_pythonw()}" "{script}"'),                   # RelaunchCommand
                  (4, APP_NAME),                                       # RelaunchDisplayNameResource
                  (3, f"{ico_path},0"))                                # RelaunchIconResource
        keep = []
        try:
            for pid, text in values:
                buf = create_unicode_buffer(text)
                keep.append(buf)
                pv = PROPVARIANT()
                pv.vt = 31                                             # VT_LPWSTR
                pv.p = cast(buf, c_void_p).value
                key = PROPERTYKEY(fmt, pid)
                set_value(ppv, byref(key), byref(pv))
            commit(ppv)
        finally:
            release(ppv)
        return True
    except Exception:
        return False
