"""
用户同意工具模块
处理免责声明和用户同意
"""

import os
import logging
from src.config.settings import DISCLAIMER

logger = logging.getLogger(__name__)


def check_consent_file() -> bool:
    """
    检查是否存在同意文件
    
    Returns:
        bool: 是否已同意
    """
    return os.path.exists("consent.txt")


def save_consent() -> bool:
    """
    保存用户同意状态到文件
    
    Returns:
        bool: 是否保存成功
    """
    try:
        with open("consent.txt", "w", encoding="utf-8") as f:
            f.write("用户已同意免责声明")
        return True
    except Exception as e:
        logger.error(f"保存同意状态失败: {str(e)}")
        return False


def display_disclaimer_and_get_consent() -> bool:
    """
    显示免责声明并获取用户同意
    
    Returns:
        bool: 用户是否同意
    """
    # 清屏
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # 显示声明
    print(DISCLAIMER)
    print("\n" + "=" * 80)
    
    # 检查是否已同意
    if check_consent_file():
        print("\n您已同意免责声明，程序继续运行...")
        return True
    
    # 获取用户同意
    while True:
        response = input("\n请仔细阅读以上声明，输入'同意'表示您已理解并接受所有条款: ").strip()
        
        if response == "同意":
            if save_consent():
                print("\n感谢您的同意，现在可以正常使用本软件。")
                return True
            else:
                print("\n保存同意状态失败，请检查文件权限。")
        else:
            print("\n您必须同意免责声明才能使用本软件。")
            print("输入'退出'将关闭程序，或重新输入'同意'继续使用。")
            
            if response == "退出":
                print("\n您已选择退出程序。")
                return False


def remove_consent() -> bool:
    """
    移除用户同意文件（用于重新获取同意）
    
    Returns:
        bool: 是否移除成功
    """
    try:
        if os.path.exists("consent.txt"):
            os.remove("consent.txt")
            logger.info("已移除用户同意文件")
            return True
        return False
    except Exception as e:
        logger.error(f"移除同意文件失败: {str(e)}")
        return False 