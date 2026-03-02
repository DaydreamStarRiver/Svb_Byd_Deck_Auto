#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影之诗自动对战脚本 2025-07-27
"""

import sys
import os
import logging
import threading
import traceback
import time
import queue
import shutil
from typing import Dict, Any, Optional

# 设置环境变量以避免PyTorch的pin_memory警告
os.environ["PIN_MEMORY"] = "false"

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config import ConfigManager
from src.utils import setup_gpu, display_disclaimer_and_get_consent
from src.device import DeviceManager
from src.ui import NotificationManager
from src.utils.gpu_utils import get_easyocr_reader

# 全局命令队列
command_queue = queue.Queue()
# 全局日志队列
log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    """将日志发送到队列的自定义处理器"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
        
    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_queue.put(msg)
        except Exception:
            self.handleError(record)

def setup_logging(config: Dict[str, Any], log_queue: Optional[queue.Queue] = None) -> logging.Logger:
    """设置日志系统"""
    # 获取日志级别
    log_level = getattr(logging, config.get("ui", {}).get("log_level", "INFO").upper())
    
    # 创建根日志器
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # 避免重复添加处理器
    if not logger.handlers:
        # 创建文件日志处理器
        file_handler = logging.FileHandler("main_log.log", encoding='utf-8')
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        
        # 创建控制台日志处理器
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        
        # 添加处理器
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        # 添加队列处理器（如果提供了队列）
        if log_queue:
            queue_handler = QueueHandler(log_queue)
            queue_handler.setFormatter(console_formatter)
            logger.addHandler(queue_handler)
    
    return logger


def command_listener(device_manager: DeviceManager, logger: logging.Logger):
    """命令监听线程"""
    logger.info("命令监听线程启动")
    logger.info("可用命令: 'p'暂停, 'r'恢复, 'e'退出, 's'统计")
    
    while True:
        try:
            # 使用非阻塞方式获取命令
            try:
                cmd = command_queue.get(timeout=0.5)
            except queue.Empty:
                continue
                
            # 广播命令到所有设备
            for device_state in device_manager.device_states.values():
                device_state.command_queue.put(cmd)
            
            # 处理全局命令
            if cmd == 'e':
                logger.info("收到退出命令，正在停止所有设备...")
                for device_state in device_manager.device_states.values():
                    device_state.script_running = False
                break
            elif cmd == 's':
                logger.info("显示所有设备统计信息:")
                for serial, device_state in device_manager.device_states.items():
                    logger.info(f"\n--- 设备 {serial} 统计 ---")
                    device_state.show_round_statistics()
                    
        except KeyboardInterrupt:
            logger.info("命令监听被中断")
            break
        except Exception as e:
            logger.error(f"命令监听异常: {str(e)}")
            break
    
    logger.info("命令监听线程结束")


