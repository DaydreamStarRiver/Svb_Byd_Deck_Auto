import os
import sys
from PyQt5.QtGui import QFont, QFontDatabase

def get_exe_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def load_custom_font(size=10):
    font = QFont("Microsoft YaHei", size)
    font_path = os.path.join(get_exe_dir(), "猫啃什锦黑.otf")
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_families = QFontDatabase.applicationFontFamilies(font_id)
            if font_families:
                font = QFont(font_families[0], size)
    return font
