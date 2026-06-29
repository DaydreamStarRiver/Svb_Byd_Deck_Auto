# 特殊效果机制用户手册

本手册面向普通使用者/配置作者，说明如何在 UI 中配置 `strategy.effects`，以及每个选项的含义。

## 1. 机制概览

Step3A 将“卡牌/随从的额外交互”统一为：

- Trigger（触发时机）：例如 `出牌时(on_play)`、`进化时(on_evolve)`
- Step（步骤列表）：一个 Trigger 下可以配置多步，按顺序执行
- Operation（操作）：每一步的具体动作，例如“选择选项”“选择目标”等

配置存储在 `config.json` 的 `strategy.effects`。

## 2. 从 UI 进入编辑器

1. 打开“卡牌设置”页面。
2. 在某张卡牌右侧点击“`特殊效果...`”。
3. 在弹窗中勾选需要启用的触发时机（出牌/攻击/进化/超进化），并为每个触发时机配置步骤。
4. 点击“保存”。

提示：

- 爆能档位行（例如 `卡名(爆能6)`）只支持配置 `出牌时(on_play)`。
- `进化/超进化/攻击` 属于“随从触发”，按基础随从名配置（不带 `@`）。

## 3. Trigger（触发时机）说明

- `出牌时 (on_play)`：打出手牌后出现的交互，例如二选一、选目标。
- `攻击时 (on_attack)`：我方随从完成一次攻击后出现的交互（较少见）。
- `进化时 (on_evolve)`：普通进化动画完成后出现的交互。
- `超进化时 (on_super_evolve)`：超进化动画完成后出现的交互。

## 4. Operation（操作）说明

### 4.1 选择选项（select_option）

用途：处理“二选一”类选项。

- `index`：选择第几个选项。
  - `1`：选项1（当前坐标硬编码为 `(748, 328)`）
  - `2`：选项2（当前坐标硬编码为 `(724, 429)`）

注意：

- 目前仅支持 `1/2` 两个选项。
- 坐标仍是 hard code，只是集中在一个 op 内统一管理。
- 旧的 `select_targets` + `target.kind=option` 已移除；启动时会自动迁移为 `select_option`。

### 4.2 选择目标（select_targets）

用途：统一的“点目标”操作（点敌方随从/点敌方玩家/点我方随从等）。

参数：

- `target`：目标描述（TargetSpec），由“目标(kind)”+“选择器(selector)”+“参数(params)”组成。
- `count`：需要点击几个目标（>=1）。
- `distinct_xy`（避免重复）：当 `count>1` 时，尽量避免点击同一个目标两次。
- `is_select_ui`（选择界面扫描）：是否处于“选择目标弹窗/高亮可选目标”的界面。
  - 勾选：使用更适合“选目标界面”的扫描区域（HP 通常上移）。
  - 不勾选：使用常规战场扫描区域。

如何理解“避免重复”和“选择界面扫描”：

- 避免重复：多目标选择时防止识别抖动导致重复点同一目标。
- 选择界面扫描：当你确实已经把牌拖出并进入“选目标界面”时，一般需要勾选；如果你不在该界面，勾选可能扫不到人。

### 4.3 取消/点空白（cancel_action）

用途：点空白位置关闭面板/取消。

常见用法：

- 某些卡牌交互失败后，补一条 `cancel_action` 让 UI 恢复到可操作状态。

### 4.4 不允许空场进化（disallow_empty_evolve）

用途：仅用于随从的 `进化时(on_evolve)` / `超进化时(on_super_evolve)`。当场上没有敌方随从时，配置了该 op 的对应触发不会作为“空场进化”的理由，实际选择进化随从时也会跳过该触发；若敌方有随从，仍可正常进化。

该 op 运行时不执行点击动作，可与其他进化后交互步骤放在同一个触发中。

### 4.5 旧兼容：特殊目标（legacy_target_type）

用途：兼容旧版本的 `target_type` 处理逻辑（包含一些“是否要出牌/是否消耗费用”的特殊语义）。

