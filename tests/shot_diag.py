"""Offscreen screenshot of the diagnostics window with synthetic statistics.

    python tests/shot_diag.py <output_dir>
"""
import os
import sys
import time
from types import SimpleNamespace

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    import numpy as np
    from PySide6.QtWidgets import QApplication

    from s7trace.core import diagnostics as dg
    from s7trace.core.config import TabConfig
    from s7trace.ui.diag_dialog import DiagDialog
    from s7trace.ui.theme import apply_dark
    from s7trace.ui.trace_tab import TraceTab

    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication([])
    apply_dark(app)
    tab = TraceTab(TabConfig(ip="10.12.91.1"), lambda: [])
    d = dg.LinkDiag(cycle_ms=40)
    rng = np.random.default_rng(3)
    t0 = time.perf_counter() - 200
    for i in range(5000):
        d.add_sample(t0 + i * 0.04, float(rng.choice([8, 12, 15, 18, 25], p=[.08, .5, .2, .2, .02])))
    d.note_state("running")
    tab.acq = SimpleNamespace(diag=d, t0=t0, stats=SimpleNamespace(), state="running")
    dlg = DiagDialog(tab)
    dlg.resize(980, 760)
    dlg.show()
    for _ in range(5):
        app.processEvents()
    dlg.refresh()
    app.processEvents()
    dlg.grab().save(os.path.join(out, "diag1.png"))
    dlg.cb_span.setCurrentIndex(5)
    dlg.findChildren(type(dlg.cb_span))
    dlg.refresh()
    dlg.close()


main()
