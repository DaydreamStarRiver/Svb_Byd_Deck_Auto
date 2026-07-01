#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main PyQt window.

This module contains the main window and wires pages + worker threads.
"""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportIncompatibleMethodOverride=false, reportArgumentType=false

import json
import os
import re
import sys
import time

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.config.paths import get_config_path
from src.config.config_repository import ConfigRepository
from src.ui.common import BACKGROUND_IMAGE, deep_update_dict, get_exe_dir
from src.ui.deck_store import DeckStore
from src.ui.pages.card_priority_page import CardPriorityPage
from src.ui.pages.card_select_page import CardSelectPage
from src.ui.pages.config_page import ConfigPage
from src.ui.pages.my_deck_page import MyDeckPage
from src.ui.pages.share_page import SharePage
from src.ui.workers.log_listener import LogListener
from src.ui.workers.script_runner import ScriptRunner


class DeviceConnectionChecker(QThread):
    """Background ADB/uiautomator2 connection probe for the connect button."""

    finished_signal = pyqtSignal(bool, str)

    def __init__(self, serial: str, parent=None):
        super().__init__(parent)
        self.serial = str(serial or "").strip()

    @staticmethod
    def _is_tcp_serial(serial: str) -> bool:
        return bool(re.match(r"^[^:\s]+:\d+$", str(serial or "").strip()))

    def run(self) -> None:
        serial = self.serial
        if not serial:
            self.finished_signal.emit(False, "设备序列号为空")
            return

        try:
            from adbutils import adb

            connect_msg = ""
            if self._is_tcp_serial(serial):
                try:
                    connect_msg = str(adb.connect(serial, timeout=5) or "")
                except Exception as e:
                    connect_msg = f"adb connect failed: {e}"

            devices = []
            try:
                devices = [str(getattr(d, "serial", "") or "") for d in adb.device_list()]
            except Exception:
                devices = []

            adb_device = adb.device(serial)
            if adb_device is None:
                detail = f"ADB未找到设备 {serial}；当前设备: {devices or '无'}"
                if connect_msg:
                    detail += f"；connect: {connect_msg}"
                self.finished_signal.emit(False, detail)
                return

            import uiautomator2 as u2

            u2_device = u2.connect(serial)
            if u2_device is None:
                self.finished_signal.emit(False, f"uiautomator2连接失败: {serial}")
                return

            detail = f"设备连接成功: {serial}"
            if connect_msg:
                detail += f"；connect: {connect_msg}"
            self.finished_signal.emit(True, detail)
        except Exception as e:
            self.finished_signal.emit(False, f"设备连接检测异常: {e}")


class ShadowverseUI(QMainWindow):
    def __init__(self, run_main_script, command_queue, log_queue):
        super().__init__()
        self._run_main_script = run_main_script
        self._command_queue = command_queue
        self._log_queue = log_queue
        self._device_check_thread = None

        # 显示启动弹窗，如果用户不同意则退出程序
        if not self.show_startup_dialog():
            sys.exit(0)
        self.init_ui()

    def show_startup_dialog(self):
        """显示启动弹窗"""
        # 检查是否已经同意过协议
        config_path = get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                if config_data.get("agreed_to_disclaimer", False):
                    return True
            except Exception:
                pass

        # 创建自定义消息框
        dialog = QMessageBox()
        dialog.setWindowTitle("免责声明")
        dialog.setIcon(QMessageBox.Information)

        # 构建HTML内容，设置不同颜色和字体样式
        message = ""
        message += "<p><span style='color: red; font-weight: bold; font-size: 14pt;'>免责声明</span></p>"
        message += "<p>&nbsp;</p>"
        message += "<p><span style='color: red;'>本工具仅供<strong>个人学习研究</strong>使用，严禁用于任何<strong>商业盈利</strong>目的</span></p>"
        message += "<p><span style='color: red;'>使用本工具可能违反游戏用户协议，<strong>可能导致账号被封禁的严重后果</strong></span></p>"
        message += "<p><span style='color: red;'>开发者不对使用本工具造成的任何损失承担法律责任</span></p>"
        message += "<p>&nbsp;</p>"
        message += "<p><span style='color: red; font-weight: bold;'>本工具属于免费发布，禁止任何形式倒卖！！！</span></p>"
        message += "<p><span style='color: blue;'>工具交流开发群：892100160</span></p>"
        message += "<p><span style='color: blue;'>工具交流群：1070074638</span></p>"
        message += "<p><span style='color: blue;'>工具开发群：883457604</span></p>"

        dialog.setTextFormat(Qt.RichText)
        dialog.setText(message)

        # 添加复选框
        checkbox = QCheckBox("同意一次后不再显示此弹窗")
        dialog.setCheckBox(checkbox)

        # 设置按钮
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.button(QMessageBox.Yes).setText("同意")
        dialog.button(QMessageBox.No).setText("不同意")

        # 执行弹窗并获取结果
        result = dialog.exec_()

        # 保存同意状态（写入app根目录consent.txt；可选同步到config.json）
        if result == QMessageBox.Yes:
            try:
                from src.utils.consent_utils import save_consent

                save_consent(persist_to_config=checkbox.isChecked())
            except Exception:
                pass

        # 返回是否同意（Yes对应QMessageBox.Yes）
        return result == QMessageBox.Yes

    def init_ui(self):
        self.setWindowTitle("影之诗自动对战脚本[完全免费]")
        self.setGeometry(100, 100, 900, 700)
        self.setup_ui()

        self.script_thread = None
        self.run_time = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_run_time)

        # 初始化状态
        self.current_turn = 0
        self.battle_count = 0
        self.turn_count = 0

        # 日志监听器
        self.log_listener = LogListener(self._log_queue, self)
        self.log_listener.log_signal.connect(self.append_log)
        self.log_listener.start()

    def setup_ui(self):
        # 主窗口设置
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint)

        # 设置窗口背景
        self.set_background()

        # 主控件
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        central_widget.setStyleSheet(
            """
            #CentralWidget {
                background-color: rgba(30, 30, 40, 180);
                border-radius: 15px;
                padding: 15px;
            }
            QLabel {
                color: #E0E0FF;
                font-weight: bold;
                font-size: 12px;
            }
            QLineEdit {
                background-color: rgba(50, 50, 70, 200);
                color: #FFFFFF;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 5px;
            }
            QPushButton {
                background-color: #4A4A7F;
                color: #FFFFFF;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-weight: bold;
                min-width: 80px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #5A5A9F;
            }
            QPushButton:pressed {
                background-color: #3A3A6F;
            }
            QTextEdit {
                background-color: rgba(25, 25, 35, 220);
                color: #66AAFF;
                border: 1px solid #444477;
                border-radius: 5px;
            }
            #StatsFrame {
                background-color: rgba(40, 40, 60, 200);
                border: 1px solid #555588;
                border-radius: 8px;
                padding: 10px;
            }
            .StatLabel {
                color: #AACCFF;
                font-size: 12px;
            }
            .StatValue {
                color: #FFFF88;
                font-size: 14px;
                font-weight: bold;
            }
            #TitleLabel {
                font-size: 20px;
                color: #88AAFF;
                font-weight: bold;
                padding: 10px 0;
            }
            #WindowControlButton {
                background: transparent;
                border: none;
                min-width: 30px;
                max-width: 30px;
                min-height: 30px;
                max-height: 30px;
                padding: 0;
                margin: 0;
            }
            #WindowControlButton:hover {
                background-color: rgba(255, 255, 255, 30);
            }
            #CloseButton:hover {
                background-color: rgba(255, 0, 0, 100);
            }
            QGroupBox {
                border: 1px solid #555588;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-size: 14px;
                color: #88AAFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 5px;
            }
            QComboBox {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 5px;
                font-size: 12px;
            }
            QComboBox:hover {
                background-color: rgba(90, 90, 140, 180);
            }
            QToolButton {
                background: transparent;
                border: none;
                color: #88AAFF;
                font-weight: bold;
                font-size: 14px;
            }
            QToolButton:hover {
                color: #AACCFF;
            }
        """
        )

        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 顶部栏布局
        top_bar_layout = QHBoxLayout()
        top_bar_layout.setContentsMargins(0, 0, 0, 0)
        top_bar_layout.setSpacing(15)

        # 添加程序标题
        title_label = QLabel("影之诗自动对战脚本[完全免费]")
        title_label.setObjectName("TitleLabel")
        top_bar_layout.addWidget(title_label)

        # 添加空白区域使按钮靠右
        top_bar_layout.addStretch()

        # 添加窗口控制按钮
        self.minimize_btn = QPushButton("－")
        self.minimize_btn.setObjectName("WindowControlButton")
        self.minimize_btn.clicked.connect(self.showMinimized)

        self.maximize_btn = QPushButton("□")
        self.maximize_btn.setObjectName("WindowControlButton")
        self.maximize_btn.clicked.connect(self.toggle_maximize)

        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("WindowControlButton")
        self.close_btn.setObjectName("CloseButton")
        self.close_btn.clicked.connect(self.close)

        top_bar_layout.addWidget(self.minimize_btn)
        top_bar_layout.addWidget(self.maximize_btn)
        top_bar_layout.addWidget(self.close_btn)

        main_layout.addLayout(top_bar_layout)

        # 创建堆叠窗口
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)

        # Shared deck store (pages subscribe; no mutual calls).
        self.deck_store = DeckStore(
            decks_dir=os.path.join(get_exe_dir(), "saved_decks"),
            parent=self,
        )

        # 创建主页面
        self.main_page = QWidget()
        self.setup_main_page()
        self.stacked_widget.addWidget(self.main_page)

        # 创建卡组选择页面
        self.card_select_page = CardSelectPage(self)
        self.stacked_widget.addWidget(self.card_select_page)

        # 创建参数设置页面
        self.config_page = ConfigPage(self)
        self.stacked_widget.addWidget(self.config_page)

        # 创建卡组分享页面
        self.share_page = SharePage(self)
        self.stacked_widget.addWidget(self.share_page)

        # 创建自己卡组页面
        self.my_deck_page = MyDeckPage(self)
        self.stacked_widget.addWidget(self.my_deck_page)

        # 创建卡牌优先级独立页面
        self.card_priority_page = CardPriorityPage(self)
        self.stacked_widget.addWidget(self.card_priority_page)

        self.setCentralWidget(central_widget)

    def set_background(self):
        # 创建调色板
        palette = self.palette()

        # 检查背景图片是否存在
        bg_path = os.path.join(get_exe_dir(), BACKGROUND_IMAGE)
        if os.path.exists(bg_path):
            # 加载背景图片并缩放以适应窗口
            background = QPixmap(bg_path).scaled(
                self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
            )
            palette.setBrush(QPalette.Window, QBrush(background))
        else:
            # 如果图片不存在，使用半透明黑色背景
            palette.setColor(QPalette.Window, QColor(30, 30, 40, 180))

        self.setPalette(palette)

    def resizeEvent(self, event):
        # 当窗口大小改变时，重新设置背景图片
        self.set_background()
        super().resizeEvent(event)

    def setup_main_page(self):
        layout = QVBoxLayout(self.main_page)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)

        # === 控制区域 ===
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        control_layout.setSpacing(15)

        # 左侧控制区域
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # 状态设置
        status_frame = QFrame()
        status_frame.setObjectName("StatsFrame")
        frame_layout = QVBoxLayout(status_frame)

        # 服务器切换
        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("服务器:"))
        self.server_combo = QComboBox()
        self.server_combo.addItems(["国服", "国际服"])
        self.server_combo.setStyleSheet(
            "background-color: rgba(80, 80, 120, 180); color: white;"
        )
        server_layout.addWidget(self.server_combo)
        server_layout.addStretch()
        frame_layout.addLayout(server_layout)

        # ADB端口
        adb_layout = QHBoxLayout()
        adb_layout.addWidget(QLabel("ADB 端口:"))
        self.adb_input = QLineEdit("127.0.0.1:16384")
        self.adb_input.setFixedWidth(150)  # 增加宽度以完整显示地址
        self.adb_input.setStyleSheet(
            "background-color: rgba(80, 80, 120, 180); color: white;"
        )
        adb_layout.addWidget(self.adb_input)
        adb_layout.addStretch()
        frame_layout.addLayout(adb_layout)

        # 深色识别、庆典模式和空过设置
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("深色识别:"))
        self.deep_color_checkbox = QCheckBox()
        self.deep_color_checkbox.setStyleSheet(
            "QCheckBox::indicator { width: 20px; height: 20px; }"
        )
        mode_layout.addWidget(self.deep_color_checkbox)
        mode_layout.addSpacing(30)
        mode_layout.addWidget(QLabel("庆典模式:"))
        self.gala_mode_checkbox = QCheckBox()
        self.gala_mode_checkbox.setStyleSheet(
            "QCheckBox::indicator { width: 20px; height: 20px; }"
        )
        mode_layout.addWidget(self.gala_mode_checkbox)
        mode_layout.addSpacing(30)
        mode_layout.addWidget(QLabel("启用空过:"))
        self.auto_pass_checkbox = QCheckBox()
        self.auto_pass_checkbox.setStyleSheet(
            "QCheckBox::indicator { width: 20px; height: 20px; }"
        )
        mode_layout.addWidget(self.auto_pass_checkbox)
        mode_layout.addStretch()
        frame_layout.addLayout(mode_layout)

        left_layout.addWidget(status_frame)

        # 控制按钮
        btn_layout = QGridLayout()
        self.connect_btn = QPushButton("连接设备")
        self.connect_btn.setFixedHeight(35)
        self.connect_btn.clicked.connect(self.connect_device)

        self.start_btn = QPushButton("开始运行")
        self.start_btn.setFixedHeight(35)
        self.start_btn.clicked.connect(self.start_script)

        self.pause_btn = QPushButton("暂停运行")
        self.pause_btn.setFixedHeight(35)
        self.pause_btn.clicked.connect(self.pause_script)

        self.resume_btn = QPushButton("恢复运行")
        self.resume_btn.setFixedHeight(35)
        self.resume_btn.clicked.connect(self.resume_script)

        self.stop_btn = QPushButton("停止运行")
        self.stop_btn.setFixedHeight(35)
        self.stop_btn.clicked.connect(self.stop_script)

        # 第一行：连接设备 | 开始运行
        btn_layout.addWidget(self.connect_btn, 0, 0)
        btn_layout.addWidget(self.start_btn, 0, 1)

        # 第二行：暂停运行 | 恢复运行
        btn_layout.addWidget(self.pause_btn, 1, 0)
        btn_layout.addWidget(self.resume_btn, 1, 1)

        # 第三行：停止运行（跨两列）
        btn_layout.addWidget(self.stop_btn, 2, 0, 1, 2)

        left_layout.addLayout(btn_layout)
        control_layout.addWidget(left_widget)

        # 中间统计区域
        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)

        stats_frame = QFrame()
        stats_frame.setObjectName("StatsFrame")
        grid_layout = QGridLayout(stats_frame)

        # 当前状态和运行时间
        grid_layout.addWidget(QLabel("当前状态:"), 0, 0)
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: #FF5555;")
        grid_layout.addWidget(self.status_label, 0, 1)

        grid_layout.addWidget(QLabel("运行时间:"), 1, 0)
        self.run_time_label = QLabel("00:00:00")
        self.run_time_label.setObjectName("StatValue")
        grid_layout.addWidget(self.run_time_label, 1, 1)

        # 对战次数
        grid_layout.addWidget(QLabel("对战次数:"), 2, 0)
        self.battle_count_label = QLabel("0")
        self.battle_count_label.setObjectName("StatValue")
        grid_layout.addWidget(self.battle_count_label, 2, 1)

        stats_layout.addWidget(stats_frame)
        control_layout.addWidget(stats_widget)

        # 右侧功能按钮区域
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(8)

        self.card_select_btn = QPushButton("卡组选择")
        self.card_select_btn.setFixedHeight(35)
        self.card_select_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))

        self.config_btn = QPushButton("参数设置")
        self.config_btn.setFixedHeight(35)
        self.config_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))

        self.card_priority_btn = QPushButton("卡牌设置")
        self.card_priority_btn.setFixedHeight(35)
        self.card_priority_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(5))

        self.my_deck_btn = QPushButton("我的卡组")
        self.my_deck_btn.setFixedHeight(35)
        self.my_deck_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(4))

        self.share_btn = QPushButton("卡组应用和分享")
        self.share_btn.setFixedHeight(35)
        self.share_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(3))

        # 紧凑排列按钮
        right_layout.addWidget(self.card_select_btn)  # 卡组选择按钮
        right_layout.addWidget(self.my_deck_btn)  # 我的卡组按钮
        right_layout.addWidget(self.card_priority_btn)  # 卡牌设置按钮
        right_layout.addWidget(self.config_btn)  # 参数设置按钮
        right_layout.addWidget(self.share_btn)  # 卡组应用和分享按钮
        right_layout.addStretch()  # 底部间距

        control_layout.addWidget(right_widget)  # 右侧功能按钮区域
        layout.addWidget(control_widget)  # 控制按钮区域

        # 日志区域
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)

        log_label = QLabel("运行日志:")
        log_layout.addWidget(log_label)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(300)  # 增大日志区域高度
        log_layout.addWidget(self.log_output)

        layout.addWidget(log_widget, 1)

        # 初始化按钮状态
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

        # 加载当前配置设置
        self.load_current_config()

    def load_current_config(self):
        """加载当前配置设置"""
        config_path = get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                # 设置服务器选项
                devices = config.get("devices", [])
                if devices:
                    # 获取最后一个设备作为当前设备
                    last_device = devices[-1]
                    self.adb_input.setText(last_device["serial"])

                    if last_device.get("is_global", False):
                        self.server_combo.setCurrentText("国际服")
                    else:
                        self.server_combo.setCurrentText("国服")

                    # 设置深色识别选项
                    self.deep_color_checkbox.setChecked(
                        last_device.get("screenshot_deep_color", False)
                    )
                    # 设置庆典模式选项
                    self.gala_mode_checkbox.setChecked(last_device.get("gala_mode", False))
                    # 设置空过选项
                    game_config = config.get("game", {})
                    self.auto_pass_checkbox.setChecked(
                        game_config.get("enable_auto_pass", False)
                    )
                else:
                    # 如果没有设备配置，设置默认值
                    self.adb_input.setText("127.0.0.1:16384")
            except Exception as e:
                self.log_output.append(f"加载配置失败: {str(e)}")
                self.adb_input.setText("127.0.0.1:16384")
        else:
            self.adb_input.setText("127.0.0.1:16384")

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.maximize_btn.setText("□")
        else:
            self.showMaximized()
            self.maximize_btn.setText("❐")

    def connect_device(self):
        if self.is_script_running():
            QMessageBox.warning(
                self,
                "运行中",
                "脚本运行中，禁止修改设备/配置。请先停止脚本后再连接或修改设置。",
            )
            try:
                self.connect_btn.setEnabled(True)
            except Exception:
                pass
            return

        adb_port = self.adb_input.text()
        self.append_log(f"正在连接设备: {adb_port}...")
        self.connect_btn.setEnabled(False)

        # 获取服务器、深色识别、庆典模式和空过设置
        is_global = self.server_combo.currentText() == "国际服"
        deep_color = self.deep_color_checkbox.isChecked()
        gala_mode = self.gala_mode_checkbox.isChecked()
        auto_pass = self.auto_pass_checkbox.isChecked()

        # 保存设备配置（不写入配置文件，直接用于脚本运行）
        # 包含卡组策略配置
        strategy_config = {}
        if hasattr(self, "card_select_page") and hasattr(self.card_select_page, "strategy_config"):
            strategy_config = self.card_select_page.strategy_config or {}

        self._device_config = {
            "name": f"模拟器-{adb_port}",
            "serial": adb_port,
            "is_global": is_global,
            "screenshot_deep_color": deep_color,
            "gala_mode": gala_mode,
            "strategy_config": strategy_config,
        }
        self._auto_pass = auto_pass

        # 写入配置文件（保存供下次启动使用）
        self._save_device_config_to_file(adb_port, is_global, deep_color, gala_mode, auto_pass)

        self.append_log(
            f"设备配置已准备: 服务器={self.server_combo.currentText()}, "
            f"深色识别={'开启' if deep_color else '关闭'}, "
            f"庆典模式={'开启' if gala_mode else '关闭'}, "
            f"启用空过={'开启' if auto_pass else '关闭'}"
        )

        # 创建脚本运行线程（传递设备配置）
        self.script_thread = ScriptRunner(self._run_main_script, self._log_queue, self, device_config=self._device_config)
        self.script_thread.status_signal.connect(self.update_status)
        self.script_thread.stats_signal.connect(self.update_stats)

        self.status_label.setText("连接中...")
        self.status_label.setStyleSheet("color: #FFFF55;")
        self._device_check_thread = DeviceConnectionChecker(adb_port, self)
        self._device_check_thread.finished_signal.connect(self._on_device_connection_checked)
        self._device_check_thread.start()

    def _save_device_config_to_file(self, adb_port, is_global, deep_color, gala_mode, auto_pass):
        """保存设备配置到配置文件（供下次启动读取）"""
        try:
            config_path = get_config_path()
            repo = ConfigRepository(config_path)
            existing, _, parse_err = repo.load_existing(allow_default_on_error=False)
            
            if existing is None:
                self.append_log(f"保存配置失败: config.json解析错误: {str(parse_err or '')}")
                return

            device_update = {
                "name": f"模拟器-{adb_port}",
                "serial": adb_port,
                "is_global": is_global,
                "screenshot_deep_color": deep_color,
                "gala_mode": gala_mode,
            }

            existing_devices = existing.get("devices", [])
            if not isinstance(existing_devices, list):
                existing_devices = []

            # 更新或添加设备
            updated_devices = []
            found = False
            for d in existing_devices:
                if isinstance(d, dict) and d.get("serial") == adb_port:
                    merged = dict(d)
                    deep_update_dict(merged, device_update)
                    updated_devices.append(merged)
                    found = True
                else:
                    updated_devices.append(d)

            if not found:
                updated_devices.append(device_update)

            res = repo.update(
                {"devices": updated_devices, "game": {"enable_auto_pass": auto_pass}},
                refuse_on_parse_error=True,
                indent=4,
                ensure_ascii=False,
            )

            if res.ok:
                self.append_log("设备配置已保存到 config.json")
            else:
                raise RuntimeError(res.error or "config write failed")

        except Exception as e:
            self.append_log(f"保存配置文件失败: {str(e)}")

    def _check_device_connection(self, serial: str) -> bool:
        """检查设备是否能成功连接"""
        try:
            from adbutils import adb

            adb_device = adb.device(serial)
            if adb_device is None:
                return False

            import uiautomator2 as u2

            u2_device = u2.connect(serial)
            if u2_device is None:
                return False

            return True
        except Exception as e:
            self.append_log(f"设备连接检测异常: {str(e)}")
            return False

    def _on_device_connection_checked(self, ok: bool, message: str) -> None:
        if ok:
            self.start_btn.setEnabled(True)
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet("color: #55FF55;")
            self.append_log(message)
        else:
            self.connect_btn.setEnabled(True)
            self.start_btn.setEnabled(False)
            self.status_label.setText("连接失败")
            self.status_label.setStyleSheet("color: #FF5555;")
            self.append_log(message or "设备连接失败")

        try:
            if self._device_check_thread is not None:
                self._device_check_thread.deleteLater()
        except Exception:
            pass
        self._device_check_thread = None

    def is_script_running(self) -> bool:
        """Return True when automation thread is active."""

        try:
            return bool(self.script_thread is not None and self.script_thread.isRunning())
        except Exception:
            return False

    def append_log(self, message):
        """安全地添加日志到UI"""
        self.log_output.append(message)
        # 自动滚动到底部
        self.log_output.verticalScrollBar().setValue(
            self.log_output.verticalScrollBar().maximum()
        )

        # 解析对战开始日志，更新对战次数
        if "[对战开始]" in message:
            try:
                import re

                match = re.search(r"第(\d+)场对战", message)
                if match:
                    battle_count = int(match.group(1))
                    self.battle_count = battle_count
                    self.battle_count_label.setText(str(battle_count))
            except Exception:
                pass

    def start_script(self):
        if self.script_thread and not self.script_thread.isRunning():
            self.script_thread.start()
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)  # 开始时恢复按钮禁用
            self.stop_btn.setEnabled(True)
            self.timer.start(1000)
            self.append_log("===== 脚本开始运行 =====")

    def pause_script(self):
        """暂停脚本执行"""
        if self.script_thread and self.script_thread.isRunning():
            # 发送暂停命令
            self._command_queue.put("p")
            self.status_label.setText("已暂停")
            self.status_label.setStyleSheet("color: #FFFF55;")
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
            self.timer.stop()
            self.append_log("[控制] 脚本已暂停")

    def resume_script(self):
        """恢复脚本执行"""
        if self.script_thread and self.script_thread.isRunning():
            # 发送恢复命令
            self._command_queue.put("r")
            self.status_label.setText("运行中")
            self.status_label.setStyleSheet("color: #55FF55;")
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.timer.start(1000)
            self.append_log("[控制] 脚本已恢复")

    def stop_script(self):
        """停止脚本执行（发送退出命令）。"""

        if self.script_thread and self.script_thread.isRunning():
            try:
                self._command_queue.put("e")
            except Exception:
                pass
            self.append_log("[控制] 已发送停止命令，等待脚本退出...")
            try:
                self.pause_btn.setEnabled(False)
                self.resume_btn.setEnabled(False)
                self.stop_btn.setEnabled(False)
            except Exception:
                pass

            # 避免“已发停止命令但线程长时间不退出”导致看起来无法停止。
            self._force_stop_script_thread(timeout_ms=8000)

    def _force_stop_script_thread(self, timeout_ms: int = 8000) -> bool:
        """等待脚本线程退出；超时后执行一次强制终止兜底。"""

        if not (self.script_thread and self.script_thread.isRunning()):
            return True

        if self.script_thread.wait(max(200, int(timeout_ms))):
            return True

        self.append_log("[控制] 停止超时，尝试强制结束脚本线程...")
        try:
            self.script_thread.terminate()
        except Exception:
            pass

        if self.script_thread.wait(1500):
            self.append_log("[控制] 已强制结束脚本线程")
            return True

        self.append_log("[控制] 强制结束失败，请关闭程序后重试")
        return False

    def calculate_avg_turns(self):
        battle_count = int(self.battle_count_label.text()) if self.battle_count_label.text() else 0
        turn_count = int(self.turn_count_label.text()) if self.turn_count_label.text() else 0
        return round(turn_count / battle_count, 2) if battle_count > 0 else 0

    def update_status(self, status):
        self.status_label.setText(status)
        if status == "运行中":
            self.status_label.setStyleSheet("color: #55FF55;")
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        elif status == "已暂停":
            self.status_label.setStyleSheet("color: #FFFF55;")
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
        else:
            self.status_label.setStyleSheet("color: #FF5555;")
            try:
                self.stop_btn.setEnabled(False)
            except Exception:
                pass
            try:
                self.pause_btn.setEnabled(False)
                self.resume_btn.setEnabled(False)
                if self.script_thread is not None:
                    self.start_btn.setEnabled(True)
                self.timer.stop()
            except Exception:
                pass

    def update_stats(self, stats):
        # 不再更新被删除的统计项
        run_time = stats.get("run_time", 0)
        hours = run_time // 3600
        minutes = (run_time % 3600) // 60
        seconds = run_time % 60
        self.run_time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def update_run_time(self):
        # 更新运行时间显示
        if self.script_thread and self.script_thread.isRunning():
            run_time = int(time.time() - self.script_thread.start_time)
            hours = run_time // 3600
            minutes = (run_time % 3600) // 60
            seconds = run_time % 60
            self.run_time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    # 添加鼠标事件处理以实现窗口拖动
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if hasattr(self, "drag_position") and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def closeEvent(self, event):
        """窗口关闭事件处理"""
        # 停止日志监听
        if self.log_listener.isRunning():
            self.log_listener.stop()
            self.log_listener.wait(1000)

        # 停止脚本线程
        if self.script_thread and self.script_thread.isRunning():
            # 发送退出命令
            try:
                self._command_queue.put("e")
            except Exception:
                pass
            self._force_stop_script_thread(timeout_ms=5000)

        event.accept()
