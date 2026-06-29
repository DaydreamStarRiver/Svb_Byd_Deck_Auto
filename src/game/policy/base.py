"""Policy interfaces.

For now we introduce a minimal battle policy hook so the existing logic can be
gradually migrated without changing outward behavior.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.config.card_priorities import is_evolve_priority_card
from src.config.strategy_effects import card_effect_has_op


class _BattleActionsLike(Protocol):
    device_state: Any
    follower_manager: Any

    def _scan_enemy_ATK(self, screenshot: Any) -> Any: ...


class BattlePolicy(Protocol):
    name: str

    def should_evolve(self, actions: _BattleActionsLike) -> bool: ...


class LegacyBattlePolicy:
    """Policy that preserves the current hardcoded evolve decision."""

    name = "legacy"

    @staticmethod
    def _allows_empty_evolve_for_active_trigger(ds: Any, follower_name: Any) -> bool:
        name = str(follower_name or "")
        if not name:
            return True
        config = getattr(ds, "config", None)

        if getattr(ds, "super_evolution_point", 0) > 0 and not card_effect_has_op(
            config,
            card_name=name,
            trigger="on_super_evolve",
            op_id="disallow_empty_evolve",
        ):
            return True

        if getattr(ds, "evolution_point", 0) > 0 and not card_effect_has_op(
            config,
            card_name=name,
            trigger="on_evolve",
            op_id="disallow_empty_evolve",
        ):
            return True

        return False

    def should_evolve(self, actions: _BattleActionsLike) -> bool:
        ds = actions.device_state

        # Must have points.
        if not (getattr(ds, "evolution_point", 0) > 0 or getattr(ds, "super_evolution_point", 0) > 0):
            return False

        # Condition 1: enemy has followers.
        cached_enemy_presence = getattr(actions, "_cached_enemy_presence_for_evolve", None)
        if cached_enemy_presence is not None:
            if bool(cached_enemy_presence):
                ds.logger.info("复用缓存检测到敌方随从，满足进化/超进化条件")
                return True
        else:
            screenshot = ds.take_screenshot()
            if screenshot:
                try:
                    enemy_followers = actions._scan_enemy_ATK(screenshot)
                except Exception:
                    enemy_followers = []
                if enemy_followers:
                    ds.logger.info("检测到敌方随从，满足进化/超进化条件")
                    return True

        # Condition 2: our green (storm) followers exist.
        try:
            manager = getattr(actions, "follower_manager", None)
            if manager is None or not hasattr(manager, "get_positions"):
                our_followers = []
            else:
                our_followers = manager.get_positions() or []
        except Exception:
            our_followers = []
        green_followers = [
            f
            for f in our_followers
            if len(f) > 2
            and f[2] == "green"
            and self._allows_empty_evolve_for_active_trigger(ds, f[3] if len(f) > 3 else None)
        ]
        if green_followers:
            ds.logger.info("检测到我方疾驰随从，满足进化/超进化条件")
            return True

        # Condition 3: any evolve-priority follower exists.
        for follower in our_followers:
            follower_name = follower[3] if len(follower) > 3 else None
            if follower_name and is_evolve_priority_card(
                follower_name, getattr(ds, "config", None)
            ) and self._allows_empty_evolve_for_active_trigger(
                ds, follower_name
            ):
                ds.logger.info(f"检测到优先进化随从[{follower_name}]，满足进化/超进化条件")
                return True

        return False
