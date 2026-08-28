"""Result-screen deck rotation for the fixed 1280x720 game layout."""

from __future__ import annotations

import copy
import json
import os
import random
import time
from typing import Any, Optional

import cv2
import numpy as np

from src.core.run_control import PauseRequested, StopRequested
from src.game.deck_profiles import DeckProfileError, RuntimeDeckProfileLoader
from src.game.template_manager import PAGE_TEXT_ALIASES
from src.ui.deck_io import apply_strategy_config


# 结算页“使用牌组”的卡组卡面中心。上方蓝色“确认”按钮只用于查看
# 当前构筑详情，不会进入更换牌组弹窗，不能点它。
RESULT_DECK_CARD = (839, 530)
DIALOG_DECK_BUTTON = (825, 370)
DIALOG_DECIDE_BUTTON = (766, 553)
DECK_GRID_POINTS = {
    1: (274, 285),
    2: (642, 285),
    3: (1009, 285),
    4: (274, 430),
    5: (642, 430),
    6: (1009, 430),
    7: (274, 573),
    8: (642, 573),
    9: (1009, 573),
}


def _normalized_sequence(value: object) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    sequence: list[int] = []
    for item in value:
        try:
            slot = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= slot <= 9:
            sequence.append(slot)
    return sequence[:100]


def _normalized_slot_profiles(value: object) -> dict[int, str]:
    if not isinstance(value, dict):
        return {}
    profiles: dict[int, str] = {}
    for key, filename in value.items():
        try:
            slot = int(key)
        except (TypeError, ValueError):
            continue
        safe_name = os.path.basename(str(filename or "").strip())
        if 1 <= slot <= 9 and safe_name and safe_name.casefold().endswith(".json"):
            profiles[slot] = safe_name
    return profiles


