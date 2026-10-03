"""S7Trace entry point:  python main.py"""
import multiprocessing
import os
import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from s7trace.core.config import app_dir
    from s7trace.ui import appicon
    from s7trace.ui.main_window import MainWindow
    from s7trace.ui.theme import apply_dark

    appicon.set_app_id()                                  # own taskbar group (not "Python") - before the QApplication
    app = QApplication(sys.argv)
    app.setApplicationName(appicon.APP_NAME)
    app.setWindowIcon(appicon.app_icon())
    apply_dark(app)
    win = MainWindow()
    win.show()
    ico = os.path.join(app_dir(), "s7trace.ico")          # for the taskbar's relaunch / pinned entry
    appicon.write_ico(ico)
    appicon.set_taskbar_identity(int(win.winId()), ico)
    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
