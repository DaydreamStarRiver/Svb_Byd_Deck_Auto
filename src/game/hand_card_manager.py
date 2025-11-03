"""
手牌管理器
专门使用SIFT特征匹配识别手牌区域中的卡牌及其费用
"""

import cv2
import numpy as np
import logging
import time
from typing import List, Dict, Optional
from .sift_card_recognition import SiftCardRecognition

logger = logging.getLogger(__name__)


class HandCardManager:
    """手牌管理器类"""
    
    # 全局SIFT识别器实例，确保模板只加载一次
    _sift_recognition_instance = None
    
    def __init__(self, device_state=None):
        """
        初始化手牌管理器
        
        Args:
            device_state: 设备状态对象
        """
        self.device_state = device_state
        self.hand_area = (229, 539, 1130, 710)  # 手牌区域坐标
        
        # 使用全局单例SIFT识别器
        if HandCardManager._sift_recognition_instance is None:
            HandCardManager._sift_recognition_instance = SiftCardRecognition("shadowverse_cards_cost")
            logger.info("首次创建SIFT识别器，加载卡牌模板")
        # else:
            # logger.info("复用已存在的SIFT识别器实例")
        
        self.sift_recognition = HandCardManager._sift_recognition_instance

    def recognize_hand_shield_card(self) -> bool:
        """
        检测手牌中是否有守护卡牌名字
        
        Returns:
            bool: 如果手牌中有shield随从则返回True，否则返回False
        """
        try:
        #     # 从game_constants导入shield随从列表
            from src.config.game_constants import SHIELD_FOLLOWER_NAMES
            shield_names = SHIELD_FOLLOWER_NAMES
            # logger.info(f"成功加载 {len(shield_names)} 个shield随从名字")
            
            # 获取当前手牌
            hand_cards = self.get_hand_cards_with_retry(silent=True)
            if not hand_cards:
                logger.info("未识别到手牌，无法检测shield随从")
                return False
            
            # 检查手牌中是否有shield随从
            found_shield_cards = []
            for card in hand_cards:
                card_name = card.get('name', '')
                if card_name in shield_names:
                    found_shield_cards.append(card_name)
            
            if found_shield_cards:
                logger.warning(f"手牌中发现护盾手牌: {' | '.join(found_shield_cards)}")
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"检测shield随从时出错: {str(e)}")
            return False

    def recognize_hand_cards(self, screenshot, silent=False) -> List[Dict]:
        """
        使用SIFT识别手牌区域中的卡牌
        
        Args:
            screenshot: 游戏截图
            silent: 是否静默模式，不输出日志
            
        Returns:
            List[Dict]: 识别到的卡牌列表，每个字典包含:
                - center: (x, y) 卡牌中心位置
                - cost: int 卡牌费用
                - name: str 卡牌名称
                - confidence: float 匹配置信度
        """
        try:
            # 使用SIFT识别手牌
            recognized_cards = self.sift_recognition.recognize_hand_cards(screenshot)
            
            if recognized_cards and not silent:
                # 输出识别结果
                card_info = []
                for card in recognized_cards:
                    card_info.append(f"{card['cost']}费_{card['name']}")
                    #加上了置信度 card_info.append(f"{card['cost']}费_{card['name']}({card['confidence']:.2f})")
                logger.info(f"手牌详情: {' | '.join(card_info)}")
                
            elif not recognized_cards and not silent:
                logger.info("SIFT未识别到任何手牌")
            
            return recognized_cards
            
        except Exception as e:
            logger.error(f"手牌识别出错: {str(e)}")
            return []
    
    def get_hand_cards_with_retry(self, max_retries: int = 3, silent: bool = False) -> List[Dict]:
        """
        带重试机制的手牌识别
        
        Args:
            max_retries: 最大重试次数
            silent: 是否静默模式，不输出日志
            
        Returns:
            List[Dict]: 识别到的卡牌列表
        """
        for attempt in range(max_retries):
            try:
                # 获取截图
                screenshot = self.device_state.take_screenshot()
                if screenshot is None:
                    if not silent:
                        logger.warning(f"第{attempt + 1}次尝试获取截图失败")
                    continue
                
                # 识别手牌
                cards = self.recognize_hand_cards(screenshot, silent)
                
                if cards:
                    return cards
                else:
                    if not silent:
                        logger.warning(f"第{attempt + 1}次尝试未识别到手牌")
                    
                    # 未识别到手牌时，点击展牌按钮再重试
                    from src.config.game_constants import SHOW_CARDS_BUTTON, SHOW_CARDS_RANDOM_X, SHOW_CARDS_RANDOM_Y
                    import random, time
                    self.device_state.u2_device.click(
                        SHOW_CARDS_BUTTON[0] + random.randint(SHOW_CARDS_RANDOM_X[0], SHOW_CARDS_RANDOM_X[1]),
                        SHOW_CARDS_BUTTON[1] + random.randint(SHOW_CARDS_RANDOM_Y[0], SHOW_CARDS_RANDOM_Y[1])
                    )
                    time.sleep(0.1)
                    #移除手牌光标提高识别率
                    from src.config.game_constants import DEFAULT_ATTACK_TARGET
                    self.device_state.u2_device.click(DEFAULT_ATTACK_TARGET[0] + random.randint(-2,2), DEFAULT_ATTACK_TARGET[1] + random.randint(-2,2))
                    time.sleep(1.2)
            
            except Exception as e:
                logger.error(f"第{attempt + 1}次手牌识别尝试出错: {str(e)}")
            
            # 等待一段时间后重试
            if attempt < max_retries - 1:
                time.sleep(1)
        
        if not silent:
            logger.warning(f"经过{max_retries}次尝试仍未识别到手牌")
        return []
    
    def get_card_cost_by_name(self, card_name: str) -> Optional[int]:
        """
        根据卡牌名称获取费用
        
        Args:
            card_name: 卡牌名称
            
        Returns:
            Optional[int]: 卡牌费用，如果未找到返回None
        """
        return self.sift_recognition.get_card_cost_by_name(card_name)
    
    def get_all_card_names(self) -> List[str]:
        """
        获取所有卡牌名称
        
        Returns:
            List[str]: 所有卡牌名称列表
        """
        return self.sift_recognition.get_all_card_names()
    
    def get_all_card_costs(self) -> Dict[str, int]:
        """
        获取所有卡牌的费用映射
        
        Returns:
            Dict[str, int]: 卡牌名称到费用的映射
        """
        return self.sift_recognition.get_all_card_costs()
    
    def sort_cards_by_cost(self, cards: List[Dict]) -> List[Dict]:
        """
        按费用排序卡牌（从低到高）
        
        Args:
            cards: 卡牌列表
            
        Returns:
            List[Dict]: 排序后的卡牌列表
        """
        return sorted(cards, key=lambda card: card['cost'])
    
    def sort_cards_by_position(self, cards: List[Dict]) -> List[Dict]:
        """
        按位置排序卡牌（从左到右）
        
        Args:
            cards: 卡牌列表
            
        Returns:
            List[Dict]: 排序后的卡牌列表
        """
        return sorted(cards, key=lambda card: card['center'][0])
    
    def filter_cards_by_cost(self, cards: List[Dict], max_cost: int) -> List[Dict]:
        """
        按费用过滤卡牌
        
        Args:
            cards: 卡牌列表
            max_cost: 最大费用
            
        Returns:
            List[Dict]: 过滤后的卡牌列表
        """
        return [card for card in cards if card['cost'] <= max_cost]
    
    def get_cards_summary(self, cards: List[Dict]) -> str:
        """
        获取卡牌摘要信息
        
        Args:
            cards: 卡牌列表
            
        Returns:
            str: 卡牌摘要信息
        """
        if not cards:
            return "无手牌"
        
        # 按费用分组
        cost_groups = {}
        for card in cards:
            cost = card['cost']
            if cost not in cost_groups:
                cost_groups[cost] = []
            cost_groups[cost].append(card['name'])
        
        # 生成摘要
        summary_parts = []
        for cost in sorted(cost_groups.keys()):
            names = cost_groups[cost]
            summary_parts.append(f"{cost}费({len(names)}张): {', '.join(names)}")
        
        return " | ".join(summary_parts) 