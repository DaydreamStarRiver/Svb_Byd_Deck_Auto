# 特殊效果机制开发手册

本手册面向开发者，说明 Step3A 的分层、数据结构与扩展点（新增 trigger/op/target，以及如何在新接口中接入）。

## 1. 总览

Step3A 的目标：

- 把“特殊交互”从散落的 if/elif 中抽离成 `strategy.effects` 配置
- UI 通过注册表自动渲染配置表单
- 运行期用统一的 `EffectEngine` 执行操作

关键模块：

- 注册表（UI 读取，必须轻量）：`src/config/effects_registry.py`
- schema helpers（轻量）：`src/config/strategy_effects.py`
- 迁移：`src/config/migrations.py`
- 运行期引擎：`src/game/effects/*`
- 接入点：
  - on_play：`src/game/card_play_special_actions.py`
  - on_evolve/on_super_evolve：`src/game/evolution_special_actions.py`
  - on_attack：`src/game/game_actions.py` + `src/game/battle/phases/attack.py`
- 二级编辑器（UI）：`src/ui/pages/card_effects_editor.py`

## 2. 数据结构

### 2.1 strategy.effects

```json
{
  "strategy": {
    "effects": {
      "<card_key>": {
        "on_play": [<OperationSpec>, ...],
        "on_evolve": [<OperationSpec>, ...]
      }
    }
  }
}
```

### 2.2 card_key 规则

- `on_play`：可使用爆能 key：`卡名@6`（手牌识别会生成 config_key）。
- `on_evolve/on_super_evolve/on_attack`：按随从基础名（不带 `@`）。

### 2.3 OperationSpec

最小形式：

```json
{"op": "select_option", "index": 1}
```

可选增强字段（引擎支持，UI 暂未暴露）：

- `on_error`：`skip_step | cancel_action | abort_trigger`

## 3. 注册表（effects_registry.py）

注册表是“UI -> 可配置项”的来源，必须保持轻量：禁止导入 cv/u2/game。

包含：

- `TRIGGERS`：`id/label/short/context_kind`
- `OPERATIONS`：`op_id/label/supported_context_kinds/params_schema`
- `TARGET_KINDS`：用于 `target_spec` 参数的 UI 构建

参数类型（当前 UI 支持）：

- `bool/int/float/str/enum/target_spec`

如果你新增了新的参数类型，需要同步扩展 `src/ui/pages/card_effects_editor.py`。

## 4. 运行期引擎（src/game/effects）

### 4.1 EffectEngine

文件：`src/game/effects/engine.py`

- `EffectEngine.run_ops(ops, ctx, trigger_id)`：顺序执行 OperationSpec。
- 每步失败默认跳过（或按 `on_error` 控制）。

### 4.2 OperationExecutor

文件：`src/game/effects/operations.py`

负责实现具体动作：

- `select_option`
- `select_targets`
- `cancel_action`
- `disallow_empty_evolve`（运行时 no-op；由进化决策读取）
- `legacy_action`（兼容 action 字符串）

### 4.3 TargetResolver

文件：`src/game/effects/target_resolver.py`

把 `TargetSpec` 转成点击坐标：

- enemy_leader / enemy_follower / friendly_follower

说明：曾存在 `TargetSpec.kind=option`（用于用 select_targets 点选项），现已废弃并由 migration 自动转换为 `select_option`。

其中 enemy/friendly follower 的筛选逻辑复用 `src/game/policy/targets.py` 的 `TargetSelector`。

## 5. 接入点（hooks）

### 5.1 on_play

文件：`src/game/card_play_special_actions.py`

当前策略：

- 从 `strategy.effects[config_key].on_play` 读取 steps
- 用 `normalize_effect_steps_to_ops()` 将旧 step 结构归一化为 op
- 若只有 `legacy_target_type` 且没有新引擎 op（select_option/select_targets/cancel_action），则走旧 dispatcher（它可能包含“不出牌/不消耗 PP”的语义）
- 否则：先按原逻辑拖拽出牌，再执行 op 引擎（忽略 legacy_target_type）

这意味着：

- 新引擎的 on_play 是“post-play”，不支持 pre-play 的复杂语义。

### 5.2 on_evolve/on_super_evolve

