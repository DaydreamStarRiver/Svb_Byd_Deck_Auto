"""
增强版换牌策略模块（极简2规则系统）

相比原版的改进：
1. 支持具体卡牌识别（SIFT结果，包含name字段）
2. 集成卡牌优先级系统（high_priority_cards）
3. 配置驱动的费用限制（cost_limits）和低费目标（low_cost_target）
4. 换牌时从最高费开始
5. 同费选择时基于优先级
6. 极简2规则系统，消除规则冲突

重构理念：
- 规则1: 超费过滤 + 费用限制（如1费≤1，2费≤2）
- 规则2: 曲线平衡（只从重复卡中换，自动保护唯一卡）
- 删除了冗余的规则3-7（核心费用强制、曲线完整性等）
"""

from typing import List, Tuple, Dict, Optional
import logging

logger = logging.getLogger(__name__)


# ========== 策略配置系统 ==========

STRATEGY_CONFIGS = {
    "3费档次": {
        "max_cost": 3,
        "cost_limits": {1: 1, 2: 2},  # 1费最多1张，2费最多2张
        "low_cost_target": [2, 3],    # 低费(1+2费)目标范围2-3张
        "allowed_costs": {1, 2, 3},
        "description": "目标: 低费2-3张，以3费为主; 理想组合: [1,2,3] 或 [2,2,3]"
    },
    "4费档次": {
        "max_cost": 4,
        "cost_limits": {1: 1, 2: 2},
        "low_cost_target": [2, 3],
        "allowed_costs": {1, 2, 3, 4},
        "description": "目标: 低费2-3张，以4费为主; 理想组合: [1,2,4] 或 [2,2,4] 或 [2,3,4]"
    },
    "5费档次": {
        "max_cost": 5,
        "cost_limits": {1: 1, 2: 2},
        "low_cost_target": [2, 3],
        "allowed_costs": {1, 2, 3, 4, 5},
        "description": "目标: 低费2-3张，以5费为主; 理想组合: [2,3,5] 或 [2,4,5]"
    }
}


# ========== 辅助函数 ==========

def get_card_priority(card_name: str, priority_cards: Optional[Dict] = None) -> int:
    """
    获取卡牌优先级

    Args:
        card_name: 卡牌名称
        priority_cards: 优先级配置字典 {"卡牌名": {"priority": 数字}}

    Returns:
        int: 优先级数字（越小优先级越高，默认500）
    """
    if priority_cards and card_name in priority_cards:
        return priority_cards[card_name].get('priority', 500)
    return 500


def _build_card_index(hand_cards: List[Dict], priority_cards: Optional[Dict]) -> Dict:
    """
    构建按费用分组的卡牌索引结构

    Args:
        hand_cards: 手牌列表 [{'cost': 3, 'name': '...', ...}, ...]
        priority_cards: 优先级配置

    Returns:
        Dict: {费用: [{'index': 索引, 'card': 卡牌, 'priority': 优先级}, ...]}
    """
    cards_by_cost = {i: [] for i in range(11)}
    for idx, card in enumerate(hand_cards):
        cost = card['cost']
        priority = get_card_priority(card['name'], priority_cards)
        cards_by_cost[cost].append({
            'index': idx,
            'card': card,
            'priority': priority
        })
    return cards_by_cost


def _sort_swaps_by_cost(
    swap_indices: List[int],
    reasons: List[str],
    hand_cards: List[Dict]
) -> Tuple[List[int], List[str]]:
    """
    按费用从高到低排序换牌索引，并同步调整原因列表

    Args:
        swap_indices: 换牌索引列表
        reasons: 换牌原因列表
        hand_cards: 手牌列表

    Returns:
        Tuple[List[int], List[str]]: 排序后的索引和原因
    """
    swap_with_cost = [(idx, hand_cards[idx]['cost']) for idx in swap_indices]
    swap_with_cost.sort(key=lambda x: -x[1])  # 费用降序
    swap_indices_sorted = [idx for idx, _ in swap_with_cost]
    reasons_sorted = [reasons[swap_indices.index(idx)] for idx in swap_indices_sorted]
    return swap_indices_sorted, reasons_sorted


