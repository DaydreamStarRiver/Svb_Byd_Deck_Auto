"""
换牌策略模块
用于根据不同费用档次的最优组合，决定需要保留或更换的卡牌
"""

from typing import List, Tuple, Dict
import logging
import os
import random
import time

logger = logging.getLogger(__name__)


def determine_card_swaps_legacy(
    hand_cards: List[Dict],
    strategy: str
) -> Tuple[List[int], List[int], List[str]]:
    """
    旧版换牌策略（简单档次判断，无优先级支持）

    与旧版 determine_card_swaps 的区别：
    1. 接受新格式输入 List[Dict]（但只使用 cost 字段）
    2. 返回三元组 (keep_indices, swap_indices, reasons) 兼容新接口

    策略规则：
    - 简单基于费用阈值判断
    - 无卡牌优先级考虑
    - 无费用上限控制（1费/2费可以无限）
    - 无曲线完整性检查

    Args:
        hand_cards: 手牌列表，格式 [{'cost': 3, 'name': '卡名', ...}, ...]
        strategy: 换牌策略名称（"3费档次" | "4费档次" | "5费档次"）

    Returns:
        Tuple[List[int], List[int], List[str]]:
            - keep_indices: 保留的卡牌索引列表
            - swap_indices: 换掉的卡牌索引列表
            - reasons: 每张换牌的原因列表（兼容新接口）
    """
    # 提取费用列表
    hand_costs = [card['cost'] for card in hand_cards]

    # 确保手牌数量不超过4张
    hand_costs = hand_costs[:4]
    num_cards = len(hand_costs)

    logger.info(f"[old] 当前手牌费用: {hand_costs}")
    logger.info(f"[old] 使用策略: {strategy}")

    # 根据策略执行对应的换牌逻辑
    if strategy == '3费档次':
        swap_indices = _check_3_cost_strategy(hand_costs)
    elif strategy == '4费档次':
        swap_indices = _check_4_cost_strategy(hand_costs)
    elif strategy == '5费档次':
        swap_indices = _check_5_cost_strategy(hand_costs)
    else:
        # 默认使用4费档次策略
        logger.warning(f"[old] 未知策略: {strategy}，使用默认4费档次策略")
        swap_indices = _check_4_cost_strategy(hand_costs)

    # 计算保留索引
    keep_indices = [i for i in range(num_cards) if i not in swap_indices]

    # 生成原因列表（简单说明）
    reasons = [f"超过{strategy}档次" for _ in swap_indices]

    return keep_indices, swap_indices, reasons


def _check_3_cost_strategy(hand_costs):
    """
    检查3费档次策略
    要求：必须包含至少一张3费牌
    最优：前三张牌组合为 [1,2,3]
    次优：牌序为2，3
    目标：确保3费时能准时打出
    """
    # 统计各费用的数量
    cost_counts = {}
    for cost in hand_costs:
        cost_counts[cost] = cost_counts.get(cost, 0) + 1
    
    # 检查是否有3费牌
    has_3_cost = cost_counts.get(3, 0) >= 1
    
    # 检查是否有费用大于3的牌
    has_higher_cost = any(cost > 3 for cost in hand_costs)
    
    # 最优条件：包含1费、2费、3费牌各至少一张
    if has_3_cost and cost_counts.get(1, 0) >= 1 and cost_counts.get(2, 0) >= 1:
        logger.info("满足3费档次最优组合[1,2,3]相关卡牌")
        # 替换费用大于3的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 3]
    
    # 次优条件：包含2费和3费牌
    if has_3_cost and cost_counts.get(2, 0) >= 1:
        logger.info("满足3费档次次优组合[2,3]相关卡牌")
        # 替换费用大于3的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 3]
    
    # 基本条件：有3费牌
    if has_3_cost:
        logger.info("满足3费档次基本条件：有3费牌")
        # 替换费用大于3的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 3]
    
    # 如果没有3费牌，但有费用大于3的牌，应该换掉这些高费牌
    if not has_3_cost and has_higher_cost:
        logger.info("不满足3费档次条件（缺少3费牌），但存在高费牌，替换高费牌")
        return [i for i, cost in enumerate(hand_costs) if cost > 3]
    
    # 其他情况：没有3费牌且没有高费牌，不需要换牌
    logger.info("3费档次：没有3费牌且没有高费牌，无需换牌")
    return []


