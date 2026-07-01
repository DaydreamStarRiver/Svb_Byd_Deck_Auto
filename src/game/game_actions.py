"""
游戏操作模块
实现所有游戏动作和策略
"""

import cv2
import numpy as np
import random
import time
import logging
import os
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple, cast
from src.config import settings
from src.config.game_constants import (
    DEFAULT_ATTACK_TARGET, DEFAULT_ATTACK_RANDOM,
    POSITION_RANDOM_RANGE, SHOW_CARDS_BUTTON, SHOW_CARDS_RANDOM_X, SHOW_CARDS_RANDOM_Y,
    BLANK_CLICK_POSITION, BLANK_CLICK_RANDOM, OUR_FOLLOWER_REGION
)
from src.config.card_priorities import (
    get_card_priority_pre_evolution,
    get_card_priority_post_evolution,
    get_evolve_priority,
    is_evolution_unlocked,
    is_evolve_priority_card,
)
from src.config.strategy_effects import card_effect_has_op
from src.game.drag_utils import human_like_drag
from src.utils.image_io import safe_imread

logger = logging.getLogger(__name__)

FollowerState = tuple[int, int, str, str | None]
EnemyFollowerState = tuple[int, int, Any, Any]


class _U2DeviceLike(Protocol):
    def click(self, *args: Any, **kwargs: Any) -> Any: ...

    def swipe(self, *args: Any, **kwargs: Any) -> Any: ...


