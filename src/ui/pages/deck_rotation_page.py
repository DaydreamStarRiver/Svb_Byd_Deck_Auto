"""Configure result-screen deck rotation without recognizing deck artwork."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config.config_repository import ConfigRepository
from src.config.paths import get_config_path


class DeckRotationPage(QWidget):
    config_saved = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget: Any = parent
        self.deck_store = getattr(parent, "deck_store", None)
        self.slot_profile_combos: dict[int, QComboBox] = {}
        self._build_ui()
        if self.deck_store is not None:
            try:
                self.deck_store.decks_changed.connect(self.refresh_saved_decks)
            except Exception:
                pass
        self.refresh_config_display()

    @staticmethod
    def _panel(title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setProperty("card", True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setProperty("heading", "section")
        hint = QLabel(description)
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(hint)
        return panel, layout

    def _build_ui(self) -> None:
        self.setObjectName("DeckRotationPage")
        self.setProperty("pageRoot", True)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)

        title = QLabel("卡组轮换")
        title.setObjectName("PageTitle")
        subtitle = QLabel("按已完成对局数，在结算页自动切换九宫格中的牌组槽位")
        subtitle.setProperty("muted", True)
        root.addWidget(title)
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setProperty("pageRoot", True)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(12)

        basic, basic_layout = self._panel(
            "轮换规则",
            "只统计明确识别到胜利或失败的完整对局；未判定和中途停止不计数。",
        )
        self.enabled_check = QCheckBox("启用自动卡组轮换")
        basic_layout.addWidget(self.enabled_check)
        self.switch_on_start_check = QCheckBox(
            "启动后先同步到序列首项（确保游戏卡组与脚本构筑一致）"
        )
        self.switch_on_start_check.setChecked(True)
        basic_layout.addWidget(self.switch_on_start_check)
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.addWidget(QLabel("每完成"), 0, 0)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 999)
        self.interval_spin.setSuffix(" 局")
        form.addWidget(self.interval_spin, 0, 1)
        form.addWidget(QLabel("切换一次卡组"), 0, 2)
        form.addWidget(QLabel("使用方式"), 1, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("按序循环", "cycle")
        self.mode_combo.addItem("按序执行一轮", "once")
        self.mode_combo.addItem("独立随机（允许连续重复）", "random")
        form.addWidget(self.mode_combo, 1, 1, 1, 2)
        form.addWidget(QLabel("切换失败"), 2, 0)
        self.failure_combo = QComboBox()
        self.failure_combo.addItem("暂停脚本，等待人工处理（推荐）", "pause")
        self.failure_combo.addItem("退回结算页并跳过该槽位", "skip")
        self.failure_combo.addItem("退回结算页并保留该槽位", "continue")
        form.addWidget(self.failure_combo, 2, 1, 1, 2)
        basic_layout.addLayout(form)
        content_layout.addWidget(basic)

        sequence_panel, sequence_layout = self._panel(
            "游戏槽位与本地构筑",
            "每个九宫格槽位必须绑定一份“卡组构筑”中保存的本地构筑；切换时会同时更新卡图识别、出牌优先级、进化优先级和卡牌效果。",
        )
        grid = QGridLayout()
        grid.setSpacing(8)
        for slot in range(1, 10):
            cell = QFrame()
            cell.setProperty("card", True)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(8, 8, 8, 8)
            cell_layout.setSpacing(6)
            button = QPushButton(f"添加卡组 {slot} 到顺序")
            button.setMinimumHeight(36)
            button.clicked.connect(lambda checked=False, value=slot: self._append_slot(value))
            combo = QComboBox()
            combo.addItem("未绑定本地构筑", None)
            combo.currentIndexChanged.connect(self._update_summary)
            self.slot_profile_combos[slot] = combo
            cell_layout.addWidget(button)
            cell_layout.addWidget(combo)
            grid.addWidget(cell, (slot - 1) // 3, (slot - 1) % 3)
        sequence_layout.addLayout(grid)

        order_title = QLabel("牌组使用顺序")
        order_title.setProperty("heading", "section")
        sequence_layout.addWidget(order_title)
        body = QHBoxLayout()
        body.addStretch(1)
        sequence_side = QVBoxLayout()
        self.sequence_list = QListWidget()
        self.sequence_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.sequence_list.setDefaultDropAction(Qt.MoveAction)
        self.sequence_list.setMinimumHeight(190)
        sequence_side.addWidget(self.sequence_list)
        actions = QHBoxLayout()
        for label, callback in (
            ("上移", lambda: self._move_selected(-1)),
            ("下移", lambda: self._move_selected(1)),
            ("删除", self._remove_selected),
            ("清空", self.sequence_list.clear),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        sequence_side.addLayout(actions)
        body.addLayout(sequence_side, 1)
        body.addStretch(1)
        sequence_layout.addLayout(body)
        self.summary_label = QLabel("")
        self.summary_label.setProperty("muted", True)
        self.summary_label.setWordWrap(True)
        sequence_layout.addWidget(self.summary_label)
        content_layout.addWidget(sequence_panel)

        safety, safety_layout = self._panel(
            "执行说明",
            "固定坐标仅适用于 1280×720。空槽位、创建牌组入口或页面未识别都会按失败策略处理，不会继续盲点。",
        )
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(3, 30)
        self.timeout_spin.setSuffix(" 秒")
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel("页面切换等待时间"))
        timeout_row.addWidget(self.timeout_spin)
        timeout_row.addStretch(1)
        safety_layout.addLayout(timeout_row)
        content_layout.addWidget(safety)
        content_layout.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("设置在下次启动脚本时生效"))
        footer.addStretch(1)
        self.save_button = QPushButton("保存轮换设置")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self.save_config)
        footer.addWidget(self.save_button)
        root.addLayout(footer)

        self.sequence_list.model().rowsInserted.connect(self._update_summary)
        self.sequence_list.model().rowsRemoved.connect(self._update_summary)
        self.sequence_list.model().rowsMoved.connect(self._update_summary)
        self.enabled_check.toggled.connect(self._sync_enabled)
        self.mode_combo.currentIndexChanged.connect(self._update_summary)
        self.switch_on_start_check.toggled.connect(self._update_summary)

    def _append_slot(self, slot: int) -> None:
        item = QListWidgetItem(self._slot_item_text(slot))
        item.setData(Qt.UserRole, int(slot))
        self.sequence_list.addItem(item)

    def _slot_item_text(self, slot: int) -> str:
        combo = self.slot_profile_combos.get(int(slot))
        profile_name = combo.currentText() if combo is not None and combo.currentData() else "未绑定"
        return f"卡组 {slot} · {profile_name}"

    def _slot_profiles(self) -> dict[str, str]:
        profiles: dict[str, str] = {}
        for slot, combo in self.slot_profile_combos.items():
            filename = combo.currentData()
            if filename:
                profiles[str(slot)] = str(filename)
        return profiles

    def _sequence(self) -> list[int]:
        return [
            int(self.sequence_list.item(index).data(Qt.UserRole))
            for index in range(self.sequence_list.count())
        ]

    def _move_selected(self, delta: int) -> None:
        row = self.sequence_list.currentRow()
        target = row + int(delta)
        if row < 0 or target < 0 or target >= self.sequence_list.count():
            return
        item = self.sequence_list.takeItem(row)
        self.sequence_list.insertItem(target, item)
        self.sequence_list.setCurrentRow(target)
        self._update_summary()

    def _remove_selected(self) -> None:
        row = self.sequence_list.currentRow()
        if row >= 0:
            self.sequence_list.takeItem(row)
        self._update_summary()

    def _update_summary(self, *_args) -> None:
        sequence = self._sequence()
        for index in range(self.sequence_list.count()):
            item = self.sequence_list.item(index)
            slot = int(item.data(Qt.UserRole))
            item.setText(self._slot_item_text(slot))
        labels = [self._slot_item_text(slot).replace("卡组 ", "", 1) for slot in sequence]
        startup = "启动先同步首项" if self.switch_on_start_check.isChecked() else "启动时沿用当前卡组"
        mode = str(self.mode_combo.currentData() or "cycle")
        mode_hint = (
            "独立随机抽取，允许连续重复"
            if mode == "random"
            else ("按序执行一轮" if mode == "once" else "按序循环")
        )
        sequence_label = "随机候选" if mode == "random" else "使用顺序"
        self.summary_label.setText(
            f"{startup}；{mode_hint}；{sequence_label}："
            + (" → ".join(labels) if labels else "未设置")
        )

    def _sync_enabled(self, enabled: bool) -> None:
        self.interval_spin.setEnabled(enabled)
        self.mode_combo.setEnabled(enabled)
        self.failure_combo.setEnabled(enabled)
        self.timeout_spin.setEnabled(enabled)
        self.switch_on_start_check.setEnabled(enabled)
        for combo in self.slot_profile_combos.values():
            combo.setEnabled(enabled)

    def refresh_saved_decks(self) -> None:
        current = self._slot_profiles()
        decks = []
        if self.deck_store is not None:
            try:
                decks = self.deck_store.get_decks()
            except Exception:
                decks = []
        for slot, combo in self.slot_profile_combos.items():
            selected = current.get(str(slot))
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("未绑定本地构筑", None)
            for display_name, filename in decks:
                combo.addItem(str(display_name), str(filename))
            if selected:
                index = combo.findData(selected)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self._update_summary()

    def _load_slot_profiles(self, value: object) -> None:
        mapping = value if isinstance(value, dict) else {}
        self.refresh_saved_decks()
        for slot, combo in self.slot_profile_combos.items():
            filename = str(mapping.get(str(slot), mapping.get(slot, "")) or "")
            if not filename:
                continue
            index = combo.findData(filename)
            if index >= 0:
                combo.setCurrentIndex(index)

    def refresh_config_display(self) -> None:
        config, _, _ = ConfigRepository(get_config_path()).load_existing(
            allow_default_on_error=True
        )
        raw = config.get("deck_rotation", {}) if isinstance(config, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        self.enabled_check.setChecked(bool(raw.get("enabled", False)))
        self.switch_on_start_check.setChecked(bool(raw.get("switch_on_start", True)))
        self.interval_spin.setValue(int(raw.get("interval_matches", 5) or 5))
        self.timeout_spin.setValue(int(raw.get("page_timeout_seconds", 8) or 8))
        mode_index = self.mode_combo.findData(str(raw.get("mode", "cycle")))
        self.mode_combo.setCurrentIndex(max(0, mode_index))
        failure_index = self.failure_combo.findData(str(raw.get("failure_policy", "pause")))
        self.failure_combo.setCurrentIndex(max(0, failure_index))
        self._load_slot_profiles(raw.get("slot_profiles", {}))
        self.sequence_list.clear()
        for value in raw.get("sequence", [1, 2, 3]):
            try:
                slot = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= slot <= 9:
                self._append_slot(slot)
        self._update_summary()
        self._sync_enabled(self.enabled_check.isChecked())

    def save_config(self) -> None:
        if bool(getattr(self.parent_widget, "is_script_running", lambda: False)()):
            QMessageBox.warning(self, "运行中", "请先停止脚本，再修改卡组轮换设置。")
            return
        sequence = self._sequence()
        if self.enabled_check.isChecked() and not sequence:
            QMessageBox.warning(self, "序列为空", "启用轮换前至少添加一个卡组槽位。")
            return
        slot_profiles = self._slot_profiles()
        missing_slots = sorted(
            {slot for slot in sequence if str(slot) not in slot_profiles}
        )
        if self.enabled_check.isChecked() and missing_slots:
            QMessageBox.warning(
                self,
                "本地构筑未绑定",
                "请先为以下游戏槽位选择本地构筑："
                + ", ".join(str(slot) for slot in missing_slots),
            )
            return
        rotation = {
            "enabled": self.enabled_check.isChecked(),
            "interval_matches": self.interval_spin.value(),
            "sequence": sequence,
            "slot_profiles": slot_profiles,
            "switch_on_start": self.switch_on_start_check.isChecked(),
            "mode": str(self.mode_combo.currentData() or "cycle"),
            "failure_policy": str(self.failure_combo.currentData() or "pause"),
            "page_timeout_seconds": self.timeout_spin.value(),
        }
        result = ConfigRepository(get_config_path()).update(
            {"deck_rotation": rotation},
            refuse_on_parse_error=True,
            indent=4,
            ensure_ascii=False,
        )
        if not result.ok:
            QMessageBox.warning(self, "保存失败", result.error or "无法写入 config.json")
            return
        self.config_saved.emit({"deck_rotation": rotation})
        QMessageBox.information(self, "保存成功", "卡组轮换设置已保存。")