文件：`src/game/evolution_special_actions.py`

- 读取并归一化 op
- 为避免旧卡牌顺序问题，会把 `select_option` 移到最后执行
- 运行完 op 后，如果没有配置 `select_option`，才走旧的 `handle_evolve_mode_option`（读取 `card_evolve_mode_options/card_mode_options`）
- `disallow_empty_evolve` 是随从触发专用标记：`LegacyBattlePolicy.should_evolve()` 在无敌方随从、仅靠疾驰/优先进化随从判断是否进化时，会按当前可用的进化/超进化点检查对应触发；含该 op 的触发不计入空场进化理由。`GameActions.perform_evolution_actions()` 在空场时也会跳过对应触发；引擎遇到该 op 时返回成功但不执行动作。

### 5.3 on_attack

文件：

- hook：`src/game/game_actions.py`（每次攻击后调用）
- 扫描优化：`src/game/battle/phases/attack.py`

为了避免 SIFT 命名的性能开销：

- 只有当配置里存在任意 `on_attack` effects 时，AttackPhase 才会用 `with_names=True` 做扫描。

## 6. 配置迁移

文件：`src/config/migrations.py`

- `migrate_strategy_effects_schema`：确保 `strategy.effects` 存在，并从 legacy 字段“补齐缺失”的 select_option（不会覆盖已有 effects）。
- `migrate_strategy_effects_to_ops`：把旧 step dict（select_option/target_type/action）升级为 Step3A op schema。

调用点：

- `src/config/config_manager.py`
- `src/config/config_repository.py`

## 7. 如何新增一个 Operation

1. 在 `src/config/effects_registry.py` 的 `OPERATIONS` 里新增一项：
   - `op_id`（唯一）
   - `supported_context_kinds`（hand_card / follower）
   - `params_schema`（让 UI 自动生成表单）
2. 在运行期实现：
   - 推荐在 `src/game/effects/operations.py` 增加 `OperationExecutor.<op>()`
   - 并在 `src/game/effects/engine.py::_execute_one()` 中路由
3. 如果 op 需要新的参数控件类型：
   - 扩展 `src/ui/pages/card_effects_editor.py`：`_build_param_widget/_get_param_widget_value/_set_param_widget_value`
4. 如果 op 要做 CV/扫描：
   - 放在 `src/game/effects/*`（不要放到 config/UI 层）

## 8. 如何新增一个 TargetSpec kind/selector

1. 在 `src/config/effects_registry.py` 的 `TARGET_KINDS` 增加 kind/selector 描述（含 params_schema）。
2. 在 `src/game/effects/target_resolver.py::resolve_targets()` 实现解析和返回坐标。
3. 若需要新增筛选策略：
   - 优先在 `src/game/policy/targets.py` 的 `TargetSelector` 中新增纯逻辑函数，resolver 只负责“拿数据 + 调用 selector”。

## 9. 如何新增一个 Trigger 并在新接口中接入

当你新增一个“新的交互时机/新接口”时，按以下步骤：

1. `effects_registry.TRIGGERS` 新增 trigger：
   - 明确 `context_kind`（hand_card 或 follower）
2. 在运行期选择一个稳定的 hook 点：
   - 例如某个 phase 结束、某个动画后、某个按钮点击后
3. 构造 context：
   - hand_card：用 `HandCardContext`
   - follower：用 `FollowerContext`
   - 若不够用可以新增 dataclass，但注意不要引入重依赖到 config/UI
4. 读取并执行：

```python
from src.config.strategy_effects import get_card_effect_steps, normalize_effect_steps_to_ops
from src.game.effects import EffectEngine

steps = get_card_effect_steps(ds.config, card_name=key, trigger="<trigger_id>")
ops = normalize_effect_steps_to_ops(steps)
EffectEngine.run_ops(ops, ctx=ctx, trigger_id="<trigger_id>")
```

5. 性能注意：
   - 如果 trigger 需要随从名（SIFT），尽量像 on_attack 一样做“按需启用”。

## 10. 运行与验证

- 语法验证：`python -m compileall Svb_Byd_Deck_Auto`
- UI 侧验证：打开“特殊效果...”弹窗，检查新增 op/target 的表单是否能正确渲染、保存并写入 `strategy.effects`。
