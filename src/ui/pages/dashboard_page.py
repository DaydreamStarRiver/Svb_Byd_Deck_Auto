"""展示设备、运行控制、卡组摘要和实时日志的仪表盘。"""

from __future__ import annotations

import os
from typing import Any, Dict

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui.deck_io import MAX_DECK_SIZE


def format_duration(seconds: int) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "0", accent: str = "primary", parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setProperty("accent", accent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.value_label.setProperty("accent", accent)
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("MetricDetail")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def set_value(self, value: Any, detail: str = "") -> None:
        self.value_label.setText(str(value))
        self.detail_label.setText(str(detail or ""))


class CostCurveWidget(QWidget):
    DISPLAY_BUCKETS = tuple(range(1, 9))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._costs: Dict[int, int] = {}
        self.setFixedHeight(124)
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("费用 8 及以上合并为 8+；0 费卡会在总数区域单独标明")

    def set_costs(self, costs: Dict[Any, Any]) -> None:
        normalized: Dict[int, int] = {}
        for key, value in (costs or {}).items():
            try:
                cost = int(key)
                count = int(value)
            except Exception:
                continue
            if cost < 0 or count <= 0:
                continue
            bucket = 8 if cost >= 8 else cost
            normalized[bucket] = normalized.get(bucket, 0) + count
        self._costs = normalized
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API 命名
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(3.0, 2.0, -3.0, -2.0)
        summary_width = 74.0 if bounds.width() >= 320.0 else 64.0
        summary_gap = 10.0
        chart_width = max(160.0, bounds.width() - summary_width - summary_gap)
        chart = QRectF(bounds.left(), bounds.top(), chart_width, bounds.height())
        summary = QRectF(
            chart.right() + summary_gap,
            bounds.top(),
            max(0.0, bounds.right() - chart.right() - summary_gap),
            bounds.height(),
        )

        buckets = self.DISPLAY_BUCKETS
        values = [self._costs.get(cost, 0) for cost in buckets]
        max_count = max(values or [1]) or 1
        slot_width = chart.width() / len(buckets)
        count_height = 18.0
        badge_size = min(23.0, max(17.0, slot_width - 7.0))
        badge_top = chart.bottom() - badge_size - 2.0
        track_top = chart.top() + count_height + 4.0
        track_bottom = badge_top - 5.0
        track_height = max(12.0, track_bottom - track_top)
        track_width = min(15.0, max(8.0, slot_width * 0.38))

        base_font = painter.font()
        count_font = painter.font()
        count_font.setPointSize(9)
        count_font.setBold(True)
        painter.setFont(count_font)

        for index, cost in enumerate(buckets):
            value = self._costs.get(cost, 0)
            center_x = chart.left() + slot_width * (index + 0.5)
            count_rect = QRectF(
                chart.left() + slot_width * index,
                chart.top(),
                slot_width,
                count_height,
            )
            painter.setPen(QColor("#cdd6f4" if value else "#6c7086"))
            painter.drawText(count_rect, int(Qt.AlignHCenter | Qt.AlignVCenter), str(value))

            track = QRectF(
                center_x - track_width / 2.0,
                track_top,
                track_width,
                track_height,
            )
            painter.setPen(QPen(QColor("#39543a"), 1.0))
            painter.setBrush(QColor("#263b2c"))
            painter.drawRoundedRect(track, 1.5, 1.5)

            if value > 0:
                fill_height = max(3.0, track.height() * value / max_count)
                fill = QRectF(
                    track.left() + 1.0,
                    track.bottom() - fill_height + 1.0,
                    max(1.0, track.width() - 2.0),
                    min(track.height() - 2.0, fill_height),
                )
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#79b84a"))
                painter.drawRoundedRect(fill, 1.0, 1.0)

            badge = QRectF(
                center_x - badge_size / 2.0,
                badge_top,
                badge_size,
                badge_size,
            )
            painter.setPen(QPen(QColor("#8bc75b" if value else "#52664c"), 1.5))
            painter.setBrush(QColor("#31552e" if value else "#29352b"))
            painter.drawEllipse(badge)

            badge_font = painter.font()
            badge_font.setPointSize(8 if cost == 8 else 9)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            painter.setPen(QColor("#eff7e8" if value else "#9399b2"))
            painter.drawText(
                badge,
                int(Qt.AlignCenter),
                "8+" if cost == 8 else str(cost),
            )
            painter.setFont(count_font)

        if summary.width() > 0:
            separator_x = summary.left() - summary_gap / 2.0
            painter.setPen(QPen(QColor("#3a3a4a"), 1.0))
            painter.drawLine(
                int(separator_x),
                int(bounds.top() + 8.0),
                int(separator_x),
                int(bounds.bottom() - 8.0),
            )

            total = sum(self._costs.values())
            zero_count = self._costs.get(0, 0)
            label_font = painter.font()
            label_font.setPointSize(8)
            painter.setFont(label_font)
            painter.setPen(QColor("#9399b2"))
            painter.drawText(
                QRectF(summary.left(), summary.top() + 5.0, summary.width(), 18.0),
                int(Qt.AlignCenter),
                "总计",
            )

            total_font = painter.font()
            total_font.setPointSize(15)
            total_font.setBold(True)
            painter.setFont(total_font)
            painter.setPen(QColor("#cdd6f4"))
            painter.drawText(
                QRectF(summary.left(), summary.top() + 25.0, summary.width(), 34.0),
                int(Qt.AlignCenter),
                f"{total}/{MAX_DECK_SIZE}",
            )

            painter.setFont(label_font)
            painter.setPen(QColor("#9399b2"))
            painter.drawText(
                QRectF(summary.left(), summary.top() + 60.0, summary.width(), 17.0),
                int(Qt.AlignCenter),
                "张卡牌",
            )
            if zero_count:
                zero_font = painter.font()
                zero_font.setPointSize(8)
                zero_font.setBold(True)
                painter.setFont(zero_font)
                painter.setPen(QColor("#f9e2af"))
                painter.drawText(
                    QRectF(summary.left(), summary.top() + 84.0, summary.width(), 19.0),
                    int(Qt.AlignCenter),
                    f"0费  {zero_count}",
                )

        painter.setFont(base_font)


class DashboardPage(QWidget):
    connect_requested = pyqtSignal()
    start_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    screenshot_requested = pyqtSignal()
    navigate_requested = pyqtSignal(str)
    disclaimer_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._run_status = "disconnected"
        self._device_connected = False
        self._build_ui()
        self.set_run_status("disconnected")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)

        title = QLabel("仪表盘")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.device_banner = QFrame()
        self.device_banner.setObjectName("SurfacePanel")
        banner = QHBoxLayout(self.device_banner)
        banner.setContentsMargins(16, 14, 16, 14)
        banner.setSpacing(12)
        self.device_dot = QLabel("●")
        self.device_dot.setObjectName("DeviceDot")
        self.device_status = QLabel("设备未连接")
        self.device_status.setObjectName("SectionTitle")
        self.device_detail = QLabel("请填写 ADB 地址后连接设备")
        self.device_detail.setObjectName("SubtleText")
        device_text = QVBoxLayout()
        device_text.setSpacing(2)
        device_text.addWidget(self.device_status)
        device_text.addWidget(self.device_detail)
        banner.addWidget(self.device_dot)
        banner.addLayout(device_text)
        banner.addStretch()
        self.connect_button = QPushButton("连接设备")
        self.connect_button.setObjectName("SecondaryButton")
        self.connect_button.clicked.connect(self.connect_requested)
        self.screenshot_button = QPushButton("截图预览")
        self.screenshot_button.setObjectName("SecondaryButton")
        self.screenshot_button.clicked.connect(self.screenshot_requested)
        self.screenshot_button.setEnabled(False)
        banner.addWidget(self.connect_button)
        banner.addWidget(self.screenshot_button)
        root.addWidget(self.device_banner)

        metrics = QHBoxLayout()
        metrics.setSpacing(14)
        self.battles_metric = MetricCard("本次对战次数", "0", "primary")
        self.runtime_metric = MetricCard("运行时长", "00:00:00", "success")
        self.cards_metric = MetricCard("当前卡组卡牌", "0", "warning")
        self.status_metric = MetricCard("脚本状态", "未连接", "neutral")
        for card in (
            self.battles_metric,
            self.runtime_metric,
            self.cards_metric,
            self.status_metric,
        ):
            metrics.addWidget(card, 1)
        root.addLayout(metrics)

        center = QHBoxLayout()
        center.setSpacing(16)
        control_panel = QFrame()
        control_panel.setObjectName("SurfacePanel")
        control = QVBoxLayout(control_panel)
        control.setContentsMargins(18, 16, 18, 18)
        control.setSpacing(14)
        control.addWidget(self._section_title("运行控制"))

        primary_buttons = QHBoxLayout()
        primary_buttons.setSpacing(10)
        self.start_button = QPushButton("开始运行")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self.start_requested)
        self.pause_button = QPushButton("暂停")
        self.pause_button.setObjectName("SecondaryButton")
        self.pause_button.clicked.connect(self.pause_requested)
        self.resume_button = QPushButton("恢复")
        self.resume_button.setObjectName("SecondaryButton")
        self.resume_button.clicked.connect(self.resume_requested)
        self.stop_button = QPushButton("停止运行")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.clicked.connect(self.stop_requested)
        primary_buttons.addWidget(self.start_button, 2)
        primary_buttons.addWidget(self.pause_button, 1)
        primary_buttons.addWidget(self.resume_button, 1)
        primary_buttons.addWidget(self.stop_button, 2)
        control.addLayout(primary_buttons)

        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(11)
        self.adb_input = QLineEdit("127.0.0.1:16384")
        self.server_combo = QComboBox()
        self.server_combo.addItems(["国服", "国际服"])
        self.adb_input.textChanged.connect(self._refresh_control_states)
        self.server_combo.currentTextChanged.connect(self._refresh_control_states)
        form.addWidget(QLabel("ADB 地址"), 0, 0)
        form.addWidget(self.adb_input, 0, 1)
        form.addWidget(QLabel("服务器"), 1, 0)
        form.addWidget(self.server_combo, 1, 1)
        self.deep_color_checkbox = QCheckBox("深色识别")
        self.gala_mode_checkbox = QCheckBox("庆典模式")
        self.auto_pass_checkbox = QCheckBox("空过模式")
        self.auto_restart_checkbox = QCheckBox("自动重启")
        quick_flags = QHBoxLayout()
        for checkbox in (
            self.deep_color_checkbox,
            self.gala_mode_checkbox,
            self.auto_pass_checkbox,
            self.auto_restart_checkbox,
        ):
            quick_flags.addWidget(checkbox)
        quick_flags.addStretch()
        form.addLayout(quick_flags, 2, 0, 1, 2)
        control.addLayout(form)

        deck_panel = QFrame()
        deck_panel.setObjectName("SurfacePanel")
        deck = QVBoxLayout(deck_panel)
        deck.setContentsMargins(18, 16, 18, 16)
        deck.setSpacing(10)
        deck_header = QHBoxLayout()
        deck_header.addWidget(self._section_title("当前卡组"))
        deck_header.addStretch()
        self.deck_state_label = QLabel("已应用")
        self.deck_state_label.setObjectName("SubtleText")
        self.deck_state_label.setProperty("status", "success")
        deck_header.addWidget(self.deck_state_label)
        edit_deck = QPushButton("编辑卡组")
        edit_deck.setObjectName("LinkButton")
        edit_deck.clicked.connect(lambda: self.navigate_requested.emit("deck"))
        deck_header.addWidget(edit_deck)
        deck.addLayout(deck_header)
        self.deck_name_label = QLabel("未命名卡组")
        self.deck_name_label.setObjectName("DeckName")
        self.deck_count_label = QLabel("已选择 0 张不同卡牌")
        self.deck_count_label.setObjectName("SubtleText")
        deck.addWidget(self.deck_name_label)
        deck.addWidget(self.deck_count_label)
        rotation_header = QHBoxLayout()
        rotation_title = QLabel("自动轮换")
        rotation_title.setObjectName("SubtleText")
        self.rotation_state_label = QLabel("未启用")
        self.rotation_state_label.setObjectName("SubtleText")
        rotation_header.addWidget(rotation_title)
        rotation_header.addStretch(1)
        rotation_header.addWidget(self.rotation_state_label)
        deck.addLayout(rotation_header)
        self.rotation_progress_label = QLabel("启用后显示当前、下一卡组和剩余局数")
        self.rotation_progress_label.setObjectName("SubtleText")
        self.rotation_progress_label.setWordWrap(True)
        deck.addWidget(self.rotation_progress_label)
        curve_label = QLabel("费用分布")
        curve_label.setObjectName("SubtleText")
        deck.addWidget(curve_label)
        self.cost_curve = CostCurveWidget()
        deck.addWidget(self.cost_curve)

        center.addWidget(control_panel, 3)
        center.addWidget(deck_panel, 2)
        root.addLayout(center)

        log_panel = QFrame()
        log_panel.setObjectName("SurfacePanel")
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        log_header = QHBoxLayout()
        log_header.setContentsMargins(16, 11, 12, 9)
        log_header.addWidget(self._section_title("实时日志"))
        log_header.addStretch()
        full_log = QPushButton("查看全部")
        full_log.setObjectName("LinkButton")
        full_log.clicked.connect(lambda: self.navigate_requested.emit("logs"))
        log_header.addWidget(full_log)
        log_layout.addLayout(log_header)
        self.log_output = QTextEdit()
        self.log_output.setObjectName("LiveLog")
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(150)
        self.log_output.document().setMaximumBlockCount(1000)
        log_layout.addWidget(self.log_output)
        root.addWidget(log_panel, 1)

        notice = QFrame()
        notice.setObjectName("DisclaimerStrip")
        notice_layout = QHBoxLayout(notice)
        notice_layout.setContentsMargins(10, 2, 6, 2)
        notice_layout.setSpacing(6)
        notice_text = QLabel("免费工具 · 仅供个人学习研究 · 使用风险自负")
        notice_text.setObjectName("DisclaimerNoticeText")
        notice_layout.addWidget(notice_text)
        notice_layout.addStretch()
        self.disclaimer_button = QPushButton("查看详情")
        self.disclaimer_button.setObjectName("LinkButton")
        self.disclaimer_button.clicked.connect(self.disclaimer_requested)
        notice_layout.addWidget(self.disclaimer_button)
        root.addWidget(notice)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def load_quick_settings(self, config: Dict[str, Any]) -> None:
        devices = config.get("devices", []) if isinstance(config, dict) else []
        if isinstance(devices, list) and devices:
            device = devices[-1] if isinstance(devices[-1], dict) else {}
            self.adb_input.setText(str(device.get("serial") or "127.0.0.1:16384"))
            self.server_combo.setCurrentText("国际服" if device.get("is_global") else "国服")
            self.deep_color_checkbox.setChecked(bool(device.get("screenshot_deep_color", False)))
            self.gala_mode_checkbox.setChecked(bool(device.get("gala_mode", False)))
        game = config.get("game", {}) if isinstance(config, dict) else {}
        auto_restart = config.get("auto_restart", {}) if isinstance(config, dict) else {}
        self.auto_pass_checkbox.setChecked(bool(game.get("enable_auto_pass", False)))
        self.auto_restart_checkbox.setChecked(bool(auto_restart.get("enabled", True)))
        rotation = config.get("deck_rotation", {}) if isinstance(config, dict) else {}
        if not isinstance(rotation, dict):
            rotation = {}
        sequence = rotation.get("sequence", [])
        sequence = sequence if isinstance(sequence, list) else []
        first_slot = sequence[0] if sequence else None
        profiles = rotation.get("slot_profiles", {})
        profiles = profiles if isinstance(profiles, dict) else {}
        next_file = profiles.get(str(first_slot), "") if first_slot is not None else ""
        self.set_rotation_status(
            {
                "enabled": bool(rotation.get("enabled", False) and sequence),
                "state": "ready",
                "current_slot": None,
                "current_name": "",
                "next_slot": first_slot,
                "next_name": os.path.splitext(os.path.basename(str(next_file or "")))[0],
                "completed": 0,
                "interval": int(rotation.get("interval_matches", 5) or 5),
                "remaining": int(rotation.get("interval_matches", 5) or 5),
                "mode": str(rotation.get("mode", "cycle") or "cycle"),
            }
        )

    def connection_values(self) -> Dict[str, Any]:
        return {
            "serial": self.adb_input.text().strip(),
            "server": self.server_combo.currentText(),
            "is_global": self.server_combo.currentText() == "国际服",
            "screenshot_deep_color": self.deep_color_checkbox.isChecked(),
            "gala_mode": self.gala_mode_checkbox.isChecked(),
            "enable_auto_pass": self.auto_pass_checkbox.isChecked(),
            "auto_restart_enabled": self.auto_restart_checkbox.isChecked(),
        }

    def set_device_info(self, info: Dict[str, Any]) -> None:
        connected = bool(info.get("connected"))
        self._device_connected = connected
        self.device_dot.setProperty("connected", connected)
        self.device_dot.style().unpolish(self.device_dot)
        self.device_dot.style().polish(self.device_dot)
        self.device_status.setText("设备已连接" if connected else str(info.get("status") or "设备未连接"))
        serial = str(info.get("serial") or self.adb_input.text() or "-")
        server = str(info.get("server") or self.server_combo.currentText() or "-")
        model = str(info.get("model") or "未知型号")
        resolution = str(info.get("resolution") or "未知分辨率")
        message = str(info.get("message") or "")
        if connected:
            self.device_detail.setText(
                f"ADB: {serial}  |  服务器: {server}  |  "
                f"型号: {model}  |  分辨率: {resolution}"
            )
        else:
            self.device_detail.setText(message or f"ADB: {serial}")
        self.screenshot_button.setEnabled(connected)
        self._refresh_control_states()

    def set_run_status(self, status: str) -> None:
        self._run_status = str(status or "stopped")
        labels = {
            "disconnected": "未连接",
            "connecting": "连接中",
            "connected": "已连接",
            "running": "运行中",
            "paused": "已暂停",
            "stopping": "停止中",
            "stopped": "已停止",
            "error": "异常",
        }
        self.status_metric.set_value(labels.get(self._run_status, self._run_status))
        self._refresh_control_states()

    def _refresh_control_states(self, *args) -> None:
        del args
        running = self._run_status == "running"
        paused = self._run_status == "paused"
        active = running or paused or self._run_status == "stopping"
        connecting = self._run_status == "connecting"
        has_serial = bool(self.adb_input.text().strip())
        settings_enabled = self._run_status not in {
            "connecting",
            "running",
            "paused",
            "stopping",
        }
        self.connect_button.setEnabled(not active and not connecting and has_serial)
        self.start_button.setEnabled(not active and not connecting and has_serial)
        self.start_button.setToolTip(
            ""
            if self._device_connected
            else "开始运行时会先连接并检查当前设备"
        )
        self.pause_button.setEnabled(running)
        self.resume_button.setEnabled(paused)
        self.stop_button.setEnabled(running or paused)
        for control in (
            self.adb_input,
            self.server_combo,
            self.deep_color_checkbox,
            self.gala_mode_checkbox,
            self.auto_pass_checkbox,
            self.auto_restart_checkbox,
        ):
            control.setEnabled(settings_enabled)

    def set_elapsed(self, seconds: int) -> None:
        self.runtime_metric.set_value(format_duration(seconds), "本次运行")

    def set_battle_count(self, count: int) -> None:
        self.battles_metric.set_value(str(max(0, int(count or 0))), "本次运行")

    def set_active_deck(self, data: Dict[str, Any]) -> None:
        name = str(data.get("name") or "未命名卡组")
        count = max(0, int(data.get("count") or 0))
        distinct_count = max(0, int(data.get("distinct_count") or count))
        applied = bool(data.get("applied", True))
        self.deck_name_label.setText(name)
        self.deck_count_label.setText(
            f"已应用 {count} / {MAX_DECK_SIZE} 张 · {distinct_count} 种"
            if applied
            else f"工作区 {count} / {MAX_DECK_SIZE} 张 · {distinct_count} 种，尚未应用"
        )
        self.deck_state_label.setText("已应用" if applied else "待应用")
        self.deck_state_label.setProperty(
            "status", "success" if applied else "warning"
        )
        self.deck_state_label.style().unpolish(self.deck_state_label)
        self.deck_state_label.style().polish(self.deck_state_label)
        self.cards_metric.set_value(
            f"{count}/{MAX_DECK_SIZE}", "已应用卡牌" if applied else "工作区待应用"
        )
        self.cost_curve.set_costs(data.get("costs") or {})

    def set_rotation_status(self, data: Dict[str, Any]) -> None:
        enabled = bool(data.get("enabled", False))
        if not enabled:
            self.rotation_state_label.setText("未启用")
            self.rotation_progress_label.setText("启用后显示当前、下一卡组和剩余局数")
            return

        state = str(data.get("state") or "ready")
        state_labels = {
            "ready": "待命",
            "counting": "计数中",
            "pending": "等待切换",
            "switching": "正在切换",
            "active": "已同步",
            "recovered": "已恢复",
            "exhausted": "序列完成",
            "error": "切换异常",
        }
        self.rotation_state_label.setText(state_labels.get(state, state))
        current_slot = data.get("current_slot")
        current_name = str(data.get("current_name") or "").strip()
        next_slot = data.get("next_slot")
        next_name = str(data.get("next_name") or "").strip()
        current_text = (
            f"卡组 {current_slot} · {current_name or '本地构筑'}"
            if current_slot is not None
            else (current_name or "尚未完成启动同步")
        )
        if bool(data.get("exhausted", False)):
            next_text = "序列已完成"
        elif str(data.get("mode") or "") == "random" and next_slot is None:
            next_text = "随机选择"
        elif next_slot is not None:
            next_text = f"卡组 {next_slot} · {next_name or '本地构筑'}"
        else:
            next_text = "等待计数"
        remaining = max(0, int(data.get("remaining") or 0))
        interval = max(0, int(data.get("interval") or 0))
        self.rotation_progress_label.setText(
            f"当前：{current_text}\n下一项：{next_text} · 还需 {remaining}/{interval} 局"
        )

    def append_log(self, message: str) -> None:
        self.log_output.append(str(message or ""))
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
