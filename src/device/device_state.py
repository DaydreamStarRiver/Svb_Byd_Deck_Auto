"""
设备状态管理
管理每个设备的状态信息
"""

import json
import os
import time
import datetime
import logging
import queue
import subprocess
import psutil
from collections import defaultdict
from typing import Any, Optional, List, Dict, TYPE_CHECKING
from src.utils.resource_utils import ensure_directory

if TYPE_CHECKING:
    from src.game.game_manager import GameManager


class DeviceState:
    """管理每个设备的状态"""
    
    def __init__(self, serial: str, config: Dict[str, Any], device_config: Optional[Dict[str, Any]] = None):
        self.serial = serial
        self.config = config
        self.device_config = device_config or {}
        
        # 脚本运行状态
        self.script_running = True
        self.script_paused = False
        
        # 设置日志器（必须在其他初始化之前）
        self.logger = self._setup_logger()
        
        # 初始化截图方法选择
        self._init_screenshot_method()
        
        # 对战状态
        self.current_round_count = 1
        self.evolution_point = 2
        self.super_evolution_point = 2
        self.match_start_time: Optional[float] = None
        self.match_history: List[Dict[str, Any]] = []
        self.current_run_matches = 0
        self.current_run_start_time = datetime.datetime.now()
        self.in_match = False
        
        # 命令和通知
        self.command_queue = queue.Queue()
        self.last_detected_button: Optional[str] = None
        self.has_clicked_plus_this_round = False
        
        # 额外费用点状态管理
        self.extra_cost_used_early = False  # 1-5回合是否已使用额外费用点
        self.extra_cost_used_late = False   # 6回合后是否已使用额外费用点
        self.extra_cost_available_this_match: Optional[bool] = None  # 本局是否有额外费用点
        self.extra_cost_active = False  # 当前是否有激活的额外费用点
        self.extra_cost_remaining_uses = 0  # 当前激活的额外费用点剩余使用次数
        self.last_round_cost_used = 0  # 上一回合使用的费用数量
        self.last_round_available_cost = 0  # 上一回合的可用费用数量
        
        # 费用历史
        self.cost_history: List[int] = []
        
        # 超时检测相关属性
        self.last_activity_time = time.time()  # 最后一次活动时间
        self.last_match_time = time.time()     # 最后一次战斗时间
        
        # 从配置中读取超时设置
        auto_restart_config = config.get("auto_restart", {})
        self.auto_restart_enabled = auto_restart_config.get("enabled", True)
        self.output_timeout = auto_restart_config.get("output_timeout", 300)
        self.match_timeout = auto_restart_config.get("match_timeout", 900)
        
        # 设备对象
        self.u2_device: Optional[Any] = None
        self.adb_device: Optional[Any] = None
        
        # 游戏管理器
        self.game_manager: Optional['GameManager'] = None
        
        # 随从管理器 - 将在GameManager初始化时设置
        self.follower_manager: Optional[Any] = None
        
        # 加载历史统计数据
        self.load_round_statistics()
    
    def _init_screenshot_method(self):
        """初始化截图方法选择，只在程序启动时执行一次"""
        try:
            # 从设备配置中获取screenshot_deep_color值，默认为False
            screenshot_deep_color = self.device_config.get('screenshot_deep_color', False)
            
            if screenshot_deep_color:
                self.logger.info("初始化截图方法: 使用深色截图方法")
                self._screenshot_method = self.take_screenshot_MuMugblobe
            else:
                self.logger.info("初始化截图方法: 使用普通截图方法")
                self._screenshot_method = self.take_screenshot_normal
                
        except Exception as e:
            self.logger.error(f"读取设备配置失败，使用默认截图方法: {str(e)}")
            self._screenshot_method = self.take_screenshot_normal
    
    def _setup_logger(self) -> logging.Logger:
        """为每个设备创建独立的日志器"""
        logger = logging.getLogger(f"Device-{self.serial}")
        logger.setLevel(logging.INFO)

        # 避免重复添加处理器
        if logger.handlers:
            return logger

        # 创建文件日志处理器
        log_file = f"script_log_{self.serial.replace(':', '_')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)

        # 添加文件处理器
        logger.addHandler(file_handler)
        
        # 添加控制台处理器，让设备日志也能显示在终端
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # 设置不向上传递，避免重复输出
        logger.propagate = False

        return logger

    def take_screenshot(self) -> Optional[Any]:
        """
        执行截图，使用初始化时选择的截图方法
        """
        return self._screenshot_method()

    def take_screenshot_normal(self) -> Optional[Any]:
        """获取设备截图"""
        if self.adb_device is None:
            return None
        return self.adb_device.screenshot()

    def take_screenshot_MuMugblobe(self) -> Optional[Any]:
        """获取设备截图"""
        if self.adb_device is None:
            return None

        try:
            screenshot = self.adb_device.screenshot()
            if screenshot is not None:
                # 转换为numpy数组进行亮度调整
                import numpy as np
                import cv2
                
                # 将PIL图像转换为numpy数组
                img_array = np.array(screenshot)
                
                # 转换为BGR格式（OpenCV默认格式）
                if len(img_array.shape) == 3:
                    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                else:
                    img_bgr = img_array
                
                # 提高亮度43
                brightness = 43
                img_brightened = cv2.add(img_bgr, brightness)
                
                # 转换回RGB格式
                img_rgb = cv2.cvtColor(img_brightened, cv2.COLOR_BGR2RGB)
                
                # 转换回PIL图像
                from PIL import Image
                return Image.fromarray(img_rgb)
            else:
                return None
        except Exception as e:
            self.logger.error(f"截图失败: {str(e)}")
            return None

    def save_screenshot(self, screenshot, scene="general") -> Optional[str]:
        """保存截图并添加场景标签"""
        if screenshot is None:
            return None

        # 创建输出目录（如果不存在）
        output_dir = f"screenshots_{self.serial.replace(':', '_')}"
        ensure_directory(output_dir)

        # 生成时间戳文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{scene}_{timestamp}.png"
        filepath = os.path.join(output_dir, filename)

        # 保存为PNG
        screenshot.save(filepath)
        self.logger.info(f"截图保存 [{scene}]: {filepath}")
        return filepath

    def end_current_match(self):
        """结束当前对战并记录统计数据"""
        if self.match_start_time is None:
            return

        match_duration = time.time() - self.match_start_time
        minutes, seconds = divmod(match_duration, 60)

        match_record = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rounds": self.current_round_count,
            "duration": f"{int(minutes)}分{int(seconds)}秒",
            "run_id": self.current_run_start_time.strftime("%Y%m%d%H%M%S")
        }

        self.match_history.append(match_record)

        # 保存统计数据到文件
        self.save_round_statistics()

        self.logger.info(f"===== 对战结束 =====")
        self.logger.info(f"回合数: {self.current_round_count}, 持续时间: {int(minutes)}分{int(seconds)}秒")

        # 重置对战状态
        self.match_start_time = None
        self.current_round_count = 1
        self.evolution_point = 2
        self.super_evolution_point = 2

    def save_round_statistics(self):
        """保存回合统计数据到文件"""
        stats_file = f"round_stats_{self.serial.replace(':', '_')}.json"
        try:
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.match_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存统计数据失败: {str(e)}")

    def load_round_statistics(self):
        """从文件加载回合统计数据"""
        stats_file = f"round_stats_{self.serial.replace(':', '_')}.json"
        if not os.path.exists(stats_file):
            return

        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                self.match_history = json.load(f)
        except Exception as e:
            self.logger.error(f"加载统计数据失败: {str(e)}")

    def show_round_statistics(self):
        """显示回合统计数据"""
        if not self.match_history:
            self.logger.info("暂无对战统计数据")
            return

        # 计算总数据
        total_matches = len(self.match_history)
        total_rounds = sum(match['rounds'] for match in self.match_history)
        avg_rounds = total_rounds / total_matches if total_matches > 0 else 0

        # 计算本次运行数据
        current_run_matches = 0
        current_run_rounds = 0
        for match in self.match_history:
            if match.get('run_id') == self.current_run_start_time.strftime("%Y%m%d%H%M%S"):
                current_run_matches += 1
                current_run_rounds += match['rounds']

        current_run_avg = current_run_rounds / current_run_matches if current_run_matches > 0 else 0

        # 按回合数分组统计
        from collections import defaultdict
        round_distribution = defaultdict(int)
        for match in self.match_history:
            round_distribution[match['rounds']] += 1

        # 显示统计数据
        self.logger.info(f"\n===== 对战回合统计 =====")
        self.logger.info(f"总对战次数: {total_matches}")
        self.logger.info(f"总回合数: {total_rounds}")
        self.logger.info(f"平均每局回合数: {avg_rounds:.1f}")

        # 显示本次运行统计
        self.logger.info(f"\n===== 本次运行统计 =====")
        self.logger.info(f"对战次数: {current_run_matches}")
        self.logger.info(f"总回合数: {current_run_rounds}")
        self.logger.info(f"平均每局回合数: {current_run_avg:.1f}")

        self.logger.info("\n回合数分布:")
        for rounds in sorted(round_distribution.keys()):
            count = round_distribution[rounds]
            percentage = (count / total_matches) * 100
            self.logger.info(f"{rounds}回合: {count}次 ({percentage:.1f}%)")

        # 显示最近5场对战
        self.logger.info("\n最近5场对战:")
        for match in self.match_history[-5:]:
            run_marker = "(本次运行)" if match.get('run_id') == self.current_run_start_time.strftime(
                "%Y%m%d%H%M%S") else ""
            self.logger.info(f"{match['date']} - {match['rounds']}回合 ({match['duration']}) {run_marker}")

    def update_activity_time(self):
        """更新最后活动时间"""
        self.last_activity_time = time.time()

    def update_match_time(self):
        """更新最后战斗时间"""
        self.last_match_time = time.time()

    def check_timeout_and_restart(self) -> bool:
        """检查超时并重启模拟器"""
        # 如果自动重启功能未启用，直接返回
        if not self.auto_restart_enabled:
            return False
            
        current_time = time.time()
        
        # 检查5分钟无输出超时
        output_timeout_elapsed = current_time - self.last_activity_time
        if output_timeout_elapsed >= self.output_timeout:
            self.logger.warning(f"检测到{self.output_timeout//60}分钟无输出，准备重启模拟器")
            return self.restart_emulator()
        
        # 检查10分钟无新战斗超时
        match_timeout_elapsed = current_time - self.last_match_time
        if match_timeout_elapsed >= self.match_timeout:
            self.logger.warning(f"检测到{self.match_timeout//60}分钟无新战斗，准备重启模拟器")
            return self.restart_emulator()
        
        return False

    def restart_emulator(self) -> bool:
        """重启所有包名包含 'Shadowverse' 或 'com.netease.yzs' 的应用，不重启模拟器"""
        try:
            self.logger.info("开始重启所有包含 'Shadowverse' 或 'com.netease.yzs' 的应用...")
            if self.adb_device is None:
                self.logger.error("adb_device 未连接，无法重启应用")
                return False
            # 获取所有包名
            packages = self.adb_device.shell("pm list packages").splitlines()
            target_pkgs = [p.split(":")[-1] for p in packages if ("Shadowverse" in p or "shadowverse" in p or "com.netease.yzs" in p)]
            if not target_pkgs:
                self.logger.warning("未找到包含 'Shadowverse' 或 'com.netease.yzs' 的包名")
                return False
            # 先全部强制停止
            for pkg in target_pkgs:
                try:
                    self.logger.info(f"停止应用: {pkg}")
                    if self.u2_device:
                        self.u2_device.app_stop(pkg)
                    else:
                        self.adb_device.shell(f"am force-stop {pkg}")
                except Exception as e:
                    self.logger.warning(f"停止应用 {pkg} 失败: {e}")
            time.sleep(2)
            # 再全部启动
            for pkg in target_pkgs:
                try:
                    self.logger.info(f"启动应用: {pkg}")
                    if self.u2_device:
                        self.u2_device.app_start(pkg)
                    else:
                        self.adb_device.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
                except Exception as e:
                    self.logger.warning(f"启动应用 {pkg} 失败: {e}")
            self.logger.info(f"已重启所有包含 'Shadowverse' 或 'com.netease.yzs' 的应用: {target_pkgs}")
            # 重置超时计时器
            self.update_activity_time()
            self.update_match_time()
            return True
        except Exception as e:
            self.logger.error(f"重启应用过程中出错: {e}")
            return False

    def reset_match_state(self):
        """重置对战状态"""
        self.in_match = False
        self.match_start_time = None
        self.current_round_count = 1
        self.evolution_point = 2
        self.super_evolution_point = 2
        self.extra_cost_used_early = False
        self.extra_cost_used_late = False
        self.extra_cost_available_this_match = None
        self.extra_cost_active = False
        self.extra_cost_remaining_uses = 0
        self.last_round_cost_used = 0
        self.last_round_available_cost = 0
        self.cost_history.clear()
    
    def start_new_match(self):
        """开始新对战"""
        if self.in_match:
            self.end_current_match()
        
        self.current_run_matches += 1
        self.match_start_time = time.time()
        self.current_round_count = 1
        self.evolution_point = 2
        self.super_evolution_point = 2
        
        # 重置额外费用点状态，但不重置in_match
        self.extra_cost_used_early = False
        self.extra_cost_used_late = False
        self.extra_cost_available_this_match = None
        self.extra_cost_active = False
        self.extra_cost_remaining_uses = 0
        self.last_round_cost_used = 0
        self.last_round_available_cost = 0
        self.cost_history.clear()
        
        self.update_match_time()
        self.logger.debug("检测到新对战开始")
    
    def get_run_summary(self) -> Dict[str, Any]:
        """获取本次运行总结"""
        run_duration = datetime.datetime.now() - self.current_run_start_time
        hours, remainder = divmod(run_duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        return {
            "start_time": self.current_run_start_time.strftime('%Y-%m-%d %H:%M:%S'),
            "duration": f"{int(hours)}小时{int(minutes)}分钟{int(seconds)}秒",
            "matches_completed": self.current_run_matches,
            "serial": self.serial
        } 