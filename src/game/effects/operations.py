"""Operation executors for Step3A effects."""

from __future__ import annotations

import random
import re
import time
from typing import Any, List, Optional, Tuple

from src.config.game_constants import BLANK_CLICK_POSITION, BLANK_CLICK_RANDOM
from src.config.paths import get_card_cost_dir
from src.game.sift_card_recognition import SiftCardRecognition
from src.utils.card_filename import normalize_card_base_name, split_enhance_key

from .target_resolver import resolve_targets


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _get_u2_device(ds: Any) -> Optional[Any]:
    try:
        getter = getattr(ds, "get_u2_device", None)
        if callable(getter):
            return getter()
        return None
    except Exception:
        return None


def _normalize_card_name_for_match(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        return ""
    try:
        base, _enh = split_enhance_key(name)
        name = base or name
    except Exception:
        pass
    try:
        name = normalize_card_base_name(name)
    except Exception:
        pass
    return " ".join(str(name or "").replace("_", " ").split())


class OperationExecutor:
    @staticmethod
    def select_option(ctx: Any, *, index: Any, option_count: Any = 2) -> bool:
        ds = getattr(ctx, "device_state", None)
        if ds is None:
            return False
        idx = _safe_int(index, 0)
        count = _safe_int(option_count, 2)
        if count not in (2, 3):
            count = 2

        coords = {
            2: {1: (748, 328), 2: (724, 429)},
            3: {1: (768, 254), 2: (768, 361), 3: (768, 467)},
        }
        pos = coords.get(count, {}).get(idx)
        if pos is None:
            return False
        x, y = pos

        try:
            ds.logger.info(f"[Effect] select_option index={idx} option_count={count}")
        except Exception:
            pass

        u2_device = _get_u2_device(ds)
        if u2_device is None:
            return False

        time.sleep(0.3)
        u2_device.click(x + random.randint(-15, 15), y + random.randint(-2, 2))
        time.sleep(0.5)
        return True

    @staticmethod
    def select_option_by_our_followers(
        ctx: Any,
        *,
        threshold: Any = 3,
        le_option: Any = 1,
        gt_option: Any = 2,
        option_count: Any = 2,
    ) -> bool:
        ds = getattr(ctx, "device_state", None)
        if ds is None:
            return False

        threshold_i = _safe_int(threshold, 3)
        le_option_i = _safe_int(le_option, 1)
        gt_option_i = _safe_int(gt_option, 2)

        pre_count = getattr(ctx, "pre_action_our_follower_count", None)
        if pre_count is not None:
            follower_count = _safe_int(pre_count, 0)
            source = "pre_action"
        else:
            try:
                ds.logger.warning(
                    "[Effect] select_option_by_our_followers skipped: "
                    "pre_action_our_follower_count unavailable"
                )
            except Exception:
                pass
            return False
        selected_option = le_option_i if follower_count <= threshold_i else gt_option_i
        try:
            ds.logger.info(
                "[Effect] select_option_by_our_followers "
                f"count={follower_count} source={source} "
                f"threshold={threshold_i} -> option={selected_option}"
            )
        except Exception:
            pass

        return OperationExecutor.select_option(ctx, index=selected_option, option_count=option_count)

    @staticmethod
    def select_hand_card(ctx: Any, *, priority_cards: Any, max_retries: Any = 2) -> bool:
        ds = getattr(ctx, "device_state", None)
        if ds is None:
            return False

        priorities = [p.strip() for p in re.split(r"[\n,，、|]+", str(priority_cards or "")) if p.strip()]
        normalized_priorities = [_normalize_card_name_for_match(p) for p in priorities]
        if not priorities:
            try:
                ds.logger.warning("[Effect] select_hand_card: priority_cards is empty")
            except Exception:
                pass
            return False

        u2_device = _get_u2_device(ds)
        if u2_device is None:
            return False

        recognizer = SiftCardRecognition(get_card_cost_dir(ensure=True))
        retries = max(1, _safe_int(max_retries, 2))
        hand_area = (250, 120, 1050, 650)
        cards: List[Any] = []

        for attempt in range(1, retries + 1):
            try:
                screenshot = ds.take_screenshot()
                cards = recognizer.recognize_hand_cards(screenshot, hand_area=hand_area) if screenshot is not None else []
            except Exception as e:
                cards = []
                try:
                    ds.logger.warning(f"[Effect] select_hand_card recognize failed: {e}")
                except Exception:
                    pass

            normalized_cards = [
                (card, _normalize_card_name_for_match(card.get("name") if isinstance(card, dict) else ""))
                for card in (cards or [])
                if isinstance(card, dict)
            ]
            for want, want_norm in zip(priorities, normalized_priorities):
                if not want_norm:
                    continue
                for card, card_norm in normalized_cards:
                    if card_norm == want_norm:
                        center = card.get("center") or None
                        if not center or len(center) != 2:
                            continue
                        x, y = int(center[0]), int(center[1])
                        try:
                            ds.logger.info(f"[Effect] select_hand_card {want}: ({x},{y}) attempt={attempt}")
                        except Exception:
                            pass
                        time.sleep(0.3)
                        u2_device.click(x, y)
                        time.sleep(0.5)
                        return True

            fallback_cards = []
            for card, _card_norm in normalized_cards:
                center = card.get("center") or None
                if center and len(center) == 2:
                    try:
                        fallback_cards.append((int(center[0]), int(center[1]), card))
                    except Exception:
                        continue
            if fallback_cards:
                x, y, card = sorted(fallback_cards, key=lambda it: it[0])[0]
                try:
                    name = str(card.get("name") or "")
                    ds.logger.info(f"[Effect] select_hand_card fallback {name}: ({x},{y}) attempt={attempt}")
                except Exception:
                    pass
                time.sleep(0.3)
                u2_device.click(x, y)
                time.sleep(0.5)
                return True

            if attempt < retries:
                time.sleep(0.2)

        try:
            found = [str(c.get("name") or "") for c in (cards or [])]
            ds.logger.warning(f"[Effect] select_hand_card: no priority match, priorities={priorities}, found={found}")
        except Exception:
            pass
        return False

    @staticmethod
    def force_post_play_hand_refresh(ctx: Any) -> bool:
        ds = getattr(ctx, "device_state", None)
        setattr(ctx, "force_post_play_hand_refresh", True)
        try:
            if ds is not None:
                ds.logger.info("[Effect] force_post_play_hand_refresh")
        except Exception:
            pass
        return True

    @staticmethod
    def cancel_action(ctx: Any) -> bool:
        ds = getattr(ctx, "device_state", None)
        if ds is None:
            return False
        try:
            ds.logger.info("[Effect] cancel_action")
        except Exception:
            pass
        u2_device = _get_u2_device(ds)
        if u2_device is None:
            return False

        u2_device.click(
            BLANK_CLICK_POSITION[0] + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM),
            BLANK_CLICK_POSITION[1] + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM),
        )
        time.sleep(0.2)
        return True

    @staticmethod
    def add_cost_bonus(ctx: Any, *, amount: Any) -> bool:
        ds = getattr(ctx, "device_state", None)
        val = _safe_int(amount, 0)
        prev = _safe_int(getattr(ctx, "extra_cost_bonus", 0), 0)
        setattr(ctx, "extra_cost_bonus", int(prev + val))
        try:
            if ds is not None:
                ds.logger.info(f"[Effect] add_cost_bonus amount={val} total={int(prev + val)}")
        except Exception:
            pass
        return True

    @staticmethod
    def buff(
        ctx: Any,
        *,
        target: Any,
        atk_delta: Any,
        hp_delta: Any,
    ) -> bool:
        ds = getattr(ctx, "device_state", None)
        if ds is None:
            return False

        target_mode = str(target or "others")
        if target_mode not in ("others", "self"):
            target_mode = "others"

        atk_val = _safe_int(atk_delta, 0)
        hp_val = _safe_int(hp_delta, 0)

        runtime = getattr(ds, "battle_runtime_state", None)
        if runtime is None or not hasattr(runtime, "apply_buff"):
            try:
                ds.logger.warning("[Effect] buff skipped: runtime unavailable")
            except Exception:
                pass
            return True

        source_pos = getattr(ctx, "follower_pos", None) or getattr(ctx, "attack_source_pos", None)
        source_uid = None
        try:
            uid_raw = getattr(ctx, "follower_uid", None)
            if uid_raw is not None:
                uid_i = int(uid_raw)
                if uid_i > 0:
                    source_uid = int(uid_i)
        except Exception:
            source_uid = None

        if source_uid is None and source_pos is not None and hasattr(runtime, "get_ours_uid"):
            try:
                source_uid = runtime.get_ours_uid(
                    source_pos,
                    fallback_name=str(
                        getattr(ctx, "card_name", "")
                        or getattr(ctx, "follower_name", "")
                        or ""
                    ),
                )
            except Exception:
                source_uid = None

        if source_pos is None and runtime is not None and hasattr(runtime, "find_ours_pos_by_cfg_key"):
            try:
                source_pos = runtime.find_ours_pos_by_cfg_key(
                    cfg_key=str(getattr(ctx, "cfg_key", "") or ""),
                    fallback_name=str(
                        getattr(ctx, "card_name", "")
                        or getattr(ctx, "follower_name", "")
                        or ""
                    ),
                )
            except Exception:
                source_pos = None
        try:
            changed = int(
                runtime.apply_buff(
                    source_pos=source_pos,
                    source_uid=source_uid,
                    target_mode=target_mode,
                    atk_delta=atk_val,
                    hp_delta=hp_val,
                    round_index=getattr(ds, "current_round_count", None),
                )
            )
        except Exception:
            changed = 0

        try:
            ds.logger.info(
                "[Effect] buff "
                f"mode={target_mode} atk_delta={atk_val} hp_delta={hp_val} "
                f"affected={changed}"
            )
        except Exception:
            pass
        return True

    @staticmethod
    def buff_attack_times(
        ctx: Any,
        *,
        target: Any,
        attack_times: Any,
    ) -> bool:
        ds = getattr(ctx, "device_state", None)
        if ds is None:
            return False

        target_mode = str(target or "others")
        if target_mode not in ("others", "self"):
            target_mode = "others"

        attack_times_val = max(1, _safe_int(attack_times, 1))

        runtime = getattr(ds, "battle_runtime_state", None)
        if runtime is None or not hasattr(runtime, "apply_attack_times_buff"):
            try:
                ds.logger.warning("[Effect] buff_attack_times skipped: runtime unavailable")
            except Exception:
                pass
            return True

        source_pos = getattr(ctx, "follower_pos", None) or getattr(ctx, "attack_source_pos", None)
        source_uid = None
        try:
            uid_raw = getattr(ctx, "follower_uid", None)
            if uid_raw is not None:
                uid_i = int(uid_raw)
                if uid_i > 0:
                    source_uid = int(uid_i)
        except Exception:
            source_uid = None

        if source_uid is None and source_pos is not None and hasattr(runtime, "get_ours_uid"):
            try:
                source_uid = runtime.get_ours_uid(
                    source_pos,
                    fallback_name=str(
                        getattr(ctx, "card_name", "")
                        or getattr(ctx, "follower_name", "")
                        or ""
                    ),
                )
            except Exception:
                source_uid = None

        if source_pos is None and runtime is not None and hasattr(runtime, "find_ours_pos_by_cfg_key"):
            try:
                source_pos = runtime.find_ours_pos_by_cfg_key(
                    cfg_key=str(getattr(ctx, "cfg_key", "") or ""),
                    fallback_name=str(
                        getattr(ctx, "card_name", "")
                        or getattr(ctx, "follower_name", "")
                        or ""
                    ),
                )
            except Exception:
                source_pos = None

        try:
            changed = int(
                runtime.apply_attack_times_buff(
                    source_pos=source_pos,
                    source_uid=source_uid,
                    target_mode=target_mode,
                    attack_times=attack_times_val,
                    round_index=getattr(ds, "current_round_count", None),
                )
            )
        except Exception:
            changed = 0

        try:
            ds.logger.info(
                "[Effect] buff_attack_times "
                f"mode={target_mode} attack_times={attack_times_val} affected={changed}"
            )
        except Exception:
            pass

        return True

    @staticmethod
    def select_targets(
        ctx: Any,
        *,
        target: Any,
        count: Any = 1,
        distinct_xy: Any = True,
        is_select_ui: Any = True,
    ) -> bool:
        ds = getattr(ctx, "device_state", None)
        if ds is None:
            return False

        target_kind = ""
        try:
            if isinstance(target, dict):
                target_kind = str(target.get("kind") or "")
        except Exception:
            target_kind = ""

        # Allow animations / target UI to settle.
        time.sleep(0.4)

        n = max(1, _safe_int(count, 1))
        positions: List[Tuple[int, int]] = resolve_targets(
            ctx,
            target=target,
            count=n,
            distinct_xy=bool(distinct_xy),
            is_select_ui=bool(is_select_ui),
        )
        if not positions:
            try:
                ds.logger.warning(f"[Effect] select_targets: no targets (target={target})")
            except Exception:
                pass
            try:
                fail_kinds = getattr(ctx, "select_targets_fail_kinds", None)
                if isinstance(fail_kinds, list):
                    if target_kind:
                        fail_kinds.append(target_kind)
                else:
                    setattr(ctx, "select_targets_fail_kinds", [target_kind] if target_kind else [])
            except Exception:
                pass
            return False

        try:
            success_kinds = getattr(ctx, "select_targets_success_kinds", None)
            if isinstance(success_kinds, list):
                if target_kind and target_kind not in success_kinds:
                    success_kinds.append(target_kind)
            else:
                setattr(
                    ctx,
                    "select_targets_success_kinds",
                    [target_kind] if target_kind else [],
                )

            fail_kinds = getattr(ctx, "select_targets_fail_kinds", None)
            if isinstance(fail_kinds, list) and target_kind:
                while target_kind in fail_kinds:
                    fail_kinds.remove(target_kind)
        except Exception:
            pass

        try:
            ds.logger.info(f"[Effect] select_targets count={len(positions)}/{n}")
        except Exception:
            pass

        u2_device = _get_u2_device(ds)
        if u2_device is None:
            return False

        for i, (x, y) in enumerate(list(positions)[:n], 1):
            u2_device.click(int(x), int(y))
            try:
                ds.logger.info(f"[Effect] click_target {i}: ({int(x)},{int(y)})")
            except Exception:
                pass
            time.sleep(0.35)
        return True