def main(enable_command_listener=True):
    """主函数"""
    try:
        # 初始化配置管理器
        config_manager = ConfigManager()
        
        # 验证配置
        if not config_manager.validate_config():
            print("配置验证失败，请检查配置文件")
            return
        
        # 重新加载卡牌优先级配置（确保PyInstaller打包后能正确读取）
        try:
            from src.config.card_priorities import reload_config
            reload_config()
            print("卡牌优先级配置重新加载完成")
        except Exception as e:
            print(f"重新加载卡牌优先级配置失败: {e}")
        
        # 设置日志系统
        logger = setup_logging(config_manager.config, log_queue)
        logger.info("=== 影之诗自动对战脚本启动 ===")
        
        # 显示免责声明并获取用户同意
        if not display_disclaimer_and_get_consent():
            logger.info("用户未同意免责声明，程序退出")
            return
        
        # 设置GPU
        gpu_enabled = setup_gpu()
        if gpu_enabled:
            logger.info("OCR识别GPU加速已启用")
        else:
            logger.info("OCR识别使用CPU模式")

        # 全局初始化OCR reader，确保子线程只用全局实例
        ocr_reader = get_easyocr_reader(gpu_enabled=gpu_enabled)
        if ocr_reader is not None:
            logger.info("全局OCR reader初始化成功")
        else:
            logger.warning("全局OCR reader初始化失败，后续OCR功能不可用")
        
        # 初始化通知管理器
        notification_manager = NotificationManager()
        notification_manager.start()
        
        # 创建设备管理器
        device_manager = DeviceManager(config_manager, notification_manager)
        
        # 启动设备处理
        device_manager.start_all_devices()
        
        # 启动命令监听线程
        command_thread = None
        if enable_command_listener:
            command_thread = threading.Thread(
                target=command_listener,
                args=(device_manager, logger),
                daemon=True
            )
            command_thread.start()
        
        # 等待所有设备完成
        device_manager.wait_for_completion()
        
        # 显示运行总结
        device_manager.show_run_summary()
        
        logger.info("=== 脚本运行完成 ===")
        
    except KeyboardInterrupt:
        logger.info("用户中断脚本执行")
    except Exception as e:
        logger.exception(f"程序运行出错: {str(e)}")
        print(f"程序崩溃: {str(e)}")
        traceback.print_exc()
    finally:
        # 清理PyInstaller临时文件
        cleanup_pyinstaller_temp()
        # 在控制台保持打开
        input("按回车键退出...")
        sys.exit(0)


def cleanup_pyinstaller_temp():
    """清理PyInstaller临时文件，解决打包后临时文件残留导致的问题"""
    try:
        # 检查是否为PyInstaller打包环境
        if not hasattr(sys, '_MEIPASS'):
            return
        
        # 清理多个可能的临时目录
        temp_dirs_to_check = []
        
        # 1. 可执行文件所在目录
        exe_dir = os.path.dirname(sys.executable)
        if exe_dir:
            temp_dirs_to_check.append(exe_dir)
        
        # 2. 系统临时目录（用户提到的）
        import tempfile
        system_temp_dir = tempfile.gettempdir()
        if system_temp_dir:
            temp_dirs_to_check.append(system_temp_dir)
        
        # 3. 用户临时目录（Windows特定）
        if sys.platform.startswith('win'):
            user_temp_dir = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp')
            if os.path.exists(user_temp_dir):
                temp_dirs_to_check.append(user_temp_dir)
        
        # 遍历所有临时目录进行清理
        for temp_dir in temp_dirs_to_check:
            if not os.path.exists(temp_dir):
                continue
            
            print(f"正在检查临时目录: {temp_dir}")
            
            try:
                # 清理以_MEI开头的临时文件夹
                for item in os.listdir(temp_dir):
                    item_path = os.path.join(temp_dir, item)
                    try:
                        if os.path.isdir(item_path) and item.startswith('_MEI'):
                            print(f"正在清理PyInstaller临时文件夹: {item_path}")
                            try:
                                shutil.rmtree(item_path, ignore_errors=True)
                                print(f"已清理: {item_path}")
                            except Exception as e:
                                print(f"清理临时文件夹失败: {item_path}, 错误: {str(e)}")
                    except Exception:
                        continue
                
                # 清理mei相关文件（用户提到的）
                for item in os.listdir(temp_dir):
                    item_path = os.path.join(temp_dir, item)
                    try:
                        if os.path.isfile(item_path) and 'mei' in item.lower():
                            print(f"正在清理PyInstaller临时文件: {item_path}")
                            try:
                                os.remove(item_path)
                                print(f"已清理: {item_path}")
                            except Exception as e:
                                print(f"清理临时文件失败: {item_path}, 错误: {str(e)}")
                    except Exception:
                        continue
            except Exception as e:
                print(f"处理临时目录 {temp_dir} 时出错: {str(e)}")
                continue
                
    except Exception as e:
        print(f"清理PyInstaller临时文件时出错: {str(e)}")
        traceback.print_exc()


if __name__ == "__main__":
    main()