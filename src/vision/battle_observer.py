"""Recognition of battle values from calibrated 1280x720 screenshots."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import cv2
import numpy as np

from src.vision.ocr_runtime import RecognitionService


# Calibrated from real 1280x720 Traditional-Chinese game screenshots.
ENEMY_LEADER_HP_ROI = (730, 38, 786, 110)
OUR_LEADER_HP_ROI = (746, 528, 803, 601)
OUR_PP_ROI = (1064, 395, 1268, 486)
OUR_EXTRA_PP_ROI = (1063, 483, 1264, 555)
OUR_EP_ROI = (526, 472, 596, 548)
OUR_SEP_ROI = (681, 470, 758, 550)


@dataclass(frozen=True)
class FollowerObservation:
    x: int
    y: int
    attack: Optional[int]
    health: Optional[int]
    kind: str = "normal"


@dataclass(frozen=True)
class BattleObservation:
    captured_at: float
    enemy_leader_hp: Optional[int]
    our_leader_hp: Optional[int]
    enemy_followers: tuple[FollowerObservation, ...] = field(default_factory=tuple)
    our_followers: tuple[FollowerObservation, ...] = field(default_factory=tuple)
    pp_current: Optional[int] = None
    pp_maximum: Optional[int] = None
    evolution_points: Optional[int] = None
    super_evolution_points: Optional[int] = None
    extra_pp_state: str = "unknown"
    backend: str = "legacy"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pil_to_bgr(screenshot: Any) -> np.ndarray:
    array = np.asarray(screenshot)
    if array.ndim == 2:
        return cv2.cvtColor(array.astype(np.uint8, copy=False), cv2.COLOR_GRAY2BGR)
    if array.ndim == 3 and array.shape[2] == 4:
        return cv2.cvtColor(array.astype(np.uint8, copy=False), cv2.COLOR_RGBA2BGR)
    if array.ndim == 3 and array.shape[2] == 3:
        # DeviceState.take_screenshot returns PIL RGB.
        return cv2.cvtColor(array.astype(np.uint8, copy=False), cv2.COLOR_RGB2BGR)
    raise ValueError(f"unsupported screenshot shape: {array.shape}")


def _int_or_none(value: object, *, reject_default_99: bool = False) -> Optional[int]:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed < 0 or parsed > 99 or (reject_default_99 and parsed == 99):
        return None
    return parsed


def _count_resource_pips(image: np.ndarray, roi: tuple[int, int, int, int]) -> Optional[int]:
    """Count the two colored diamonds used by EP/SEP.

    The outer emblem remains colored after use, so only small bottom-center
    diamond windows are inspected.  DeviceState counters remain the fallback.
    """

    x1, y1, x2, y2 = roi
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    height, width = crop.shape[:2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    windows = (
        (int(width * 0.30), int(height * 0.70), int(width * 0.46), int(height * 0.87)),
        (int(width * 0.58), int(height * 0.70), int(width * 0.76), int(height * 0.87)),
    )
    filled = 0
    for wx1, wy1, wx2, wy2 in windows:
        part = hsv[wy1:wy2, wx1:wx2]
        if part.size == 0:
            continue
        colored = (part[:, :, 1] >= 70) & (part[:, :, 2] >= 110)
        ratio = float(np.count_nonzero(colored)) / float(colored.size)
        if ratio >= 0.35:
            filled += 1
    return filled


def _extra_pp_visual_state(
    image: np.ndarray,
    recognition: RecognitionService,
    *,
    active_from_pp: bool,
    button_detected: bool,
    device_state: Any,
) -> str:
    x1, y1, x2, y2 = OUR_EXTRA_PP_ROI
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return "unknown"

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    orange = (
        (hsv[:, :, 0] <= 28)
        & (hsv[:, :, 1] >= 100)
        & (hsv[:, :, 2] >= 100)
    )
    orange_ratio = float(np.count_nonzero(orange)) / float(orange.size)

    has_label = False
    try:
        texts = recognition.read_texts(
            image,
            roi=OUR_EXTRA_PP_ROI,
            only_rec=False,
            digits=False,
            threshold=0.1,
        )
        has_label = any("PP+1" in str(item.text).upper().replace(" ", "") for item in texts)
    except Exception:
        has_label = False

    if active_from_pp or bool(getattr(device_state, "extra_cost_active", False)):
        return "active"
    if button_detected and orange_ratio >= 0.075:
        return "available"
    if button_detected or has_label:
        return "spent"
    configured = getattr(device_state, "extra_cost_available_this_match", None)
    if configured is False:
        return "unavailable"
    if configured is True:
        return "spent"
    return "unavailable"


class BattleObserver:
    def __init__(
        self,
        recognition: RecognitionService,
        device_state: Any,
        game_manager: Any,
    ):
        self.recognition = recognition
        self.device_state = device_state
        self.game_manager = game_manager
        self._last_observed_at = 0.0
        self._last_signature: Optional[tuple[Any, ...]] = None

    def observe(
        self,
        screenshot: Any,
        *,
        force: bool = False,
    ) -> Optional[BattleObservation]:
        now = time.monotonic()
        if not force and now - self._last_observed_at < 0.8:
            return getattr(self.device_state, "battle_observation", None)
        self._last_observed_at = now

        try:
            image = _pil_to_bgr(screenshot)
        except Exception as exc:
            self.device_state.logger.debug("战斗状态截图转换失败: %s", exc)
            return None

        enemy_hp = self.recognition.read_integer(image, ENEMY_LEADER_HP_ROI, maximum=99)
        our_hp = self.recognition.read_integer(image, OUR_LEADER_HP_ROI, maximum=99)

        enemy_observations: list[FollowerObservation] = []
        try:
            enemy_followers = self.game_manager.scan_enemy_followers(
                screenshot,
                debug_flag=False,
            )
        except Exception as exc:
            self.device_state.logger.debug("敌方随从状态识别失败: %s", exc)
            enemy_followers = []
        for follower in enemy_followers:
            try:
                x, y = int(follower[0]), int(follower[1])
            except (TypeError, ValueError, IndexError):
                continue
            attack_roi = (x - 78, 247, x - 30, 305)
            health_roi = (x + 25, 247, x + 72, 305)
            attack = self.recognition.read_integer(image, attack_roi, maximum=99)
            health = self.recognition.read_integer(image, health_roi, maximum=99)
            if health is None and len(follower) > 3:
                health = _int_or_none(follower[3], reject_default_99=True)
            enemy_observations.append(
                FollowerObservation(x, y, attack, health, str(follower[2] or "normal"))
            )

        our_observations: list[FollowerObservation] = []
        try:
            our_followers = self.game_manager.scan_our_followers(
                screenshot,
                debug_flag=False,
                with_names=False,
            )
        except Exception as exc:
            self.device_state.logger.debug("我方随从状态识别失败: %s", exc)
            our_followers = []
        for follower in our_followers:
            try:
                x, y = int(follower[0]), int(follower[1])
            except (TypeError, ValueError, IndexError):
                continue
            attack_roi = (x - 78, 425, x - 30, 480)
            health_roi = (x + 25, 425, x + 75, 480)
            attack = self.recognition.read_integer(image, attack_roi, maximum=99)
            health = self.recognition.read_integer(image, health_roi, maximum=99)
            our_observations.append(
                FollowerObservation(x, y, attack, health, str(follower[2] or "normal"))
            )

        pp_current, pp_maximum, active_from_pp = self.recognition.read_ratio(
            image,
            OUR_PP_ROI,
        )
        ep_visual = _count_resource_pips(image, OUR_EP_ROI)
        sep_visual = _count_resource_pips(image, OUR_SEP_ROI)
        ep = ep_visual if ep_visual is not None else _int_or_none(
            getattr(self.device_state, "evolution_point", None)
        )
        sep = sep_visual if sep_visual is not None else _int_or_none(
            getattr(self.device_state, "super_evolution_point", None)
        )
        try:
            extra_point = self.game_manager.game_actions._detect_extra_cost_point(image)
        except Exception:
            extra_point = None
        extra_pp_state = _extra_pp_visual_state(
            image,
            self.recognition,
            active_from_pp=active_from_pp,
            button_detected=extra_point is not None,
            device_state=self.device_state,
        )

        observation = BattleObservation(
            captured_at=time.time(),
            enemy_leader_hp=enemy_hp,
            our_leader_hp=our_hp,
            enemy_followers=tuple(sorted(enemy_observations, key=lambda item: item.x)),
            our_followers=tuple(sorted(our_observations, key=lambda item: item.x)),
            pp_current=pp_current,
            pp_maximum=pp_maximum,
            evolution_points=ep,
            super_evolution_points=sep,
            extra_pp_state=extra_pp_state,
            backend=self.recognition.active_backend,
        )
        updater = getattr(self.device_state, "update_battle_observation", None)
        if callable(updater):
            updater(observation)
        else:
            self.device_state.battle_observation = observation

        signature = (
            enemy_hp,
            our_hp,
            tuple((item.attack, item.health) for item in observation.enemy_followers),
            tuple((item.attack, item.health) for item in observation.our_followers),
            pp_current,
            pp_maximum,
            ep,
            sep,
            extra_pp_state,
        )
        if signature != self._last_signature:
            self._last_signature = signature
            self.device_state.logger.info(
                "[识别状态] 主战者HP 敌=%s 我=%s | PP=%s/%s | EP=%s SEP=%s | "
                "额外PP=%s | 随从 敌=%s 我=%s",
                enemy_hp if enemy_hp is not None else "?",
                our_hp if our_hp is not None else "?",
                pp_current if pp_current is not None else "?",
                pp_maximum if pp_maximum is not None else "?",
                ep if ep is not None else "?",
                sep if sep is not None else "?",
                extra_pp_state,
                [(item.attack, item.health) for item in observation.enemy_followers],
                [(item.attack, item.health) for item in observation.our_followers],
            )
        return observation
