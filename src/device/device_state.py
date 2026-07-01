"""
设备状态管理
管理每个设备的状态信息
"""

import json
import os
import time
import datetime
import logging
import threading
import queue
import random
import numpy as np
import cv2
from typing import Any, Optional, List, Dict, Protocol, TYPE_CHECKING
from PIL import Image
from src.utils.resource_utils import ensure_directory
from src.core.logging_utils import QueueHandler
from src.core.json_io import write_json_atomic
from src.core.run_control import PauseRequested, StopRequested

if TYPE_CHECKING:
    from src.game.game_manager import GameManager


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


class U2DeviceLike(Protocol):
    """Minimal uiautomator2 device protocol used in this project."""

    def click(self, *args: Any, **kwargs: Any) -> Any: ...

    def swipe(self, *args: Any, **kwargs: Any) -> Any: ...

    def app_start(self, *args: Any, **kwargs: Any) -> Any: ...

    def app_stop(self, *args: Any, **kwargs: Any) -> Any: ...

    def app_current(self, *args: Any, **kwargs: Any) -> Any: ...


class _U2DeviceProxy:
    """Proxy for uiautomator2 Device with pause gating."""

    def __init__(self, device_state: "DeviceState", raw_device: U2DeviceLike):
        self._device_state = device_state
        self._raw = raw_device

        # Only gate operations that can affect user manual control.
        # Read-only queries (e.g. screenshot, dump_hierarchy) are allowed.
        self._gated_methods = {
            "click",
            "swipe",
            "drag",
            "long_click",
            "double_click",
            "press",
            "keyevent",
            "send_keys",
            "set_text",
            "clear_text",
            # App lifecycle operations definitely affect user control.
            "app_start",
            "app_stop",
            "app_stop_all",
            "app_clear",
            # Shell can change app/UI state (force-stop, input, etc.).
            "shell",
        }

    def click(self, *args, **kwargs):
        self._device_state.check_interrupt()
        return self._raw.click(*args, **kwargs)

    def swipe(self, *args, **kwargs):
        self._device_state.check_interrupt()
        return self._raw.swipe(*args, **kwargs)

    def app_start(self, *args, **kwargs):
        self._device_state.check_interrupt()
        return self._raw.app_start(*args, **kwargs)

    def app_stop(self, *args, **kwargs):
        self._device_state.check_interrupt()
        return self._raw.app_stop(*args, **kwargs)

    def app_current(self, *args, **kwargs):
        return self._raw.app_current(*args, **kwargs)

    def __getattr__(self, item: str):
        attr = getattr(self._raw, item)
        if item in self._gated_methods and callable(attr):
            def _wrapped(*args, **kwargs):
                self._device_state.check_interrupt()
                return attr(*args, **kwargs)

            return _wrapped
        return attr


