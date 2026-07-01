"""Strategy effects schema helpers.

Important: this module must stay lightweight because UI imports it.
It should not import cv/u2/game modules.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from src.config.effects_registry import get_operation
from src.utils.card_filename import (
    make_enhance_key,
    normalize_card_base_name,
    parse_follower_stat_suffix,
    split_enhance_key,
)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def convert_legacy_target_type_to_ops(target_type: Any) -> List[Dict[str, Any]]:
    """Convert legacy ``target_type`` string to canonical Step3A ops."""

    tt = str(target_type or "")
    if not tt:
        return []

    if tt == "enemy_player":
        return [
            {
                "op": "select_targets",
                "target": {"kind": "enemy_leader", "selector": "", "params": {}},
                "count": 1,
                "distinct_xy": True,
                "is_select_ui": True,
            }
        ]

    if tt == "shield_or_highest_hp":
        return [
            {
                "op": "select_targets",
                "target": {
                    "kind": "enemy_follower",
                    "selector": "ward_or_highest_hp",
                    "params": {"allow_amulet_fallback": True},
                },
                "count": 1,
                "distinct_xy": True,
                "is_select_ui": True,
            }
        ]

    if tt == "double_enemy":
        return [
            {
                "op": "select_targets",
                "target": {
                    "kind": "enemy_follower",
                    "selector": "highest_hp",
                    "params": {},
                },
                "count": 2,
                "distinct_xy": True,
                "is_select_ui": True,
            }
        ]

    if tt == "enemy_followers_hp_less_than_6":
        return [
            {
                "op": "select_targets",
                "target": {
                    "kind": "enemy_follower",
                    "selector": "hp_leq_or_highest_hp",
                    "params": {"max_hp": 5, "fallback_to_enemy_leader": True},
                },
                "count": 1,
                "distinct_xy": True,
                "is_select_ui": True,
            }
        ]

    if tt == "shield_or_highest_hp_no_enemy_retrun_point":
        return [
            {
                "op": "select_targets",
                "target": {
                    "kind": "enemy_follower",
                    "selector": "ward_or_highest_hp",
                    "params": {"allow_amulet_fallback": False},
                },
                "count": 1,
                "distinct_xy": True,
                "is_select_ui": True,
            }
        ]

    if tt == "scan_our_follower_to_choose":
        return [
            {
                "op": "select_option_by_our_followers",
                "threshold": 3,
                "le_option": 1,
                "gt_option": 2,
            }
        ]

    return []


def convert_legacy_action_to_ops(action: Any) -> List[Dict[str, Any]]:
    """Convert legacy ``action`` string to canonical Step3A ops."""

    act = str(action or "")
    if not act:
        return []

    if act == "attack_enemy_follower_hp_less_than_4":
        return [
            {
                "op": "select_targets",
                "target": {
                    "kind": "enemy_follower",
                    "selector": "hp_leq",
                    "params": {"max_hp": 3},
                },
                "count": 1,
                "distinct_xy": True,
                "is_select_ui": True,
            }
        ]

    if act == "attack_two_enemy_followers_hp_less_than_4":
        return [
            {
                "op": "select_targets",
                "target": {
                    "kind": "enemy_follower",
                    "selector": "hp_leq",
                    "params": {"max_hp": 3},
                },
                "count": 2,
                "distinct_xy": True,
                "is_select_ui": True,
            }
        ]

    if act == "attack_two_enemy_followers_hp_highest":
        # Preserve legacy runtime behavior: this action historically clicked 1 target.
        return [
            {
                "op": "select_targets",
                "target": {
                    "kind": "enemy_follower",
                    "selector": "highest_hp",
                    "params": {},
                },
                "count": 1,
                "distinct_xy": True,
                "is_select_ui": True,
            }
        ]

    if act == "our_followers_with_evolution":
        return [
            {
                "op": "select_targets",
                "target": {
                    "kind": "friendly_follower",
                    "selector": "by_evolve_priority",
                    "params": {"exclude_self": True},
                },
                "count": 1,
                "distinct_xy": True,
                "is_select_ui": False,
            }
        ]

    return []


def _effect_key_candidates(card_name: str) -> List[str]:
    raw = str(card_name or "")
    if not raw:
        return []

    out: List[str] = [raw]
    base = raw
    enhance_cost = None

    if "@" in raw:
        b, c = split_enhance_key(raw)
        base = str(b or "")
        enhance_cost = c
        if base and base not in out:
            out.append(base)

    stripped, _atk, _hp = parse_follower_stat_suffix(base)
    if stripped and stripped != base:
        if enhance_cost is not None:
            enh_key = make_enhance_key(stripped, int(enhance_cost))
            if enh_key not in out:
                out.append(enh_key)
        if stripped not in out:
            out.append(stripped)

    normalized_base = normalize_card_base_name(base)
    if normalized_base:
        if enhance_cost is not None:
            enh_key = make_enhance_key(normalized_base, int(enhance_cost))
            if enh_key not in out:
                out.append(enh_key)
        if normalized_base not in out:
            out.append(normalized_base)

    return out


def _base_name_no_suffix(name: str) -> str:
    raw = str(name or "")
    if not raw:
        return ""
    stripped, _atk, _hp = parse_follower_stat_suffix(raw)
    return str(stripped or raw)


def _first_effect_steps(
    effects: Dict[str, Any],
    *,
    candidate_keys: Sequence[str],
    trigger: str,
) -> List[Dict[str, Any]]:
    trig = str(trigger or "")
    for key in list(candidate_keys or []):
        k = str(key or "")
        if not k:
            continue
        card_eff = effects.get(k, {})
        if not isinstance(card_eff, dict):
            continue
        steps = card_eff.get(trig, [])
        if not isinstance(steps, list):
            continue
        normalized = [s for s in steps if isinstance(s, dict)]
        if normalized:
            return normalized
    return []


def _step_effect_signature(step: Dict[str, Any]) -> Optional[tuple[Any, ...]]:
    if not isinstance(step, dict):
        return None

    op = str(step.get("op") or "")
    if not op:
        if "select_option" in step:
            op = "select_option"
        elif "target_type" in step:
            op = "legacy_target_type"
        elif "action" in step:
            op = "legacy_action"

    if op == "buff_others":
        return ("buff", "others")
    if op == "buff":
        return ("buff", str(step.get("target") or "others"))
    if op == "buff_attack_times":
        return ("buff_attack_times", str(step.get("target") or "others"))
    if op == "select_option":
        return ("select_option",)
    if op == "select_option_by_our_followers":
        return ("select_option_by_our_followers",)
    if op == "cancel_action":
        return ("cancel_action",)
    if op == "disallow_empty_evolve":
        return ("disallow_empty_evolve",)
    if op == "legacy_target_type":
        return ("legacy_target_type", str(step.get("target_type") or ""))
    if op == "legacy_action":
        return ("legacy_action", str(step.get("action") or ""))
    if op == "select_targets":
        target = step.get("target")
        if isinstance(target, dict):
            kind = str(target.get("kind") or "")
            selector = str(target.get("selector") or "")
            return ("select_targets", kind, selector)
        return ("select_targets", "", "")
    if op:
        return ("op", op)
    return None


def _merge_steps_with_enhance_override(
    base_steps: Sequence[Dict[str, Any]],
    enhance_steps: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out = [dict(s) for s in list(base_steps or []) if isinstance(s, dict)]

    if not enhance_steps:
        return out

    for es in list(enhance_steps or []):
        if not isinstance(es, dict):
            continue

        sig = _step_effect_signature(es)
        if sig is not None:
            out = [bs for bs in out if _step_effect_signature(bs) != sig]

        try:
            es_key = json.dumps(es, ensure_ascii=False, sort_keys=True)
        except Exception:
            es_key = ""
        if es_key:
            duplicated = False
            for bs in out:
                try:
                    if json.dumps(bs, ensure_ascii=False, sort_keys=True) == es_key:
                        duplicated = True
                        break
                except Exception:
                    continue
            if duplicated:
                continue

        out.append(dict(es))

    return out


def get_card_effect_steps(
    config: Dict[str, Any] | None,
    *,
    card_name: str,
    trigger: str,
) -> List[Dict[str, Any]]:
    if not isinstance(config, dict):
        return []
    effects = config.get("strategy", {}).get("effects", {})
    if not isinstance(effects, dict):
        return []

    raw = str(card_name or "")
    trig = str(trigger or "")
    if not raw:
        return []

    # Enhance key behavior:
    # - inherit base trigger effects
    # - if enhance defines the same effect kind, enhance overrides that effect
    # - different effects are merged (base first, enhance appended)
    if "@" in raw:
        base_raw, enhance_cost = split_enhance_key(raw)
        base_name = _base_name_no_suffix(str(base_raw or ""))

        enhance_key_candidates: List[str] = []
        if enhance_cost is not None and base_name:
            enhance_key_candidates.append(make_enhance_key(base_name, int(enhance_cost)))
        enhance_key_candidates.extend(_effect_key_candidates(raw))

        base_key_candidates: List[str] = []
        if base_name:
            base_key_candidates.append(base_name)
        base_key_candidates.extend(_effect_key_candidates(str(base_raw or "")))

        # de-dup while preserving order
        def _dedup(seq: Sequence[str]) -> List[str]:
            seen = set()
            out: List[str] = []
            for it in list(seq or []):
                k = str(it or "")
                if not k or k in seen:
                    continue
                seen.add(k)
                out.append(k)
            return out

        enhance_steps = _first_effect_steps(
            effects,
            candidate_keys=_dedup(enhance_key_candidates),
            trigger=trig,
        )
        base_steps = _first_effect_steps(
            effects,
            candidate_keys=_dedup(base_key_candidates),
            trigger=trig,
        )

        if enhance_steps:
            return _merge_steps_with_enhance_override(base_steps, enhance_steps)
        return base_steps

    for key in _effect_key_candidates(raw):
        card_eff = effects.get(key, {})
        if not isinstance(card_eff, dict):
            continue
        steps = card_eff.get(trig, [])
        if not isinstance(steps, list):
            continue
        normalized = [s for s in steps if isinstance(s, dict)]
        if normalized:
            return normalized
    return []


def normalize_effect_steps_to_ops(steps: Sequence[Any]) -> List[Dict[str, Any]]:
    """Normalize legacy Step2B steps to Step3A OperationSpec dicts.

    Supported legacy keys:
    - {"select_option": 1/2/3} -> {"op": "select_option", "index": 1/2/3}
    - {"target_type": "..."} -> canonical ops (select_targets / select_option_by_our_followers)
    - {"action": "..."} -> canonical ops (select_targets)

    Legacy op wrappers are also canonicalized:
    - {"op":"legacy_target_type", ...}
    - {"op":"legacy_action", ...}
    """

    def _norm_select_option(v: Any) -> int | None:
        if v in (1, "1", "选项1", "Option1", "option1"):
            return 1
        if v in (2, "2", "选项2", "Option2", "option2"):
            return 2
        if v in (3, "3", "选项3", "Option3", "option3"):
            return 3
        return None

    def _attach_on_error(items: Sequence[Dict[str, Any]], src_step: Dict[str, Any]) -> List[Dict[str, Any]]:
        on_error = src_step.get("on_error") if isinstance(src_step, dict) else None
        if on_error in (None, ""):
            return [dict(it) for it in list(items or []) if isinstance(it, dict)]

        out: List[Dict[str, Any]] = []
        for it in list(items or []):
            if not isinstance(it, dict):
                continue
            row = dict(it)
            if "on_error" not in row:
                row["on_error"] = on_error
            out.append(row)
        return out

    ops: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue

        op_id = step.get("op")
        if isinstance(op_id, str) and op_id:
            if op_id == "select_targets":
                target = step.get("target")
                if isinstance(target, dict) and str(target.get("kind") or "") == "option":
                    params_obj = target.get("params")
                    idx = _norm_select_option(params_obj.get("index")) if isinstance(params_obj, dict) else None
                    if idx is not None:
                        normalized: Dict[str, Any] = {"op": "select_option", "index": int(idx)}
                        if isinstance(params_obj, dict) and params_obj.get("option_count") is not None:
                            normalized["option_count"] = _safe_int(params_obj.get("option_count"), 2)
                        elif step.get("option_count") is not None:
                            normalized["option_count"] = _safe_int(step.get("option_count"), 2)
                        if step.get("on_error"):
                            normalized["on_error"] = step.get("on_error")
                        ops.append(normalized)
                        continue

            if get_operation(op_id) is not None:
                if op_id == "select_option":
                    idx = _norm_select_option(step.get("index"))
                    if idx is not None and step.get("index") != idx:
                        normalized = dict(step)
                        normalized["index"] = int(idx)
                        ops.append(normalized)
                        continue
                ops.append(dict(step))
                continue

            if op_id == "legacy_target_type":
                ops.extend(_attach_on_error(convert_legacy_target_type_to_ops(step.get("target_type")), step))
                continue
            if op_id == "legacy_action":
                ops.extend(_attach_on_error(convert_legacy_action_to_ops(step.get("action")), step))
                continue
            if op_id == "buff_others":
                amount = step.get("amount", 0)
                try:
                    amount_i = int(amount)
                except Exception:
                    amount_i = 0
                ops.append(
                    {
                        "op": "buff",
                        "target": "others",
                        "atk_delta": int(amount_i),
                        "hp_delta": int(amount_i),
                    }
                )
                if step.get("on_error"):
                    ops[-1]["on_error"] = step.get("on_error")
                continue
            if op_id == "buff_self":
                amount = step.get("amount", 0)
                try:
                    amount_i = int(amount)
                except Exception:
                    amount_i = 0
                ops.append(
                    {
                        "op": "buff",
                        "target": "self",
                        "atk_delta": int(amount_i),
                        "hp_delta": int(amount_i),
                    }
                )
                if step.get("on_error"):
                    ops[-1]["on_error"] = step.get("on_error")
                continue
            ops.append(dict(step))
            continue

        if "select_option" in step:
            opt = _norm_select_option(step.get("select_option"))
            if opt is not None:
                ops.append({"op": "select_option", "index": int(opt)})

        if "target_type" in step:
            ops.extend(_attach_on_error(convert_legacy_target_type_to_ops(step.get("target_type")), step))

        if "action" in step:
            ops.extend(_attach_on_error(convert_legacy_action_to_ops(step.get("action")), step))

        target = step.get("target")
        if isinstance(target, dict) and str(target.get("kind") or "") == "option":
            params_obj = target.get("params")
            opt = _norm_select_option(params_obj.get("index")) if isinstance(params_obj, dict) else None
            if opt is not None:
                normalized = {"op": "select_option", "index": int(opt)}
                if isinstance(params_obj, dict) and params_obj.get("option_count") is not None:
                    normalized["option_count"] = _safe_int(params_obj.get("option_count"), 2)
                elif step.get("option_count") is not None:
                    normalized["option_count"] = _safe_int(step.get("option_count"), 2)
                ops.append(normalized)

    return ops


def get_card_effect_ops(
    config: Dict[str, Any] | None,
    *,
    card_name: str,
    trigger: str,
) -> List[Dict[str, Any]]:
    return normalize_effect_steps_to_ops(
        get_card_effect_steps(config, card_name=card_name, trigger=trigger)
    )


def card_effect_has_op(
    config: Dict[str, Any] | None,
    *,
    card_name: str,
    trigger: str,
    op_id: str,
) -> bool:
    """Return whether a card trigger contains a normalized operation."""

    oid = str(op_id or "")
    if not oid:
        return False
    for step in get_card_effect_ops(config, card_name=card_name, trigger=trigger):
        if isinstance(step, dict) and str(step.get("op") or "") == oid:
            return True
    return False


def parse_select_option(steps: Sequence[Any]) -> Optional[int]:
    """Return 1/2/3 if any step requests option selection."""

    for step in steps:
        if not isinstance(step, dict) or "select_option" not in step:
            # Step3A op schema
            if not isinstance(step, dict) or str(step.get("op") or "") != "select_option":
                continue
            v = step.get("index")
        else:
            v = step.get("select_option")

        if v in (1, "1", "选项1", "Option1", "option1"):
            return 1
        if v in (2, "2", "选项2", "Option2", "option2"):
            return 2
        if v in (3, "3", "选项3", "Option3", "option3"):
            return 3
    return None


def parse_target_type(steps: Sequence[Any]) -> Optional[str]:
    for step in steps:
        if not isinstance(step, dict):
            continue
        if str(step.get("op") or "") == "legacy_target_type":
            v = step.get("target_type")
        else:
            v = step.get("target_type")
        if isinstance(v, str) and v:
            return v
    return None


def parse_action(steps: Sequence[Any]) -> Optional[str]:
    for step in steps:
        if not isinstance(step, dict):
            continue
        if str(step.get("op") or "") == "legacy_action":
            v = step.get("action")
        else:
            v = step.get("action")
        if isinstance(v, str) and v:
            return v
    return None


def has_any_effects_for_trigger(config: Dict[str, Any] | None, *, trigger: str) -> bool:
    if not isinstance(config, dict):
        return False
    effects = config.get("strategy", {}).get("effects", {})
    if not isinstance(effects, dict):
        return False
    trig = str(trigger or "")
    for _card_name, card_eff in effects.items():
        if not isinstance(card_eff, dict):
            continue
        steps = card_eff.get(trig)
        if isinstance(steps, list) and any(isinstance(s, dict) for s in steps):
            return True
    return False
