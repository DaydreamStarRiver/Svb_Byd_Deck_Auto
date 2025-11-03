"""
费用识别模块
实现卡牌费用数字的识别功能
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class CostRecognition:
    """费用识别类"""
    
    def __init__(self, constants_manager=None):
        # 从常量管理器获取参数
        if constants_manager:
            self.constants = constants_manager
            self.cost_digit_height, self.cost_digit_width = constants_manager.get_cost_digit_size()
            self.cost_min, self.cost_max = constants_manager.get_cost_range()
            self.cost_confidence_threshold = constants_manager.cost_confidence_threshold
        else:
            # 使用默认值
            from src.config.game_constants import (
                COST_DIGIT_HEIGHT, COST_DIGIT_WIDTH,
                COST_MIN, COST_MAX, COST_CONFIDENCE_THRESHOLD
            )
            self.cost_digit_height, self.cost_digit_width = COST_DIGIT_HEIGHT, COST_DIGIT_WIDTH
            self.cost_min, self.cost_max = COST_MIN, COST_MAX
            self.cost_confidence_threshold = COST_CONFIDENCE_THRESHOLD
    
    def get_cost_digit_size(self) -> Tuple[int, int]:
        """获取费用数字尺寸"""
        return self.cost_digit_height, self.cost_digit_width
    
    def get_cost_range(self) -> Tuple[int, int]:
        """获取费用范围"""
        return self.cost_min, self.cost_max
    
    def get_confidence_threshold(self) -> float:
        """获取置信度阈值"""
        return self.cost_confidence_threshold 