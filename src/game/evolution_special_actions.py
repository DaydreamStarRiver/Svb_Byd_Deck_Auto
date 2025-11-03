"""
进化/超进化特殊操作处理模块
处理进化/超进化后的特殊action（如铁拳神父等）
"""

import time
import random
import logging
from src.config.card_priorities import get_evolve_priority_cards
from src.config import settings

logger = logging.getLogger(__name__)

# 进化/超进化后需要特殊操作的卡牌
EVOLVE_SPECIAL_ACTIONS = {
    "铁拳神父": {
        "action": "attack_enemy_follower_hp_less_than_4"  # 进化后点击一个血量小于4的敌方随从
    },
    "爽朗的天宫菲尔德亚": {
        "action": "attack_two_enemy_followers_hp_highest",  # 进化后点击一个血量最高的敌方随从
        "super_evolution_action": "attack_two_enemy_followers_hp_highest"  # 超进化后点击一个血量最高的敌方随从
    },
    "勇武的堕天使奥莉薇": {
        "super_evolution_action": "our_followers_with_evolution"  # 超进化的同时选择点击一个未进化的随从
    }
}

def get_evolve_special_actions():
    """获取进化/超进化特殊操作卡牌列表"""
    return EVOLVE_SPECIAL_ACTIONS

def is_evolve_special_action_card(card_name):
    """检查是否为进化/超进化特殊操作卡牌"""
    return card_name in EVOLVE_SPECIAL_ACTIONS