# ========== 极简2规则系统 ==========

def _apply_rule1_overcost_and_limits(
    cards_by_cost: Dict,
    max_cost: int,
    cost_limits: Dict[int, int],
    swap_indices: List[int],
    reasons: List[str]
) -> Tuple[List[int], List[str]]:
    """
    规则1: 超费过滤 + 费用限制

    步骤：
    1. 换掉所有 > max_cost 的卡牌
    2. 执行费用限制（如1费≤1张，2费≤2张）

    Args:
        cards_by_cost: 按费用分组的卡牌
        max_cost: 档次最大费用（3/4/5）
        cost_limits: 费用上限配置 {1: 1, 2: 2}
        swap_indices: 当前换牌索引列表
        reasons: 当前换牌原因列表

    Returns:
        Tuple[List[int], List[str]]: 更新后的换牌索引和原因
    """
    # 步骤1: 换掉超费卡（按优先级从低到高换）
    for cost in range(10, max_cost, -1):  # 10,9,8...max_cost+1
        for item in sorted(cards_by_cost[cost], key=lambda x: -x['priority']):
            swap_indices.append(item['index'])
            reasons.append(f"超过{max_cost}费档次({cost}费)")
            logger.info(f"规则1.1: 换掉 {item['card']['name']} - 超过{max_cost}费档次")

    # 步骤2: 执行费用限制
    for cost, limit in cost_limits.items():
        cards_of_cost = [c for c in cards_by_cost[cost] if c['index'] not in swap_indices]

        if len(cards_of_cost) > limit:
            # 超限，换掉优先级低的（保留优先级高的）
            excess = len(cards_of_cost) - limit
            sorted_cards = sorted(cards_of_cost, key=lambda x: x['priority'])  # 升序

            for item in sorted_cards[-excess:]:  # 取优先级最低的（priority最大）
                swap_indices.append(item['index'])
                reasons.append(f"{cost}费超限(最多{limit}张)")
                logger.info(f"规则1.2: 换掉 {item['card']['name']} - {cost}费超限(最多{limit}张)")

    return swap_indices, reasons


def _apply_rule2_curve_balance(
    cards_by_cost: Dict,
    low_cost_target: List[int],
    allowed_costs: set,
    swap_indices: List[int],
    reasons: List[str]
) -> Tuple[List[int], List[str]]:
    """
    规则2: 曲线平衡（只从重复卡中换）

    步骤：
    1. 计算低费(1+2费)数量
    2. 如果低费不足：从档次内有多张的费用中换（保护唯一卡）
    3. 如果低费过多：换掉优先级低的低费

    关键：只从【有多张】的费用中换，自动保护唯一卡

    Args:
        cards_by_cost: 按费用分组的卡牌
        low_cost_target: 低费目标范围 [min, max]（如[2, 3]）
        allowed_costs: 档次允许的费用集合
        swap_indices: 当前换牌索引列表
        reasons: 当前换牌原因列表

    Returns:
        Tuple[List[int], List[str]]: 更新后的换牌索引和原因
    """
    # 计算剩余卡牌中的低费数量
    remaining_1cost = [c for c in cards_by_cost[1] if c['index'] not in swap_indices]
    remaining_2cost = [c for c in cards_by_cost[2] if c['index'] not in swap_indices]
    low_cost_count = len(remaining_1cost) + len(remaining_2cost)

    min_low, max_low = low_cost_target

    # 情况A: 低费不足
    if low_cost_count < min_low:
        logger.info(f"规则2.1: 低费不足({low_cost_count}张 < {min_low}张)，从档次内重复卡中换")
        swaps_needed = min_low - low_cost_count
        swaps_made = 0

        # 从档次内费用中找有多张的，按费用从高到低
        for cost in sorted(allowed_costs, reverse=True):
            if swaps_made >= swaps_needed:
                break

            available = [c for c in cards_by_cost[cost] if c['index'] not in swap_indices]

            # 关键：只有该费用有多张时，才换掉优先级低的（保护唯一卡）
            if len(available) > 1:
                # 保留至少1张，换掉优先级最低的
                sorted_cards = sorted(available, key=lambda x: x['priority'])
                num_to_swap = min(len(available) - 1, swaps_needed - swaps_made)

                for item in sorted_cards[-num_to_swap:]:  # 取优先级最低的
                    swap_indices.append(item['index'])
                    reasons.append(f"低费不足，换重复{cost}费(优先级{item['priority']})")
                    logger.info(f"  换掉 {item['card']['name']} ({cost}费, 优先级{item['priority']})")
                    swaps_made += 1

    # 情况B: 低费过多
    elif low_cost_count > max_low:
        logger.info(f"规则2.2: 低费过多({low_cost_count}张 > {max_low}张)，换掉优先级低的低费")
        excess = low_cost_count - max_low
        low_cost_cards = remaining_1cost + remaining_2cost

        # 按优先级排序（升序），换掉优先级最低的
        sorted_low = sorted(low_cost_cards, key=lambda x: x['priority'])

        for item in sorted_low[-excess:]:  # 取优先级最低的
            swap_indices.append(item['index'])
            reasons.append(f"低费过多，换{item['card']['cost']}费(优先级{item['priority']})")
            logger.info(f"  换掉 {item['card']['name']} ({item['card']['cost']}费, 优先级{item['priority']})")

    else:
        # 低费数量刚好，无需调整
        logger.info(f"规则2: 低费数量({low_cost_count}张)在目标范围{low_cost_target}内，无需调整")

    return swap_indices, reasons


