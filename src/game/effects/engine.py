"""EffectEngine: execute Step3A operations at runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from src.config.effects_registry import get_operation

from .operations import OperationExecutor


@dataclass
class EffectRunResult:
    ok: bool
    aborted: bool = False
    warnings: List[str] = field(default_factory=list)


class EffectEngine:
    @staticmethod
    def run_ops(
        ops: Sequence[Dict[str, Any]],
        *,
        ctx: Any,
        trigger_id: str,
    ) -> EffectRunResult:
        ds = getattr(ctx, "device_state", None)
        warnings: List[str] = []
        aborted = False

        for step in list(ops or []):
            if not isinstance(step, dict):
                continue
            op_id = str(step.get("op") or "")
            if not op_id:
                continue

            op_def = get_operation(op_id)
            if not op_def:
                msg = f"unknown op: {op_id}"
                warnings.append(msg)
                try:
                    if ds is not None:
                        ds.logger.warning(f"[Effect] {trigger_id}: {msg}")
                except Exception:
                    pass
                continue

            supported = op_def.get("supported_context_kinds")
            ctx_kind = str(getattr(ctx, "context_kind", "") or "")
            if isinstance(supported, list) and ctx_kind and ctx_kind not in [str(x) for x in supported]:
                msg = f"op {op_id} not supported for ctx_kind={ctx_kind}"
                warnings.append(msg)
                try:
                    if ds is not None:
                        ds.logger.warning(f"[Effect] {trigger_id}: {msg}")
                except Exception:
                    pass
                continue

            on_error = str(step.get("on_error") or "skip_step")

            try:
                ok = EffectEngine._execute_one(op_id, step, ctx)
                if ok:
                    continue
                # Treat False as a failure (but not an exception).
                raise RuntimeError(f"op returned false: {op_id}")
            except Exception as e:
                msg = f"{op_id} failed: {e}"
                warnings.append(msg)
                try:
                    if ds is not None:
                        ds.logger.warning(f"[Effect] {trigger_id}: {msg}")
                except Exception:
                    pass

                if on_error == "abort_trigger":
                    aborted = True
                    break
                if on_error == "cancel_action":
                    try:
                        OperationExecutor.cancel_action(ctx)
                    except Exception:
                        pass
                    # Continue by default.
                    continue
                # default: skip_step
                continue

        ok = not aborted
        return EffectRunResult(ok=ok, aborted=aborted, warnings=warnings)

    @staticmethod
    def _execute_one(op_id: str, step: Dict[str, Any], ctx: Any) -> bool:
        if op_id == "select_option":
            return OperationExecutor.select_option(ctx, index=step.get("index", 1))
        if op_id == "select_option_by_our_followers":
            return OperationExecutor.select_option_by_our_followers(
                ctx,
                threshold=step.get("threshold", 3),
                le_option=step.get("le_option", 1),
                gt_option=step.get("gt_option", 2),
            )
        if op_id == "select_targets":
            return OperationExecutor.select_targets(
                ctx,
                target=step.get("target"),
                count=step.get("count", 1),
                distinct_xy=step.get("distinct_xy", True),
                is_select_ui=step.get("is_select_ui", True),
            )
        if op_id == "cancel_action":
            return OperationExecutor.cancel_action(ctx)
        if op_id == "disallow_empty_evolve":
            return True
        if op_id == "add_cost_bonus":
            return OperationExecutor.add_cost_bonus(
                ctx,
                amount=step.get("amount", 0),
            )
        if op_id == "buff":
            stat_ok = OperationExecutor.buff(
                ctx,
                target=step.get("target", "others"),
                atk_delta=step.get("atk_delta", 1),
                hp_delta=step.get("hp_delta", 1),
            )
            # Backward compatibility: legacy buff step may contain attack_times.
            if step.get("attack_times") is not None:
                return bool(
                    stat_ok
                    and OperationExecutor.buff_attack_times(
                        ctx,
                        target=step.get("target", "others"),
                        attack_times=step.get("attack_times", 1),
                    )
                )
            return bool(stat_ok)
        if op_id == "buff_attack_times":
            return OperationExecutor.buff_attack_times(
                ctx,
                target=step.get("target", "others"),
                attack_times=step.get("attack_times", 1),
            )

        return False
