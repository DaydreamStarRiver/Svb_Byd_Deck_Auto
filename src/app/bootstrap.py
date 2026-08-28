"""应用启动编排层（组合根）。

集中连接配置、日志、GPU 和设备线程，使各入口文件保持轻量。
"""

from __future__ import annotations

import logging
import threading
import traceback
import queue
import sys
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.app.native_runtime import (
    loaded_cpp_runtime_paths,
    prepare_windows_cpp_runtime,
)
from src.config.config_manager import ConfigManager
from src.config.settings import EXPERIMENTAL_MAA_RECOGNITION_ENABLED
from src.core.logging_utils import setup_logging
from src.utils.consent_utils import display_disclaimer_and_get_consent
from src.utils.gpu_utils import get_easyocr_reader, setup_gpu

if TYPE_CHECKING:
    from src.device.device_manager import DeviceManager


def _command_listener(
    command_queue: "queue.Queue[str]",
    device_manager: "DeviceManager",
    logger: logging.Logger,
    stop_event: threading.Event,
) -> None:
    """命令监听线程（广播到所有设备）。"""

    logger.info("命令监听线程启动")
    logger.info("可用命令: 'p'暂停, 'r'恢复, 'e'退出, 's'统计")

    while not stop_event.is_set():
        try:
            try:
                cmd = command_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if stop_event.is_set():
                break

            # 立即应用暂停或恢复，不等待设备主循环下一次轮询。
            if cmd == "p":
                for device_state in device_manager.device_states.values():
                    device_state.request_pause(reason="command")
                continue
            if cmd == "r":
                for device_state in device_manager.device_states.values():
                    device_state.request_resume(reason="command")
                continue

            if cmd == "e":
                logger.info("收到退出命令，正在停止所有设备...")
                for device_state in device_manager.device_states.values():
                    device_state.request_stop(reason="user_exit")
                break
            if cmd == "s":
                logger.info("显示所有设备统计信息:")
                for serial, device_state in device_manager.device_states.items():
                    logger.info(f"\n--- 设备 {serial} 统计 ---")
                    device_state.show_round_statistics()

        # 为后续扩展命令保留回退分支。
            for device_state in device_manager.device_states.values():
                device_state.command_queue.put(cmd)

        except KeyboardInterrupt:
            logger.info("命令监听被中断")
            break
        except Exception as e:
            logger.error(f"命令监听异常: {str(e)}")
            break

    logger.info("命令监听线程结束")


