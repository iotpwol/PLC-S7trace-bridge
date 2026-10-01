"""S7Trace entry point:  python main.py"""
import multiprocessing
import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from s7trace.ui.main_window import MainWindow
    from s7trace.ui.theme import apply_dark

    app = QApplication(sys.argv)
    apply_dark(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
