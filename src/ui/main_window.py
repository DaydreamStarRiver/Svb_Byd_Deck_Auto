#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口模块
集成所有UI页面并提供主程序入口功能
"""

import os
import sys
import json
import time
import threading
import queue
from main import command_queue  # 导入全局命令队列
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTabWidget, QStackedWidget, QTextEdit, QLineEdit, QCheckBox,
    QComboBox, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QFont, QIcon, QPixmap, QClipboard, QBrush

# 导入页面模块
from src.ui.pages.config_page import ConfigPage
from src.ui.pages.card_select_page import CardSelectPage
from src.ui.pages.my_deck_page import MyDeckPage
from src.ui.pages.share_page import SharePage
from src.ui.utils.ui_utils import get_exe_dir, load_custom_font
from src.ui.notification_manager import NotificationManager

class LogListener(threading.Thread):
    """日志监听线程"""
    def __init__(self, log_output, interval=1):
        super().__init__(daemon=True)
        self.log_output = log_output
        self.interval = interval
        self.running = True

    def run(self):
        while self.running:
            time.sleep(self.interval)
            # 实际项目中可以在这里实现日志文件监听

    def stop(self):
        self.running = False

class ScriptRunner(threading.Thread):
    """脚本运行线程"""
    def __init__(self, parent):
        super().__init__(daemon=True)
        self.parent = parent
        self.running = False
        self.paused = False
        self.start_time = 0
        self.elapsed_time = 0

    def run(self):
        try:
            self.running = True
            self.start_time = time.time() - self.elapsed_time
            self.parent.update_status("运行中")
            
            # 清空命令队列，确保不会有历史命令影响本次运行
            while not command_queue.empty():
                try:
                    command_queue.get_nowait()
                    command_queue.task_done()
                except queue.Empty:
                    break
            
            # 导入并运行主脚本
            from main import main as run_main_script
            run_main_script(enable_command_listener=True)
            
        except Exception as e:
            import traceback
            self.parent.append_log(f"[错误] 脚本运行失败: {str(e)}")
            self.parent.append_log(f"[错误详情] {traceback.format_exc()}")
            self.parent.update_status("错误")
        finally:
            self.running = False

    def stop(self):
        # 实现优雅停止
        self.running = False
        
        # 如果有全局命令队列，发送退出命令
        if 'command_queue' in globals():
            try:
                import queue
                command_queue.put('e')
                # 等待一段时间让命令生效
                import time
                time.sleep(2)
            except Exception:
                pass
        
        # 如果线程仍然在运行，强制终止
        if self.is_alive():
            # 注意：强制终止线程不是最佳实践，但在这种情况下是必要的
            self.parent.append_log("[警告] 脚本线程未能正常终止")

    def pause(self):
        if self.running and not self.paused:
            self.paused = True
            self.elapsed_time = time.time() - self.start_time
            self.parent.update_status("已暂停")

    def resume(self):
        if self.running and self.paused:
            self.paused = False
            self.start_time = time.time() - self.elapsed_time
            self.parent.update_status("运行中")

class ShadowverseUI(QMainWindow):
    """主窗口类"""
    def __init__(self):
        super().__init__()
        self.script_runner = None
        self.log_listener = None
        self.notification_manager = NotificationManager()
        self.clipboard = QApplication.clipboard()
        self.start_time = 0
        # 窗口调整大小功能已禁用
        self.dragging = False  # 仅保留窗口拖动功能
        self.setup_ui()
        
        # 加载示例运行日志

        


    def setup_ui(self):
        # 窗口基础设置
        self.setWindowTitle("Shadowverse Automation")
        
        # 从配置文件加载窗口大小
        config_path = os.path.join(get_exe_dir(), "config.json")
        window_width = 1200
        window_height = 1000
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    if "window" in config_data:
                        if "width" in config_data["window"]:
                            window_width = config_data["window"]["width"]
                        if "height" in config_data["window"]:
                            window_height = config_data["window"]["height"]
            except Exception as e:
                print(f"加载窗口大小配置失败: {str(e)}")
        
        # 设置窗口位置和大小
        self.setGeometry(100, 100, window_width, window_height)
        
        # 添加必要的窗口标志以支持调整大小
        # 设置窗口标志（已禁用拉伸功能）
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowSystemMenuHint | Qt.WindowMinimizeButtonHint)
        
        # 设置最小窗口尺寸
        self.setMinimumSize(800, 600)
        # 已实现自定义窗口边缘调整大小功能
        
        # 设置背景
        self.set_background()
        
        # 中央部件
        central_widget = QWidget()
        central_widget.setStyleSheet("background-color: transparent;")  # 设置为透明，不覆盖背景图片
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 顶部栏
        top_bar = QWidget()
        top_bar.setStyleSheet("background-color: rgba(40, 40, 70, 220); height: 40px;")
        top_bar.setFixedHeight(40)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 0, 10, 0)
        
        # 标题
        title_label = QLabel("Shadowverse Auto")
        title_label.setStyleSheet("color: #88AAFF; font-size: 16px; font-weight: bold;")
        top_layout.addWidget(title_label)
        top_layout.addStretch()
        
        # 窗口控制按钮
        min_btn = QPushButton("_")
        min_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                width: 30px;
                height: 30px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: rgba(60, 60, 90, 200);
            }
        """)
        min_btn.clicked.connect(self.showMinimized)
        
        max_btn = QPushButton("□")
        max_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                width: 30px;
                height: 30px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(60, 60, 90, 200);
            }
        """)
        max_btn.clicked.connect(self.toggle_maximize)
        
        close_btn = QPushButton("×")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                width: 30px;
                height: 30px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(200, 60, 60, 200);
            }
        """)
        close_btn.clicked.connect(self.close)
        
        top_layout.addWidget(min_btn)
        top_layout.addWidget(max_btn)
        top_layout.addWidget(close_btn)
        
        main_layout.addWidget(top_bar)
        
        # 堆叠窗口
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)
        
        # 主页面
        self.main_page = QWidget()
        self.setup_main_page()
        self.stacked_widget.addWidget(self.main_page)
        
        # 卡片选择页面
        self.card_select_page = CardSelectPage(self)
        self.stacked_widget.addWidget(self.card_select_page)
        
        # 参数设置页面
        self.config_page = ConfigPage(self)
        self.stacked_widget.addWidget(self.config_page)
        
        # 分享页面
        self.share_page = SharePage(self)
        self.stacked_widget.addWidget(self.share_page)
        
        # 我的卡组页面
        self.my_deck_page = MyDeckPage(self)
        self.stacked_widget.addWidget(self.my_deck_page)
        
        # 初始化状态
        self.is_maximized = False
        self.dragging = False
        self.offset = QPoint()
        self.resizing = False
        self.resize_direction = None
        
        # 加载配置
        self.load_current_config()
        
        # 启动日志监听
        self.log_listener = LogListener(self.log_output)
        self.log_listener.start()

    def setup_main_page(self):
        """设置主页面布局"""
        main_layout = QVBoxLayout(self.main_page)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # 顶部状态区域
        status_layout = QHBoxLayout()
        status_layout.setSpacing(20)
        
        # 左侧连接设置
        left_section = QWidget()
        left_section.setStyleSheet("background-color: rgba(50, 50, 80, 180); border-radius: 10px;")
        left_layout = QVBoxLayout(left_section)
        left_layout.setContentsMargins(15, 15, 15, 15)
        left_layout.setSpacing(10)
        
        # 服务器选择
        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("服务器:"))
        self.server_combo = QComboBox()
        self.server_combo.addItem("国服", "cn")
        self.server_combo.addItem("国际服", "intl")
        self.server_combo.setStyleSheet("""
            QComboBox {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 5px;
                min-width: 100px;
            }
        """)
        server_layout.addWidget(self.server_combo)
        server_layout.addStretch()
        left_layout.addLayout(server_layout)
        
        # ADB端口
        adb_layout = QHBoxLayout()
        adb_layout.addWidget(QLabel("ADB端口:"))
        self.adb_port_input = QLineEdit("127.0.0.1:16384")
        self.adb_port_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 5px;
                min-width: 100px;
            }
        """)
        adb_layout.addWidget(self.adb_port_input)
        
        # 深色识别
        self.dark_mode_check = QCheckBox("深色识别")
        self.dark_mode_check.setStyleSheet("""
            QCheckBox {
                color: white;
            }
        """)
        adb_layout.addWidget(self.dark_mode_check)
        adb_layout.addStretch()
        left_layout.addLayout(adb_layout)
        
        # 连接按钮
        self.connect_btn = QPushButton("连接设备")
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A7AFF;
                color: white;
                border-radius: 5px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5A8AFF;
            }
        """)
        self.connect_btn.clicked.connect(self.connect_device)
        left_layout.addWidget(self.connect_btn)
        
        # 控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)
        
        self.start_btn = QPushButton("开始")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4AFF4A;
                color: white;
                border-radius: 5px;
                padding: 8px;
                font-weight: bold;
                flex: 1;
            }
            QPushButton:hover {
                background-color: #5AFF5A;
            }
        """)
        self.start_btn.clicked.connect(self.start_script)
        
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFAA4A;
                color: white;
                border-radius: 5px;
                padding: 8px;
                font-weight: bold;
                flex: 1;
            }
            QPushButton:hover {
                background-color: #FFBA5A;
            }
        """)
        self.pause_btn.clicked.connect(self.pause_script)
        
        self.resume_btn = QPushButton("恢复")
        self.resume_btn.setStyleSheet("""
            QPushButton {
                background-color: #4AFFAA;
                color: white;
                border-radius: 5px;
                padding: 8px;
                font-weight: bold;
                flex: 1;
            }
            QPushButton:hover {
                background-color: #5AFFBA;
            }
        """)
        self.resume_btn.clicked.connect(self.resume_script)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.pause_btn)
        control_layout.addWidget(self.resume_btn)
        left_layout.addLayout(control_layout)
        
        # 状态显示
        self.status_label = QLabel("状态: 未连接")
        self.status_label.setStyleSheet("color: #AACCFF; font-weight: bold;")
        left_layout.addWidget(self.status_label)
        
        # 运行时间
        self.run_time_label = QLabel("运行时间: 00:00:00")
        self.run_time_label.setStyleSheet("color: #AACCFF; font-weight: bold;")
        left_layout.addWidget(self.run_time_label)
        
        # 右侧功能按钮
        right_section = QWidget()
        right_section.setStyleSheet("background-color: rgba(50, 50, 80, 180); border-radius: 10px;")
        right_layout = QVBoxLayout(right_section)
        right_layout.setContentsMargins(15, 15, 15, 15)
        right_layout.setSpacing(15)
        
        # 功能按钮组
        function_btns = [
            ("卡组选择", lambda: self.stacked_widget.setCurrentIndex(1)),
            ("参数设置", lambda: self.stacked_widget.setCurrentIndex(2)),
            ("我的卡组", lambda: self.stacked_widget.setCurrentIndex(4)),
            ("卡组应用和分享", lambda: self.stacked_widget.setCurrentIndex(3))
        ]
        
        for text, callback in function_btns:
            btn = QPushButton(text)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(80, 80, 120, 180);
                    color: white;
                    border: 1px solid #5A5A8F;
                    border-radius: 8px;
                    padding: 12px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(90, 90, 140, 180);
                    border: 1px solid #88AAFF;
                }
            """)
            btn.clicked.connect(callback)
            right_layout.addWidget(btn)
        
        right_layout.addStretch()
        
        status_layout.addWidget(left_section, 3)
        status_layout.addWidget(right_section, 2)
        main_layout.addLayout(status_layout)
        
        # 日志区域
        log_group = QWidget()
        log_group.setStyleSheet("background-color: rgba(50, 50, 80, 180); border-radius: 10px;")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(15, 15, 15, 15)
        log_layout.setSpacing(10)
        
        log_title = QLabel("运行日志")
        log_title.setStyleSheet("color: #88AAFF; font-weight: bold; font-size: 14px;")
        log_layout.addWidget(log_title)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("""
            QTextEdit {
                background-color: rgba(30, 30, 50, 200);
                color: #CCCCCC;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
            }
        """)
        log_layout.addWidget(self.log_output)
        
        main_layout.addWidget(log_group)
        
        # 启动计时器更新运行时间
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_run_time)
        self.timer.start(1000)

    def set_background(self):
        """设置窗口背景"""
        # 尝试加载背景图片
        current_dir = os.path.dirname(os.path.abspath(__file__))  # src/ui目录
        project_root = os.path.dirname(os.path.dirname(current_dir))
        bg_path = os.path.join(project_root, "Image", "background.jpg")
        
        # 添加调试信息
        print(f"调试: 当前文件路径: {os.path.abspath(__file__)}")
        print(f"调试: 计算的项目根目录: {project_root}")
        print(f"调试: 背景图片路径: {bg_path}")
        print(f"调试: 背景图片文件存在: {os.path.exists(bg_path)}")
        
        if os.path.exists(bg_path):
            # 设置背景图片
            palette = self.palette()
            # 将QPixmap包装在QBrush中
            brush = QBrush(QPixmap(bg_path).scaled(
                self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
            ))
            palette.setBrush(self.backgroundRole(), brush)
            self.setPalette(palette)
            print("调试: 成功设置背景图片")
        else:
            # 默认背景色
            self.setStyleSheet("background-color: rgba(255, 30, 88, 240);")
            print("调试: 使用默认背景色")

    def resizeEvent(self, event):
        """窗口大小改变事件"""
        super().resizeEvent(event)
        # 更新背景
        self.set_background()

    def load_current_config(self):
        """加载当前配置"""
        config_path = os.path.join(get_exe_dir(), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                
                # 恢复服务器选择
                if 'server' in config_data:
                    server_index = self.server_combo.findData(config_data['server'])
                    if server_index >= 0:
                        self.server_combo.setCurrentIndex(server_index)
                
                # 恢复ADB端口
                if 'adb_port' in config_data:
                    self.adb_port_input.setText(str(config_data['adb_port']))
                
                # 恢复深色模式
                if 'dark_mode' in config_data:
                    self.dark_mode_check.setChecked(config_data['dark_mode'])
                
                self.append_log("[系统] 已加载配置")
            except Exception as e:
                self.append_log(f"[错误] 加载配置失败: {str(e)}")
        else:
            self.append_log("[系统] 未找到配置文件，使用默认配置")

    def toggle_maximize(self):
        """切换窗口最大化/还原"""
        if self.is_maximized:
            self.showNormal()
            self.is_maximized = False
        else:
            self.showMaximized()
            self.is_maximized = True

    def connect_device(self):
        """连接设备"""
        adb_input = self.adb_port_input.text().strip()
        if not adb_input:
            QMessageBox.warning(self, "输入错误", "请输入ADB连接地址")
            return
        
        try:
            # 支持 IP:端口 格式的输入
            # 实际项目中这里应该实现ADB连接逻辑
            import subprocess
            import re
            
            # 验证输入格式 (支持纯数字端口或 IP:端口 格式)
            port_pattern = r'^(\d+)$'
            ip_port_pattern = r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)$'
            
            if re.match(port_pattern, adb_input):
                # 纯数字端口格式，转换为127.0.0.1:端口格式
                serial = f"127.0.0.1:{adb_input}"
            elif re.match(ip_port_pattern, adb_input):
                # IP:端口格式
                serial = adb_input
            else:
                QMessageBox.warning(self, "输入错误", "ADB连接地址格式不正确，请使用端口号或IP:端口格式")
                return
            
            # 实际测试ADB连接
            try:
                # 使用虚拟环境中的ADB工具路径
                import os
                adb_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "shadowverse_automation", ".venv", "Lib", "site-packages", "adbutils", "binaries", "adb.exe")
                
                # 使用adb命令测试连接
                result = subprocess.run([adb_path, 'connect', serial], capture_output=True, text=True, timeout=5)
                if "connected to" in result.stdout or "already connected" in result.stdout:
                    # 连接成功
                    self.update_status("已连接")
                    self.append_log(f"[系统] 已成功连接设备（{serial}）")
                    
                    # 保存配置
                    config_path = os.path.join(get_exe_dir(), "config.json")
                    config_data = {
                        'server': self.server_combo.currentData(),
                        'adb_port': serial,  # 保存完整的IP:端口格式
                        'dark_mode': self.dark_mode_check.isChecked()
                    }
                    with open(config_path, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f, ensure_ascii=False, indent=2)
                    
                    QMessageBox.information(self, "连接成功", f"已成功连接设备（{serial}）")
                else:
                    # 连接失败
                    error_msg = f"无法连接到设备：{result.stderr if result.stderr else result.stdout}"
                    self.update_status("连接失败")
                    self.append_log(f"[错误] 连接设备失败: {error_msg}")
                    QMessageBox.warning(self, "连接失败", error_msg)
            except FileNotFoundError:
                # ADB命令未找到
                self.update_status("连接失败")
                self.append_log(f"[错误] 未找到ADB工具（路径：{adb_path}）")
                QMessageBox.warning(self, "连接失败", f"未找到ADB工具，请检查路径是否正确：{adb_path}")
            except subprocess.TimeoutExpired:
                # 连接超时
                self.update_status("连接失败")
                self.append_log(f"[错误] 连接设备超时（{serial}）")
                QMessageBox.warning(self, "连接失败", f"连接设备超时，请检查地址是否正确")
        except Exception as e:
            self.update_status("连接失败")
            self.append_log(f"[错误] 连接设备过程出错: {str(e)}")
            QMessageBox.warning(self, "连接失败", f"连接设备过程出错: {str(e)}")

    def append_log(self, message):
        """添加日志"""
        timestamp = time.strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"
        self.log_output.append(log_message)
        # 滚动到底部
        self.log_output.moveCursor(self.log_output.textCursor().End)

    def start_script(self):
        """启动脚本"""
        if self.status_label.text() != "状态: 已连接":
            QMessageBox.warning(self, "未连接设备", "请先连接设备")
            return
        
        if self.script_runner is None or not self.script_runner.running:
            self.script_runner = ScriptRunner(self)
            self.script_runner.start()
            self.start_time = time.time()
            self.append_log("[脚本] 已启动")

    def pause_script(self):
        """暂停脚本"""
        if self.script_runner and self.script_runner.running:
            self.script_runner.pause()
            # 向全局命令队列发送暂停命令
            command_queue.put('p')
            self.append_log("[脚本] 已暂停")

    def resume_script(self):
        """恢复脚本"""
        if self.script_runner and self.script_runner.running:
            self.script_runner.resume()
            # 向全局命令队列发送恢复命令
            command_queue.put('r')
            self.append_log("[脚本] 已恢复")

    def update_status(self, status):
        """更新状态"""
        self.status_label.setText(f"状态: {status}")
        
        # 根据状态更新颜色
        if status == "运行中":
            self.status_label.setStyleSheet("color: #4AFF4A; font-weight: bold;")
        elif status == "已暂停":
            self.status_label.setStyleSheet("color: #FFAA4A; font-weight: bold;")
        elif status == "已连接":
            self.status_label.setStyleSheet("color: #4AFFAA; font-weight: bold;")
        elif status == "错误":
            self.status_label.setStyleSheet("color: #FF4A4A; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("color: #AACCFF; font-weight: bold;")

    def update_run_time(self):
        """更新运行时间"""
        if self.script_runner and self.script_runner.running:
            if self.script_runner.paused:
                elapsed = self.script_runner.elapsed_time
            else:
                elapsed = time.time() - self.script_runner.start_time
            
            hours, remainder = divmod(int(elapsed), 3600)
            minutes, seconds = divmod(remainder, 60)
            self.run_time_label.setText(f"运行时间: {hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.run_time_label.setText("运行时间: 00:00:00")

    def mousePressEvent(self, event):
        """鼠标按下事件（已禁用拉伸功能，仅保留拖动）"""
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            # 仅保留标题栏拖动功能
            if pos.y() <= 40:
                self.dragging = True
                self.offset = event.pos()

    def mouseMoveEvent(self, event):
        """鼠标移动事件（已禁用拉伸功能，仅保留拖动）"""
        # 仅处理窗口拖动
        if self.dragging and not self.is_maximized:
            self.move(event.globalPos() - self.offset)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件（已禁用拉伸功能）"""
        self.dragging = False
        self.setCursor(Qt.ArrowCursor)

    def closeEvent(self, event):
        """窗口关闭事件"""
        # 停止脚本和日志监听
        if self.script_runner and self.script_runner.running:
            self.script_runner.stop()
        
        if self.log_listener and self.log_listener.running:
            self.log_listener.stop()
        
        # 停止通知管理器
        if self.notification_manager:
            self.notification_manager.stop()
        
        event.accept()

# 主程序入口
if __name__ == "__main__":
    # 设置中文字体支持
    load_custom_font()
    
    app = QApplication(sys.argv)
    window = ShadowverseUI()
    window.show()
    sys.exit(app.exec_())