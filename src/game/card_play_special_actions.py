"""
出牌特殊操作处理模块
处理出牌时的特殊操作（如选择目标等）
"""

import time
import random
import logging
from typing import TYPE_CHECKING
from src.config.card_priorities import get_high_priority_cards
from src.config import settings
from src.config.game_constants import DEFAULT_ATTACK_TARGET, DEFAULT_ATTACK_RANDOM
from src.game.game_actions import human_like_drag

if TYPE_CHECKING:
    from src.device.device_state import DeviceState

logger = logging.getLogger(__name__)

# 手牌出牌时特殊处理卡牌（需要特殊操作逻辑）
SPECIAL_CARDS = {
    "蛇神之怒": {
        "target_type": "enemy_player"  # 目标类型：敌方玩家
    },
    "命运黄昏奥丁": {
        "target_type": "shield_or_highest_hp"  # 目标类型：护盾或最高血量
    },
    "触手撕咬": {
        "target_type": "enemy_player"  # 目标类型：敌方玩家
    },
    "沉默的狙击手瓦路兹": {
        "target_type": "enemy_followers_hp_less_than_6"  # 目标类型：敌方随从血量小于6
    },
    "剑士的斩击": {
        "target_type": "shield_or_highest_hp_no_enemy_retrun_point"  # 目标类型：护盾或最高血量,若未检测到敌方随从则不用划出，直接返回恢复能量点
    },
    "王断的威光": {
        "target_type": "scan_our_follower_to_choose"  # 目标类型：扫描我方随从数量，选择选项
    }
}

def get_special_cards():
    """获取特殊处理卡牌列表"""
    return SPECIAL_CARDS


