"""
设备管理器
管理所有设备的连接和运行
"""

import threading
import logging
import time
import re

import cv2
import numpy as np
from typing import Dict, Any
from src.core.run_control import PauseRequested, StopRequested
from src.device.device_state import DeviceState
from src.game.game_manager import GameManager
from src.game.state_machine import GameStateMachine

logger = logging.getLogger(__name__)


class DeviceManager:
    """设备管理器类"""

    def __init__(self, config_manager, notification_manager, log_queue=None):
        self.config_manager = config_manager
        self.notification_manager = notification_manager
        self.log_queue = log_queue
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
            device_state = DeviceState(
                serial, self.config_manager.config, device_config, log_queue=self.log_queue
            )
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
        max_reconnect_attempts = 10
        reconnect_delay = 15
        reconnect_count = 0

        logger.info(f"设备 {serial} 工作线程开始")

        while device_state.script_running:
            try:
                # 连接设备（或重新连接）
                if reconnect_count > 0:
                    logger.info(
                        f"设备 {serial} 尝试重新连接，第 {reconnect_count}/{max_reconnect_attempts} 次"
                    )

                if not self._connect_device(device_config, device_state):
                    error_msg = f"无法连接设备: {serial}"
                    logger.error(error_msg)
                    reconnect_count += 1
                    if reconnect_count >= max_reconnect_attempts:
                        self.notification_manager.show_error(
                            f"设备连接失败: {serial}",
                            f"已尝试 {max_reconnect_attempts} 次，均失败",
                        )
                        return
                    logger.info(f"等待 {reconnect_delay} 秒后重试...")
                    time.sleep(reconnect_delay)
                    continue

                # 重置重连计数器
                reconnect_count = 0

                # 初始化游戏管理器（首次连接或重连后）
                if device_state.game_manager is None:
                    game_manager = GameManager(device_state)
                    game_manager.state_machine = GameStateMachine()
                    device_state.game_manager = game_manager
                else:
                    game_manager = device_state.game_manager

                # 运行设备主循环
                self._run_device_loop(device_state, game_manager)

                # 如果正常退出主循环，结束线程
                break

            except KeyboardInterrupt:
                device_state.logger.info("用户中断脚本执行")
                break
            except Exception as e:
                reconnect_count += 1
                logger.warning(
                    f"设备 {serial} 工作线程异常，尝试重连 ({reconnect_count}/{max_reconnect_attempts}): {str(e)}"
                )

                if reconnect_count >= max_reconnect_attempts:
                    logger.error(
                        f"设备 {serial} 重连 {max_reconnect_attempts} 次失败，停止尝试"
                    )
                    self.notification_manager.show_error(
                        f"设备连接失败: {serial}",
                        f"重连 {max_reconnect_attempts} 次均失败",
                    )
                    break

                # 重置设备状态以便重新连接
                device_state.adb_device = None
                device_state.u2_device = None
                device_state.game_manager = None

                logger.info(f"等待 {reconnect_delay} 秒后重试...")
                time.sleep(reconnect_delay)
                continue
            finally:
                # 只有在完全退出时才清理资源
                if (
                    not device_state.script_running
                    or reconnect_count >= max_reconnect_attempts
                ):
                    self._cleanup_device(device_state)

        logger.info(f"设备 {serial} 工作线程结束")

    def _connect_device(self, device_config: Dict[str, Any], device_state: DeviceState) -> bool:
        """连接设备"""
        serial = device_config["serial"]
        max_retries = 5
        retry_delay = 10

        def _is_tcp_serial(value: str) -> bool:
            return bool(re.match(r"^[^:\s]+:\d+$", str(value or "").strip()))

        for attempt in range(1, max_retries + 1):
            try:
                from adbutils import adb
                import uiautomator2 as u2

                if _is_tcp_serial(serial):
                    try:
                        msg = adb.connect(serial, timeout=5)
                        if msg:
                            logger.info(f"adb connect {serial}: {msg}")
                    except Exception as e:
                        logger.warning(f"adb connect {serial} 失败: {e}")

                # 直接连接设备
                adb_device = adb.device(serial)
                if adb_device is None:
                    raise RuntimeError(f"无法连接设备: {serial}")

                # 同时返回 u2 设备对象
                u2_device = u2.connect(serial)
                device_state.u2_device = device_state.wrap_u2_device(u2_device)
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

        # 启动脚本时若游戏未运行，自动拉起 Shadowverse 应用。
        try:
            device_state.ensure_shadowverse_apps_running(launch_delay_seconds=3.0)
        except Exception as e:
            device_state.logger.warning(f"自动启动游戏应用失败，继续执行: {e}")

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
                # 检测到已开始的对战，设置为第1场
                device_state.current_run_matches = 0
                device_state.in_match = True
                device_state.logger.debug("检测到已开始的对战，将作为第1场计算")
            else:
                device_state.logger.debug("未检测到进行中的对战")
        else:
            device_state.logger.warning("无法获取初始截图，跳过状态检测")

        # 跳过按钮列表
        skip_buttons = ['enemy_round']

        # 主工作循环
        device_state.logger.debug("脚本初始化完成，开始运行...")

        run_settings = device_state.config.get("run_settings", {})
        try:
            max_run_duration = int(run_settings.get("max_run_duration", 0) or 0)
        except Exception:
            max_run_duration = 0
        max_run_duration = max(0, max_run_duration)

        script_start_time = time.time()
        runtime_limit_pending = False
        runtime_wait_log_shown = False

        while device_state.script_running:
            start_time = time.time()

            # If we just resumed, apply "new turn" semantics.
            try:
                device_state.apply_resume_policy_if_needed()
            except Exception:
                pass

            # 检查脚本总时长上限（到时后仅在当前对战结束后停止）。
            if max_run_duration > 0 and not runtime_limit_pending:
                if (time.time() - script_start_time) >= max_run_duration:
                    runtime_limit_pending = True
                    device_state.stop_after_current_match = True
                    device_state.logger.warning(
                        f"达到脚本总时长上限({max_run_duration}秒)，将在当前对战结束后停止"
                    )

            if runtime_limit_pending and not device_state.in_match:
                device_state.logger.info("当前不在对战中，按总时长限制停止脚本")
                device_state.request_stop(reason="runtime_limit")
                break
            if runtime_limit_pending and device_state.in_match and not runtime_wait_log_shown:
                runtime_wait_log_shown = True
                device_state.logger.info("总时长已到，等待当前对战结束后停止")

            # 检查命令队列
            while not device_state.command_queue.empty():
                cmd = device_state.command_queue.get()
                self._handle_command(device_state, cmd)

            # 检查脚本暂停状态
            if device_state.is_paused():
                device_state.logger.debug("脚本暂停中...输入 'r' 继续")
                device_state.wait_while_paused()
                continue

            # 检查超时并自动重启（暂停状态下不会触发）。
            if device_state.check_timeout_and_restart():
                if not device_state.script_running:
                    break
                try:
                    device_state.sleep(6)
                except StopRequested:
                    device_state.script_running = False
                    break
                except PauseRequested:
                    device_state.wait_while_paused()
                continue

            # 主要游戏逻辑
            try:
                game_manager.state_machine.process(
                    device_state, game_manager, skip_buttons
                )
            except StopRequested:
                device_state.script_running = False
                break
            except PauseRequested:
                device_state.wait_while_paused()
                continue

            # 计算处理时间并调整等待
            process_time = time.time() - start_time
            sleep_time = max(0, 1 - process_time)
            try:
                device_state.sleep(sleep_time)
            except StopRequested:
                device_state.script_running = False
                break
            except PauseRequested:
                device_state.wait_while_paused()
                continue

    def _handle_command(self, device_state: DeviceState, cmd: str):
        """处理用户命令"""
        if not cmd:
            return

        logger = device_state.logger
        serial = device_state.serial

        if cmd == "p":
            device_state.request_pause(reason="device_queue")
            logger.warning("用户请求暂停脚本")
            print(f">>> 脚本已暂停 (设备: {serial}) <<<")
        elif cmd == "r":
            device_state.request_resume(reason="device_queue")
            logger.info("用户请求恢复脚本")
            print(f">>> 脚本已恢复 (设备: {serial}) <<<")
        elif cmd == "e":
            device_state.request_stop(reason="user_exit")
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

    def wait_for_completion(self, *, poll_interval: float = 0.2, stop_grace_seconds: float = 8.0):
        """等待所有设备完成。

        正常运行时持续阻塞直到线程结束；
        若已收到停止请求但个别线程长时间未退出，则在宽限期后结束等待，
        避免 GUI 无法停止。
        """

        pending = dict(self.device_threads)
        stop_wait_start = None

        while pending:
            for serial, thread in list(pending.items()):
                thread.join(timeout=max(0.05, float(poll_interval)))
                if not thread.is_alive():
                    logger.info(f"设备线程已结束: {serial}")
                    pending.pop(serial, None)

            if not pending:
                break

            all_stop_requested = bool(self.device_states) and all(
                not bool(getattr(ds, "script_running", True))
                for ds in self.device_states.values()
            )

            if all_stop_requested:
                if stop_wait_start is None:
                    stop_wait_start = time.time()
                elif (time.time() - stop_wait_start) >= max(0.5, float(stop_grace_seconds)):
                    remain = ", ".join(sorted(pending.keys()))
                    logger.warning(
                        "停止请求后设备线程仍未退出，跳过继续等待: %s",
                        remain,
                    )
                    break
            else:
                stop_wait_start = None

    def show_run_summary(self):
        """显示运行总结"""
        logger.info("=== 所有设备运行完成 ===")
        for serial, device_state in self.device_states.items():
            summary = device_state.get_run_summary()
            logger.info(f"设备 {serial}: {summary['matches_completed']} 场对战")
