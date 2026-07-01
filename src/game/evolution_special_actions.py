"""
进化/超进化特殊操作处理模块
处理进化/超进化后的特殊action（如铁拳神父等）
"""

from src.game.policy.effects import get_card_effect_steps

from src.config.strategy_effects import normalize_effect_steps_to_ops
from src.game.effects import EffectEngine, FollowerContext

class EvolutionSpecialActions:
    """进化/超进化特殊操作处理类"""
    
    def __init__(self, device_state):
        self.device_state = device_state
        self._force_post_evolve_hand_refresh = False
    
    def handle_evolve_special_action(
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
        self._force_post_evolve_hand_refresh = False
        trigger = "on_super_evolve" if is_super_evolution else "on_evolve"

        effect_key = str(follower_name or "")
        source_uid = None
        try:
            if follower_uid is not None:
                uid_i = int(follower_uid)
                if uid_i > 0:
                    source_uid = int(uid_i)
        except Exception:
            source_uid = None

        try:
            runtime = getattr(self.device_state, "battle_runtime_state", None)
            if runtime is not None and hasattr(runtime, "get_effect_key_for_ours"):
                key = runtime.get_effect_key_for_ours(
                    follower_pos=pos,
                    follower_uid=source_uid,
                    fallback_name=str(follower_name or ""),
                )
                if key:
                    effect_key = str(key)

            if (
                source_uid is None
                and runtime is not None
                and pos is not None
                and hasattr(runtime, "get_ours_uid")
            ):
                source_uid = runtime.get_ours_uid(
                    pos,
                    fallback_name=str(follower_name or ""),
                )
        except Exception:
            effect_key = str(follower_name or "")

        steps = get_card_effect_steps(
            getattr(self.device_state, "config", None), card_name=effect_key, trigger=trigger
        )

        ops = normalize_effect_steps_to_ops(steps)

        # Preserve legacy runtime semantics: evolve special clicks before select_option.
        ops = [
            o for o in ops if isinstance(o, dict) and str(o.get("op") or "") != "select_option"
        ] + [
            o for o in ops if isinstance(o, dict) and str(o.get("op") or "") == "select_option"
        ]

        pre_action_followers = list(existing_followers or []) if existing_followers else None
        pre_action_count = len(pre_action_followers) if pre_action_followers is not None else None
        if pre_action_followers is None and self._ops_require_pre_action_our_followers(ops):
            pre_action_followers, pre_action_count = self._scan_pre_action_our_followers()

        ctx = FollowerContext(
            device_state=self.device_state,
            follower_name=str(effect_key or follower_name or ""),
            cfg_key=str(effect_key or ""),
            follower_pos=(int(pos[0]), int(pos[1])) if isinstance(pos, (list, tuple)) and len(pos) >= 2 else None,
            follower_uid=int(source_uid) if source_uid is not None else None,
            is_super_evolution=bool(is_super_evolution),
            existing_followers=existing_followers,
            pre_action_our_followers=pre_action_followers,
            pre_action_our_follower_count=pre_action_count,
        )
        run_result = EffectEngine.run_ops(ops, ctx=ctx, trigger_id=trigger)

        # If a required enemy-follower target was not selected, the game may still
        # be waiting in target-select UI; cancel and let caller try another follower.
        fail_kinds = list(getattr(ctx, "select_targets_fail_kinds", []) or [])
        success_kinds = set(str(k) for k in list(getattr(ctx, "select_targets_success_kinds", []) or []))
        enemy_target_failed = any(
            str(k) == "enemy_follower" and "enemy_follower" not in success_kinds
            for k in fail_kinds
        )
        if enemy_target_failed:
            try:
                self.device_state.logger.info(
                    f"[{effect_key}] 进化敌方随从目标选择失败，取消当前进化并尝试其他随从"
                )
            except Exception:
                pass
            try:
                from src.game.effects.operations import OperationExecutor

                OperationExecutor.cancel_action(ctx)
            except Exception:
                pass
            return False

        if run_result.aborted:
            try:
                self.device_state.logger.warning(
                    f"[{effect_key}] {trigger} effects aborted，取消当前进化并尝试其他随从"
                )
            except Exception:
                pass
            try:
                from src.game.effects.operations import OperationExecutor

                OperationExecutor.cancel_action(ctx)
            except Exception:
                pass
            return False

        self._force_post_evolve_hand_refresh = bool(
            getattr(ctx, "force_post_play_hand_refresh", False)
        )
        return True

    @staticmethod
    def _ops_require_pre_action_our_followers(ops) -> bool:
        for step in list(ops or []):
            if isinstance(step, dict) and str(step.get("op") or "") == "select_option_by_our_followers":
                return True
        return False

    def _scan_pre_action_our_followers(self):
        try:
            game_manager = getattr(self.device_state, "game_manager", None)
            if game_manager is None:
                return None, None
            screenshot = self.device_state.take_screenshot()
            if screenshot is None:
                return None, None
            followers = game_manager.scan_our_followers(
                screenshot,
                extra_shots=0,
                with_names=True,
            )
            followers_list = list(followers or [])
            try:
                runtime = getattr(self.device_state, "battle_runtime_state", None)
                if runtime is not None and hasattr(runtime, "sync_ours"):
                    runtime.sync_ours(followers_list)
            except Exception:
                pass
            try:
                self.device_state.logger.info(f"[Effect] pre_action_our_followers count={len(followers_list)}")
            except Exception:
                pass
            return followers_list, len(followers_list)
        except Exception as e:
            try:
                self.device_state.logger.warning(f"[Effect] pre_action_our_followers scan failed: {e}")
            except Exception:
                pass
            return None, None