def _check_4_cost_strategy(hand_costs):
    """
    检查4费档次策略
    要求：必须包含至少一张4费牌
    最优：四张牌组合为 [1,2,3,4]
    次优：牌序为 [2,3,4] 或 [2,2,4]
    目标：确保4费时能有效展开
    """
    # 统计各费用的数量
    cost_counts = {}
    for cost in hand_costs:
        cost_counts[cost] = cost_counts.get(cost, 0) + 1
    
    # 检查是否有4费牌
    has_4_cost = cost_counts.get(4, 0) >= 1
    
    # 检查是否有费用大于4的牌
    has_higher_cost = any(cost > 4 for cost in hand_costs)
    
    # 如果没有4费牌，但有费用大于4的牌，应该换掉这些高费牌
    if not has_4_cost:
        if has_higher_cost:
            logger.info("4费档次策略：缺少4费牌，但存在高费牌，替换高费牌")
            return [i for i, cost in enumerate(hand_costs) if cost > 4]
        else:
            logger.info("4费档次策略：缺少4费牌且没有高费牌，无需换牌")
            return []
    
    # 最优条件：[1,2,3,4]组合
    if cost_counts.get(1, 0) >= 1 and cost_counts.get(2, 0) >= 1 and \
       cost_counts.get(3, 0) >= 1 and has_4_cost:
        logger.info("满足4费档次最优组合[1,2,3,4]相关卡牌")
        # 替换费用大于4的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 4]
    
    # 次优条件1：[2,3,4]组合
    if cost_counts.get(2, 0) >= 1 and cost_counts.get(3, 0) >= 1 and has_4_cost:
        logger.info("满足4费档次次优组合[2,3,4]相关卡牌")
        # 替换费用大于4的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 4]
    
    # 次优条件2：[2,2,4]组合
    if cost_counts.get(2, 0) >= 2 and has_4_cost:
        logger.info("满足4费档次次优组合[2,2,4]相关卡牌")
        # 替换费用大于4的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 4]
    
    # 基本条件：有4费牌和一些低费牌
    if has_4_cost:
        # 至少有一张4费牌，检查是否有2费或3费牌
        if cost_counts.get(2, 0) >= 1 or cost_counts.get(3, 0) >= 1:
            logger.info("满足4费档次基本条件：4费牌+低费牌组合")
            # 替换费用大于4的牌
            return [i for i, cost in enumerate(hand_costs) if cost > 4]
    
    # 如果有4费牌但没有其他低费牌，只替换费用大于4的牌
    if has_4_cost:
        logger.info("4费档次：仅有4费牌，替换高费牌")
        return [i for i, cost in enumerate(hand_costs) if cost > 4]
    
    return []


def _check_5_cost_strategy(hand_costs):
    """
    检查5费档次策略
    要求：必须包含至少一张5费牌
    优先级：[2,3,4,5] > [2,3,3,5] > [2,2,3,5] > [2,2,2,5]
    """
    # 统计各费用的数量
    cost_counts = {}
    for cost in hand_costs:
        cost_counts[cost] = cost_counts.get(cost, 0) + 1
    
    # 检查是否有5费牌
    has_5_cost = cost_counts.get(5, 0) >= 1
    
    # 检查是否有费用大于5的牌
    has_higher_cost = any(cost > 5 for cost in hand_costs)
    
    # 如果没有5费牌，但有费用大于5的牌，应该换掉这些高费牌
    if not has_5_cost:
        if has_higher_cost:
            logger.info("5费档次策略：缺少5费牌，但存在高费牌，替换高费牌")
            return [i for i, cost in enumerate(hand_costs) if cost > 5]
        else:
            logger.info("5费档次策略：缺少5费牌且没有高费牌，无需换牌")
            return []
    
    # 检查优先级组合
    # 优先级1: [2,3,4,5]
    if cost_counts.get(2, 0) >= 1 and cost_counts.get(3, 0) >= 1 and \
       cost_counts.get(4, 0) >= 1 and has_5_cost:
        logger.info("满足5费档次优先级1组合[2,3,4,5]相关卡牌")
        # 替换费用大于5的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 5]
    
    # 优先级2: [2,3,3,5]
    if cost_counts.get(2, 0) >= 1 and cost_counts.get(3, 0) >= 2 and has_5_cost:
        logger.info("满足5费档次优先级2组合[2,3,3,5]相关卡牌")
        # 替换费用大于5的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 5]
    
    # 优先级3: [2,2,3,5]
    if cost_counts.get(2, 0) >= 2 and cost_counts.get(3, 0) >= 1 and has_5_cost:
        logger.info("满足5费档次优先级3组合[2,2,3,5]相关卡牌")
        # 替换费用大于5的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 5]
    
    # 优先级4: [2,2,2,5]
    if cost_counts.get(2, 0) >= 3 and has_5_cost:
        logger.info("满足5费档次优先级4组合[2,2,2,5]相关卡牌")
        # 替换费用大于5的牌
        return [i for i, cost in enumerate(hand_costs) if cost > 5]
    
    # 检查是否有5费牌和一些低费牌的组合
    if has_5_cost:
        # 至少有一张5费牌，检查是否有2费或3费牌
        if cost_counts.get(2, 0) >= 1 or cost_counts.get(3, 0) >= 1:
            logger.info("满足5费档次基本条件：5费牌+低费牌组合")
            # 替换费用大于5的牌
            return [i for i, cost in enumerate(hand_costs) if cost > 5]
    
    # 如果有5费牌但没有其他低费牌，只替换费用大于5的牌
    if has_5_cost:
        logger.info("5费档次：仅有5费牌，替换高费牌")
        return [i for i, cost in enumerate(hand_costs) if cost > 5]
    
    return []
