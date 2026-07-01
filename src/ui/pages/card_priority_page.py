#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Card priority and mode options page."""

from __future__ import annotations

import json
import os

from typing import Any

from PyQt5.QtCore import Qt as _Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.config.paths import get_config_path
from src.config.paths import get_card_cost_dir
from src.config.config_repository import ConfigRepository
from src.config.effects_registry import get_triggers
from src.utils.card_filename import (
    is_evo_card_name,
    make_enhance_key,
    normalize_card_base_name,
    normalize_config_key,
    parse_card_filename,
)


# PyQt5 stubs vary across environments; keep Qt attribute access flexible.
Qt: Any = _Qt


class CardPriorityPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget: Any = parent
        self.config_data = self.load_config()
        self.card_widgets = []
        # Enhance rows share evolve priority with the base card row.
        self._base_evolve_priority_inputs = {}
        self._enhance_evolve_priority_views = {}
        self.init_ui()

    def _sync_enhance_evolve_priority_views(self, base_name: str, text: str) -> None:
        views = self._enhance_evolve_priority_views.get(str(base_name), [])
        for v in list(views):
            try:
                v.setText(text)
            except Exception:
                pass

    def init_ui(self):
        self.setObjectName("CardPriorityPage")
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        title_label = QLabel("卡牌设置")
        title_label.setStyleSheet("font-size: 20px; color: #88AAFF; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # 说明文字和帮助按钮
        desc_layout = QHBoxLayout()
        desc_label = QLabel(
            "为卡组中的卡片设置优先级、进化优先级与留牌。特殊效果/特殊交互请点击右侧“特殊效果...”进入二级编辑器。"
        )
        desc_label.setStyleSheet("font-size: 12px; color: #AACCFF;")
        desc_layout.addWidget(desc_label)
        desc_layout.addStretch()
        self.help_btn = QPushButton("帮助")
        self.help_btn.clicked.connect(self.show_card_settings_help)
        desc_layout.addWidget(self.help_btn)
        main_layout.addLayout(desc_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_area.setWidget(self.scroll_content)
        self.scroll_content.setObjectName("ScrollContent")
        main_layout.addWidget(self.scroll_area)

        # 设置滚动区域样式与主窗口一致
        self.scroll_area.setStyleSheet(
            """
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QWidget#ScrollContent {
                background-color: transparent;
            }
        """
        )
        self.scroll_content.setObjectName("ScrollContent")

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存设置")
        self.save_btn.clicked.connect(self.save_config)
        self.back_btn = QPushButton("返回主界面")
        self.back_btn.clicked.connect(self._go_back)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.back_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        self.load_card_priority_settings()

    def _go_back(self) -> None:
        try:
            sw = getattr(self.parent_widget, "stacked_widget", None)
            if sw is not None and hasattr(sw, "setCurrentIndex"):
                sw.setCurrentIndex(0)
        except Exception:
            pass

    def _build_effects_tag(self, base_name: str, config_key: str, is_enhance: bool) -> str:
        try:
            from src.config.strategy_effects import get_card_effect_steps
        except Exception:
            return ""

        tags = []
        for t in get_triggers():
            tid = str(t.get("id") or "")
            short = str(t.get("short") or tid)
            if not tid:
                continue

            # on_play is keyed by hand-card config key (enhance-aware);
            # follower triggers are keyed by base follower name.
            if tid == "on_play":
                key = str(config_key or base_name)
            else:
                if is_enhance:
                    continue
                key = str(base_name)

            steps = get_card_effect_steps(self.config_data, card_name=key, trigger=tid)
            if steps:
                tags.append(short)

        return "/".join(tags)

    def open_effects_editor(
        self, base_name: str, config_key: str, display_name: str, is_enhance: bool
    ) -> None:
        try:
            from src.ui.pages.card_effects_editor import CardEffectsDialog
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开特殊效果编辑器: {str(e)}")
            return

        dlg = CardEffectsDialog(
            self,
            base_name=str(base_name or ""),
            config_key=str(config_key or base_name or ""),
            display_name=str(display_name or base_name or ""),
            is_enhance=bool(is_enhance),
            deck_card_names=self._current_deck_card_names(),
        )
        res = dlg.exec_()
        if res == QDialog.Accepted:
            self.refresh_card_priority()

    def _current_deck_card_names(self) -> list:
        names = []
        seen = set()
        for card in getattr(self, "card_widgets", []) or []:
            if not isinstance(card, dict) or bool(card.get("is_enhance")):
                continue
            name = str(card.get("card_name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        if names:
            return names

        for name in (getattr(self, "config_data", {}) or {}).get("high_priority_cards", {}).keys():
            base = str(name or "").split("_enhance_", 1)[0].strip()
            if base and base not in seen:
                seen.add(base)
                names.append(base)
        return names

    def show_card_settings_help(self):
        """显示卡牌设置帮助"""
        help_text = """
卡牌设置详细说明

一、优先级设置

1. 出牌优先级（进化前/进化后）
   作用：控制出牌顺序，会根据进化是否解锁切换不同阶段的优先级
   数值含义：数字越小优先级越高
   默认值：999（最低优先级）
   示例：若“进化前=1、进化后=5”，则前期更倾向优先打出；进化解锁后优先级会降低

2. 进化优先级
   作用：控制进化/超进化时的选择顺序
   数值含义：数字越小优先级越高
   默认值：999（最低优先级）
   示例：进化时会优先选择进化优先级更高（数字更小）的随从

二、模式选项设置

二、留牌与特殊效果

1. 必留(force_keep)
   作用：换牌阶段强制保留该基础卡（爆能档位共用）。

2. 特殊效果...
   作用：进入二级编辑器，按触发时机配置操作（出牌/攻击/进化/超进化）。
   说明：爆能档位行也可配置攻击/进化等触发，作为该爆能档位专属效果。
"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("卡牌设置帮助")
        msg_box.setText(help_text)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.addButton(QMessageBox.Ok)

        msg_box.setStyleSheet(
            """
            QMessageBox {
                background-color: white;
            }
            QMessageBox QLabel {
                color: black;
                font-size: 12px;
            }
            QPushButton {
                background-color: #4A4A7F;
                color: white;
                border-radius: 5px;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #5A5A8F;
            }
        """
        )

        msg_box.exec_()

    def load_config(self):
        config_path = get_config_path()
        cfg, _, _ = ConfigRepository(config_path).load_existing(allow_default_on_error=True)
        return cfg if isinstance(cfg, dict) else {}

    def load_card_priority_settings(self):
        # 清空现有内容
        for i in reversed(range(self.scroll_layout.count())):
            item = self.scroll_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.card_widgets = []
        self._base_evolve_priority_inputs = {}
        self._enhance_evolve_priority_views = {}

        card_dir = get_card_cost_dir(ensure=True)
        if not os.path.exists(card_dir):
            no_card_label = QLabel("未找到卡组卡片，请先在'卡组选择'页面选择卡片")
            no_card_label.setStyleSheet("color: #FF8888; font-size: 14px;")
            no_card_label.setAlignment(Qt.AlignCenter)
            self.scroll_layout.addWidget(no_card_label)
            return

        card_files = [
            f
            for f in os.listdir(card_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            and not is_evo_card_name(f)
        ]
        if not card_files:
            no_card_label = QLabel("没有找到卡片，请先在'卡组选择'页面选择卡片")
            no_card_label.setStyleSheet("color: #FF8888; font-size: 14px;")
            no_card_label.setAlignment(Qt.AlignCenter)
            self.scroll_layout.addWidget(no_card_label)
            return

        # Build display entries (base + enhance tiers) from filenames.
        entries = []
        for card_file in card_files:
            try:
                base_cost, enhance_costs, base_name = parse_card_filename(card_file)
            except Exception:
                base_cost, enhance_costs, base_name = 0, [], card_file.split("_", 1)[-1].rsplit(".", 1)[0]

            base_name = normalize_card_base_name(str(base_name or "").strip())
            if not base_name:
                continue
            enhance_costs = list(enhance_costs or [])

            entries.append(
                {
                    "file": card_file,
                    "base_name": base_name,
                    "config_key": normalize_config_key(base_name),
                    "base_cost": int(base_cost or 0),
                    "variant_cost": int(base_cost or 0),
                    "is_enhance": False,
                    "enhance_costs": enhance_costs,
                }
            )
            for c in enhance_costs:
                entries.append(
                    {
                        "file": card_file,
                        "base_name": base_name,
                        "config_key": normalize_config_key(make_enhance_key(base_name, c)),
                        "base_cost": int(base_cost or 0),
                        "variant_cost": int(c),
                        "is_enhance": True,
                        "enhance_costs": enhance_costs,
                    }
                )

        entries.sort(
            key=lambda e: (
                int(e.get("base_cost", 0)),
                str(e.get("base_name", "")),
                1 if bool(e.get("is_enhance")) else 0,
                int(e.get("variant_cost", 0)),
            )
        )

        for entry in entries:
            card_file = entry["file"]
            base_name = entry["base_name"]
            config_key = entry["config_key"]
            is_enhance = bool(entry.get("is_enhance"))
            variant_cost = int(entry.get("variant_cost", 0))

            card_row = QWidget()
            card_row.setStyleSheet(
                "background-color: rgba(60, 60, 90, 150); border-radius: 10px;"
            )
            row_layout = QHBoxLayout(card_row)
            row_layout.setContentsMargins(10, 5, 10, 5)

            card_label = QLabel()
            card_path = os.path.join(card_dir, card_file)
            pixmap = QPixmap(card_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(80, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                card_label.setPixmap(pixmap)
            card_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(card_label)

            if is_enhance:
                display_name = f"{base_name} (爆能{variant_cost})"
            else:
                display_name = f"{base_name}"

            name_label = QLabel(display_name)
            name_label.setStyleSheet("color: #FFFFFF; font-weight: bold; min-width: 140px;")
            name_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(name_label)

            # 出牌优先级（进化前/进化后） - key is base or enhance-variant.
            high_priority = self.config_data.get("high_priority_cards", {}).get(config_key, {})

            row_layout.addWidget(QLabel("出牌(进化前):"))
            play_priority_pre_input = QLineEdit()
            play_priority_pre_input.setStyleSheet(
                "background-color: rgba(80, 80, 120, 180); color: white;"
            )
            play_priority_pre_input.setMaximumWidth(50)
            if isinstance(high_priority, dict):
                pre_priority = high_priority.get(
                    "priority_pre_evolution", high_priority.get("priority", "")
                )
                play_priority_pre_input.setText(str(pre_priority) if pre_priority != "" else "")
            row_layout.addWidget(play_priority_pre_input)

            row_layout.addWidget(QLabel("出牌(进化后):"))
            play_priority_post_input = QLineEdit()
            play_priority_post_input.setStyleSheet(
                "background-color: rgba(80, 80, 120, 180); color: white;"
            )
            play_priority_post_input.setMaximumWidth(50)
            if isinstance(high_priority, dict):
                post_priority = high_priority.get(
                    "priority_post_evolution", high_priority.get("priority", "")
                )
                play_priority_post_input.setText(
                    str(post_priority) if post_priority != "" else ""
                )
            row_layout.addWidget(play_priority_post_input)

            force_keep_checkbox = None
            evolve_priority_input = None
            evolve_priority_view = None

            if not is_enhance:
                # 强制留牌（仅基础卡）
                row_layout.addWidget(QLabel("必留:"))
                force_keep_checkbox = QCheckBox()
                force_keep_checkbox.setStyleSheet(
                    "QCheckBox::indicator { width: 18px; height: 18px; }"
                )
                base_cfg = self.config_data.get("high_priority_cards", {}).get(base_name, {})
                if isinstance(base_cfg, dict) and base_cfg.get("force_keep") is True:
                    force_keep_checkbox.setChecked(True)
                row_layout.addWidget(force_keep_checkbox)

                # 进化优先级（仅基础卡）
                row_layout.addWidget(QLabel("进化优先级:"))
                evolve_priority_input = QLineEdit()
                evolve_priority_input.setStyleSheet(
                    "background-color: rgba(80, 80, 120, 180); color: white;"
                )
                evolve_priority_input.setMaximumWidth(50)
                evolve_priority = self.config_data.get("evolve_priority_cards", {}).get(
                    base_name, {}
                )
                if isinstance(evolve_priority, dict):
                    evolve_priority_input.setText(str(evolve_priority.get("priority", "")))
                row_layout.addWidget(evolve_priority_input)

                # Keep enhance rows in sync with this base evolve priority input.
                self._base_evolve_priority_inputs[base_name] = evolve_priority_input
                evolve_priority_input.textChanged.connect(
                    lambda text, n=base_name: self._sync_enhance_evolve_priority_views(n, text)
                )

            else:
                # 爆能档位不支持独立进化优先级（进化按随从名判定）。这里显示共用值，避免误解。
                row_layout.addWidget(QLabel("进化优先级(共用):"))
                evolve_priority_view = QLineEdit()
                evolve_priority_view.setStyleSheet(
                    "background-color: rgba(80, 80, 120, 120); color: white;"
                )
                evolve_priority_view.setMaximumWidth(50)
                evolve_priority_view.setReadOnly(True)
                evolve_priority_view.setToolTip("进化优先级按随从名共用，请在基础卡行设置")
                evolve_priority = self.config_data.get("evolve_priority_cards", {}).get(
                    base_name, {}
                )
                if isinstance(evolve_priority, dict):
                    evolve_priority_view.setText(str(evolve_priority.get("priority", "")))
                row_layout.addWidget(evolve_priority_view)

                self._enhance_evolve_priority_views.setdefault(base_name, []).append(
                    evolve_priority_view
                )
                try:
                    base_input = self._base_evolve_priority_inputs.get(base_name)
                    if base_input is not None:
                        evolve_priority_view.setText(base_input.text())
                except Exception:
                    pass

            # Step3A: special effects go to a 2nd-level editor.
            effects_tag = self._build_effects_tag(base_name, config_key, is_enhance)
            tag_label = QLabel(effects_tag if effects_tag else "")
            tag_label.setStyleSheet("color: #AACCFF; font-size: 11px; min-width: 80px;")
            tag_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(tag_label)

            effects_btn = QPushButton("特殊效果...")
            effects_btn.setStyleSheet(
                "background-color: rgba(80, 80, 120, 180); color: white;"
            )
            effects_btn.setMaximumWidth(90)
            effects_btn.clicked.connect(
                lambda _=False,
                b=base_name,
                k=config_key,
                d=display_name,
                enh=is_enhance: self.open_effects_editor(b, k, d, enh)
            )
            row_layout.addWidget(effects_btn)

            self.card_widgets.append(
                {
                    "card_name": base_name,
                    "config_key": config_key,
                    "is_enhance": is_enhance,
                    "play_priority_pre": play_priority_pre_input,
                    "play_priority_post": play_priority_post_input,
                    "force_keep": force_keep_checkbox,
                    "evolve_priority": evolve_priority_input,
                    "evolve_priority_view": evolve_priority_view if is_enhance else None,
                }
            )

            self.scroll_layout.addWidget(card_row)

        self.scroll_layout.addStretch()

    def refresh_card_priority(self):
        # 重新加载配置文件
        self.config_data = self.load_config()
        # 重新加载卡牌优先级设置
        self.load_card_priority_settings()

    def save_config(self):
        try:
            if getattr(self.parent_widget, "is_script_running", lambda: False)():
                QMessageBox.warning(
                    self,
                    "运行中",
                    "脚本运行中，禁止修改卡牌设置/配置。请先停止脚本后再保存。",
                )
                return
        except Exception:
            pass

        # 仅保存卡牌优先级部分，合并磁盘上的其余配置
        high_priority_cards = {}
        evolve_priority_cards = {}
        for card in self.card_widgets:
            base_name = card.get("card_name", "")
            config_key = normalize_config_key(str(card.get("config_key") or base_name))
            is_enhance = bool(card.get("is_enhance"))

            name_for_msg = str(config_key or base_name)
            if is_enhance:
                try:
                    _b, _c = str(config_key).rsplit("@", 1)
                    if str(_b) == str(base_name):
                        name_for_msg = f"{base_name}(爆能{_c})"
                except Exception:
                    name_for_msg = str(config_key or base_name)

            play_pre_text = card["play_priority_pre"].text().strip()
            play_post_text = card["play_priority_post"].text().strip()
            if play_pre_text or play_post_text:
                pre_val = None
                post_val = None
                if play_pre_text:
                    try:
                        pre_val = int(play_pre_text)
                        if pre_val < 0 or pre_val > 999:
                            raise ValueError("优先级必须在0-999之间")
                    except Exception as e:
                        QMessageBox.warning(
                            self,
                            "输入错误",
                            f"卡片 '{name_for_msg}' 的出牌优先级(进化前)设置错误: {str(e)}",
                        )
                        return
                if play_post_text:
                    try:
                        post_val = int(play_post_text)
                        if post_val < 0 or post_val > 999:
                            raise ValueError("优先级必须在0-999之间")
                    except Exception as e:
                        QMessageBox.warning(
                            self,
                            "输入错误",
                            f"卡片 '{name_for_msg}' 的出牌优先级(进化后)设置错误: {str(e)}",
                        )
                        return

                # 只填了一个阶段时，默认另一阶段同值，避免出现999导致策略异常
                if pre_val is None and post_val is not None:
                    pre_val = post_val
                if post_val is None and pre_val is not None:
                    post_val = pre_val

                high_priority_cards[config_key] = {
                    "priority_pre_evolution": pre_val,
                    "priority_post_evolution": post_val,
                }

            # 强制留牌（仅基础卡）
            try:
                force_keep_widget = card.get("force_keep")
                force_keep_checked = bool(
                    force_keep_widget is not None and force_keep_widget.isChecked()
                )
            except Exception:
                force_keep_checked = False

            if force_keep_checked:
                base_cfg = high_priority_cards.get(base_name)
                if not isinstance(base_cfg, dict):
                    base_cfg = {}
                    high_priority_cards[base_name] = base_cfg
                base_cfg["force_keep"] = True

            # 进化优先级（仅基础卡；爆能档位不单独配置）
            evolve_widget = card.get("evolve_priority")
            if evolve_widget is not None:
                evolve_priority_text = evolve_widget.text().strip()
                if evolve_priority_text:
                    try:
                        priority = int(evolve_priority_text)
                        if priority < 0 or priority > 999:
                            raise ValueError("优先级必须在0-999之间")
                        evolve_priority_cards[base_name] = {"priority": priority}
                    except Exception as e:
                        QMessageBox.warning(
                            self,
                            "输入错误",
                            f"卡片 '{base_name}' 的进化优先级设置错误: {str(e)}",
                        )
                        return

        config_path = get_config_path()
        repo = ConfigRepository(config_path)
        existing, parse_ok, parse_err = repo.load_existing(allow_default_on_error=False)
        if existing is None:
            QMessageBox.warning(
                self,
                "保存失败",
                f"config.json解析失败，已拒绝覆盖写入: {str(parse_err or '')}",
            )
            return

        if high_priority_cards:
            existing["high_priority_cards"] = high_priority_cards
        elif "high_priority_cards" in existing:
            del existing["high_priority_cards"]

        if evolve_priority_cards:
            existing["evolve_priority_cards"] = evolve_priority_cards
        elif "evolve_priority_cards" in existing:
            del existing["evolve_priority_cards"]

        try:
            res = repo.replace_with_snapshot(existing, indent=4, ensure_ascii=False)
            if not res.ok:
                raise RuntimeError(res.error or "config write failed")
            QMessageBox.information(self, "成功", "卡牌设置已保存！")
            try:
                log_output = getattr(self.parent_widget, "log_output", None)
                if log_output is not None and hasattr(log_output, "append"):
                    log_output.append("[配置] 卡牌设置已更新")
            except Exception:
                pass

            # 保存到当前卡组文件
            self._save_to_current_deck(high_priority_cards, evolve_priority_cards)

        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存卡牌设置失败: {str(e)}")

    def _save_to_current_deck(
        self, high_priority_cards: dict, evolve_priority_cards: dict
    ) -> None:
        """将优先级设置保存到当前卡组文件"""
        if not high_priority_cards and not evolve_priority_cards:
            return

        try:
            # 获取主窗口
            parent = self.parent_widget

            while parent:
                if hasattr(parent, "card_select_page"):
                    card_select_page = parent.card_select_page
                    break
                parent = getattr(parent, "parent_widget", None) or getattr(
                    parent, "parent", None
                )
            else:
                return

            # 获取当前选中的卡组文件（使用新的 current_deck_file 属性）
            deck_file = getattr(card_select_page, "current_deck_file", None)
            if not deck_file:
                return

            # 读取卡组文件
            decks_dir = os.path.join(os.path.dirname(get_config_path()), "saved_decks")
            deck_path = os.path.join(decks_dir, deck_file)

            if not os.path.exists(deck_path):
                return

            with open(deck_path, "r", encoding="utf-8") as f:
                deck_data = json.load(f)

            # 更新 strategy_config
            sc = deck_data.get("strategy_config")
            if not isinstance(sc, dict):
                sc = {}
                deck_data["strategy_config"] = sc

            # 保存高优先级卡牌
            if high_priority_cards:
                sc["high_priority_cards"] = high_priority_cards
            elif "high_priority_cards" in sc:
                del sc["high_priority_cards"]

            # 保存进化优先级
            if evolve_priority_cards:
                sc["evolve_priority_cards"] = evolve_priority_cards
            elif "evolve_priority_cards" in sc:
                del sc["evolve_priority_cards"]

            # 写回卡组文件
            with open(deck_path, "w", encoding="utf-8") as f:
                json.dump(deck_data, f, ensure_ascii=False, indent=2)

        except Exception:
            pass
