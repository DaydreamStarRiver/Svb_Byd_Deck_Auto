"""
设备管理器
管理所有设备的连接和运行
"""

import threading
import logging
import time
from adbutils import device
import cv2
import numpy as np
import os
import random
from typing import Dict, Any, List
from src.device.device_state import DeviceState
from src.game.game_manager import GameManager
from src.game.game_actions import GameActions

logger = logging.getLogger(__name__)


class DeviceManager:
    """设备管理器类"""
    
    def __init__(self, config_manager, notification_manager):
        self.config_manager = config_manager
        self.notification_manager = notification_manager
        self.device_states: Dict[str, DeviceState] = {}
        self.device_threads: Dict[str, threading.Thread] = {}
    
    def start_all_devices(self):
        """启动所有设备"""
        devices = self.config_manager.get_devices()
        
        if not devices:
            error_msg = "配置文件中未找到设备列表，请添加设备配置"
            logger.error(error_msg)
            self.notification_manager.show_error("配置错误", error_msg)
            return
        
        logger.info(f"发现 {len(devices)} 个设备配置")
        
        for device_config in devices:
            serial = device_config.get("serial")
            if not serial:
                logger.error("设备配置缺少serial字段")
                continue
            
            # 创建设备状态
            device_state = DeviceState(serial, self.config_manager.config, device_config)
            self.device_states[serial] = device_state
            
            # 启动设备工作线程
            thread = threading.Thread(
                target=self._device_worker,
                args=(device_config, device_state),
                daemon=True
            )
            thread.start()
            self.device_threads[serial] = thread
            
            logger.info(f"已启动设备线程: {serial}")
    
    def _device_worker(self, device_config: Dict[str, Any], device_state: DeviceState):
        """设备工作线程"""
        serial = device_config["serial"]
        
        try:
            logger.info(f"设备 {serial} 工作线程开始")
            
            # 连接设备
            if not self._connect_device(device_config, device_state):
                error_msg = f"无法连接设备: {serial}"
                logger.error(error_msg)
                self.notification_manager.show_error(f"设备连接错误: {serial}", error_msg)
                return
            
            # 初始化游戏管理器
            game_manager = GameManager(device_state)
            device_state.game_manager = game_manager
            
            # 运行设备主循环
            self._run_device_loop(device_state, game_manager)
            
        except KeyboardInterrupt:
            device_state.logger.info("用户中断脚本执行")
        except Exception as e:
            logger.exception(f"设备 {serial} 工作线程异常: {str(e)}")
        finally:
            # 清理资源
            self._cleanup_device(device_state)
            logger.info(f"设备 {serial} 工作线程结束")
    
    def _connect_device(self, device_config: Dict[str, Any], device_state: DeviceState) -> bool:
        """连接设备"""
        serial = device_config["serial"]
        max_retries = 5
        retry_delay = 10

        for attempt in range(1, max_retries + 1):
            try:
                from adbutils import adb
                import uiautomator2 as u2
                
                # 直接连接设备
                adb_device = adb.device(serial)
                if adb_device is None:
                    raise RuntimeError(f"无法连接设备: {serial}")

                # 同时返回 u2 设备对象
                u2_device = u2.connect(serial)
                device_state.u2_device = u2_device
                device_state.adb_device = adb_device
                
                logger.info(f"已连接设备: {serial}")
                return True

            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"连接设备 {serial} 失败，重试 {attempt}/{max_retries}。错误: {str(e)}")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"设备连接失败: {serial}")
                    return False
        
        return False
    
    def _run_device_loop(self, device_state: DeviceState, game_manager: GameManager):
        """运行设备主循环"""
        device_state.logger.info("设备主循环开始")
        
        # 检测脚本启动时是否已经在对战中
        device_state.logger.info("检测当前游戏状态...")
        init_screenshot = device_state.take_screenshot()
        if init_screenshot is not None:
            # 转换为OpenCV格式
            init_screenshot_np = np.array(init_screenshot)
            init_screenshot_cv = cv2.cvtColor(init_screenshot_np, cv2.COLOR_RGB2BGR)
            gray_init_screenshot = cv2.cvtColor(init_screenshot_cv, cv2.COLOR_BGR2GRAY)

            # 加载模板
            templates = game_manager.template_manager.load_templates(device_state.config)

            # 检测是否已经在游戏中
            if game_manager.detect_existing_match(gray_init_screenshot, templates):
                # 设置本次运行的对战次数
                device_state.current_run_matches = 1
                device_state.in_match = True
                device_state.logger.debug(f"本次运行对战次数: {device_state.current_run_matches} (包含已开始的对战)")
            else:
                device_state.logger.debug("未检测到进行中的对战")
        else:
            device_state.logger.warning("无法获取初始截图，跳过状态检测")

        # 跳过按钮列表
        skip_buttons = ['enemy_round']

        # 主工作循环
        device_state.logger.debug("脚本初始化完成，开始运行...")

        while device_state.script_running:
            start_time = time.time()

            # 检查超时并重启游戏
            if device_state.check_timeout_and_restart():
                # 如果重启成功，继续循环；如果失败，等待一段时间后继续
                time.sleep(30)
                continue

            # 检查命令队列
            while not device_state.command_queue.empty():
                cmd = device_state.command_queue.get()
                self._handle_command(device_state, cmd)

            # 检查脚本暂停状态
            if device_state.script_paused:
                device_state.logger.debug("脚本暂停中...输入 'r' 继续")
                time.sleep(1)
                continue

            # 主要游戏逻辑
            self._process_game_logic(device_state, game_manager, skip_buttons)

            # 计算处理时间并调整等待
            process_time = time.time() - start_time
            sleep_time = max(0, 1 - process_time)
            time.sleep(sleep_time)
    
    def _process_game_logic(self, device_state: DeviceState, game_manager: GameManager, skip_buttons: List[str]):
        """处理游戏逻辑"""
        # 获取截图
        screenshot = device_state.take_screenshot()
        if screenshot is None:
            time.sleep(2)
            return

        # 转换为OpenCV格式
        screenshot_np = np.array(screenshot)
        screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)
        gray_screenshot = cv2.cvtColor(screenshot_cv, cv2.COLOR_BGR2GRAY)

        # 检查其他按钮
        button_detected = False
        templates = game_manager.template_manager.templates
        
        for key, template_info in templates.items():
            if not template_info:
                continue

            max_loc, max_val = game_manager.template_manager.match_template(gray_screenshot, template_info)
            if max_val >= template_info['threshold'] and max_loc is not None:
                # 更新活动时间（检测到任何按钮都算作活动）
                device_state.update_activity_time()
                
                if key in skip_buttons:
                    continue
                if key == 'LoginPage':
                    device_state.u2_device.click(659 + random.randint(-10, 10), 338 + random.randint(-10, 10))
                    continue

                if key == 'mainPage':
                    device_state.u2_device.click(987 + random.randint(-10, 10), 447 + random.randint(-10, 10))
                    continue

                if key == 'dailyCard':
                    device_state.u2_device.click(640 + random.randint(-2, 2), 646 + random.randint(-2, 2))
                    continue

                if key != device_state.last_detected_button:
                        if key == 'end_round' and device_state.in_match:
                            device_state.logger.debug(f"已发现'结束回合'按钮 (当前回合: {device_state.current_round_count})")

                # 处理对战开始/结束逻辑
                if key == 'war':
                    # 检测到"决斗"按钮，表示新对战开始
                    device_state.logger.debug(f"检测到决斗按钮 - 当前in_match: {device_state.in_match}")
                    # 计算中心点并点击
                    center_x = max_loc[0] + template_info['w'] // 2
                    center_y = max_loc[1] + template_info['h'] // 2
                    device_state.u2_device.click(center_x + random.randint(-2, 2), center_y + random.randint(-2, 2))
                    time.sleep(3)
                    device_state.logger.debug(f"调用start_new_match后 - in_match: {device_state.in_match}")
                    continue

                if key == 'decision':
                    device_state.start_new_match()
                    game_manager.game_actions._detect_change_card()
                    time.sleep(0.5)
                    center_x = max_loc[0] + template_info['w'] // 2
                    center_y = max_loc[1] + template_info['h'] // 2
                    device_state.u2_device.click(center_x + random.randint(-2, 2), center_y + random.randint(-2, 2))
                    break

                if key == 'end_round':
                    device_state.logger.debug(f"处理结束回合按钮 - in_match: {device_state.in_match}, 当前回合: {device_state.current_round_count}")
                    
                    # 根据是否有额外费用点决定进化/超进化执行回合
                    if device_state.extra_cost_available_this_match:
                        evolution_rounds = range(4, 25)  # 4到14，包含4和14
                    else:
                        evolution_rounds = range(5, 25) # 5到14，包含5和14
                    if device_state.current_round_count in evolution_rounds:
                        game_manager.game_actions.perform_fullPlus_actions()
                    else:
                        game_manager.game_actions.perform_full_actions()
                    if device_state.current_round_count == 15:
                        device_state.restart_emulator()
                   
                        
                    # 记录当前回合的费用使用情况（在回合结束时）
                    device_state.last_round_available_cost = device_state.current_round_count  # 当前回合的基础费用
                    # 如果有激活的额外费用点，加上额外费用（PP）
                    if device_state.extra_cost_active and device_state.extra_cost_remaining_uses > 0:
                        device_state.last_round_available_cost += 1
                    
                    # 记录实际使用的费用（从cost_history获取）
                    if hasattr(device_state, 'cost_history') and device_state.cost_history:
                        device_state.last_round_cost_used = device_state.cost_history[-1] if device_state.cost_history else 0
                    else:
                        device_state.last_round_cost_used = 0
                    
                    device_state.current_round_count += 1
                    device_state.has_clicked_plus_this_round = False
                    
                    # 自动点击结束回合按钮
                    center_x = max_loc[0] + template_info['w'] // 2
                    center_y = max_loc[1] + template_info['h'] // 2
                    device_state.u2_device.click(center_x + random.randint(-2, 2), center_y + random.randint(-2, 2))
                    device_state.logger.info("结束回合")
                    button_detected = True
                    if key != device_state.last_detected_button:
                        device_state.logger.debug(f"检测到按钮并处理: {template_info['name']} ")
                    device_state.last_detected_button = key
                    time.sleep(0.5)
                    break


                # 计算中心点并点击（除了结束回合按钮）
                center_x = max_loc[0] + template_info['w'] // 2
                center_y = max_loc[1] + template_info['h'] // 2
                device_state.u2_device.click(center_x + random.randint(-2, 2), center_y + random.randint(-2, 2))
                button_detected = True

                if key != device_state.last_detected_button:
                    device_state.logger.debug(f"检测到按钮并点击: {template_info['name']} ")

                # 更新状态跟踪
                device_state.last_detected_button = key
                time.sleep(0.5)
                break
    
    def _handle_command(self, device_state: DeviceState, cmd: str):
        """处理用户命令"""
        if not cmd:
            return
        
        logger = device_state.logger
        serial = device_state.serial
        
        if cmd == "p":
            device_state.script_paused = True
            logger.warning("用户请求暂停脚本")
            print(f">>> 脚本已暂停 (设备: {serial}) <<<")
        elif cmd == "r":
            device_state.script_paused = False
            logger.info("用户请求恢复脚本")
            print(f">>> 脚本已恢复 (设备: {serial}) <<<")
        elif cmd == "e":
            device_state.script_running = False
            logger.info("正在退出脚本...")
            print(f">>> 正在退出脚本... (设备: {serial}) <<<")
        elif cmd == "s":
            device_state.show_round_statistics()
            print(f">>> 已显示统计信息 (设备: {serial}) <<<")
        else:
            logger.warning(f"未知命令: '{cmd}'. 可用命令:'p'暂停, 'r'恢复, 'e'退出 或 's'统计")
            print(f">>> 未知命令: '{cmd}' (设备: {serial}) <<<")
    
    def _cleanup_device(self, device_state: DeviceState):
        """清理设备资源"""
        # 结束当前对战（如果正在进行）
        if device_state.in_match:
            device_state.end_current_match()
        
        # 保存统计数据
        device_state.save_round_statistics()
        
        # 显示运行总结
        summary = device_state.get_run_summary()
        device_state.logger.info("\n===== 本次运行总结 =====")
        device_state.logger.info(f"脚本启动时间: {summary['start_time']}")
        device_state.logger.info(f"运行时长: {summary['duration']}")
        device_state.logger.info(f"完成对战次数: {summary['matches_completed']}")
        device_state.logger.info("===== 脚本结束运行 =====")
    
    def wait_for_completion(self):
        """等待所有设备完成"""
        for serial, thread in self.device_threads.items():
            thread.join()
            logger.info(f"设备线程已结束: {serial}")
    
    def show_run_summary(self):
        """显示运行总结"""
        logger.info("=== 所有设备运行完成 ===")
        for serial, device_state in self.device_states.items():
            summary = device_state.get_run_summary()
            logger.info(f"设备 {serial}: {summary['matches_completed']} 场对战") 