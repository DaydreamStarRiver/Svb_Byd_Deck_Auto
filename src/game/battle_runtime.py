"""Runtime board state for Step3B battle decisions."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.game.domain import FollowerRuntimeState
from src.utils.card_filename import (
    normalize_card_base_name,
    parse_follower_stat_suffix,
    split_enhance_key,
)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _parse_hp(v: Any) -> Optional[int]:
    if isinstance(v, int):
        return int(v)
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return None


class BattleRuntimeState:
    """Tracks lightweight follower runtime states for target/settlement logic."""

    def __init__(self, *, logger: Any = None):
        self.logger = logger
        self.ours: List[FollowerRuntimeState] = []
        self.enemy: List[FollowerRuntimeState] = []
        self._next_uid: int = 1

    def reset(self, *, reason: str = "") -> None:
        self.ours = []
        self.enemy = []
        self._next_uid = 1
        if reason:
            self._debug(f"reset: {reason}")

    def sync_ours(self, followers: Sequence[Sequence[Any]]) -> List[FollowerRuntimeState]:
        self.ours = self._sync_side(
            existing=self.ours,
            scanned=followers,
            side="ours",
            with_hp=False,
            ward_positions=None,
        )
        self._drop_dead(self.ours)
        return [st for st in list(self.ours) if int(getattr(st, "miss_count", 0) or 0) <= 0]

    def sync_enemy(
        self,
        enemy_followers: Sequence[Sequence[Any]],
        *,
        ward_positions: Optional[Sequence[Sequence[Any]]] = None,
    ) -> List[FollowerRuntimeState]:
        self.enemy = self._sync_side(
            existing=self.enemy,
            scanned=enemy_followers,
            side="enemy",
            with_hp=True,
            ward_positions=ward_positions,
        )
        self._drop_dead(self.enemy)
        return list(self.enemy)

    def mark_our_evolution(
        self,
        follower_pos: Sequence[Any],
        evolved_type: str,
        *,
        cfg_key: str = "",
        fallback_name: str = "",
    ) -> bool:
        state = self._find_ours_for_action(
            follower_pos,
            cfg_key=str(cfg_key or ""),
            fallback_name=str(fallback_name or ""),
        )
        if state is None:
            return False
        return self._mark_state_evolution(state, evolved_type)

    def mark_our_evolution_by_uid(self, uid: Any, evolved_type: str) -> bool:
        state = self._find_ours_by_uid(uid)
        if state is None:
            return False
        return self._mark_state_evolution(state, evolved_type)

    def _mark_state_evolution(self, state: FollowerRuntimeState, evolved_type: str) -> bool:
        mode = str(evolved_type or "none")
        if mode not in ("none", "normal", "super"):
            mode = "none"
        state.evolved_type = mode
        cur_type = str(getattr(state, "follower_type", "normal") or "normal")
        if cur_type == "normal":
            state.follower_type = "yellow"
        elif cur_type in ("green", "yellow"):
            state.follower_type = cur_type
        self._debug(
            "mark_evolution "
            f"uid={int(getattr(state, 'uid', 0) or 0)} "
            f"mode={mode} x={int(getattr(state, 'x', 0) or 0)} "
            f"name={str(getattr(state, 'raw_name', '') or getattr(state, 'base_name', '') or '')}"
        )
        return True

    def mark_our_attack_spent(
        self,
        follower_pos: Optional[Sequence[Any]] = None,
        follower_uid: Any = None,
        fallback_name: str = "",
    ) -> bool:
        state = None
        if follower_uid is not None:
            state = self._find_ours_by_uid(follower_uid)
        if state is None and follower_pos is not None:
            state = self._find_ours_for_action(follower_pos, fallback_name=str(fallback_name or ""))
        if state is None:
            return False
        setattr(state, "_attack_spent_pending", 1)
        setattr(state, "_attack_spent_ts", time.time())
        setattr(state, "_attack_spent_name", str(fallback_name or getattr(state, "raw_name", "") or getattr(state, "base_name", "") or ""))
        self._debug(
            "mark_attack_spent "
            f"uid={int(getattr(state, 'uid', 0) or 0)} x={int(getattr(state, 'x', 0) or 0)} "
            f"name={str(getattr(state, '_attack_spent_name', '') or '')}"
        )
        return True

    def mark_latest_play_origin(
        self,
        *,
        card_name: str,
        cfg_key: str,
    ) -> Optional[Tuple[int, int]]:
        """Mark the most likely newly played follower with its config key.

        Returns follower position when a target was tagged.
        """

        cfg = str(cfg_key or "")
        if not cfg:
            return None

        expected_base = normalize_card_base_name(str(card_name or ""))
        if not expected_base:
            b, _enh = split_enhance_key(cfg)
            expected_base = normalize_card_base_name(str(b or ""))

        def _is_match(st: FollowerRuntimeState) -> bool:
            st_base = normalize_card_base_name(str(getattr(st, "base_name", "") or ""))
            if expected_base and st_base and st_base == expected_base:
                return True
            raw = normalize_card_base_name(str(getattr(st, "raw_name", "") or ""))
            if expected_base and raw and raw == expected_base:
                return True
            return False

        candidates = [st for st in self._active_ours() if _is_match(st)]
        if not candidates:
            candidates = self._active_ours()
        if not candidates:
            return None

        # Prefer rightmost, and prefer states without a specific source key yet.
        picked = sorted(
            candidates,
            key=lambda st: (
                1 if (str(getattr(st, "source_cfg_key", "") or "") in ("", expected_base)) else 0,
                int(getattr(st, "x", 0) or 0),
            ),
            reverse=True,
        )[0]

        picked.source_cfg_key = cfg
        return (int(picked.x), int(picked.y))

    def get_effect_key_for_ours(
        self,
        *,
        follower_pos: Optional[Sequence[Any]],
        follower_uid: Any = None,
        fallback_name: str = "",
    ) -> str:
        state = self._find_ours_by_uid(follower_uid)
        if state is None:
            state = (
                self._find_ours_for_action(follower_pos, fallback_name=str(fallback_name or ""))
                if follower_pos is not None
                else None
            )
        if state is not None:
            key = str(getattr(state, "source_cfg_key", "") or "")
            if key:
                return key
            base = str(getattr(state, "base_name", "") or "")
            if base:
                return base
            raw = str(getattr(state, "raw_name", "") or "")
            if raw:
                return raw
        return str(fallback_name or "")

    def get_ours_uid(
        self,
        follower_pos: Sequence[Any],
        *,
        fallback_name: str = "",
    ) -> Optional[int]:
        state = self._find_ours_for_action(
            follower_pos,
            cfg_key="",
            fallback_name=str(fallback_name or ""),
        )
        if state is None:
            return None
        uid = _safe_int(getattr(state, "uid", 0), 0)
        return int(uid) if uid > 0 else None

    def find_ours_pos_by_uid(self, uid: Any) -> Optional[Tuple[int, int]]:
        st = self._find_ours_by_uid(uid)
        if st is None:
            return None
        return (int(st.x), int(st.y))

    def find_ours_pos_by_cfg_key(
        self,
        *,
        cfg_key: str,
        fallback_name: str = "",
    ) -> Optional[Tuple[int, int]]:
        key = str(cfg_key or "")
        if not key:
            return None

        expected_base = normalize_card_base_name(str(fallback_name or ""))
        if not expected_base:
            b, _enh = split_enhance_key(key)
            expected_base = normalize_card_base_name(str(b or ""))

        exact = [
            st
            for st in self._active_ours()
            if str(getattr(st, "source_cfg_key", "") or "") == key
        ]
        if exact:
            picked = sorted(exact, key=lambda st: int(getattr(st, "x", 0) or 0), reverse=True)[0]
            return (int(picked.x), int(picked.y))

        if not expected_base:
            return None

        by_base = [
            st
            for st in self._active_ours()
            if normalize_card_base_name(str(getattr(st, "base_name", "") or "")) == expected_base
        ]
        if not by_base:
            return None

        picked = sorted(by_base, key=lambda st: int(getattr(st, "x", 0) or 0), reverse=True)[0]
        return (int(picked.x), int(picked.y))

    def apply_buff(
        self,
        *,
        source_pos: Optional[Sequence[Any]],
        source_uid: Any = None,
        target_mode: str,
        atk_delta: int,
        hp_delta: int,
        round_index: Optional[int] = None,
    ) -> int:
        atk_v = _safe_int(atk_delta, 0)
        hp_v = _safe_int(hp_delta, 0)
        if atk_v == 0 and hp_v == 0:
            return 0

        mode = str(target_mode or "others")
        if mode not in ("others", "self"):
            mode = "others"

        source = self._find_ours_by_uid(source_uid)
        if source is None and source_pos is not None:
            source = self._find_state(self.ours, source_pos)
        changed = 0

        for st in self._active_ours():
            is_source = source is not None and st is source

            if mode == "self":
                if not is_source:
                    continue
            else:
                if is_source:
                    continue

            st.buff_atk += atk_v
            st.buff_hp += hp_v

            changed += 1

        return changed

    def apply_attack_times_buff(
        self,
        *,
        source_pos: Optional[Sequence[Any]],
        source_uid: Any = None,
        target_mode: str,
        attack_times: int,
        round_index: Optional[int] = None,
    ) -> int:
        attack_times_v = max(1, _safe_int(attack_times, 1))

        mode = str(target_mode or "others")
        if mode not in ("others", "self"):
            mode = "others"

        source = self._find_ours_by_uid(source_uid)
        if source is None and source_pos is not None:
            source = self._find_state(self.ours, source_pos)
        changed = 0

        for st in self._active_ours():
            is_source = source is not None and st is source

            if mode == "self":
                if not is_source:
                    continue
            else:
                if is_source:
                    continue

            ri = _safe_int(round_index, -1) if round_index is not None else -1
            prev_round = _safe_int(getattr(st, "attack_times_round", -1), -1)
            prev_total = max(1, _safe_int(getattr(st, "attack_times_total", 1), 1))

            if ri >= 0:
                if prev_round == ri:
                    st.attack_times_total = max(prev_total, int(attack_times_v))
                else:
                    st.attack_times_round = int(ri)
                    st.attack_times_total = int(attack_times_v)
            else:
                st.attack_times_total = max(prev_total, int(attack_times_v))

            changed += 1

        return changed

    def apply_buff_others(
        self,
        *,
        source_pos: Optional[Sequence[Any]],
        amount: int,
    ) -> int:
        value = _safe_int(amount, 0)
        return self.apply_buff(
            source_pos=source_pos,
            target_mode="others",
            atk_delta=value,
            hp_delta=value,
        )

    def apply_buff_self(
        self,
        *,
        source_pos: Optional[Sequence[Any]],
        amount: int,
    ) -> int:
        value = _safe_int(amount, 0)
        return self.apply_buff(
            source_pos=source_pos,
            target_mode="self",
            atk_delta=value,
            hp_delta=value,
        )

    def get_ours_attack_times(
        self,
        follower_pos: Sequence[Any],
        *,
        round_index: Optional[int] = None,
    ) -> int:
        """Return allowed attack count for the specified friendly follower in round."""

        st = self._find_state(self.ours, follower_pos)
        if st is None:
            return 1

        if round_index is not None:
            st_round = _safe_int(getattr(st, "attack_times_round", -1), -1)
            if st_round != _safe_int(round_index, -1):
                return 1

        return max(1, _safe_int(getattr(st, "attack_times_total", 1), 1))

    def pick_enemy_target(
        self,
        *,
        attacker_pos: Sequence[Any],
        ward_only: bool = False,
    ) -> Tuple[Optional[FollowerRuntimeState], Dict[str, Any]]:
        attacker = self._find_state(self.ours, attacker_pos)
        attacker_atk = attacker.effective_atk() if attacker is not None else None

        candidates = [e for e in self.enemy if (e.is_ward if ward_only else True)]
        if not candidates:
            return None, {
                "mode": "no_candidates",
                "attacker_atk": attacker_atk,
                "ward_only": bool(ward_only),
            }

        hp_known = [(c, c.current_hp()) for c in candidates if c.current_hp() is not None]

        if attacker_atk is not None and hp_known:
            lethal: List[Tuple[FollowerRuntimeState, int, int]] = []
            for c, hp in hp_known:
                hp_i = _safe_int(hp, 0)
                residual = hp_i - int(attacker_atk)
                if residual <= 0:
                    lethal.append((c, hp_i, residual))
            if lethal:
                target, hp_i, residual = max(lethal, key=lambda it: (int(it[2]), int(it[0].x)))
                return target, {
                    "mode": "kill_overflow",
                    "attacker_atk": attacker_atk,
                    "target_hp": hp_i,
                    "residual": residual,
                    "ward_only": bool(ward_only),
                }

        if hp_known:
            target, hp_i = min(
                hp_known,
                key=lambda it: (_safe_int(it[1], 999), -_safe_int(it[0].x, 0)),
            )
            return target, {
                "mode": "fallback_min_hp",
                "attacker_atk": attacker_atk,
                "target_hp": _safe_int(hp_i, 0),
                "ward_only": bool(ward_only),
            }

        target = max(candidates, key=lambda it: int(it.x))
        return target, {
            "mode": "fallback_rightmost_unknown_hp",
            "attacker_atk": attacker_atk,
            "target_hp": None,
            "ward_only": bool(ward_only),
        }

    def apply_local_combat(
        self,
        *,
        attacker_pos: Sequence[Any],
        target_pos: Sequence[Any],
    ) -> Dict[str, Any]:
        attacker = self._find_state(self.ours, attacker_pos)
        target = self._find_state(self.enemy, target_pos)
        if target is None:
            return {"applied": False}

        attacker_atk = attacker.effective_atk() if attacker is not None else None
        target_atk = target.effective_atk()

        target_hp_before = target.current_hp()
        if attacker_atk is not None:
            if target.hp0 is not None:
                target.damage_taken += int(attacker_atk)
            if target.observed_hp is not None:
                target.observed_hp = max(0, int(target.observed_hp) - int(attacker_atk))

        target_hp_after = target.current_hp()
        target_dead = target_hp_after is not None and int(target_hp_after) <= 0

        attacker_hp_before = attacker.current_hp() if attacker is not None else None
        attacker_dead = False

        if attacker is not None and attacker.evolved_type != "super":
            if target_atk is not None and attacker.hp0 is not None:
                attacker.damage_taken += int(target_atk)
                if attacker.observed_hp is not None:
                    attacker.observed_hp = max(0, int(attacker.observed_hp) - int(target_atk))
                attacker_hp_after = attacker.current_hp()
                attacker_dead = attacker_hp_after is not None and int(attacker_hp_after) <= 0

        if target_dead:
            self.enemy = [e for e in self.enemy if e is not target]
        if attacker is not None and attacker_dead:
            self.ours = [o for o in self.ours if o is not attacker]

        return {
            "applied": True,
            "attacker_name": getattr(attacker, "base_name", "") if attacker is not None else "",
            "attacker_atk": attacker_atk,
            "attacker_hp_before": attacker_hp_before,
            "attacker_dead": attacker_dead,
            "target_name": target.base_name,
            "target_hp_before": target_hp_before,
            "target_hp_after": target_hp_after,
            "target_dead": target_dead,
        }

    def _parse_scanned_item(
        self,
        item: Sequence[Any],
        *,
        side: str,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None

        x = _safe_int(item[0], 0)
        y = _safe_int(item[1], 0)
        ftype = str(item[2] if len(item) > 2 else "normal")

        raw_name = ""
        if len(item) > 3 and isinstance(item[3], str):
            raw_name = str(item[3] or "")

        parsed_base = ""
        parsed_atk = None
        parsed_hp = None
        if raw_name:
            parsed_base, parsed_atk, parsed_hp = parse_follower_stat_suffix(raw_name)
            parsed_base = str(parsed_base or raw_name)

        norm_base = normalize_card_base_name(parsed_base)
        if str(side) != "ours":
            # Enemy slot payload at item[3] is usually HP text, not reliable name.
            norm_base = ""

        return {
            "x": int(x),
            "y": int(y),
            "ftype": ftype,
            "raw_name": raw_name,
            "parsed_base": parsed_base,
            "parsed_atk": parsed_atk,
            "parsed_hp": parsed_hp,
            "norm_base": norm_base,
            "hp_field": item[3] if len(item) > 3 else None,
        }

    def _match_runtime_marked_ours_index(
        self,
        existing: Sequence[FollowerRuntimeState],
        used: Iterable[int],
        *,
        x: int,
        y: int,
        norm_base: str,
    ) -> Optional[int]:
        used_set = set(used)
        best_idx = None
        best_score = 10**9

        for i, st in enumerate(list(existing or [])):
            if i in used_set:
                continue
            if not self._has_runtime_marks(st):
                continue

            dx = abs(int(getattr(st, "x", 0)) - int(x))
            dy = abs(int(getattr(st, "y", 0)) - int(y))
            if dx > 176 or dy > 150:
                continue

            score = dx * 2 + dy
            if norm_base:
                st_base = normalize_card_base_name(
                    str(getattr(st, "base_name", "") or getattr(st, "raw_name", "") or "")
                )
                if st_base and st_base != norm_base:
                    continue
                if st_base and st_base == norm_base:
                    score -= 300
                else:
                    score += 120

            if score < best_score:
                best_score = score
                best_idx = i

        return best_idx

    def _pick_existing_index_for_scan(
        self,
        *,
        existing: Sequence[FollowerRuntimeState],
        used: Iterable[int],
        side: str,
        x: int,
        y: int,
        norm_base: str,
        x_limit: int,
        y_limit: int,
    ) -> Optional[int]:
        idx = None

        if norm_base:
            idx = self._match_existing_index(
                existing,
                used,
                x,
                y,
                expected_base=norm_base,
                x_limit=max(220, x_limit),
                y_limit=max(150, y_limit),
            )

        if idx is None and not norm_base:
            idx = self._match_existing_index(
                existing,
                used,
                x,
                y,
                expected_base="",
                x_limit=x_limit,
                y_limit=y_limit,
            )

        if idx is None and str(side) == "ours":
            idx = self._match_runtime_marked_ours_index(
                existing,
                used,
                x=x,
                y=y,
                norm_base=norm_base,
            )

        return idx

    def _build_or_reuse_state(
        self,
        *,
        existing: Sequence[FollowerRuntimeState],
        used: set[int],
        idx: Optional[int],
        side: str,
    ) -> FollowerRuntimeState:
        if idx is not None:
            st = existing[idx]
            used.add(int(idx))
        else:
            st = FollowerRuntimeState(side=side)
            st.uid = self._alloc_uid()

        if _safe_int(getattr(st, "uid", 0), 0) <= 0:
            st.uid = self._alloc_uid()
        return st

    def _apply_scanned_fields(
        self,
        st: FollowerRuntimeState,
        *,
        side: str,
        scan: Dict[str, Any],
        with_hp: bool,
        wards: Sequence[Sequence[Any]],
    ) -> None:
        x = _safe_int(scan.get("x"), 0)
        y = _safe_int(scan.get("y"), 0)
        ftype = str(scan.get("ftype") or "normal")
        raw_name = str(scan.get("raw_name") or "")
        parsed_base = str(scan.get("parsed_base") or "")
        parsed_atk = scan.get("parsed_atk")
        parsed_hp = scan.get("parsed_hp")

        st.side = side
        st.x = int(x)
        st.y = int(y)
        old_type = str(getattr(st, "follower_type", "normal") or "normal")
        if side == "ours" and ftype == "normal" and old_type in ("green", "yellow"):
            pending = int(getattr(st, "_attack_spent_pending", 0) or 0)
            pending_ts = float(getattr(st, "_attack_spent_ts", 0.0) or 0.0)
            pending_fresh = bool(pending > 0 and pending_ts > 0.0 and (time.time() - pending_ts) <= 3.0)
            if pending_fresh:
                st.follower_type = "normal"
                try:
                    delattr(st, "_attack_spent_pending")
                except Exception:
                    setattr(st, "_attack_spent_pending", 0)
                try:
                    delattr(st, "_attack_spent_ts")
                except Exception:
                    setattr(st, "_attack_spent_ts", 0.0)
                self._debug(
                    f"accept normal after attack uid={int(getattr(st, 'uid', 0) or 0)} old={old_type}"
                )
            else:
                if pending > 0:
                    try:
                        delattr(st, "_attack_spent_pending")
                    except Exception:
                        setattr(st, "_attack_spent_pending", 0)
                    try:
                        delattr(st, "_attack_spent_ts")
                    except Exception:
                        setattr(st, "_attack_spent_ts", 0.0)
                st.follower_type = old_type
                self._debug(
                    f"keep {old_type} over raw normal uid={int(getattr(st, 'uid', 0) or 0)}"
                )
        else:
            st.follower_type = ftype

        if side == "enemy":
            st.is_ward = any(abs(int(x) - _safe_int(w[0], 0)) < 50 for w in wards if len(w) >= 1)

        if raw_name:
            st.raw_name = raw_name
            st.base_name = parsed_base if parsed_base else raw_name
            if parsed_atk is not None:
                st.atk0 = int(parsed_atk)
            if parsed_hp is not None:
                st.hp0 = int(parsed_hp)
        elif not st.base_name:
            st.base_name = st.raw_name or ""

        st.miss_count = 0

        if with_hp:
            hp_seen = _parse_hp(scan.get("hp_field"))
            if hp_seen is not None:
                hp_seen_i = int(hp_seen)
                st.observed_hp = hp_seen_i
                if st.hp0 is None:
                    st.hp0 = hp_seen_i
                total = int(st.hp0 or hp_seen_i) + int(st.evolution_bonus()) + int(st.buff_hp)
                if hp_seen_i > total:
                    st.hp0 = hp_seen_i - int(st.evolution_bonus()) - int(st.buff_hp)
                    st.damage_taken = 0
                else:
                    st.damage_taken = max(0, total - hp_seen_i)

    def _append_preserved_unseen_ours(
        self,
        out: List[FollowerRuntimeState],
        *,
        existing: Sequence[FollowerRuntimeState],
        used: Iterable[int],
    ) -> None:
        used_set = set(used)
        for i, st in enumerate(list(existing or [])):
            if i in used_set:
                continue
            if not self._should_preserve_unseen_ours(st):
                continue
            st.miss_count = int(getattr(st, "miss_count", 0) or 0) + 1
            if st.miss_count > 2:
                continue
            out.append(st)

    def _sync_side(
        self,
        *,
        existing: Sequence[FollowerRuntimeState],
        scanned: Sequence[Sequence[Any]],
        side: str,
        with_hp: bool,
        ward_positions: Optional[Sequence[Sequence[Any]]],
    ) -> List[FollowerRuntimeState]:
        used: set[int] = set()
        out: List[FollowerRuntimeState] = []
        wards = list(ward_positions or [])

        x_limit = 128 if str(side) == "ours" else 72
        y_limit = 120 if str(side) == "ours" else 90

        for item in list(scanned or []):
            scan = self._parse_scanned_item(item, side=side)
            if scan is None:
                continue

            idx = self._pick_existing_index_for_scan(
                existing=existing,
                used=used,
                side=side,
                x=_safe_int(scan.get("x"), 0),
                y=_safe_int(scan.get("y"), 0),
                norm_base=str(scan.get("norm_base") or ""),
                x_limit=x_limit,
                y_limit=y_limit,
            )

            st = self._build_or_reuse_state(
                existing=existing,
                used=used,
                idx=idx,
                side=side,
            )

            self._apply_scanned_fields(
                st,
                side=side,
                scan=scan,
                with_hp=bool(with_hp),
                wards=wards,
            )

            out.append(st)

        if str(side) == "ours" and existing:
            self._append_preserved_unseen_ours(out, existing=existing, used=used)

        out = sorted(out, key=lambda s: int(s.x), reverse=True)
        return out

    def _match_existing_index(
        self,
        existing: Sequence[FollowerRuntimeState],
        used: Iterable[int],
        x: int,
        y: int,
        *,
        expected_base: str = "",
        x_limit: int = 72,
        y_limit: int = 90,
    ) -> Optional[int]:
        used_set = set(used)
        best_idx = None
        best_score = 10**9
        for i, st in enumerate(list(existing or [])):
            if i in used_set:
                continue
            dx = abs(int(st.x) - int(x))
            dy = abs(int(st.y) - int(y))
            if dx > int(x_limit) or dy > int(y_limit):
                continue
            score = dx * 2 + dy
            if expected_base:
                st_base = normalize_card_base_name(
                    str(getattr(st, "base_name", "") or getattr(st, "raw_name", "") or "")
                )
                if st_base and st_base != expected_base:
                    continue
                if st_base and st_base == expected_base:
                    score -= 420
                else:
                    score += 120
            if str(getattr(st, "source_cfg_key", "") or ""):
                score -= 20
            if score < best_score:
                best_score = score
                best_idx = i
        return best_idx

    @staticmethod
    def _has_runtime_marks(st: FollowerRuntimeState) -> bool:
        return bool(
            str(getattr(st, "source_cfg_key", "") or "")
            or int(getattr(st, "buff_atk", 0) or 0) != 0
            or int(getattr(st, "buff_hp", 0) or 0) != 0
            or str(getattr(st, "evolved_type", "none") or "none") != "none"
        )

    def _should_preserve_unseen_ours(self, st: FollowerRuntimeState) -> bool:
        # 仅在短时间内保留高价值状态，避免无名帧导致BUFF/进化/来源键丢失。
        if self._has_runtime_marks(st):
            return True

        # 已有明确基础身材/名字的随从，也允许短暂保留一小段时间。
        if str(getattr(st, "raw_name", "") or ""):
            return True
        if getattr(st, "atk0", None) is not None or getattr(st, "hp0", None) is not None:
            return True
        return False

    def _find_ours_by_uid(self, uid: Any) -> Optional[FollowerRuntimeState]:
        uid_i = _safe_int(uid, 0)
        if uid_i <= 0:
            return None
        for st in list(self.ours or []):
            if int(getattr(st, "miss_count", 0) or 0) > 0:
                continue
            if _safe_int(getattr(st, "uid", 0), 0) == uid_i:
                return st
        return None

    def _active_ours(self) -> List[FollowerRuntimeState]:
        return [st for st in list(self.ours or []) if int(getattr(st, "miss_count", 0) or 0) <= 0]

    def _find_state(
        self,
        states: Sequence[FollowerRuntimeState],
        pos: Sequence[Any],
        *,
        expected_base: str = "",
        prefer_cfg_key: str = "",
        x_limit: int = 84,
        y_limit: int = 110,
    ) -> Optional[FollowerRuntimeState]:
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            return None
        x = _safe_int(pos[0], 0)
        y = _safe_int(pos[1], 0)

        best: Optional[FollowerRuntimeState] = None
        best_score = 10**9
        for st in list(states or []):
            if str(getattr(st, "side", "") or "") == "ours" and int(getattr(st, "miss_count", 0) or 0) > 0:
                continue
            dx = abs(int(st.x) - int(x))
            dy = abs(int(st.y) - int(y))
            if dx > int(x_limit) or dy > int(y_limit):
                continue
            score = dx * 2 + dy
            if expected_base:
                st_base = normalize_card_base_name(
                    str(getattr(st, "base_name", "") or getattr(st, "raw_name", "") or "")
                )
                if st_base and st_base == expected_base:
                    score -= 320
                elif st_base:
                    score += 140
            if prefer_cfg_key:
                cfg = str(getattr(st, "source_cfg_key", "") or "")
                if cfg == prefer_cfg_key:
                    score -= 360
            if score < best_score:
                best_score = score
                best = st
        return best

    def _find_ours_for_action(
        self,
        pos: Sequence[Any],
        *,
        cfg_key: str = "",
        fallback_name: str = "",
    ) -> Optional[FollowerRuntimeState]:
        key = str(cfg_key or "")
        expected_base = normalize_card_base_name(str(fallback_name or ""))
        if not expected_base and key:
            b, _enh = split_enhance_key(key)
            expected_base = normalize_card_base_name(str(b or ""))

        if key:
            st = self._find_state(
                self.ours,
                pos,
                expected_base=expected_base,
                prefer_cfg_key=key,
                x_limit=140,
                y_limit=150,
            )
            if st is not None and str(getattr(st, "source_cfg_key", "") or "") == key:
                return st

            exact = [
                s
                for s in list(self.ours or [])
                if str(getattr(s, "source_cfg_key", "") or "") == key
                and int(getattr(s, "miss_count", 0) or 0) <= 0
            ]
            if exact:
                try:
                    px = _safe_int(pos[0], 0)
                    py = _safe_int(pos[1], 0)
                except Exception:
                    px, py = 0, 0
                return min(
                    exact,
                    key=lambda s: abs(int(getattr(s, "x", 0)) - px) * 2
                    + abs(int(getattr(s, "y", 0)) - py),
                )

        st = self._find_state(
            self.ours,
            pos,
            expected_base=expected_base,
            x_limit=130,
            y_limit=140,
        )
        if st is not None:
            return st

        return self._find_state(self.ours, pos)

    def _alloc_uid(self) -> int:
        uid = max(1, int(getattr(self, "_next_uid", 1) or 1))
        self._next_uid = int(uid) + 1
        return int(uid)

    def _drop_dead(self, states: List[FollowerRuntimeState]) -> None:
        keep: List[FollowerRuntimeState] = []
        for st in list(states or []):
            hp = st.current_hp()
            if hp is not None and int(hp) <= 0:
                continue
            keep.append(st)
        states[:] = keep

    def _debug(self, msg: str) -> None:
        try:
            if self.logger is not None:
                self.logger.debug(f"[Runtime] {msg}")
        except Exception:
            pass
