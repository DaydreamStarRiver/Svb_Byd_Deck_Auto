#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参数配置页面。"""

from __future__ import annotations

import os
from typing import Any, Tuple

from PyQt5.QtCore import Qt as _Qt, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QIntValidator, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.config.paths import get_config_path
from src.config.config_repository import ConfigRepository
from src.config.settings import EXPERIMENTAL_MAA_RECOGNITION_ENABLED
from src.ui.background import (
    BACKGROUND_OPACITY_DEFAULT,
    BACKGROUND_OPACITY_MAX,
    BACKGROUND_OPACITY_MIN,
    clamp_background_opacity,
    render_background_preview,
    resolve_background_path,
    serialize_background_path,
)


# 不同环境的 PyQt5 类型桩存在差异，因此保持 Qt 属性访问方式兼容。
Qt: Any = _Qt


class ConfigPage(QWidget):
    config_saved = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget: Any = parent
        self.config_data = self.load_config()
        self.init_ui()

    def init_ui(self):
        self.setObjectName("SettingsPage")
        self.setProperty("pageRoot", True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 22, 24, 20)
        main_layout.setSpacing(16)

        title_label = QLabel("参数设置")
        title_label.setObjectName("PageTitle")
        title_label.setProperty("heading", "page")
        main_layout.addWidget(title_label)

        subtitle_label = QLabel("统一管理操作速度、停止条件、界面背景和换牌策略")
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setProperty("muted", True)
        main_layout.addWidget(subtitle_label)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("SettingsScrollArea")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setAutoFillBackground(False)
        self.settings_scroll.viewport().setAutoFillBackground(False)

        settings_content = QWidget()
        settings_content.setObjectName("SettingsContent")
        settings_content.setProperty("pageRoot", True)
        content_layout = QVBoxLayout(settings_content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(14)

        drag_range = self._read_drag_range()
        basic_panel, basic_layout = self._create_section(
            "基础设置",
            "调整模拟点击拖拽的持续时间。数值越小操作越快，稳定性也会相应降低。",
            "BasicSettingsPanel",
        )
        basic_form = QGridLayout()
        self._configure_form_layout(basic_form)

        drag_validator = QDoubleValidator(0.0, 999999.0, 3, self)
        drag_validator.setNotation(QDoubleValidator.StandardNotation)

        self.min_drag_input = self._create_line_edit(
            str(drag_range[0]), "MinDragDurationInput"
        )
        self.min_drag_input.setValidator(drag_validator)
        self.max_drag_input = self._create_line_edit(
            str(drag_range[1]), "MaxDragDurationInput"
        )
        max_drag_validator = QDoubleValidator(0.0, 999999.0, 3, self)
        max_drag_validator.setNotation(QDoubleValidator.StandardNotation)
        self.max_drag_input.setValidator(max_drag_validator)

        self._add_form_row(
            basic_form,
            0,
            "最小拖拽时间",
            self.min_drag_input,
            "秒",
            "每次拖拽采用区间内的随机时长。",
        )
        self._add_form_row(
            basic_form,
            2,
            "最大拖拽时间",
            self.max_drag_input,
            "秒",
            "必须大于或等于最小拖拽时间。",
        )
        basic_layout.addLayout(basic_form)
        content_layout.addWidget(basic_panel)

        recognition_panel, recognition_layout = self._create_section(
            "识别设置",
            "选择旧版 EasyOCR/MNIST 流程，或使用 MaaFramework 识别战斗数值并提供页面文字回退。",
            "RecognitionSettingsPanel",
        )
        recognition_row = QHBoxLayout()
        recognition_row.setSpacing(12)
        recognition_label = QLabel("识别方案")
        recognition_label.setObjectName("SettingsFieldLabel")
        recognition_row.addWidget(recognition_label)

        self.recognition_combo = QComboBox()
        self.recognition_combo.setObjectName("RecognitionBackendCombo")
        self.recognition_combo.addItem("旧版识别（EasyOCR + MNIST）", "legacy")
        self.recognition_combo.addItem("新版识别（MaaFramework）", "maa")
        self.recognition_combo.setMinimumWidth(280)
        recognition_config = self.config_data.get("recognition", {})
        recognition_backend = "legacy"
        if EXPERIMENTAL_MAA_RECOGNITION_ENABLED:
            recognition_backend = str(
                recognition_config.get("backend", "legacy")
                if isinstance(recognition_config, dict)
                else "legacy"
            ).strip().lower()
        recognition_index = self.recognition_combo.findData(recognition_backend)
        self.recognition_combo.setCurrentIndex(max(0, recognition_index))
        recognition_row.addWidget(self.recognition_combo)
        recognition_hint = QLabel("设置在下次启动脚本时生效；MAA 初始化失败会自动回退旧版识别。")
        recognition_hint.setObjectName("SettingsFieldHint")
        recognition_hint.setProperty("dim", True)
        recognition_hint.setWordWrap(True)
        recognition_row.addWidget(recognition_hint, 1)
        recognition_layout.addLayout(recognition_row)
        recognition_panel.setVisible(EXPERIMENTAL_MAA_RECOGNITION_ENABLED)
        content_layout.addWidget(recognition_panel)

        self._load_background_values()
        appearance_panel, appearance_layout = self._create_section(
            "外观设置",
            "为主内容区设置本地背景图片。侧边栏、卡片和日志区域会保持实色。",
            "AppearanceSettingsPanel",
        )
        appearance_row = QHBoxLayout()
        appearance_row.setSpacing(18)

        self.background_preview = QLabel("未选择背景")
        self.background_preview.setObjectName("BackgroundPreview")
        self.background_preview.setAlignment(Qt.AlignCenter)
        self.background_preview.setFixedSize(260, 146)
        appearance_row.addWidget(self.background_preview, 0, Qt.AlignTop)

        background_controls = QVBoxLayout()
        background_controls.setSpacing(10)
        self.background_enabled_checkbox = QCheckBox("启用自定义背景")
        self.background_enabled_checkbox.setObjectName("CustomBackgroundCheckBox")
        background_controls.addWidget(self.background_enabled_checkbox)

        path_label = QLabel("背景图片")
        path_label.setObjectName("SettingsFieldLabel")
        background_controls.addWidget(path_label)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.background_path_input = QLineEdit()
        self.background_path_input.setObjectName("BackgroundPathInput")
        self.background_path_input.setReadOnly(True)
        self.background_path_input.setPlaceholderText("请选择 JPG、PNG、WebP 或 BMP 图片")
        path_row.addWidget(self.background_path_input, 1)
        self.background_browse_btn = QPushButton("选择图片")
        self.background_browse_btn.setObjectName("SecondaryButton")
        path_row.addWidget(self.background_browse_btn)
        self.background_clear_btn = QPushButton("清除")
        self.background_clear_btn.setObjectName("SecondaryButton")
        path_row.addWidget(self.background_clear_btn)
        background_controls.addLayout(path_row)

        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(10)
        opacity_label = QLabel("背景强度")
        opacity_label.setObjectName("SettingsFieldLabel")
        opacity_row.addWidget(opacity_label)
        self.background_opacity_slider = QSlider(Qt.Horizontal)
        self.background_opacity_slider.setObjectName("BackgroundOpacitySlider")
        self.background_opacity_slider.setRange(
            BACKGROUND_OPACITY_MIN,
            BACKGROUND_OPACITY_MAX,
        )
        opacity_row.addWidget(self.background_opacity_slider, 1)
        self.background_opacity_value = QLabel()
        self.background_opacity_value.setObjectName("SettingsUnitLabel")
        self.background_opacity_value.setMinimumWidth(42)
        opacity_row.addWidget(self.background_opacity_value)
        background_controls.addLayout(opacity_row)

        background_hint = QLabel("建议使用 16:9 图片；强度上限已限制，以保证文字可读性。")
        background_hint.setObjectName("SettingsFieldHint")
        background_hint.setProperty("dim", True)
        background_hint.setWordWrap(True)
        background_controls.addWidget(background_hint)
        background_controls.addStretch(1)
        appearance_row.addLayout(background_controls, 1)
        appearance_layout.addLayout(appearance_row)
        content_layout.addWidget(appearance_panel)

        self._load_run_values()
        run_panel, run_layout = self._create_section(
            "运行设置",
            "控制异常阶段恢复、重启次数以及脚本单次运行上限。",
            "RunSettingsPanel",
        )

        restart_header = QVBoxLayout()
        restart_header.setSpacing(4)
        self.restart_enabled_checkbox = QCheckBox("启用自动重启")
        self.restart_enabled_checkbox.setObjectName("AutoRestartCheckBox")
        self.restart_enabled_checkbox.setChecked(self.auto_restart_enabled)
        restart_header.addWidget(self.restart_enabled_checkbox)
        self.restart_note = QLabel("长时间没有进入新阶段时尝试恢复游戏")
        self.restart_note.setObjectName("SettingsInlineHint")
        self.restart_note.setProperty("muted", True)
        self.restart_note.setWordWrap(True)
        self.restart_note.setContentsMargins(24, 0, 0, 0)
        restart_header.addWidget(self.restart_note)
        run_layout.addLayout(restart_header)

        run_form = QGridLayout()
        self._configure_form_layout(run_form)
        self.restart_time_input = self._create_line_edit(
            str(self.stage_timeout), "RestartIntervalInput"
        )
        self.restart_time_input.setValidator(QIntValidator(1, 120, self))
        self.restart_count_input = self._create_line_edit(
            str(self.max_restarts), "RestartCountInput"
        )
        self.restart_count_input.setValidator(QIntValidator(1, 20, self))
        self.runtime_limit_input = self._create_line_edit(
            str(self.max_run_duration_minutes), "RuntimeLimitInput"
        )
        self.runtime_limit_input.setValidator(QIntValidator(0, 10080, self))
        self.target_wins_input = self._create_line_edit(
            str(self.target_wins), "TargetWinsInput"
        )
        self.target_wins_input.setValidator(QIntValidator(0, 9999, self))

        self._add_form_row(
            run_form,
            0,
            "无新阶段重启间隔",
            self.restart_time_input,
            "分钟",
            "允许范围 1-120 分钟。",
        )
        self._add_form_row(
            run_form,
            2,
            "自动重启最大次数",
            self.restart_count_input,
            "次",
            "达到次数后再次触发将停止脚本，允许范围 1-20 次。",
        )
        self._add_form_row(
            run_form,
            4,
            "脚本运行总时长",
            self.runtime_limit_input,
            "分钟",
            "0 表示不限制；达到上限后会等待当前对战结束再停止。",
        )
        self._add_form_row(
            run_form,
            6,
            "目标胜利场数",
            self.target_wins_input,
            "胜",
            "0 表示不限制；胜场达标后停在当前结算页，不再开始下一局。",
        )
        run_layout.addLayout(run_form)
        content_layout.addWidget(run_panel)

        strategy_panel, strategy_layout = self._create_section(
            "策略设置",
            "选择自动换牌使用的费用曲线。策略变更将在重启软件后完整生效。",
            "StrategySettingsPanel",
        )
        strategy_row = QHBoxLayout()
        strategy_row.setSpacing(12)
        strategy_label = QLabel("换牌策略")
        strategy_label.setObjectName("SettingsFieldLabel")
        strategy_row.addWidget(strategy_label)

        self.strategy_combo = QComboBox()
        self.strategy_combo.setObjectName("ReplacementStrategyCombo")
        self.strategy_combo.addItems(["3费档次", "4费档次", "5费档次"])
        self.strategy_combo.setMinimumWidth(220)
        current_strategy = self.config_data.get("game", {}).get(
            "card_replacement_strategy", "3费档次"
        )
        index = self.strategy_combo.findText(current_strategy)
        if index >= 0:
            self.strategy_combo.setCurrentIndex(index)
        strategy_row.addWidget(self.strategy_combo)

        self.strategy_help_btn = QPushButton("查看规则")
        self.strategy_help_btn.setObjectName("SecondaryButton")
        self.strategy_help_btn.clicked.connect(self.show_strategy_help)
        strategy_row.addWidget(self.strategy_help_btn)
        strategy_row.addStretch(1)
        strategy_layout.addLayout(strategy_row)
        content_layout.addWidget(strategy_panel)
        content_layout.addStretch(1)

        self.settings_scroll.setWidget(settings_content)
        main_layout.addWidget(self.settings_scroll, 1)

        footer = QFrame()
        footer.setObjectName("SettingsFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(12)
        save_hint = QLabel("设置只会在点击保存后写入 config.json")
        save_hint.setObjectName("SettingsSaveHint")
        save_hint.setProperty("muted", True)
        footer_layout.addWidget(save_hint)
        footer_layout.addStretch(1)
        self.save_btn = QPushButton("保存设置")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.setProperty("variant", "primary")
        self.save_btn.setMinimumWidth(120)
        self.save_btn.clicked.connect(self.save_config)
        footer_layout.addWidget(self.save_btn)
        main_layout.addWidget(footer)

        self.restart_enabled_checkbox.stateChanged.connect(
            self.on_restart_enabled_changed
        )
        self.background_enabled_checkbox.stateChanged.connect(
            self._on_background_enabled_changed
        )
        self.background_browse_btn.clicked.connect(self.choose_background_image)
        self.background_clear_btn.clicked.connect(self.clear_background_image)
        self.background_opacity_slider.valueChanged.connect(
            self._on_background_opacity_changed
        )
        self._sync_background_controls()
        self.on_restart_enabled_changed()

        self.setTabOrder(self.min_drag_input, self.max_drag_input)
        if EXPERIMENTAL_MAA_RECOGNITION_ENABLED:
            self.setTabOrder(self.max_drag_input, self.recognition_combo)
            self.setTabOrder(self.recognition_combo, self.background_enabled_checkbox)
        else:
            self.setTabOrder(self.max_drag_input, self.background_enabled_checkbox)
        self.setTabOrder(self.background_enabled_checkbox, self.background_browse_btn)
        self.setTabOrder(self.background_browse_btn, self.background_clear_btn)
        self.setTabOrder(self.background_clear_btn, self.background_opacity_slider)
        self.setTabOrder(self.background_opacity_slider, self.restart_enabled_checkbox)
        self.setTabOrder(self.restart_enabled_checkbox, self.restart_time_input)
        self.setTabOrder(self.restart_time_input, self.restart_count_input)
        self.setTabOrder(self.restart_count_input, self.runtime_limit_input)
        self.setTabOrder(self.runtime_limit_input, self.strategy_combo)
        self.setTabOrder(self.strategy_combo, self.strategy_help_btn)
        self.setTabOrder(self.strategy_help_btn, self.save_btn)

    def _read_drag_range(self) -> Tuple[float, float]:
        drag_range = self.config_data.get("game", {}).get(
            "human_like_drag_duration_range", [0.10, 0.13]
        )
        try:
            return float(drag_range[0]), float(drag_range[1])
        except (IndexError, TypeError, ValueError):
            return 0.10, 0.13

    def _load_run_values(self) -> None:
        auto_restart_config = self.config_data.get("auto_restart", {})
        self.auto_restart_enabled = bool(auto_restart_config.get("enabled", True))
        try:
            self.stage_timeout = int(
                auto_restart_config.get("stage_timeout", 300)
            ) // 60
        except (TypeError, ValueError):
            self.stage_timeout = 5
        if self.stage_timeout <= 0:
            self.stage_timeout = 5
        try:
            self.max_restarts = int(auto_restart_config.get("max_restarts", 3))
        except (TypeError, ValueError):
            self.max_restarts = 3

        run_settings = self.config_data.get("run_settings", {})
        if not isinstance(run_settings, dict):
            run_settings = {}
        try:
            self.max_run_duration_minutes = int(
                run_settings.get("max_run_duration", 0) or 0
            ) // 60
        except (TypeError, ValueError):
            self.max_run_duration_minutes = 0
        try:
            self.target_wins = max(
                0,
                int(run_settings.get("target_wins", 0) or 0),
            )
        except (TypeError, ValueError):
            self.target_wins = 0

    def _load_background_values(self) -> None:
        ui_config = self.config_data.get("ui", {})
        if not isinstance(ui_config, dict):
            ui_config = {}
        background = ui_config.get("custom_background", {})
        if not isinstance(background, dict):
            background = {}
        self.background_enabled = bool(background.get("enabled", False))
        self.background_path = resolve_background_path(background.get("path", ""))
        self.background_opacity = clamp_background_opacity(
            background.get("opacity", BACKGROUND_OPACITY_DEFAULT)
        )

    def _sync_background_controls(self) -> None:
        self.background_enabled_checkbox.blockSignals(True)
        self.background_enabled_checkbox.setChecked(self.background_enabled)
        self.background_enabled_checkbox.blockSignals(False)
        self.background_opacity_slider.blockSignals(True)
        self.background_opacity_slider.setValue(self.background_opacity)
        self.background_opacity_slider.blockSignals(False)
        self.background_path_input.setText(
            os.path.normpath(self.background_path) if self.background_path else ""
        )
        self._on_background_opacity_changed(self.background_opacity)
        self._on_background_enabled_changed()
        self._update_background_preview()

    def _background_is_valid(self) -> bool:
        return bool(
            self.background_path
            and os.path.isfile(self.background_path)
            and not QPixmap(self.background_path).isNull()
        )

    def _update_background_preview(self) -> None:
        if not self._background_is_valid():
            self.background_preview.clear()
            self.background_preview.setText(
                "背景文件不可用" if self.background_path else "未选择背景"
            )
            return
        self.background_preview.setText("")
        self.background_preview.setPixmap(
            render_background_preview(
                self.background_path,
                self.background_preview.size(),
                self.background_opacity_slider.value(),
            )
        )

    def _on_background_enabled_changed(self, *_args) -> None:
        has_path = bool(self.background_path)
        active = self.background_enabled_checkbox.isChecked() and has_path
        self.background_opacity_slider.setEnabled(active)
        self.background_clear_btn.setEnabled(has_path)

    def _on_background_opacity_changed(self, value: int) -> None:
        self.background_opacity = clamp_background_opacity(value)
        self.background_opacity_value.setText(f"{self.background_opacity}%")
        self._update_background_preview()

    def _set_background_path(self, path: object) -> bool:
        resolved = resolve_background_path(path)
        if not resolved or not os.path.isfile(resolved) or QPixmap(resolved).isNull():
            return False
        self.background_path = resolved
        self.background_path_input.setText(os.path.normpath(resolved))
        self.background_enabled_checkbox.setChecked(True)
        self._on_background_enabled_changed()
        self._update_background_preview()
        return True

    def choose_background_image(self) -> None:
        start_dir = os.path.dirname(self.background_path) if self.background_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择自定义背景",
            start_dir,
            "图片文件 (*.jpg *.jpeg *.png *.webp *.bmp);;所有文件 (*)",
        )
        if path and not self._set_background_path(path):
            QMessageBox.warning(self, "背景不可用", "无法读取所选图片，请选择其他文件。")

    def clear_background_image(self) -> None:
        self.background_path = ""
        self.background_path_input.clear()
        self.background_enabled_checkbox.setChecked(False)
        self._on_background_enabled_changed()
        self._update_background_preview()

    def _background_config(self) -> dict:
        enabled = self.background_enabled_checkbox.isChecked()
        if enabled and not self._background_is_valid():
            raise ValueError("启用自定义背景前，请先选择有效的图片文件")
        return {
            "enabled": enabled,
            "path": serialize_background_path(self.background_path),
            "opacity": clamp_background_opacity(
                self.background_opacity_slider.value()
            ),
        }

    def _create_section(
        self, title: str, description: str, object_name: str
    ) -> Tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName(object_name)
        panel.setProperty("card", True)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("SettingsSectionTitle")
        title_label.setProperty("heading", "section")
        description_label = QLabel(description)
        description_label.setObjectName("SettingsSectionDescription")
        description_label.setProperty("muted", True)
        description_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        return panel, layout

    @staticmethod
    def _configure_form_layout(layout: QGridLayout) -> None:
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(5)
        layout.setColumnMinimumWidth(0, 180)
        layout.setColumnMinimumWidth(1, 180)
        layout.setColumnStretch(3, 1)

    def _create_line_edit(self, text: str, object_name: str) -> QLineEdit:
        line_edit = QLineEdit(text)
        line_edit.setObjectName(object_name)
        line_edit.setMaximumWidth(220)
        line_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return line_edit

    @staticmethod
    def _add_form_row(
        layout: QGridLayout,
        row: int,
        label_text: str,
        editor: QWidget,
        unit_text: str,
        hint_text: str,
    ) -> None:
        label = QLabel(label_text)
        label.setObjectName("SettingsFieldLabel")
        unit = QLabel(unit_text)
        unit.setObjectName("SettingsUnitLabel")
        unit.setProperty("muted", True)
        hint = QLabel(hint_text)
        hint.setObjectName("SettingsFieldHint")
        hint.setProperty("dim", True)
        hint.setWordWrap(True)
        layout.addWidget(label, row, 0)
        layout.addWidget(editor, row, 1)
        layout.addWidget(unit, row, 2)
        layout.addWidget(hint, row + 1, 1, 1, 3)

    def _go_back(self) -> None:
        try:
            sw = getattr(self.parent_widget, "stacked_widget", None)
            if sw is not None and hasattr(sw, "setCurrentIndex"):
                sw.setCurrentIndex(0)
        except Exception:
            pass

    def on_restart_enabled_changed(self, *_args):
        """处理自动重启功能启用/禁用状态变化"""

        self.restart_time_input.setEnabled(self.restart_enabled_checkbox.isChecked())
        self.restart_count_input.setEnabled(self.restart_enabled_checkbox.isChecked())

    def show_strategy_help(self):
        """显示换牌策略说明"""

        help_text = """
换牌策略说明：

【3费档次】
• 最优：前三张牌组合为 [1,2,3]
• 次优：牌序为2，3
• 目标：确保3费时能准时打出

【4费档次】
• 最优：四张牌组合为 [1,2,3,4]
• 次优：牌序为 [2,3,4] 或 [2,2,4]
• 目标：确保4费时能有效展开

【5费档次】
• 优先级组合（从高到低）：
[2,3,4,5] > [2,3,3,5] > [2,2,3,5] > [2,2,2,5]
• 目标：确保5费时能打出关键牌
"""
        msg = QMessageBox()
        msg.setWindowTitle("换牌策略说明")
        msg.setText(help_text)
        msg.setIcon(QMessageBox.Information)
        msg.exec_()

    def load_config(self):
        """加载配置文件"""
        config_path = get_config_path()
        cfg, _, _ = ConfigRepository(config_path).load_existing(allow_default_on_error=True)
        return cfg if isinstance(cfg, dict) else {}

    def save_config(self):
        """保存配置到文件"""

        try:
            if getattr(self.parent_widget, "is_script_running", lambda: False)():
                QMessageBox.warning(
                    self,
                    "运行中",
                    "脚本运行中，禁止修改配置。请先停止脚本后再保存。",
                )
                return
        except Exception:
            pass

        try:
            min_drag = float(self.min_drag_input.text())
            max_drag = float(self.max_drag_input.text())

            if min_drag < 0 or max_drag < 0:
                raise ValueError("拖拽时间不能为负数")
            if min_drag > max_drag:
                raise ValueError("最小拖拽时间不能大于最大拖拽时间")

            if "game" not in self.config_data:
                self.config_data["game"] = {}
            self.config_data["game"]["human_like_drag_duration_range"] = [min_drag, max_drag]
        except Exception as e:
            QMessageBox.warning(self, "输入错误", f"拖拽时间设置错误: {str(e)}")
            return

        try:
            if "auto_restart" not in self.config_data:
                self.config_data["auto_restart"] = {}
            self.config_data["auto_restart"]["enabled"] = self.restart_enabled_checkbox.isChecked()

            if self.restart_enabled_checkbox.isChecked():
                restart_time = int(self.restart_time_input.text())
                if restart_time < 1 or restart_time > 120:
                    raise ValueError("自动重启时间必须在1-120分钟之间")
                self.config_data["auto_restart"]["stage_timeout"] = restart_time * 60

                max_restarts = int(self.restart_count_input.text())
                if max_restarts < 1 or max_restarts > 20:
                    raise ValueError("自动重启最大次数必须在1-20之间")
                self.config_data["auto_restart"]["max_restarts"] = max_restarts

            self.config_data["auto_restart"].pop("output_timeout", None)
            self.config_data["auto_restart"].pop("match_timeout", None)

            if "stage_timeout" not in self.config_data["auto_restart"]:
                self.config_data["auto_restart"]["stage_timeout"] = 300
            if "max_restarts" not in self.config_data["auto_restart"]:
                self.config_data["auto_restart"]["max_restarts"] = 3
        except Exception as e:
            QMessageBox.warning(self, "输入错误", f"自动重启设置错误: {str(e)}")
            return

        try:
            runtime_limit = int(self.runtime_limit_input.text())
            if runtime_limit < 0 or runtime_limit > 10080:
                raise ValueError("脚本运行总时长必须在0-10080分钟之间")
            if "run_settings" not in self.config_data:
                self.config_data["run_settings"] = {}
            self.config_data["run_settings"]["max_run_duration"] = runtime_limit * 60
            target_wins = int(self.target_wins_input.text())
            if target_wins < 0 or target_wins > 9999:
                raise ValueError("目标胜利场数必须在0-9999之间")
            self.config_data["run_settings"]["target_wins"] = target_wins
            self.config_data["run_settings"].pop("max_battle_count", None)
            self.config_data["run_settings"].pop("force_close", None)
        except Exception as e:
            QMessageBox.warning(self, "输入错误", f"运行停止条件设置错误: {str(e)}")
            return

        strategy = self.strategy_combo.currentText()
        if "game" not in self.config_data:
            self.config_data["game"] = {}
        self.config_data["game"]["card_replacement_strategy"] = strategy

        recognition_config = self.config_data.get("recognition")
        if not isinstance(recognition_config, dict):
            recognition_config = {}
            self.config_data["recognition"] = recognition_config
        recognition_config["backend"] = (
            str(self.recognition_combo.currentData() or "legacy")
            if EXPERIMENTAL_MAA_RECOGNITION_ENABLED
            else "legacy"
        )
        recognition_config.setdefault("maa_model_dir", "models/maa_ocr")
        recognition_config.setdefault("maa_threshold", 0.3)
        recognition_config.setdefault("page_text_fallback", True)

        try:
            if "ui" not in self.config_data or not isinstance(self.config_data["ui"], dict):
                self.config_data["ui"] = {}
            self.config_data["ui"]["custom_background"] = self._background_config()
        except ValueError as e:
            QMessageBox.warning(self, "背景设置错误", str(e))
            return

        config_path = get_config_path()
        try:
            repo = ConfigRepository(config_path)
            res = repo.update(self.config_data, indent=4, ensure_ascii=False)
            if not res.ok:
                raise RuntimeError(res.error or "config write failed")

            if res.parse_ok:
                QMessageBox.information(self, "成功", "配置已保存！")
            else:
                QMessageBox.information(self, "成功", "配置已保存（原config.json解析失败，已重建）")
            self.config_saved.emit(dict(self.config_data))
            try:
                log_output = getattr(self.parent_widget, "log_output", None)
                if log_output is not None and hasattr(log_output, "append"):
                    log_output.append("[配置] 参数设置已更新")
            except Exception:
                pass
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存配置文件时出错: {str(e)}")

    def refresh_config_display(self):
        """刷新整个配置页面的显示"""

        self.config_data = self.load_config()

        drag_range = self._read_drag_range()
        self.min_drag_input.setText(str(drag_range[0]))
        self.max_drag_input.setText(str(drag_range[1]))

        self._load_run_values()
        self.restart_enabled_checkbox.setChecked(self.auto_restart_enabled)
        self.restart_time_input.setText(str(self.stage_timeout))
        self.restart_count_input.setText(str(self.max_restarts))
        self.runtime_limit_input.setText(str(self.max_run_duration_minutes))
        self.target_wins_input.setText(str(self.target_wins))
        self.on_restart_enabled_changed()

        self._load_background_values()
        self._sync_background_controls()

        current_strategy = self.config_data.get("game", {}).get(
            "card_replacement_strategy", "3费档次"
        )
        index = self.strategy_combo.findText(current_strategy)
        if index >= 0:
            self.strategy_combo.setCurrentIndex(index)

        recognition_config = self.config_data.get("recognition", {})
        recognition_backend = "legacy"
        if EXPERIMENTAL_MAA_RECOGNITION_ENABLED:
            recognition_backend = str(
                recognition_config.get("backend", "legacy")
                if isinstance(recognition_config, dict)
                else "legacy"
            ).strip().lower()
        recognition_index = self.recognition_combo.findData(recognition_backend)
        self.recognition_combo.setCurrentIndex(max(0, recognition_index))
        return
