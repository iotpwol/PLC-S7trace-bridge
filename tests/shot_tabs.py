"""Offscreen check of the tab bar geometry in the menu row.

    python tests/shot_tabs.py <output_dir>
"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    from PySide6.QtWidgets import QApplication

    from s7trace.core.config import TabConfig
    from s7trace.ui.main_window import MainWindow
    from s7trace.ui.theme import apply_dark

    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication([])
    apply_dark(app)
    w = MainWindow(config_file=os.path.join(tempfile.mkdtemp(), "c.json"))
    for ip in ("10.12.91.1", "192.168.0.1", "192.168.100.200", "10.1.1.1", "10.1.1.2", "172.16.0.10", "172.16.0.11", "10.9.9.9"):
        w.new_tab(TabConfig(ip=ip))
    for width in (1200, 1500):
        w.resize(width, 600)
        w.show()
        for _ in range(4):
            app.processEvents()
        bar, mb = w.tabs.bar, w.menuBar()
        right = bar.mapTo(w, bar.rect().topRight()).x()
        print(f"win={w.width()} mb={mb.width()} bar_w={bar.width()} corner_w={w._corner.width()} "
              f"bar_right_in_window={right} plus_right={w._plus.mapTo(w, w._plus.rect().topRight()).x()} "
              f"tabs={bar.count()} sum_hint={sum(bar.tabSizeHint(i).width() for i in range(bar.count()))}")
        w.grab().copy(0, 0, width, 40).save(os.path.join(out, f"tabs_{width}.png"))
    w.close()


main()