class DeckRotationController:
    """Per-device runtime cursor and guarded result-page switching workflow."""

    def __init__(self, device_state: Any, game_manager: Any):
        self.device_state = device_state
        self.game_manager = game_manager
        raw = device_state.config.get("deck_rotation", {})
        self.config = raw if isinstance(raw, dict) else {}
        self.enabled = bool(self.config.get("enabled", False))
        self.sequence = _normalized_sequence(self.config.get("sequence", ()))
        self.slot_profiles = _normalized_slot_profiles(
            self.config.get("slot_profiles", {})
        )
        self.switch_on_start = bool(self.config.get("switch_on_start", True))
        try:
            self.interval = max(1, min(999, int(self.config.get("interval_matches", 5))))
        except (TypeError, ValueError):
            self.interval = 5
        mode = str(self.config.get("mode", "cycle") or "cycle").strip().lower()
        self.mode = mode if mode in {"cycle", "once", "random"} else "cycle"
        policy = str(self.config.get("failure_policy", "pause") or "pause").strip().lower()
        self.failure_policy = policy if policy in {"pause", "skip", "continue"} else "pause"
        try:
            self.timeout = max(3.0, min(30.0, float(self.config.get("page_timeout_seconds", 8))))
        except (TypeError, ValueError):
            self.timeout = 8.0

        self.completed_since_switch = 0
        self.sequence_index = 0
        self.current_slot: Optional[int] = self._infer_active_slot()
        self.current_profile: Any = None
        self.last_slot: Optional[int] = self.current_slot
        self.pending_slot: Optional[int] = None
        self.exhausted = False
        self._state_signature = json.dumps(
            {
                "sequence": self.sequence,
                "slot_profiles": self.slot_profiles,
                "interval": self.interval,
                "mode": self.mode,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        restored_runtime = self._restore_runtime_state()
        self.profile_loader = RuntimeDeckProfileLoader()

        snapshot = self._active_snapshot()
        if snapshot and not str(
            getattr(self.device_state, "active_deck_file", "") or ""
        ).strip():
            self.device_state.set_active_deck_profile(
                slot=self.current_slot,
                filename=str(snapshot.get("deck_file") or ""),
                name=str(snapshot.get("name") or ""),
            )

        if bool(getattr(self.device_state, "runtime_deck_profile_active", False)):
            try:
                active_filename = str(
                    getattr(self.device_state, "active_deck_file", "") or ""
                )
                if active_filename:
                    active_profile = self.profile_loader.load(active_filename)
                    restored_config = apply_strategy_config(
                        self.device_state.config,
                        strategy_config=active_profile.strategy_config,
                    )
                    self.game_manager.set_runtime_deck_profile(active_profile)
                    self.current_profile = active_profile
                    self.device_state.config.clear()
                    self.device_state.config.update(restored_config)
                    self.device_state.logger.info(
                        "[卡组轮换] 设备重连后已恢复本地构筑[%s]",
                        active_profile.name,
                    )
            except Exception as exc:
                self.device_state.logger.error(
                    "[卡组轮换] 设备重连后恢复构筑失败: %s",
                    exc,
                )
                self.device_state.request_pause(reason="deck_profile_restore_failed")

        if self.enabled and not self.sequence:
            self.device_state.logger.warning("[卡组轮换] 已启用但切换序列为空，本次运行不切换")
        elif self.enabled and not restored_runtime:
            missing = sorted({slot for slot in self.sequence if slot not in self.slot_profiles})
            if missing:
                self.device_state.logger.error(
                    "[卡组轮换] 以下游戏槽位尚未绑定本地构筑: %s",
                    ", ".join(str(slot) for slot in missing),
                )
            if self.switch_on_start:
                self.pending_slot = self._next_slot()
                if self.pending_slot is not None:
                    self.device_state.logger.info(
                        "[卡组轮换] 启动同步目标：卡组 %d",
                        self.pending_slot,
                    )
            elif self.current_slot in self.sequence:
                self.sequence_index = self.sequence.index(self.current_slot) + 1
        elif self.enabled and restored_runtime:
            self.device_state.logger.info(
                "[卡组轮换] 已恢复轮换进度：游标=%d，已完成=%d/%d，待切换=%s",
                self.sequence_index,
                self.completed_since_switch,
                self.interval,
                self.pending_slot if self.pending_slot is not None else "无",
            )

        self._emit_status("pending" if self.pending_slot is not None else "ready")

    @staticmethod
    def _runtime_slot(value: object) -> Optional[int]:
        try:
            slot = int(value)
        except (TypeError, ValueError):
            return None
        return slot if 1 <= slot <= 9 else None

    def _restore_runtime_state(self) -> bool:
        state = getattr(self.device_state, "deck_rotation_runtime_state", None)
        if not isinstance(state, dict) or state.get("signature") != self._state_signature:
            return False
        try:
            self.completed_since_switch = max(
                0,
                min(self.interval, int(state.get("completed_since_switch", 0) or 0)),
            )
            self.sequence_index = max(0, int(state.get("sequence_index", 0) or 0))
        except (TypeError, ValueError):
            return False
        self.current_slot = self._runtime_slot(state.get("current_slot"))
        self.last_slot = self._runtime_slot(state.get("last_slot"))
        self.pending_slot = self._runtime_slot(state.get("pending_slot"))
        self.exhausted = bool(state.get("exhausted", False))
        return True

    def _persist_runtime_state(self) -> None:
        self.device_state.deck_rotation_runtime_state = {
            "signature": self._state_signature,
            "completed_since_switch": self.completed_since_switch,
            "sequence_index": self.sequence_index,
            "current_slot": self.current_slot,
            "last_slot": self.last_slot,
            "pending_slot": self.pending_slot,
            "exhausted": self.exhausted,
        }

    def _active_snapshot(self) -> dict[str, Any]:
        ui_config = self.device_state.config.get("ui", {})
        if not isinstance(ui_config, dict):
            return {}
        snapshot = ui_config.get("active_deck_snapshot", {})
        return snapshot if isinstance(snapshot, dict) else {}

    def _infer_active_slot(self) -> Optional[int]:
        active_file = str(
            getattr(self.device_state, "active_deck_file", "")
            or self._active_snapshot().get("deck_file")
            or ""
        )
        snapshot_file = os.path.basename(active_file.strip()).casefold()
        if not snapshot_file:
            return None
        matches = [
            slot
            for slot, filename in self.slot_profiles.items()
            if filename.casefold() == snapshot_file
        ]
        return matches[0] if len(matches) == 1 else None

    def _profile_filename(self, slot: Optional[int]) -> str:
        return self.slot_profiles.get(int(slot), "") if slot is not None else ""

    def _profile_name(self, slot: Optional[int]) -> str:
        filename = self._profile_filename(slot)
        return os.path.splitext(filename)[0] if filename else ""

    def _next_slot_preview(self) -> Optional[int]:
        if self.pending_slot is not None:
            return self.pending_slot
        if not self.sequence or self.exhausted or self.mode == "random":
            return None
        if self.mode == "once" and self.sequence_index >= len(self.sequence):
            return None
        return self.sequence[self.sequence_index % len(self.sequence)]

    def _emit_status(self, state: str, *, reason: str = "") -> None:
        self._persist_runtime_state()
        next_slot = self._next_slot_preview()
        payload = {
            "enabled": bool(self.enabled and self.sequence),
            "state": str(state or "ready"),
            "mode": self.mode,
            "current_slot": self.current_slot,
            "current_file": str(getattr(self.device_state, "active_deck_file", "") or ""),
            "current_name": str(getattr(self.device_state, "active_deck_name", "") or ""),
            "next_slot": next_slot,
            "next_file": self._profile_filename(next_slot),
            "next_name": self._profile_name(next_slot),
            "completed": self.completed_since_switch,
            "interval": self.interval,
            "remaining": max(0, self.interval - self.completed_since_switch),
            "exhausted": self.exhausted,
            "reason": str(reason or ""),
        }
        if self.current_profile is not None:
            payload["deck_summary"] = self.current_profile.dashboard_summary(
                slot=self.current_slot
            )
        self.device_state.logger.info(
            "[卡组轮换状态] %s",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )

    @property
    def has_pending(self) -> bool:
        return self.pending_slot is not None

    def record_completed_match(self, result: str) -> bool:
        """Count only settled wins/losses and queue one destination slot."""

        if (
            not self.enabled
            or not self.sequence
            or self.exhausted
            or str(result or "").lower() not in {"win", "loss"}
        ):
            return False
        if self.pending_slot is not None:
            return True
        self.completed_since_switch += 1
        remaining = max(0, self.interval - self.completed_since_switch)
        self.device_state.logger.info(
            "[卡组轮换] 已完成 %d/%d 局，距离切换还剩 %d 局",
            self.completed_since_switch,
            self.interval,
            remaining,
        )
        if self.completed_since_switch < self.interval:
            self._emit_status("counting")
            return False
        self.pending_slot = self._next_slot()
        if self.pending_slot is None:
            self.exhausted = True
            self._emit_status("exhausted")
            return False
        self.device_state.logger.info("[卡组轮换] 本次目标：卡组 %d", self.pending_slot)
        self._emit_status("pending")
        return True

    def _next_slot(self) -> Optional[int]:
        if not self.sequence:
            return None
        if self.mode == "random":
            candidates = [slot for slot in self.sequence if slot != self.last_slot]
            return random.choice(candidates or self.sequence)
        if self.mode == "once" and self.sequence_index >= len(self.sequence):
            return None
        return self.sequence[self.sequence_index % len(self.sequence)]

    def _advance(self, *, success: bool, skip: bool = False) -> None:
        target = self.pending_slot
        if success and target is not None:
            self.last_slot = target
        if self.mode != "random" and (success or skip):
            self.sequence_index += 1
            if self.mode == "once" and self.sequence_index >= len(self.sequence):
                self.exhausted = True
                self.device_state.logger.info("[卡组轮换] 单次序列已执行完成")
        self.completed_since_switch = 0
        self.pending_slot = None

    def _click(self, point: tuple[int, int]) -> None:
        device = self.device_state.require_u2_device()
        device.click(point[0] + random.randint(-2, 2), point[1] + random.randint(-2, 2))

    def _capture(self):
        screenshot = self.device_state.take_screenshot()
        if screenshot is None:
            return None, None
        bgr = cv2.cvtColor(np.asarray(screenshot), cv2.COLOR_RGB2BGR)
        return bgr, cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    def _matches(self, key: str, bgr: np.ndarray, gray: np.ndarray) -> bool:
        manager = self.game_manager.template_manager
        info = manager.templates.get(key)
        if info:
            location, score = manager.match_template(gray, info)
            if location is not None and score >= float(info["threshold"]):
                return True
        recognition = getattr(self.game_manager, "recognition", None)
        aliases = PAGE_TEXT_ALIASES.get(key, ())
        if recognition is not None and aliases:
            try:
                return recognition.match_page_aliases(bgr, aliases) is not None
            except Exception:
                return False
        return False

    def _wait_page(self, key: str, *, present: bool = True) -> bool:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.device_state.check_interrupt()
            bgr, gray = self._capture()
            if bgr is not None and gray is not None:
                matched = self._matches(key, bgr, gray)
                if matched is present:
                    return True
            self.device_state.sleep(0.25)
        return False

    def _wait_result_page(self) -> bool:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.device_state.check_interrupt()
            bgr, gray = self._capture()
            if bgr is not None and gray is not None and any(
                self._matches(key, bgr, gray) for key in ("war", "win", "result")
            ):
                return True
            self.device_state.sleep(0.25)
        return False

    def _recover_result_page(self) -> bool:
        """Best-effort back navigation before allowing continue/skip policies."""

        device = self.device_state.require_u2_device()
        for _ in range(2):
            try:
                device.press("back")
            except Exception:
                break
            if self._wait_result_page():
                return True
        return False

    def perform_pending(self) -> bool:
        """Execute the four-page transition; return whether next battle may start."""

        slot = self.pending_slot
        if slot is None:
            return True
        point = DECK_GRID_POINTS.get(slot)
        if point is None:
            return self._handle_failure(
                f"无效卡组槽位: {slot}",
                needs_recovery=False,
            )

        profile_filename = self._profile_filename(slot)
        if not profile_filename:
            return self._handle_failure(
                f"卡组 {slot} 尚未绑定本地构筑",
                needs_recovery=False,
            )

        try:
            self.device_state.logger.info(
                "[卡组轮换] 预检本地构筑: 卡组 %d -> %s",
                slot,
                profile_filename,
            )
            profile = self.profile_loader.load(profile_filename)
        except DeckProfileError as exc:
            return self._handle_failure(
                f"本地构筑预检失败: {exc}",
                needs_recovery=False,
            )
        except Exception as exc:
            return self._handle_failure(
                f"本地构筑加载异常: {exc}",
                needs_recovery=False,
            )

        try:
            self._emit_status("switching")
            self.device_state.logger.info("[卡组轮换] 点击使用牌组卡面，打开换牌组弹窗")
            self._click(RESULT_DECK_CARD)
            if not self._wait_page("deck_confirm_dialog"):
                return self._handle_failure("未识别到确认牌组弹窗")

            self.device_state.logger.info("[卡组轮换] 点击弹窗中的确认牌组按钮")
            self._click(DIALOG_DECK_BUTTON)
            if not self._wait_page("deck_selection_page"):
                return self._handle_failure("未识别到选择牌组页面")

            self.device_state.logger.info("[卡组轮换] 点击卡组 %d: %s", slot, point)
            self._click(point)
            if not self._wait_page("deck_confirm_dialog"):
                return self._handle_failure("选择槽位后未返回确认牌组弹窗")

            self.device_state.logger.info("[卡组轮换] 点击决定，应用所选卡组")
            self._click(DIALOG_DECIDE_BUTTON)
            if not self._wait_result_page():
                return self._handle_failure("决定后未返回结算页面", critical=True)

            try:
                self._activate_runtime_profile(slot, profile)
            except Exception as exc:
                return self._handle_failure(
                    f"游戏卡组已切换，但脚本构筑同步失败: {exc}",
                    critical=True,
                )

            self.device_state.logger.info(
                "[卡组轮换] 已切换至卡组 %d，并同步本地构筑[%s]",
                slot,
                profile.name,
            )
            self._advance(success=True)
            self._emit_status("active")
            return True
        except (PauseRequested, StopRequested):
            raise
        except Exception as exc:
            return self._handle_failure(f"切换异常: {exc}")

    def _activate_runtime_profile(self, slot: int, profile: Any) -> None:
        current_config = self.device_state.config
        merged_config = apply_strategy_config(
            current_config,
            strategy_config=profile.strategy_config,
        )
        old_config = copy.deepcopy(current_config)
        old_template_dir = self.game_manager.card_template_dir
        old_hand_recognizer = self.game_manager.game_actions.hand_manager.sift_recognition
        old_board_templates = self.game_manager._board_sift_templates
        old_identity = (
            getattr(self.device_state, "active_deck_slot", None),
            getattr(self.device_state, "active_deck_file", ""),
            getattr(self.device_state, "active_deck_name", ""),
        )
        old_profile = self.current_profile
        old_current_slot = self.current_slot
        try:
            self.game_manager.set_runtime_deck_profile(profile)
            current_config.clear()
            current_config.update(merged_config)
            self.device_state.set_active_deck_profile(
                slot=slot,
                filename=profile.filename,
                name=profile.name,
            )
            self.current_slot = slot
            self.current_profile = profile
            self.device_state.runtime_deck_profile_active = True
        except Exception:
            current_config.clear()
            current_config.update(old_config)
            self.game_manager.card_template_dir = old_template_dir
            self.game_manager.game_actions.hand_manager.sift_recognition = old_hand_recognizer
            self.game_manager._board_sift_templates = old_board_templates
            self.device_state.set_active_deck_profile(
                slot=old_identity[0],
                filename=old_identity[1],
                name=old_identity[2],
            )
            self.current_slot = old_current_slot
            self.current_profile = old_profile
            raise

    def _handle_failure(
        self,
        reason: str,
        *,
        critical: bool = False,
        needs_recovery: bool = True,
    ) -> bool:
        self.device_state.logger.error("[卡组轮换] %s", reason)
        if (
            not critical
            and self.failure_policy in {"skip", "continue"}
            and (not needs_recovery or self._recover_result_page())
        ):
            if needs_recovery:
                self.device_state.logger.warning("[卡组轮换] 已退回结算页，按失败策略继续")
            else:
                self.device_state.logger.warning("[卡组轮换] 未操作游戏页面，按失败策略继续")
            self._advance(success=False, skip=self.failure_policy == "skip")
            self._emit_status("recovered", reason=reason)
            return True
        self.device_state.logger.error("[卡组轮换] 为避免误点击，已暂停脚本等待人工处理")
        self._emit_status("error", reason=reason)
        self.device_state.request_pause(reason="deck_rotation_failed")
        return False

    def close(self) -> None:
        self.profile_loader.close()
