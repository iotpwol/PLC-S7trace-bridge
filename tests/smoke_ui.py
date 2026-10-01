"""Offscreen smoke test: runs the UI against the simulator and saves screenshots.

    python tests/smoke_ui.py <output_dir> [<scenario>]
"""
import os
import subprocess
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    import numpy as np
    from PySide6.QtWidgets import QApplication

    from s7trace.core.config import TabConfig
    from s7trace.core.trigger import TriggerConfig
    from s7trace.core.types import Signal
    from s7trace.ui.main_window import MainWindow
    from s7trace.ui.theme import apply_dark

    out = sys.argv[1]
    scenario = sys.argv[2] if len(sys.argv) > 2 else "run"
    simp = subprocess.Popen([sys.executable, "-m", "s7trace.sim", "11103"], cwd=ROOT)
    time.sleep(1.5)
    try:
        app = QApplication([])
        apply_dark(app)
        cfg = TabConfig(ip="127.0.0.1:11103", window_s=20)
        cols = ["#ffb347", "#c8f04e", "#4ef04e", "#4ef0c0", "#4eb8f0"]
        cfg.signals = [Signal(name=f"D160{c}", dtype="BOOL", db=1, byte=160, bit=i,
                              offset_y=round(-1.1 * i, 3), color=col)
                       for i, (c, col) in enumerate(zip("ABCDE", cols))]
        cfg.signals.append(Signal(name="SINE", dtype="REAL", db=1, byte=172, offset_y=-7,
                                  gain=0.05, color="#b48cff"))
        if scenario == "trigger":
            cfg.trigger = TriggerConfig(enabled=True, signal="D160A", mode="rising edge", a=0.5,
                                        pretrigger=5.0, action="Pauza + zapis CSV",
                                        folder=tempfile.mkdtemp())
        w = MainWindow(config_file=os.path.join(tempfile.mkdtemp(), "c.json"))
        tab = w.tabs.widget(0)
        tab.cfg = cfg
        tab._load_cfg()
        w.resize(1500, 860)
        w.show()

        def spin(sec):
            t0 = time.time()
            while time.time() - t0 < sec:
                app.processEvents()
                time.sleep(0.01)

        tab.start()
        spin(14 if scenario == "run" else 26)
        _t, _v = tab.buffer.snapshot()
        _d = np.diff(_t) * 1000
        print("dt mean %.1f p50 %.1f p95 %.1f max %.1f" %
              (_d.mean(), np.percentile(_d, 50), np.percentile(_d, 95), _d.max()))
        print("state", tab.state, "samples", len(tab.buffer), tab.lbl_status.text())
        w.grab().save(os.path.join(out, f"{scenario}.png"))
        if scenario == "run":
            tab.btn_v.setChecked(True)
            tab.plot._add_marker(tab.plot.vmarks, tab.plot.view_range()[1] - 8, 90)
            tab.plot._add_marker(tab.plot.vmarks, tab.plot.view_range()[1] - 3, 90)
            tab.plot.update_readout()
            tab.stop()
            spin(1.5)
            print("state after stop", tab.state)
            w.grab().save(os.path.join(out, "stopped.png"))
        else:
            print("trig_state", tab.trig_state, "paused", tab.paused, "msg", tab.status_msg)
            print("files", os.listdir(tab.ed_tfolder.text()))
            tab.stop()
            spin(1.5)
        w.close()
    finally:
        simp.terminate()


if __name__ == "__main__":
    main()
