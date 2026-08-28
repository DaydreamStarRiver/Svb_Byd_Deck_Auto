"""PyQt5 界面的全局视觉主题。

配色沿用演示界面的紧凑深色控制中心风格。组件可通过动态属性选择语义变体，例如
``button.setProperty("variant", "primary")`` 或
``frame.setProperty("card", True)``。
"""

from __future__ import annotations

from typing import Dict

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication


COLORS: Dict[str, str] = {
    "background": "#1e1e2e",
    "sidebar": "#181825",
    "surface": "#282838",
    "surface_hover": "#32324a",
    "border": "#3a3a4a",
    "border_hover": "#4a4a5a",
    "primary": "#89b4fa",
    "primary_hover": "#a3c7fb",
    "success": "#a6e3a1",
    "warning": "#f9e2af",
    "error": "#f38ba8",
    "text": "#cdd6f4",
    "text_secondary": "#9399b2",
    "text_muted": "#6c7086",
}


APP_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #1e1e2e;
}

QWidget {
    color: #cdd6f4;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
    letter-spacing: 0;
}

QWidget#AppRoot {
    background-color: #1e1e2e;
}

QStackedWidget#PageStack, QWidget[pageRoot="true"] {
    background: transparent;
}

QFrame#Sidebar {
    background-color: #181825;
    border-right: 1px solid #3a3a4a;
}

QFrame#SidebarBrand {
    background-color: #181825;
    border-bottom: 1px solid #3a3a4a;
}

QFrame#SidebarFooter {
    background-color: #181825;
    border-top: 1px solid #3a3a4a;
}

QLabel#BrandMark {
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    color: #89b4fa;
    background-color: #293653;
    border: 1px solid #3e5278;
    border-radius: 4px;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}

QLabel#BrandTitle {
    color: #cdd6f4;
    font-size: 14px;
    font-weight: 600;
}

QLabel#BrandSubtitle {
    color: #6c7086;
    font-size: 11px;
}

QLabel#FooterDot {
    color: #6c7086;
}

QLabel#FooterDot[active="true"] {
    color: #a6e3a1;
}

QPushButton#SidebarAboutButton {
    min-height: 28px;
    padding: 0 4px;
    color: #9399b2;
    background: transparent;
    border: 0;
    text-align: left;
}

QPushButton#SidebarAboutButton:hover {
    color: #cdd6f4;
    background-color: #282838;
}

QFrame[card="true"], QFrame#SurfacePanel, QFrame#DashboardPanel,
QFrame#MetricCard, QGroupBox {
    background-color: #282838;
    border: 1px solid #3a3a4a;
    border-radius: 6px;
}

QFrame#DashboardPanel {
    background-color: #262637;
    border-color: #3b3d52;
    border-radius: 8px;
}

QFrame#StatusBanner {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #292a3d, stop: 1 #252536
    );
    border: 1px solid #414660;
    border-left: 3px solid #89b4fa;
    border-radius: 8px;
}

QWidget#StatusBannerContent, QWidget#StatusBannerActions {
    background: transparent;
}

QFrame[card="true"]:hover, QFrame#MetricCard:hover,
QFrame#DashboardPanel:hover {
    border-color: #4a4a5a;
}

QLabel[heading="page"], QLabel#PageTitle {
    color: #cdd6f4;
    font-size: 20px;
    font-weight: 600;
}

QLabel[heading="section"], QLabel#SectionTitle, QLabel#DeckName {
    color: #cdd6f4;
    font-size: 15px;
    font-weight: 600;
}

QLabel[muted="true"], QLabel#MetricTitle, QLabel#SubtleText {
    color: #9399b2;
}

QLabel[dim="true"], QLabel#MetricDetail {
    color: #6c7086;
}

QLabel#MetricValue {
    color: #cdd6f4;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
    font-size: 20px;
    font-weight: 700;
}

QLabel#MetricTitle {
    font-size: 12px;
}

QLabel#MetricDetail {
    font-size: 11px;
}