# ========== 统一执行引擎 ==========

def _execute_strategy_rules(
    hand_cards: List[Dict],
    config: Dict,
    priority_cards: Optional[Dict]
) -> Tuple[List[int], List[int], List[str]]:
    """
    配置驱动的规则执行引擎（极简2规则）

    Args:
        hand_cards: 手牌列表
        config: 策略配置字典（从STRATEGY_CONFIGS获取）
        priority_cards: 优先级配置

    Returns:
        Tuple[List[int], List[int], List[str]]: (保留索引, 换牌索引, 换牌原因)
    """
    # 构建索引结构
    cards_by_cost = _build_card_index(hand_cards, priority_cards)

    swap_indices = []
    reasons = []

    # 规则1: 超费过滤 + 费用限制
    swap_indices, reasons = _apply_rule1_overcost_and_limits(
        cards_by_cost,
        config["max_cost"],
        config["cost_limits"],
        swap_indices,
        reasons
    )

    # 规则2: 曲线平衡（只从重复卡中换）
    swap_indices, reasons = _apply_rule2_curve_balance(
        cards_by_cost,
        config["low_cost_target"],
        config["allowed_costs"],
        swap_indices,
        reasons
    )

    # 计算保留索引
    keep_indices = [i for i in range(len(hand_cards)) if i not in swap_indices]

    # 按费用排序（从高到低）
    swap_indices_sorted, reasons_sorted = _sort_swaps_by_cost(
        swap_indices, reasons, hand_cards
    )

    logger.info(f"决策结果: 保留 {keep_indices}, 换掉 {swap_indices_sorted}")

    return keep_indices, swap_indices_sorted, reasons_sorted


# ========== 公共接口 ==========

