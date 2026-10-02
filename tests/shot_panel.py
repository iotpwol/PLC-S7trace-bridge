"""Offscreen screenshot of the connection / device boxes of the left panel.

    python tests/shot_panel.py <output_dir>
"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"
os.environ["APPDATA"] = tempfile.mkdtemp()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from s7trace.core import ip_history
    from s7trace.core.config import TabConfig
    from s7trace.ui.theme import apply_dark
    from s7trace.ui.trace_tab import TraceTab

    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication([])
    apply_dark(app)
    for a in ("172.16.0.5", "192.168.0.1", "10.12.91.1"):
        ip_history.add(a)
    tab = TraceTab(TabConfig(ip="10.12.91.1"), lambda: [])
    tab.resize(1500, 700)
    tab.show()
    for _ in range(4):
        app.processEvents()
    tab.split_h.setSizes([int(os.environ.get('PANEL_W', 300)), 800])
    for _ in range(4):
        app.processEvents()
    print('sizes', tab.split_h.sizes(), 'ip', tab.ed_ip.width())
    tab.grab().copy(0, 0, int(os.environ.get('PANEL_W', 300)), 360).save(os.path.join(out, "panel_empty.png"))
    tab._infoRaw.emit({"method": "s7", "info": {"family": "S7-300", "model": "CPU 315-2 PN/DP", "firmware": "V3.2.10",
                                                "plc_name": "Proofer (10_12_92_1)", "module_name": "CPU 315-2 PN/DP"}})
    for _ in range(4):
        app.processEvents()
    tab.grab().copy(0, 0, int(os.environ.get('PANEL_W', 300)), 360).save(os.path.join(out, "panel_device.png"))
    tab.ed_ip.setText("10.12.91.1")
    tab.ed_ip.showPopup()
    for _ in range(4):
        app.processEvents()
    pop = tab.ed_ip.view().window()
    pop.grab().save(os.path.join(out, "panel_popup.png"))
    tab.ed_ip.hidePopup()
    tab.shutdown()


main()