class GameActions:
    """游戏操作类"""
    
    def __init__(self, device_state: Any):
        self.device_state = device_state
        # 初始化手牌管理器，只创建一次
        from .hand_card_manager import HandCardManager
        self.hand_manager = HandCardManager(device_state)

        # Keep a small observation cache for logging.
        self._last_observed_hand_cards = []
        self._force_post_play_hand_refresh = False
        self._force_post_evolve_hand_refresh = False
        self._last_play_phase_remaining_cost = 0

        # Policy hook (default preserves legacy behavior).
        try:
            from src.game.policy.base import LegacyBattlePolicy

            self.battle_policy = LegacyBattlePolicy()
        except Exception:
            self.battle_policy = None

        # Lightweight perf counters for follower scanning.
        self._perf_scan_our_followers = {
            "fast": {"calls": 0, "ok": 0, "total_ms": 0.0},
            "full": {"calls": 0, "ok": 0, "total_ms": 0.0},
        }
        self._perf_scan_our_followers_last_log_ts = 0.0

        # Spot-based scan stabilization (max 5 board slots).
        self._spot_state: Dict[int, Dict[str, Any]] = {}
        self._spot_round_key: Optional[Tuple[int, int]] = None
        self._spot_centers: List[int] = self._build_spot_centers()
        self._recent_attack_slots: Dict[int, Dict[str, Any]] = {}

        self.battle_runtime = None
        self._runtime_epoch = None
        try:
            from src.game.battle_runtime import BattleRuntimeState

            self.battle_runtime = BattleRuntimeState(logger=getattr(self.device_state, "logger", None))
            setattr(self.device_state, "battle_runtime_state", self.battle_runtime)
        except Exception:
            self.battle_runtime = None

        # Step3C: lightweight phase cache flags.
        self._play_phase_enemy_affected = False
        self._cached_enemy_presence_for_evolve = None

        # Round-local state used by card-play flow.
        self._banlist_blocked_this_round = False
        self._current_round_ignored_cards: set[str] = set()
        self._current_extra_cost_bonus = 0
        self._last_played_card = ""
        self._should_not_consume_cost = False
        self._should_remove_from_hand = False
    
    @property
    def follower_manager(self):
        """动态获取follower_manager，确保在GameManager初始化后才可用"""
        manager = getattr(self.device_state, "follower_manager", None)
        if manager is not None:
            return manager

        from src.game.follower_manager import FollowerManager

        manager = FollowerManager()
        setattr(self.device_state, "follower_manager", manager)
        return manager

    def _require_u2_device(self) -> _U2DeviceLike:
        getter = cast(Callable[[], _U2DeviceLike], getattr(self.device_state, "require_u2_device"))
        return getter()

    def _build_spot_centers(self) -> List[int]:
        """Build 5 fixed slot centers from our follower region."""

        try:
            x1, _y1, x2, _y2 = OUR_FOLLOWER_REGION
            width = max(1, int(x2) - int(x1))
            step = float(width) / 5.0
            return [int(round(int(x1) + step * (i + 0.5))) for i in range(5)]
        except Exception:
            return [975, 797, 620, 442, 264]

    def _slot_id_for_x(self, x: Any) -> int:
        """Map x coordinate to nearest board slot [0..4], rightmost=0."""

        try:
            x_i = int(x)
        except Exception:
            x_i = 0

        centers = list(self._spot_centers or [975, 797, 620, 442, 264])
        if not centers:
            return 0

        left_to_right_idx = min(
            range(len(centers)),
            key=lambda i: abs(int(centers[i]) - x_i),
        )
        # Convert to right->left slot id for easier reasoning in logs.
        return int((len(centers) - 1) - left_to_right_idx)

    def _current_round_key(self) -> Tuple[int, int]:
        try:
            match_idx = int(getattr(self.device_state, "current_run_matches", 0) or 0)
        except Exception:
            match_idx = 0
        try:
            round_idx = int(getattr(self.device_state, "current_round_count", 1) or 1)
        except Exception:
            round_idx = 1
        return (match_idx, round_idx)

    def _sync_spot_round(self) -> None:
        key = self._current_round_key()
        prev = self._spot_round_key
        if prev is None:
            self._spot_round_key = key
            return
        if key != prev:
            self._spot_state.clear()
            self._recent_attack_slots.clear()
            self._spot_round_key = key

    def _mark_recent_attack_slot(self, pos: Sequence[Any]) -> None:
        """Short-lived slot evidence after an attack was actually consumed."""

        if not isinstance(pos, (list, tuple)) or len(pos) < 1:
            return
        self._sync_spot_round()
        try:
            x_i = int(pos[0])
        except Exception:
            return
        slot = int(self._slot_id_for_x(x_i))
        self._recent_attack_slots[slot] = {"x": int(x_i), "ts": time.time(), "round": self._current_round_key()}

    def _consume_recent_attack_slot(self, slot: int, x_i: int) -> bool:
        ev = self._recent_attack_slots.get(int(slot))
        if not ev:
            return False
        now = time.time()
        if ev.get("round") != self._current_round_key() or now - float(ev.get("ts", 0) or 0) > 3.0:
            self._recent_attack_slots.pop(int(slot), None)
            return False
        if abs(int(ev.get("x", x_i) or x_i) - int(x_i)) > 90:
            return False
        self._recent_attack_slots.pop(int(slot), None)
        return True

    def _aggregate_followers_from_shots(
        self,
        shot_followers: Sequence[Sequence[Tuple[Any, Any, Any, Any]]],
        *,
        sort_desc: bool,
    ) -> List[Tuple[int, int, str, Optional[str]]]:
        """Aggregate multi-shot scans using best-shot anchor + constrained assignment.

        Priority to pick anchor frame:
        1) total follower count
        2) named count
        3) attackable count (green/yellow)

        Then assign type evidence from other frames to anchor followers:
        - first by exact name
        - then (for remaining) by x/y-nearest fallback
        """

        def _norm_type(v: Any) -> str:
            t = str(v or "normal")
            if t not in ("green", "yellow", "normal"):
                return "normal"
            return t

        def _norm_name(v: Any) -> Optional[str]:
            if not isinstance(v, str):
                return None
            s = str(v or "").strip()
            return s or None

        def _normalize_shot(raw_shot: Sequence[Tuple[Any, Any, Any, Any]]) -> List[Tuple[int, int, str, Optional[str]]]:
            one: List[Tuple[int, int, str, Optional[str]]] = []
            for it in list(raw_shot or []):
                if not isinstance(it, (list, tuple)) or len(it) < 3:
                    continue
                try:
                    x_i = int(it[0])
                    y_i = int(it[1])
                except Exception:
                    continue
                t_s = _norm_type(it[2] if len(it) > 2 else "normal")
                n_s = _norm_name(it[3] if len(it) > 3 else None)
                one.append((x_i, y_i, t_s, n_s))
            return sorted(one, key=lambda f: int(f[0]), reverse=True)[:5]

        shots = [_normalize_shot(s) for s in list(shot_followers or [])]
        shots = [s for s in shots if s]
        if not shots:
            return []
        if len(shots) == 1:
            return sorted(shots[0], key=lambda f: int(f[0]), reverse=bool(sort_desc))[:5]

        def _shot_score(shot: Sequence[Tuple[int, int, str, Optional[str]]]) -> Tuple[int, int, int]:
            total = len(list(shot or []))
            named = sum(1 for it in list(shot or []) if bool(it[3]))
            attackable = sum(1 for it in list(shot or []) if str(it[2]) in ("green", "yellow"))
            return (int(total), int(named), int(attackable))

        # Use best single-shot as anchor, with strong priority on follower count,
        # then naming quality, then attackable type evidence.
        best_idx = max(range(len(shots)), key=lambda i: (_shot_score(shots[i]), i))
        best_shot = list(shots[best_idx])

        type_rank = {"normal": 1, "yellow": 2, "green": 3}

        anchors: List[Dict[str, Any]] = []
        for x_i, y_i, t_s, n_s in best_shot:
            anchors.append(
                {
                    "x": int(x_i),
                    "y": int(y_i),
                    "base_name": n_s,
                    "types": [str(t_s or "normal")],
                    "names": [n_s] if n_s else [],
                }
            )

        def _pick_by_name(
            shot: Sequence[Tuple[int, int, str, Optional[str]]],
            *,
            target_name: str,
            ax: int,
            ay: int,
            used: set[int],
        ) -> Optional[int]:
            best = None
            best_score = 10**9
            for i, item in enumerate(list(shot or [])):
                if i in used:
                    continue
                if str(item[3] or "") != str(target_name):
                    continue
                dx = abs(int(item[0]) - int(ax))
                dy = abs(int(item[1]) - int(ay))
                score = dx * 2 + dy
                if score < best_score:
                    best_score = score
                    best = i
            return best

        def _pick_by_coord(
            shot: Sequence[Tuple[int, int, str, Optional[str]]],
            *,
            ax: int,
            ay: int,
            used: set[int],
            x_thresh: int = 72,
            y_thresh: int = 90,
        ) -> Optional[int]:
            best = None
            best_score = 10**9
            for i, item in enumerate(list(shot or [])):
                if i in used:
                    continue
                dx = abs(int(item[0]) - int(ax))
                dy = abs(int(item[1]) - int(ay))
                if dx > int(x_thresh) or dy > int(y_thresh):
                    continue
                score = dx * 2 + dy
                if score < best_score:
                    best_score = score
                    best = i
            return best

        for si, shot in enumerate(shots):
            if si == best_idx:
                continue

            used: set[int] = set()
            matched_anchor: set[int] = set()

            # Pass 1: name-based assignment first.
            for ai, anchor in enumerate(anchors):
                name = str(anchor.get("base_name") or "")
                if not name:
                    continue
                pick = _pick_by_name(
                    shot,
                    target_name=name,
                    ax=int(anchor.get("x", 0)),
                    ay=int(anchor.get("y", 0)),
                    used=used,
                )
                if pick is None:
                    continue
                used.add(int(pick))
                matched_anchor.add(int(ai))
                item = shot[pick]
                anchor["types"].append(str(item[2] or "normal"))
                if item[3]:
                    anchor["names"].append(item[3])

            # Pass 2: coord-based assignment for remaining anchors.
            for ai, anchor in enumerate(anchors):
                if ai in matched_anchor:
                    continue
                pick = _pick_by_coord(
                    shot,
                    ax=int(anchor.get("x", 0)),
                    ay=int(anchor.get("y", 0)),
                    used=used,
                )
                if pick is None:
                    continue
                used.add(int(pick))
                item = shot[pick]
                anchor["types"].append(str(item[2] or "normal"))
                if item[3]:
                    anchor["names"].append(item[3])

        out: List[Tuple[int, int, str, Optional[str]]] = []
        for anchor in anchors:
            t_list = [str(t or "normal") for t in list(anchor.get("types") or [])]
            t_sel = max(t_list, key=lambda t: type_rank.get(str(t), 0)) if t_list else "normal"

            name_sel = anchor.get("base_name")
            if not name_sel:
                names = [n for n in list(anchor.get("names") or []) if n]
                if names:
                    name_sel = Counter(names).most_common(1)[0][0]

            out.append(
                (
                    int(anchor.get("x", 0)),
                    int(anchor.get("y", 0)),
                    str(t_sel),
                    name_sel if isinstance(name_sel, str) else None,
                )
            )

        out = sorted(out, key=lambda f: int(f[0]), reverse=bool(sort_desc))
        return out[:5]

    def _stabilize_followers_by_spot(
        self,
        followers: Sequence[Tuple[Any, Any, Any, Any]],
        *,
        sort_desc: bool,
    ) -> List[Tuple[int, int, str, Optional[str]]]:
        """Stabilize follower type/name by board slot history.

        Rules:
        - raw normal can downgrade green/yellow only with short-lived attack evidence.
        - empty name does not overwrite a continuous slot name.
        """

        now = time.time()
        self._sync_spot_round()
        round_idx = self._current_round_key()[1]

        out: List[Tuple[int, int, str, Optional[str]]] = []

        raw = list(followers or [])
        if not raw:
            return []

        for item in sorted(raw, key=lambda f: int(f[0]), reverse=True):
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            try:
                x_i = int(item[0])
                y_i = int(item[1])
            except Exception:
                continue

            in_type = str(item[2] or "normal")
            in_name = item[3] if len(item) > 3 else None

            slot = int(self._slot_id_for_x(x_i))
            prev = self._spot_state.get(slot, {})
            prev_type = str(prev.get("type") or "")
            prev_name = prev.get("name")
            prev_streak = int(prev.get("normal_streak", 0) or 0)
            prev_x = int(prev.get("x", x_i) or x_i)
            prev_y = int(prev.get("y", y_i) or y_i)

            in_name_s = str(in_name or "") if isinstance(in_name, str) else ""
            prev_name_s = str(prev_name or "") if isinstance(prev_name, str) else ""
            same_name = bool(in_name_s and prev_name_s and in_name_s == prev_name_s)
            name_conflict = bool(in_name_s and prev_name_s and in_name_s != prev_name_s)

            dx = abs(int(prev_x) - int(x_i))
            dy = abs(int(prev_y) - int(y_i))
            if same_name:
                spot_continuous = dx <= 120 and dy <= 130
            elif in_name_s or prev_name_s:
                spot_continuous = dx <= 72 and dy <= 96
            else:
                spot_continuous = dx <= 56 and dy <= 90
            if name_conflict:
                spot_continuous = False

            eff_type = in_type
            normal_streak = 0

            if in_type == "normal":
                if spot_continuous:
                    normal_streak = prev_streak + 1
                    if prev_type in ("green", "yellow"):
                        eff_type = "normal" if self._consume_recent_attack_slot(slot, x_i) else prev_type
                    else:
                        eff_type = "normal"
                else:
                    normal_streak = 1
                    eff_type = "normal"
            else:
                eff_type = in_type
                normal_streak = 0

            if isinstance(in_name, str) and in_name:
                eff_name = in_name
            elif spot_continuous and prev_name_s:
                eff_name = prev_name_s
            else:
                eff_name = None

            out.append((x_i, y_i, str(eff_type), eff_name))
            self._spot_state[slot] = {
                "type": str(eff_type),
                "name": eff_name,
                "normal_streak": int(normal_streak),
                "x": int(x_i),
                "y": int(y_i),
                "ts": now,
                "round": int(round_idx),
            }

        out = sorted(out, key=lambda f: int(f[0]), reverse=bool(sort_desc))
        return out[:5]

    def _ensure_runtime_epoch(self):
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None:
            return

        match_idx = int(getattr(self.device_state, "current_run_matches", 0) or 0)
        round_idx = int(getattr(self.device_state, "current_round_count", 1) or 1)
        current = (match_idx, round_idx)

        prev = getattr(self, "_runtime_epoch", None)
        if prev is not None:
            try:
                prev_match, prev_round = int(prev[0]), int(prev[1])
            except Exception:
                prev_match, prev_round = match_idx, round_idx
            if match_idx != prev_match or round_idx < prev_round:
                runtime.reset(reason=f"epoch {prev_match}/{prev_round} -> {match_idx}/{round_idx}")
        self._runtime_epoch = current

    def _runtime_sync_ours(self, followers):
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None:
            return
        try:
            runtime.sync_ours(list(followers or []))
        except Exception:
            pass

    def _runtime_sync_enemy(self, enemy_followers, *, ward_targets=None):
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None:
            return
        try:
            runtime.sync_enemy(list(enemy_followers or []), ward_positions=list(ward_targets or []))
        except Exception:
            pass

    def _runtime_pick_enemy_target(self, attacker_pos, *, ward_only=False):
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None:
            return None, {"mode": "runtime_unavailable"}
        try:
            target_state, reason = runtime.pick_enemy_target(
                attacker_pos=attacker_pos,
                ward_only=bool(ward_only),
            )
            if target_state is None:
                return None, reason
            return (int(target_state.x), int(target_state.y)), reason
        except Exception as e:
            return None, {"mode": f"runtime_error:{e}"}

    def _runtime_apply_local_combat(self, attacker_pos, target_pos):
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None:
            return {"applied": False}
        try:
            return runtime.apply_local_combat(attacker_pos=attacker_pos, target_pos=target_pos)
        except Exception:
            return {"applied": False}

    def _runtime_effect_key_for_ours(self, source_pos, fallback_name: str = "", source_uid: Any = None) -> str:
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None or not hasattr(runtime, "get_effect_key_for_ours"):
            return str(fallback_name or "")
        try:
            return str(
                runtime.get_effect_key_for_ours(
                    follower_pos=source_pos,
                    follower_uid=source_uid,
                    fallback_name=str(fallback_name or ""),
                )
                or str(fallback_name or "")
            )
        except Exception:
            return str(fallback_name or "")

    def _runtime_attack_times_for_ours(self, source_pos) -> int:
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None or not hasattr(runtime, "get_ours_attack_times"):
            return 1

        try:
            round_idx = int(getattr(self.device_state, "current_round_count", 1) or 1)
        except Exception:
            round_idx = 1

        try:
            return max(
                1,
                int(
                    runtime.get_ours_attack_times(
                        source_pos,
                        round_index=round_idx,
                    )
                    or 1
                ),
            )
        except Exception:
            return 1

    def _runtime_attack_times_for_ours_uid(self, source_uid: Any) -> int:
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None or not hasattr(runtime, "get_ours_attack_times_by_uid"):
            return 1

        try:
            uid_i = int(source_uid)
            if uid_i <= 0:
                return 1
        except Exception:
            return 1

        try:
            round_idx = int(getattr(self.device_state, "current_round_count", 1) or 1)
        except Exception:
            round_idx = 1

        try:
            return max(
                1,
                int(
                    runtime.get_ours_attack_times_by_uid(
                        uid_i,
                        round_index=round_idx,
                    )
                    or 1
                ),
            )
        except Exception:
            return 1

    def _runtime_uid_for_ours(self, source_pos, *, fallback_name: str = "") -> Optional[int]:
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None or not hasattr(runtime, "get_ours_uid"):
            return None
        try:
            uid = runtime.get_ours_uid(
                source_pos,
                fallback_name=str(fallback_name or ""),
            )
            if uid is None:
                return None
            uid_i = int(uid)
            return uid_i if uid_i > 0 else None
        except Exception:
            return None

    def _tag_recent_played_follower(self, *, card_name: str, cfg_key: str) -> None:
        runtime = getattr(self, "battle_runtime", None)
        if runtime is None or not hasattr(runtime, "mark_latest_play_origin"):
            return
        try:
            # Wait for summon/effect animation to settle before tagging follower origin.
            self.device_state.sleep(2.0)
            followers = self._refresh_our_followers(
                sort_desc=True,
                extra_shots=0,
                retries=0,
                with_names=True,
                allow_cached_fallback=False,
            )
            if followers:
                runtime.sync_ours(list(followers or []))
            runtime.mark_latest_play_origin(card_name=str(card_name or ""), cfg_key=str(cfg_key or ""))
        except Exception:
            pass

    @staticmethod
    def _enemy_hp_value(enemy_follower) -> Optional[int]:
        try:
            hp = enemy_follower[3]
        except Exception:
            return None
        if isinstance(hp, int):
            return int(hp)
        if isinstance(hp, str) and hp.isdigit():
            return int(hp)
        return None

    def _fallback_pick_enemy_target(self, enemy_followers, *, ward_targets=None, ward_only=False):
        followers = list(enemy_followers or [])
        if not followers:
            return None, {"mode": "fallback_no_enemy"}

        if ward_only:
            wards = list(ward_targets or [])
            ward_filtered = []
            for f in followers:
                try:
                    fx = int(f[0])
                except Exception:
                    continue
                if any(abs(fx - int(w[0])) < 50 for w in wards if isinstance(w, (list, tuple)) and len(w) >= 1):
                    ward_filtered.append(f)
            if ward_filtered:
                followers = ward_filtered
            else:
                return None, {"mode": "fallback_no_ward_match"}

        numeric = [f for f in followers if self._enemy_hp_value(f) is not None]
        if numeric:
            target = min(
                numeric,
                key=lambda f: (
                    int(self._enemy_hp_value(f) or 999),
                    -int(f[0]),
                ),
            )
            return (int(target[0]), int(target[1])), {
                "mode": "fallback_min_hp",
                "target_hp": int(self._enemy_hp_value(target) or 0),
            }

        rightmost = max(followers, key=lambda f: int(f[0]))
        return (int(rightmost[0]), int(rightmost[1])), {
            "mode": "fallback_rightmost",
            "target_hp": None,
        }

    def _pick_enemy_target(self, attacker_pos, enemy_followers, *, ward_targets=None, ward_only=False):
        target, reason = self._runtime_pick_enemy_target(attacker_pos, ward_only=ward_only)
        if target is not None:
            return target, reason
        return self._fallback_pick_enemy_target(
            enemy_followers,
            ward_targets=ward_targets,
            ward_only=ward_only,
        )

    def perform_follower_attacks(self, enemy_check, *, all_followers: Optional[List[Tuple[Any, Any, Any, Any]]] = None):
        """执行随从攻击"""
        type_name_map = {
            "yellow": "突进",
            "green": "疾驰"
        }
        ATTACK_SETTLE_SLEEP_COMBAT = 1.5
        ATTACK_SETTLE_SLEEP_FACE = 0.5

        # 对面玩家位置（默认攻击目标）
        default_target = (
            DEFAULT_ATTACK_TARGET[0] + random.randint(-DEFAULT_ATTACK_RANDOM, DEFAULT_ATTACK_RANDOM),
            DEFAULT_ATTACK_TARGET[1] + random.randint(-DEFAULT_ATTACK_RANDOM, DEFAULT_ATTACK_RANDOM)
        )

        # Step3A: optional on_attack effects hook.
        try:
            from src.config.strategy_effects import (
                get_card_effect_steps as _get_eff_steps,
                has_any_effects_for_trigger as _has_any_eff,
                normalize_effect_steps_to_ops as _norm_ops,
            )
            from src.game.effects import EffectEngine as _EffectEngine
            from src.game.effects import FollowerContext as _FollowerContext

            attack_effects_enabled = _has_any_eff(
                getattr(self.device_state, "config", None), trigger="on_attack"
            )
        except Exception:
            attack_effects_enabled = False
            _get_eff_steps = None
            _norm_ops = None
            _EffectEngine = None
            _FollowerContext = None

        try:
            debug_mode = bool(
                isinstance(getattr(self.device_state, "config", None), dict)
                and self.device_state.config.get("ui", {}).get("debug_mode")
            )
        except Exception:
            debug_mode = False

        def _run_on_attack_effects(follower_name: Any, source_pos: Optional[Tuple[Any, Any]] = None) -> None:
            if not attack_effects_enabled:
                return
            if not isinstance(follower_name, str) or not follower_name:
                return
            if _get_eff_steps is None or _norm_ops is None or _EffectEngine is None or _FollowerContext is None:
                return

            pos_xy = None
            try:
                if source_pos is not None and len(source_pos) >= 2:
                    pos_xy = (int(source_pos[0]), int(source_pos[1]))
            except Exception:
                pos_xy = None

            source_uid = self._runtime_uid_for_ours(
                pos_xy,
                fallback_name=str(follower_name or ""),
            )
            effect_key = self._runtime_effect_key_for_ours(
                pos_xy,
                fallback_name=follower_name,
                source_uid=source_uid,
            )

            steps = _get_eff_steps(
                getattr(self.device_state, "config", None), card_name=effect_key, trigger="on_attack"
            )
            ops = _norm_ops(steps)
            if not ops:
                return

            ctx = _FollowerContext(
                device_state=self.device_state,
                follower_name=effect_key,
                cfg_key=str(effect_key or ""),
                follower_pos=pos_xy,
                follower_uid=source_uid,
                existing_followers=list(all_followers or []),
                pre_action_our_followers=list(all_followers or []),
                pre_action_our_follower_count=len(list(all_followers or [])),
                attack_source_pos=pos_xy,
            )
            _EffectEngine.run_ops(ops, ctx=ctx, trigger_id="on_attack")

        shield_targets = []

        # Step3C: attack-phase cache (single phase, local lifetime).
        attack_cache: Dict[str, Any] = {
            "enemy": None,
            "ward": list(shield_targets or []),
            "enemy_dirty": True,
            "ward_dirty": False,
        }

        def _strict_refresh_attack_followers(*, with_names: bool = False, retries: int = 1):
            """Attack-critical scan: 3-shots + retry, no stale-cache fallback."""

            return self._refresh_our_followers(
                sort_desc=True,
                extra_shots=2,
                retries=max(0, int(retries)),
                with_names=bool(with_names),
                allow_cached_fallback=False,
            )

        _named_scan_cache: Dict[str, Any] = {"followers": None, "ts": 0.0}

        def _invalidate_named_scan_cache():
            _named_scan_cache["followers"] = None
            _named_scan_cache["ts"] = 0.0

        def _get_named_followers_cached():
            now = time.time()
            cached = _named_scan_cache.get("followers")
            cache_ts = float(_named_scan_cache.get("ts", 0.0) or 0.0)
            if isinstance(cached, list) and (now - cache_ts) <= 0.35:
                return list(cached)

            named_followers = list(_strict_refresh_attack_followers(with_names=True, retries=0) or [])
            if named_followers:
                self._runtime_sync_ours(named_followers)
            _named_scan_cache["followers"] = list(named_followers)
            _named_scan_cache["ts"] = now
            return named_followers

        def _pick_named_attacker(current_pos: Tuple[Any, Any], *, preferred_type: Optional[str] = None):
            """Refresh with names and rematch attacker by position/type."""

            named_followers = list(_get_named_followers_cached() or [])
            if not named_followers:
                return None

            try:
                cx, cy = int(current_pos[0]), int(current_pos[1])
            except Exception:
                cx, cy = 0, 0

            candidates = list(named_followers)
            if preferred_type:
                typed = [f for f in candidates if len(f) > 2 and str(f[2] or "") == str(preferred_type)]
                if typed:
                    candidates = typed

            best = None
            best_score = 10**9
            for item in candidates:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                try:
                    x_i = int(item[0])
                    y_i = int(item[1])
                except Exception:
                    continue
                score = abs(x_i - cx) * 2 + abs(y_i - cy)
                if score < best_score:
                    best_score = score
                    best = item

            return best

        def _as_int_or_none(v: Any) -> Optional[int]:
            try:
                return int(v)
            except Exception:
                return None

        TARGET_BUCKET_WIDTH = 55
        TARGET_MATCH_TOL = 55
        NO_PROGRESS_BLACKLIST_THRESHOLD = 2

        def _target_bucket(target_xy: Any) -> Optional[int]:
            if not isinstance(target_xy, (list, tuple)) or len(target_xy) < 1:
                return None
            try:
                tx = int(target_xy[0])
            except Exception:
                return None
            return int(round(float(tx) / float(TARGET_BUCKET_WIDTH)))

        def _find_enemy_by_x(rows: Sequence[Sequence[Any]], target_xy: Any) -> Optional[Sequence[Any]]:
            if not isinstance(target_xy, (list, tuple)) or len(target_xy) < 1:
                return None
            try:
                tx = int(target_xy[0])
            except Exception:
                return None

            best = None
            best_dx = 10**9
            for row in list(rows or []):
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                try:
                    ex = int(row[0])
                except Exception:
                    continue
                dx = abs(ex - tx)
                if dx > int(TARGET_MATCH_TOL):
                    continue
                if dx < best_dx:
                    best_dx = dx
                    best = row
            return best

        def _is_ward_at_target(ward_rows: Sequence[Sequence[Any]], target_xy: Any) -> bool:
            return _find_enemy_by_x(list(ward_rows or []), target_xy) is not None

        def _target_progressed(
            *,
            target_xy: Any,
            enemy_before: Sequence[Sequence[Any]],
            enemy_after: Sequence[Sequence[Any]],
            ward_before: Optional[Sequence[Sequence[Any]]] = None,
            ward_after: Optional[Sequence[Sequence[Any]]] = None,
        ) -> bool:
            before_rows = list(enemy_before or [])
            after_rows = list(enemy_after or [])

            if len(after_rows) < len(before_rows):
                return True

            before_target = _find_enemy_by_x(before_rows, target_xy)
            after_target = _find_enemy_by_x(after_rows, target_xy)

            if before_target is not None and after_target is None:
                return True

            hp_before = self._enemy_hp_value(before_target) if before_target is not None else None
            hp_after = self._enemy_hp_value(after_target) if after_target is not None else None
            if hp_before is not None and hp_after is not None and int(hp_after) < int(hp_before):
                return True

            if ward_before is not None and ward_after is not None:
                wb = bool(_is_ward_at_target(list(ward_before or []), target_xy))
                wa = bool(_is_ward_at_target(list(ward_after or []), target_xy))
                if wb and not wa:
                    return True
                if len(list(ward_after or [])) < len(list(ward_before or [])):
                    return True

            return False

        def _scan_enemy_followers_synced(*, ward_positions: Optional[Sequence[Sequence[Any]]] = None):
            shots: List[List[Tuple[Any, Any, Any, Any]]] = []
            total_shots = 3

            for si in range(total_shots):
                try:
                    enemy_screenshot = self.device_state.take_screenshot()
                    if enemy_screenshot is None:
                        one = []
                    else:
                        one = list(self._scan_enemy_followers(enemy_screenshot) or [])
                except Exception:
                    one = []

                if debug_mode:
                    try:
                        self.device_state.logger.info(
                            f"[Scan][enemy/full][{si + 1}/{total_shots}] count={len(one)} result={one}"
                        )
                    except Exception:
                        pass

                shots.append(list(one))
                if si < (total_shots - 1):
                    self.device_state.sleep(0.05)

            def _enemy_score(rows: Sequence[Sequence[Any]]) -> Tuple[int, int]:
                total = len(list(rows or []))
                hp_known = 0
                for it in list(rows or []):
                    if not isinstance(it, (list, tuple)) or len(it) < 4:
                        continue
                    if self._enemy_hp_value(it) is not None:
                        hp_known += 1
                return (int(total), int(hp_known))

            enemy_followers = []
            if shots:
                best = sorted(
                    list(enumerate(shots)),
                    key=lambda it: (_enemy_score(it[1]), int(it[0])),
                    reverse=True,
                )[0]
                enemy_followers = list(best[1] or [])

            if enemy_followers:
                self._runtime_sync_enemy(enemy_followers, ward_targets=list(ward_positions or []))
            return list(enemy_followers or [])

        def _get_enemy_followers_cached(*, force: bool = False, ward_positions=None):
            if force or attack_cache.get("enemy_dirty") or attack_cache.get("enemy") is None:
                refreshed = _scan_enemy_followers_synced(ward_positions=ward_positions)
                attack_cache["enemy"] = list(refreshed or [])
                attack_cache["enemy_dirty"] = False
            return list(attack_cache.get("enemy") or [])

        def _get_ward_targets_cached(*, force: bool = False):
            if force or attack_cache.get("ward_dirty") or attack_cache.get("ward") is None:
                attack_cache["ward"] = list(self._scan_shield_targets() or [])
                attack_cache["ward_dirty"] = False
            return list(attack_cache.get("ward") or [])

        def _mark_enemy_board_dirty() -> None:
            attack_cache["enemy_dirty"] = True
            attack_cache["ward_dirty"] = True

        def _choose_attack_plan(
            enemy_followers: Sequence[Sequence[Any]],
            *,
            attacker_followers: Optional[Sequence[Sequence[Any]]] = None,
            allowed_types: Sequence[str],
            ward_only: bool,
            ward_positions: Optional[Sequence[Sequence[Any]]] = None,
            blocked_target_buckets: Optional[Sequence[int]] = None,
        ):
            """Select attacker+target by type priority and residual minimization.

            Priority:
            1) attacker type order follows ``allowed_types`` (e.g. yellow then green)
            2) within same type, if lethal exists, choose residual closest to 0
            3) if no lethal, fallback to right-to-left first valid plan
            """

            enemy_list = list(enemy_followers or [])
            if not enemy_list:
                return None

            # Use the latest caller-provided follower snapshot; fallback to the
            # phase baseline for compatibility.
            attackers = list(attacker_followers or all_followers or [])
            blocked = {int(b) for b in list(blocked_target_buckets or [])}

            # Important: plan selection must only consider attackers that still
            # have remaining attack uses in this turn.
            unspent_attackers = list(
                _iter_unspent_attackers(attackers, allowed_types=allowed_types)
            )

            for type_priority in list(allowed_types or []):
                candidates = [
                    f
                    for f in unspent_attackers
                    if isinstance(f, (list, tuple)) and len(f) > 2 and str(f[2] or "") == str(type_priority)
                ]
                if not candidates:
                    continue

                plans = []
                for item in candidates:
                    try:
                        fx, fy = int(item[0]), int(item[1])
                    except Exception:
                        continue

                    attacker = (fx, fy)
                    attacker_name = item[3] if len(item) > 3 else None
                    if not attacker_name:
                        named_match = _pick_named_attacker(attacker, preferred_type=str(type_priority))
                        if isinstance(named_match, (list, tuple)) and len(named_match) >= 4:
                            attacker = (int(named_match[0]), int(named_match[1]))
                            attacker_name = named_match[3]

                    target_xy, target_reason = self._pick_enemy_target(
                        attacker,
                        enemy_list,
                        ward_targets=list(ward_positions or []),
                        ward_only=bool(ward_only),
                    )
                    if target_xy is None:
                        continue

                    bucket = _target_bucket(target_xy)
                    if bucket is not None and int(bucket) in blocked:
                        continue

                    mode = str(target_reason.get("mode") or "")
                    residual = _as_int_or_none(target_reason.get("residual"))
                    plans.append(
                        {
                            "attacker": attacker,
                            "attacker_name": attacker_name,
                            "attacker_type": str(type_priority),
                            "target_xy": (int(target_xy[0]), int(target_xy[1])),
                            "reason": target_reason,
                            "mode": mode,
                            "residual": residual,
                        }
                    )

                if not plans:
                    continue

                if debug_mode:
                    try:
                        brief_rows: List[str] = []
                        for p in list(plans or []):
                            ax = int(p.get("attacker", (0, 0))[0])
                            ay = int(p.get("attacker", (0, 0))[1])
                            pname = str(p.get("attacker_name") or "?")
                            reason_obj = p.get("reason")
                            reason = reason_obj if isinstance(reason_obj, dict) else {}
                            brief_rows.append(
                                f"{pname}@({ax},{ay}) mode={p.get('mode')} "
                                f"atk={reason.get('attacker_atk')} hp={reason.get('target_hp')} "
                                f"residual={p.get('residual')}"
                            )
                        self.device_state.logger.info(
                            f"[AttackPlan] type={str(type_priority)} ward_only={bool(ward_only)} "
                            f"candidates={' | '.join(brief_rows)}"
                        )
                    except Exception:
                        pass

                kill_plans = [
                    p for p in plans if p.get("mode") == "kill_overflow" and p.get("residual") is not None
                ]
                if kill_plans:
                    kill_plans = sorted(
                        kill_plans,
                        key=lambda p: (int(p.get("residual") or -999), int(p["attacker"][0])),
                        reverse=True,
                    )
                    return kill_plans[0]

                # No lethal in this type: keep existing behavior (right-to-left first available).
                return plans[0]

            return None

        attacker_attack_caps: Dict[int, int] = {}
        attacker_attack_used: Dict[int, int] = {}
        attacker_key_meta: Dict[int, Dict[str, Any]] = {}
        next_attacker_key = -1

        def _norm_name(v: Any) -> Optional[str]:
            if not isinstance(v, str):
                return None
            s = str(v or "").strip()
            return s or None

        def _resolve_attacker_key(pos_xy: Sequence[Any], *, name_hint: Any = None) -> int:
            nonlocal next_attacker_key

            if not isinstance(pos_xy, (list, tuple)) or len(pos_xy) < 2:
                return 0
            try:
                x_i = int(pos_xy[0])
                y_i = int(pos_xy[1])
            except Exception:
                return 0

            name = _norm_name(name_hint)
            slot_i = int(self._slot_id_for_x(x_i))

            uid_key = self._runtime_uid_for_ours((x_i, y_i), fallback_name=str(name or ""))
            if uid_key is not None and int(uid_key) > 0:
                meta = attacker_key_meta.get(int(uid_key), {})
                if not isinstance(meta, dict):
                    meta = {}
                meta["x"] = int(x_i)
                meta["y"] = int(y_i)
                meta["slot"] = int(slot_i)
                if name:
                    meta["name"] = name
                attacker_key_meta[int(uid_key)] = meta
                return int(uid_key)

            by_pos_tol = 72
            by_slot_tol = 110
            by_y_tol = 130

            best_key = None
            best_score = 10**9

            for key_i, meta in list(attacker_key_meta.items()):
                # Fallback keys are negative. Positive keys are runtime uid and
                # should be resolved in the uid path above.
                if int(key_i) > 0:
                    continue
                mx = int(meta.get("x", x_i))
                my = int(meta.get("y", y_i))
                dx = abs(mx - x_i)
                dy = abs(my - y_i)
                mslot = int(meta.get("slot", -1))
                same_slot = mslot == int(slot_i)

                if not same_slot and dx > by_pos_tol:
                    continue
                if same_slot and dx > by_slot_tol:
                    continue
                if dy > by_y_tol:
                    continue

                score = dx * 2 + dy
                if same_slot:
                    score -= 90

                if name:
                    mname = _norm_name(meta.get("name"))
                    if mname and mname == name:
                        score -= 120
                    elif mname:
                        score += 160

                if score < best_score:
                    best_score = score
                    best_key = int(key_i)

            if best_key is None:
                best_key = int(next_attacker_key)
                next_attacker_key -= 1

            meta = attacker_key_meta.get(best_key, {})
            if not isinstance(meta, dict):
                meta = {}
            old_x = int(meta.get("x", x_i))
            meta["x"] = int(round((old_x + x_i) / 2.0))
            meta["y"] = int(y_i)
            meta["slot"] = int(slot_i)
            if name:
                meta["name"] = name
            attacker_key_meta[best_key] = meta
            return int(best_key)

        def _attack_cap_for_attacker(pos_xy: Sequence[Any], *, name_hint: Any = None) -> int:
            key_i = _resolve_attacker_key(pos_xy, name_hint=name_hint)
            # key_i == 0 means unresolved/invalid attacker. Negative keys are
            # valid fallback ids and should keep attack cap bookkeeping.
            if key_i == 0:
                return 1

            cached_cap = max(1, int(attacker_attack_caps.get(key_i, 1) or 1))
            if key_i > 0:
                runtime_cap = self._runtime_attack_times_for_ours_uid(key_i)
            else:
                runtime_cap = self._runtime_attack_times_for_ours((int(pos_xy[0]), int(pos_xy[1])))
            cap = max(cached_cap, max(1, int(runtime_cap or 1)))
            attacker_attack_caps[key_i] = int(cap)
            return int(cap)

        def _consume_attack_use(pos_xy: Sequence[Any], *, name_hint: Any = None) -> Tuple[int, int, int]:
            key_i = _resolve_attacker_key(pos_xy, name_hint=name_hint)
            if key_i == 0:
                return (0, 1, 0)

            cap = _attack_cap_for_attacker(pos_xy, name_hint=name_hint)
            used = int(attacker_attack_used.get(key_i, 0) or 0) + 1
            attacker_attack_used[key_i] = int(used)
            remain = max(0, int(cap) - int(used))
            return (int(used), int(cap), int(remain))

        def _iter_unspent_attackers(
            followers: Any,
            *,
            allowed_types: Sequence[str],
        ):
            allowed = {str(t) for t in list(allowed_types or [])}
            for item in list(followers or []):
                if not isinstance(item, (list, tuple)) or len(item) < 3:
                    continue
                t_s = str(item[2] or "")
                if t_s not in allowed:
                    continue
                name_hint = item[3] if len(item) > 3 else None
                key_i = _resolve_attacker_key((item[0], item[1]), name_hint=name_hint)
                cap = _attack_cap_for_attacker((item[0], item[1]), name_hint=name_hint)
                used = int(attacker_attack_used.get(key_i, 0) or 0)
                if used >= cap:
                    continue
                yield item

        def _has_attack_followers(
            followers: Any,
            *,
            allowed_types: Sequence[str] = ("green", "yellow"),
        ) -> bool:
            try:
                return any(True for _ in _iter_unspent_attackers(followers, allowed_types=allowed_types))
            except Exception:
                return False

        def _local_consume_attacker_slot(
            followers: Any,
            attacker_pos: Sequence[Any],
            *,
            force_normal: bool = True,
            attacker_name: Any = None,
        ) -> List[Tuple[Any, Any, Any, Any]]:
            if not isinstance(attacker_pos, (list, tuple)) or len(attacker_pos) < 2:
                return list(followers or [])
            try:
                target_x = int(attacker_pos[0])
                target_y = int(attacker_pos[1])
            except Exception:
                return list(followers or [])

            name_hint = _norm_name(attacker_name)
            match_idx = None
            best_score = 10**9
            items = list(followers or [])

            for idx, item in enumerate(items):
                if not isinstance(item, (list, tuple)) or len(item) < 3:
                    continue
                try:
                    x_i = int(item[0])
                    y_i = int(item[1])
                except Exception:
                    continue
                n_s = _norm_name(item[3] if len(item) > 3 else None)

                if name_hint and n_s == name_hint:
                    score = abs(x_i - target_x) * 2 + abs(y_i - target_y)
                    if score < best_score:
                        best_score = score
                        match_idx = idx

            if match_idx is None:
                for idx, item in enumerate(items):
                    if not isinstance(item, (list, tuple)) or len(item) < 3:
                        continue
                    try:
                        x_i = int(item[0])
                        y_i = int(item[1])
                    except Exception:
                        continue
                    dx = abs(x_i - target_x)
                    if dx > 45:
                        continue
                    score = dx * 2 + abs(y_i - target_y)
                    if score < best_score:
                        best_score = score
                        match_idx = idx

            if match_idx is None:
                for idx, item in enumerate(items):
                    if not isinstance(item, (list, tuple)) or len(item) < 3:
                        continue
                    try:
                        x_i = int(item[0])
                        y_i = int(item[1])
                    except Exception:
                        continue
                    score = abs(x_i - target_x) * 2 + abs(y_i - target_y)
                    if score < best_score:
                        best_score = score
                        match_idx = idx

            consumed: List[Tuple[Any, Any, Any, Any]] = []
            for idx, item in enumerate(items):
                if not isinstance(item, (list, tuple)) or len(item) < 3:
                    continue
                try:
                    x_i = int(item[0])
                    y_i = int(item[1])
                except Exception:
                    continue
                t_s = str(item[2] or "normal")
                n_s = item[3] if len(item) > 3 else None
                if force_normal and match_idx is not None and idx == int(match_idx):
                    t_s = "normal"
                consumed.append((x_i, y_i, t_s, n_s))

            try:
                consumed = sorted(consumed, key=lambda f: int(f[0]), reverse=True)
            except Exception:
                pass
            return consumed

        self._ensure_runtime_epoch()

        # Attack baseline: ours(handled by caller), enemy + ward one-shot at phase start.
        shield_targets = _get_ward_targets_cached(force=True)
        _ = _get_enemy_followers_cached(force=True, ward_positions=shield_targets)
        max_attack_attempts = 6


        # 攻击阶段：从右往左优先处理（新召唤随从通常出现在右侧）。
        # 默认使用带命名的严格扫描，避免先无名再补名的重复开销。
        if all_followers is None:
            all_followers = list(_strict_refresh_attack_followers(with_names=True, retries=0) or [])
            _invalidate_named_scan_cache()
        else:
            # Ensure expected order (right -> left)
            try:
                all_followers = sorted(
                    list(all_followers or []),
                    key=lambda f: int(f[0]) if len(f) > 0 else 0,
                    reverse=True,
                )
            except Exception:
                all_followers = list(all_followers or [])
        all_followers = list(all_followers or [])

        self._runtime_sync_ours(all_followers)

        # Structured observation log (no extra recognition).
        enemy_positions = enemy_check if isinstance(enemy_check, (list, tuple)) else []
        self._log_observed_state(note="attack/start", enemy=enemy_positions, ward=shield_targets)

        if not _has_attack_followers(all_followers):
            self.device_state.logger.info("未检测到可进行攻击的随从，跳过攻击操作")
            return

        def _run_shield_break_phase(
            current_followers: List[Tuple[Any, Any, Any, Any]],
            current_shield_targets: List[Tuple[Any, Any, Any, Any]],
        ) -> Tuple[bool, List[Tuple[Any, Any, Any, Any]], List[Tuple[Any, Any, Any, Any]]]:
            if not current_shield_targets:
                return True, list(current_followers or []), list(current_shield_targets or [])

            max_attempts = int(max_attack_attempts)
            attempt_count = 0
            ward_target_blacklist: set[int] = set()
            ward_target_fail_streak: Dict[int, int] = {}

            while current_shield_targets and attempt_count < max_attempts:
                attempt_count += 1
                self.device_state.logger.info(f"破盾尝试第{attempt_count}/{max_attempts}次")

                if current_shield_targets:
                    remaining_ward_targets = [
                        w
                        for w in list(current_shield_targets or [])
                        if _target_bucket(w) not in ward_target_blacklist
                    ]
                    if not remaining_ward_targets:
                        self.device_state.logger.warning("守护目标连续无效已全部黑名单，按无守护流程继续")
                        break

                enemy_followers = _get_enemy_followers_cached(
                    force=False,
                    ward_positions=current_shield_targets,
                )

                # 护盾阶段默认关闭“最近者策略”。保留开关便于快速回退。
                use_nearest_shield_attacker = False
                selected_plan = None
                if use_nearest_shield_attacker:
                    for type_priority in ("yellow", "green"):
                        type_followers = [
                            f
                            for f in (current_followers or [])
                            if isinstance(f, (list, tuple)) and len(f) > 2 and str(f[2] or "") == type_priority
                        ]
                        if not type_followers:
                            continue

                        pick = type_followers[0]
                        try:
                            selected_plan = {
                                "attacker": (int(pick[0]), int(pick[1])),
                                "attacker_name": pick[3] if len(pick) > 3 else None,
                                "attacker_type": type_priority,
                            }
                        except Exception:
                            selected_plan = None
                        if selected_plan:
                            break
                else:
                    selected_plan = _choose_attack_plan(
                        enemy_followers,
                        attacker_followers=current_followers,
                        allowed_types=("yellow", "green"),
                        ward_only=True,
                        ward_positions=current_shield_targets,
                        blocked_target_buckets=list(ward_target_blacklist),
                    )

                if not isinstance(selected_plan, dict):
                    if current_shield_targets and all(
                        _target_bucket(w) in ward_target_blacklist for w in list(current_shield_targets or [])
                    ):
                        self.device_state.logger.warning("守护目标均被黑名单过滤，忽略守护进入无守护流程")
                        break
                    self.device_state.logger.info("没有可用的突进/疾驰随从攻击护盾")
                    return False, list(current_followers or []), list(current_shield_targets or [])

                raw_attacker = selected_plan.get("attacker")
                if not isinstance(raw_attacker, (list, tuple)) or len(raw_attacker) < 2:
                    self.device_state.logger.info("护盾阶段未找到有效攻击随从")
                    return False, list(current_followers or []), list(current_shield_targets or [])
                selected_follower = (int(raw_attacker[0]), int(raw_attacker[1]))

                selected_follower_name = selected_plan.get("attacker_name")
                selected_type = str(selected_plan.get("attacker_type") or "")
                reason_raw = selected_plan.get("reason")
                target_reason: Dict[str, Any] = reason_raw if isinstance(reason_raw, dict) else {}
                shield_xy = selected_plan.get("target_xy")
                if isinstance(shield_xy, (list, tuple)) and len(shield_xy) >= 2:
                    shield_x, shield_y = int(shield_xy[0]), int(shield_xy[1])
                else:
                    shield_x, shield_y = int(current_shield_targets[-1][0]), int(current_shield_targets[-1][1])
                enemy_before = list(enemy_followers or [])
                ward_before = list(current_shield_targets or [])

                if not selected_follower_name:
                    named_match = _pick_named_attacker(
                        selected_follower,
                        preferred_type=selected_type,
                    )
                    if isinstance(named_match, (list, tuple)) and len(named_match) >= 4:
                        selected_follower = (int(named_match[0]), int(named_match[1]))
                        selected_follower_name = named_match[3]

                self.device_state.logger.info(
                    "护盾目标选择: "
                    f"mode={target_reason.get('mode')} atk={target_reason.get('attacker_atk')} "
                    f"hp={target_reason.get('target_hp')} residual={target_reason.get('residual')}"
                )

                selected_type_key = str(selected_type or "")
                type_name = type_name_map.get(selected_type_key, selected_type_key or "可攻击")
                if selected_follower_name:
                    self.device_state.logger.info(
                        f"使用{type_name}随从[{selected_follower_name}]攻击护盾"
                    )
                else:
                    self.device_state.logger.info(f"使用{type_name}随从攻击护盾")

                human_like_drag(
                    self._require_u2_device(),
                    selected_follower[0],
                    selected_follower[1],
                    shield_x,
                    shield_y,
                    duration=random.uniform(*settings.get_human_like_drag_duration_range()),
                )
                self.device_state.sleep(ATTACK_SETTLE_SLEEP_COMBAT)
                _run_on_attack_effects(selected_follower_name, selected_follower)
                used_cnt, cap_cnt, remain_cnt = _consume_attack_use(
                    selected_follower,
                    name_hint=selected_follower_name,
                )
                if remain_cnt <= 0:
                    try:
                        runtime = getattr(self, "battle_runtime", None)
                        if runtime is not None and hasattr(runtime, "mark_our_attack_spent"):
                            runtime.mark_our_attack_spent(selected_follower, fallback_name=str(selected_follower_name or ""))
                    except Exception:
                        pass
                    self._mark_recent_attack_slot(selected_follower)
                current_followers = _local_consume_attacker_slot(
                    current_followers,
                    selected_follower,
                    force_normal=bool(remain_cnt <= 0),
                    attacker_name=selected_follower_name,
                )

                combat = self._runtime_apply_local_combat(selected_follower, (shield_x, shield_y))
                if combat.get("applied"):
                    self.device_state.logger.info(
                        "本地结算(护盾): "
                        f"atk={combat.get('attacker_atk')} "
                        f"target_hp={combat.get('target_hp_before')}->{combat.get('target_hp_after')} "
                        f"target_dead={combat.get('target_dead')}"
                    )

                if not _has_attack_followers(current_followers):
                    self.device_state.logger.info("攻击后没有可用的突进/疾驰随从，停止破盾")
                    return False, list(current_followers or []), list(current_shield_targets or [])

                # 仍有可攻击随从时再重扫更新（避免末次攻击后的无效重扫）
                current_followers = list(_strict_refresh_attack_followers(with_names=True, retries=0) or [])
                _invalidate_named_scan_cache()
                self._runtime_sync_ours(current_followers)
                _mark_enemy_board_dirty()

                # 重新扫描护盾，检查当前护盾是否还在
                current_shield_targets = _get_ward_targets_cached(force=True)
                enemy_after = _get_enemy_followers_cached(force=True, ward_positions=current_shield_targets)

                progressed = _target_progressed(
                    target_xy=(shield_x, shield_y),
                    enemy_before=enemy_before,
                    enemy_after=enemy_after,
                    ward_before=ward_before,
                    ward_after=current_shield_targets,
                )
                target_bucket = _target_bucket((shield_x, shield_y))
                if progressed:
                    if target_bucket is not None:
                        ward_target_fail_streak.pop(int(target_bucket), None)
                else:
                    if target_bucket is not None:
                        streak = int(ward_target_fail_streak.get(int(target_bucket), 0) or 0) + 1
                        ward_target_fail_streak[int(target_bucket)] = int(streak)
                        if streak >= int(NO_PROGRESS_BLACKLIST_THRESHOLD):
                            if int(target_bucket) not in ward_target_blacklist:
                                ward_target_blacklist.add(int(target_bucket))
                                self.device_state.logger.warning(
                                    "护盾目标连续2次攻击无变化，加入黑名单 "
                                    f"bucket={int(target_bucket)} x={int(shield_x)}"
                                )

                self.device_state.sleep(0.2)
            
            # 检查是否因为达到最大尝试次数而退出循环
            if attempt_count >= max_attempts and current_shield_targets:
                self.device_state.logger.warning(f"达到最大破盾尝试次数({max_attempts}次)，停止破盾操作")

            # 破盾结束后，基于最新扫描结果决定是否继续后续攻击
            if current_shield_targets:
                remaining_ward_targets = [
                    w
                    for w in list(current_shield_targets or [])
                    if _target_bucket(w) not in ward_target_blacklist
                ]
                if not remaining_ward_targets:
                    self.device_state.logger.warning("剩余守护目标均疑似不可攻击，忽略守护进入无守护流程")
                    current_shield_targets = []
                else:
                    # 护盾仍存在：继续攻击脸/随从都会被护盾干扰，直接结束攻击阶段
                    self.device_state.logger.info("护盾仍存在，停止后续攻击操作")
                    return False, list(current_followers or []), list(current_shield_targets or [])

            return True, list(current_followers or []), list(current_shield_targets or [])

        can_continue, all_followers, shield_targets = _run_shield_break_phase(
            list(all_followers or []),
            list(shield_targets or []),
        )
        if not can_continue:
            return

        def _run_green_face_phase(
            current_followers: List[Tuple[Any, Any, Any, Any]],
        ) -> List[Tuple[Any, Any, Any, Any]]:
            # 无护盾阶段统一策略：先疾驰打脸。
            seed_named = list(
                _strict_refresh_attack_followers(
                    with_names=bool(attack_effects_enabled),
                    retries=0,
                )
                or []
            )
            if seed_named:
                current_followers = seed_named
                self._runtime_sync_ours(current_followers)

            max_green_attacks = int(max_attack_attempts)
            green_attack_count = 0
            while green_attack_count < max_green_attacks:
                green_followers = list(
                    _iter_unspent_attackers(current_followers, allowed_types=("green",))
                )
                if not green_followers:
                    break

                pick = green_followers[0]  # 已按x从右到左排序
                x, y = int(pick[0]), int(pick[1])
                name = pick[3] if len(pick) > 3 else None

                if not name and attack_effects_enabled:
                    named_match = _pick_named_attacker((x, y), preferred_type="green")
                    if isinstance(named_match, (list, tuple)) and len(named_match) >= 4:
                        x, y = int(named_match[0]), int(named_match[1])
                        name = named_match[3]

                if name:
                    self.device_state.logger.info(f"使用疾驰随从[{name}]攻击敌方玩家")
                else:
                    self.device_state.logger.info("使用疾驰随从攻击敌方玩家")

                target_x, target_y = default_target
                human_like_drag(
                    self._require_u2_device(),
                    x,
                    y,
                    target_x,
                    target_y,
                    duration=random.uniform(*settings.get_human_like_drag_duration_range()),
                )
                green_attack_count += 1
                self.device_state.sleep(ATTACK_SETTLE_SLEEP_FACE)

                _run_on_attack_effects(name, (x, y))
                used_cnt, cap_cnt, remain_cnt = _consume_attack_use(
                    (x, y),
                    name_hint=name,
                )
                if remain_cnt <= 0:
                    try:
                        runtime = getattr(self, "battle_runtime", None)
                        if runtime is not None and hasattr(runtime, "mark_our_attack_spent"):
                            runtime.mark_our_attack_spent((x, y), fallback_name=str(name or ""))
                    except Exception:
                        pass
                    self._mark_recent_attack_slot((x, y))
                current_followers = _local_consume_attacker_slot(
                    current_followers,
                    (x, y),
                    force_normal=bool(remain_cnt <= 0),
                    attacker_name=name,
                )
                if cap_cnt > 1 and remain_cnt > 0:
                    self.device_state.logger.info(
                        f"同一随从可继续攻击: {used_cnt}/{cap_cnt}"
                    )

                if not _has_attack_followers(current_followers, allowed_types=("green",)):
                    self.device_state.logger.info("疾驰随从已全部完成攻击")
                    break

            return list(current_followers or [])

        def _run_yellow_trade_phase(
            current_followers: List[Tuple[Any, Any, Any, Any]],
        ) -> List[Tuple[Any, Any, Any, Any]]:
            # 疾驰打脸后，再由突进处理敌方随从。
            enemy_present = bool(_get_enemy_followers_cached(force=False, ward_positions=None))
            max_yellow_attacks = int(max_attack_attempts)
            yellow_attack_count = 0
            enemy_target_blacklist: set[int] = set()
            enemy_target_fail_streak: Dict[int, int] = {}

            while enemy_present and yellow_attack_count < max_yellow_attacks:
                yellow_followers = list(
                    _iter_unspent_attackers(current_followers, allowed_types=("yellow",))
                )
                if not yellow_followers:
                    break

                enemy_followers = _get_enemy_followers_cached(force=False, ward_positions=None)
                if not enemy_followers:
                    self.device_state.logger.info("未检测到敌方随从，突进攻击结束")
                    break

                if enemy_followers and all(
                    _target_bucket(e) in enemy_target_blacklist for e in list(enemy_followers or [])
                ):
                    self.device_state.logger.warning("敌方可选目标均在黑名单，结束突进攻击")
                    break

                plan = _choose_attack_plan(
                    enemy_followers,
                    attacker_followers=current_followers,
                    allowed_types=("yellow",),
                    ward_only=False,
                    ward_positions=None,
                    blocked_target_buckets=list(enemy_target_blacklist),
                )
                if not isinstance(plan, dict):
                    self.device_state.logger.info("突进未找到可攻击目标，结束突进攻击")
                    break

                selected_follower = tuple(plan.get("attacker") or ())
                if len(selected_follower) < 2:
                    self.device_state.logger.info("突进阶段未找到有效攻击随从")
                    break

                selected_follower_name = plan.get("attacker_name")
                target_reason = dict(plan.get("reason") or {})
                target_xy = plan.get("target_xy")
                if not (isinstance(target_xy, (list, tuple)) and len(target_xy) >= 2):
                    self.device_state.logger.info("突进未找到有效目标坐标，结束突进攻击")
                    break

                if not selected_follower_name:
                    named_match = _pick_named_attacker(selected_follower, preferred_type="yellow")
                    if isinstance(named_match, (list, tuple)) and len(named_match) >= 4:
                        selected_follower = (int(named_match[0]), int(named_match[1]))
                        selected_follower_name = named_match[3]

                enemy_x, enemy_y = int(target_xy[0]), int(target_xy[1])
                enemy_before = list(enemy_followers or [])

                if selected_follower_name:
                    self.device_state.logger.info(
                        f"使用突进随从[{selected_follower_name}]攻击敌方随从 mode={target_reason.get('mode')} "
                        f"atk={target_reason.get('attacker_atk')} hp={target_reason.get('target_hp')} "
                        f"residual={target_reason.get('residual')}"
                    )
                else:
                    self.device_state.logger.info(
                        "使用突进随从攻击敌方随从 "
                        f"mode={target_reason.get('mode')} atk={target_reason.get('attacker_atk')} "
                        f"hp={target_reason.get('target_hp')} residual={target_reason.get('residual')}"
                    )

                human_like_drag(
                    self._require_u2_device(),
                    selected_follower[0],
                    selected_follower[1],
                    enemy_x,
                    enemy_y,
                    duration=random.uniform(*settings.get_human_like_drag_duration_range()),
                )
                yellow_attack_count += 1
                self.device_state.sleep(ATTACK_SETTLE_SLEEP_COMBAT)
                _run_on_attack_effects(selected_follower_name, selected_follower)
                used_cnt, cap_cnt, remain_cnt = _consume_attack_use(
                    selected_follower,
                    name_hint=selected_follower_name,
                )
                if remain_cnt <= 0:
                    try:
                        runtime = getattr(self, "battle_runtime", None)
                        if runtime is not None and hasattr(runtime, "mark_our_attack_spent"):
                            runtime.mark_our_attack_spent(selected_follower, fallback_name=str(selected_follower_name or ""))
                    except Exception:
                        pass
                    self._mark_recent_attack_slot(selected_follower)
                current_followers = _local_consume_attacker_slot(
                    current_followers,
                    selected_follower,
                    force_normal=bool(remain_cnt <= 0),
                    attacker_name=selected_follower_name,
                )

                combat = self._runtime_apply_local_combat(selected_follower, (enemy_x, enemy_y))
                if combat.get("applied"):
                    self.device_state.logger.info(
                        "本地结算(突进): "
                        f"atk={combat.get('attacker_atk')} "
                        f"target_hp={combat.get('target_hp_before')}->{combat.get('target_hp_after')} "
                        f"target_dead={combat.get('target_dead')}"
                    )

                _mark_enemy_board_dirty()
                enemy_after = _get_enemy_followers_cached(force=True, ward_positions=None)
                progressed = _target_progressed(
                    target_xy=(enemy_x, enemy_y),
                    enemy_before=enemy_before,
                    enemy_after=enemy_after,
                )
                target_bucket = _target_bucket((enemy_x, enemy_y))
                if progressed:
                    if target_bucket is not None:
                        enemy_target_fail_streak.pop(int(target_bucket), None)
                else:
                    if target_bucket is not None:
                        streak = int(enemy_target_fail_streak.get(int(target_bucket), 0) or 0) + 1
                        enemy_target_fail_streak[int(target_bucket)] = int(streak)
                        if streak >= int(NO_PROGRESS_BLACKLIST_THRESHOLD):
                            if int(target_bucket) not in enemy_target_blacklist:
                                enemy_target_blacklist.add(int(target_bucket))
                                self.device_state.logger.warning(
                                    "敌方目标连续2次攻击无变化，加入黑名单 "
                                    f"bucket={int(target_bucket)} x={int(enemy_x)}"
                                )

                enemy_present = bool(enemy_after)
                if not _has_attack_followers(current_followers, allowed_types=("yellow",)):
                    self.device_state.logger.info("突进随从已全部完成攻击")
                    break

                # 仍有突进随从可攻击时再重扫。
                current_followers = list(_strict_refresh_attack_followers(with_names=True, retries=0) or [])
                _invalidate_named_scan_cache()
                self._runtime_sync_ours(current_followers)

            return list(current_followers or [])

        all_followers = _run_green_face_phase(list(all_followers or []))
        all_followers = _run_yellow_trade_phase(list(all_followers or []))

    def _sort_followers_for_evolution(
        self,
        all_followers: Sequence[FollowerState],
        runtime_cfg: Optional[dict[str, object]],
    ) -> list[FollowerState]:
        evolve_priority_followers: list[FollowerState] = []
        other_followers: list[FollowerState] = []

        for follower in list(all_followers or []):
            follower_name = follower[3] if len(follower) > 3 else None
            if follower_name and is_evolve_priority_card(str(follower_name), runtime_cfg):
                evolve_priority_followers.append(follower)
            else:
                other_followers.append(follower)

        type_priority = {"green": 0, "yellow": 1, "normal": 2}
        sorted_evolve_priority = sorted(
            evolve_priority_followers,
            key=lambda follower: (
                get_evolve_priority(str(follower[3] if len(follower) > 3 else ""), runtime_cfg),
                type_priority.get(follower[2], 3),
                follower[0],
            ),
        )
        sorted_others = sorted(
            other_followers,
            key=lambda follower: (type_priority.get(follower[2], 3), follower[0]),
        )
        return list(sorted_evolve_priority + sorted_others)

    def _find_follower_meta_for_position(
        self,
        all_followers: Sequence[FollowerState],
        pos: tuple[int, int],
    ) -> tuple[Optional[str], Optional[str]]:
        x, y = int(pos[0]), int(pos[1])
        position_tolerance = POSITION_RANDOM_RANGE["medium"]
        for follower in list(all_followers or []):
            if abs(int(follower[0]) - x) < position_tolerance and abs(int(follower[1]) - y) < position_tolerance:
                follower_type = str(follower[2]) if len(follower) > 2 else None
                follower_name = str(follower[3]) if len(follower) > 3 and follower[3] else None
                return follower_type, follower_name
        return None, None

    def _is_enemy_board_empty_for_evolve(self) -> bool:
        cached_enemy_presence = getattr(self, "_cached_enemy_presence_for_evolve", None)
        if cached_enemy_presence is not None:
            return not bool(cached_enemy_presence)

        screenshot = self.device_state.take_screenshot()
        if screenshot is None:
            return False
        try:
            return not bool(self._scan_enemy_ATK(screenshot))
        except Exception:
            return False

    def _disallows_empty_evolve_trigger(
        self,
        follower_name: Optional[str],
        *,
        trigger: str,
        runtime_cfg: Optional[dict[str, object]],
    ) -> bool:
        name = str(follower_name or "")
        if not name:
            return False
        return card_effect_has_op(
            runtime_cfg,
            card_name=name,
            trigger=trigger,
            op_id="disallow_empty_evolve",
        )

    def _disallows_all_available_empty_evolve(
        self,
        follower_name: Optional[str],
        *,
        runtime_cfg: Optional[dict[str, object]],
    ) -> bool:
        available_triggers: list[str] = []
        if getattr(self.device_state, "super_evolution_point", 0) > 0:
            available_triggers.append("on_super_evolve")
        if getattr(self.device_state, "evolution_point", 0) > 0:
            available_triggers.append("on_evolve")
        if not available_triggers:
            return False
        return all(
            self._disallows_empty_evolve_trigger(
                follower_name,
                trigger=trigger,
                runtime_cfg=runtime_cfg,
            )
            for trigger in available_triggers
        )

    def _mark_runtime_evolution(
        self,
        pos: tuple[int, int],
        follower_name: Optional[str],
        evolve_uid: Optional[int],
        mode: str,
    ) -> None:
        try:
            runtime = getattr(self, "battle_runtime", None)
            if runtime is None:
                return

            marked = False
            if evolve_uid is not None and hasattr(runtime, "mark_our_evolution_by_uid"):
                marked = bool(runtime.mark_our_evolution_by_uid(evolve_uid, mode))

            if not marked:
                effect_key = self._runtime_effect_key_for_ours(
                    pos,
                    fallback_name=str(follower_name or ""),
                    source_uid=evolve_uid,
                )
                runtime.mark_our_evolution(
                    pos,
                    mode,
                    cfg_key=str(effect_key or ""),
                    fallback_name=str(follower_name or ""),
                )
        except Exception:
            pass

    @staticmethod
    def _pick_highest_hp_enemy(
        enemy_followers: Sequence[EnemyFollowerState],
    ) -> Optional[EnemyFollowerState]:
        if not enemy_followers:
            return None
        try:
            return max(
                list(enemy_followers or []),
                key=lambda follower: int(follower[3]) if isinstance(follower[3], (int, str)) and str(follower[3]).isdigit() else 0,
            )
        except Exception:
            return list(enemy_followers)[0]

    @staticmethod
    def _normalize_follower_rows(rows: Sequence[object]) -> list[FollowerState]:
        normalized: list[FollowerState] = []
        for row in list(rows or []):
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            try:
                x = int(row[0])
                y = int(row[1])
            except Exception:
                continue
            follower_type = str(row[2] or "normal")
            follower_name = str(row[3]) if len(row) > 3 and row[3] else None
            normalized.append((x, y, follower_type, follower_name))
        return normalized

    @staticmethod
    def _normalize_enemy_followers(rows: Sequence[object]) -> list[EnemyFollowerState]:
        normalized: list[EnemyFollowerState] = []
        for row in list(rows or []):
            if not isinstance(row, (list, tuple)) or len(row) < 4:
                continue
            try:
                x = int(row[0])
                y = int(row[1])
            except Exception:
                continue
            normalized.append((x, y, row[2], row[3]))
        return normalized

    def _try_super_evolution_attack_follow_up(
        self,
        pos: tuple[int, int],
        follower_name: Optional[str],
        follower_type: Optional[str],
    ) -> None:
        if str(follower_type or "") not in {"yellow", "normal"}:
            return

        self.device_state.sleep(1)
        shield_targets = self._scan_shield_targets()
        if bool(shield_targets):
            return

        screenshot = self.device_state.take_screenshot()
        if screenshot is None:
            return

        enemy_followers = self._normalize_enemy_followers(self._scan_enemy_followers(screenshot))
        if not enemy_followers:
            return

        max_hp_follower = self._pick_highest_hp_enemy(enemy_followers)
        if not max_hp_follower:
            return

        enemy_x, enemy_y = int(max_hp_follower[0]), int(max_hp_follower[1])
        human_like_drag(
            self._require_u2_device(),
            pos[0],
            pos[1],
            enemy_x,
            enemy_y,
            duration=random.uniform(*settings.get_human_like_drag_duration_range()),
        )
        runtime = getattr(self, "battle_runtime", None)
        if runtime is not None and hasattr(runtime, "mark_our_attack_spent"):
            try:
                uid = self._runtime_uid_for_ours(pos, fallback_name=str(follower_name or ""))
                runtime.mark_our_attack_spent(
                    pos,
                    follower_uid=uid,
                    fallback_name=str(follower_name or ""),
                )
            except Exception:
                pass
        try:
            self._mark_recent_attack_slot(pos)
        except Exception:
            pass
        self.device_state.sleep(1)
        if follower_name:
            self.device_state.logger.info(f"超进化了[{follower_name}]并攻击了敌方较高血量随从")
        else:
            self.device_state.logger.info("超进化了突进/普通随从攻击了敌方较高血量随从")

    def _try_apply_super_evolution(
        self,
        new_screenshot_cv: object,
        pos: tuple[int, int],
        follower_name: Optional[str],
        follower_type: Optional[str],
        evolve_uid: Optional[int],
        all_followers: Sequence[FollowerState],
        runtime_cfg: Optional[dict[str, object]],
    ) -> bool:
        max_loc, max_val = self._detect_super_evolution_button(new_screenshot_cv)
        if max_val < 0.80 or max_loc is None:
            return False

        template_info = self._load_super_evolution_template()
        if not template_info:
            return False

        center_x = int(max_loc[0]) + int(template_info["w"]) // 2
        center_y = int(max_loc[1]) + int(template_info["h"]) // 2
        self._require_u2_device().click(center_x, center_y)
        self.device_state.sleep(0.4)

        if follower_name:
            special_ok = self._handle_evolve_special_action(
                follower_name,
                pos,
                is_super_evolution=True,
                existing_followers=all_followers,
                follower_uid=evolve_uid,
            )
            if not special_ok:
                return False

        self.device_state.sleep(4.8)
        self.device_state.super_evolution_point -= 1
        if follower_name:
            if is_evolve_priority_card(follower_name, runtime_cfg):
                self.device_state.logger.info(f"优先超进化了[{follower_name}]")
            self.device_state.logger.info(
                f"超进化了[{follower_name}]，剩余超进化次数：{self.device_state.super_evolution_point}"
            )
        else:
            self.device_state.logger.info(
                f"检测到超进化按钮并点击，剩余超进化次数：{self.device_state.super_evolution_point}"
            )

        self._mark_runtime_evolution(
            pos,
            follower_name=follower_name,
            evolve_uid=evolve_uid,
            mode="super",
        )

        self._try_super_evolution_attack_follow_up(
            pos,
            follower_name=follower_name,
            follower_type=follower_type,
        )
        return True

    def _try_apply_normal_evolution(
        self,
        new_screenshot_cv: object,
        pos: tuple[int, int],
        follower_name: Optional[str],
        evolve_uid: Optional[int],
        all_followers: Sequence[FollowerState],
        runtime_cfg: Optional[dict[str, object]],
    ) -> bool:
        max_loc, max_val = self._detect_evolution_button(new_screenshot_cv)
        if max_val < 0.80 or max_loc is None:
            return False

        template_info = self._load_evolution_template()
        if not template_info:
            return False

        center_x = int(max_loc[0]) + int(template_info["w"]) // 2
        center_y = int(max_loc[1]) + int(template_info["h"]) // 2
        self._require_u2_device().click(center_x, center_y)
        self.device_state.sleep(0.4)

        if follower_name:
            special_ok = self._handle_evolve_special_action(
                follower_name,
                pos,
                is_super_evolution=False,
                existing_followers=all_followers,
                follower_uid=evolve_uid,
            )
            if not special_ok:
                return False

        self.device_state.sleep(4.8)
        self.device_state.evolution_point -= 1
        if follower_name:
            if is_evolve_priority_card(follower_name, runtime_cfg):
                self.device_state.logger.info(f"优先进化了[{follower_name}]")
            self.device_state.logger.info(
                f"进化了[{follower_name}]，剩余进化次数：{self.device_state.evolution_point}"
            )
        else:
            self.device_state.logger.info(f"执行了进化，剩余进化次数：{self.device_state.evolution_point}")

        self._mark_runtime_evolution(
            pos,
            follower_name=follower_name,
            evolve_uid=evolve_uid,
            mode="normal",
        )
        return True

    def perform_evolution_actions(self):
        """执行进化/超进化操作"""
        all_followers = self._normalize_follower_rows(self.follower_manager.get_positions())
        if not all_followers:
            self.device_state.logger.info("没有随从可进化")
            return
        self._runtime_sync_ours(all_followers)
        runtime_cfg_raw = getattr(self.device_state, "config", None)
        runtime_cfg = runtime_cfg_raw if isinstance(runtime_cfg_raw, dict) else None
        enemy_board_empty = self._is_enemy_board_empty_for_evolve()

        sorted_followers = self._sort_followers_for_evolution(all_followers, runtime_cfg)

        # 遍历每个随从位置
        for follower in list(sorted_followers or []):
            pos = (int(follower[0]), int(follower[1]))
            follower_type, follower_name = self._find_follower_meta_for_position(all_followers, pos)

            evolve_uid = self._runtime_uid_for_ours(
                pos,
                fallback_name=str(follower_name or ""),
            )
            if enemy_board_empty and self._disallows_all_available_empty_evolve(
                follower_name,
                runtime_cfg=runtime_cfg,
            ):
                self.device_state.logger.info(
                    f"[{follower_name}] 已配置不允许空场进化，跳过该随从"
                )
                continue

            # 点击该位置
            self._require_u2_device().click(pos[0], pos[1])
            self.device_state.sleep(0.3)  # 等待进化按钮出现

            # 获取新截图检测进化按钮
            new_screenshot = self.device_state.take_screenshot()
            if new_screenshot is None:
                self.device_state.logger.warning(f"位置 {pos} 无法获取截图，跳过检测")
                self.device_state.sleep(0.1)
                continue

            # 转换为OpenCV格式
            new_screenshot_np = np.array(new_screenshot)
            new_screenshot_cv = cv2.cvtColor(new_screenshot_np, cv2.COLOR_RGB2BGR)

            if not (
                enemy_board_empty
                and self._disallows_empty_evolve_trigger(
                    follower_name,
                    trigger="on_super_evolve",
                    runtime_cfg=runtime_cfg,
                )
            ) and self._try_apply_super_evolution(
                new_screenshot_cv,
                pos,
                follower_name=follower_name,
                follower_type=follower_type,
                evolve_uid=evolve_uid,
                all_followers=all_followers,
                runtime_cfg=runtime_cfg,
            ):
                break

            if not (
                enemy_board_empty
                and self._disallows_empty_evolve_trigger(
                    follower_name,
                    trigger="on_evolve",
                    runtime_cfg=runtime_cfg,
                )
            ) and self._try_apply_normal_evolution(
                new_screenshot_cv,
                pos,
                follower_name=follower_name,
                evolve_uid=evolve_uid,
                all_followers=all_followers,
                runtime_cfg=runtime_cfg,
            ):
                break

            self.device_state.sleep(0.01)
        # 内部已完成进化后的主要等待，避免与 phase 层重复叠加。

    def _handle_evolve_special_action(
        self,
        follower_name,
        pos=None,
        is_super_evolution=False,
        existing_followers=None,
        follower_uid=None,
    ) -> bool:
        """
        处理进化/超进化后特殊action（如铁拳神父等），便于扩展
        follower_name: 卡牌名称
        pos: 进化随从的坐标（如有需要）
        is_super_evolution: 是否为超进化
        existing_followers: 已扫描的随从结果，避免重复扫描
        """
        from .evolution_special_actions import EvolutionSpecialActions
        self._force_post_evolve_hand_refresh = False
        evolution_actions = EvolutionSpecialActions(self.device_state)
        result = bool(evolution_actions.handle_evolve_special_action(
            follower_name,
            pos,
            is_super_evolution,
            existing_followers,
            follower_uid=follower_uid,
        ))
        self._force_post_evolve_hand_refresh = bool(
            result and getattr(evolution_actions, "_force_post_evolve_hand_refresh", False)
        )
        return result

    def _show_cards_once(self):
        """点击一次展牌按钮（不包含额外 sleep，调用方保持原顺序控制时序）。"""
        self._require_u2_device().click(
            SHOW_CARDS_BUTTON[0]
            + random.randint(SHOW_CARDS_RANDOM_X[0], SHOW_CARDS_RANDOM_X[1]),
            SHOW_CARDS_BUTTON[1]
            + random.randint(SHOW_CARDS_RANDOM_Y[0], SHOW_CARDS_RANDOM_Y[1]),
        )

    def _click_blank_panel(self, *, sleep_seconds: float):
        """点击绝对无遮挡处关闭面板，并按需等待。"""
        self._require_u2_device().click(
            BLANK_CLICK_POSITION[0]
            + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM),
            BLANK_CLICK_POSITION[1]
            + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM),
        )
        self.device_state.sleep(float(sleep_seconds))

    def _take_screenshot_bgr(self):
        screenshot = self.device_state.take_screenshot()
        if screenshot is None:
            return None
        image = np.array(screenshot)
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    def _await_enemy_check(self, enemy_future):
        try:
            return enemy_future.result()
        except Exception as e:
            self.device_state.logger.warning(f"敌方随从检测失败: {str(e)}")
            return []

    def _log_observed_state(self, *, note: str, enemy=None, ward=None):
        """Log a minimal ObservedGameState without changing battle behavior."""

        try:
            from src.game.domain import ObservedGameState
        except Exception:
            return

        try:
            board_ours = []
            try:
                fm = getattr(self.device_state, "follower_manager", None)
                if fm is not None:
                    board_ours = fm.get_positions() or []
            except Exception:
                board_ours = []

            state = ObservedGameState(
                turn=getattr(self.device_state, "current_round_count", None),
                is_second_player=getattr(self.device_state, "extra_cost_available_this_match", None),
                pp_available=None,
                ep=getattr(self.device_state, "evolution_point", None),
                sep=getattr(self.device_state, "super_evolution_point", None),
                hand=list(getattr(self, "_last_observed_hand_cards", []) or []),
                board_ours=board_ours,
                board_enemy=list(enemy or []),
                ward_enemy=list(ward or []),
                ui={"last_button": getattr(self.device_state, "last_detected_button", None)},
                note=str(note or ""),
            )
            self.device_state.logger.info(f"[OBS] {state.brief()}")
        except Exception as e:
            # Don't break battle loop for logging failures.
            try:
                self.device_state.logger.debug(f"[OBS] build failed: {e}")
            except Exception:
                pass

    def perform_full_actions(self):
        """720P分辨率下的出牌攻击操作"""
        from concurrent.futures import ThreadPoolExecutor

        from src.game.battle.phases import AttackPhase, PlayPhase

        # 保持原有语义：提交后立刻退出 executor（实际会等待完成）
        with ThreadPoolExecutor(max_workers=3) as executor:
            enemy_future = executor.submit(
                self._scan_enemy_ATK, self.device_state.take_screenshot()
            )

        if not PlayPhase(self).run(post_show_sleep=0.3):
            return

        enemy_check = self._await_enemy_check(enemy_future)
        # Give summon / board animations time to settle before attack scanning.
        self.device_state.sleep(0.5)
        AttackPhase(self).run(enemy_check)
        self.device_state.sleep(1)

    def perform_fullPlus_actions(self):
        """执行进化/超进化与攻击操作"""
        from concurrent.futures import ThreadPoolExecutor

        from src.game.battle.phases import AttackPhase, EvolvePhase, PlayPhase
        from src.game.policy.base import LegacyBattlePolicy

        with ThreadPoolExecutor(max_workers=3) as executor:
            enemy_future = executor.submit(
                self._scan_enemy_ATK, self.device_state.take_screenshot()
            )

        if not PlayPhase(self).run(post_show_sleep=0.5):
            return

        enemy_check = self._await_enemy_check(enemy_future)

        # Step3C: evolve-pre only needs 1-shot ours scan.
        self._refresh_our_followers(
            sort_desc=False,
            extra_shots=0,
            retries=0,
            with_names=True,
        )

        # Step3C: if play phase had no enemy-affecting action, reuse pre-play enemy presence.
        # Otherwise refresh once before evolve decision.
        self._cached_enemy_presence_for_evolve = bool(enemy_check)
        if bool(getattr(self, "_play_phase_enemy_affected", False)):
            try:
                screen = self.device_state.take_screenshot()
                if screen is not None:
                    self._cached_enemy_presence_for_evolve = bool(self._scan_enemy_ATK(screen))
            except Exception:
                self._cached_enemy_presence_for_evolve = bool(enemy_check)

        policy = self.battle_policy or LegacyBattlePolicy()
        self._force_post_evolve_hand_refresh = False
        EvolvePhase(self, policy).run()
        self._cached_enemy_presence_for_evolve = None

        if bool(getattr(self, "_force_post_evolve_hand_refresh", False)):
            self._force_post_evolve_hand_refresh = False
            self._continue_play_after_evolve_refresh()
            if getattr(self, "_banlist_blocked_this_round", False):
                return
            try:
                screen = self.device_state.take_screenshot()
                if screen is not None:
                    enemy_check = bool(self._scan_enemy_ATK(screen))
            except Exception:
                pass

        # Give summon / evolution animations time to settle before attack scanning.
        self.device_state.sleep(0.5)
        AttackPhase(self).run(enemy_check)
        self.device_state.sleep(1)


    def _play_cards(self, image):
        """改进的出牌策略：每出一张牌都重新检测手牌，最多重试展牌次数为当前回合数"""
        self._banlist_blocked_this_round = False
        self._play_phase_enemy_affected = False
        # 获取当前回合可用费用
        current_round = self.device_state.current_round_count
        available_cost = min(10, current_round)  # 基础费用 = 当前回合数（最大10）
        
        # 第一回合检查是否有额外费用点
        if current_round == 1 and self.device_state.extra_cost_available_this_match is None:
            extra_point = self._detect_extra_cost_point(image)
            if extra_point:
                self.device_state.extra_cost_available_this_match = True
                self.device_state.logger.info("本局为后手，有额外费用点")
            else:
                self.device_state.extra_cost_available_this_match = False
                self.device_state.logger.info("本局为先手，没有额外费用点")
        
        # 检测额外费用点（1-5回合可用一次，6回合后可用一次，且本局有额外费用点功能）
        if self.device_state.extra_cost_available_this_match:
            
            # 检查是否有激活的额外费用点（费用没用完）
            if self.device_state.extra_cost_active and self.device_state.extra_cost_remaining_uses > 0:
                # 检查上一回合是否用完费用（如果没用完才能继续使用）
                if current_round > 1:
                    cost_unused = self.device_state.last_round_available_cost - self.device_state.last_round_cost_used
                    if cost_unused <= 0:
                        # 上一回合费用用完了，关闭激活状态
                        self.device_state.extra_cost_active = False
                        self.device_state.logger.info("上一回合费用已用完，关闭额外费用点激活状态")
                    else:
                        # 上一回合费用没用完，可以继续使用
                        extra_point = self._detect_extra_cost_point(image)
                        if extra_point:
                            x, y, confidence = extra_point
                            self.device_state.logger.info("点击额外费用点按钮")
                            self._require_u2_device().click(x, y)
                            time.sleep(0.2)
                            available_cost += 1  # 增加1点费用
                            self.device_state.extra_cost_remaining_uses -= 1
                            self.device_state.logger.info(f"使用激活的额外费用点，当前可用费用: {available_cost}")
                            
                            # 如果使用完了，关闭激活状态
                            if self.device_state.extra_cost_remaining_uses <= 0:
                                self.device_state.extra_cost_active = False
                                self.device_state.logger.info("额外费用点使用完毕，关闭激活状态")
                else:
                    # 第一回合，直接使用
                    extra_point = self._detect_extra_cost_point(image)
                    if extra_point:
                        x, y, confidence = extra_point
                        self.device_state.logger.info("点击额外费用点按钮")
                        self._require_u2_device().click(x, y)
                        time.sleep(0.1)
                        available_cost += 1  # 增加1点费用
                        self.device_state.extra_cost_remaining_uses -= 1
                        self.device_state.logger.info(f"使用激活的额外费用点，当前可用费用: {available_cost}")
                        
                        # 如果使用完了，关闭激活状态
                        if self.device_state.extra_cost_remaining_uses <= 0:
                            self.device_state.extra_cost_active = False
                            self.device_state.logger.info("额外费用点使用完毕，关闭激活状态")
            
            # 检查是否可以激活新的额外费用点
            else:
                # 检查1-5回合是否可以使用
                can_use_early = (current_round <= 5 and not self.device_state.extra_cost_used_early)
                
                # 检查6回合后是否可以使用
                can_use_late = (current_round >= 6 and not self.device_state.extra_cost_used_late)
                
                if can_use_early or can_use_late:
                    extra_point = self._detect_extra_cost_point(image)
                    if extra_point:
                        x, y, confidence = extra_point
                        self.device_state.logger.info("点击额外费用点按钮")
                        self._require_u2_device().click(x, y)
                        time.sleep(0.1)
                        available_cost += 1  # 增加1点费用
                        
                        # 激活额外费用点（每次激活只有1次使用机会）
                        self.device_state.extra_cost_active = True
                        self.device_state.extra_cost_remaining_uses = 1  # 每次激活只有1次使用机会 
                        
                        # 根据当前回合标记使用状态
                        if current_round <= 5:
                            self.device_state.extra_cost_used_early = True
                            self.device_state.logger.info(f"当前可用费用: {available_cost}")
                        else:
                            self.device_state.extra_cost_used_late = True
                            self.device_state.logger.info(f"当前可用费用: {available_cost}")
        
        # 改进的出牌逻辑：每出一张牌都重新检测手牌
        self._play_cards_with_retry(available_cost, current_round)

        # Banlist hit: skip later phases (evolve/attack) and only end turn.
        if getattr(self, "_banlist_blocked_this_round", False):
            return False
        return True

    def _continue_play_after_evolve_refresh(self) -> None:
        """进化效果刷新手牌后，用出牌阶段剩余费用继续出牌。"""
        remaining_cost = int(getattr(self, "_last_play_phase_remaining_cost", 0) or 0)
        if remaining_cost <= 0:
            self.device_state.logger.info("进化后刷新手牌：无剩余费用，跳过补出牌")
            return

        self.device_state.logger.info(f"进化后刷新手牌，使用剩余{remaining_cost}费继续出牌")
        self._show_cards_once()
        self.device_state.sleep(2.0)
        self._play_cards_with_retry(
            remaining_cost,
            int(getattr(self.device_state, "current_round_count", 0) or 0),
            reset_round_state=False,
            accumulate_cost_history=True,
        )
        self._click_blank_panel(sleep_seconds=0.5)

    def _play_cards_with_retry(
        self,
        available_cost: int,
        current_round: int,
        *,
        reset_round_state: bool = True,
        accumulate_cost_history: bool = False,
    ) -> int:
        """出牌顺序：优先卡（特殊牌+高优先级牌，组内按优先级和费用从高到低）先出，然后普通牌按费用从高到低出。每次出牌都重新识别手牌。"""
        max_retry_attempts = 2  # 最多重试次数
        total_cost_used = 0
        retry_count = 0
        self._last_play_phase_remaining_cost = int(available_cost or 0)
        if reset_round_state:
            # Reset observation cache per round.
            self._last_observed_hand_cards = []
            # 当前回合需要忽略的卡牌（如剑士的斩击在没有敌方随从时）
            self._current_round_ignored_cards = set()
        elif not hasattr(self, '_current_round_ignored_cards'):
            self._current_round_ignored_cards = set()
        # 同名牌连续出牌计数器
        card_attempt_count: Dict[str, int] = {}
        self.device_state.logger.info(f"当前回合：{current_round}，可用费用: {available_cost}")

        hand_manager = self.hand_manager
        # 1. 获取初始手牌
        cards = hand_manager.get_hand_cards_with_retry(max_retries=3)
        if not cards:
            self.device_state.logger.warning("未能识别到任何手牌")
            return int(available_cost or 0)

        # Banlist guard (anti-abuse / emergency stop).
        try:
            from src.game.internal.banlist import should_block_play

            blocked, hits = should_block_play(cards, getattr(self.device_state, "config", None))
        except Exception:
            blocked, hits = False, []
        if blocked:
            hits_str = " | ".join(hits) if hits else "<unknown>"
            self.device_state.logger.warning(f"[Banlist] 命中禁卡表，跳过本回合出牌: {hits_str}")
            self._banlist_blocked_this_round = True
            return int(available_cost or 0)

        # Cache last observed hand for later structured logging.
        self._last_observed_hand_cards = list(cards)

        from src.config.card_priorities import (
            get_card_priority_pre_evolution,
            get_card_priority_post_evolution,
            is_evolution_unlocked
        )
        runtime_cfg = getattr(self.device_state, "config", None)

        from src.utils.card_filename import make_enhance_key

        def _decorate_cards_for_pp(cards_list: List[Dict[str, Any]], pp: int) -> None:
            """Decorate card dicts with effective cost/key for current PP."""

            for c in cards_list:
                base_name = str(c.get("name", "") or "")
                try:
                    base_cost = int(c.get("cost", 0) or 0)
                except Exception:
                    base_cost = 0

                eff_cost = base_cost
                enhance_costs = c.get("enhance_costs")
                if not isinstance(enhance_costs, (list, tuple)):
                    enhance_costs = []
                for ec in enhance_costs:
                    try:
                        ec_i = int(ec)
                    except Exception:
                        continue
                    if ec_i <= int(pp or 0) and ec_i > eff_cost:
                        eff_cost = ec_i

                if base_name and eff_cost != base_cost:
                    cfg_key = make_enhance_key(base_name, eff_cost)
                else:
                    cfg_key = base_name

                c["_cfg_key"] = cfg_key
                c["_eff_cost"] = int(eff_cost)

                pr = 999
                try:
                    pr = int(priority_fn(cfg_key))
                except Exception:
                    pr = 999
                if pr == 999 and cfg_key != base_name:
                    try:
                        pr = int(priority_fn(base_name))
                    except Exception:
                        pr = 999
                c["_eff_priority"] = pr
                c["_is_priority"] = bool(int(pr) != 999)

        # 根据进化是否解锁，动态选择优先级函数
        priority_fn: Callable[[str], int]
        if is_evolution_unlocked(self.device_state):
            def _get_priority_fn(name: str) -> int:
                try:
                    return int(get_card_priority_post_evolution(name, runtime_cfg))
                except Exception:
                    return 999
            priority_fn = _get_priority_fn
            priority_phase = "进化后"
        else:
            def _get_priority_fn(name: str) -> int:
                try:
                    return int(get_card_priority_pre_evolution(name, runtime_cfg))
                except Exception:
                    return 999
            priority_fn = _get_priority_fn
            priority_phase = "进化前"

        self.device_state.logger.info(f"使用{priority_phase}优先级策略")

        def _resort_planned_cards(
            cards_list: List[Dict[str, Any]],
            pp: int,
        ) -> List[Dict[str, Any]]:
            _decorate_cards_for_pp(cards_list, int(pp or 0))
            priority_local = [c for c in cards_list if c.get('_is_priority')]
            normal_local = [c for c in cards_list if not c.get('_is_priority')]
            priority_local.sort(key=lambda x: (x.get('_eff_priority', 999), -x.get('_eff_cost', 0)))
            normal_local.sort(key=lambda x: x.get('_eff_cost', 0), reverse=True)
            return priority_local + normal_local

        def _pick_next_card_to_play(
            planned_cards_local: List[Dict[str, Any]],
            remain_cost_local: int,
        ) -> Optional[Dict[str, Any]]:
            affordable_priority = [
                c
                for c in planned_cards_local
                if c.get('_is_priority') and int(c.get('_eff_cost', 0) or 0) <= int(remain_cost_local or 0)
            ]
            normal_zero_cost = [
                c
                for c in planned_cards_local
                if (not c.get('_is_priority')) and int(c.get('_eff_cost', 0) or 0) == 0
            ]
            affordable_normal = [
                c
                for c in planned_cards_local
                if (not c.get('_is_priority'))
                and int(c.get('_eff_cost', 0) or 0) > 0
                and int(c.get('_eff_cost', 0) or 0) <= int(remain_cost_local or 0)
            ]

            if not affordable_priority and not normal_zero_cost and not affordable_normal:
                return None

            if affordable_priority:
                affordable_priority.sort(key=lambda x: (x.get('_eff_priority', 999), -x.get('_eff_cost', 0)))
                selected = affordable_priority[0]
                self.device_state.logger.info(f"检测到高优先级卡牌[{selected.get('name', '未知')}]，优先打出")
                return selected

            if normal_zero_cost:
                selected = normal_zero_cost[0]
                self.device_state.logger.info(f"检测到普通0费卡牌[{selected.get('name', '未知')}]，优先打出")
                return selected

            affordable_normal.sort(key=lambda x: x.get('_eff_cost', 0), reverse=True)
            return affordable_normal[0]

        def _has_playable_cards(
            planned_cards_local: List[Dict[str, Any]],
            remain_cost_local: int,
        ) -> bool:
            return bool(
                any(
                    int(c.get('_eff_cost', c.get('cost', 0) or 0) or 0) <= int(remain_cost_local or 0)
                    for c in planned_cards_local
                )
                or any(
                    int(c.get('_eff_cost', c.get('cost', 0) or 0) or 0) == 0
                    for c in planned_cards_local
                )
            )

        def _refresh_planned_cards_after_play(
            planned_cards_local: List[Dict[str, Any]],
            remain_cost_local: int,
            retry_count_local: int,
            force_refresh: bool = False,
        ) -> Tuple[List[Dict[str, Any]], int, bool, bool]:
            if not (
                bool(force_refresh)
                or (
                    planned_cards_local
                    and (
                        int(remain_cost_local or 0) > 0
                        or any(
                            int(c.get('_eff_cost', c.get('cost', 0) or 0) or 0) == 0
                            for c in planned_cards_local
                        )
                    )
                )
            ):
                return planned_cards_local, retry_count_local, False, False

            time.sleep(0.5)
            self._require_u2_device().click(
                SHOW_CARDS_BUTTON[0] + random.randint(-2, 2),
                SHOW_CARDS_BUTTON[1] + random.randint(-2, 2),
            )
            time.sleep(1.0)
            if force_refresh:
                self.device_state.logger.info("[Effect] force post-play hand refresh")
                time.sleep(2.0)

            new_cards_local: List[Dict[str, Any]] = hand_manager.get_hand_cards_with_retry(
                max_retries=2,
                silent=True,
            )
            if new_cards_local:
                self._last_observed_hand_cards = list(new_cards_local)
                card_info_local = []
                for card in new_cards_local:
                    name_local = card.get('name', '未知')
                    cost_local = card.get('cost', 0)
                    center_local = card.get('center', (0, 0))
                    card_info_local.append(f"{cost_local}费_{name_local}({center_local[0]},{center_local[1]})")
                self.device_state.logger.info(f"出牌后更新手牌状态与位置: {' | '.join(card_info_local)}")

                filtered_cards_local = [
                    c for c in new_cards_local if c.get('name', '') not in self._current_round_ignored_cards
                ]
                planned_cards_local = _resort_planned_cards(filtered_cards_local, int(remain_cost_local or 0))
            else:
                if retry_count_local < max_retry_attempts:
                    self.device_state.logger.info(f"检测不到手牌，重新识别 ({retry_count_local + 1}/2)")
                    return planned_cards_local, int(retry_count_local + 1), False, True
                self.device_state.logger.info("达到最大重试次数，停止出牌")
                return planned_cards_local, retry_count_local, True, False

            if not planned_cards_local or not _has_playable_cards(planned_cards_local, remain_cost_local):
                return planned_cards_local, retry_count_local, True, False

            return planned_cards_local, retry_count_local, False, False

        # 过滤掉当前回合需要忽略的卡牌
        filtered_cards = [c for c in cards if c.get('name', '') not in self._current_round_ignored_cards]

        planned_cards = _resort_planned_cards(filtered_cards, int(available_cost or 0))

        remain_cost = int(available_cost or 0)
        while planned_cards and (
            remain_cost > 0
            or any(int(c.get('_eff_cost', c.get('cost', 0) or 0) or 0) == 0 for c in planned_cards)
        ):
            planned_cards = _resort_planned_cards(planned_cards, int(remain_cost or 0))
            card_to_play = _pick_next_card_to_play(planned_cards, remain_cost)
            if card_to_play is None:
                break

            name = card_to_play.get('name', '未知')
            base_cost = int(card_to_play.get('cost', 0) or 0)
            cost = int(card_to_play.get('_eff_cost', base_cost) or 0)
            cfg_key = str(card_to_play.get('_cfg_key') or name)
            card_to_play['_config_key'] = cfg_key
            card_to_play['_effective_cost'] = cost

            if cost != base_cost:
                self.device_state.logger.info(
                    f"打出卡牌: {name} (爆能费用: {cost}, 基础费用: {base_cost})"
                )
            else:
                self.device_state.logger.info(f"打出卡牌: {name} (费用: {cost})")
            self._force_post_play_hand_refresh = False
            result = self._play_single_card(card_to_play)
            force_refresh = bool(getattr(self, '_force_post_play_hand_refresh', False)) if result else False
            self._force_post_play_hand_refresh = False
            
            # 处理额外的费用奖励
            extra_cost_bonus = getattr(self, '_current_extra_cost_bonus', 0)
            if extra_cost_bonus > 0:
                remain_cost += extra_cost_bonus
                # 清除额外费用奖励，避免重复使用
                self._current_extra_cost_bonus = 0
            
            # 记录最后打出的卡牌名称，用于特殊逻辑判断
            self._last_played_card = name
            
            # 检查是否应该消耗费用
            should_not_consume_cost = getattr(self, '_should_not_consume_cost', False)
            if should_not_consume_cost:
                self.device_state.logger.info(f"出不了 {name}卡牌 ，不用消耗费用")
                # 清除不消耗费用的标记，避免影响后续卡牌
                self._should_not_consume_cost = False
            elif cost > 0:
                remain_cost -= cost
                total_cost_used += cost
            
            # 检查是否需要从手牌中移除
            should_remove_from_hand = getattr(self, '_should_remove_from_hand', False)
            if should_remove_from_hand:
                self.device_state.logger.info(f"出不了 {name} ，已加入当前回合忽略列表")
                # 将卡牌加入当前回合忽略列表
                self._current_round_ignored_cards.add(name)
                # 清除需要移除的标记，避免影响后续卡牌
                self._should_remove_from_hand = False
                # 从planned_cards中移除这张卡，避免重复处理
                planned_cards.remove(card_to_play)
                continue  # 跳过后续的手牌更新逻辑

            # 增加同名牌连续出牌计数
            card_attempt_count[name] = card_attempt_count.get(name, 0) + 1
            if card_attempt_count[name] >= 3:
                self.device_state.logger.warning(f"卡牌 {name} 连续出牌3次，加入当前回合忽略列表")
                self._current_round_ignored_cards.add(name)
                self._should_remove_from_hand = False
                # 从planned_cards中移除这张卡，避免重复处理
                planned_cards.remove(card_to_play)
                continue
            
            # 检查卡牌是否成功打出
            if not result:
                self.device_state.logger.info(f"卡牌 {name} 未成功打出，跳过后续逻辑")
                continue

            try:
                if self._card_play_may_affect_enemy(card_to_play):
                    self._play_phase_enemy_affected = True
            except Exception:
                pass
            
            planned_cards.remove(card_to_play)
            planned_cards, retry_count, should_break, should_continue = _refresh_planned_cards_after_play(
                planned_cards,
                remain_cost,
                retry_count,
                force_refresh=force_refresh,
            )
            if should_break:
                break
            if should_continue:
                continue

        if not hasattr(self.device_state, 'cost_history'):
            self.device_state.cost_history = []
        if accumulate_cost_history and self.device_state.cost_history:
            self.device_state.cost_history[-1] += total_cost_used
        else:
            self.device_state.cost_history.append(total_cost_used)
        self._last_play_phase_remaining_cost = int(remain_cost or 0)
        self.device_state.logger.info(f"本回合出牌完成，消耗{total_cost_used}费 (可用费用: {available_cost})")
        return int(remain_cost or 0)

    def _play_single_card(self, card):
        """打出单张牌"""
        from .card_play_special_actions import CardPlaySpecialActions
        card_play_actions = CardPlaySpecialActions(self.device_state)
        result = card_play_actions.play_single_card(card)
        self._force_post_play_hand_refresh = bool(
            result and getattr(card_play_actions, "_force_post_play_hand_refresh", False)
        )

        try:
            if result:
                preplay_tag_ok = bool(getattr(card_play_actions, "_preplay_origin_tag_succeeded", False))
                card_name = str(card.get("name", "") or "")
                cfg_key = str(
                    card.get("_config_key")
                    or card.get("_cfg_key")
                    or card.get("config_key")
                    or card_name
                )
                # Avoid duplicate heavy scan when pre-play origin tagging already succeeded.
                if not preplay_tag_ok:
                    self._tag_recent_played_follower(card_name=card_name, cfg_key=cfg_key)
        except Exception:
            pass
        
        # 处理额外的费用奖励
        extra_cost_bonus = getattr(card_play_actions, '_extra_cost_bonus', 0)
        if extra_cost_bonus > 0:
            self.device_state.logger.info(f"获得额外费用: +{extra_cost_bonus}")
            # 将额外费用奖励存储到实例变量中，供调用方使用
            self._current_extra_cost_bonus = extra_cost_bonus
        
        # 处理不消耗费用的特殊情况
        should_not_consume_cost = getattr(card_play_actions, '_should_not_consume_cost', False)
        if should_not_consume_cost:
            # 将不消耗费用的标记存储到实例变量中，供调用方使用
            self._should_not_consume_cost = True
        
        # 处理需要从手牌中移除的特殊情况
        should_remove_from_hand = getattr(card_play_actions, '_should_remove_from_hand', False)
        if should_remove_from_hand:
            # 将需要移除的标记存储到实例变量中，供调用方使用
            self._should_remove_from_hand = True

        return result

    def _card_play_may_affect_enemy(self, card: Dict[str, Any]) -> bool:
        """Best-effort detector for enemy-affecting on_play cards (Step3C cache invalidation)."""

        try:
            from src.config.strategy_effects import get_card_effect_steps, normalize_effect_steps_to_ops
        except Exception:
            return False

        card_name = str((card or {}).get("name") or "")
        cfg_key = str(
            (card or {}).get("_config_key")
            or (card or {}).get("_cfg_key")
            or (card or {}).get("config_key")
            or card_name
        )
        if not card_name and not cfg_key:
            return False

        steps = get_card_effect_steps(
            getattr(self.device_state, "config", None),
            card_name=cfg_key,
            trigger="on_play",
        )
        if (not steps) and cfg_key != card_name:
            steps = get_card_effect_steps(
                getattr(self.device_state, "config", None),
                card_name=card_name,
                trigger="on_play",
            )
        ops = normalize_effect_steps_to_ops(steps)
        if not ops:
            return False

        for op in ops:
            if not isinstance(op, dict):
                continue
            op_name = str(op.get("op") or "")
            if op_name == "select_targets":
                target = op.get("target")
                if isinstance(target, dict):
                    target_kind = str(target.get("kind") or "")
                    target_selector = str(target.get("selector") or "")
                    if "enemy" in target_kind or "ward" in target_kind:
                        return True
                    if "enemy" in target_selector or "ward" in target_selector:
                        return True

            for key in ("kind", "target", "target_kind"):
                value = str(op.get(key) or "")
                if "enemy" in value or "ward" in value:
                    return True

        return False




    def _detect_extra_cost_point(self, image):
        """检测额外费用点按钮"""
        try:
            game_manager = getattr(self.device_state, "game_manager", None)
            if game_manager is None or getattr(game_manager, "template_manager", None) is None:
                return None

            # 使用template_manager中已经设置好的模板目录
            templates_dir = game_manager.template_manager.templates_dir
            template_path = f"{templates_dir}/point.png"
            
            if not os.path.exists(template_path):
                self.device_state.logger.debug(f"额外费用点模板不存在: {template_path}")
                return None
            
            template = safe_imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is None:
                self.device_state.logger.debug("无法加载额外费用点模板")
                return None
            
            # 转换为灰度图
            gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # 模板匹配
            result = cv2.matchTemplate(gray_image, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            # 如果匹配度足够高且位置在y轴大于340的区域
            if max_val > 0.7:
                x, y = max_loc
                # 检查y轴位置是否大于340
                if y > 340:
                    self.device_state.logger.info("检测到额外费用点按钮")
                    return (x, y, max_val)
            
            return None
        except Exception as e:
            self.device_state.logger.error(f"检测额外费用点时出错: {str(e)}")
            return None

    def _validate_mulligan_cards(self, cards: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        验证换牌识别结果是否合理

        Args:
            cards: 识别到的卡牌列表

        Returns:
            (is_valid, reason): 是否有效及原因
        """
        # 检查1：必须恰好4张（严格遵循游戏规则）
        if len(cards) != 4:
            return False, f"卡牌数量错误: {len(cards)}张（预期4张）"

        # 检查2：X坐标必须均匀分布
        x_coords = sorted([c['center'][0] for c in cards])
        # 换牌区域：182-971，宽789px
        # 预期位置：每张卡间隔约197px，中心位置分别在 282, 479, 676, 873
        expected_positions = [282, 479, 676, 873]

        for i, (actual_x, expected_x) in enumerate(zip(x_coords, expected_positions)):
            if abs(actual_x - expected_x) > 150:  # 放宽误差到±150px
                return False, f"第{i+1}张卡位置异常: X={actual_x} (预期{expected_x}±150)"

        # 检查3：Y坐标必须基本一致
        y_coords = [c['center'][1] for c in cards]
        y_mean = sum(y_coords) / len(y_coords)
        for i, y in enumerate(y_coords):
            if abs(y - y_mean) > 80:  # 放宽Y轴误差到±80px
                return False, f"第{i+1}张卡Y坐标异常: {y} (平均{y_mean:.0f}±80)"

        return True, "验证通过"

    def _detect_change_card_sift(self, debug_flag=False):
        """
        使用SIFT卡牌识别 + 增强策略的新换牌方法
        替代旧的_detect_change_card方法
        """
        try:
            from src.utils.card_swap_strategy_enhanced import determine_card_swaps_enhanced
            from src.config.card_priorities import get_high_priority_cards

            # 1. 获取截图
            screenshot = self.device_state.take_screenshot()
            if screenshot is None:
                self.device_state.logger.warning("[SIFT换牌] 无法获取截图")
                return False

            image = np.array(screenshot)
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

            # 2. 复用单例SIFT识别器（避免重复加载模板）
            # 换牌区域: (170, 390, 980, 645) - 扩大区域以确保捕捉到所有4张卡牌
            mulligan_region = (170, 390, 980, 645)
            sift_recognizer = self.hand_manager.sift_recognition

            try:
                # 3. 识别手牌（带重试机制）
                max_retries = 3
                cards = None

                for attempt in range(max_retries):
                    # 执行识别
                    recognized_cards = sift_recognizer.recognize_hand_cards(
                        screenshot, hand_area=mulligan_region
                    )

                    if not recognized_cards:
                        self.device_state.logger.warning(
                            f"[SIFT换牌] 第{attempt+1}次识别: 未检测到卡牌"
                        )
                        if attempt < max_retries - 1:
                            time.sleep(0.3)  # 等待卡牌动画完成
                            screenshot = self.device_state.take_screenshot()
                            if screenshot is None:
                                continue
                        continue

                    # 确保最多4张牌（避免过度识别）
                    recognized_cards = recognized_cards[:4]

                    # 验证识别结果
                    is_valid, reason = self._validate_mulligan_cards(recognized_cards)

                    if is_valid:
                        self.device_state.logger.info(
                            f"[SIFT换牌] 第{attempt+1}次识别成功，验证通过"
                        )
                        cards = recognized_cards
                        break
                    else:
                        self.device_state.logger.warning(
                            f"[SIFT换牌] 第{attempt+1}次识别失败: {reason}"
                        )

                        # Debug: 输出识别到的卡牌位置信息
                        for i, card in enumerate(recognized_cards):
                            cx, cy = card['center']
                            self.device_state.logger.debug(
                                f"  卡牌{i+1}: {card['name']} | "
                                f"费用{card['cost']} | "
                                f"位置({cx},{cy}) | "
                                f"置信度{card.get('confidence', 0):.3f}"
                            )

                        # 保存失败截图用于调试
                        if debug_flag:
                            failure_dir = "debug_mulligan_failures"
                            if not os.path.exists(failure_dir):
                                os.makedirs(failure_dir)

                            failure_img = np.array(screenshot)
                            failure_img = cv2.cvtColor(failure_img, cv2.COLOR_RGB2BGR)

                            # 标注识别到的位置
                            for i, card in enumerate(recognized_cards):
                                cx, cy = card['center']
                                cv2.circle(failure_img, (cx, cy), 8, (0, 0, 255), 2)
                                cv2.putText(
                                    failure_img,
                                    f"{i+1}:{card['cost']}",
                                    (cx - 15, cy - 15),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.5,
                                    (0, 0, 255),
                                    2
                                )

                            failure_path = os.path.join(
                                failure_dir,
                                f"fail_{int(time.time()*1000)}_attempt{attempt+1}.png"
                            )
                            cv2.imwrite(failure_path, failure_img)
                            self.device_state.logger.debug(
                                f"[SIFT换牌] 失败截图已保存: {failure_path}"
                            )

                        if attempt < max_retries - 1:
                            time.sleep(0.3)  # 等待后重试
                            screenshot = self.device_state.take_screenshot()
                            if screenshot is None:
                                continue

                # 重试后仍失败
                if cards is None:
                    self.device_state.logger.error(
                        f"[SIFT换牌] {max_retries}次重试均失败，放弃识别"
                    )
                    return False
                
                # 自动补全机制：如果识别到3张卡牌，尝试根据位置信息补全第4张
                if len(cards) == 3:
                    self.device_state.logger.warning("[SIFT换牌] 识别到3张卡牌，尝试自动补全第4张")
                    # 计算已识别卡牌的X坐标间隔
                    x_coords = sorted([c['center'][0] for c in cards])
                    intervals = [x_coords[i+1] - x_coords[i] for i in range(2)]
                    avg_interval = sum(intervals) / len(intervals)
                    
                    # 检查缺失的位置 - 放宽匹配阈值到150
                    expected_positions = [282, 479, 676, 873]
                    missing_pos = None
                    for pos in expected_positions:
                        if not any(abs(c['center'][0] - pos) < 150 for c in cards):
                            missing_pos = pos
                            break
                    
                    # 如果没有找到缺失的位置，尝试通过间隔计算
                    if not missing_pos and len(x_coords) == 3:
                        # 检查是否在开头或结尾缺失
                        if x_coords[0] > 350:  # 开头缺失
                            missing_pos = x_coords[0] - avg_interval
                        elif x_coords[-1] < 800:  # 结尾缺失
                            missing_pos = x_coords[-1] + avg_interval
                        else:  # 中间缺失
                            # 检查哪个间隔异常大
                            if intervals[0] > avg_interval * 1.5:
                                missing_pos = x_coords[0] + avg_interval
                            elif intervals[1] > avg_interval * 1.5:
                                missing_pos = x_coords[1] + avg_interval
                    
                    if missing_pos:
                        # 确保位置在合理范围内
                        missing_pos = max(200, min(900, missing_pos))
                        # 创建一个虚拟卡牌补全
                        virtual_card = {
                            'cost': 0,
                            'name': '未知卡牌',
                            'center': (int(missing_pos), cards[0]['center'][1]),
                            'confidence': 0.5
                        }
                        cards.append(virtual_card)
                        self.device_state.logger.info(f"[SIFT换牌] 已补全第4张卡牌，位置: {int(missing_pos)}")
                    else:
                        self.device_state.logger.warning("[SIFT换牌] 无法确定缺失卡牌的位置，补全失败")

                # 记录识别结果（含详细位置信息）
                card_names = [f"{c['cost']}费_{c['name']}" for c in cards]
                self.device_state.logger.info(f"[SIFT换牌] 识别到手牌: {' | '.join(card_names)}")

                for i, card in enumerate(cards):
                    cx, cy = card['center']
                    self.device_state.logger.debug(
                        f"  [位置{i+1}] {card['name']} | "
                        f"费用:{card['cost']} | "
                        f"坐标:({cx},{cy}) | "
                        f"置信度:{card.get('confidence', 0):.3f}"
                    )

                # 4. 获取配置的策略
                strategy_setting = self.device_state.config.get("game", {}).get(
                    "card_replacement_strategy", "4费档次"
                )

                # 5. 调用增强策略决策
                priority_cards = get_high_priority_cards(getattr(self.device_state, "config", None))
                keep_indices, swap_indices, reasons = determine_card_swaps_enhanced(
                    cards,
                    strategy_setting,
                    priority_cards
                )

                self.device_state.logger.info(f"[SIFT换牌] 策略: {strategy_setting}")
                self.device_state.logger.info(f"[SIFT换牌] 保留: {keep_indices}, 换掉: {swap_indices}")

                # 6. 执行换牌拖拽操作
                if swap_indices:
                    for idx, reason in zip(swap_indices, reasons):
                        card = cards[idx]
                        center_x, center_y = card['center']

                        self.device_state.logger.info(
                            f"[SIFT换牌] 换掉 {card['name']} ({card['cost']}费) - 原因: {reason}"
                        )

                        # 执行拖拽 (从卡牌中心向上拖动)
                        # 换牌区域Y轴: 402-633，拖拽起点大约在下方，终点在上方
                        start_x = center_x + random.randint(-5, 5)
                        start_y = 516  # 固定拖拽起点Y坐标
                        end_x = center_x + random.randint(-5, 5)
                        end_y = 208    # 固定拖拽终点Y坐标

                        human_like_drag(
                            self._require_u2_device(),
                            start_x, start_y,
                            end_x, end_y,
                            duration=random.uniform(*settings.get_human_like_drag_duration_range())
                        )

                        time.sleep(random.uniform(0.05, 0.1))

                    self.device_state.logger.info(f"[SIFT换牌] 换牌完成，共换掉 {len(swap_indices)} 张")
                else:
                    self.device_state.logger.info("[SIFT换牌] 无需换牌，当前手牌已满足策略")

                # 7. Debug模式保存截图
                if debug_flag:
                    debug_dir = "debug_mulligan_sift"
                    if not os.path.exists(debug_dir):
                        os.makedirs(debug_dir)

                    debug_img = image.copy()
                    for idx, card in enumerate(cards):
                        center_x, center_y = card['center']
                        color = (0, 255, 0) if idx in keep_indices else (0, 0, 255)
                        cv2.circle(debug_img, (center_x, center_y), 10, color, 3)
                        cv2.putText(
                            debug_img,
                            f"{card['cost']}费",
                            (center_x - 20, center_y - 15),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            color,
                            2
                        )

                    debug_path = os.path.join(debug_dir, f"mulligan_{int(time.time()*1000)}.png")
                    cv2.imwrite(debug_path, debug_img)
                    self.device_state.logger.info(f"[SIFT换牌] Debug图片已保存: {debug_path}")

                return True

            finally:
                # No per-instance mutation; nothing to restore.
                pass

        except Exception as e:
            self.device_state.logger.error(f"[SIFT换牌] 执行失败: {str(e)}")
            import traceback
            self.device_state.logger.error(f"[SIFT换牌] 错误详情:\n{traceback.format_exc()}")
            return False

    def _scan_enemy_followers(self, screenshot, is_select=False):
        """检测场上的敌方随从位置与血量"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_enemy_followers(screenshot, is_select=is_select)
        return []

    @staticmethod
    def _normalize_scan_delay_range(shot_delay_range: Sequence[Any]) -> tuple[float, float]:
        try:
            dmin, dmax = float(shot_delay_range[0]), float(shot_delay_range[1])
        except Exception:
            dmin, dmax = 0.10, 0.15
        if dmax < dmin:
            dmin, dmax = dmax, dmin
        dmin = max(0.0, dmin)
        dmax = max(dmin, dmax)
        return dmin, dmax

    def _scan_our_followers_multi_shot(
        self,
        *,
        first_screenshot: Any,
        total_shots: int,
        sort_desc: bool,
        shot_delay_range: Sequence[Any],
        debug_flag: bool,
        with_names: bool,
        debug_mode: bool,
        phase_tag: Optional[str] = None,
    ) -> list[list[tuple[Any, Any, Any, Any]]]:
        shots: list[list[tuple[Any, Any, Any, Any]]] = []
        dmin, dmax = self._normalize_scan_delay_range(shot_delay_range)

        for si in range(total_shots):
            shot = first_screenshot if si == 0 else self.device_state.take_screenshot()
            if shot is None:
                continue
            one = self._scan_our_followers(
                shot,
                extra_shots=0,
                sort_desc=sort_desc,
                shot_delay_range=shot_delay_range,
                debug_flag=debug_flag,
                with_names=with_names,
            )
            if debug_mode and with_names:
                try:
                    suffix = f"[{phase_tag}]" if phase_tag else ""
                    self.device_state.logger.info(
                        "[Scan][ours/full]"
                        f"{suffix}[{si + 1}/{total_shots}] count={len(list(one or []))} result={list(one or [])}"
                    )
                except Exception:
                    pass
            if one:
                shots.append(list(one))

            if si < (total_shots - 1):
                self.device_state.sleep(random.uniform(dmin, dmax))

        return shots

    def _record_our_scan_perf(
        self,
        *,
        mode: str,
        dt_ms: float,
        has_followers: bool,
        debug_mode: bool,
    ) -> None:
        try:
            perf = getattr(self, "_perf_scan_our_followers", None)
            if not (isinstance(perf, dict) and mode in perf and isinstance(perf.get(mode), dict)):
                return

            perf[mode]["calls"] = int(perf[mode].get("calls", 0)) + 1
            perf[mode]["total_ms"] = float(perf[mode].get("total_ms", 0.0)) + float(dt_ms)
            if has_followers:
                perf[mode]["ok"] = int(perf[mode].get("ok", 0)) + 1

            now = time.time()
            if not (debug_mode and (now - float(self._perf_scan_our_followers_last_log_ts)) >= 10.0):
                return

            self._perf_scan_our_followers_last_log_ts = now
            fast = perf.get("fast", {})
            full = perf.get("full", {})

            def _fmt(d: Dict[str, Any]) -> str:
                calls = int(d.get("calls", 0))
                ok = int(d.get("ok", 0))
                total_ms = float(d.get("total_ms", 0.0))
                avg = (total_ms / calls) if calls else 0.0
                return f"calls={calls} ok={ok} avg={avg:.1f}ms"

            self.device_state.logger.info(
                f"[Perf] scan_our_followers fast({_fmt(fast)}) full({_fmt(full)})"
            )
        except Exception:
            pass

    def _refresh_our_followers(
        self,
        *,
        sort_desc: bool = False,
        extra_shots: int = 2,
        shot_delay_range=(0.10, 0.15),
        retries: int = 1,
        debug_flag: bool = False,
        with_names: bool = True,
        allow_cached_fallback: bool = True,
    ):
        """统一的“扫描并刷新我方随从”入口。

        通过多次单帧采样（默认3次）+ slot聚合 + 必要时确认重扫，
        减少外层零散补扫并稳定类型/命名结果。
        """
        # Keep old names when doing fast scans (no SIFT naming).
        try:
            cached_before = self.follower_manager.get_positions() or []
        except Exception:
            cached_before = []

        mode = "full" if with_names else "fast"
        try:
            debug_mode = bool(
                isinstance(getattr(self.device_state, "config", None), dict)
                and self.device_state.config.get("ui", {}).get("debug_mode")
            )
        except Exception:
            debug_mode = False

        def _finalize_followers(found):
            followers_local = list(found or [])
            if not followers_local:
                return []

            # Optional: backfill names from cache when we skipped naming.
            if not with_names and cached_before and len(cached_before) == len(followers_local):
                try:
                    if any(len(f) > 3 and f[3] for f in cached_before):
                        filled = []
                        for x, y, t, name in followers_local:
                            if name:
                                filled.append((x, y, t, name))
                                continue
                            best = None
                            best_dx = 10**9
                            for cx, cy, ct, cname in cached_before:
                                if not cname:
                                    continue
                                dx = abs(int(cx) - int(x))
                                if dx < 30 and dx < best_dx:
                                    best_dx = dx
                                    best = cname
                            filled.append((x, y, t, best))
                        followers_local = filled
                except Exception:
                    pass

            try:
                followers_local = self._stabilize_followers_by_spot(
                    followers_local,
                    sort_desc=bool(sort_desc),
                )
            except Exception:
                followers_local = list(followers_local or [])

            self.follower_manager.update_positions(followers_local)
            try:
                if debug_flag or debug_mode:
                    self.device_state.logger.info(f"我方当前场上随从: {followers_local}")
                else:
                    self.device_state.logger.debug(f"我方当前场上随从: {followers_local}")
            except Exception:
                pass
            return followers_local

        last_followers = []
        for attempt in range(max(0, int(retries)) + 1):
            t0 = time.perf_counter()
            screenshot = self.device_state.take_screenshot()
            if screenshot is None:
                break
            total_shots = max(1, 1 + int(max(0, int(extra_shots))))
            shots = self._scan_our_followers_multi_shot(
                first_screenshot=screenshot,
                total_shots=total_shots,
                sort_desc=bool(sort_desc),
                shot_delay_range=shot_delay_range,
                debug_flag=bool(debug_flag),
                with_names=bool(with_names),
                debug_mode=bool(debug_mode),
            )

            followers = self._aggregate_followers_from_shots(shots, sort_desc=bool(sort_desc))
            last_followers = list(followers or [])

            # Perf record (includes the scan_our_followers path and any extra shots inside it).
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self._record_our_scan_perf(
                mode=mode,
                dt_ms=dt_ms,
                has_followers=bool(followers),
                debug_mode=bool(debug_mode),
            )

            if followers:
                return _finalize_followers(followers)
            if attempt < retries:
                time.sleep(random.uniform(0.12, 0.22))

        # Unified bottom-layer empty confirm scan (total: at most 2 scans when retries=0).
        if not last_followers:
            try:
                self.device_state.sleep(0.2)
                t0 = time.perf_counter()
                screenshot = self.device_state.take_screenshot()
                if screenshot is not None:
                    total_shots = max(1, 1 + int(max(0, int(extra_shots))))
                    confirm_shots = self._scan_our_followers_multi_shot(
                        first_screenshot=screenshot,
                        total_shots=total_shots,
                        sort_desc=bool(sort_desc),
                        shot_delay_range=shot_delay_range,
                        debug_flag=bool(debug_flag),
                        with_names=bool(with_names),
                        debug_mode=bool(debug_mode),
                        phase_tag="confirm",
                    )

                    confirm = self._aggregate_followers_from_shots(
                        confirm_shots,
                        sort_desc=bool(sort_desc),
                    )

                    dt_ms = (time.perf_counter() - t0) * 1000.0
                    self._record_our_scan_perf(
                        mode=mode,
                        dt_ms=dt_ms,
                        has_followers=bool(confirm),
                        debug_mode=bool(debug_mode),
                    )

                    if confirm:
                        return _finalize_followers(confirm)
            except Exception:
                pass

        # Fallback: optionally return cached positions (for non-critical paths).
        if not allow_cached_fallback:
            return []

        # Return cached positions, ensuring order matches caller expectations.
        try:
            cached = self.follower_manager.get_positions() or []
        except Exception:
            cached = []
        try:
            return sorted(list(cached), key=lambda f: int(f[0]) if len(f) > 0 else 0, reverse=bool(sort_desc))
        except Exception:
            return list(cached)

    def _scan_our_followers(
        self,
        screenshot,
        extra_shots: int = 2,
        sort_desc: bool = False,
        shot_delay_range=(0.12, 0.22),
        debug_flag: bool = False,
        with_names: bool = True,
    ):
        """检测场上的我方随从位置和状态"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_our_followers(
                screenshot,
                debug_flag=debug_flag,
                extra_shots=extra_shots,
                sort_desc=sort_desc,
                shot_delay_range=shot_delay_range,
                with_names=with_names,
            )
        return []

    def _scan_shield_targets(self):
        """扫描护盾"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_shield_targets()
        return []

    def _scan_enemy_ATK(self, screenshot):
        """扫描敌方攻击力"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_enemy_ATK(screenshot)
        return []

    def _detect_evolution_button(self, screenshot):
        """检测进化按钮是否出现，彩色"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.template_manager.detect_evolution_button(screenshot)
        return None, 0

    def _detect_super_evolution_button(self, screenshot):
        """检测超进化按钮是否出现，彩色"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.template_manager.detect_super_evolution_button(screenshot)
        return None, 0

    def _load_evolution_template(self):
        """加载进化按钮模板"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.template_manager.load_evolution_template()
        return None

    def _load_super_evolution_template(self):
        """加载超进化按钮模板"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.template_manager.load_super_evolution_template()
        return None
