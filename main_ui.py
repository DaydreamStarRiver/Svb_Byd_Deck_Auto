#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影之诗自动对战脚本 - 增强版UI
"""

import sys
import os
import logging
import threading
import time
import json
import shutil
import queue
import traceback
import base64
import zlib
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QStackedWidget, QLineEdit, QGroupBox,
    QGridLayout, QScrollArea, QSizePolicy, QCheckBox, QMessageBox, QComboBox,
    QMenu, QAction, QFileDialog, QInputDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, pyqtSlot
from PyQt5.QtGui import QFont, QPixmap, QPalette, QBrush, QColor, QIcon, QFontDatabase, QPainter, QPen

# 设置环境变量以避免PyTorch的pin_memory警告
os.environ["PIN_MEMORY"] = "false"

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# 导入原有主逻辑
from main import main as run_main_script
from main import command_queue, log_queue  # 导入全局命令队列和日志队列

# 设置字体路径（如果文件不存在则使用默认字体）
FONT_PATH = "猫啃什锦黑.otf"
BACKGROUND_IMAGE = "Image/ui背景.jpg"  # 背景图片路径

def get_exe_dir():
    """获取 EXE 所在目录（打包后）或脚本目录（直接运行 .py 时）"""
    if getattr(sys, 'frozen', False):  # 检查是否打包
        return os.path.dirname(sys.executable)  # EXE 所在目录
    else:
        return os.path.dirname(os.path.abspath(__file__))  # 脚本所在目录

# 创建自定义字体
def load_custom_font(size=10):
    font = QFont("Microsoft YaHei", size)  # 默认字体
    if os.path.exists(FONT_PATH):
        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        if font_id != -1:
            font_families = QFontDatabase.applicationFontFamilies(font_id)
            if font_families:
                font = QFont(font_families[0], size)
    return font

class ConfigPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.config_data = self.load_config()
        self.card_widgets = []
        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("参数设置")
        title_label.setStyleSheet("font-size: 20px; color: #88AAFF; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 拖拽速度设置
        drag_group = QGroupBox("拖拽速度设置 (单位:秒)")
        drag_layout = QGridLayout(drag_group)
        
        # 获取当前拖拽速度设置 - 修复1: 确保正确读取配置
        drag_range = [0.10, 0.13]  # 默认值
        if "game" in self.config_data and "human_like_drag_duration_range" in self.config_data["game"]:
            drag_range = self.config_data["game"]["human_like_drag_duration_range"]
        
        drag_layout.addWidget(QLabel("最小拖拽时间:"), 0, 0)
        self.min_drag_input = QLineEdit(str(drag_range[0]))
        self.min_drag_input.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
        drag_layout.addWidget(self.min_drag_input, 0, 1)
        
        drag_layout.addWidget(QLabel("最大拖拽时间:"), 1, 0)
        self.max_drag_input = QLineEdit(str(drag_range[1]))
        self.max_drag_input.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
        drag_layout.addWidget(self.max_drag_input, 1, 1)
        
        drag_layout.addWidget(QLabel("说明: 设置更小的值会使操作更快，但可能被检测为脚本"), 2, 0, 1, 2)
        
        main_layout.addWidget(drag_group)
        
        # 自动重启设置
        restart_group = QGroupBox("自动重启设置 (防止游戏卡死)")
        restart_layout = QGridLayout(restart_group)
        
        # 获取当前自动重启设置
        auto_restart_config = self.config_data.get("auto_restart", {})
        self.auto_restart_enabled = auto_restart_config.get("enabled", True)
        self.output_timeout = auto_restart_config.get("output_timeout", 300) // 60  # 转换为分钟
        
        # 启用/禁用复选框
        self.restart_enabled_checkbox = QCheckBox("启用自动重启功能")
        self.restart_enabled_checkbox.setChecked(self.auto_restart_enabled)
        self.restart_enabled_checkbox.setStyleSheet("color: #FFFFFF;")
        restart_layout.addWidget(self.restart_enabled_checkbox, 0, 0, 1, 2)
        
        # 无操作重启时间输入
        restart_layout.addWidget(QLabel("无操作自动重启时间 (分钟):"), 1, 0)
        self.restart_time_input = QLineEdit(str(self.output_timeout))
        self.restart_time_input.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
        self.restart_time_input.setEnabled(self.auto_restart_enabled)
        restart_layout.addWidget(self.restart_time_input, 1, 1)
        
        # 连接复选框状态变化信号
        self.restart_enabled_checkbox.stateChanged.connect(self.on_restart_enabled_changed)
        
        # 添加说明
        restart_layout.addWidget(QLabel("说明: 设置无操作后自动重启游戏的时间间隔，建议设置在3-10分钟之间"), 2, 0, 1, 2)
        
        main_layout.addWidget(restart_group)
        
        # 换牌策略设置
        strategy_group = QGroupBox("换牌策略设置")
        strategy_layout = QVBoxLayout(strategy_group)
        
        # 策略选择
        strategy_selection_layout = QHBoxLayout()
        strategy_selection_layout.addWidget(QLabel("选择换牌策略:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["3费档次", "4费档次", "5费档次"])
        self.strategy_combo.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
        # 设置当前选中的策略
        current_strategy = self.config_data.get("game", {}).get("card_replacement_strategy", "3费档次")
        index = self.strategy_combo.findText(current_strategy)
        if index >= 0:
            self.strategy_combo.setCurrentIndex(index)
        strategy_selection_layout.addWidget(self.strategy_combo)
        
        # 帮助按钮
        self.strategy_help_btn = QPushButton("帮助")
        self.strategy_help_btn.clicked.connect(self.show_strategy_help)
        strategy_selection_layout.addWidget(self.strategy_help_btn)
        
        strategy_layout.addLayout(strategy_selection_layout)
        
        # 添加说明
        strategy_desc = QLabel("说明: 根据费用档次策略自动换牌，确保关键回合能准时展开")
        strategy_desc.setStyleSheet("font-size: 12px; color: #AACCFF;")
        strategy_layout.addWidget(strategy_desc)
        
        main_layout.addWidget(strategy_group)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存设置")
        self.save_btn.clicked.connect(self.save_config)
        self.back_btn = QPushButton("返回主界面")
        self.back_btn.clicked.connect(lambda: self.parent.stacked_widget.setCurrentIndex(0))
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.back_btn)
        btn_layout.addStretch()
        
        main_layout.addLayout(btn_layout)
        
    # 卡牌优先级已拆分至独立页面 CardPriorityPage；此处不再直接加载卡片优先级
    
    def on_restart_enabled_changed(self):
        """处理自动重启功能启用/禁用状态变化"""
        self.restart_time_input.setEnabled(self.restart_enabled_checkbox.isChecked())
        
    def get_current_config(self):
        """获取当前配置的JSON数据"""
        # 仅返回通用参数（卡牌优先级已拆分至 CardPriorityPage，完整配置可从磁盘读取）
        config = {
            "game": {
                "human_like_drag_duration_range": [
                    float(self.min_drag_input.text()),
                    float(self.max_drag_input.text())
                ]
            },
            "auto_restart": {
                "enabled": self.restart_enabled_checkbox.isChecked(),
                "output_timeout": int(self.restart_time_input.text()) * 60,  # 转换为秒
                "match_timeout": 900
            }
        }
        return config
    
    def refresh_card_priority(self):
        """刷新卡片优先级显示"""
        # 已迁移到 CardPriorityPage，保留空实现以避免外部直接调用时报错
        return
    
    def show_strategy_help(self):
        """显示换牌策略说明"""
        help_text = """
换牌策略说明：

【3费档次】
• 最优：前三张牌组合为 [1,2,3]
• 次优：牌序为2，3
• 目标：确保3费时能准时打出

【4费档次】（向下兼容3费档次）
• 最优：四张牌组合为 [1,2,3,4]
• 次优：牌序为 [2,3,4] 或 [2,2,4]
• 目标：确保4费时能有效展开

【5费档次】（向下兼容4费、3费档次）
• 优先级组合（从高到低）：
[2,3,4,5] > [2,3,3,5] > [2,2,3,5] > [2,2,2,5]
• 目标：确保5费时能打出关键牌