class EvolutionSpecialActions:
    """进化/超进化特殊操作处理类"""
    
    def __init__(self, device_state):
        self.device_state = device_state
    
    def handle_evolve_special_action(self, follower_name, pos=None, is_super_evolution=False, existing_followers=None):
        """
        处理进化/超进化后特殊action（如铁拳神父等），便于扩展
        follower_name: 卡牌名称
        pos: 进化随从的坐标（如有需要）
        is_super_evolution: 是否为超进化
        existing_followers: 已扫描的随从结果，避免重复扫描
        """
        special_actions = get_evolve_special_actions()
        
        if is_super_evolution:
            # 超进化逻辑
            action = special_actions.get(follower_name, {}).get('super_evolution_action', None)
            if action == 'attack_two_enemy_followers_hp_less_than_4':
                self._handle_attack_two_enemy_followers_hp_less_than_4(follower_name, is_super_evolution=True)
            elif action == 'attack_two_enemy_followers_hp_highest':
                self._handle_attack_two_enemy_followers_hp_highest(follower_name, is_super_evolution=True)
            elif action == 'our_followers_with_evolution':
                self._handle_our_followers_with_evolution(follower_name, is_super_evolution=True, existing_followers=existing_followers)
        else:
            # 普通进化逻辑
            action = special_actions.get(follower_name, {}).get('action', None)
            if action == 'attack_enemy_follower_hp_less_than_4':
                self._handle_attack_enemy_follower_hp_less_than_4(follower_name)
            elif action == 'attack_two_enemy_followers_hp_highest':
                self._handle_attack_two_enemy_followers_hp_highest(follower_name)
        # 以后可扩展更多action
    
    def _handle_attack_two_enemy_followers_hp_less_than_4(self, follower_name, is_super_evolution=False):
        """处理攻击两个HP<=3的敌方随从"""
        evolution_type = "超进化" if is_super_evolution else "进化"
        screenshot = self.device_state.take_screenshot()
        if screenshot:
            enemy_followers = self._scan_enemy_followers(screenshot)
            # 只保留HP为数字且<=3的随从
            valid_targets = [f for f in enemy_followers if f[3].isdigit() and int(f[3]) <= 3]
            if valid_targets:
                # 按血量从大到小排序，选择前两个
                sorted_targets = sorted(valid_targets, key=lambda f: int(f[3]), reverse=True)
                targets_to_click = sorted_targets[:2]
                
                for i, target in enumerate(targets_to_click):
                    self.device_state.logger.info(f"[{follower_name}]{evolution_type}后点击第{i+1}个敌方HP<=3随从: ({target[0]}, {target[1]}) HP={target[3]}")
                    self.device_state.u2_device.click(int(target[0]), int(target[1]))
                    time.sleep(0.5)
            else:
                self.device_state.logger.info(f"[{follower_name}]{evolution_type}后未找到HP<=3随从")
    
    def _handle_attack_two_enemy_followers_hp_highest(self, follower_name, is_super_evolution=False):
        """处理攻击血量最高的敌方随从"""
        evolution_type = "超进化" if is_super_evolution else "进化"
        screenshot = self.device_state.take_screenshot()
        if screenshot:
            enemy_followers = self._scan_enemy_followers(screenshot)
            # 只保留HP为数字的随从
            valid_targets = [f for f in enemy_followers if f[3].isdigit()]
            if valid_targets:
                # 选择血量最大的
                target = max(valid_targets, key=lambda f: int(f[3]))
                self.device_state.logger.info(f"[{follower_name}]{evolution_type}后点击血量最大敌方随从: ({target[0]}, {target[1]}) HP={target[3]}")
                self.device_state.u2_device.click(int(target[0]), int(target[1]))
                time.sleep(0.5)
            else:
                self.device_state.logger.info(f"[{follower_name}]{evolution_type}后未找到有效敌方随从")
    
    def _handle_our_followers_with_evolution(self, follower_name, is_super_evolution=False, existing_followers=None):
        """选择随从进行/超进化"""
        evolution_type = "超进化" if is_super_evolution else "进化"
        
        # 如果传入了已扫描的随从结果，直接使用；否则重新扫描
        if existing_followers is not None:
            our_followers = existing_followers
            self.device_state.logger.debug(f"[{follower_name}]{evolution_type}后使用已扫描的随从结果，避免重复扫描")
        else:
            screenshot = self.device_state.take_screenshot()
            if screenshot:
                # 获取我方随从位置和名字（scan_our_followers已经包含了SIFT识别结果）
                our_followers = self._scan_our_followers(screenshot)
            else:
                self.device_state.logger.info(f"[{follower_name}]{evolution_type}后截图失败")
                return
        
        if our_followers:
            # 找到有名字的随从（name不为None的随从），但排除自己
            named_followers = [f for f in our_followers if f[3] is not None and f[3] != follower_name]
            
            if named_followers:
                # 优先选择config.json中进化优先度高的随从
                evolve_priority_cards = get_evolve_priority_cards()
                
                # 按优先级排序：优先度高的在前，相同优先度按x坐标排序
                def get_priority(follower):
                    follower_name = follower[3]
                    if follower_name in evolve_priority_cards:
                        return evolve_priority_cards[follower_name].get('priority', 999)
                    return 999  # 没有配置的随从优先级最低
                
                # 按优先级排序，优先级数字越小越优先
                sorted_followers = sorted(named_followers, key=lambda f: (get_priority(f), f[0]))
                
                # 选择优先级最高的随从
                target = sorted_followers[0]
                target_x, target_y, target_type, target_name = target
                target_priority = get_priority(target)
                
                if target_priority < 999:
                    self.device_state.logger.info(f"[{follower_name}]{evolution_type}后选择高优先级随从: {target_name} (优先级:{target_priority})")
                else:
                    self.device_state.logger.info(f"[{follower_name}]{evolution_type}后选择我方未进化随从: {target_name}")
                
                self.device_state.u2_device.click(int(target_x), int(target_y))
                time.sleep(0.5)
                
                # # 检查选择的随从是否也有进化/超进化特殊操作
                # if target_name and is_evolve_special_action_card(target_name):
                #     self.device_state.logger.info(f"[{follower_name}]选择的随从[{target_name}]也有特殊操作，执行其超进化操作")
                #     # 执行该随从的超进化特殊操作
                #     self.handle_evolve_special_action(target_name, (target_x, target_y), is_super_evolution=True)
            else:
                # 如果没有其他有名字的随从，选择第一个没有名字的随从
                unnamed_followers = [f for f in our_followers if f[3] is None]
                if unnamed_followers:
                    target = unnamed_followers[0]
                    target_x, target_y, target_type, target_name = target
                    
                    self.device_state.logger.info(f"[{follower_name}]{evolution_type}后选择我方随从")
                    self.device_state.u2_device.click(int(target_x), int(target_y))
                    time.sleep(0.5)
                    
                    # 注意：无名字随从无法检查是否有特殊操作，因为不知道其名称
                else:
                    self.device_state.logger.info(f"[{follower_name}]{evolution_type}后未检测到可选择进化的我方随从")
        else:
            self.device_state.logger.info(f"[{follower_name}]{evolution_type}后未检测到我方随从")
        time.sleep(1)
    
    def _handle_attack_enemy_follower_hp_less_than_4(self, follower_name):
        """处理攻击HP<=3的敌方随从"""
        screenshot = self.device_state.take_screenshot()
        if screenshot:
            enemy_followers = self._scan_enemy_followers(screenshot)
            # 只保留HP为数字且<=3的随从
            valid_targets = [f for f in enemy_followers if f[3].isdigit() and int(f[3]) <= 3]
            if valid_targets:
                # 选择血量最大的
                target = max(valid_targets, key=lambda f: int(f[3]))
                self.device_state.logger.info(f"[{follower_name}]进化后点击敌方HP<=3且最大随从: ({target[0]}, {target[1]}) HP={target[3]}")
                self.device_state.u2_device.click(int(target[0]), int(target[1]))
                time.sleep(0.5)
            else:
                self.device_state.logger.info(f"[{follower_name}]进化后未找到HP<=3随从")
    
    def _scan_enemy_followers(self, screenshot):
        """扫描敌方随从"""
        # 这里需要调用原有的扫描方法，通过device_state访问
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_enemy_followers(screenshot)
        return []
    
    def _scan_our_followers(self, screenshot):
        """扫描我方随从"""
        # 这里需要调用原有的扫描方法，通过device_state访问
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_our_followers(screenshot)
        return [] 