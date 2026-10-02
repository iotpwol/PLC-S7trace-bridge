"""Offscreen screenshots of the lane layout / diagnostics window (synthetic data, no PLC).

    python tests/shot_lanes.py <output_dir>
"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    import numpy as np
    from PySide6.QtWidgets import QApplication

    from s7trace.core.config import TabConfig
    from s7trace.core.types import Signal
    from s7trace.ui.main_window import MainWindow
    from s7trace.ui.theme import apply_dark

    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication([])
    apply_dark(app)
    cols = ["#ffb347", "#c8f04e", "#4ef04e", "#4ef0c0", "#4eb8f0"]
    cfg = TabConfig(ip="10.12.91.1", window_s=60)
    cfg.signals = [Signal(name=f"D160{c}", dtype="BOOL", db=1, byte=160, bit=i, color=col)
                   for i, (c, col) in enumerate(zip("ABCDE", cols))]
    cfg.signals.append(Signal(name="B160", source="I", dtype="BYTE", byte=160, gain=0.05, color="#b48cff", share=2.0))
    cfg.signals.append(Signal(name="TEMP", dtype="REAL", db=1, byte=172, color="#ff6fa8", share=1.0))
    w = MainWindow(config_file=os.path.join(tempfile.mkdtemp(), "c.json"))
    tab = w.tabs.widget(0)
    tab.cfg = cfg
    tab._load_cfg()
    w.resize(1500, 860)
    w.show()
    t = np.arange(0, 120, 0.05)
    v = np.zeros((len(t), 7))
    for i in range(5):
        v[:, i] = ((t + 7 * i) % 40 < 12).astype(float)
    v[:, 5] = np.clip(120 * np.sin(t / 9) ** 2 + 20, 0, 255).round()
    v[:, 6] = 20 + 4 * np.sin(t / 3) + np.random.default_rng(1).normal(0, .2, len(t))
    tab.buffer.reset(7)
    tab.buffer.load(t, v)
    tab._run_signals = list(tab.display_signals())
    tab.plot.set_follow(False)
    tab.plot.set_view(40, 100)
    for _ in range(5):
        app.processEvents()
    tab.plot.refresh(force=True)
    app.processEvents()
    w.grab().save(os.path.join(out, "lanes.png"))
    tab.cb_ylayout.setCurrentIndex(1)                        # Offset + Gain
    tab.plot.refresh(force=True)
    app.processEvents()
    w.grab().save(os.path.join(out, "offset.png"))
    tab.cb_ylayout.setCurrentIndex(0)
    tab.plot.set_view(60, 60.1)                              # the narrowest window
    tab.plot.refresh(force=True)
    app.processEvents()
    w.grab().save(os.path.join(out, "zoom01.png"))
    w.close()


main()