QLabel#MetricValue[accent="primary"] { color: #89b4fa; }
QLabel#MetricValue[accent="success"] { color: #a6e3a1; }
QLabel#MetricValue[accent="warning"] { color: #f9e2af; }
QLabel#MetricValue[accent="error"] { color: #f38ba8; }

QLabel#DeviceDot {
    color: #6c7086;
    font-size: 18px;
}

QLabel#DeviceDot[connected="true"] { color: #a6e3a1; }

QLabel[status="success"] { color: #a6e3a1; }
QLabel[status="warning"] { color: #f9e2af; }
QLabel[status="error"] { color: #f38ba8; }

QLabel#DisclaimerTitle {
    color: #f38ba8;
    font-size: 22px;
    font-weight: 700;
}

QFrame#DisclaimerRiskPanel {
    background-color: #30242d;
    border: 1px solid #5b3948;
    border-radius: 6px;
}

QScrollArea#DisclaimerScroll,
QScrollArea#DisclaimerScroll QWidget#qt_scrollarea_viewport,
QWidget#DisclaimerContent {
    background-color: #1e1e2e;
    border: 0;
}

QLabel#DisclaimerRiskText {
    color: #cdd6f4;
    font-size: 14px;
}

QFrame#CommunityRow {
    background-color: #242434;
    border-bottom: 1px solid #3a3a4a;
}

QLabel#CommunityNumber {
    color: #89b4fa;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
    font-weight: 600;
}

QLabel#DisclaimerVersion {
    color: #6c7086;
    font-size: 10px;
}

QFrame#DisclaimerStrip {
    background: transparent;
    border-top: 1px solid #3a3a4a;
}

QLabel#DisclaimerNoticeText {
    color: #9399b2;
    font-size: 11px;
}

QPushButton, QToolButton {
    min-height: 30px;
    padding: 0 12px;
    color: #cdd6f4;
    background-color: #282838;
    border: 1px solid #3a3a4a;
    border-radius: 4px;
    font-weight: 500;
}

QPushButton:hover, QToolButton:hover {
    background-color: #32324a;
    border-color: #4a4a5a;
}

QPushButton:pressed, QToolButton:pressed {
    background-color: #222232;
}

QPushButton:disabled, QToolButton:disabled {
    color: #6c7086;
    background-color: #242434;
    border-color: #323242;
}

QPushButton[variant="primary"], QToolButton[variant="primary"],
QPushButton#PrimaryButton {
    color: #1e1e2e;
    background-color: #89b4fa;
    border-color: #89b4fa;
    font-weight: 600;
}

QPushButton[variant="primary"]:hover, QToolButton[variant="primary"]:hover,
QPushButton#PrimaryButton:hover {
    background-color: #a3c7fb;
    border-color: #a3c7fb;
}

QPushButton[variant="primary"]:disabled, QToolButton[variant="primary"]:disabled,
QPushButton#PrimaryButton:disabled,
QPushButton[variant="danger"]:disabled, QToolButton[variant="danger"]:disabled,
QPushButton#DangerButton:disabled {
    color: #6c7086;
    background-color: #242434;
    border-color: #323242;
}

QPushButton[variant="success"], QToolButton[variant="success"] {
    color: #1e1e2e;
    background-color: #a6e3a1;
    border-color: #a6e3a1;
    font-weight: 600;
}

QPushButton[variant="danger"], QToolButton[variant="danger"],
QPushButton#DangerButton {
    color: #1e1e2e;
    background-color: #f38ba8;
    border-color: #f38ba8;
    font-weight: 600;
}

QPushButton[variant="danger"]:hover, QToolButton[variant="danger"]:hover,
QPushButton#DangerButton:hover {
    background-color: #f5a4bb;
    border-color: #f5a4bb;
}

QPushButton[nav="true"], QToolButton[nav="true"] {
    min-height: 38px;
    padding: 0 14px;
    color: #9399b2;
    background: transparent;
    border: 0;
    border-left: 3px solid transparent;
    border-radius: 0;
    text-align: left;
}