可选值与含义（与旧逻辑一致）：

- `enemy_player`：划出卡牌后点敌方玩家（打脸）。
- `double_enemy`：划出卡牌后点 2 个敌方随从（按血量高优先）。
- `shield_or_highest_hp`：优先点护盾随从，否则点敌方血量最高随从。
- `enemy_followers_hp_less_than_6`：优先点“HP<=5 且其中 HP 最大”的敌方随从；否则点敌方血量最高随从。
- `scan_our_follower_to_choose`：扫描我方随从数量并选择不同选项（特例）。
- `shield_or_highest_hp_no_enemy_retrun_point`：若无护盾且无敌方随从则“不出牌/不消耗 PP”（特例）。

重要限制：

- 新 op 引擎的 `on_play` 是“先出牌拖拽，再执行 op”，因此无法实现“不出牌/不消耗 PP”。
- 如果你需要“无目标则不出牌”的语义，请使用 `legacy_target_type`（并且不要与 `select_option/select_targets` 混用）。

### 4.6 旧兼容：进化特殊动作（legacy_action）

用途：兼容旧版本的 `action` 字符串。

当前支持：

- `attack_enemy_follower_hp_less_than_4`：点 1 个敌方随从（HP<=3 且其中 HP 最大）。
- `attack_two_enemy_followers_hp_less_than_4`：点 2 个敌方随从（HP<=3）。
- `attack_two_enemy_followers_hp_highest`：点 1 个敌方随从（血量最高；保持旧实现行为）。
- `our_followers_with_evolution`：点 1 个我方随从（按“进化优先级”选择，排除自身）。

提示：如果你已经用 `select_targets` 明确描述了目标，建议不要再同时配置 `legacy_action`。

## 5. TargetSpec（目标描述）说明

### 5.1 敌方玩家（enemy_leader）

点击敌方玩家的默认坐标（相当于打脸）。

### 5.2 敌方随从（enemy_follower）

可用选择器：

- `highest_hp`：血量最高。
- `hp_leq`：HP<=X（在满足条件的随从中取 HP 最大）。参数：
  - `max_hp`：最大 HP。
- `ward_or_highest_hp`：优先护盾随从，否则血量最高。

### 5.3 我方随从（friendly_follower）

可用选择器：

- `by_evolve_priority`：按“进化优先级”选择。参数：
  - `exclude_self`：是否排除自身（通常勾选）。

## 6. 常见配置示例

### 示例 A：某张手牌永远选项 2

Trigger：`出牌时(on_play)`

Step：

```json
{"op": "select_option", "index": 2}
```

### 示例 B：某张解牌优先点护盾，否则点血量最高

Trigger：`出牌时(on_play)`

Step：

```json
{
  "op": "select_targets",
  "target": {"kind": "enemy_follower", "selector": "ward_or_highest_hp", "params": {}},
  "count": 1,
  "distinct_xy": true,
  "is_select_ui": true
}
```

### 示例 C：进化后点 HP<=3 的敌随从，再选项 1

Trigger：`进化时(on_evolve)`

Steps：

```json
[
  {
    "op": "select_targets",
    "target": {"kind": "enemy_follower", "selector": "hp_leq", "params": {"max_hp": 3}},
    "count": 1,
    "distinct_xy": true,
    "is_select_ui": true
  },
  {"op": "select_option", "index": 1}
]
```

说明：对进化/超进化触发，运行期会优先执行“选目标”，再执行“选项”。

## 7. 排查问题

- 日志：运行日志会出现 `[Effect] ...` 前缀，包含触发时机和每一步执行情况。
- 选不到目标：
  - 确认是不是进入了选目标界面（一般需要勾选 `选择界面扫描`）。
  - 确认敌方/我方随从是否确实存在。
- “无目标不出牌”：请用 `legacy_target_type` 的 `shield_or_highest_hp_no_enemy_retrun_point` 这类旧兼容逻辑（新引擎目前无法做到）。
