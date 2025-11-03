# -*- coding: utf-8 -*-
"""
卡组选择页面模块
提供从卡片库中选择卡片组成卡组的功能
"""

import os
import shutil
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, 
    QGroupBox, QGridLayout, QScrollArea, QComboBox, QMessageBox, QFrame
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap, QLinearGradient, QColor
from src.utils.resource_utils import resource_path

class CardSelectPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.current_page = 0
        self.selected_cards = []
        self.cards_per_row = 4
        self.card_size = QSize(110, 154)  # 稍微增大卡片尺寸以提高显示质量
        self.cost_filters = {}  # 存储费用筛选按钮
        self.all_cards = []     # 所有卡片
        self.filtered_cards = [] # 筛选后的卡片
        self.card_categories = []  # 卡片分类
        self.current_category = None  # 当前选择的分类
        self.init_ui()

    def init_ui(self):
        # 设置主窗口背景
        self.setStyleSheet("background-color: #2D2D4A;")
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题区域
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(60, 60, 90, 100);
                border-radius: 10px;
                border: 1px solid #4A4A7F;
            }
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        title_label = QLabel("卡组选择")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                color: #88AAFF;
                font-weight: bold;
                padding-bottom: 5px;
            }
        """)
        title_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title_label)
        
        desc_label = QLabel("从以下卡牌中选择您的卡组，点击保存应用选择")
        desc_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                color: #CCDDFF;
                font-weight: bold;
            }
        """)
        desc_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(desc_label)
        
        main_layout.addWidget(header_frame)

        # 搜索和筛选区域
        filter_frame = QFrame()
        filter_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(60, 60, 90, 100);
                border-radius: 10px;
                border: 1px solid #4A4A7F;
                padding: 10px;
            }
        """)
        filter_layout = QVBoxLayout(filter_frame)
        
        # 搜索框和分类选择
        search_layout = QHBoxLayout()
        search_layout.setSpacing(15)
        
        # 分类选择下拉框
        self.category_combo = QComboBox()
        self.category_combo.addItem("所有分类", None)
        self.category_combo.setStyleSheet("""
            QComboBox {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                font-size: 14px;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 6px 10px;
                min-width: 120px;
            }
            QComboBox:hover {
                background-color: rgba(90, 90, 140, 180);
                border-color: #6A6AAF;
            }
            QComboBox::drop-down {
                border: none;
                background-color: rgba(80, 80, 120, 180);
                width: 25px;
                border-left: 1px solid #5A5A8F;
            }
            QComboBox::down-arrow {
                image: url(:/icons/down_arrow.png);
                width: 12px;
                height: 12px;
            }
        """)
        self.category_combo.currentIndexChanged.connect(self.on_category_changed)
        
        category_label = QLabel("分类:")
        category_label.setStyleSheet("color: #CCDDFF; font-size: 14px;")
        search_layout.addWidget(category_label)
        search_layout.addWidget(self.category_combo)
        
        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索卡牌...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(80, 80, 120, 180);
                color: white;
                font-size: 14px;
                border: 1px solid #5A5A8F;
                border-radius: 5px;
                padding: 6px 10px;
                min-width: 200px;
            }
            QLineEdit:hover {
                border-color: #6A6AAF;
            }
            QLineEdit:focus {
                border-color: #88AAFF;
                background-color: rgba(90, 90, 140, 180);
            }
            QLineEdit::placeholder-text {
                color: #AAAACC;
                font-style: italic;
            }
        """)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        
        search_label = QLabel("搜索:")
        search_label.setStyleSheet("color: #CCDDFF; font-size: 14px;")
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addStretch()
        
        filter_layout.addLayout(search_layout)
        
        # 费用筛选栏
        self.init_cost_filter(filter_layout)
        
        main_layout.addWidget(filter_frame)
        
        # 卡片显示区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setAlignment(Qt.AlignTop)
        self.grid_layout.setSpacing(10)
        self.scroll_area.setWidget(self.scroll_content)
        
        # 设置滚动区域样式
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: rgba(45, 45, 75, 150);
                border: 1px solid #4A4A7F;
                border-radius: 10px;
            }
            QScrollArea QScrollBar:vertical {
                background-color: rgba(60, 60, 90, 150);
                width: 10px;
                border-radius: 5px;
                margin: 2px;
            }
            QScrollArea QScrollBar::handle:vertical {
                background-color: rgba(80, 80, 120, 150);
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollArea QScrollBar::handle:vertical:hover {
                background-color: rgba(90, 90, 140, 150);
            }
            QScrollArea QScrollBar::add-line:vertical, 
            QScrollArea QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QWidget#ScrollContent {
                background-color: transparent;
                padding: 10px;
            }
        """)
        self.scroll_content.setObjectName("ScrollContent")
        main_layout.addWidget(self.scroll_area)
        
        # 底部控制区域
        bottom_frame = QFrame()
        bottom_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(60, 60, 90, 100);
                border-radius: 10px;
                border: 1px solid #4A4A7F;
            }
        """)
        bottom_layout = QVBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(20, 10, 20, 15)
        
        # 翻页控制
        page_control_layout = QHBoxLayout()
        page_control_layout.setSpacing(10)
        
        # 创建美观的分页控件
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #4A4A7F, stop: 1 #3A3A6F);
                color: white;
                font-size: 14px;
                border: 1px solid #5A5A8F;
                border-radius: 6px;
                padding: 6px 12px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #5A5A9F, stop: 1 #4A4A8F);
                border-color: #6A6AAF;
            }
            QPushButton:disabled {
                background-color: #3A3A6F;
                color: #8888AA;
                border-color: #4A4A7F;
            }
            QPushButton:pressed {
                background-color: #3A3A6F;
            }
        """)
        self.prev_btn.clicked.connect(self.prev_page)
        
        self.page_label = QLabel("第1页")
        self.page_label.setStyleSheet("""
            QLabel {
                color: #CCDDFF;
                font-size: 14px;
                padding: 6px 15px;
                min-width: 100px;
                text-align: center;
                background-color: rgba(60, 60, 90, 150);
                border-radius: 6px;
                border: 1px solid #4A4A7F;
            }
        """)
        
        self.next_btn = QPushButton("下一页")
        self.next_btn.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #4A4A7F, stop: 1 #3A3A6F);
                color: white;
                font-size: 14px;
                border: 1px solid #5A5A8F;
                border-radius: 6px;
                padding: 6px 12px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #5A5A9F, stop: 1 #4A4A8F);
                border-color: #6A6AAF;
            }
            QPushButton:disabled {
                background-color: #3A3A6F;
                color: #8888AA;
                border-color: #4A4A7F;
            }
            QPushButton:pressed {
                background-color: #3A3A6F;
            }
        """)
        self.next_btn.clicked.connect(self.next_page)
        
        page_control_layout.addStretch()
        page_control_layout.addWidget(self.prev_btn)
        page_control_layout.addWidget(self.page_label)
        page_control_layout.addWidget(self.next_btn)
        page_control_layout.addStretch()
        
        bottom_layout.addLayout(page_control_layout)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        
        self.save_btn = QPushButton("保存卡组")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #6A8AFF, stop: 1 #5A7AFF);
                color: white;
                font-size: 14px;
                border: 1px solid #7A9AFF;
                border-radius: 6px;
                padding: 8px 16px;
                min-width: 120px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #7AA9FF, stop: 1 #6A8AFF);
                border-color: #8AB9FF;
            }
            QPushButton:disabled {
                background-color: #5A7ABF;
                color: #8888AA;
                border-color: #6A8ACF;
            }
            QPushButton:pressed {
                background-color: #5A7AFF;
            }
        """)
        self.save_btn.clicked.connect(self.save_selection)
        
        self.back_btn = QPushButton("返回主界面")
        self.back_btn.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #4A4A7F, stop: 1 #3A3A6F);
                color: white;
                font-size: 14px;
                border: 1px solid #5A5A8F;
                border-radius: 6px;
                padding: 8px 16px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #5A5A9F, stop: 1 #4A4A8F);
                border-color: #6A6AAF;
            }
            QPushButton:pressed {
                background-color: #3A3A6F;
            }
        """)
        self.back_btn.clicked.connect(lambda: self.parent.stacked_widget.setCurrentIndex(0))
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.back_btn)
        btn_layout.addStretch()
        
        bottom_layout.addLayout(btn_layout)
        
        main_layout.addWidget(bottom_frame)
        
        # 加载卡片
        self.load_cards()

    def init_cost_filter(self, filter_layout):
        """初始化费用筛选控件"""
        cost_filter_frame = QFrame()
        cost_filter_frame.setStyleSheet("background-color: transparent;")
        cost_filter_layout = QHBoxLayout(cost_filter_frame)
        cost_filter_layout.setSpacing(8)
        
        cost_label = QLabel("费用筛选:")
        cost_label.setStyleSheet("color: #CCDDFF; font-size: 14px;")
        cost_filter_layout.addWidget(cost_label)
        
        # 添加0-10费选项
        for cost in range(0, 11):
            btn = QPushButton(f"{cost}费")
            btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(80, 80, 120, 180);
                    color: white;
                    font-size: 14px;
                    border: 1px solid #5A5A8F;
                    border-radius: 4px;
                    padding: 5px 10px;
                    min-width: 50px;
                    text-align: center;
                }
                QPushButton:checked {
                    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #88AAFF, stop: 1 #789AFF);
                    font-weight: bold;
                    border-color: #88AAFF;
                }
                QPushButton:hover {
                    background-color: rgba(90, 90, 140, 180);
                    border-color: #6A6AAF;
                }
                QPushButton:pressed {
                    background-color: rgba(70, 70, 110, 180);
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
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #88AAFF, stop: 1 #789AFF);
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: 1px solid #88AAFF;
                border-radius: 4px;
                padding: 5px 12px;
                min-width: 60px;
                text-align: center;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #98BAFF, stop: 1 #88AAFF);
                border-color: #98BAFF;
            }
            QPushButton:pressed {
                background-color: #789AFF;
            }
        """)
        all_btn.clicked.connect(self.select_all_costs)
        cost_filter_layout.addWidget(all_btn)
        
        cost_filter_layout.addStretch()
        filter_layout.addWidget(cost_filter_frame)

    def load_cards(self):
        """加载所有卡片和分类"""
        card_dir = resource_path("quanka")
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
            card_path = resource_path(os.path.join("quanka", card_data["path"]))
            
            # 创建卡片容器
            card_container = QFrame()
            card_container.setStyleSheet("""
                QFrame {
                    background-color: rgba(60, 60, 90, 180);
                    border-radius: 10px;
                    border: 1px solid #5A5A8F;
                    padding: 5px;
                    margin: 5px;
                }
                QFrame:hover {
                    border-color: #6A6AAF;
                    background-color: rgba(70, 70, 100, 180);
                }
            """)
            card_layout = QVBoxLayout(card_container)
            card_layout.setAlignment(Qt.AlignCenter)
            card_layout.setSpacing(6)
            card_layout.setContentsMargins(5, 5, 5, 5)
            
            # 卡片图片
            card_label = QLabel()
            card_label.setStyleSheet("background-color: rgba(45, 45, 75, 180); border-radius: 5px;")
            pixmap = QPixmap(card_path)
            if not pixmap.isNull():
                # 添加平滑变换以提高图片质量
                pixmap = pixmap.scaled(self.card_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                card_label.setPixmap(pixmap)
            card_label.setAlignment(Qt.AlignCenter)
            card_label.mousePressEvent = lambda event, f=card_data["file"]: self.toggle_card_selection_by_click(f)
            
            # 卡片名称
            card_name = ' '.join(card_data["file"].split('_', 1)[-1].rsplit('.', 1)[0].split('_'))
            name_label = QLabel(card_name)
            style_sheet = """
                QLabel {
                    color: #FFFFFF;
                    background-color: transparent;
                    font-weight: bold;
                    font-size: 12px;
                    padding: 3px;
                    max-width: %dpx;
                }
            """ % (self.card_size.width() - 10)
            name_label.setStyleSheet(style_sheet)
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setWordWrap(True)
            
            # 选择框
            checkbox = QPushButton("选择")
            checkbox.setCheckable(True)
            checkbox.setChecked(card_data["file"] in self.selected_cards)
            checkbox.setStyleSheet("""
                QPushButton {
                    background-color: rgba(80, 80, 120, 180);
                    color: white;
                    border-radius: 5px;
                    padding: 3px 8px;
                    font-size: 12px;
                    min-width: 70px;
                    border: 1px solid #5A5A8F;
                }
                QPushButton:checked {
                    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #88AAFF, stop: 1 #789AFF);
                    font-weight: bold;
                    border-color: #88AAFF;
                }
                QPushButton:hover {
                    background-color: rgba(90, 90, 140, 180);
                    border-color: #6A6AAF;
                }
                QPushButton:pressed {
                    background-color: rgba(70, 70, 110, 180);
                }
            """)
            checkbox.clicked.connect(lambda state, f=card_data["file"]: self.toggle_card_selection(f, state))
            
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
        if state:
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
        
        target_dir = resource_path("shadowverse_cards_cost")
        os.makedirs(target_dir, exist_ok=True)
        
        # 不清空目标文件夹，只添加新卡片
        success_count = 0
        for card_file in self.selected_cards:
            # 查找卡片完整路径
            src = None
            for card in self.all_cards:
                if card["file"] == card_file:
                    src = resource_path(os.path.join("quanka", card["path"]))
                    break
            
            if src and os.path.exists(src):
                dst = os.path.join(target_dir, card_file)
                # 如果文件已存在，跳过
                if os.path.exists(dst):
                    continue
                try:
                    shutil.copy2(src, dst)
                    success_count += 1
                except Exception as e:
                    print(f"复制文件失败: {src} -> {dst} - {e}")
        
        if success_count > 0:
            QMessageBox.information(self, "成功", f"已添加 {success_count} 张卡片到卡组！")
            self.parent.log_output.append(f"[卡组] 已添加 {success_count} 张卡片")
            
            # 刷新参数设置页面的卡片显示
            if hasattr(self.parent, 'config_page'):
                self.parent.config_page.refresh_card_priority()
            # 刷新自己卡组页面
            if hasattr(self.parent, 'my_deck_page'):
                self.parent.my_deck_page.load_deck()