QPushButton#NavButton {
    min-height: 40px;
    padding: 0 14px;
    color: #9399b2;
    background: transparent;
    border: 0;
    border-left: 3px solid transparent;
    border-radius: 0;
    text-align: left;
}

QPushButton#NavButton:hover {
    color: #cdd6f4;
    background-color: #282838;
}

QPushButton#NavButton:checked {
    color: #89b4fa;
    background-color: #282838;
    border-left-color: #89b4fa;
}

QPushButton[nav="true"]:hover, QToolButton[nav="true"]:hover {
    color: #cdd6f4;
    background-color: #282838;
}

QPushButton[nav="true"]:checked, QToolButton[nav="true"]:checked {
    color: #89b4fa;
    background-color: #282838;
    border-left-color: #89b4fa;
}

QPushButton#LinkButton {
    min-width: 0;
    min-height: 24px;
    padding: 0 4px;
    color: #89b4fa;
    background: transparent;
    border: 0;
}

QPushButton#LinkButton:hover {
    color: #a3c7fb;
    background: transparent;
}

QPushButton#DangerGhostButton {
    min-width: 0;
    color: #f38ba8;
    background: transparent;
    border-color: #5b3948;
}

QPushButton#DangerGhostButton:hover {
    color: #ffd5df;
    background-color: #4b2d3a;
    border-color: #f38ba8;
}

QPushButton#FilterButton {
    min-width: 28px;
    min-height: 27px;
    padding: 0 8px;
    color: #9399b2;
    background-color: transparent;
}

QPushButton#FilterButton:checked {
    color: #1e1e2e;
    background-color: #89b4fa;
    border-color: #89b4fa;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
QComboBox, QDateEdit, QTimeEdit, QDateTimeEdit {
    min-height: 30px;
    color: #cdd6f4;
    selection-color: #1e1e2e;
    selection-background-color: #89b4fa;
    background-color: #1e1e2e;
    border: 1px solid #3a3a4a;
    border-radius: 4px;
    padding: 0 9px;
}

QTextEdit, QPlainTextEdit {
    padding: 8px;
}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QComboBox:hover, QDateEdit:hover, QTimeEdit:hover,
QDateTimeEdit:hover {
    border-color: #4a4a5a;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
QDateTimeEdit:focus {
    border-color: #89b4fa;
}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: #6c7086;
    background-color: #242434;
}

QLineEdit#DeckNameInput {
    min-height: 36px;
    font-size: 15px;
    font-weight: 600;
}

QComboBox {
    padding-right: 26px;
}

QComboBox::drop-down {
    width: 24px;
    border: 0;
}

QComboBox::down-arrow {
    width: 8px;
    height: 8px;
}

QComboBox QAbstractItemView {
    color: #cdd6f4;
    background-color: #282838;
    border: 1px solid #3a3a4a;
    selection-color: #cdd6f4;
    selection-background-color: #3a3a4a;
    outline: 0;
}

QCheckBox, QRadioButton {
    spacing: 7px;
    color: #cdd6f4;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 15px;
    height: 15px;
}

QCheckBox::indicator {
    background-color: #1e1e2e;
    border: 1px solid #4a4a5a;
    border-radius: 3px;
}

QCheckBox::indicator:hover {
    border-color: #89b4fa;
}

QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}

QRadioButton::indicator {
    background-color: #1e1e2e;
    border: 1px solid #4a4a5a;
    border-radius: 8px;
}

QRadioButton::indicator:checked {
    background-color: #89b4fa;
    border: 4px solid #1e1e2e;
}

QGroupBox {
    margin-top: 10px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 5px;
    color: #cdd6f4;
    background-color: #282838;
}

QListView, QTreeView, QTableView, QListWidget, QTreeWidget, QTableWidget {
    color: #cdd6f4;
    alternate-background-color: #242434;
    background-color: #1e1e2e;
    border: 1px solid #3a3a4a;
    border-radius: 4px;
    selection-color: #cdd6f4;
    selection-background-color: #3a3a4a;
    outline: 0;
}

