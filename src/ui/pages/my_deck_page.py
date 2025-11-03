#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
我的卡组页面模块
显示和管理当前已选择的卡组卡片
"""

import os
import shutil
import json
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, 
    QGridLayout, QMessageBox, QMenu, QAction, QInputDialog, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap
from src.utils.resource_utils import resource_path

class MyDeckPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.current_page = 0
        self.cards_per_row = 4
        self.card_size = QSize(110, 154)  # 增大卡片尺寸
        self.deck_cards = []
        
        # 使用resource_path获取正确的路径
        self.deck_dir = resource_path("shadowverse_cards_cost")
        self.quanka_dir = resource_path("quanka")
        
        # 设置窗口拉伸策略
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 添加详细调试信息
        print(f"调试: 当前文件路径: {os.path.abspath(__file__)}")
        print(f"调试: 当前目录: {os.path.dirname(os.path.abspath(__file__))}")
        print(f"调试: deck_dir路径: {self.deck_dir}")
        print(f"调试: deck_dir存在: {os.path.exists(self.deck_dir)}")
        print(f"调试: quanka_dir路径: {self.quanka_dir}")
        print(f"调试: quanka_dir存在: {os.path.exists(self.quanka_dir)}")
        
        # 确保目录存在
        os.makedirs(self.deck_dir, exist_ok=True)
        print(f"调试: 已确保deck_dir存在")
        
        self.init_ui()

    def init_ui(self):
        # 设置整体背景色
        self.setStyleSheet("background-color: #2D2D4A;")
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = QLabel("我的卡组")
        title_label.setStyleSheet(
            "font-size: 24px; color: #88AAFF; font-weight: bold;"
            "padding: 10px; border-bottom: 2px solid #4A4A7F;"
        )
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # 操作按钮组 - 美化样式
        btn_group_layout = QHBoxLayout()
        btn_group_layout.setSpacing(10)
        
        # 添加卡片按钮
        self.add_cards_btn = QPushButton("添加卡片")
        self.add_cards_btn.setStyleSheet(
            "QPushButton {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4A7AFF, stop:1 #3A5ACF);"
            "    color: white;"
            "    font-size: 14px;"
            "    padding: 8px 16px;"
            "    border-radius: 5px;"
            "    border: 1px solid #5A5A8F;"
            "}"
            "QPushButton:hover {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5A8AFF, stop:1 #4A6ACF);"
            "}"
            "QPushButton:pressed {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3A6ACF, stop:1 #2A4ABF);"
            "}"
        )
        self.add_cards_btn.clicked.connect(lambda: self.parent.stacked_widget.setCurrentIndex(1))
        
        # 清空卡组按钮
        self.clear_deck_btn = QPushButton("清空卡组")
        self.clear_deck_btn.setStyleSheet(
            "QPushButton {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF6A6A, stop:1 #CF5A5A);"
            "    color: white;"
            "    font-size: 14px;"
            "    padding: 8px 16px;"
            "    border-radius: 5px;"
            "    border: 1px solid #5A5A8F;"
            "}"
            "QPushButton:hover {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF7A7A, stop:1 #CF6A6A);"
            "}"
            "QPushButton:pressed {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #CF5A5A, stop:1 #BF4A4A);"
            "}"
        )
        self.clear_deck_btn.clicked.connect(self.clear_deck)
        
        # 保存卡组按钮
        self.save_deck_btn = QPushButton("保存当前卡组")
        self.save_deck_btn.setStyleSheet(
            "QPushButton {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6AFF6A, stop:1 #5ACF5A);"
            "    color: white;"
            "    font-size: 14px;"
            "    padding: 8px 16px;"
            "    border-radius: 5px;"
            "    border: 1px solid #5A5A8F;"
            "}"
            "QPushButton:hover {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7AFF7A, stop:1 #6ACF6A);"
            "}"
            "QPushButton:pressed {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5ACF5A, stop:1 #4ABF4A);"
            "}"
        )
        self.save_deck_btn.clicked.connect(self.save_current_deck)
        
        # 加载卡组按钮
        self.load_deck_btn = QPushButton("加载保存的卡组")
        self.load_deck_btn.setStyleSheet(
            "QPushButton {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFAA6A, stop:1 #CF8A5A);"
            "    color: white;"
            "    font-size: 14px;"
            "    padding: 8px 16px;"
            "    border-radius: 5px;"
            "    border: 1px solid #5A5A8F;"
            "}"
            "QPushButton:hover {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFBA7A, stop:1 #CF9A6A);"
            "}"
            "QPushButton:pressed {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #CF8A5A, stop:1 #BF7A4A);"
            "}"
        )
        self.load_deck_btn.clicked.connect(self.load_saved_deck)
        
        btn_group_layout.addWidget(self.add_cards_btn)
        btn_group_layout.addWidget(self.clear_deck_btn)
        btn_group_layout.addWidget(self.save_deck_btn)
        btn_group_layout.addWidget(self.load_deck_btn)
        btn_group_layout.addStretch()
        
        main_layout.addLayout(btn_group_layout)
        
        # 卡片显示区域 - 美化样式
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setAlignment(Qt.AlignTop)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setContentsMargins(15, 15, 15, 15)
        self.scroll_area.setWidget(self.scroll_content)
        
        # 设置滚动区域样式
        self.scroll_area.setStyleSheet(
            "QScrollArea {"
            "    border: 1px solid #4A4A7F;"
            "    border-radius: 8px;"
            "    background-color: #2D2D4A;"
            "}"
            "QScrollArea QScrollBar:vertical {"
            "    width: 12px;"
            "    background-color: #2D2D4A;"
            "    border-radius: 6px;"
            "}"
            "QScrollArea QScrollBar::handle:vertical {"
            "    background-color: #4A4A7F;"
            "    border-radius: 6px;"
            "    min-height: 20px;"
            "}"
            "QScrollArea QScrollBar::handle:vertical:hover {"
            "    background-color: #5A5A8F;"
            "}"
            "QScrollArea QScrollBar::add-line:vertical, QScrollArea QScrollBar::sub-line:vertical {"
            "    background-color: transparent;"
            "}"
        )
        self.scroll_content.setObjectName("ScrollContent")
        self.scroll_content.setStyleSheet("background-color: #2D2D4A;")
        main_layout.addWidget(self.scroll_area)
        
        # 说明标签
        self.card_count_label = QLabel("当前卡组没有卡片")
        self.card_count_label.setStyleSheet("font-size: 14px; color: #AACCFF;")
        self.card_count_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.card_count_label)
        
        # 返回按钮 - 美化样式
        back_layout = QHBoxLayout()
        back_layout.addStretch()
        
        self.back_btn = QPushButton("返回主界面")
        self.back_btn.setStyleSheet(
            "QPushButton {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8A8A8A, stop:1 #6A6A6A);"
            "    color: white;"
            "    font-size: 14px;"
            "    padding: 8px 20px;"
            "    border-radius: 5px;"
            "    border: 1px solid #5A5A8F;"
            "}"
            "QPushButton:hover {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #9A9A9A, stop:1 #7A7A7A);"
            "}"
            "QPushButton:pressed {"
            "    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7A7A7A, stop:1 #5A5A5A);"
            "}"
        )
        self.back_btn.clicked.connect(lambda: self.parent.stacked_widget.setCurrentIndex(0))
        back_layout.addWidget(self.back_btn)
        back_layout.addStretch()
        
        main_layout.addLayout(back_layout)
        
        # 加载卡组
        self.load_deck()

    def load_deck(self):
        """加载当前卡组"""
        self.deck_cards = []
        
        # 添加调试信息
        print(f"调试: load_deck方法中的self.deck_dir: {self.deck_dir}")
        print(f"调试: load_deck方法中的self.deck_dir存在: {os.path.exists(self.deck_dir)}")
        
        if os.path.exists(self.deck_dir):
            # 获取所有卡片文件
            files = os.listdir(self.deck_dir)
            print(f"调试: deck_dir中的文件数量: {len(files)}")
            if files:
                print(f"调试: deck_dir中的前5个文件: {files[:5]}")
                
            for file in files:
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    self.deck_cards.append(file)
            
            # 按费用和名称排序
            self.deck_cards.sort(key=lambda x: (
                self.get_card_cost(x),
                x.lower()
            ))
            
            print(f"调试: 成功加载的卡片数量: {len(self.deck_cards)}")
        else:
            print(f"调试: deck_dir不存在，无法加载卡组")
        
        # 更新说明标签
        if len(self.deck_cards) == 0:
            self.card_count_label.setText("当前卡组没有卡片")
        else:
            self.card_count_label.setText(f"当前卡组共有 {len(self.deck_cards)} 张卡片")
        
        # 显示卡片
        print(f"调试: 准备显示卡片，self.deck_cards数量: {len(self.deck_cards)}")
        self.display_deck()
        print(f"调试: 卡片显示完成，grid_layout中的项目数量: {self.grid_layout.count()}")

    def display_deck(self):
        """显示卡组卡片"""
        # 清空现有内容
        for i in reversed(range(self.grid_layout.count())):
            if widget := self.grid_layout.itemAt(i).widget():
                widget.deleteLater()
        
        # 添加卡片
        print(f"调试: display_deck方法中的self.deck_cards数量: {len(self.deck_cards)}")
        print(f"调试: display_deck方法中的self.grid_layout: {self.grid_layout}")
        print(f"调试: display_deck方法中的self.scroll_area: {self.scroll_area}")
        print(f"调试: display_deck方法中的self.scroll_content: {self.scroll_content}")
        
        if self.deck_cards:
            row, col = 0, 0
            for card_file in self.deck_cards:
                card_path = os.path.join(self.deck_dir, card_file)
                
                # 创建卡片容器 - 添加悬停效果
                card_container = QWidget()
                card_container.setStyleSheet(
                    "QWidget {"
                    "    background-color: rgba(60, 60, 90, 180);"
                    "    border-radius: 10px;"
                    "    border: 1px solid transparent;"
                    "}"
                    "QWidget:hover {"
                    "    background-color: rgba(74, 122, 255, 0.2);"
                    "    border: 1px solid #88AAFF;"
                    "}"
                )
                card_layout = QVBoxLayout(card_container)
                card_layout.setAlignment(Qt.AlignCenter)
                card_layout.setSpacing(5)
                card_layout.setContentsMargins(5, 5, 5, 5)
                
                # 卡片图片
                card_label = QLabel()
                pixmap = QPixmap(card_path)
                if not pixmap.isNull():
                    print(f"调试: 成功加载图片: {card_path}")
                    pixmap = pixmap.scaled(self.card_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    card_label.setPixmap(pixmap)
                else:
                    print(f"调试: 图片加载失败: {card_path}")
                    card_label.setText("图片加载失败")
                card_label.setAlignment(Qt.AlignCenter)
                card_label.setContextMenuPolicy(Qt.CustomContextMenu)
                card_label.customContextMenuRequested.connect(lambda pos, f=card_file: self.show_context_menu(pos, f))
                
                # 右键菜单事件处理
                card_label.mousePressEvent = lambda event, f=card_file: self.on_card_clicked(event, f)
                
                # 卡片名称 - 美化样式
                card_name = ' '.join(card_file.split('_', 1)[-1].rsplit('.', 1)[0].split('_'))
                name_label = QLabel(card_name)
                name_label.setStyleSheet(
                    "QLabel {"
                    "    color: #FFFFFF;"
                    "    background-color: rgba(74, 74, 127, 0.3);"
                    "    font-weight: bold;"
                    "    font-size: 12px;"
                    "    padding: 4px 8px;"
                    "    border-radius: 4px;"
                    "    max-width: %dpx;"
                    "}"
                % (self.card_size.width() - 10))
                name_label.setAlignment(Qt.AlignCenter)
                name_label.setWordWrap(True)
                
                # 移除按钮
                remove_btn = QPushButton("移除")
                remove_btn.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(120, 60, 60, 180);
                        color: white;
                        border-radius: 5px;
                        padding: 2px 5px;
                        font-size: 12px;
                        min-width: 60px;
                    }
                    QPushButton:hover {
                        background-color: rgba(140, 70, 70, 180);
                    }
                """)
                remove_btn.clicked.connect(lambda state, f=card_file: self.remove_card(f))
                
                card_layout.addWidget(card_label)
                card_layout.addWidget(name_label)
                card_layout.addWidget(remove_btn)
                self.grid_layout.addWidget(card_container, row, col)
                
                col += 1
                if col >= self.cards_per_row:
                    col = 0
                    row += 1

    def on_card_clicked(self, event, card_file):
        """卡片点击事件处理"""
        if event.button() == Qt.RightButton:
            self.show_context_menu(event.pos(), card_file)

    def show_context_menu(self, pos, card_file):
        """显示右键菜单"""
        menu = QMenu()
        remove_action = QAction("移除卡片", self)
        remove_action.triggered.connect(lambda: self.remove_card(card_file))
        menu.addAction(remove_action)
        
        # 使用self.scroll_area来获取全局位置，避免依赖sender()
        global_pos = self.scroll_area.viewport().mapToGlobal(pos)
        menu.exec_(global_pos)

    def remove_card(self, card_file):
        """移除卡片"""
        confirm = QMessageBox.question(
            self,
            "确认移除",
            f"确定要移除卡片 '{card_file}' 吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if confirm == QMessageBox.Yes:
            try:
                file_path = os.path.join(self.deck_dir, card_file)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    self.parent.log_output.append(f"[卡组] 已移除卡片: {card_file}")
                    self.load_deck()  # 重新加载卡组
            except Exception as e:
                QMessageBox.warning(self, "移除失败", f"移除卡片失败: {str(e)}")
                print(f"移除卡片失败: {str(e)}")

    def add_cards(self):
        """添加卡片（从CardSelectPage调用）"""
        if hasattr(self.parent, 'card_select_page'):
            self.parent.stacked_widget.setCurrentIndex(1)

    def clear_deck(self):
        """清空卡组"""
        if not self.deck_cards:
            QMessageBox.information(self, "提示", "卡组已经是空的了")
            return
        
        confirm = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空当前卡组吗？此操作不可撤销！",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if confirm == QMessageBox.Yes:
            try:
                for card_file in self.deck_cards:
                    file_path = os.path.join(self.deck_dir, card_file)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                
                self.parent.log_output.append("[卡组] 已清空所有卡片")
                self.load_deck()  # 重新加载卡组
                
                # 刷新参数设置页面的卡片显示
                if hasattr(self.parent, 'config_page'):
                    self.parent.config_page.refresh_card_priority()
                
                QMessageBox.information(self, "成功", "已清空当前卡组")
            except Exception as e:
                QMessageBox.warning(self, "清空失败", f"清空卡组失败: {str(e)}")
                print(f"清空卡组失败: {str(e)}")

    def save_current_deck(self):
        """保存当前卡组"""
        if not self.deck_cards:
            QMessageBox.warning(self, "无法保存", "当前卡组为空，无法保存")
            return
        
        # 获取保存名称
        deck_name, ok = QInputDialog.getText(
            self,
            "保存卡组",
            "请输入卡组名称:"
        )
        
        if ok and deck_name.strip():
            deck_name = deck_name.strip()
            
            # 确保quanka目录存在
            os.makedirs(self.quanka_dir, exist_ok=True)
            
            backup_path = os.path.join(self.quanka_dir, f"{deck_name}.json")
            
            # 构建卡组数据
            deck_data = {
                "name": deck_name,
                "cards": self.deck_cards,
                "card_count": len(self.deck_cards),
                "save_time": os.path.getmtime(self.deck_dir)  # 添加保存时间
            }
            
            # 检查是否已存在同名卡组
            overwrite = True
            if os.path.exists(backup_path):
                confirm = QMessageBox.question(
                    self,
                    "确认覆盖",
                    f"已存在同名卡组 '{deck_name}'，是否覆盖？",
                    QMessageBox.Yes | QMessageBox.No
                )
                overwrite = confirm == QMessageBox.Yes
            
            if overwrite:
                try:
                    with open(backup_path, 'w', encoding='utf-8') as f:
                        json.dump(deck_data, f, ensure_ascii=False, indent=2)
                    
                    self.parent.log_output.append(f"[卡组] 已保存卡组: {deck_name}")
                    QMessageBox.information(self, "成功", f"卡组 '{deck_name}' 已保存")
                except Exception as e:
                    QMessageBox.warning(self, "保存失败", f"保存卡组失败: {str(e)}")
                    print(f"保存卡组失败: {str(e)}")

    def load_saved_deck(self):
        """加载保存的卡组"""
        # 检查备份目录是否存在
        if not os.path.exists(self.quanka_dir):
            QMessageBox.information(self, "提示", "没有保存的卡组")
            return
        
        # 获取所有保存的卡组
        saved_decks = []
        for file in os.listdir(self.quanka_dir):
            if file.lower().endswith('.json'):
                try:
                    with open(os.path.join(self.quanka_dir, file), 'r', encoding='utf-8') as f:
                        deck_data = json.load(f)
                        saved_decks.append((deck_data.get('name', file[:-5]), file))
                except:
                    pass
        
        if not saved_decks:
            QMessageBox.information(self, "提示", "没有保存的卡组")
            return
        
        # 显示选择对话框
        deck_names = [deck[0] for deck in saved_decks]
        selected_name, ok = QInputDialog.getItem(
            self,
            "加载卡组",
            "请选择要加载的卡组:",
            deck_names,
            0,
            False
        )
        
        if ok and selected_name:
            # 找到对应的文件名
            selected_file = None
            for name, file in saved_decks:
                if name == selected_name:
                    selected_file = file
                    break
            
            if selected_file:
                try:
                    with open(os.path.join(self.quanka_dir, selected_file), 'r', encoding='utf-8') as f:
                        deck_data = json.load(f)
                    
                    # 清空当前卡组
                    for card_file in self.deck_cards:
                        file_path = os.path.join(self.deck_dir, card_file)
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    
                    # 从quanka目录复制卡片到当前卡组
                    success_count = 0
                    fail_count = 0
                    # 使用项目根目录下的quanka文件夹
                    quanka_dir = self.quanka_dir
                    
                    # 添加调试信息
                    print(f"调试: load_saved_deck方法中的quanka_dir: {quanka_dir}")
                    print(f"调试: load_saved_deck方法中的quanka_dir存在: {os.path.exists(quanka_dir)}")
                    
                    # 确保quanka目录存在
                    os.makedirs(quanka_dir, exist_ok=True)
                    
                    # 确保deck_dir存在
                    os.makedirs(self.deck_dir, exist_ok=True)
                    
                    # 首先显示quanka目录下的所有子目录
                    if os.path.exists(quanka_dir):
                        subdirs = [d for d in os.listdir(quanka_dir) if os.path.isdir(os.path.join(quanka_dir, d))]
                        print(f"调试: quanka目录下的子目录: {subdirs}")
                    
                    for card_file in deck_data.get('cards', []):
                        # 查找卡片在quanka目录中的位置
                        card_found = False
                        card_path = None
                        
                        # 尝试直接在quanka目录下查找
                        direct_path = os.path.join(quanka_dir, card_file)
                        if os.path.exists(direct_path):
                            card_path = direct_path
                            card_found = True
                        else:
                            # 递归搜索整个quanka目录
                            for root, _, files in os.walk(quanka_dir):
                                if card_file in files:
                                    card_path = os.path.join(root, card_file)
                                    card_found = True
                                    break
                        
                        # 如果找到了卡片，进行复制
                        if card_found and card_path:
                            dst = os.path.join(self.deck_dir, card_file)
                            try:
                                shutil.copy2(card_path, dst)
                                success_count += 1
                                print(f"调试: 成功复制卡片: {card_path} -> {dst}")
                            except Exception as e:
                                print(f"复制卡片失败: {card_path} -> {dst} - {str(e)}")
                                fail_count += 1
                        else:
                            fail_count += 1
                            print(f"未找到卡片: {card_file}")
                    
                    self.parent.log_output.append(f"[卡组] 已加载卡组: {selected_name}")
                    self.load_deck()  # 重新加载卡组
                    
                    # 刷新参数设置页面的卡片显示
                    if hasattr(self.parent, 'config_page'):
                        self.parent.config_page.refresh_card_priority()
                    
                    message = f"成功加载卡组 '{selected_name}'\n"
                    message += f"成功复制 {success_count} 张卡片\n"
                    if fail_count > 0:
                        message += f"无法找到 {fail_count} 张卡片（可能已删除或更新）"
                    
                    QMessageBox.information(self, "成功", message)
                except Exception as e:
                    QMessageBox.warning(self, "加载失败", f"加载卡组失败: {str(e)}")
                    print(f"加载卡组失败: {str(e)}")

    def get_card_cost(self, card_file):
        """从文件名提取费用数字"""
        try:
            return int(card_file.split('_')[0])
        except:
            return 0  # 如果解析失败，默认0费