def determine_card_swaps_enhanced(
    hand_cards: List[Dict],
    strategy: str,
    priority_cards: Optional[Dict] = None
) -> Tuple[List[int], List[int], List[str]]:
    """
    增强版换牌策略决策（极简2规则系统）

    Args:
        hand_cards: SIFT识别结果列表
            [
                {'center': (x, y), 'cost': 3, 'name': '精灵公主艾莉娅', ...},
                ...
            ]
        strategy: 策略名称 ("3费档次"/"4费档次"/"5费档次")
        priority_cards: 优先级配置（可选）

    Returns:
        Tuple[List[int], List[int], List[str]]:
            - keep_indices: 保留的卡索引
            - swap_indices: 换掉的卡索引（按费用从高到低排序）
            - reasons: 每张换掉的卡的原因
    """
    # 确保手牌不超过4张
    hand_cards = hand_cards[:4]
    num_cards = len(hand_cards)

    logger.info(f"手牌数量: {num_cards}")
    logger.info(f"策略: {strategy}")
    for i, card in enumerate(hand_cards):
        priority = get_card_priority(card['name'], priority_cards)
        logger.info(f"  {i+1}. {card['name']} ({card['cost']}费, 优先级:{priority})")

    # 验证策略并获取配置
    if strategy not in STRATEGY_CONFIGS:
        logger.warning(f"未知策略: {strategy}，使用默认4费档次")
        strategy = "4费档次"

    config = STRATEGY_CONFIGS[strategy]
    logger.debug(f"策略描述: {config['description']}")

    # 执行策略
    return _execute_strategy_rules(hand_cards, config, priority_cards)


def determine_card_swaps_unified(
    hand_data,
    strategy: str,
    priority_cards: Optional[Dict] = None,
    use_enhanced: bool = True
) -> Tuple[List[int], List[int], List[str]]:
    """
    统一换牌策略决策接口

    支持新旧两种输入格式和策略规则，通过参数灵活切换。

    Args:
        hand_data:
            - 旧格式：List[int] 如 [1, 3, 5, 7]（仅费用）
            - 新格式：List[Dict] 如 [{'name': '卡名', 'cost': 3, 'center': (x,y), ...}]
        strategy: 换牌策略名称
            - "3费档次"：1-3费曲线
            - "4费档次"：1-4费曲线
            - "5费档次"：2-5费曲线
        priority_cards: 高优先级卡牌配置（可选）
            格式：{'卡牌名': 优先级数字}，数字越小优先级越高
            仅在 use_enhanced=True 时生效
        use_enhanced: 是否使用增强策略规则
            - True: 使用增强规则（2规则系统，支持优先级、费用限制等）
            - False: 使用旧规则（简单档次判断，仅按费用阈值）

    Returns:
        Tuple[List[int], List[int], List[str]]:
            - keep_indices: 保留的卡牌索引列表
            - swap_indices: 换掉的卡牌索引列表（按费用降序排列）
            - reasons: 每张换牌的原因列表

    Examples:
        >>> # 使用旧格式输入 + 增强策略
        >>> keep, swap, reasons = determine_card_swaps_unified(
        ...     hand_data=[1, 3, 5, 7],
        ...     strategy="4费档次",
        ...     priority_cards={'精灵公主': 1},
        ...     use_enhanced=True
        ... )

        >>> # 使用新格式输入 + 旧策略
        >>> cards = [{'name': '妖精', 'cost': 1, 'center': (100, 200)}]
        >>> keep, swap, reasons = determine_card_swaps_unified(
        ...     hand_data=cards,
        ...     strategy="4费档次",
        ...     use_enhanced=False
        ... )
    """
    # 1. 自动检测并转换输入格式
    if not hand_data:
        logger.warning("手牌数据为空")
        return [], [], []

    # 检查第一个元素类型判断输入格式
    if isinstance(hand_data[0], int):
        # 旧格式：仅费用列表 -> 转换为新格式
        hand_cards = [
            {
                'cost': cost,
                'name': f'未知{cost}费卡',
                'center': (0, 0),
                'confidence': 1.0,
                'template_name': f'{cost}_unknown'
            }
            for cost in hand_data
        ]
        logger.debug(f"检测到旧格式输入（费用列表），已转换为新格式")
    else:
        # 新格式：完整卡牌信息
        hand_cards = hand_data

    # 2. 根据 use_enhanced 参数分发到对应策略
    if use_enhanced:
        # 使用增强策略（2规则系统，支持优先级等）
        logger.debug(f"使用增强换牌策略: {strategy}")
        return determine_card_swaps_enhanced(hand_cards, strategy, priority_cards)
    else:
        # 使用旧策略（简单档次判断）
        logger.debug(f"使用旧换牌策略: {strategy}")
        from .card_swap_strategy import determine_card_swaps_legacy
        return determine_card_swaps_legacy(hand_cards, strategy)
