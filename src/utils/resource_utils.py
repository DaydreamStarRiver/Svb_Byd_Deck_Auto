"""
资源工具模块
处理资源文件路径和加载
"""

import os
import sys


def resource_path(relative_path: str) -> str:
    """
    获取资源文件的绝对路径，兼容PyInstaller和源码运行
    
    Args:
        relative_path: 相对路径
        
    Returns:
        绝对路径
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller打包后的路径处理
        # 首先尝试exe同目录下的文件（用于外部模型文件）
        exe_dir = os.path.dirname(sys.executable)
        exe_path = os.path.join(exe_dir, relative_path)
        
        if os.path.exists(exe_path):
            # 如果exe同目录下存在文件，优先使用
            return exe_path
        else:
            # 否则使用打包在内部的路径
            return os.path.join(sys._MEIPASS, relative_path)
    else:
        # 源码运行时的路径 - 从当前文件位置计算到项目根目录
        current_dir = os.path.dirname(os.path.abspath(__file__))  # src/utils/
        project_root = os.path.dirname(os.path.dirname(current_dir))  # 项目根目录
        return os.path.join(project_root, relative_path)


def ensure_directory(path: str) -> bool:
    """
    确保目录存在，如果不存在则创建
    
    Args:
        path: 目录路径
        
    Returns:
        是否成功
    """
    try:
        if not os.path.exists(path):
            os.makedirs(path)
        return True
    except Exception:
        return False


def get_model_directory() -> str:
    """
    获取模型目录路径
    
    Returns:
        模型目录的绝对路径
    """
    return resource_path("models")


def get_templates_directory() -> str:
    """
    获取模板目录路径
    
    Returns:
        模板目录的绝对路径
    """
    return resource_path("templates")


def get_resource_path(relative_path: str) -> str:
    """
    兼容旧代码的别名，等价于resource_path
    """
    return resource_path(relative_path) 