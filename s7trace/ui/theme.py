"""Dark theme similar to the reference screenshots."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

QSS = """
QWidget { font-size: 9pt; }
QMainWindow, QDialog { background: #2b2b2b; }
QGroupBox { border: 1px solid #3c3c3c; border-radius: 3px; margin-top: 14px; padding-top: 6px; background: #303030; }
QGroupBox::title { subcontrol-origin: margin; left: 2px; top: -2px; color: #d8d8d8; }
QLabel { color: #d0d0d0; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #1e1e1e; color: #f0f0f0; border: 1px solid #3a3a3a; border-radius: 2px; padding: 2px 4px;
    selection-background-color: #2a82da; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    background: #2a2a2a; color: #777; }
QComboBox QAbstractItemView { background: #1e1e1e; color: #f0f0f0; selection-background-color: #2a82da; }
QPushButton { background: #3a3a3a; color: #e8e8e8; border: 1px solid #4a4a4a; border-radius: 2px; padding: 4px 12px; }
QPushButton:hover { background: #454545; }
QPushButton:pressed, QPushButton:checked { background: #1f5f9f; border-color: #2a82da; }
QPushButton:disabled { background: #2f2f2f; color: #6a6a6a; border-color: #363636; }
QTableWidget { background: #262626; gridline-color: #3a3a3a; color: #e0e0e0; }
QHeaderView::section { background: #333; color: #bbb; border: 1px solid #3f3f3f; padding: 3px; }
QMenuBar, QMenu { background: #2b2b2b; color: #e0e0e0; }
QMenu::item:selected, QMenuBar::item:selected { background: #3d6fa5; }
QTabBar::tab { background: #333; color: #ddd; padding: 5px 12px; border: 1px solid #444; }
QTabBar::tab:selected { background: #444; }
QToolTip { background: #202020; color: #eee; border: 1px solid #555; }
"""


def apply_dark(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window, QColor(43, 43, 43))
    p.setColor(QPalette.WindowText, QColor(220, 220, 220))
    p.setColor(QPalette.Base, QColor(30, 30, 30))
    p.setColor(QPalette.AlternateBase, QColor(38, 38, 38))
    p.setColor(QPalette.Text, QColor(235, 235, 235))
    p.setColor(QPalette.Button, QColor(58, 58, 58))
    p.setColor(QPalette.ButtonText, QColor(232, 232, 232))
    p.setColor(QPalette.Highlight, QColor(42, 130, 218))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ToolTipBase, QColor(32, 32, 32))
    p.setColor(QPalette.ToolTipText, QColor(235, 235, 235))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    app.setPalette(p)
    app.setStyleSheet(QSS)
