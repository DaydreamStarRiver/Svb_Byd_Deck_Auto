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


def determine_card_swaps(hand_cards: List[int], strategy: str) -> Tuple[List[int], List[int]]:
    """
    根据当前手牌和选择的策略，确定需要保留和更换的卡牌索引
    
    Args:
        hand_cards: 当前手牌，每个元素表示卡牌费用
        strategy: 换牌策略，直接从UI传入的策略名称（"3费档次"、"4费档次"、"5费档次"）
    
    Returns:
        Tuple[List[int], List[int]]: (需要保留的卡牌索引, 需要更换的卡牌索引)
    """
    # 确保手牌数量不超过4张（影之诗起始手牌只有4张）
    hand_cards = hand_cards[:4]
    num_cards = len(hand_cards)
    
    # 根据UI设置的策略直接执行对应的换牌逻辑
    cards_to_replace = []
    
    logger.info(f"当前手牌费用: {hand_cards}")
    logger.info(f"使用策略: {strategy}")
    
    if strategy == '3费档次':
        cards_to_replace = _check_3_cost_strategy(hand_cards)
    elif strategy == '4费档次':
        cards_to_replace = _check_4_cost_strategy(hand_cards)
    elif strategy == '5费档次':
        cards_to_replace = _check_5_cost_strategy(hand_cards)
    else:
        # 默认使用3费档次策略
        logger.warning(f"未知策略: {strategy}，使用默认3费档次策略")
        cards_to_replace = _check_3_cost_strategy(hand_cards)
    
    # 计算需要保留的卡牌索引
    keep_indices = [i for i in range(num_cards) if i not in cards_to_replace]
    
    return keep_indices, cards_to_replace


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





def execute_card_swaps(game_actions_instance, swap_indices: List[int], card_infos: List[Dict]) -> bool:
    """
    根据指定的索引执行换牌操作
    
    Args:
        game_actions_instance: GameActions类的实例
        swap_indices: 需要更换的卡牌索引列表
        card_infos: 卡牌信息列表，包含位置信息
    
    Returns:
        bool: 换牌操作是否成功
    """
    try:
        device_state = game_actions_instance.device_state
        
        # 确保换牌索引不超过卡牌信息数量
        valid_indices = [idx for idx in swap_indices if 0 <= idx < len(card_infos)]
        
        if not valid_indices:
            logger.info("没有需要更换的卡牌")
            return True
        
        from src.config import settings
        from src.game.game_actions import human_like_drag
        
        # 执行换牌操作
        for idx in valid_indices:
            card = card_infos[idx]
            center_x = card['center_x']
            center_y = card['center_y']
            cost = card['cost']
            
            logger.info(f"更换费用为{cost}的卡牌")
            # 拖动卡牌到换牌区域上方
            human_like_drag(
                device_state.u2_device,
                center_x + 66, 516,  # 卡牌中心位置稍微向右偏移
                center_x + 66, 208,  # 换牌区域上方
                duration=random.uniform(*settings.get_human_like_drag_duration_range())
            )
            # 等待一下，确保换牌操作完成
            import time
            time.sleep(0.5)
        
        logger.info(f"成功更换了{len(valid_indices)}张卡牌")
        return True
        
    except Exception as e:
        logger.error(f"执行换牌操作时出错: {str(e)}")
        return False