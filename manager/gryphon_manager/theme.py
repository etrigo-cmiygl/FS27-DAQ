from __future__ import annotations

BG = "#0B0E0D"
PANEL = "#131917"
RAISED = "#1C2421"
BORDER = "#26302C"
GREEN = "#1E5C3A"
GREEN_BRIGHT = "#2FA36B"
RED = "#8C1D24"
RED_BRIGHT = "#E0453A"
AMBER = "#E0A23A"
TEXT = "#F2F4F3"
TEXT_DIM = "#9AA5A0"
GREY = "#5C6662"

STATUS = {"green": GREEN_BRIGHT, "amber": AMBER, "red": RED_BRIGHT, "grey": GREY}
STATUS_WORD = {"green": "OK", "amber": "Check", "red": "Fault", "grey": "Not connected"}
SERIES = ["#2FA36B", "#E0453A", "#F2F4F3", "#E0A23A", "#5AA9E6", "#B58CE0", "#7FD1B9", "#F28B6B"]


def stylesheet(font_family: str, base: int = 13) -> str:
    return f"""
* {{ font-family: "{font_family}"; font-size: {base}px; color: {TEXT}; }}
QWidget {{ background: transparent; }}
QMainWindow, QDialog, QMessageBox, QInputDialog, QFileDialog, QWidget#root {{ background: {BG}; }}
QMessageBox QLabel {{ font-size: 14px; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {GREEN}; padding: 6px; }}
QFrame#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QFrame#topbar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#tile {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#tile[state="amber"] {{ border: 1px solid {AMBER}; }}
QFrame#tile[state="red"] {{ border: 1px solid {RED_BRIGHT}; background: #1F1213; }}
QFrame#chip {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#alarmbar {{ background: {RED}; border: none; }}
QFrame#noticebar {{ background: {RAISED}; border-bottom: 1px solid {AMBER}; }}
QFrame#noticebar[level="error"] {{ border-bottom: 1px solid {RED_BRIGHT}; }}
QFrame#noticebar[level="info"] {{ border-bottom: 1px solid {GREEN_BRIGHT}; }}
QFrame#empty {{ background: {PANEL}; border: 1px dashed {BORDER}; border-radius: 12px; }}
QLabel#h1 {{ font-size: 22px; font-weight: 600; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; }}
QLabel#dim {{ color: {TEXT_DIM}; }}
QLabel#caption {{ color: {TEXT_DIM}; font-size: 12px; font-weight: 600; }}
QLabel#brand {{ font-size: 17px; font-weight: 700; letter-spacing: 1px; }}
QLabel#brandsub {{ color: {GREEN_BRIGHT}; font-size: 11px; font-weight: 600; letter-spacing: 3px; }}
QLabel#emptytitle {{ font-size: 19px; font-weight: 600; }}
QLabel#timer {{ font-size: 18px; font-weight: 600; color: {TEXT}; }}
QLabel#pill {{ border-radius: 12px; padding: 4px 12px; font-weight: 600; background: {RAISED}; color: {TEXT_DIM}; }}
QLabel#pill[state="green"] {{ background: {GREEN}; color: {TEXT}; }}
QLabel#pill[state="amber"] {{ background: #5A4318; color: {TEXT}; }}
QLabel#pill[state="red"] {{ background: {RED}; color: {TEXT}; }}
QPushButton {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 7px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {GREEN_BRIGHT}; }}
QPushButton:pressed {{ background: {GREEN}; }}
QPushButton:disabled {{ color: {GREY}; border-color: {BORDER}; background: {PANEL}; }}
QPushButton#primary {{ background: {GREEN}; border: 1px solid {GREEN_BRIGHT}; font-weight: 600; padding: 9px 22px; font-size: 14px; }}
QPushButton#primary:hover {{ background: #24704A; }}
QPushButton#primary[connected="true"] {{ background: {RAISED}; border: 1px solid {BORDER}; }}
QPushButton#danger {{ background: {RED}; border: 1px solid {RED_BRIGHT}; font-weight: 600; }}
QPushButton#record {{ padding: 9px 16px; font-weight: 600; }}
QPushButton#record[recording="true"] {{ background: {RED}; border: 1px solid {RED_BRIGHT}; }}
QPushButton#nav {{ text-align: left; padding: 9px 14px; border: none; border-radius: 7px; background: transparent; color: {TEXT_DIM}; font-size: {base}px; }}
QPushButton#nav:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {GREEN}; color: {TEXT}; font-weight: 600; }}
QPushButton#link {{ background: transparent; border: none; color: {GREEN_BRIGHT}; padding: 2px; text-align: left; }}
QPushButton#link:hover {{ color: {TEXT}; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 8px; selection-background-color: {GREEN}; }}
QComboBox:hover, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {GREEN_BRIGHT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {RAISED}; border: 1px solid {BORDER}; selection-background-color: {GREEN}; outline: none; }}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {GREY}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled {{ color: {GREY}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {GREY}; border-radius: 4px; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {GREEN_BRIGHT}; border-color: {GREEN_BRIGHT}; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border: 2px solid {GREY}; border-radius: 9px; background: {BG}; }}
QRadioButton::indicator:checked {{ background: {GREEN_BRIGHT}; border-color: {TEXT}; }}
QTableView, QTreeView, QListWidget, QTextBrowser {{
    background: {PANEL}; alternate-background-color: #161D1A; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: {BORDER}; selection-background-color: {GREEN}; selection-color: {TEXT}; outline: none; }}
QTableView::item {{ padding: 3px 6px; }}
QHeaderView::section {{ background: {RAISED}; color: {TEXT_DIM}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {RAISED}; border: none; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSlider::groove:horizontal {{ height: 6px; background: {RAISED}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {GREEN_BRIGHT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; margin: -5px 0; border-radius: 7px; }}
QProgressBar {{ background: {RAISED}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {GREEN_BRIGHT}; border-radius: 4px; }}
QMenu {{ background: {RAISED}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {GREEN}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QSplitter::handle {{ background: {BG}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; }}
QTabBar::tab {{ background: {PANEL}; padding: 7px 14px; border: 1px solid {BORDER}; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; color: {TEXT_DIM}; }}
QTabBar::tab:selected {{ background: {GREEN}; color: {TEXT}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {TEXT_DIM}; }}
QScrollArea {{ border: none; }}
"""


def palette():
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, PANEL),
                        (QPalette.AlternateBase, "#161D1A"), (QPalette.Text, TEXT), (QPalette.Button, RAISED),
                        (QPalette.ButtonText, TEXT), (QPalette.ToolTipBase, RAISED), (QPalette.ToolTipText, TEXT),
                        (QPalette.Highlight, GREEN), (QPalette.HighlightedText, TEXT), (QPalette.Link, GREEN_BRIGHT),
                        (QPalette.PlaceholderText, GREY), (QPalette.BrightText, RED_BRIGHT)):
        p.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(GREY))
    return p
