#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI工具函数模块
提供UI相关的通用工具函数
"""

import os
import sys
from PyQt5.QtGui import QFont, QFontDatabase

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