"""
影之诗自动对战脚本 - 核心模块包
"""

__version__ = "1.0.0"
__author__ = "Auto SZB Team"

# 导出主要模块
from .config import ConfigManager
from .utils import setup_gpu, display_disclaimer_and_get_consent
from .device import DeviceManager
from .ui import NotificationManager

__all__ = [
    'ConfigManager',
    'setup_gpu',
    'display_disclaimer_and_get_consent', 
    'DeviceManager',
    'NotificationManager'
] 