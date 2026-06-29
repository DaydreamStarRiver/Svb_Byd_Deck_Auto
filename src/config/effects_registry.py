"""Effects registries (Trigger/Operation metadata) for Step3A.

This module must stay lightweight because UI imports it.
Do NOT import cv/u2/game modules here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


CONTEXT_HAND_CARD = "hand_card"
CONTEXT_FOLLOWER = "follower"


TRIGGERS: List[Dict[str, Any]] = [
    {
        "id": "on_play",
        "label": "出牌时",
        "short": "play",
        "context_kind": CONTEXT_HAND_CARD,
    },
    {
        "id": "on_attack",
        "label": "攻击时",
        "short": "atk",
        "context_kind": CONTEXT_FOLLOWER,
    },
    {
        "id": "on_evolve",
        "label": "进化时",
        "short": "evo",
        "context_kind": CONTEXT_FOLLOWER,
    },
    {
        "id": "on_super_evolve",
        "label": "超进化时",
        "short": "sevo",
        "context_kind": CONTEXT_FOLLOWER,
    },
]


TARGET_KINDS: List[Dict[str, Any]] = [
    {
        "kind": "enemy_leader",
        "label": "敌方玩家",
        "selectors": [
            {"id": "", "label": "敌方玩家", "params_schema": []},
        ],
    },
    {
        "kind": "enemy_follower",
        "label": "敌方随从",
        "selectors": [
            {"id": "highest_hp", "label": "血量最高", "params_schema": []},
            {
                "id": "hp_leq",
                "label": "HP<=X(取最大)",
                "params_schema": [
                    {
                        "name": "max_hp",
                        "label": "最大HP",
                        "type": "int",
                        "default": 3,
                        "min": 0,
                        "max": 99,
                    }
                ],
            },
            {
                "id": "hp_leq_or_highest_hp",
                "label": "HP<=X否则最高",
                "params_schema": [
                    {
                        "name": "max_hp",
                        "label": "最大HP",
                        "type": "int",
                        "default": 5,
                        "min": 0,
                        "max": 99,
                    },
                    {
                        "name": "allow_amulet_fallback",
                        "label": "无随从时允许护符",
                        "type": "bool",
                        "default": False,
                    },
                    {
                        "name": "fallback_to_enemy_leader",
                        "label": "无随从时改为打脸",
                        "type": "bool",
                        "default": False,
                    },
                ],
            },
            {
                "id": "ward_or_highest_hp",
                "label": "护盾优先/血量最高",
                "params_schema": [
                    {
                        "name": "allow_amulet_fallback",
                        "label": "无随从时允许护符",
                        "type": "bool",
                        "default": True,
                    }
                ],
            },
        ],
    },
    {
        "kind": "friendly_follower",
        "label": "我方随从",
        "selectors": [
            {
                "id": "by_evolve_priority",
                "label": "按进化优先级",
                "params_schema": [
                    {
                        "name": "exclude_self",
                        "label": "排除自身",
                        "type": "bool",
                        "default": True,
                    }
                ],
            }
        ],
    },
]


OPERATIONS: List[Dict[str, Any]] = [
    {
        "op_id": "select_option",
        "label": "选择选项",
        "supported_context_kinds": [CONTEXT_HAND_CARD, CONTEXT_FOLLOWER],
        "params_schema": [
            {
                "name": "index",
                "label": "选项",
                "type": "enum",
                "default": 1,
                "options": [
                    {"label": "选项1", "value": 1},
                    {"label": "选项2", "value": 2},
                ],
            }
        ],
    },
    {
        "op_id": "select_targets",
        "label": "选择目标",
        "supported_context_kinds": [CONTEXT_HAND_CARD, CONTEXT_FOLLOWER],
        "params_schema": [
            {
                "name": "target",
                "label": "目标",
                "type": "target_spec",
                "default": {"kind": "enemy_follower", "selector": "highest_hp", "params": {}},
            },
            {
                "name": "count",
                "label": "数量",
                "type": "int",
                "default": 1,
                "min": 1,
                "max": 5,
            },
            {
                "name": "distinct_xy",
                "label": "避免重复",
                "type": "bool",
                "default": True,
            },
            {
                "name": "is_select_ui",
                "label": "选择界面扫描",
                "type": "bool",
                "default": True,
            },
        ],
    },
    {
        "op_id": "select_option_by_our_followers",
        "label": "按我方随从数选项",
        "supported_context_kinds": [CONTEXT_HAND_CARD],
        "params_schema": [
            {
                "name": "threshold",
                "label": "阈值(<=)",
                "type": "int",
                "default": 3,
                "min": 0,
                "max": 10,
            },
            {
                "name": "le_option",
                "label": "<=阈值选项",
                "type": "enum",
                "default": 1,
                "options": [
                    {"label": "选项1", "value": 1},
                    {"label": "选项2", "value": 2},
                ],
            },
            {
                "name": "gt_option",
                "label": ">阈值选项",
                "type": "enum",
                "default": 2,
                "options": [
                    {"label": "选项1", "value": 1},
                    {"label": "选项2", "value": 2},
                ],
            },
        ],
    },
    {
        "op_id": "cancel_action",
        "label": "取消/点空白",
        "supported_context_kinds": [CONTEXT_HAND_CARD, CONTEXT_FOLLOWER],
        "params_schema": [],
    },
    {
        "op_id": "disallow_empty_evolve",
        "label": "不允许空场进化",
        "supported_context_kinds": [CONTEXT_FOLLOWER],
        "params_schema": [],
    },
    {
        "op_id": "add_cost_bonus",
        "label": "增加费用",
        "supported_context_kinds": [CONTEXT_HAND_CARD],
        "params_schema": [
            {
                "name": "amount",
                "label": "费用+",
                "type": "int",
                "default": 1,
                "min": -10,
                "max": 10,
                "compact": True,
            }
        ],
    },
    {
        "op_id": "buff",
        "label": "BUFF",
        "supported_context_kinds": [CONTEXT_HAND_CARD, CONTEXT_FOLLOWER],
        "params_schema": [
            {
                "name": "target",
                "label": "BUFF类型",
                "type": "enum",
                "default": "others",
                "options": [
                    {"label": "其他友方(+X/+Y)", "value": "others"},
                    {"label": "自身(+X/+Y)", "value": "self"},
                ],
            },
            {
                "name": "atk_delta",
                "label": "攻击+",
                "type": "int",
                "default": 1,
                "min": -20,
                "max": 20,
                "compact": True,
            },
            {
                "name": "hp_delta",
                "label": "生命+",
                "type": "int",
                "default": 1,
                "min": -20,
                "max": 20,
                "compact": True,
            },
        ],
    },
    {
        "op_id": "buff_attack_times",
        "label": "攻击次数BUFF",
        "supported_context_kinds": [CONTEXT_HAND_CARD, CONTEXT_FOLLOWER],
        "params_schema": [
            {
                "name": "target",
                "label": "BUFF类型",
                "type": "enum",
                "default": "others",
                "options": [
                    {"label": "其他友方(攻击次数)", "value": "others"},
                    {"label": "自身(攻击次数)", "value": "self"},
                ],
            },
            {
                "name": "attack_times",
                "label": "攻击次数",
                "type": "int",
                "default": 2,
                "min": 1,
                "max": 5,
                "compact": True,
            },
        ],
    },
]


def get_triggers() -> List[Dict[str, Any]]:
    return list(TRIGGERS)


def get_trigger(trigger_id: str) -> Optional[Dict[str, Any]]:
    tid = str(trigger_id or "")
    for t in TRIGGERS:
        if str(t.get("id")) == tid:
            return dict(t)
    return None


def get_operations(*, context_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    if not context_kind:
        return list(OPERATIONS)
    ck = str(context_kind)
    out: List[Dict[str, Any]] = []
    for op in OPERATIONS:
        kinds = op.get("supported_context_kinds")
        if isinstance(kinds, list) and ck in [str(x) for x in kinds]:
            out.append(op)
    return out


def get_operation(op_id: str) -> Optional[Dict[str, Any]]:
    oid = str(op_id or "")
    for op in OPERATIONS:
        if str(op.get("op_id")) == oid:
            return dict(op)
    return None


def get_target_kinds() -> List[Dict[str, Any]]:
    return list(TARGET_KINDS)


def get_target_kind(kind: str) -> Optional[Dict[str, Any]]:
    k = str(kind or "")
    for d in TARGET_KINDS:
        if str(d.get("kind")) == k:
            return dict(d)
    return None