QListView::item, QTreeView::item, QTableView::item,
QListWidget::item, QTreeWidget::item, QTableWidget::item {
    min-height: 28px;
    padding: 3px 6px;
}

QListView::item:hover, QTreeView::item:hover, QTableView::item:hover,
QListWidget::item:hover, QTreeWidget::item:hover, QTableWidget::item:hover {
    background-color: #32324a;
}

QHeaderView::section {
    min-height: 30px;
    padding: 0 8px;
    color: #9399b2;
    background-color: #282838;
    border: 0;
    border-right: 1px solid #3a3a4a;
    border-bottom: 1px solid #3a3a4a;
    font-weight: 600;
}

QTabWidget::pane {
    border: 1px solid #3a3a4a;
    background-color: #282838;
}

QTabBar::tab {
    min-height: 32px;
    padding: 0 14px;
    color: #9399b2;
    background: transparent;
    border: 0;
    border-bottom: 2px solid transparent;
}

QTabBar::tab:hover { color: #cdd6f4; }
QTabBar::tab:selected {
    color: #cdd6f4;
    border-bottom-color: #89b4fa;
}

QScrollArea,
QScrollArea QWidget#qt_scrollarea_viewport,
QWidget#PriorityScrollContent,
QWidget#SettingsContent,
QWidget#DashboardContent {
    background: transparent;
    border: 0;
}

QScrollArea#DashboardScroll,
QScrollArea#DashboardScroll QWidget#qt_scrollarea_viewport {
    background: transparent;
    border: 0;
}

QLabel#BackgroundPreview {
    color: #6c7086;
    background-color: #181825;
    border: 1px solid #3a3a4a;
    border-radius: 6px;
}

QProgressBar {
    min-height: 6px;
    max-height: 6px;
    color: transparent;
    background-color: #181825;
    border: 0;
    border-radius: 3px;
}

QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 3px;
}

QScrollBar:vertical {
    width: 8px;
    margin: 0;
    background: transparent;
}

QScrollBar:horizontal {
    height: 8px;
    margin: 0;
    background: transparent;
}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    min-width: 24px;
    min-height: 24px;
    background-color: #3a3a4a;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: #4a4a5a;
}

QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    width: 0;
    height: 0;
    background: transparent;
    border: 0;
}

QSplitter::handle {
    background-color: #3a3a4a;
}

QSplitter::handle:hover {
    background-color: #89b4fa;
}

QMenu, QToolTip {
    color: #cdd6f4;
    background-color: #282838;
    border: 1px solid #3a3a4a;
}

QMenu::item {
    min-height: 26px;
    padding: 2px 22px 2px 10px;
}

QMenu::item:selected {
    background-color: #3a3a4a;
}

QStatusBar {
    color: #9399b2;
    background-color: #181825;
    border-top: 1px solid #3a3a4a;
}

QPlainTextEdit#LogViewer {
    color: #cdd6f4;
    background-color: #191925;
    border: 1px solid #3a3a4a;
    border-radius: 6px;
    padding: 10px;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
    font-size: 12px;
}

QTextEdit#LiveLog {
    color: #cdd6f4;
    background-color: #191925;
    border: 0;
    border-top: 1px solid #3a3a4a;
    border-radius: 0;
    padding: 10px 12px;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
    font-size: 12px;
}
"""

# 为偏好描述性常量名的旧调用方保留兼容别名。
GLOBAL_QSS = APP_STYLESHEET


def build_stylesheet() -> str:
    """返回完整应用样式表。"""

    return APP_STYLESHEET


def apply_theme(application: QApplication) -> None:
    """向应用统一应用 Fusion 风格、字体和样式表。"""

    application.setStyle("Fusion")
    application.setFont(QFont("Microsoft YaHei UI", 9))
    application.setStyleSheet(APP_STYLESHEET)


# 启动编排层和主窗口使用的别名。
apply_app_theme = apply_theme
