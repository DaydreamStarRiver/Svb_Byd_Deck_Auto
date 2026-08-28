#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyQt 控制中心主窗口。"""

from __future__ import annotations

import os
import json
import re
import sys
import time
from typing import Any, Dict, Optional

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.config.config_repository import ConfigRepository
from src.config.paths import get_app_root, get_config_path
from src.ui.app_state import AppState
from src.ui.background import BackgroundWidget, resolve_background_path
from src.ui.common import deep_update_dict
from src.ui.deck_store import DeckStore
from src.ui.disclaimer import show_disclaimer_dialog
from src.ui.pages.card_priority_page import CardPriorityPage
from src.ui.pages.config_page import ConfigPage
from src.ui.pages.dashboard_page import DashboardPage
from src.ui.pages.deck_workspace_page import DeckWorkspacePage
from src.ui.pages.deck_rotation_page import DeckRotationPage
from src.ui.pages.deck_center_page import DeckCenterPage
from src.ui.pages.logs_page import LogsPage
from src.ui.pages.statistics_page import StatisticsPage
from src.ui.theme import apply_theme
from src.ui.workers.log_listener import LogListener
from src.ui.workers.script_runner import ScriptRunner


class DeviceConnectionChecker(QThread):
    """后台执行的 ADB/uiautomator2 连接探测线程。"""

    finished_signal = pyqtSignal(bool, str, dict)

    def __init__(self, serial: str, parent=None):
        super().__init__(parent)
        self.serial = str(serial or "").strip()

    @staticmethod
    def _is_tcp_serial(serial: str) -> bool:
        return bool(re.match(r"^[^:\s]+:\d+$", str(serial or "").strip()))

    def run(self) -> None:
        serial = self.serial
        if self.isInterruptionRequested():
            return
        if not serial:
            self.finished_signal.emit(False, "设备序列号为空", {})
            return

        try:
            from adbutils import adb

            connect_message = ""
            if self._is_tcp_serial(serial):
                try:
                    connect_message = str(adb.connect(serial, timeout=5) or "")
                except Exception as exc:
                    connect_message = f"adb connect failed: {exc}"

            devices = [
                str(getattr(device, "serial", "") or "")
                for device in adb.device_list()
            ]
            if self.isInterruptionRequested():
                return
            if serial not in devices:
                detail = f"ADB 未找到设备 {serial}；当前设备: {devices or '无'}"
                if connect_message:
                    detail += f"；connect: {connect_message}"
                self.finished_signal.emit(False, detail, {})
                return

            import uiautomator2 as u2

            device = u2.connect(serial)
            if self.isInterruptionRequested():
                return
            if device is None:
                self.finished_signal.emit(False, f"uiautomator2 连接失败: {serial}", {})
                return

            raw_info = getattr(device, "info", {}) or {}
            if not isinstance(raw_info, dict):
                raw_info = {}
            width = raw_info.get("displayWidth") or raw_info.get("width")
            height = raw_info.get("displayHeight") or raw_info.get("height")
            model = (
                raw_info.get("productName")
                or raw_info.get("model")
                or raw_info.get("brand")
                or "Android 设备"
            )
            info = {
                "serial": serial,
                "model": str(model),
                "resolution": f"{width}×{height}" if width and height else "未知分辨率",
            }
            detail = f"设备连接成功: {serial}"
            if connect_message:
                detail += f"；connect: {connect_message}"
            self.finished_signal.emit(True, detail, info)
        except Exception as exc:
            self.finished_signal.emit(False, f"设备连接检测异常: {exc}", {})