class DeviceState:
    """管理每个设备的状态"""

    def __init__(
        self,
        serial: str,
        config: Dict[str, Any],
        device_config: Optional[Dict[str, Any]] = None,
        log_queue: Optional[queue.Queue[Any]] = None,
    ):
        self.serial = serial
        self.config = config
        self.device_config = device_config or {}
        self.log_queue = log_queue

        # 脚本运行状态
        self.script_running = True
        self.script_paused = False

        # Immediate pause control (settable from other threads)
        self.pause_event = threading.Event()
        self._resume_advance_round_pending = False

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
        self.current_stage_key: Optional[str] = None
        self.last_stage_change_time = time.time()
        self.has_clicked_plus_this_round = False
        self.stop_after_current_match = False
        self.mulligan_done_this_match = False

        # 额外费用点状态管理
        self.extra_cost_used_early = False  # 1-5回合是否已使用额外费用点
        self.extra_cost_used_late = False  # 6回合后是否已使用额外费用点
        self.extra_cost_available_this_match: Optional[bool] = (
            None  # 本局是否有额外费用点
        )
        self.extra_cost_active = False  # 当前是否有激活的额外费用点
        self.extra_cost_remaining_uses = 0  # 当前激活的额外费用点剩余使用次数
        self.last_round_cost_used = 0  # 上一回合使用的费用数量
        self.last_round_available_cost = 0  # 上一回合的可用费用数量

        # 费用历史
        self.cost_history: List[int] = []

        # 超时检测相关属性
        self.last_activity_time = time.time()  # 最后一次活动时间

        # 从配置中读取超时设置
        auto_restart_config = config.get("auto_restart", {})
        self.auto_restart_enabled = auto_restart_config.get("enabled", True)
        stage_timeout_raw = auto_restart_config.get("stage_timeout", 300)
        self.stage_timeout = max(30, _safe_int(stage_timeout_raw, 300))
        self.auto_restart_max_restarts = max(
            1,
            _safe_int(auto_restart_config.get("max_restarts", 3), 3),
        )
        self.auto_restart_trigger_count = 0
        self.stop_reason = ""

        # 设备对象
        # Kept as `Any` (not Optional) to avoid pervasive None-check noise.
        self.u2_device: Optional[U2DeviceLike] = None
        self.u2_device_raw: Optional[U2DeviceLike] = None
        self.adb_device: Any = None

        # 游戏管理器
        self.game_manager: Optional["GameManager"] = None

        # 随从管理器 - 将在GameManager初始化时设置
        self.follower_manager: Optional[Any] = None

        # 加载历史统计数据
        self.load_round_statistics()

    def _init_screenshot_method(self):
        """初始化截图方法选择，只在程序启动时执行一次"""
        try:
            # 从设备配置中获取screenshot_deep_color值，默认为False
            screenshot_deep_color = self.device_config.get(
                "screenshot_deep_color", False
            )

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

        # 创建文件日志处理器（按设备区分；同一设备复用同一个日志文件）
        log_file = f"script_log_{self.serial.replace(':', '_')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(file_formatter)

        # 添加文件处理器
        logger.addHandler(file_handler)

        # 添加控制台处理器，让设备日志也能显示在终端
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # 添加队列处理器，让设备日志也能显示在UI界面
        if self.log_queue is not None:
            queue_handler = QueueHandler(self.log_queue)
            queue_handler.setFormatter(console_formatter)
            logger.addHandler(queue_handler)

        # 设置不向上传递，避免重复输出
        logger.propagate = False

        return logger

    def take_screenshot(self) -> Optional[Any]:
        """
        执行截图，使用初始化时选择的截图方法
        """
        return self._screenshot_method()

    # ===== Run control: cooperative pause/stop =====

    def is_paused(self) -> bool:
        return bool(self.script_paused or self.pause_event.is_set())

    def request_pause(self, *, reason: str = "") -> None:
        """Request an immediate pause (thread-safe)."""

        already = self.is_paused()
        self.script_paused = True
        self.pause_event.set()

        # Resume policy: treat the current turn as ended.
        if getattr(self, "in_match", False):
            self._resume_advance_round_pending = True

        if not already:
            try:
                self.logger.warning(
                    f"[控制] 收到暂停请求{(' - ' + reason) if reason else ''}"
                )
            except Exception:
                pass

    def request_resume(self, *, reason: str = "") -> None:
        """Resume from pause (thread-safe)."""

        was_paused = self.is_paused()
        self.script_paused = False
        self.pause_event.clear()
        if was_paused:
            now = time.time()
            self.last_stage_change_time = now
            self.update_activity_time()
            try:
                self.logger.info(
                    f"[控制] 收到恢复请求{(' - ' + reason) if reason else ''}"
                )
            except Exception:
                pass

    def record_stage_detection(self, stage_key: Any) -> None:
        """Record detected UI stage; timeout only advances on stage changes."""

        key = str(stage_key or "")
        if not key:
            return

        now = time.time()
        self.update_activity_time()

        if key != self.current_stage_key:
            self.current_stage_key = key
            self.last_stage_change_time = now

    def click_blank_before_restart(self) -> bool:
        """Try a single blank click before auto-restart."""

        try:
            from src.config.game_constants import BLANK_CLICK_POSITION, BLANK_CLICK_RANDOM
        except Exception:
            return False

        if self.u2_device is None:
            return False

        try:
            self.logger.info("[自动重启] 重启前尝试点击空白区域")
            self.u2_device.click(
                int(BLANK_CLICK_POSITION[0])
                + random.randint(-int(BLANK_CLICK_RANDOM), int(BLANK_CLICK_RANDOM)),
                int(BLANK_CLICK_POSITION[1])
                + random.randint(-int(BLANK_CLICK_RANDOM), int(BLANK_CLICK_RANDOM)),
            )
            self.sleep(0.6)
            return True
        except PauseRequested:
            return False
        except StopRequested:
            return False
        except Exception as e:
            self.logger.debug(f"[自动重启] 空白点击尝试失败: {e}")
            return False

    def request_stop(self, *, reason: str = "manual") -> None:
        """Request script stop without forcing app shutdown by default."""

        self.stop_reason = str(reason or "manual")

        # Runtime-limit stop should also close game app(s) on device.
        if self.stop_reason == "runtime_limit":
            try:
                self.stop_shadowverse_apps(trigger=self.stop_reason)
            except Exception:
                pass

        self.script_running = False

        # Ensure paused loops can unwind quickly.
        self.script_paused = False
        self.pause_event.clear()

        try:
            self.logger.info(
                f"[控制] 收到停止请求{(' - ' + self.stop_reason) if self.stop_reason else ''}"
            )
        except Exception:
            pass

    def _find_shadowverse_packages(self) -> List[str]:
        """Find installed package names related to Shadowverse/Byd."""

        if self.adb_device is None:
            return []

        try:
            packages = self.adb_device.shell("pm list packages").splitlines()
        except Exception:
            return []

        out: List[str] = []
        seen = set()
        for item in packages:
            pkg = str(item or "").split(":")[-1].strip()
            if not pkg:
                continue
            low = pkg.lower()
            if "shadowverse" not in low and "com.netease.yzs" not in low:
                continue
            if pkg in seen:
                continue
            seen.add(pkg)
            out.append(pkg)
        return out

    def _is_package_running(self, pkg: str) -> bool:
        if self.adb_device is None or not pkg:
            return False

        try:
            result = str(self.adb_device.shell(f"pidof {pkg}") or "").strip()
        except Exception:
            return False

        if not result:
            return False
        low = result.lower()
        if "not found" in low or "unknown" in low or "error" in low:
            return False

        tokens = [t.strip() for t in result.replace("\n", " ").split(" ") if t.strip()]
        if not tokens:
            return False
        return all(tok.isdigit() for tok in tokens)

    def _get_foreground_package(self) -> str:
        """Get current foreground package name (best effort)."""

        for dev in (self.u2_device_raw, self.u2_device):
            if dev is None:
                continue
            try:
                current = dev.app_current()
                if isinstance(current, dict):
                    pkg = str(current.get("package") or "").strip()
                    if pkg:
                        return pkg
            except Exception:
                pass

        if self.adb_device is None:
            return ""

        try:
            top = str(self.adb_device.shell("dumpsys activity top") or "")
        except Exception:
            return ""

        import re

        for line in top.splitlines():
            if "ACTIVITY" not in line and "topResumedActivity" not in line:
                continue
            m = re.search(r"\b([A-Za-z0-9_\.]+)/[A-Za-z0-9_.$]+", line)
            if m:
                return str(m.group(1) or "").strip()

        return ""

    def ensure_shadowverse_apps_running(self, *, launch_delay_seconds: float = 3.0) -> bool:
        """Ensure Shadowverse app is running; auto-start when not running."""

        target_pkgs = self._find_shadowverse_packages()
        if not target_pkgs:
            self.logger.warning("未找到Shadowverse相关包名，无法自动启动应用")
            return False

        foreground_pkg = self._get_foreground_package()
        if foreground_pkg in target_pkgs:
            self.logger.info(f"检测到Shadowverse应用已在前台: {foreground_pkg}")
            return True

        running_pkgs = [pkg for pkg in target_pkgs if self._is_package_running(pkg)]
        if running_pkgs:
            self.logger.info(
                f"检测到Shadowverse应用进程在后台，尝试拉起前台: {running_pkgs}"
            )
        else:
            self.logger.info(f"未检测到运行中的Shadowverse应用，尝试自动启动: {target_pkgs}")

        preferred = sorted(
            running_pkgs or target_pkgs,
            key=lambda p: (
                0 if "worldsbeyond" in p.lower() else 1,
                0 if "beyond" in p.lower() else 1,
                p,
            ),
        )

        started = False
        for pkg in preferred:
            try:
                if self.adb_device is not None:
                    self.adb_device.shell(
                        f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1"
                    )
                elif self.u2_device_raw is not None:
                    self.u2_device_raw.app_start(pkg)
                elif self.u2_device is not None:
                    self.u2_device.app_start(pkg)
                self.logger.info(f"已发送应用启动命令: {pkg}")
                started = True
                break
            except Exception as e:
                self.logger.warning(f"启动应用 {pkg} 失败: {e}")

        if started and launch_delay_seconds > 0:
            try:
                self.sleep(float(launch_delay_seconds))
            except Exception:
                time.sleep(float(launch_delay_seconds))

        if started:
            now_foreground = self._get_foreground_package()
            if now_foreground:
                self.logger.info(f"应用当前前台包名: {now_foreground}")

        return started

    def stop_shadowverse_apps(self, *, trigger: str = "") -> bool:
        """Stop Shadowverse-related app(s) on device via adb/u2."""

        target_pkgs = self._find_shadowverse_packages()
        if not target_pkgs:
            self.logger.warning("未找到可关闭的Shadowverse相关包名")
            return False

        self.logger.info(
            "停止脚本触发应用关闭%s: %s",
            f"({trigger})" if trigger else "",
            target_pkgs,
        )

        stopped_any = False
        for pkg in target_pkgs:
            try:
                if self.adb_device is not None:
                    self.adb_device.shell(f"am force-stop {pkg}")
                elif self.u2_device_raw is not None:
                    self.u2_device_raw.app_stop(pkg)
                elif self.u2_device is not None:
                    self.u2_device.app_stop(pkg)
                stopped_any = True
            except Exception as e:
                self.logger.warning(f"关闭应用 {pkg} 失败: {e}")

        return stopped_any

    def check_interrupt(self) -> None:
        """Raise if paused/stopped so callers can unwind quickly."""

        if not getattr(self, "script_running", True):
            raise StopRequested("script stopped")

        if self.script_paused and not self.pause_event.is_set():
            # Keep legacy flag in sync.
            self.pause_event.set()

        if self.pause_event.is_set() or self.script_paused:
            raise PauseRequested("paused")

    def sleep(self, seconds: float, *, step: float = 0.05) -> None:
        """Interruptible sleep: raises PauseRequested/StopRequested when needed."""

        try:
            total = float(seconds)
        except Exception:
            total = 0.0
        if total <= 0:
            self.check_interrupt()
            return

        end = time.time() + total
        while True:
            self.check_interrupt()
            remain = end - time.time()
            if remain <= 0:
                return
            time.sleep(min(float(step), remain))

    def wait_while_paused(self, *, poll: float = 0.2) -> None:
        """Block until resumed; then apply resume policy."""

        while self.is_paused() and getattr(self, "script_running", True):
            time.sleep(float(poll))

        # Apply "new turn" semantics after a pause cycle.
        self.apply_resume_policy_if_needed()

    def apply_resume_policy_if_needed(self) -> None:
        """After resume, treat the paused turn as ended and reset minimal state."""

        if self.is_paused() or not getattr(self, "script_running", True):
            return
        if not getattr(self, "_resume_advance_round_pending", False):
            return

        self._resume_advance_round_pending = False

        # Only advance turn counter inside an active battle phase.
        # In pre-battle pages (war/decision), do not advance turn.
        phase_key = str(getattr(self, "current_stage_key", "") or "")
        should_advance_turn = bool(
            getattr(self, "in_match", False)
            and phase_key not in {"war", "decision"}
        )

        if should_advance_turn:
            try:
                prev = int(getattr(self, "current_round_count", 1) or 1)
            except Exception:
                prev = 1
            self.current_round_count = max(1, prev + 1)

        # Reset per-turn state that is known to be stale after manual intervention.
        try:
            self.has_clicked_plus_this_round = False
        except Exception:
            pass
        try:
            self.last_detected_button = None
        except Exception:
            pass
        try:
            self.extra_cost_active = False
            self.extra_cost_remaining_uses = 0
        except Exception:
            pass

        # Let GameActions drop per-round caches.
        try:
            gm = getattr(self, "game_manager", None)
            if gm is not None and hasattr(gm, "game_actions"):
                ga = getattr(gm, "game_actions", None)
                if ga is not None and hasattr(ga, "reset_round_context_for_pause"):
                    ga.reset_round_context_for_pause()
        except Exception:
            pass

        try:
            if should_advance_turn:
                self.logger.info(
                    f"[控制] 恢复后默认本回合已结束：turn -> {self.current_round_count}"
                )
            elif getattr(self, "in_match", False):
                self.logger.info(
                    f"[控制] 恢复运行（预对战阶段，不推进回合）：turn={self.current_round_count}"
                )
            else:
                self.logger.info("[控制] 恢复运行")
        except Exception:
            pass

    def get_u2_device(self) -> Optional[U2DeviceLike]:
        """Get current wrapped u2 device (if connected)."""

        return self.u2_device

    def require_u2_device(self) -> U2DeviceLike:
        """Get wrapped u2 device or raise a descriptive runtime error."""

        dev = self.u2_device
        if dev is None:
            raise RuntimeError("u2_device is not connected")
        return dev

    def wrap_u2_device(self, u2_device: Optional[U2DeviceLike]) -> Optional[U2DeviceLike]:
        """Wrap uiautomator2 device to gate click/swipe on pause."""

        if u2_device is None:
            return u2_device
        try:
            # Keep a reference to the raw device for cleanup paths.
            self.u2_device_raw = u2_device
            return _U2DeviceProxy(self, u2_device)
        except Exception:
            return u2_device

    def take_screenshot_normal(self) -> Optional[Any]:
        """获取设备截图"""
        if self.adb_device is None:
            return None
        return self.adb_device.screenshot()

    def take_screenshot_MuMugblobe(self) -> Optional[Any]:
        """获取设备截图（使用Gamma校正增强亮度）"""
        if self.adb_device is None:
            return None

        try:
            screenshot = self.adb_device.screenshot()
            if screenshot is not None:
                img_array = np.array(screenshot)

                # 转换为BGR格式（OpenCV默认格式）
                if len(img_array.shape) == 3:
                    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                else:
                    img_bgr = img_array

                # Gamma校正（替代原来的 +43 亮度增强）
                # gamma > 1 使图像变暗，gamma < 1 使图像变亮
                # 使用 inv_gamma = 1/2.0 = 0.5 来提亮图像
                gamma = 2.0
                inv_gamma = 1.0 / gamma

                # 构建查找表（LUT）：256个预计算值，避免对每个像素计算
                # 使用 np.clip 确保值域在 [0, 255]，np.round 保证正确的四舍五入
                lut = np.clip(
                    np.round(np.power(np.arange(256) / 255.0, inv_gamma) * 255.0),
                    0,
                    255,
                ).astype(np.uint8)

                img_brightened = cv2.LUT(img_bgr, lut)

                # 转换回RGB格式
                img_rgb = cv2.cvtColor(img_brightened, cv2.COLOR_BGR2RGB)

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
            "run_id": self.current_run_start_time.strftime("%Y%m%d%H%M%S"),
        }

        self.match_history.append(match_record)

        # 保存统计数据到文件
        self.save_round_statistics()

        self.logger.info("===== 对战结束 =====")
        self.logger.info(
            f"回合数: {self.current_round_count}, 持续时间: {int(minutes)}分{int(seconds)}秒"
        )

        # 重置对战状态
        self.match_start_time = None
        self.in_match = False
        self.current_round_count = 1
        self.evolution_point = 2
        self.super_evolution_point = 2

    def save_round_statistics(self):
        """保存回合统计数据到文件"""
        stats_file = f"round_stats_{self.serial.replace(':', '_')}.json"
        try:
            write_json_atomic(stats_file, self.match_history, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存统计数据失败: {str(e)}")

    def load_round_statistics(self):
        """从文件加载回合统计数据"""
        stats_file = f"round_stats_{self.serial.replace(':', '_')}.json"
        if not os.path.exists(stats_file):
            return

        try:
            with open(stats_file, "r", encoding="utf-8") as f:
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
        total_rounds = sum(match["rounds"] for match in self.match_history)
        avg_rounds = total_rounds / total_matches if total_matches > 0 else 0

        # 计算本次运行数据
        current_run_matches = 0
        current_run_rounds = 0
        for match in self.match_history:
            if match.get("run_id") == self.current_run_start_time.strftime(
                "%Y%m%d%H%M%S"
            ):
                current_run_matches += 1
                current_run_rounds += match["rounds"]

        current_run_avg = (
            current_run_rounds / current_run_matches if current_run_matches > 0 else 0
        )

        # 按回合数分组统计
        from collections import defaultdict

        round_distribution = defaultdict(int)
        for match in self.match_history:
            round_distribution[match["rounds"]] += 1

        # 显示统计数据
        self.logger.info("\n===== 对战回合统计 =====")
        self.logger.info(f"总对战次数: {total_matches}")
        self.logger.info(f"总回合数: {total_rounds}")
        self.logger.info(f"平均每局回合数: {avg_rounds:.1f}")

        # 显示本次运行统计
        self.logger.info("\n===== 本次运行统计 =====")
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
            run_marker = (
                "(本次运行)"
                if match.get("run_id")
                == self.current_run_start_time.strftime("%Y%m%d%H%M%S")
                else ""
            )
            self.logger.info(
                f"{match['date']} - {match['rounds']}回合 ({match['duration']}) {run_marker}"
            )

    def update_activity_time(self):
        """更新最后活动时间"""
        self.last_activity_time = time.time()

    def check_timeout_and_restart(self) -> bool:
        """检查超时并重启游戏应用"""
        # 如果自动重启功能未启用，直接返回
        if not self.auto_restart_enabled:
            return False

        # 暂停/停止状态下，不触发自动重启。
        if not getattr(self, "script_running", True) or self.is_paused():
            return False

        current_time = time.time()

        trigger_reason = ""

        # 检查无新阶段超时
        stage_timeout_elapsed = current_time - self.last_stage_change_time
        if stage_timeout_elapsed >= self.stage_timeout:
            trigger_reason = f"{self.stage_timeout//60}分钟无新阶段"

        if not trigger_reason:
            return False

        # 达到自动重启次数上限后，再次触发则停止脚本。
        if self.auto_restart_trigger_count >= self.auto_restart_max_restarts:
            self.logger.error(
                f"自动重启已达上限({self.auto_restart_max_restarts}次)，再次触发[{trigger_reason}]，停止脚本"
            )
            self.request_stop(reason="auto_restart_limit")
            return True

        self.auto_restart_trigger_count += 1
        self.logger.warning(
            f"检测到{trigger_reason}，准备自动重启({self.auto_restart_trigger_count}/{self.auto_restart_max_restarts})"
        )

        # 先尝试一次空白点击，给结算/弹窗一个恢复机会。
        self.click_blank_before_restart()

        restarted = self.restart_emulator()
        if not restarted:
            self.logger.warning("自动重启执行失败，将在后续循环继续检查")
        return True

    def restart_emulator(self) -> bool:
        """重启所有包名包含 'Shadowverse' 或 'com.netease.yzs' 的应用，不重启模拟器"""
        # Do not issue disruptive device commands while paused/stopped.
        try:
            self.check_interrupt()
        except PauseRequested:
            try:
                self.logger.info("[控制] 暂停中，跳过重启应用")
            except Exception:
                pass
            return False
        except StopRequested:
            return False

        try:
            self.logger.info(
                "开始重启所有包含 'Shadowverse' 或 'com.netease.yzs' 的应用..."
            )
            if self.adb_device is None:
                self.logger.error("adb_device 未连接，无法重启应用")
                return False
            # 获取所有包名
            packages = self.adb_device.shell("pm list packages").splitlines()
            target_pkgs = [
                p.split(":")[-1]
                for p in packages
                if ("Shadowverse" in p or "shadowverse" in p or "com.netease.yzs" in p)
            ]
            if not target_pkgs:
                self.logger.warning(
                    "未找到包含 'Shadowverse' 或 'com.netease.yzs' 的包名"
                )
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
                        self.adb_device.shell(
                            f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1"
                        )
                except Exception as e:
                    self.logger.warning(f"启动应用 {pkg} 失败: {e}")
            self.logger.info(
                f"已重启所有包含 'Shadowverse' 或 'com.netease.yzs' 的应用: {target_pkgs}"
            )
            # 重置超时计时器
            self.current_stage_key = None
            self.last_stage_change_time = time.time()
            self.update_activity_time()
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
        self.mulligan_done_this_match = False

    def start_new_match(self):
        """开始新对战"""
        # 防止同一局在短时间内被重复触发start。
        if self.in_match and self.match_start_time is not None:
            elapsed = time.time() - float(self.match_start_time)
            if self.current_round_count <= 1 and elapsed < 12.0:
                self.logger.debug(
                    "忽略重复start_new_match: "
                    f"elapsed={elapsed:.1f}s round={self.current_round_count}"
                )
                return

        if self.in_match:
            self.end_current_match()

        self.current_run_matches += 1
        self.match_start_time = time.time()
        self.in_match = True
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
        self.mulligan_done_this_match = False

        self.logger.info(f"检测到新对战开始 - 第{self.current_run_matches}场对战")
        # 将对战次数信息发送到日志队列，供UI界面显示
        if self.log_queue is not None:
            self.log_queue.put(f"[对战开始] 第{self.current_run_matches}场对战")

    def get_run_summary(self) -> Dict[str, Any]:
        """获取本次运行总结"""
        run_duration = datetime.datetime.now() - self.current_run_start_time
        hours, remainder = divmod(run_duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)

        return {
            "start_time": self.current_run_start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": f"{int(hours)}小时{int(minutes)}分钟{int(seconds)}秒",
            "matches_completed": self.current_run_matches,
            "serial": self.serial,
        }