def run_cli(
    *,
    enable_command_listener: bool,
    command_queue: "queue.Queue[str]",
    log_queue: Optional["queue.Queue[str]"],
    device_config: Optional[Dict[str, Any]] = None,
) -> None:
    """运行 CLI 或脚本模式的自动化循环。

    ``device_config`` 可接收界面传入的设备配置；提供后直接使用，不再从
    ``config.json`` 读取设备信息。
    """

    logger: logging.Logger = logging.getLogger(__name__)

    prepare_windows_cpp_runtime()

    # 延迟导入重量级模块，保持界面启动轻量。
    from src.device.device_manager import DeviceManager
    from src.ui.notification_manager import NotificationManager

    command_stop_event: Optional[threading.Event] = None
    command_thread: Optional[threading.Thread] = None
    try:
        # 初始化配置管理器
        config_manager = ConfigManager()

        # 如果提供了设备配置，直接使用它覆盖config中的设备列表
        if device_config is not None:
            config_manager.config["devices"] = [device_config]
            logger.info(f"使用UI输入的设备配置: {device_config.get('serial')}")

            # 如果设备配置中包含策略配置，应用到全局配置
            strategy_config = device_config.get("strategy_config")
            if isinstance(strategy_config, dict) and strategy_config:
                try:
                    from src.ui.deck_io import apply_strategy_config

                    config_manager.config = apply_strategy_config(
                        config_manager.config, strategy_config=strategy_config
                    )
                    logger.info("已应用卡组策略配置")
                except Exception as e:
                    logger.warning(f"应用策略配置失败: {e}")

        # 注入运行时配置，避免热路径重复读取磁盘。
        try:
            from src.config import settings as _settings

            _settings.set_runtime_config(config_manager.config)
        except Exception:
            pass

        # 设置日志系统（尽早初始化，方便后续步骤输出一致）
        log_file = "main_log.log"
        logger = setup_logging(config_manager.config, log_queue, log_file=log_file)
        logger.info("=== 影之诗自动对战脚本启动 ===")
        logger.info(f"使用配置文件: {config_manager.config_file}")
        logger.info("[Native] Python=%s; C++ runtime=%s", sys.executable, loaded_cpp_runtime_paths())

        # 记录当前启用的卡组与策略档案。
        try:
            from src.config.profiles import (
                format_profile_summary,
                get_active_deck_profile,
                get_active_strategy_profile,
            )

            deck_p = get_active_deck_profile(config_manager.config)
            strat_p = get_active_strategy_profile(config_manager.config)
            logger.info("Profile: %s", format_profile_summary(deck_p, strat_p))
        except Exception:
            pass

        # 验证配置
        if not config_manager.validate_config():
            logger.error("配置验证失败，请检查配置文件")
            return

        # 重新加载卡牌优先级配置（确保能正确读取）
        try:
            from src.config.card_priorities import reload_config

            reload_config(config_manager.config)
            logger.info("卡牌优先级配置重新加载完成")
        except Exception as e:
            logger.warning(f"重新加载卡牌优先级配置失败: {e}")

        # 显示免责声明并获取用户同意
        if not display_disclaimer_and_get_consent():
            logger.info("用户未同意免责声明，程序退出")
            return

        recognition_config = config_manager.config.get("recognition", {})
        recognition_backend = str(
            recognition_config.get("backend", "legacy")
            if isinstance(recognition_config, dict)
            else "legacy"
        ).strip().lower()
        if EXPERIMENTAL_MAA_RECOGNITION_ENABLED and recognition_backend == "maa":
            # Maa 在设备线程中按数字/页面语言分别惰性加载模型。
            logger.info("识别方案: MaaFramework 新版识别（CPU）")
        else:
            # 设置GPU并全局初始化旧版 EasyOCR，确保子线程共享实例。
            gpu_enabled: bool = bool(setup_gpu())
            if gpu_enabled:
                logger.info("旧版OCR识别GPU加速已启用")
            else:
                logger.info("旧版OCR识别使用CPU模式")

            ocr_reader = get_easyocr_reader(gpu_enabled=gpu_enabled)
            if ocr_reader is not None:
                logger.info("全局EasyOCR reader初始化成功")
            else:
                logger.warning("全局EasyOCR reader初始化失败，将仅使用MNIST兜底")

        # 初始化通知管理器
        notification_manager = NotificationManager()
        notification_manager.start()

        # 创建设备管理器
        device_manager = DeviceManager(
            config_manager, notification_manager, log_queue=log_queue
        )

        # 启动设备处理
        device_manager.start_all_devices()

        # 启动命令监听线程
        if enable_command_listener:
            command_stop_event = threading.Event()
            command_thread = threading.Thread(
                target=_command_listener,
                args=(command_queue, device_manager, logger, command_stop_event),
                daemon=True,
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
        if command_stop_event is not None:
            command_stop_event.set()
        if command_thread is not None and command_thread.is_alive():
            command_thread.join()


def run_gui(argv: Optional[list[str]] = None) -> int:
    """启动 PyQt 图形界面，并复用同一套自动化运行器。"""

    import sys as _sys

    # 必须先于任何 PyQt5 导入，避免 Qt 自带旧 MSVCP140 抢占 MAA 的依赖。
    # 只加载系统运行库，不加载 Maa/EasyOCR 或任何识别模型。
    prepare_windows_cpp_runtime()

    from PyQt5.QtWidgets import QApplication

    from src.ui.disclaimer import request_startup_disclaimer
    from src.ui.main_window import ShadowverseUI
    from src.ui.theme import apply_theme

    command_queue: "queue.Queue[str]" = queue.Queue()
    log_queue: "queue.Queue[str]" = queue.Queue()

    def run_main_script(
        *,
        enable_command_listener: bool = True,
        device_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        run_cli(
            enable_command_listener=enable_command_listener,
            command_queue=command_queue,
            log_queue=log_queue,
            device_config=device_config,
        )

    app = QApplication(argv if argv is not None else _sys.argv)
    apply_theme(app)
    if not request_startup_disclaimer():
        return 0

    window = ShadowverseUI(run_main_script, command_queue, log_queue)
    window.show()
    return int(app.exec_())