class ScreenshotWorker(QThread):
    finished_signal = pyqtSignal(bool, str, object)

    def __init__(self, serial: str, parent=None):
        super().__init__(parent)
        self.serial = str(serial or "").strip()

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            import uiautomator2 as u2

            device = u2.connect(self.serial)
            if self.isInterruptionRequested():
                return
            image = device.screenshot()
            if self.isInterruptionRequested():
                return
            if image is None:
                raise RuntimeError("设备未返回截图")
            rgb = image.convert("RGB")
            data = rgb.tobytes("raw", "RGB")
            qimage = QImage(
                data,
                rgb.width,
                rgb.height,
                rgb.width * 3,
                QImage.Format_RGB888,
            ).copy()
            self.finished_signal.emit(True, "截图获取成功", qimage)
        except Exception as exc:
            self.finished_signal.emit(False, f"截图获取失败: {exc}", None)


class LogSink:
    """兼容旧页面调用 ``parent.log_output.append`` 的适配器。"""

    def __init__(self, callback):
        self._callback = callback

    def append(self, message: Any) -> None:
        self._callback(str(message or ""))


class ShadowverseUI(QMainWindow):
    def __init__(self, run_main_script, command_queue, log_queue):
        super().__init__()
        self._run_main_script = run_main_script
        self._command_queue = command_queue
        self._log_queue = log_queue
        self._device_check_thread: Optional[DeviceConnectionChecker] = None
        self._screenshot_thread: Optional[ScreenshotWorker] = None
        self._screenshot_purpose = "preview"
        self.script_thread: Optional[ScriptRunner] = None
        self._device_config: Optional[Dict[str, Any]] = None
        self._start_after_connect = False
        self._auto_pass = False
        self._run_start_time = 0.0
        self._close_pending = False
        self._close_deadline = 0.0

        app = QApplication.instance()
        if app is not None:
            apply_theme(app)

        self.state = AppState(self)
        self.log_output = LogSink(self.append_log)
        self.deck_store = DeckStore(
            decks_dir=os.path.join(get_app_root(), "saved_decks"),
            parent=self,
        )
        self._build_ui()
        self._apply_custom_background(self.config_page.config_data)
        self._wire_state()
        self.state.set_active_deck(self.deck_workspace_page.active_deck_summary())
        self._load_config_into_dashboard()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_run_time)
        self._close_poll_timer = QTimer(self)
        self._close_poll_timer.timeout.connect(self._retry_pending_close)
        self.log_listener = LogListener(self._log_queue, self)
        self.log_listener.log_signal.connect(self.append_log)
        self.log_listener.start()

    def show_about_disclaimer(self) -> None:
        """从主界面随时重新打开免责声明和交流群信息。"""

        show_disclaimer_dialog(self, require_acceptance=False)

    def _build_ui(self) -> None:
        self.setWindowTitle("Shadowverse Auto Control Center")
        self.setMinimumSize(980, 620)
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
        else:
            available = screen.availableGeometry()
            target_width = min(1560, max(980, int(available.width() * 0.90)))
            target_height = min(960, max(620, int(available.height() * 0.90)))
            self.resize(target_width, target_height)

        central = BackgroundWidget()
        self.app_root = central
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_sidebar())

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("PageStack")
        shell.addWidget(self.stacked_widget, 1)
        self.setCentralWidget(central)

        self.dashboard_page = DashboardPage(self)
        self.deck_workspace_page = DeckWorkspacePage(self)
        self.card_priority_page = CardPriorityPage(self)
        self.deck_rotation_page = DeckRotationPage(self)
        self.deck_center_page = DeckCenterPage(
            workspace_page=self.deck_workspace_page,
            priority_page=self.card_priority_page,
            rotation_page=self.deck_rotation_page,
            parent=self,
        )
        self.statistics_page = StatisticsPage(self)
        self.config_page = ConfigPage(self)
        self.logs_page = LogsPage(self)
        self.config_page.config_saved.connect(self._on_config_saved)
        self.deck_rotation_page.config_saved.connect(
            lambda _config: self._load_config_into_dashboard()
        )

        # 为现有卡牌与效果编辑器保留兼容别名。
        self.card_select_page = self.deck_workspace_page
        self.my_deck_page = self.deck_workspace_page
        self.share_page = self.deck_workspace_page

        self.pages: Dict[str, QWidget] = {
            "dashboard": self.dashboard_page,
            "deck_center": self.deck_center_page,
            "deck": self.deck_center_page,
            "cards": self.deck_center_page,
            "rotation": self.deck_center_page,
            "stats": self.statistics_page,
            "settings": self.config_page,
            "logs": self.logs_page,
        }
        for key in ("dashboard", "deck_center", "stats", "settings", "logs"):
            self.stacked_widget.addWidget(self.pages[key])
        self.stacked_widget.currentChanged.connect(self._sync_sidebar_selection)

        self.dashboard_page.connect_requested.connect(self.connect_device)
        self.dashboard_page.start_requested.connect(self.start_script)
        self.dashboard_page.pause_requested.connect(self.pause_script)
        self.dashboard_page.resume_requested.connect(self.resume_script)
        self.dashboard_page.stop_requested.connect(self.stop_script)
        self.dashboard_page.screenshot_requested.connect(self.show_screenshot_preview)
        self.dashboard_page.navigate_requested.connect(self.navigate)
        self.dashboard_page.disclaimer_requested.connect(self.show_about_disclaimer)
        self.deck_workspace_page.log_requested.connect(self.append_log)
        self.deck_workspace_page.active_deck_changed.connect(self.state.set_active_deck)
        self.deck_workspace_page.device_qr_requested.connect(
            self.capture_deck_qr_from_device
        )
        self.navigate("dashboard")

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(190)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QFrame()
        brand.setObjectName("SidebarBrand")
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(16, 12, 12, 12)
        mark = QLabel("SV")
        mark.setObjectName("BrandMark")
        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)
        title = QLabel("SV Auto")
        title.setObjectName("BrandTitle")
        subtitle = QLabel("Control Center")
        subtitle.setObjectName("BrandSubtitle")
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)
        brand_layout.addWidget(mark)
        brand_layout.addLayout(text_layout)
        brand_layout.addStretch()
        layout.addWidget(brand)

        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 10, 0, 0)
        nav_layout.setSpacing(2)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: Dict[str, QPushButton] = {}
        nav_items = [
            ("dashboard", "仪表盘"),
            ("deck_center", "卡组中心"),
            ("stats", "统计数据"),
            ("settings", "参数设置"),
            ("logs", "运行日志"),
        ]
        for key, label in nav_items:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page=key: self.navigate(page))
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            nav_layout.addWidget(button)
        nav_layout.addStretch()
        layout.addWidget(nav_container, 1)

        footer = QFrame()
        footer.setObjectName("SidebarFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(10, 8, 10, 9)
        footer_layout.setSpacing(5)
        self.about_button = QPushButton("关于与免责声明")
        self.about_button.setObjectName("SidebarAboutButton")
        self.about_button.setToolTip("查看使用风险、免费发布声明和交流群信息")
        self.about_button.clicked.connect(self.show_about_disclaimer)
        footer_layout.addWidget(self.about_button)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(4, 0, 4, 0)
        self.footer_dot = QLabel("●")
        self.footer_dot.setObjectName("FooterDot")
        self.footer_status = QLabel("服务待命")
        self.footer_status.setObjectName("BrandSubtitle")
        status_row.addWidget(self.footer_dot)
        status_row.addWidget(self.footer_status)
        status_row.addStretch()
        footer_layout.addLayout(status_row)
        layout.addWidget(footer)
        return sidebar

    def _on_config_saved(self, config: Dict[str, Any]) -> None:
        self.dashboard_page.load_quick_settings(config)
        self._apply_custom_background(config)

    def _apply_custom_background(self, config: Dict[str, Any]) -> bool:
        ui_config = config.get("ui", {}) if isinstance(config, dict) else {}
        if not isinstance(ui_config, dict):
            ui_config = {}
        background = ui_config.get("custom_background", {})
        if not isinstance(background, dict):
            background = {}
        return self.app_root.set_background(
            enabled=bool(background.get("enabled", False)),
            path=resolve_background_path(background.get("path", "")),
            opacity=background.get("opacity", 22),
        )

    def _wire_state(self) -> None:
        self.state.device_changed.connect(self.dashboard_page.set_device_info)
        self.state.run_status_changed.connect(self.dashboard_page.set_run_status)
        self.state.run_status_changed.connect(self._update_footer_status)
        self.state.elapsed_changed.connect(self.dashboard_page.set_elapsed)
        self.state.elapsed_changed.connect(
            lambda value: self.statistics_page.set_live_stats(value, self.state.battle_count)
        )
        self.state.battle_count_changed.connect(self.dashboard_page.set_battle_count)
        self.state.battle_count_changed.connect(
            lambda value: self.statistics_page.set_live_stats(self.state.elapsed_seconds, value)
        )
        self.state.active_deck_changed.connect(self.dashboard_page.set_active_deck)
        self.state.rotation_status_changed.connect(
            self.dashboard_page.set_rotation_status
        )
        self.state.log_added.connect(self.dashboard_page.append_log)
        self.state.log_added.connect(self.logs_page.append_log)
        self.state.set_run_status("disconnected")

    def navigate(self, key: str) -> None:
        key = str(key or "")
        page = self.pages.get(key)
        if page is None:
            return
        self.stacked_widget.setCurrentWidget(page)
        button_key = "deck_center" if key in {"deck", "cards", "rotation"} else key
        button = self.nav_buttons.get(button_key)
        if button is not None:
            button.setChecked(True)
        if key == "stats":
            self.statistics_page.refresh_stats()
            self.statistics_page.set_live_stats(
                self.state.elapsed_seconds,
                self.state.battle_count,
            )
        elif key in {"deck_center", "deck", "cards", "rotation"}:
            section = "deck" if key == "deck_center" else key
            self.deck_center_page.select_section(section)
        elif key == "settings":
            try:
                self.config_page.refresh_config_display()
            except Exception:
                pass

    def _sync_sidebar_selection(self, index: int) -> None:
        page = self.stacked_widget.widget(index)
        for key, candidate in self.pages.items():
            if candidate is page:
                button = self.nav_buttons.get(key)
                if button is not None:
                    button.setChecked(True)
                return

    def _load_config_into_dashboard(self) -> None:
        config, _, _ = ConfigRepository(get_config_path()).load_existing(
            allow_default_on_error=True
        )
        self.dashboard_page.load_quick_settings(config or {})

    def connect_device(self, *, start_after_connect: bool = False) -> None:
        if self.is_script_running():
            self._start_after_connect = False
            QMessageBox.warning(self, "运行中", "脚本运行中，不能重新连接设备。")
            return
        if self._device_check_thread is not None and self._device_check_thread.isRunning():
            if start_after_connect:
                self._start_after_connect = True
            return

        self._start_after_connect = bool(start_after_connect)

        values = self.dashboard_page.connection_values()
        serial = str(values.get("serial") or "").strip()
        if not serial:
            self._start_after_connect = False
            QMessageBox.warning(self, "ADB 地址为空", "请输入模拟器 ADB 地址。")
            return

        self.append_log(f"正在连接设备: {serial}...")
        self.state.set_run_status("connecting")
        self.state.set_device(
            connected=False,
            serial=serial,
            server=values.get("server"),
            status="连接中",
            message="正在检查 ADB 和 uiautomator2 连接",
        )

        self._device_config = {
            "name": f"模拟器-{serial}",
            "serial": serial,
            "is_global": bool(values.get("is_global")),
            "screenshot_deep_color": bool(values.get("screenshot_deep_color")),
            "gala_mode": bool(values.get("gala_mode")),
        }
        self._auto_pass = bool(values.get("enable_auto_pass"))
        self._save_device_config(values)
        self.script_thread = ScriptRunner(
            self._run_main_script,
            self._log_queue,
            self,
            device_config=self._device_config,
        )
        self.script_thread.status_signal.connect(self.update_status)
        self.script_thread.stats_signal.connect(self.update_stats)

        self._device_check_thread = DeviceConnectionChecker(serial, self)
        self._device_check_thread.finished_signal.connect(
            self._on_device_connection_checked
        )
        self._device_check_thread.start()

    def _save_device_config(self, values: Dict[str, Any]) -> None:
        try:
            repo = ConfigRepository(get_config_path())
            existing, _, parse_error = repo.load_existing(allow_default_on_error=False)
            if existing is None:
                self.append_log(f"保存配置失败: {parse_error or 'config.json 解析错误'}")
                return

            serial = str(values.get("serial") or "")
            device_update = {
                "name": f"模拟器-{serial}",
                "serial": serial,
                "is_global": bool(values.get("is_global")),
                "screenshot_deep_color": bool(values.get("screenshot_deep_color")),
                "gala_mode": bool(values.get("gala_mode")),
            }
            devices = existing.get("devices")
            devices = devices if isinstance(devices, list) else []
            updated_devices = []
            found = False
            for item in devices:
                if isinstance(item, dict) and item.get("serial") == serial:
                    merged = dict(item)
                    deep_update_dict(merged, device_update)
                    updated_devices.append(merged)
                    found = True
                else:
                    updated_devices.append(item)
            if not found:
                updated_devices.append(device_update)

            result = repo.update(
                {
                    "devices": updated_devices,
                    "game": {"enable_auto_pass": bool(values.get("enable_auto_pass"))},
                    "auto_restart": {
                        "enabled": bool(values.get("auto_restart_enabled"))
                    },
                },
                refuse_on_parse_error=True,
                indent=4,
                ensure_ascii=False,
            )
            if not result.ok:
                raise RuntimeError(result.error or "配置写入失败")
            self.append_log("设备与快捷设置已保存到 config.json")
        except Exception as exc:
            self.append_log(f"保存设备配置失败: {exc}")

    def _on_device_connection_checked(
        self,
        ok: bool,
        message: str,
        info: Dict[str, Any],
    ) -> None:
        should_start = bool(ok and self._start_after_connect and not self._close_pending)
        self._start_after_connect = False
        connection_config = dict(self._device_config or {})
        serial = str(connection_config.get("serial") or "")
        server = "国际服" if connection_config.get("is_global") else "国服"
        if ok:
            self.state.set_device(
                connected=True,
                serial=serial,
                server=server,
                model=info.get("model"),
                resolution=info.get("resolution"),
                message=message,
            )
            self.state.set_run_status("connected")
        else:
            self.state.set_device(
                connected=False,
                serial=serial,
                server=server,
                status="连接失败",
                message=message,
            )
            self.state.set_run_status("error")
        self.append_log(message)
        if self._device_check_thread is not None:
            self._device_check_thread.deleteLater()
        self._device_check_thread = None
        if should_start:
            self.start_script()

    def start_script(self) -> None:
        if self.is_script_running():
            return
        if not self.deck_workspace_page.workspace_is_applied():
            QMessageBox.warning(
                self,
                "卡组尚未应用",
                "卡组工作区存在未应用的修改，请先应用当前卡组再开始运行。",
            )
            return

        values = self.dashboard_page.connection_values()
        requested_serial = str(values.get("serial") or "").strip()
        if not requested_serial:
            QMessageBox.warning(self, "ADB 地址为空", "请输入模拟器 ADB 地址。")
            return

        connected_serial = str((self._device_config or {}).get("serial") or "")
        connection_ready = bool(
            self.state.device.get("connected")
            and self.script_thread is not None
            and requested_serial == connected_serial
        )
        if not connection_ready:
            self.append_log(f"[控制] 开始运行前先连接设备: {requested_serial}")
            self.connect_device(start_after_connect=True)
            return

        if self._device_config is not None:
            self._device_config.update(
                {
                    "name": f"模拟器-{connected_serial}",
                    "is_global": bool(values.get("is_global")),
                    "screenshot_deep_color": bool(
                        values.get("screenshot_deep_color")
                    ),
                    "gala_mode": bool(values.get("gala_mode")),
                }
            )
        self.state.set_device(server=values.get("server"))
        self._save_device_config(values)
        self.state.set_elapsed(0)
        self.state.set_battle_count(0)
        self.statistics_page.begin_run()
        self._run_start_time = time.time()
        self.script_thread.start()
        self.timer.start(1000)
        self.state.set_run_status("running")
        self.append_log("===== 脚本开始运行 =====")

    def pause_script(self) -> None:
        if not self.is_script_running():
            return
        self._command_queue.put("p")
        self.state.set_run_status("paused")
        self.append_log("[控制] 脚本已暂停")

    def resume_script(self) -> None:
        if not self.is_script_running():
            return
        self._command_queue.put("r")
        self.state.set_run_status("running")
        self.append_log("[控制] 脚本已恢复")

    def stop_script(self) -> None:
        if not self.is_script_running():
            return
        self._command_queue.put("e")
        self.state.set_run_status("stopping")
        self.append_log("[控制] 已发送停止命令，等待当前任务退出...")

    def is_script_running(self) -> bool:
        return bool(self.script_thread is not None and self.script_thread.isRunning())

    def update_status(self, status: str) -> None:
        mapping = {
            "运行中": "running",
            "已暂停": "paused",
            "已停止": "stopped",
        }
        normalized = mapping.get(str(status), str(status or "stopped"))
        self.state.set_run_status(normalized)
        if normalized == "stopped":
            self.timer.stop()
            self.statistics_page.refresh_stats()

    def update_stats(self, stats: Dict[str, Any]) -> None:
        if not isinstance(stats, dict):
            return
        if "battle_count" in stats:
            self.state.set_battle_count(int(stats.get("battle_count") or 0))
        if "run_time" in stats:
            self.state.set_elapsed(int(stats.get("run_time") or 0))

    def update_run_time(self) -> None:
        if self.is_script_running() and self._run_start_time > 0:
            self.state.set_elapsed(int(time.time() - self._run_start_time))

    def append_log(self, message: Any) -> None:
        text = str(message or "")
        if not text:
            return
        self.state.append_log(text)
        marker = "[卡组轮换状态]"
        if marker in text:
            raw = text.split(marker, 1)[1].strip()
            start = raw.find("{")
            if start >= 0:
                try:
                    payload, _end = json.JSONDecoder().raw_decode(raw[start:])
                    if isinstance(payload, dict):
                        self.state.set_rotation_status(payload)
                        summary = payload.get("deck_summary")
                        if isinstance(summary, dict):
                            self.state.set_active_deck(summary)
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
        if "[对战开始]" in text:
            match = re.search(r"第(\d+)场对战", text)
            if match:
                self.state.set_battle_count(int(match.group(1)))
        if "===== 对战结束 =====" in text:
            self.statistics_page.refresh_stats()

    def show_screenshot_preview(self) -> None:
        serial = str(self.dashboard_page.connection_values().get("serial") or "")
        if not serial:
            return
        if self._screenshot_thread is not None and self._screenshot_thread.isRunning():
            return
        self._screenshot_purpose = "preview"
        self.append_log("[设备] 正在获取截图预览...")
        self._screenshot_thread = ScreenshotWorker(serial, self)
        self._screenshot_thread.finished_signal.connect(self._on_screenshot_ready)
        self._screenshot_thread.start()

    def capture_deck_qr_from_device(self) -> None:
        serial = str(self.dashboard_page.connection_values().get("serial") or "")
        if not serial:
            QMessageBox.warning(self, "设备未配置", "请先在仪表盘填写设备序列号。")
            return
        if self._screenshot_thread is not None and self._screenshot_thread.isRunning():
            QMessageBox.information(self, "截图进行中", "已有一个设备截图任务正在执行。")
            return
        self._screenshot_purpose = "deck_qr"
        self.append_log("[二维码] 正在读取当前游戏画面...")
        self._screenshot_thread = ScreenshotWorker(serial, self)
        self._screenshot_thread.finished_signal.connect(self._on_screenshot_ready)
        self._screenshot_thread.start()

    def _on_screenshot_ready(self, ok: bool, message: str, image: object) -> None:
        self.append_log(f"[设备] {message}")
        purpose = self._screenshot_purpose
        if self._close_pending:
            pass
        elif ok and isinstance(image, QImage) and purpose == "deck_qr":
            self.deck_workspace_page.import_qr_qimage(image)
        elif ok and isinstance(image, QImage):
            dialog = QDialog(self)
            dialog.setWindowTitle("设备截图预览")
            dialog.resize(900, 600)
            layout = QVBoxLayout(dialog)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setPixmap(
                QPixmap.fromImage(image).scaled(
                    860,
                    540,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            scroll.setWidget(label)
            layout.addWidget(scroll)
            dialog.exec_()
        elif not ok:
            QMessageBox.warning(self, "截图失败", message)
        if self._screenshot_thread is not None:
            self._screenshot_thread.deleteLater()
        self._screenshot_thread = None
        self._screenshot_purpose = "preview"

    def _update_footer_status(self, status: str) -> None:
        labels = {
            "disconnected": "服务待命",
            "connecting": "正在连接",
            "connected": "设备在线",
            "running": "脚本运行中",
            "paused": "脚本已暂停",
            "stopping": "正在停止",
            "stopped": "运行已结束",
            "error": "连接异常",
        }
        self.footer_status.setText(labels.get(status, str(status)))
        self.footer_dot.setProperty(
            "active", status in {"connected", "running", "paused", "stopped"}
        )
        self.footer_dot.style().unpolish(self.footer_dot)
        self.footer_dot.style().polish(self.footer_dot)

    def _background_threads_running(self) -> bool:
        threads = (
            self.script_thread,
            self._device_check_thread,
            self._screenshot_thread,
        )
        return any(thread is not None and thread.isRunning() for thread in threads) or bool(
            getattr(self, "deck_workspace_page", None)
            and self.deck_workspace_page.card_update_running()
        )

    def _retry_pending_close(self) -> None:
        if not self._close_pending:
            return
        if not self._background_threads_running():
            self._close_poll_timer.stop()
            self.close()
            return
        if time.monotonic() >= self._close_deadline:
            self._close_poll_timer.stop()
            self._close_pending = False
            self.setEnabled(True)
            self.footer_status.setText("后台任务仍在退出，请稍后重试关闭")
            self.append_log(
                "[关闭] 后台任务尚未退出，窗口已恢复操作；请稍后再次关闭。"
            )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API 命名
        if not self._close_pending:
            self._close_pending = True
            self._start_after_connect = False
            self._close_deadline = time.monotonic() + 15.0
            self.footer_status.setText("正在等待后台任务退出")
            if self.is_script_running():
                try:
                    self._command_queue.put("e")
                    self.state.set_run_status("stopping")
                except Exception:
                    pass

            for worker in (self._device_check_thread, self._screenshot_thread):
                if worker is not None and worker.isRunning():
                    worker.requestInterruption()
            try:
                self.deck_workspace_page.request_card_update_stop()
            except Exception:
                pass

        if self._background_threads_running():
            self.setEnabled(False)
            self._close_poll_timer.start(100)
            event.ignore()
            return

        self._close_poll_timer.stop()
        try:
            self.log_listener.stop()
            self.log_listener.wait(1500)
        except Exception:
            pass
        event.accept()


__all__ = ["ShadowverseUI"]