注意：高档次策略条件不满足时会自动检查低档次策略
"""
        msg = QMessageBox()
        msg.setWindowTitle("换牌策略说明")
        msg.setText(help_text)
        msg.setIcon(QMessageBox.Information)
        msg.exec_()
    
    def load_config(self):
        """加载配置文件"""
        config_path = os.path.join(get_exe_dir(), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载配置文件失败: {str(e)}")
                return {}
        return {}
    
    def load_card_priority_settings(self, scroll_content):
        """加载卡片优先级设置"""
        # 清空现有内容
        for i in reversed(range(self.scroll_layout.count())): 
            widget = self.scroll_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        self.card_widgets = []
        
        # 获取卡组目录
        card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
        if not os.path.exists(card_dir):
            QMessageBox.warning(self, "警告", "未找到'shadowverse_cards_cost'文件夹，请先选择卡组！")
            return
        
        # 获取所有卡片文件
        card_files = []
        for file in os.listdir(card_dir):
            if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                card_files.append(file)
        
        # 如果没有卡片，显示提示
        if not card_files:
            no_card_label = QLabel("没有找到卡片，请先在'卡组选择'页面选择卡片")
            no_card_label.setStyleSheet("color: #FF8888; font-size: 14px;")
            no_card_label.setAlignment(Qt.AlignCenter)
            self.scroll_layout.addWidget(no_card_label)
            return
        
        # 为每张卡片创建设置行
        for card_file in card_files:
            # 解析卡片名称
            card_name = card_file.split('_', 1)[-1].rsplit('.', 1)[0]
            
            # 创建卡片行控件
            card_row = QWidget()
            card_row.setStyleSheet("background-color: rgba(60, 60, 90, 150); border-radius: 10px;")
            row_layout = QHBoxLayout(card_row)
            row_layout.setContentsMargins(10, 5, 10, 5)
            
            # 卡片图片
            card_label = QLabel()
            card_path = os.path.join(get_exe_dir(), "shadowverse_cards_cost", card_file)
            pixmap = QPixmap(card_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(80, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                card_label.setPixmap(pixmap)
            card_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(card_label)
            
            # 卡片名称
            name_label = QLabel(card_name)
            name_label.setStyleSheet("color: #FFFFFF; font-weight: bold; min-width: 120px;")
            name_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(name_label)
            
            # 出牌优先级
            row_layout.addWidget(QLabel("出牌优先级:"))
            play_priority_input = QLineEdit()
            play_priority_input.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
            play_priority_input.setMaximumWidth(50)
            
            # 设置当前值（如果有） - 修复2: 正确读取优先级
            high_priority = self.config_data.get("high_priority_cards", {}).get(card_name, {})
            if high_priority:
                play_priority_input.setText(str(high_priority.get("priority", "")))
            else:
                play_priority_input.setText("")  # 确保为空
            row_layout.addWidget(play_priority_input)
            
            # 进化优先级
            row_layout.addWidget(QLabel("进化优先级:"))
            evolve_priority_input = QLineEdit()
            evolve_priority_input.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
            evolve_priority_input.setMaximumWidth(50)
            
            # 设置当前值（如果有） - 修复2: 正确读取优先级
            evolve_priority = self.config_data.get("evolve_priority_cards", {}).get(card_name, {})
            if evolve_priority:
                evolve_priority_input.setText(str(evolve_priority.get("priority", "")))
            else:
                evolve_priority_input.setText("")  # 确保为空
            row_layout.addWidget(evolve_priority_input)
            
            # 保存控件引用
            self.card_widgets.append({
                "card_name": card_name,
                "play_priority": play_priority_input,
                "evolve_priority": evolve_priority_input
            })
            
            self.scroll_layout.addWidget(card_row)
        
        self.scroll_layout.addStretch()
    
    def save_config(self):
        """保存配置到文件"""
        # 验证并保存拖拽速度设置
        try:
            min_drag = float(self.min_drag_input.text())
            max_drag = float(self.max_drag_input.text())
            
            if min_drag < 0 or max_drag < 0:
                raise ValueError("拖拽时间不能为负数")
            if min_drag > max_drag:
                raise ValueError("最小拖拽时间不能大于最大拖拽时间")
            
            # 更新配置数据
            if "game" not in self.config_data:
                self.config_data["game"] = {}
            self.config_data["game"]["human_like_drag_duration_range"] = [min_drag, max_drag]
        except Exception as e:
            QMessageBox.warning(self, "输入错误", f"拖拽时间设置错误: {str(e)}")
            return
        
        # 验证并保存自动重启设置
        try:
            # 更新自动重启配置
            if "auto_restart" not in self.config_data:
                self.config_data["auto_restart"] = {}
            
            self.config_data["auto_restart"]["enabled"] = self.restart_enabled_checkbox.isChecked()
            
            if self.restart_enabled_checkbox.isChecked():
                restart_time = int(self.restart_time_input.text())
                if restart_time < 1 or restart_time > 60:
                    raise ValueError("自动重启时间必须在1-60分钟之间")
                self.config_data["auto_restart"]["output_timeout"] = restart_time * 60  # 转换为秒
            
            # 保持match_timeout不变（15分钟）
            if "match_timeout" not in self.config_data["auto_restart"]:
                self.config_data["auto_restart"]["match_timeout"] = 900
        except Exception as e:
            QMessageBox.warning(self, "输入错误", f"自动重启设置错误: {str(e)}")
            return
        
        # 保存换牌策略设置
        strategy = self.strategy_combo.currentText()
        self.config_data["game"]["card_replacement_strategy"] = strategy
        
        # 注意：卡牌优先级设置已迁移到独立页面 CardPriorityPage，由它单独保存该部分配置。
        # 这里只保存与参数设置相关的其他字段（如 'game' 和 'auto_restart'）。
        # 将更新写入磁盘（合并现有配置）。
        config_path = os.path.join(get_exe_dir(), "config.json")
        try:
            # 读取现有配置以保留其它部分（例如 high_priority_cards）
            existing = {}
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    try:
                        existing = json.load(f)
                    except Exception:
                        existing = {}

            # 合并
            existing.update(self.config_data)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(existing, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "成功", "配置已保存！")
            self.parent.log_output.append("[配置] 参数设置已更新")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存配置文件时出错: {str(e)}")
    def refresh_config_display(self):
        """刷新整个配置页面的显示"""
        # 重新加载配置数据
        self.config_data = self.load_config()
        
        # 刷新拖拽速度设置
        drag_range = [0.10, 0.13]  # 默认值
        if "game" in self.config_data and "human_like_drag_duration_range" in self.config_data["game"]:
            drag_range = self.config_data["game"]["human_like_drag_duration_range"]
        self.min_drag_input.setText(str(drag_range[0]))
        self.max_drag_input.setText(str(drag_range[1]))
        
        # 卡片优先级已移至独立页面，主配置页不再直接刷新该部分
        return

class CardSelectPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.current_page = 0
        self.selected_cards = []
        self.cards_per_row = 4
        self.card_size = QSize(100, 140)  # 减小卡片尺寸以显示更多图片
        self.cost_filters = {}  # 存储费用筛选按钮
        self.all_cards = []     # 所有卡片
        self.filtered_cards = [] # 筛选后的卡片
        self.card_categories = []  # 卡片分类
        self.current_category = None  # 当前选择的分类
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("卡组选择")
        title_label.setStyleSheet("font-size: 20px; color: #88AAFF; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 加载已保存卡组下拉框
        deck_layout = QHBoxLayout()
        deck_layout.addWidget(QLabel("已保存卡组:"))
        self.saved_decks_combo = QComboBox()
        self.saved_decks_combo.setStyleSheet("""
            QComboBox {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 5px;
                min-width: 150px;
            }
            QComboBox:hover {
                background-color: rgba(90, 90, 140, 180);
            }
        """)
        self.saved_decks_combo.addItem("选择卡组", None)
        self.saved_decks_combo.currentIndexChanged.connect(self.load_saved_deck)
        deck_layout.addWidget(self.saved_decks_combo)
        
        self.refresh_saved_decks()  # 加载已保存的卡组列表
        main_layout.addLayout(deck_layout)

        # 搜索框和分类选择
        search_layout = QHBoxLayout()
        
        # 分类选择下拉框
        self.category_combo = QComboBox()
        self.category_combo.addItem("所有分类", None)
        self.category_combo.setStyleSheet("""
            QComboBox {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 5px;
                min-width: 120px;
            }
            QComboBox:hover {
                background-color: rgba(90, 90, 140, 180);
            }
        """)
        self.category_combo.currentIndexChanged.connect(self.on_category_changed)
        search_layout.addWidget(QLabel("分类:"))
        search_layout.addWidget(self.category_combo)
        
        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索卡牌...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        search_layout.addWidget(QLabel("搜索:"))
        search_layout.addWidget(self.search_input)
        
        main_layout.addLayout(search_layout)

        # 费用筛选栏
        self.init_cost_filter(main_layout)

        # 说明标签
        desc_label = QLabel("从以下卡牌中选择您的卡组，点击保存应用选择")
        desc_label.setStyleSheet("font-size: 14px; color: #AACCFF;")
        desc_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(desc_label)
        
        # 卡片显示区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.scroll_content)
        
        # 设置滚动区域样式
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QWidget#ScrollContent {
                background-color: transparent;
            }
        """)
        self.scroll_content.setObjectName("ScrollContent")
        main_layout.addWidget(self.scroll_area)
        
        # 翻页控制
        page_control_layout = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self.prev_page)
        self.page_label = QLabel("第1页")
        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self.next_page)
        
        page_control_layout.addStretch()
        page_control_layout.addWidget(self.prev_btn)
        page_control_layout.addWidget(self.page_label)
        page_control_layout.addWidget(self.next_btn)
        page_control_layout.addStretch()
        main_layout.addLayout(page_control_layout)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存卡组")
        self.save_btn.clicked.connect(self.save_selection)
        self.save_as_btn = QPushButton("另存为...")
        self.save_as_btn.clicked.connect(self.save_deck_as)
        self.back_btn = QPushButton("返回主界面")
        self.back_btn.clicked.connect(lambda: self.parent.stacked_widget.setCurrentIndex(0))
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.save_as_btn)
        btn_layout.addWidget(self.back_btn)
        btn_layout.addStretch()
        
        main_layout.addLayout(btn_layout)
        
        # 加载卡片
        self.load_cards()

    def init_cost_filter(self, main_layout):
        """初始化费用筛选控件"""
        cost_filter_layout = QHBoxLayout()
        cost_filter_layout.addWidget(QLabel("费用筛选:"))
        
        # 添加0-10费选项
        for cost in range(0, 11):
            btn = QPushButton(f"{cost}费")
            btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #4A4A7F;
                    color: white;
                    border: none;
                    padding: 5px 8px;
                    min-width: 40px;
                    border-radius: 4px;
                    margin: 2px;
                }
                QPushButton:checked {
                    background-color: #88AAFF;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #5A5A9F;
                }
            """)
            btn.clicked.connect(self.update_card_display)
            self.cost_filters[cost] = btn
            cost_filter_layout.addWidget(btn)
        
        # 添加"全部"按钮
        all_btn = QPushButton("全部")
        all_btn.setCheckable(True)
        all_btn.setChecked(True)
        all_btn.setStyleSheet("""
            QPushButton {
                background-color: #88AAFF;
                color: white;
                font-weight: bold;
                padding: 5px 10px;
                border-radius: 4px;
                margin: 2px;
            }
        """)
        all_btn.clicked.connect(self.select_all_costs)
        cost_filter_layout.addWidget(all_btn)
        
        cost_filter_layout.addStretch()
        main_layout.addLayout(cost_filter_layout)

    def load_cards(self):
        """加载所有卡片和分类"""
        card_dir = os.path.join(get_exe_dir(), "quanka")
        self.all_cards = []
        self.card_categories = []
        
        if os.path.exists(card_dir):
            # 获取所有分类文件夹
            self.card_categories = [d for d in os.listdir(card_dir) 
                                  if os.path.isdir(os.path.join(card_dir, d))]
            
            # 更新分类下拉框
            self.category_combo.clear()
            self.category_combo.addItem("所有分类", None)
            
            for category in sorted(self.card_categories):
                self.category_combo.addItem(category, category)
            
            # 加载所有卡片
            for root, _, files in os.walk(card_dir):
                for file in files:
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                        # 存储相对路径和分类信息
                        rel_path = os.path.relpath(os.path.join(root, file), card_dir)
                        self.all_cards.append({
                            "path": rel_path,
                            "file": file,
                            "category": os.path.basename(root) if root != card_dir else None
                        })
        
        # 按费用和名称排序
        self.all_cards.sort(key=lambda x: (
            self.get_card_cost(x["file"]), 
            x["file"].lower()
        ))
        
        self.filtered_cards = self.all_cards
        self.display_page(0)

    def on_category_changed(self, index):
        """分类选择改变事件"""
        self.current_category = self.category_combo.itemData(index)
        self.update_card_display()

    def on_search_text_changed(self, text):
        """搜索文本改变事件"""
        self.update_card_display()

    def select_all_costs(self):
        """选择全部费用"""
        sender = self.sender()
        if sender.isChecked():
            for cost, btn in self.cost_filters.items():
                btn.setChecked(False)
            self.update_card_display()
            sender.setChecked(True)

    def update_card_display(self):
        """根据分类、搜索和费用筛选更新卡片显示"""
        # 获取选中的费用
        selected_costs = [cost for cost, btn in self.cost_filters.items() if btn.isChecked()]
        
        # 更新"全部"按钮状态
        all_btn = self.sender() if isinstance(self.sender(), QPushButton) and self.sender().text() == "全部" else None
        if not all_btn:
            for btn in self.findChildren(QPushButton):
                if btn.text() == "全部":
                    btn.setChecked(False)
                    break
        
        # 获取搜索文本
        search_text = self.search_input.text().strip().lower()
        
        # 筛选卡片
        self.filtered_cards = []
        for card in self.all_cards:
            # 分类筛选
            if self.current_category and card["category"] != self.current_category:
                continue
                
            # 费用筛选
            if selected_costs and self.get_card_cost(card["file"]) not in selected_costs:
                continue
                
            # 搜索筛选
            if search_text and search_text not in card["file"].lower():
                continue
                
            self.filtered_cards.append(card)
        
        # 重置到第一页
        self.current_page = 0
        self.display_page(self.current_page)

    def get_card_cost(self, card_file):
        """从文件名提取费用数字"""
        try:
            return int(card_file.split('_')[0])
        except:
            return 0  # 如果解析失败，默认0费

    def resizeEvent(self, event):
        """窗口大小改变时调整布局"""
        super().resizeEvent(event)
        self.adjust_card_layout()

    def adjust_card_layout(self):
        """根据窗口大小调整卡片布局"""
        scroll_width = self.scroll_area.width() - 30
        self.cards_per_row = max(2, scroll_width // (self.card_size.width() + 20))
        self.display_page(self.current_page)

    def display_page(self, page):
        """显示指定页码的卡片"""
        self.current_page = page
        cards_per_page = self.cards_per_row * 3  # 每页3行
        
        # 计算总页数
        self.total_pages = max(1, (len(self.filtered_cards) + cards_per_page - 1) // cards_per_page)
        self.page_label.setText(f"第{page+1}/{self.total_pages}页")
        self.prev_btn.setEnabled(page > 0)
        self.next_btn.setEnabled(page < self.total_pages - 1)
        
        # 清空现有内容
        for i in reversed(range(self.grid_layout.count())): 
            if widget := self.grid_layout.itemAt(i).widget():
                widget.deleteLater()
        
        # 添加当前页卡片
        start_index = page * cards_per_page
        end_index = min(start_index + cards_per_page, len(self.filtered_cards))
        
        row, col = 0, 0
        for i in range(start_index, end_index):
            card_data = self.filtered_cards[i]
            card_path = os.path.join(get_exe_dir(), "quanka", card_data["path"])
            
            # 创建卡片容器
            card_container = QWidget()
            card_container.setStyleSheet("""
                background-color: rgba(60, 60, 90, 150);
                border-radius: 10px;
            """)
            card_layout = QVBoxLayout(card_container)
            card_layout.setAlignment(Qt.AlignCenter)
            card_layout.setSpacing(5)
            card_layout.setContentsMargins(5, 5, 5, 5)
            
            # 卡片图片
            card_label = QLabel()
            pixmap = QPixmap(card_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(self.card_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                card_label.setPixmap(pixmap)
            card_label.setAlignment(Qt.AlignCenter)
            card_label.mousePressEvent = lambda event, f=card_data["file"]: self.toggle_card_selection_by_click(f)
            
            # 卡片名称
            card_name = ' '.join(card_data["file"].split('_', 1)[-1].rsplit('.', 1)[0].split('_'))
            name_label = QLabel(card_name)
            name_label.setStyleSheet("""
                QLabel {
                    color: #FFFFFF;
                    background-color: transparent;
                    font-weight: bold;
                    font-size: 12px;
                    padding: 2px;
                    max-width: %dpx;
                }
            """ % (self.card_size.width() - 10))
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setWordWrap(True)
            
            # 选择框
            checkbox = QCheckBox("选择")
            checkbox.setStyleSheet("""
                QCheckBox {
                    color: #FFFFFF;
                    background-color: rgba(80, 80, 120, 180);
                    border-radius: 5px;
                    padding: 2px 5px;
                    font-size: 12px;
                }
                QCheckBox::indicator {
                    width: 15px;
                    height: 15px;
                }
            """)
            checkbox.setChecked(card_data["file"] in self.selected_cards)
            checkbox.stateChanged.connect(lambda state, f=card_data["file"]: self.toggle_card_selection(f, state))
            
            card_layout.addWidget(card_label)
            card_layout.addWidget(name_label)
            card_layout.addWidget(checkbox)
            self.grid_layout.addWidget(card_container, row, col)
            
            col += 1
            if col >= self.cards_per_row:
                col = 0
                row += 1

    def toggle_card_selection(self, card_file, state):
        """复选框选择卡片"""
        if state == Qt.Checked:
            if card_file not in self.selected_cards:
                if len(self.selected_cards) < 100:
                    self.selected_cards.append(card_file)
                else:
                    self.sender().setChecked(False)
                    QMessageBox.warning(self, "警告", "最多只能选择100张卡片！")
        else:
            if card_file in self.selected_cards:
                self.selected_cards.remove(card_file)

    def toggle_card_selection_by_click(self, card_file):
        """点击图片选择卡片"""
        if card_file in self.selected_cards:
            self.selected_cards.remove(card_file)
        else:
            if len(self.selected_cards) < 100:
                self.selected_cards.append(card_file)
            else:
                QMessageBox.warning(self, "警告", "最多只能选择100张卡片！")
        self.display_page(self.current_page)  # 刷新页面更新复选框状态

    def prev_page(self):
        """上一页"""
        if self.current_page > 0:
            self.display_page(self.current_page - 1)

    def next_page(self):
        """下一页"""
        if self.current_page < self.total_pages - 1:
            self.display_page(self.current_page + 1)

    def save_selection(self):
        """保存选择的卡组"""
        if not self.selected_cards:
            QMessageBox.warning(self, "警告", "请至少选择一张卡片！")
            return
        
        target_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
        os.makedirs(target_dir, exist_ok=True)
        
        # 清空目标文件夹，然后添加所有选中的卡片
        for file in os.listdir(target_dir):
            file_path = os.path.join(target_dir, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"删除文件失败: {file_path} - {e}")
        
        # 复制选中的卡片
        success_count = 0
        for card_file in self.selected_cards:
            # 查找卡片完整路径
            src = None
            for card in self.all_cards:
                if card["file"] == card_file:
                    src = os.path.join(get_exe_dir(), "quanka", card["path"])
                    break
            
            if src and os.path.exists(src):
                dst = os.path.join(target_dir, card_file)
                try:
                    shutil.copy2(src, dst)
                    success_count += 1
                except Exception as e:
                    print(f"复制文件失败: {src} -> {dst} - {e}")
        
            if success_count > 0:
                QMessageBox.information(self, "成功", f"已保存 {success_count} 张卡片到卡组！")
                self.parent.log_output.append(f"[卡组] 已保存 {success_count} 张卡片")

                # 刷新卡牌优先级页面的卡片显示（迁移后）
                if hasattr(self.parent, 'card_priority_page'):
                    self.parent.card_priority_page.refresh_card_priority()

                # 刷新我的卡组页面的卡片显示
                if hasattr(self.parent, 'my_deck_page'):
                    self.parent.my_deck_page.load_deck()
    

    
    def save_current_deck(self):
        """保存当前卡组"""
        deck_name = self.save_deck_name.text().strip()
        if not deck_name:
            QMessageBox.warning(self, "警告", "请输入卡组名称！")
            return
        
        # 获取当前卡组中的卡片
        card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
        if not os.path.exists(card_dir):
            QMessageBox.warning(self, "警告", "当前卡组为空！")
            return
        
        card_files = [f for f in os.listdir(card_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        if not card_files:
            QMessageBox.warning(self, "警告", "当前卡组为空！")
            return
        
        try:
            # 创建保存卡组的目录
            decks_dir = os.path.join(get_exe_dir(), "saved_decks")
            os.makedirs(decks_dir, exist_ok=True)
            
            # 构建卡组数据
            deck_data = {
                "name": deck_name,
                "cards": card_files,
                "timestamp": int(time.time())
            }
            
            # 保存到文件
            deck_file = os.path.join(decks_dir, f"{deck_name}.json")
            with open(deck_file, 'w', encoding='utf-8') as f:
                json.dump(deck_data, f, ensure_ascii=False, indent=2)
            
            QMessageBox.information(self, "成功", f"卡组 '{deck_name}' 已保存！")
            self.parent.log_output.append(f"[卡组] 已保存卡组 '{deck_name}'")
            
            # 清空输入框
            self.save_deck_name.clear()
            
            # 刷新已保存卡组列表
            self.refresh_saved_decks()
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存卡组失败: {str(e)}")
            self.parent.log_output.append(f"[卡组] 保存卡组失败: {str(e)}")
    
    def load_selected_deck(self):
        """加载选中的已保存卡组"""
        deck_file = self.saved_decks_combo.itemData(self.saved_decks_combo.currentIndex())
        if not deck_file:
            QMessageBox.warning(self, "警告", "请选择要加载的卡组！")
            return
        
        try:
            decks_dir = os.path.join(get_exe_dir(), "saved_decks")
            deck_path = os.path.join(decks_dir, deck_file)
            
            with open(deck_path, 'r', encoding='utf-8') as f:
                deck_data = json.load(f)
            
            # 清空当前卡组
            card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
            for file in os.listdir(card_dir):
                file_path = os.path.join(card_dir, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    print(f"删除文件失败: {file_path} - {e}")
            
            # 复制卡片到当前卡组
            source_dir = os.path.join(get_exe_dir(), "quanka")
            success_count = 0
            for card_file in deck_data.get('cards', []):
                # 查找卡片在quanka目录中的路径
                src = None
                for root, _, files in os.walk(source_dir):
                    if card_file in files:
                        src = os.path.join(root, card_file)
                        break
                
                if src and os.path.exists(src):
                    dst = os.path.join(card_dir, card_file)
                    try:
                        shutil.copy2(src, dst)
                        success_count += 1
                    except Exception as e:
                        print(f"复制文件失败: {src} -> {dst} - {e}")
            
            if success_count > 0:
                # 重新加载卡组显示
                self.load_deck()
                
                QMessageBox.information(self, "成功", f"已加载卡组 '{deck_data.get('name')}'，共 {success_count} 张卡片")
                self.parent.log_output.append(f"[卡组] 已加载卡组 '{deck_data.get('name')}'")
                
                # 刷新卡牌优先级页面（已迁移）
                if hasattr(self.parent, 'card_priority_page'):
                    self.parent.card_priority_page.refresh_card_priority()
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载卡组失败: {str(e)}")
            self.parent.log_output.append(f"[卡组] 加载卡组失败: {str(e)}")
        
        try:
            decks_dir = os.path.join(get_exe_dir(), "saved_decks")
            deck_path = os.path.join(decks_dir, deck_file)
            
            with open(deck_path, 'r', encoding='utf-8') as f:
                deck_data = json.load(f)
            
            # 清空当前卡组
            card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
            for file in os.listdir(card_dir):
                file_path = os.path.join(card_dir, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    print(f"删除文件失败: {file_path} - {e}")
            
            # 复制卡片到当前卡组
            source_dir = os.path.join(get_exe_dir(), "quanka")
            success_count = 0
            for card_file in deck_data.get('cards', []):
                # 查找卡片在quanka目录中的路径
                src = None
                for root, _, files in os.walk(source_dir):
                    if card_file in files:
                        src = os.path.join(root, card_file)
                        break
                
                if src and os.path.exists(src):
                    dst = os.path.join(card_dir, card_file)
                    try:
                        shutil.copy2(src, dst)
                        success_count += 1
                    except Exception as e:
                        print(f"复制文件失败: {src} -> {dst} - {e}")
            
            if success_count > 0:
                # 重新加载卡组显示
                self.load_deck()
                
                QMessageBox.information(self, "成功", f"已加载卡组 '{deck_data.get('name')}'，共 {success_count} 张卡片")
                self.parent.log_output.append(f"[卡组] 已加载卡组 '{deck_data.get('name')}'")
                
                # 刷新卡牌优先级页面（已迁移）
                if hasattr(self.parent, 'card_priority_page'):
                    self.parent.card_priority_page.refresh_card_priority()
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载卡组失败: {str(e)}")
            self.parent.log_output.append(f"[卡组] 加载卡组失败: {str(e)}")
    
    def delete_selected_deck(self):
        """删除选中的已保存卡组"""
        deck_file = self.saved_decks_combo.itemData(self.saved_decks_combo.currentIndex())
        deck_name = self.saved_decks_combo.currentText()
        
        if not deck_file:
            QMessageBox.warning(self, "警告", "请选择要删除的卡组！")
            return
        
        reply = QMessageBox.question(
            self, '确认删除',
            f'确定要删除卡组 "{deck_name}" 吗？此操作不可撤销！',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                decks_dir = os.path.join(get_exe_dir(), "saved_decks")
                deck_path = os.path.join(decks_dir, deck_file)
                
                if os.path.exists(deck_path):
                    os.remove(deck_path)
                    
                    QMessageBox.information(self, "成功", f"卡组 '{deck_name}' 已删除！")
                    self.parent.log_output.append(f"[卡组] 已删除卡组 '{deck_name}'")
                    
                    # 刷新已保存卡组列表
                    self.refresh_saved_decks()
                    
                    # 刷新我的卡组页面
                    if hasattr(self.parent, 'my_deck_page'):
                        self.parent.my_deck_page.refresh_saved_decks()
                    
            except Exception as e:
                QMessageBox.warning(self, "错误", f"删除卡组失败: {str(e)}")
                self.parent.log_output.append(f"[卡组] 删除卡组失败: {str(e)}")
                
    def save_deck_as(self):
        """将当前选择的卡组另存为"""
        if not self.selected_cards:
            QMessageBox.warning(self, "警告", "请至少选择一张卡片！")
            return
        
        # 获取卡组名称
        deck_name, ok = QInputDialog.getText(self, "保存卡组", "请输入卡组名称:")
        if not ok or not deck_name.strip():
            return
        
        # 保存卡组
        self.save_named_deck(deck_name.strip())
        
    def save_named_deck(self, deck_name):
        """保存命名卡组"""
        try:
            # 创建保存卡组的目录
            decks_dir = os.path.join(get_exe_dir(), "saved_decks")
            os.makedirs(decks_dir, exist_ok=True)
            
            # 构建卡组数据
            deck_data = {
                "name": deck_name,
                "cards": self.selected_cards,
                "timestamp": int(time.time())
            }
            
            # 保存到文件
            deck_file = os.path.join(decks_dir, f"{deck_name}.json")
            with open(deck_file, 'w', encoding='utf-8') as f:
                json.dump(deck_data, f, ensure_ascii=False, indent=2)
            
            QMessageBox.information(self, "成功", f"卡组 '{deck_name}' 已保存！")
            self.parent.log_output.append(f"[卡组] 已保存卡组 '{deck_name}'")
            
            # 刷新已保存卡组列表
            self.refresh_saved_decks()
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存卡组失败: {str(e)}")
            self.parent.log_output.append(f"[卡组] 保存卡组失败: {str(e)}")
    
    def refresh_saved_decks(self):
        """刷新已保存卡组列表"""
        self.saved_decks_combo.clear()
        self.saved_decks_combo.addItem("选择卡组", None)
        
        decks_dir = os.path.join(get_exe_dir(), "saved_decks")
        if os.path.exists(decks_dir):
            for file in os.listdir(decks_dir):
                if file.endswith('.json'):
                    deck_file = os.path.join(decks_dir, file)
                    try:
                        with open(deck_file, 'r', encoding='utf-8') as f:
                            deck_data = json.load(f)
                        self.saved_decks_combo.addItem(deck_data.get('name', file[:-5]), file)
                    except Exception as e:
                        print(f"读取卡组文件失败: {deck_file} - {e}")
        
        # 同时刷新MyDeckPage中的卡组列表
        if hasattr(self.parent, 'my_deck_page'):
            self.parent.my_deck_page.refresh_saved_decks()
    
    def load_saved_deck(self, index):
        """加载选中的已保存卡组"""
        deck_file = self.saved_decks_combo.itemData(index)
        if not deck_file:
            return
        
        try:
            decks_dir = os.path.join(get_exe_dir(), "saved_decks")
            deck_path = os.path.join(decks_dir, deck_file)
            
            with open(deck_path, 'r', encoding='utf-8') as f:
                deck_data = json.load(f)
            
            # 清空当前选择
            self.selected_cards = []
            
            # 添加卡组中的卡片
            for card_file in deck_data.get('cards', []):
                self.selected_cards.append(card_file)
            
            # 刷新显示
            self.display_page(self.current_page)
            
            QMessageBox.information(self, "成功", f"已加载卡组 '{deck_data.get('name')}'")
            self.parent.log_output.append(f"[卡组] 已加载卡组 '{deck_data.get('name')}'")
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载卡组失败: {str(e)}")
            self.parent.log_output.append(f"[卡组] 加载卡组失败: {str(e)}")

class MyDeckPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.card_size = QSize(100, 140)  # 标准卡片尺寸
        self.cards_per_row = 4
        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("我的卡组")
        title_label.setStyleSheet("font-size: 20px; color: #88AAFF; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 卡组保存管理布局
        save_layout = QHBoxLayout()
        save_layout.addWidget(QLabel("卡组名称:"))
        self.save_deck_name = QLineEdit()
        self.save_deck_name.setPlaceholderText("输入卡组名称")
        self.save_deck_name.setStyleSheet("""
            QLineEdit {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 5px;
                min-width: 150px;
            }
        """)
        save_layout.addWidget(self.save_deck_name)
        
        self.save_current_btn = QPushButton("保存")
        self.save_current_btn.clicked.connect(self.save_current_deck)
        save_layout.addWidget(self.save_current_btn)
        
        main_layout.addLayout(save_layout)
        
        # 已保存卡组加载布局
        deck_layout = QHBoxLayout()
        deck_layout.addWidget(QLabel("已保存卡组:"))
        self.saved_decks_combo = QComboBox()
        self.saved_decks_combo.setStyleSheet("""
            QComboBox {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 5px;
                min-width: 150px;
            }
            QComboBox:hover {
                background-color: rgba(90, 90, 140, 180);
            }
        """)
        self.saved_decks_combo.addItem("选择卡组", None)
        deck_layout.addWidget(self.saved_decks_combo)
        
        self.load_deck_btn = QPushButton("加载")
        self.load_deck_btn.clicked.connect(self.load_selected_deck)
        deck_layout.addWidget(self.load_deck_btn)
        
        self.delete_deck_btn = QPushButton("删除")
        self.delete_deck_btn.clicked.connect(self.delete_selected_deck)
        deck_layout.addWidget(self.delete_deck_btn)
        
        main_layout.addLayout(deck_layout)
        
        # 说明
        desc_label = QLabel("当前卡组中的卡片，右键点击卡片可移除")
        desc_label.setStyleSheet("font-size: 14px; color: #AACCFF;")
        desc_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(desc_label)
        
        # 刷新已保存卡组列表
        self.refresh_saved_decks()
        
        # 卡片显示区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.scroll_content)
        
        # 设置滚动区域样式
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QWidget#ScrollContent {
                background-color: transparent;
            }
        """)
        self.scroll_content.setObjectName("ScrollContent")
        main_layout.addWidget(self.scroll_area)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        self.add_cards_btn = QPushButton("重新构筑卡组")
        self.add_cards_btn.clicked.connect(self.add_cards)
        self.clear_deck_btn = QPushButton("清空所有卡组")
        self.clear_deck_btn.clicked.connect(self.clear_deck)
        self.back_btn = QPushButton("返回主界面")
        self.back_btn.clicked.connect(lambda: self.parent.stacked_widget.setCurrentIndex(0))
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.add_cards_btn)
        btn_layout.addWidget(self.clear_deck_btn)
        btn_layout.addWidget(self.back_btn)
        btn_layout.addStretch()
        
        main_layout.addLayout(btn_layout)
        
        # 加载卡组
        self.load_deck()
    
    def save_current_deck(self):
        """保存当前卡组"""
        deck_name = self.save_deck_name.text().strip()
        if not deck_name:
            QMessageBox.warning(self, "警告", "请输入卡组名称！")
            return
        
        # 获取当前卡组中的卡片
        card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
        if not os.path.exists(card_dir):
            QMessageBox.warning(self, "警告", "当前卡组为空！")
            return
        
        card_files = [f for f in os.listdir(card_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        if not card_files:
            QMessageBox.warning(self, "警告", "当前卡组为空！")
            return
        
        try:
            # 创建保存卡组的目录
            decks_dir = os.path.join(get_exe_dir(), "saved_decks")
            os.makedirs(decks_dir, exist_ok=True)
            
            # 构建卡组数据
            deck_data = {
                "name": deck_name,
                "cards": card_files,
                "timestamp": int(time.time())
            }
            
            # 保存到文件
            deck_file = os.path.join(decks_dir, f"{deck_name}.json")
            with open(deck_file, 'w', encoding='utf-8') as f:
                json.dump(deck_data, f, ensure_ascii=False, indent=2)
            
            QMessageBox.information(self, "成功", f"卡组 '{deck_name}' 已保存！")
            self.parent.log_output.append(f"[卡组] 已保存卡组 '{deck_name}'")
            
            # 清空输入框
            self.save_deck_name.clear()
            
            # 刷新已保存卡组列表
            self.refresh_saved_decks()
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存卡组失败: {str(e)}")
            self.parent.log_output.append(f"[卡组] 保存卡组失败: {str(e)}")

    def refresh_saved_decks(self):
        """刷新已保存卡组列表"""
        if hasattr(self, 'saved_decks_combo'):
            self.saved_decks_combo.clear()
            self.saved_decks_combo.addItem("选择卡组", None)
            
            decks_dir = os.path.join(get_exe_dir(), "saved_decks")
            if os.path.exists(decks_dir):
                for file in os.listdir(decks_dir):
                    if file.endswith('.json'):
                        deck_file = os.path.join(decks_dir, file)
                        try:
                            with open(deck_file, 'r', encoding='utf-8') as f:
                                deck_data = json.load(f)
                            self.saved_decks_combo.addItem(deck_data.get('name', file[:-5]), file)
                        except Exception as e:
                            print(f"读取卡组文件失败: {deck_file} - {e}")
            
        # 同时刷新CardSelectPage中的卡组列表
        if hasattr(self.parent, 'card_select_page'):
            self.parent.card_select_page.refresh_saved_decks()
            
    def load_selected_deck(self):
        """加载选中的已保存卡组"""
        deck_file = self.saved_decks_combo.itemData(self.saved_decks_combo.currentIndex())
        if not deck_file:
            QMessageBox.warning(self, "警告", "请选择要加载的卡组！")
            return
        
        try:
            decks_dir = os.path.join(get_exe_dir(), "saved_decks")
            deck_path = os.path.join(decks_dir, deck_file)
            
            with open(deck_path, 'r', encoding='utf-8') as f:
                deck_data = json.load(f)
            
            # 清空当前卡组
            card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
            for file in os.listdir(card_dir):
                file_path = os.path.join(card_dir, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    print(f"删除文件失败: {file_path} - {e}")
            
            # 复制卡片到当前卡组
            source_dir = os.path.join(get_exe_dir(), "quanka")
            success_count = 0
            for card_file in deck_data.get('cards', []):
                # 查找卡片在quanka目录中的路径
                src = None
                for root, _, files in os.walk(source_dir):
                    if card_file in files:
                        src = os.path.join(root, card_file)
                        break
                
                if src and os.path.exists(src):
                    dst = os.path.join(card_dir, card_file)
                    try:
                        shutil.copy2(src, dst)
                        success_count += 1
                    except Exception as e:
                        print(f"复制文件失败: {src} -> {dst} - {e}")
            
            if success_count > 0:
                # 重新加载卡组显示
                self.load_deck()
                
                QMessageBox.information(self, "成功", f"已加载卡组 '{deck_data.get('name')}'，共 {success_count} 张卡片")
                self.parent.log_output.append(f"[卡组] 已加载卡组 '{deck_data.get('name')}'")
                
                # 刷新卡牌优先级页面（已迁移）
                if hasattr(self.parent, 'card_priority_page'):
                    self.parent.card_priority_page.refresh_card_priority()
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载卡组失败: {str(e)}")
            self.parent.log_output.append(f"[卡组] 加载卡组失败: {str(e)}")
            
    def delete_selected_deck(self):
        """删除选中的已保存卡组"""
        deck_file = self.saved_decks_combo.itemData(self.saved_decks_combo.currentIndex())
        deck_name = self.saved_decks_combo.currentText()
        
        if not deck_file:
            QMessageBox.warning(self, "警告", "请选择要删除的卡组！")
            return
        
        reply = QMessageBox.question(
            self, '确认删除',
            f'确定要删除卡组 "{deck_name}" 吗？此操作不可撤销！',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                decks_dir = os.path.join(get_exe_dir(), "saved_decks")
                deck_path = os.path.join(decks_dir, deck_file)
                
                if os.path.exists(deck_path):
                    os.remove(deck_path)
                    
                    QMessageBox.information(self, "成功", f"卡组 '{deck_name}' 已删除！")
                    self.parent.log_output.append(f"[卡组] 已删除卡组 '{deck_name}'")
                    
                    # 刷新已保存卡组列表
                    self.refresh_saved_decks()
                    
            except Exception as e:
                QMessageBox.warning(self, "错误", f"删除卡组失败: {str(e)}")
                self.parent.log_output.append(f"[卡组] 删除卡组失败: {str(e)}")
                
    def load_deck(self):
        """加载当前卡组"""
        # 清空现有内容
        for i in reversed(range(self.grid_layout.count())): 
            if widget := self.grid_layout.itemAt(i).widget():
                widget.deleteLater()
        
        # 获取卡组目录
        card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
        if not os.path.exists(card_dir):
            no_card_label = QLabel("卡组为空，请添加卡片")
            no_card_label.setStyleSheet("color: #FF8888; font-size: 14px;")
            no_card_label.setAlignment(Qt.AlignCenter)
            self.grid_layout.addWidget(no_card_label, 0, 0)
            return
        
        # 获取所有卡片文件
        card_files = [f for f in os.listdir(card_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        
        if not card_files:
            no_card_label = QLabel("卡组为空，请添加卡片")
            no_card_label.setStyleSheet("color: #FF8888; font-size: 14px;")
            no_card_label.setAlignment(Qt.AlignCenter)
            self.grid_layout.addWidget(no_card_label, 0, 0)
            return
        
        # 刷新已保存卡组列表
        self.refresh_saved_decks()
        
        # 添加卡片
        row, col = 0, 0
        for card_file in card_files:
            card_path = os.path.join(card_dir, card_file)
            
            # 创建卡片容器
            card_container = QWidget()
            card_container.setStyleSheet("""
                background-color: rgba(60, 60, 90, 150);
                border-radius: 10px;
            """)
            card_layout = QVBoxLayout(card_container)
            card_layout.setAlignment(Qt.AlignCenter)
            card_layout.setSpacing(5)
            card_layout.setContentsMargins(5, 5, 5, 5)
            
            # 卡片图片
            card_label = QLabel()
            pixmap = QPixmap(card_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(self.card_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                card_label.setPixmap(pixmap)
            card_label.setAlignment(Qt.AlignCenter)
            card_label.setContextMenuPolicy(Qt.CustomContextMenu)
            card_label.customContextMenuRequested.connect(lambda pos, f=card_file: self.show_context_menu(pos, f))
            
            # 卡片名称
            card_name = card_file.split('_', 1)[-1].rsplit('.', 1)[0]
            name_label = QLabel(card_name)
            name_label.setStyleSheet("""
                QLabel {
                    color: #FFFFFF;
                    background-color: transparent;
                    font-weight: bold;
                    font-size: 12px;
                    padding: 2px;
                    max-width: %dpx;
                }
            """ % (self.card_size.width() - 10))
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setWordWrap(True)
            
            card_layout.addWidget(card_label)
            card_layout.addWidget(name_label)
            self.grid_layout.addWidget(card_container, row, col)
            
            col += 1
            if col >= self.cards_per_row:
                col = 0
                row += 1
    
    def refresh_saved_decks(self):
        """刷新已保存卡组列表"""
        self.saved_decks_combo.clear()
        self.saved_decks_combo.addItem("选择卡组", None)
        
        decks_dir = os.path.join(get_exe_dir(), "saved_decks")
        if os.path.exists(decks_dir):
            for file in os.listdir(decks_dir):
                if file.endswith('.json'):
                    deck_file = os.path.join(decks_dir, file)
                    try:
                        with open(deck_file, 'r', encoding='utf-8') as f:
                            deck_data = json.load(f)
                        self.saved_decks_combo.addItem(deck_data.get('name', file[:-5]), file)
                    except Exception as e:
                        print(f"读取卡组文件失败: {deck_file} - {e}")
    
    def load_selected_deck(self):
        """加载选中的已保存卡组"""
        deck_file = self.saved_decks_combo.itemData(self.saved_decks_combo.currentIndex())
        if not deck_file:
            QMessageBox.warning(self, "警告", "请选择要加载的卡组！")
            return
        
        try:
            decks_dir = os.path.join(get_exe_dir(), "saved_decks")
            deck_path = os.path.join(decks_dir, deck_file)
            
            with open(deck_path, 'r', encoding='utf-8') as f:
                deck_data = json.load(f)
            
            # 清空当前卡组
            card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
            for file in os.listdir(card_dir):
                file_path = os.path.join(card_dir, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    print(f"删除文件失败: {file_path} - {e}")
            
            # 复制卡片到当前卡组
            import shutil
            source_dir = os.path.join(get_exe_dir(), "quanka")
            success_count = 0
            for card_file in deck_data.get('cards', []):
                # 查找卡片在quanka目录中的路径
                src = None
                for root, _, files in os.walk(source_dir):
                    if card_file in files:
                        src = os.path.join(root, card_file)
                        break
                
                if src and os.path.exists(src):
                    dst = os.path.join(card_dir, card_file)
                    try:
                        shutil.copy2(src, dst)
                        success_count += 1
                    except Exception as e:
                        print(f"复制文件失败: {src} -> {dst} - {e}")
            
            if success_count > 0:
                # 重新加载卡组显示
                self.load_deck()
                
                QMessageBox.information(self, "成功", f"已加载卡组 '{deck_data.get('name')}'，共 {success_count} 张卡片")
                self.parent.log_output.append(f"[卡组] 已加载卡组 '{deck_data.get('name')}'")
                
                # 刷新卡牌优先级页面（已迁移）
                if hasattr(self.parent, 'card_priority_page'):
                    self.parent.card_priority_page.refresh_card_priority()
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载卡组失败: {str(e)}")
            self.parent.log_output.append(f"[卡组] 加载卡组失败: {str(e)}")
    
    def delete_selected_deck(self):
        """删除选中的已保存卡组"""
        deck_file = self.saved_decks_combo.itemData(self.saved_decks_combo.currentIndex())
        deck_name = self.saved_decks_combo.currentText()
        
        if not deck_file:
            QMessageBox.warning(self, "警告", "请选择要删除的卡组！")
            return
        
        reply = QMessageBox.question(
            self, '确认删除',
            f'确定要删除卡组 "{deck_name}" 吗？此操作不可撤销！',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                decks_dir = os.path.join(get_exe_dir(), "saved_decks")
                deck_path = os.path.join(decks_dir, deck_file)
                
                if os.path.exists(deck_path):
                    os.remove(deck_path)
                    
                    QMessageBox.information(self, "成功", f"卡组 '{deck_name}' 已删除！")
                    self.parent.log_output.append(f"[卡组] 已删除卡组 '{deck_name}'")
                    
                    # 刷新已保存卡组列表
                    self.refresh_saved_decks()
                    
            except Exception as e:
                QMessageBox.warning(self, "错误", f"删除卡组失败: {str(e)}")
                self.parent.log_output.append(f"[卡组] 删除卡组失败: {str(e)}")
    
    def show_context_menu(self, pos, card_file):
        """显示右键菜单"""
        menu = QMenu(self)
        
        remove_action = QAction("移除", self)
        remove_action.triggered.connect(lambda: self.remove_card(card_file))
        
        menu.addAction(remove_action)
        menu.exec_(self.sender().mapToGlobal(pos))
    
    def remove_card(self, card_file):
        """移除指定卡片"""
        card_path = os.path.join(get_exe_dir(), "shadowverse_cards_cost", card_file)
        if os.path.exists(card_path):
            try:
                os.remove(card_path)
                self.load_deck()  # 重新加载卡组
                self.parent.log_output.append(f"[卡组] 已移除卡片: {card_file}")
                
                # 刷新卡牌优先级页面（已迁移）
                if hasattr(self.parent, 'card_priority_page'):
                    self.parent.card_priority_page.refresh_card_priority()
            except Exception as e:
                QMessageBox.warning(self, "错误", f"移除卡片失败: {str(e)}")
    
    def add_cards(self):
        """添加更多卡片"""
        # 切换到卡组选择页面
        self.parent.stacked_widget.setCurrentIndex(1)
    
    def clear_deck(self):
        """清空整个卡组"""
        reply = QMessageBox.question(
            self, '确认清空',
            '确定要清空整个卡组吗？此操作不可撤销！',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
            if os.path.exists(card_dir):
                # 删除所有卡片文件
                for file in os.listdir(card_dir):
                    file_path = os.path.join(card_dir, file)
                    try:
                        if os.path.isfile(file_path):
                            os.unlink(file_path)
                    except Exception as e:
                        print(f"删除文件失败: {file_path} - {e}")
                
                self.load_deck()  # 重新加载卡组
                self.parent.log_output.append("[卡组] 已清空所有卡片")
                
                # 刷新卡牌优先级页面（已迁移）
                if hasattr(self.parent, 'card_priority_page'):
                    self.parent.card_priority_page.refresh_card_priority()

class CardPriorityPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.config_data = self.load_config()
        self.card_widgets = []
        self.init_ui()

    def init_ui(self):
        self.setObjectName("CardPriorityPage")
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        title_label = QLabel("卡牌优先级")
        title_label.setStyleSheet("font-size: 20px; color: #88AAFF; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        desc_label = QLabel("为卡组中的卡片设置优先级 数字越大优先级越低，优先度上限是999(默认所有卡牌999)")
        desc_label.setStyleSheet("font-size: 12px; color: #AACCFF;")
        main_layout.addWidget(desc_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_area.setWidget(self.scroll_content)
        self.scroll_content.setObjectName("ScrollContent")
        main_layout.addWidget(self.scroll_area)

        # 设置滚动区域样式与主窗口一致
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QWidget#ScrollContent {
                background-color: transparent;
            }
        """)
        self.scroll_content.setObjectName("ScrollContent")
        main_layout.addWidget(self.scroll_area)

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存优先级")
        self.save_btn.clicked.connect(self.save_config)
        self.back_btn = QPushButton("返回主界面")
        self.back_btn.clicked.connect(lambda: self.parent.stacked_widget.setCurrentIndex(0))
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.back_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        self.load_card_priority_settings()

    def load_config(self):
        config_path = os.path.join(get_exe_dir(), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def load_card_priority_settings(self):
        # 清空现有内容
        for i in reversed(range(self.scroll_layout.count())):
            widget = self.scroll_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        self.card_widgets = []

        card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
        if not os.path.exists(card_dir):
            no_card_label = QLabel("未找到卡组卡片，请先在'卡组选择'页面选择卡片")
            no_card_label.setStyleSheet("color: #FF8888; font-size: 14px;")
            no_card_label.setAlignment(Qt.AlignCenter)
            self.scroll_layout.addWidget(no_card_label)
            return

        card_files = [f for f in os.listdir(card_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        if not card_files:
            no_card_label = QLabel("没有找到卡片，请先在'卡组选择'页面选择卡片")
            no_card_label.setStyleSheet("color: #FF8888; font-size: 14px;")
            no_card_label.setAlignment(Qt.AlignCenter)
            self.scroll_layout.addWidget(no_card_label)
            return

        for card_file in card_files:
            card_name = card_file.split('_', 1)[-1].rsplit('.', 1)[0]
            card_row = QWidget()
            card_row.setStyleSheet("background-color: rgba(60, 60, 90, 150); border-radius: 10px;")
            row_layout = QHBoxLayout(card_row)
            row_layout.setContentsMargins(10, 5, 10, 5)

            card_label = QLabel()
            card_path = os.path.join(get_exe_dir(), "shadowverse_cards_cost", card_file)
            pixmap = QPixmap(card_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(80, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                card_label.setPixmap(pixmap)
            card_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(card_label)

            name_label = QLabel(card_name)
            name_label.setStyleSheet("color: #FFFFFF; font-weight: bold; min-width: 120px;")
            name_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(name_label)

            row_layout.addWidget(QLabel("出牌优先级:"))
            play_priority_input = QLineEdit()
            play_priority_input.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
            play_priority_input.setMaximumWidth(50)
            high_priority = self.config_data.get("high_priority_cards", {}).get(card_name, {})
            if high_priority:
                play_priority_input.setText(str(high_priority.get("priority", "")))
            row_layout.addWidget(play_priority_input)

            row_layout.addWidget(QLabel("进化优先级:"))
            evolve_priority_input = QLineEdit()
            evolve_priority_input.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
            evolve_priority_input.setMaximumWidth(50)
            evolve_priority = self.config_data.get("evolve_priority_cards", {}).get(card_name, {})
            if evolve_priority:
                evolve_priority_input.setText(str(evolve_priority.get("priority", "")))
            row_layout.addWidget(evolve_priority_input)

            self.card_widgets.append({
                "card_name": card_name,
                "play_priority": play_priority_input,
                "evolve_priority": evolve_priority_input
            })

            self.scroll_layout.addWidget(card_row)

        self.scroll_layout.addStretch()

    def refresh_card_priority(self):
        current_settings = {}
        for card in self.card_widgets:
            play_priority = card["play_priority"].text().strip()
            evolve_priority = card["evolve_priority"].text().strip()
            current_settings[card["card_name"]] = {"play": play_priority, "evolve": evolve_priority}

        self.load_card_priority_settings()

        for card in self.card_widgets:
            card_name = card["card_name"]
            if card_name in current_settings:
                settings = current_settings[card_name]
                if settings["play"]:
                    card["play_priority"].setText(settings["play"])
                if settings["evolve"]:
                    card["evolve_priority"].setText(settings["evolve"]) 

    def get_current_config(self):
        high_priority_cards = {}
        evolve_priority_cards = {}
        for card in self.card_widgets:
            card_name = card["card_name"]
            play_priority_text = card["play_priority"].text().strip()
            if play_priority_text:
                try:
                    priority = int(play_priority_text)
                    high_priority_cards[card_name] = {"priority": priority}
                except Exception:
                    pass
            evolve_priority_text = card["evolve_priority"].text().strip()
            if evolve_priority_text:
                try:
                    priority = int(evolve_priority_text)
                    evolve_priority_cards[card_name] = {"priority": priority}
                except Exception:
                    pass
        result = {}
        if high_priority_cards:
            result["high_priority_cards"] = high_priority_cards
        if evolve_priority_cards:
            result["evolve_priority_cards"] = evolve_priority_cards
        return result

    def save_config(self):
        # 仅保存卡牌优先级部分，合并磁盘上的其余配置
        high_priority_cards = {}
        evolve_priority_cards = {}
        for card in self.card_widgets:
            card_name = card["card_name"]
            play_priority_text = card["play_priority"].text().strip()
            if play_priority_text:
                try:
                    priority = int(play_priority_text)
                    if priority < 0 or priority > 999:
                        raise ValueError("优先级必须在0-999之间")
                    high_priority_cards[card_name] = {"priority": priority}
                except Exception as e:
                    QMessageBox.warning(self, "输入错误", f"卡片 '{card_name}' 的出牌优先级设置错误: {str(e)}")
                    return
            evolve_priority_text = card["evolve_priority"].text().strip()
            if evolve_priority_text:
                try:
                    priority = int(evolve_priority_text)
                    if priority < 0 or priority > 999:
                        raise ValueError("优先级必须在0-999之间")
                    evolve_priority_cards[card_name] = {"priority": priority}
                except Exception as e:
                    QMessageBox.warning(self, "输入错误", f"卡片 '{card_name}' 的进化优先级设置错误: {str(e)}")
                    return

        config_path = os.path.join(get_exe_dir(), "config.json")
        existing = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        if high_priority_cards:
            existing["high_priority_cards"] = high_priority_cards
        elif "high_priority_cards" in existing:
            del existing["high_priority_cards"]

        if evolve_priority_cards:
            existing["evolve_priority_cards"] = evolve_priority_cards
        elif "evolve_priority_cards" in existing:
            del existing["evolve_priority_cards"]

        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(existing, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "成功", "卡牌优先级已保存！")
            if hasattr(self.parent, 'log_output'):
                self.parent.log_output.append("[配置] 卡牌优先级已更新")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存卡牌优先级失败: {str(e)}")

class SharePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("卡组应用和分享")
        title_label.setStyleSheet("font-size: 20px; color: #88AAFF; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 卡组应用部分
        apply_group = QGroupBox("卡组应用")
        apply_layout = QVBoxLayout(apply_group)
        
        self.share_code_input = QLineEdit()
        self.share_code_input.setPlaceholderText("在此输入分享码...")
        self.share_code_input.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
        
        apply_btn = QPushButton("应用")
        apply_btn.clicked.connect(self.apply_share_code)
        
        apply_layout.addWidget(QLabel("输入分享码:"))
        apply_layout.addWidget(self.share_code_input)
        apply_layout.addWidget(apply_btn)
        
        # 卡组分享部分
        share_group = QGroupBox("卡组分享")
        share_layout = QVBoxLayout(share_group)
        
        self.share_code_output = QLineEdit()
        self.share_code_output.setReadOnly(True)
        self.share_code_output.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
        
        share_btn = QPushButton("生成分享码")
        share_btn.clicked.connect(self.generate_share_code)
        
        copy_btn = QPushButton("复制分享码")
        copy_btn.clicked.connect(self.copy_share_code)
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(share_btn)
        btn_layout.addWidget(copy_btn)
        
        share_layout.addWidget(QLabel("您的分享码:"))
        share_layout.addWidget(self.share_code_output)
        share_layout.addLayout(btn_layout)
        
        # 返回按钮
        back_btn = QPushButton("返回主界面")
        back_btn.clicked.connect(lambda: self.parent.stacked_widget.setCurrentIndex(0))
        
        # 添加到主布局
        main_layout.addWidget(apply_group)
        main_layout.addWidget(share_group)
        main_layout.addStretch()
        main_layout.addWidget(back_btn)
    
    def generate_share_code(self):
        """生成分享码"""
        try:
            # 获取当前卡组和配置
            card_files = []
            card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
            if os.path.exists(card_dir):
                card_files = [f for f in os.listdir(card_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            
            # 读取磁盘上的完整配置（包含参数设置与卡牌优先级）以确保分享码包含完整内容
            config_path = os.path.join(get_exe_dir(), "config.json")
            config_data = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                except Exception:
                    config_data = {}
            
            # 创建分享数据
            share_data = {
                "version": 2,  # 更新版本号以兼容新格式
                "cards": card_files,
                "config": config_data,
                "timestamp": int(time.time())
            }
            
            # 转换为JSON并压缩
            json_data = json.dumps(share_data, ensure_ascii=False)
            compressed = zlib.compress(json_data.encode('utf-8'))
            
            # 转换为base64作为分享码
            share_code = base64.b64encode(compressed).decode('ascii')
            
            self.share_code_output.setText(share_code)
            self.parent.log_output.append("[分享] 分享码已生成")
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"生成分享码失败: {str(e)}")
            self.parent.log_output.append(f"[分享] 生成分享码失败: {str(e)}")
    
    def copy_share_code(self):
        """复制分享码到剪贴板"""
        if self.share_code_output.text():
            clipboard = QApplication.clipboard()
            clipboard.setText(self.share_code_output.text())
            self.parent.log_output.append("[分享] 分享码已复制到剪贴板")
            QMessageBox.information(self, "成功", "分享码已复制到剪贴板！")
    
    def apply_share_code(self):
        """应用分享码"""
        share_code = self.share_code_input.text().strip()
        if not share_code:
            QMessageBox.warning(self, "警告", "请输入有效的分享码！")
            return
        
        try:
            # 解码分享码
            compressed = base64.b64decode(share_code.encode('ascii'))
            json_data = zlib.decompress(compressed).decode('utf-8')
            share_data = json.loads(json_data)
            
            # 验证版本
            version = share_data.get("version", 1)
            if version not in [1, 2]:
                raise ValueError("不支持的分享码版本")
            
            # 应用卡组
            card_dir = os.path.join(get_exe_dir(), "shadowverse_cards_cost")
            os.makedirs(card_dir, exist_ok=True)
            
            # 清空现有卡组
            for f in os.listdir(card_dir):
                os.remove(os.path.join(card_dir, f))
            
            # 复制卡片
            source_dir = os.path.join(get_exe_dir(), "quanka")
            for card_file in share_data["cards"]:
                # 支持旧版本和新版本的卡片路径
                src = None
                
                # 尝试在根目录查找
                root_path = os.path.join(source_dir, card_file)
                if os.path.exists(root_path):
                    src = root_path
                else:
                    # 在新版本分类结构中查找
                    for root, dirs, files in os.walk(source_dir):
                        if card_file in files:
                            src = os.path.join(root, card_file)
                            break
                
                if src and os.path.exists(src):
                    dst = os.path.join(card_dir, card_file)
                    shutil.copy2(src, dst)
                else:
                    self.parent.log_output.append(f"[分享] 未找到卡片: {card_file}")
            
            # 应用配置
            config_path = os.path.join(get_exe_dir(), "config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(share_data["config"], f, indent=4, ensure_ascii=False)

            # 刷新UI：更新参数设置页与卡牌优先级页
            if hasattr(self.parent, 'config_page'):
                self.parent.config_page.refresh_config_display()
            if hasattr(self.parent, 'card_priority_page'):
                self.parent.card_priority_page.refresh_card_priority()

            # 刷新我的卡组页面
            if hasattr(self.parent, 'my_deck_page'):
                self.parent.my_deck_page.load_deck()
            
            QMessageBox.information(self, "成功", "卡组和配置已成功应用！")
            self.parent.log_output.append(f"[分享] 已成功应用分享码中的卡组和配置")
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"应用分享码失败: {str(e)}")
            self.parent.log_output.append(f"[分享] 应用分享码失败: {str(e)}")

class ShadowverseUI(QMainWindow):
    def __init__(self):
        super().__init__()
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
        self.log_listener = LogListener(self)
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
        central_widget.setStyleSheet("""
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
        """)
        
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
                self.size(), 
                Qt.IgnoreAspectRatio, 
                Qt.SmoothTransformation
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
        self.server_combo.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
        server_layout.addWidget(self.server_combo)
        server_layout.addStretch()
        frame_layout.addLayout(server_layout)
        
        # ADB端口
        adb_layout = QHBoxLayout()
        adb_layout.addWidget(QLabel("ADB 端口:"))
        self.adb_input = QLineEdit("127.0.0.1:16384")
        self.adb_input.setFixedWidth(150)  # 增加宽度以完整显示地址
        self.adb_input.setStyleSheet("background-color: rgba(80, 80, 120, 180); color: white;")
        adb_layout.addWidget(self.adb_input)
        adb_layout.addStretch()
        frame_layout.addLayout(adb_layout)
        
        # 深色识别
        dark_layout = QHBoxLayout()
        dark_layout.addWidget(QLabel("深色识别:"))
        self.deep_color_checkbox = QCheckBox()
        self.deep_color_checkbox.setStyleSheet("QCheckBox::indicator { width: 20px; height: 20px; }")
        dark_layout.addWidget(self.deep_color_checkbox)
        dark_layout.addStretch()
        frame_layout.addLayout(dark_layout)
        
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
        
        # 第一行：连接设备 | 开始运行
        btn_layout.addWidget(self.connect_btn, 0, 0)
        btn_layout.addWidget(self.start_btn, 0, 1)
        
        # 第二行：暂停运行 | 恢复运行
        btn_layout.addWidget(self.pause_btn, 1, 0)
        btn_layout.addWidget(self.resume_btn, 1, 1)
        
        left_layout.addLayout(btn_layout)
        control_layout.addWidget(left_widget)
        
        # 中间统计区域
        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)
        
        stats_frame = QFrame()
        stats_frame.setObjectName("StatsFrame")
        grid_layout = QGridLayout(stats_frame)
        
        # 只保留当前状态和运行时间
        grid_layout.addWidget(QLabel("当前状态:"), 0, 0)
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: #FF5555;")
        grid_layout.addWidget(self.status_label, 0, 1)
        
        grid_layout.addWidget(QLabel("运行时间:"), 1, 0)
        self.run_time_label = QLabel("00:00:00")
        self.run_time_label.setObjectName("StatValue")
        grid_layout.addWidget(self.run_time_label, 1, 1)
        
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
        
        self.card_priority_btn = QPushButton("卡牌优先级")
        self.card_priority_btn.setFixedHeight(35)
        self.card_priority_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(5))
        
        self.my_deck_btn = QPushButton("我的卡组")
        self.my_deck_btn.setFixedHeight(35)
        self.my_deck_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(4))
        
        self.share_btn = QPushButton("卡组应用和分享")
        self.share_btn.setFixedHeight(35)
        self.share_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(3))
        
        # 紧凑排列按钮
        right_layout.addWidget(self.card_select_btn) # 卡组选择按钮        
        right_layout.addWidget(self.my_deck_btn) # 我的卡组按钮
        right_layout.addWidget(self.card_priority_btn) # 卡牌优先级按钮
        right_layout.addWidget(self.config_btn) # 参数设置按钮
        # right_layout.addWidget(self.share_btn) # 卡组应用和分享按钮
        right_layout.addStretch() # 底部间距
        
        control_layout.addWidget(right_widget) # 右侧功能按钮区域
        layout.addWidget(control_widget) # 控制按钮区域
        
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
        
        # 加载当前配置设置
        self.load_current_config()
    
    def load_current_config(self):
        """加载当前配置设置"""
        config_path = os.path.join(get_exe_dir(), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
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
                    self.deep_color_checkbox.setChecked(last_device.get("screenshot_deep_color", False))
                else:
                    # 如果没有设备配置，设置默认值
                    self.adb_input.setText("127.0.0.1:16384")
            except Exception as e:
                self.log_output.append(f"加载配置失败: {str(e)}")
                # 出错时也设置默认值
                self.adb_input.setText("127.0.0.1:16384")
        else:
            # 如果配置文件不存在，设置默认值
            self.adb_input.setText("127.0.0.1:16384")
    
    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.maximize_btn.setText("□")
        else:
            self.showMaximized()
            self.maximize_btn.setText("❐")
    
    def connect_device(self):
        adb_port = self.adb_input.text()
        self.append_log(f"正在连接设备: {adb_port}...")
        self.connect_btn.setEnabled(False)
        
        # 获取服务器和深色识别设置
        is_global = self.server_combo.currentText() == "国际服"
        deep_color = self.deep_color_checkbox.isChecked()
        
        # 更新配置文件
        config_path = os.path.join(get_exe_dir(), "config.json")
        config = {}
        
        try:
            # 读取现有配置
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            # 每次只保留当前连接的设备 - 优化点
            config["devices"] = []  # 清空现有设备列表
            
            # 添加新设备
            new_device = {
                "name": f"模拟器-{adb_port}",
                "serial": adb_port,
                "is_global": is_global,
                "screenshot_deep_color": deep_color
            }
            config["devices"].append(new_device)
            
            # 保存配置
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            self.append_log(f"设备设置已更新: 服务器={self.server_combo.currentText()}, 深色识别={'开启' if deep_color else '关闭'}")
            
        except Exception as e:
            self.append_log(f"更新配置文件失败: {str(e)}")
        
        # 创建脚本运行线程
        self.script_thread = ScriptRunner()
        self.script_thread.status_signal.connect(self.update_status)
        self.script_thread.stats_signal.connect(self.update_stats)
        
        # 模拟连接成功
        self.start_btn.setEnabled(True)
        self.status_label.setText("已连接")
        self.status_label.setStyleSheet("color: #55FF55;")
    
    def append_log(self, message):
        """安全地添加日志到UI"""
        self.log_output.append(message)
        # 自动滚动到底部
        self.log_output.verticalScrollBar().setValue(
            self.log_output.verticalScrollBar().maximum()
        )
    
    def start_script(self):
        if self.script_thread and not self.script_thread.isRunning():
            self.script_thread.start()
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)  # 开始时恢复按钮禁用
            self.timer.start(1000)
            self.append_log("===== 脚本开始运行 =====")

    def pause_script(self):
        """暂停脚本执行"""
        if self.script_thread and self.script_thread.isRunning():
            # 发送暂停命令
            command_queue.put('p')
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
            command_queue.put('r')
            self.status_label.setText("运行中")
            self.status_label.setStyleSheet("color: #55FF55;")
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.timer.start(1000)
            self.append_log("[控制] 脚本已恢复")
    
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
        elif status == "已暂停":
            self.status_label.setStyleSheet("color: #FFFF55;")
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
        else:
            self.status_label.setStyleSheet("color: #FF5555;")
    
    def update_stats(self, stats):
        # 不再更新被删除的统计项
        # 更新运行时间
        run_time = stats.get('run_time', 0)
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
        if hasattr(self, 'drag_position') and event.buttons() == Qt.LeftButton:
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
            command_queue.put('e')
            self.script_thread.quit()
            self.script_thread.wait(2000)  # 等待2秒
        
        event.accept()

class LogListener(QThread):
    """日志监听线程"""
    log_signal = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = True
        
    def run(self):
        while self.running:
            try:
                # 非阻塞获取日志
                while not log_queue.empty():
                    log = log_queue.get_nowait()
                    self.log_signal.emit(log)
                time.sleep(0.1)  # 避免CPU占用过高
            except Exception as e:
                print(f"日志监听异常: {str(e)}")
    
    def stop(self):
        self.running = False

class ScriptRunner(QThread):
    """脚本运行线程"""
    status_signal = pyqtSignal(str)
    stats_signal = pyqtSignal(dict)  # 统计信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_time = 0
        self.battle_count = 0
        self.turn_count = 0
        self.current_turn = 0
    
    def run(self):
        try:
            self.start_time = time.time()
            self.status_signal.emit("运行中")
            
            # 运行主脚本（启用命令监听）
            run_main_script(enable_command_listener=True)
                
        except Exception as e:
            log_queue.put(f"脚本运行出错: {str(e)}")
            traceback.print_exc()
        finally:
            self.status_signal.emit("已停止")
            log_queue.put("===== 脚本运行结束 =====")

def main():
    app = QApplication(sys.argv)
    window = ShadowverseUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()