#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分享页面模块
提供卡组分享和导入功能
"""

import os
import shutil
import json
import base64
import zlib
import hashlib
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, 
    QScrollArea, QGridLayout, QMessageBox, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap, QFont
from src.utils.resource_utils import resource_path

class SharePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.version = "1.0.0"
        
        # 设置窗口拉伸策略
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.init_ui()

    def init_ui(self):
        # 设置整体背景色
        self.setStyleSheet("background-color: #2D2D4A;")
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = QLabel("卡组分享和应用")
        title_label.setStyleSheet(
            "font-size: 24px; color: #88AAFF; font-weight: bold;"
            "padding: 10px; border-bottom: 2px solid #4A4A7F;"
        )
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # 分享码输入区域 - 美化样式
        share_layout = QVBoxLayout()
        share_layout.setSpacing(10)
        
        # 应用分享码
        apply_layout = QHBoxLayout()
        share_code_label = QLabel("分享码:")
        share_code_label.setStyleSheet("font-size: 14px; color: #CCDDFF;")
        apply_layout.addWidget(share_code_label)
        
        self.share_code_input = QLineEdit()
        self.share_code_input.setPlaceholderText("请输入分享码...")
        self.share_code_input.setStyleSheet(
            "QLineEdit {"
            "    background-color: #3A3A6A;"
            "    color: white;"
            "    font-size: 14px;"
            "    padding: 8px;"
            "    border: 1px solid #5A5A8F;"
            "    border-radius: 5px;"
            "}"
            "QLineEdit:focus {"
            "    border: 1px solid #88AAFF;"
            "    background-color: #4A4A7A;"
            "}"
        )
        self.share_code_input.setMinimumWidth(350)
        apply_layout.addWidget(self.share_code_input)
        
        self.apply_btn = QPushButton("应用")
        self.apply_btn.setStyleSheet(
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
        self.apply_btn.clicked.connect(self.apply_share_code)
        apply_layout.addWidget(self.apply_btn)
        
        share_layout.addLayout(apply_layout)
        
        # 生成分享码
        generate_layout = QHBoxLayout()
        current_share_label = QLabel("当前卡组分享码:")
        current_share_label.setStyleSheet("font-size: 14px; color: #CCDDFF;")
        generate_layout.addWidget(current_share_label)
        
        self.share_code_output = QLineEdit()
        self.share_code_output.setReadOnly(True)
        self.share_code_output.setStyleSheet(
            "QLineEdit {"
            "    background-color: #3A3A6A;"
            "    color: #CCCCCC;"
            "    font-size: 14px;"
            "    padding: 8px;"
            "    border: 1px solid #5A5A8F;"
            "    border-radius: 5px;"
            "}"
        )
        generate_layout.addWidget(self.share_code_output)
        
        self.copy_btn = QPushButton("复制")
        self.copy_btn.setStyleSheet(
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
        self.copy_btn.clicked.connect(self.copy_share_code)
        generate_layout.addWidget(self.copy_btn)
        
        self.generate_btn = QPushButton("生成")
        self.generate_btn.setStyleSheet(
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
        self.generate_btn.clicked.connect(self.generate_share_code)
        generate_layout.addWidget(self.generate_btn)
        
        share_layout.addLayout(generate_layout)
        
        main_layout.addLayout(share_layout)

        # 说明文本
        info_label = QLabel("注意事项：")
        info_label.setStyleSheet("font-size: 14px; color: #88AAFF; font-weight: bold;")
        main_layout.addWidget(info_label)
        
        notice_text = (
            "• 分享码包含当前卡组的所有卡片信息\n"+
            "• 分享码版本: " + self.version + "\n"+
            "• 应用分享码将替换当前卡组\n"+
            "• 如果卡片不存在，将尝试从卡库中查找"
        )
        notice_label = QLabel(notice_text)
        notice_label.setStyleSheet("font-size: 12px; color: #AACCFF;")
        notice_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        main_layout.addWidget(notice_label)
        
        # 预览区域
        preview_label = QLabel("当前卡组预览")
        preview_label.setStyleSheet("font-size: 16px; color: #88AAFF; font-weight: bold;")
        main_layout.addWidget(preview_label)
        
        # 卡片预览区域 - 美化样式
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setAlignment(Qt.AlignTop)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setContentsMargins(15, 15, 15, 15)
        self.scroll_area.setWidget(self.scroll_content)
        
        # 设置滚动区域样式
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #4A4A7F;
                border-radius: 8px;
                background-color: #2D2D4A;
            }
            QScrollArea QScrollBar:vertical {
                width: 12px;
                background-color: #2D2D4A;
                border-radius: 6px;
            }
            QScrollArea QScrollBar::handle:vertical {
                background-color: #4A4A7F;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollArea QScrollBar::handle:vertical:hover {
                background-color: #5A5A8F;
            }
            QScrollArea QScrollBar::add-line:vertical, QScrollArea QScrollBar::sub-line:vertical {
                background-color: transparent;
            }
        """)
        self.scroll_content.setObjectName("ScrollContent")
        self.scroll_content.setStyleSheet("background-color: #2D2D4A;")
        main_layout.addWidget(self.scroll_area)
        
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
        
        # 显示当前卡组预览
        self.update_deck_preview()

    def update_deck_preview(self):
        """更新卡组预览"""
        # 清空现有内容
        for i in reversed(range(self.grid_layout.count())):
            if widget := self.grid_layout.itemAt(i).widget():
                widget.deleteLater()
        
        # 加载当前卡组
        deck_dir = resource_path("shadowverse_cards_cost")
        deck_cards = []
        
        if os.path.exists(deck_dir):
            # 获取所有卡片文件
            for file in os.listdir(deck_dir):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    deck_cards.append(file)
            
            # 按费用和名称排序
            deck_cards.sort(key=lambda x: (
                self.get_card_cost(x),
                x.lower()
            ))
        
        # 显示卡片预览
        if deck_cards:
            cards_per_row = 6  # 预览模式每行显示更多卡片
            card_size = QSize(80, 112)  # 缩小预览卡片尺寸
            row, col = 0, 0
            
            for card_file in deck_cards:
                card_path = os.path.join(deck_dir, card_file)
                
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
                
                # 卡片图片 - 增大尺寸并添加圆角
                card_label = QLabel()
                pixmap = QPixmap(card_path)
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(card_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    card_label.setPixmap(pixmap)
                    card_label.setStyleSheet("border-radius: 3px;")
                card_label.setAlignment(Qt.AlignCenter)
                
                # 卡片名称（只显示前几个字符） - 美化样式
                card_name = ' '.join(card_file.split('_', 1)[-1].rsplit('.', 1)[0].split('_'))
                if len(card_name) > 8:
                    card_name = card_name[:8] + "..."
                name_label = QLabel(card_name)
                name_label.setStyleSheet("""
                    QLabel {
                        color: #FFFFFF;
                        background-color: rgba(74, 74, 127, 0.3);
                        font-size: 10px;
                        padding: 4px 8px;
                        border-radius: 4px;
                        max-width: %dpx;
                    }
                """ % (card_size.width() - 10))
                name_label.setAlignment(Qt.AlignCenter)
                name_label.setWordWrap(True)
                
                card_layout.addWidget(card_label)
                card_layout.addWidget(name_label)
                self.grid_layout.addWidget(card_container, row, col)
                
                col += 1
                if col >= cards_per_row:
                    col = 0
                    row += 1
        else:
            # 无卡片提示
            no_cards_label = QLabel("当前没有卡组可以分享")
            no_cards_label.setStyleSheet("font-size: 14px; color: #AACCFF;")
            no_cards_label.setAlignment(Qt.AlignCenter)
            self.grid_layout.addWidget(no_cards_label, 0, 0)

    def generate_share_code(self):
        """生成分享码"""
        # 加载当前卡组
        deck_dir = resource_path("shadowverse_cards_cost")
        deck_cards = []
        
        if os.path.exists(deck_dir):
            # 获取所有卡片文件
            for file in os.listdir(deck_dir):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    deck_cards.append(file)
        
        if not deck_cards:
            QMessageBox.warning(self, "无法生成分享码", "当前没有卡组可以分享")
            return
        
        # 构建分享数据
        share_data = {
            "version": self.version,
            "cards": deck_cards,
            "card_count": len(deck_cards),
            "timestamp": os.path.getmtime(deck_dir) if os.path.exists(deck_dir) else 0
        }
        
        try:
            # 序列化并压缩数据
            json_data = json.dumps(share_data, ensure_ascii=False).encode('utf-8')
            compressed_data = zlib.compress(json_data, level=9)
            
            # 转换为base64编码
            share_code = base64.urlsafe_b64encode(compressed_data).decode('utf-8')
            
            # 添加校验和
            checksum = hashlib.md5(share_code.encode('utf-8')).hexdigest()[:6]
            final_code = f"{share_code}#{checksum}"
            
            # 更新分享码显示
            self.share_code_output.setText(final_code)
            self.parent.log_output.append("[分享] 已生成卡组分享码")
            
            QMessageBox.information(self, "成功", "分享码已生成，请复制分享给他人")
        except Exception as e:
            QMessageBox.warning(self, "生成失败", f"生成分享码失败: {str(e)}")
            print(f"生成分享码失败: {str(e)}")

    def copy_share_code(self):
        """复制分享码"""
        share_code = self.share_code_output.text()
        if share_code:
            self.parent.clipboard.setText(share_code)
            self.parent.log_output.append("[分享] 已复制分享码到剪贴板")
            QMessageBox.information(self, "成功", "分享码已复制到剪贴板")
        else:
            QMessageBox.warning(self, "复制失败", "请先生成分享码")

    def apply_share_code(self):
        """应用分享码"""
        share_code = self.share_code_input.text().strip()
        if not share_code:
            QMessageBox.warning(self, "应用失败", "请输入分享码")
            return
        
        try:
            # 解析分享码（分离校验和）
            if '#' in share_code:
                code_part, checksum = share_code.rsplit('#', 1)
                # 验证校验和
                calculated_checksum = hashlib.md5(code_part.encode('utf-8')).hexdigest()[:6]
                if checksum != calculated_checksum:
                    QMessageBox.warning(self, "应用失败", "分享码无效或已损坏")
                    return
            else:
                code_part = share_code
            
            # 解码并解压缩数据
            compressed_data = base64.urlsafe_b64decode(code_part)
            json_data = zlib.decompress(compressed_data)
            share_data = json.loads(json_data.decode('utf-8'))
            
            # 验证版本
            if share_data.get('version') != self.version:
                confirm = QMessageBox.question(
                    self,
                    "版本不匹配",
                    f"分享码版本({share_data.get('version')})与当前版本({self.version})不匹配，是否继续？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if confirm == QMessageBox.No:
                    return
            
            # 确认替换当前卡组
            confirm = QMessageBox.question(
                self,
                "确认应用",
                f"将应用包含 {share_data.get('card_count', 0)} 张卡片的卡组，这将替换当前卡组，是否继续？",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if confirm == QMessageBox.Yes:
                # 清空当前卡组
                deck_dir = resource_path("shadowverse_cards_cost")
                os.makedirs(deck_dir, exist_ok=True)
                
                for file in os.listdir(deck_dir):
                    file_path = os.path.join(deck_dir, file)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                
                # 复制卡片到当前卡组
                quanka_dir = resource_path("quanka")
                success_count = 0
                fail_count = 0
                
                for card_file in share_data.get('cards', []):
                    # 查找卡片在quanka目录中的位置
                    card_found = False
                    # 先尝试直接在根目录查找（旧版本格式）
                    direct_path = os.path.join(quanka_dir, card_file)
                    if os.path.exists(direct_path):
                        try:
                            shutil.copy2(direct_path, os.path.join(deck_dir, card_file))
                            success_count += 1
                            card_found = True
                        except Exception as e:
                            print(f"复制卡片失败: {direct_path} -> {deck_dir} - {str(e)}")
                            fail_count += 1
                    
                    # 如果没找到，递归搜索整个quanka目录（新版本分类结构）
                    if not card_found:
                        for root, _, files in os.walk(quanka_dir):
                            if card_file in files:
                                try:
                                    src = os.path.join(root, card_file)
                                    dst = os.path.join(deck_dir, card_file)
                                    shutil.copy2(src, dst)
                                    success_count += 1
                                    card_found = True
                                    break
                                except Exception as e:
                                    print(f"复制卡片失败: {src} -> {dst} - {str(e)}")
                                    fail_count += 1
                                    break
                    
                    if not card_found:
                        fail_count += 1
                        print(f"未找到卡片: {card_file}")
                
                # 保存配置
                config_path = resource_path("config.json")
                try:
                    # 如果文件不存在，创建一个新的配置字典
                    if os.path.exists(config_path):
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                    else:
                        config_data = {}
                    
                    # 更新配置信息
                    config_data['last_imported_share_code'] = share_code
                    config_data['last_import_time'] = os.path.getmtime(deck_dir)
                    
                    with open(config_path, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"保存配置失败: {str(e)}")
                
                # 刷新UI
                self.parent.log_output.append(f"[分享] 已应用分享码，成功导入 {success_count} 张卡片")
                self.update_deck_preview()
                
                # 刷新参数设置页面的卡片显示
                if hasattr(self.parent, 'config_page'):
                    self.parent.config_page.refresh_card_priority()
                # 刷新我的卡组页面
                if hasattr(self.parent, 'my_deck_page'):
                    self.parent.my_deck_page.load_deck()
                
                message = f"成功应用分享码\n"
                message += f"成功导入 {success_count} 张卡片\n"
                if fail_count > 0:
                    message += f"无法找到 {fail_count} 张卡片（可能已更新或删除）"
                
                QMessageBox.information(self, "成功", message)
        except Exception as e:
            QMessageBox.warning(self, "应用失败", f"解析分享码失败: {str(e)}")
            print(f"解析分享码失败: {str(e)}")

    def get_card_cost(self, card_file):
        """从文件名提取费用数字"""
        try:
            return int(card_file.split('_')[0])
        except:
            return 0  # 如果解析失败，默认0费
