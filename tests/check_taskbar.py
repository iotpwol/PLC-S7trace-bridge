"""Manual check on a real Windows desktop (flashes a window for a moment): the taskbar identity of a window.

    python tests/check_taskbar.py <png_out>
Prints the AppUserModel properties read back from the window's property store and saves the 256 px icon.
"""
import ctypes
import os
import sys
import tempfile
from ctypes import POINTER, HRESULT, WINFUNCTYPE, Structure, byref, c_ubyte, c_ulong, c_ushort, c_void_p, cast
from uuid import UUID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    from PySide6.QtWidgets import QApplication, QWidget

    from s7trace.ui import appicon

    appicon.set_app_id()
    app = QApplication([])
    app.setWindowIcon(appicon.app_icon())
    w = QWidget()
    w.setWindowTitle("check")
    w.show()
    app.processEvents()
    ico = os.path.join(tempfile.mkdtemp(), "s7trace.ico")
    print("ico written:", appicon.write_ico(ico), os.path.getsize(ico), "bytes")
    print("identity set:", appicon.set_taskbar_identity(int(w.winId()), ico))

    class GUID(Structure):
        _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort), ("Data4", c_ubyte * 8)]

    class KEY(Structure):
        _fields_ = [("fmtid", GUID), ("pid", c_ulong)]

    class PV(Structure):
        _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort), ("p", c_void_p), ("q", c_void_p)]

    g = lambda t: GUID.from_buffer_copy(UUID(t).bytes_le)
    sh = ctypes.windll.shell32
    sh.SHGetPropertyStoreForWindow.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
    sh.SHGetPropertyStoreForWindow.restype = HRESULT
    ppv = c_void_p()
    sh.SHGetPropertyStoreForWindow(int(w.winId()), byref(g("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")), byref(ppv))
    vt = cast(cast(ppv, POINTER(c_void_p))[0], POINTER(c_void_p))
    get = WINFUNCTYPE(HRESULT, c_void_p, POINTER(KEY), POINTER(PV))(vt[5])
    for pid, name in ((5, "ID"), (2, "RelaunchCommand"), (4, "RelaunchDisplayName"), (3, "RelaunchIcon")):
        pv = PV()
        get(ppv, byref(KEY(g("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid)), byref(pv))
        print(f"{name}: vt={pv.vt}", ctypes.wstring_at(pv.p) if pv.vt == 31 and pv.p else None)
    appicon.draw_icon(256).save(sys.argv[1])
    w.close()


main()