class CardPlaySpecialActions:
    """出牌特殊操作处理类"""
    
    def __init__(self, device_state: 'DeviceState'):
        self.device_state = device_state
    
    def play_single_card(self, card):
        """打出单张牌"""
        cost = card.get('cost', 0)
        center_x, center_y = card['center']
        target_x = center_x + 40
        card_name = card.get('name', '')
        
        # 导入特殊卡牌配置
        special_cards = get_special_cards()
        high_priority_names = set(get_high_priority_cards().keys())
        
        # 检查是否为特殊处理卡牌
        if card_name in special_cards:
            special_info = special_cards[card_name]
            target_type = special_info.get('target_type', '')
            
            if target_type == 'enemy_player':
                self._handle_enemy_player_target(card_name, center_x, center_y, target_x)
            elif target_type == 'shield_or_highest_hp':
                self._handle_shield_or_highest_hp_target(card_name, center_x, center_y, target_x)
            elif target_type == 'enemy_followers_hp_less_than_6':
                self._handle_enemy_followers_hp_less_than_6_target(card_name, center_x, center_y, target_x)
            elif target_type == 'scan_our_follower_to_choose':
                self._handle_scan_our_follower_to_choose_target(card_name, center_x, center_y, target_x)
            elif target_type == 'shield_or_highest_hp_no_enemy_retrun_point':
                result = self._handle_shield_or_highest_hp_noenemy_retrun_point_target(card_name, center_x, center_y, target_x)
                if result is False:
                    # 特殊处理：不消耗费用，且需要从手牌中移除
                    self._should_not_consume_cost = True
                    self._should_remove_from_hand = True
                    return False
            else:
                # 其他特殊卡牌，使用默认处理
                self._default_card_play(center_x, center_y, target_x)
        else:
            # 普通卡牌，正常打出
            self._default_card_play(center_x, center_y, target_x)
        
        # 特殊费用处理：勇武的堕天使奥莉薇打出后增加2点费用
        if card_name == "勇武的堕天使奥莉薇":
            time.sleep(5)
            self.device_state.logger.info(f"检测到打出{card_name}，增加2点费用")
            # 这里需要在调用方处理费用增加，我们通过返回值来通知
            self._extra_cost_bonus = 2
        elif card_name == "白银骑士团团长艾蜜莉亚":
            time.sleep(5)
            self.device_state.logger.info(f"检测到打出{card_name}，增加3点费用")
            # 这里需要在调用方处理费用增加，我们通过返回值来通知
            self._extra_cost_bonus = 3
        else:
            self._extra_cost_bonus = 0
        
        # 如果是高优先级卡牌，多等一会
        if card_name in high_priority_names:
            time.sleep(1)
        
        time.sleep(0.5)
        return True
    
    def _should_consume_cost(self, card_name):
        """检查是否应该消耗费用"""
        # 导入特殊卡牌配置
        special_cards = get_special_cards()
        
        # 检查是否为特殊处理卡牌
        if card_name in special_cards:
            special_info = special_cards[card_name]
            target_type = special_info.get('target_type', '')
            
            # 对于需要特殊处理的卡牌，返回True表示应该消耗费用
            return True
        
        # 普通卡牌应该消耗费用
        return True
    
    def _handle_enemy_player_target(self, card_name, center_x, center_y, target_x):
        """处理选择敌方玩家目标"""
        self.device_state.logger.info(f"检测到{card_name}，划出卡牌后选择敌方玩家目标")
        # 划出卡牌
        human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
        time.sleep(0.7)  # 等待
        
        enemy_x = DEFAULT_ATTACK_TARGET[0] + random.randint(-DEFAULT_ATTACK_RANDOM, DEFAULT_ATTACK_RANDOM)
        enemy_y = DEFAULT_ATTACK_TARGET[1] + random.randint(-DEFAULT_ATTACK_RANDOM, DEFAULT_ATTACK_RANDOM)
        self.device_state.u2_device.click(enemy_x, enemy_y)
        self.device_state.logger.info(f"{card_name}选择敌方玩家目标: ({enemy_x}, {enemy_y})")
        time.sleep(0.1)  # 等待0.1秒
    
    def _handle_shield_or_highest_hp_target(self, card_name, center_x, center_y, target_x):
        """处理优先破坏护盾，否则选择血量最高的敌方随从"""
        self.device_state.logger.info(f"检测到{card_name}，先检测护盾情况")
        # 检测护盾
        shield_targets = self._scan_shield_targets()
        shield_detected = bool(shield_targets)
        
        if shield_detected:
            self.device_state.logger.info("检测到护盾，划出卡牌后破坏护盾随从")
            # 划出卡牌
            human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
            time.sleep(0.5)  # 等待
            
            # 点击护盾随从（选择第一个护盾）
            shield_x, shield_y = shield_targets[0]
            self.device_state.u2_device.click(shield_x, shield_y)
            self.device_state.logger.info(f"点击护盾随从位置: ({shield_x}, {shield_y})")
        else:
            self.device_state.logger.info("未检测到护盾，尝试检测血量最高的敌方随从")
            # 划出卡牌
            human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
            time.sleep(0.2)  # 等待0.2秒
            
            # 检测敌方随从
            screenshot = self.device_state.take_screenshot()
            if screenshot:
                enemy_followers = self._scan_enemy_followers(screenshot)
                if enemy_followers:
                    # 找出血量最高的随从
                    try:
                        max_hp_follower = max(enemy_followers, key=lambda x: int(x[3]) if x[3].isdigit() else 0)
                        enemy_x, enemy_y, _, _ = max_hp_follower
                        enemy_x = int(enemy_x)
                        enemy_y = int(enemy_y)
                        self.device_state.u2_device.click(enemy_x, enemy_y)
                        self.device_state.logger.info(f"点击血量最高的敌方随从位置: ({enemy_x}, {enemy_y})")
                    except Exception as e:
                        self.device_state.logger.warning(f"选择敌方随从时出错: {str(e)}")
                else:
                    player_x = DEFAULT_ATTACK_TARGET[0] + random.randint(-DEFAULT_ATTACK_RANDOM, DEFAULT_ATTACK_RANDOM)
                    player_y = DEFAULT_ATTACK_TARGET[1] + random.randint(-DEFAULT_ATTACK_RANDOM, DEFAULT_ATTACK_RANDOM)
                    self.device_state.logger.info("未检测到敌方随从，尝试检测敌方护符或者其他可选择目标")
                    time.sleep(0.5)  # 等待0.几秒
                    can_choosetargets = self.device_state.game_manager.card_can_choose_target_like_amulet()
                    if can_choosetargets:
                        for pos in can_choosetargets:
                            self.device_state.u2_device.click(pos[0], pos[1])
                            time.sleep(0.1)

                        self.device_state.u2_device.click(645+random.randint(-3, 3),232+random.randint(-2, 2))
                        time.sleep(0.1)
                        self.device_state.u2_device.click(player_x+random.randint(-3, 3), player_y+random.randint(-2, 2))
                        self.device_state.logger.info(f"选择了一个可破坏目标(护符之类)")
                    else:
                        self.device_state.u2_device.click(645+random.randint(-3, 3),232+random.randint(-2, 2))
                        time.sleep(0.1)
                        self.device_state.u2_device.click(player_x+random.randint(-3, 3), player_y+random.randint(-2, 2))
                        self.device_state.logger.info("未检测到可破坏目标")


        time.sleep(2.7)
    
    def _handle_shield_or_highest_hp_noenemy_retrun_point_target(self, card_name, center_x, center_y, target_x):
        """处理优先破坏护盾，否则选择血量最高的敌方随从，若未检测到敌方随从则不消耗能量点"""
        self.device_state.logger.info(f"检测到{card_name}，先检测护盾情况")
        # 检测护盾
        shield_targets = self._scan_shield_targets()
        shield_detected = bool(shield_targets)
        
        if shield_detected:
            self.device_state.logger.info("检测到护盾，划出卡牌后破坏护盾随从")
            # 划出卡牌
            human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
            time.sleep(0.5)  # 等待
            
            # 点击护盾随从（选择第一个护盾）
            shield_x, shield_y = shield_targets[0]
            self.device_state.u2_device.click(shield_x, shield_y)
            self.device_state.logger.info(f"点击护盾随从位置: ({shield_x}, {shield_y})")
            time.sleep(2.7)
        else:
            self.device_state.logger.info("未检测到护盾，检测敌方随从")
            # 检测敌方随从
            screenshot = self.device_state.take_screenshot()
            if screenshot:
                enemy_followers = self._scan_enemy_followers(screenshot)
                if enemy_followers:
                    self.device_state.logger.info("检测到敌方随从，划出卡牌后破坏血量最高的敌方随从")
                    # 划出卡牌
                    human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
                    time.sleep(0.2)  # 等待0.2秒
                    
                    # 找出血量最高的随从
                    try:
                        max_hp_follower = max(enemy_followers, key=lambda x: int(x[3]) if x[3].isdigit() else 0)
                        enemy_x, enemy_y, _, _ = max_hp_follower
                        enemy_x = int(enemy_x)
                        enemy_y = int(enemy_y)
                        self.device_state.u2_device.click(enemy_x, enemy_y)
                        self.device_state.logger.info(f"点击血量最高的敌方随从位置: ({enemy_x}, {enemy_y})")
                    except Exception as e:
                        self.device_state.logger.warning(f"选择敌方随从时出错: {str(e)}")
                    time.sleep(2.7)
                else:
                    self.device_state.logger.info("未检测到敌方随从，不消耗能量点，直接返回")
                    # 不划出卡牌，不消耗能量点
                    return False
            else:
                self.device_state.logger.warning("无法获取截图，不消耗能量点，直接返回")
                return False
    
    def _handle_enemy_followers_hp_less_than_6_target(self, card_name, center_x, center_y, target_x):
        """处理点击敌方随从血量小于等于5的随从"""
        screenshot = self.device_state.take_screenshot()
        if screenshot:
            enemy_followers = self._scan_enemy_followers(screenshot)
            # 只保留HP为数字且<=5的随从
            valid_targets = [f for f in enemy_followers if f[3].isdigit() and int(f[3]) <= 5]
            
            if valid_targets:
                # 划出该手牌
                human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
                time.sleep(0.2)
                
                # 选择血量最大的
                target = max(valid_targets, key=lambda f: int(f[3]))
                self.device_state.logger.info(f"[划出{card_name}]，点击血量最大敌方随从: ({target[0]}, {target[1]}) HP={target[3]}")
                self.device_state.u2_device.click(int(target[0]), int(target[1]))
                time.sleep(0.2)
            else:
                # 没有血量小于5的随从，检查是否有其他敌方随从
                if enemy_followers:
                    # 有敌方随从，选择血量最大的
                    self.device_state.logger.info(f"划出[{card_name}]，未检测到血量小于5的敌方随从，选择血量最大的敌方随从")
                    # 划出该手牌
                    human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
                    time.sleep(0.3)
                    
                    # 选择血量最大的敌方随从
                    try:
                        max_hp_follower = max(enemy_followers, key=lambda x: int(x[3]) if x[3].isdigit() else 0)
                        enemy_x, enemy_y, _, hp = max_hp_follower
                        enemy_x = int(enemy_x)
                        enemy_y = int(enemy_y)
                        self.device_state.u2_device.click(enemy_x, enemy_y)
                        self.device_state.logger.info(f"划出[{card_name}]，点击血量最大的敌方随从: ({enemy_x}, {enemy_y}) HP={hp}")
                    except Exception as e:
                        self.device_state.logger.warning(f"划出[{card_name}]，选择敌方随从时出错: {str(e)}")
                    time.sleep(0.2)
                else:
                    # 一个敌方随从都没有，点击指定位置
                    self.device_state.logger.info(f"划出[{card_name}]，未检测到任何敌方随从")
                    # 划出该手牌
                    human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
                    time.sleep(0.2)
                    
                    # 点击指定位置 (611, 227)
                    self.device_state.u2_device.click(611+random.randint(-3, 3), 227+random.randint(-2, 2))
                    time.sleep(0.2)
    
    def _default_card_play(self, center_x, center_y, target_x):
        """默认卡牌打出"""
        human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
    

    
    def _scan_shield_targets(self):
        """扫描护盾目标"""
        # 这里需要调用原有的扫描方法，通过device_state访问
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_shield_targets()
        return []
    
    def _scan_enemy_followers(self, screenshot):
        """扫描敌方随从"""
        # 这里需要调用原有的扫描方法，通过device_state访问
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_enemy_followers(screenshot)
        return []
    
    def _handle_scan_our_follower_to_choose_target(self, card_name, center_x, center_y, target_x):
        """处理扫描我方随从数量选择选项（王断的威光）"""
        self.device_state.logger.info(f"检测到{card_name}，扫描我方随从数量")
        
        # 扫描我方随从
        screenshot = self.device_state.take_screenshot()
        time.sleep(0.2)  # 等待

        # 划出卡牌
        human_like_drag(self.device_state.u2_device, center_x, center_y, target_x, 400)
        time.sleep(0.2)  # 等待
        if screenshot:
            our_followers = self._scan_our_followers(screenshot)
            follower_count = len(our_followers)
            
            self.device_state.logger.info(f"检测到我方随从数量: {follower_count}")
            
            # 根据随从数量选择点击位置
            if follower_count <= 3:
                # 随从数量小于等于3个，点击上面的选项(748, 328)召唤两个随从
                click_x, click_y = 748, 328
                self.device_state.logger.info(f"随从数量≤3，召唤两个随从")
            else:
                # 随从数量大于3个，点击上面的选项(724, 429)强化随从
                click_x, click_y = 724, 429
                self.device_state.logger.info(f"随从数量>3，强化随从")
            
            # 执行点击
            self.device_state.u2_device.click(click_x+random.randint(-15, 15), click_y+random.randint(-2, 2))
            time.sleep(0.5)  # 等待点击响应
        else:
            self.device_state.logger.warning("无法获取截图，使用默认处理")
            # 如果无法获取截图，使用默认处理
            self._default_card_play(center_x, center_y, target_x)
    
    def _scan_our_followers(self, screenshot):
        """扫描我方随从"""
        # 这里需要调用原有的扫描方法，通过device_state访问
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_our_followers(screenshot)
        return [] 