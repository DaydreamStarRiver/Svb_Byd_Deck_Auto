"""Runtime effect contexts.

Keep these structures lightweight (pure data). The heavy logic stays in the
executor/engine modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class HandCardContext:
    context_kind: str = "hand_card"
    device_state: Any = None

    # Identity
    card_name: str = ""
    cfg_key: str = ""

    # Play geometry (used by caller; engine doesn't drag by default)
    card_center: Tuple[int, int] = (0, 0)
    play_target: Tuple[int, int] = (0, 0)
    follower_pos: Optional[Tuple[int, int]] = None
    follower_uid: Optional[int] = None

    # Full recognized card payload (optional)
    card: Dict[str, Any] = field(default_factory=dict)

    # Runtime diagnostics for select_targets failures (used by caller policy)
    select_targets_fail_kinds: List[str] = field(default_factory=list)
    select_targets_success_kinds: List[str] = field(default_factory=list)

    # Optional pre-action board snapshot (before play/evolve UI may cover board)
    pre_action_our_followers: Optional[Sequence[Any]] = None
    pre_action_our_follower_count: Optional[int] = None


@dataclass
class FollowerContext:
    context_kind: str = "follower"
    device_state: Any = None

    follower_name: str = ""
    cfg_key: str = ""
    follower_pos: Optional[Tuple[int, int]] = None
    follower_uid: Optional[int] = None
    is_super_evolution: bool = False

    # Optional: reuse already scanned followers to avoid extra CV work
    existing_followers: Optional[Sequence[Any]] = None

    # Optional pre-action board snapshot (before play/evolve UI may cover board)
    pre_action_our_followers: Optional[Sequence[Any]] = None
    pre_action_our_follower_count: Optional[int] = None

    # For on_attack
    attack_source_pos: Optional[Tuple[int, int]] = None

    # Runtime diagnostics for select_targets failures (used by caller policy)
    select_targets_fail_kinds: List[str] = field(default_factory=list)
    select_targets_success_kinds: List[str] = field(default_factory=list)
