"""
游戏操作模块
实现所有游戏动作和策略
"""

from errno import ECANCELED
import cv2
import numpy as np
import random
import time
import logging
import os

from torch import device
from src.config import settings
from src.config.game_constants import (
    DEFAULT_ATTACK_TARGET, DEFAULT_ATTACK_RANDOM,
    POSITION_RANDOM_RANGE, SHOW_CARDS_BUTTON, SHOW_CARDS_RANDOM_X, SHOW_CARDS_RANDOM_Y,
    BLANK_CLICK_POSITION, BLANK_CLICK_RANDOM
)
import math
from src.config.card_priorities import get_card_priority, is_evolve_priority_card, get_evolve_priority_cards, is_evolve_special_action_card, get_evolve_special_actions
from src.config.config_manager import ConfigManager
import glob

logger = logging.getLogger(__name__)


class GameActions:
    """游戏操作类"""
    
    def __init__(self, device_state):
        self.device_state = device_state
        # 初始化手牌管理器，只创建一次
        from .hand_card_manager import HandCardManager
        self.hand_manager = HandCardManager(device_state)
    
    @property
    def follower_manager(self):
        """动态获取follower_manager，确保在GameManager初始化后才可用"""
        return self.device_state.follower_manager

    def perform_follower_attacks(self,enemy_check):
        """执行随从攻击"""
        type_name_map = {
            "yellow": "突进",
            "green": "疾驰"
        }

        # 对面玩家位置（默认攻击目标）
        default_target = (
            DEFAULT_ATTACK_TARGET[0] + random.randint(-DEFAULT_ATTACK_RANDOM, DEFAULT_ATTACK_RANDOM),
            DEFAULT_ATTACK_TARGET[1] + random.randint(-DEFAULT_ATTACK_RANDOM, DEFAULT_ATTACK_RANDOM)
        )

        should_check_shield = enemy_check
        if should_check_shield:
            shield_targets = self._scan_shield_targets()
            shield_detected = bool(shield_targets)
        else:
            shield_detected = False


        # 获取当前随从位置和类型
        all_followers = self.follower_manager.get_positions()

        if shield_detected:
            max_attempts = 5  # 最多循环5次
            attempt_count = 0

            while shield_targets and attempt_count < max_attempts:
                attempt_count += 1
                self.device_state.logger.info(f"破盾尝试第{attempt_count}/5次")
                current_shield = shield_targets[-1]
                shield_x, shield_y = current_shield

                closest_follower = None
                closest_follower_name = None
                for type_priority in ["yellow", "green"]:
                    type_followers = [(x, y, name) for x, y, t, name in all_followers if t == type_priority]
                    if not type_followers:
                        continue

                    # 选择离护盾最近的该类型随从
                    min_distance = float('inf')
                    for fx, fy, fname in type_followers:
                        dist = ((fx - shield_x) ** 2 + (fy - shield_y) ** 2) ** 0.5
                        if dist < min_distance:
                            min_distance = dist
                            closest_follower = (fx, fy)
                            closest_follower_name = fname
                    if closest_follower:
                        type_name = type_name_map.get(type_priority, type_priority)
                        if closest_follower_name:
                            self.device_state.logger.info(f"使用{type_name}随从[{closest_follower_name}]攻击护盾")
                        else:
                            self.device_state.logger.info(f"使用{type_name}随从攻击护盾")
                        human_like_drag(self.device_state.u2_device, closest_follower[0], closest_follower[1], shield_x, shield_y, duration=random.uniform(*settings.get_human_like_drag_duration_range()))
                        time.sleep(1)
                        break  # 已攻击则跳出类型循环

                if not closest_follower:
                    self.device_state.logger.info("没有可用的突进/疾驰随从攻击护盾")
                    return # 退出循环

                # 攻击后更新随从信息
                new_screenshot = self.device_state.take_screenshot()
                if new_screenshot:
                    new_followers = self._scan_our_followers(new_screenshot)
                    self.follower_manager.update_positions(new_followers)
                    all_followers = new_followers

                # 检查更新后的随从是否还有突进/疾驰能力，没有则直接返回
                has_attack_followers = False
                for type_priority in ["yellow", "green"]:
                    type_followers = [(x, y, name) for x, y, t, name in all_followers if t == type_priority]
                    if type_followers:
                        has_attack_followers = True
                        break

                if not has_attack_followers:
                    self.device_state.logger.info("攻击后没有可用的突进/疾驰随从，停止破盾")
                    return

                # 重新扫描护盾，检查当前护盾是否还在
                shield_targets = self._scan_shield_targets()
                
                time.sleep(0.2)
            
            # 检查是否因为达到最大尝试次数而退出循环
            if attempt_count >= max_attempts :
                self.device_state.logger.warning(f"达到最大破盾尝试次数({max_attempts}次)，停止破盾操作")

        # 没有护盾，使用绿色随从攻击敌方主人
        green_followers = [(x, y, name) for x, y, t, name in all_followers if t == "green"]
        if green_followers:
            for x, y, name in green_followers:
                if name:
                    self.device_state.logger.info(f"使用疾驰随从[{name}]攻击敌方玩家")
                else:
                    self.device_state.logger.info("使用疾驰随从攻击敌方玩家")
                target_x, target_y = default_target
                human_like_drag(self.device_state.u2_device, x, y, target_x, target_y, duration=random.uniform(*settings.get_human_like_drag_duration_range()))
                time.sleep(0.45)

        # 使用黄色突进随从攻击敌方血量最小的随从
        if not shield_detected:
            yellow_followers = [(x, y, name) for x, y, t, name in all_followers if t == "yellow"]
            if yellow_followers:
                for i, (x, y, name) in enumerate(yellow_followers):
                    # 检查是否是最后一个黄色随从
                    is_last_yellow = (i == len(yellow_followers) - 1)
                    
                    # 每次攻击前都扫描敌方随从和血量
                    enemy_screenshot = self.device_state.take_screenshot()
                    if enemy_screenshot:
                        enemy_followers = self._scan_enemy_followers(enemy_screenshot)
                        if enemy_followers:
                            try:
                                min_hp_follower = min(enemy_followers, key=lambda x: int(x[3]) if x[3].isdigit() else 0)
                                enemy_x, enemy_y, _, _ = min_hp_follower
                                if name:
                                    self.device_state.logger.info(f"使用突进随从[{name}]攻击敌方血量较小的随从")
                                else:
                                    self.device_state.logger.info("使用突进随从攻击敌方血量较小的随从")
                                human_like_drag(self.device_state.u2_device, x, y, enemy_x, enemy_y, duration=random.uniform(*settings.get_human_like_drag_duration_range()))
                                time.sleep(1.5)
                                
                                # 如果是最后一个黄色随从，攻击完成后直接跳出循环，不再进行后续扫描
                                if is_last_yellow:
                                    break
                                    
                            except Exception as e:
                                self.device_state.logger.warning(f"突进敌方最小血量随从失败: {str(e)}")
                    else:
                        self.device_state.logger.warning("截图失败，跳过攻击")

    def perform_evolution_actions(self):
        """执行进化/超进化操作"""
        all_followers = self.follower_manager.get_positions()
        if not all_followers:
            self.device_state.logger.info("没有随从可进化")
            return

        from src.config.card_priorities import is_evolve_priority_card, get_evolve_priority_cards, is_evolve_special_action_card, get_evolve_special_actions
        evolve_priority_cards_cfg = get_evolve_priority_cards()
        # 先筛选进化优先卡牌
        evolve_priority_followers = []
        other_followers = []
        for f in all_followers:
            follower_name = f[3] if len(f) > 3 else None
            if follower_name and is_evolve_priority_card(follower_name):
                evolve_priority_followers.append(f)
            else:
                other_followers.append(f)
        # 进化优先卡牌排序：先按priority（数字小优先），再按类型（绿色>黄色>普通），再按x坐标
        def get_evolve_priority(name):
            return evolve_priority_cards_cfg.get(name, {}).get('priority', 999)
        type_priority = {"green": 0, "yellow": 1, "normal": 2}
        sorted_evolve_priority = sorted(
            evolve_priority_followers,
            key=lambda follower: (
                get_evolve_priority(follower[3] if len(follower) > 3 else None),
                type_priority.get(follower[2], 3),
                follower[0]
            )
        )
        sorted_others = sorted(
            other_followers,
            key=lambda follower: (type_priority.get(follower[2], 3), follower[0])
        )
        # 合并，优先进化优先卡牌
        sorted_followers = sorted_evolve_priority + sorted_others
        # 提取位置坐标
        positions = [pos[:2] for pos in sorted_followers]

        # 遍历每个随从位置
        for pos in positions:
            x, y = pos
            # 记录当前随从类型
            follower_type = None
            follower_name = None
            position_tolerance = POSITION_RANDOM_RANGE["medium"]
            for f in all_followers:
                if abs(f[0] - x) < position_tolerance and abs(f[1] - y) < position_tolerance:  # 找到匹配的随从
                    follower_type = f[2]
                    follower_name = f[3] if len(f) > 3 else None
                    break
            # 点击该位置
            self.device_state.u2_device.click(x, y)
            time.sleep(0.5)  # 等待进化按钮出现

            # 获取新截图检测进化按钮
            new_screenshot = self.device_state.take_screenshot()
            if new_screenshot is None:
                self.device_state.logger.warning(f"位置 {pos} 无法获取截图，跳过检测")
                time.sleep(0.1)
                continue

            # 转换为OpenCV格式
            new_screenshot_np = np.array(new_screenshot)
            new_screenshot_cv = cv2.cvtColor(new_screenshot_np, cv2.COLOR_RGB2BGR)

            # 同时检查两个检测函数
            max_loc, max_val = self._detect_super_evolution_button(new_screenshot_cv)
            if max_val >= 0.80 and max_loc is not None:
                template_info = self._load_super_evolution_template()
                if template_info:
                    center_x = max_loc[0] + template_info['w'] // 2
                    center_y = max_loc[1] + template_info['h'] // 2
                    self.device_state.u2_device.click(center_x, center_y)
                    self.device_state.super_evolution_point -= 1
                    if follower_name:
                        if is_evolve_priority_card(follower_name):
                            self.device_state.logger.info(f"优先超进化了[{follower_name}]")
                        self.device_state.logger.info(f"超进化了[{follower_name}]，剩余超进化次数：{self.device_state.super_evolution_point}")
                    else:
                        self.device_state.logger.info(f"检测到超进化按钮并点击，剩余超进化次数：{self.device_state.super_evolution_point}")
                    time.sleep(3.5)

                    # 特殊超进化后操作（如铁拳神父）
                    if follower_name and is_evolve_special_action_card(follower_name):
                        self._handle_evolve_special_action(follower_name, pos, is_super_evolution=True, existing_followers=all_followers)
                    # 如果超进化到突进或者普通随从，则再检查无护盾后攻击敌方随从
                    if follower_type in ["yellow", "normal"]:
                        # 等待超进化动画完成
                        time.sleep(1)
                        
                        # 检查敌方护盾
                        shield_targets = self._scan_shield_targets()
                        shield_detected = bool(shield_targets)

                        if not shield_detected:
                            # 扫描敌方普通随从
                            screenshot = self.device_state.take_screenshot()
                            if screenshot:
                                enemy_followers = self._scan_enemy_followers(screenshot)

                                # 扫描敌方普通随从,如果不为空则攻击血量最高的一个
                                if enemy_followers:
                                    # 找出最高血量的随从
                                    try:
                                        # 将血量字符串转换为整数进行比较
                                        max_hp_follower = max(enemy_followers, key=lambda x: int(x[3]) if x[3].isdigit() else 0)
                                    except Exception as e:
                                        # 如果转换失败，选择第一个随从
                                        self.device_state.logger.warning(f"敌方随从血量转换失败: {e}")
                                        max_hp_follower = enemy_followers[0]

                                    enemy_x, enemy_y, _, hp_value = max_hp_follower
                                    # 使用原来的随从位置作为起始点
                                    human_like_drag(self.device_state.u2_device, pos[0], pos[1], enemy_x, enemy_y, duration=random.uniform(*settings.get_human_like_drag_duration_range()))
                                    time.sleep(1)
                                    if follower_name:
                                        self.device_state.logger.info(f"超进化了[{follower_name}]并攻击了敌方较高血量随从")
                                    else:
                                        self.device_state.logger.info(f"超进化了突进/普通随从攻击了敌方较高血量随从")
                    break

            max_loc1, max_val1 = self._detect_evolution_button(new_screenshot_cv)
            if max_val1 >= 0.80 and max_loc1 is not None:
                template_info = self._load_evolution_template()
                if template_info:
                    center_x = max_loc1[0] + template_info['w'] // 2
                    center_y = max_loc1[1] + template_info['h'] // 2
                    self.device_state.u2_device.click(center_x, center_y)
                    self.device_state.evolution_point -= 1
                    if follower_name:
                        if is_evolve_priority_card(follower_name):
                            self.device_state.logger.info(f"优先进化了[{follower_name}]")
                        self.device_state.logger.info(f"进化了[{follower_name}]，剩余进化次数：{self.device_state.evolution_point}")
                    else:
                        self.device_state.logger.info(f"执行了进化，剩余进化次数：{self.device_state.evolution_point}")
                    time.sleep(3.5)

                    # 特殊进化后操作（如铁拳神父）
                    if follower_name and is_evolve_special_action_card(follower_name):
                        self._handle_evolve_special_action(follower_name, pos, is_super_evolution=False, existing_followers=all_followers)
                break
            time.sleep(0.01)
        time.sleep(2)  # 短暂等待

    def _handle_evolve_special_action(self, follower_name, pos=None, is_super_evolution=False, existing_followers=None):
        """
        处理进化/超进化后特殊action（如铁拳神父等），便于扩展
        follower_name: 卡牌名称
        pos: 进化随从的坐标（如有需要）
        is_super_evolution: 是否为超进化
        existing_followers: 已扫描的随从结果，避免重复扫描
        """
        from .evolution_special_actions import EvolutionSpecialActions
        evolution_actions = EvolutionSpecialActions(self.device_state)
        evolution_actions.handle_evolve_special_action(follower_name, pos, is_super_evolution, existing_followers)

    def perform_full_actions(self):
        """720P分辨率下的出牌攻击操作"""
        from concurrent.futures import ThreadPoolExecutor
        # 并发调用scan_enemy_ATK
        with ThreadPoolExecutor(max_workers=3) as executor:
            enemy_future = executor.submit(self._scan_enemy_ATK, self.device_state.take_screenshot())
        
        # 展牌一次
        self.device_state.u2_device.click(
            SHOW_CARDS_BUTTON[0] + random.randint(SHOW_CARDS_RANDOM_X[0], SHOW_CARDS_RANDOM_X[1]),
            SHOW_CARDS_BUTTON[1] + random.randint(SHOW_CARDS_RANDOM_Y[0], SHOW_CARDS_RANDOM_Y[1])
        )
        
        
        
        #移除手牌光标提高识别率
        self.device_state.u2_device.click(DEFAULT_ATTACK_TARGET[0] + random.randint(-2,2), DEFAULT_ATTACK_TARGET[1] + random.randint(-2,2))
        time.sleep(0.3)
        
        # 获取截图
        screenshot = self.device_state.take_screenshot()
        image = np.array(screenshot)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        # 执行出牌逻辑
        self._play_cards(image)
        time.sleep(1)

        # 点击绝对无遮挡处关闭可能扰乱识别的面板
        from src.config.game_constants import BLANK_CLICK_POSITION, BLANK_CLICK_RANDOM
        self.device_state.u2_device.click(
            BLANK_CLICK_POSITION[0] + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM),
            BLANK_CLICK_POSITION[1] + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM)
        )
        time.sleep(1.5)


        # 获取并发调用的敌方检测结果
        try:
            enemy_check = enemy_future.result()
            # self.device_state.logger.info(f"出牌前有 {len(enemy_check)} 个敌方随从")
        except Exception as e:
            self.device_state.logger.warning(f"敌方随从检测失败: {str(e)}")
            enemy_check = []

        # 获取随从位置
        screenshot = self.device_state.take_screenshot()
        if screenshot:
            blue_positions = self._scan_our_followers(screenshot)
            self.follower_manager.update_positions(blue_positions)

        # 检查是否有疾驰或突进随从
        followers = self.follower_manager.get_positions()
        green_or_yellow_followers = [f for f in followers if f[2] in ['green', 'yellow']]

        if green_or_yellow_followers:
            self.perform_follower_attacks(enemy_check)
        else:
            self.device_state.logger.info("未检测到可进行攻击的随从，跳过攻击操作")

        time.sleep(1)

    def perform_fullPlus_actions(self):
        """执行进化/超进化与攻击操作"""
        from concurrent.futures import ThreadPoolExecutor

        # 并发调用scan_enemy_ATK
        with ThreadPoolExecutor(max_workers=3) as executor:
            enemy_future = executor.submit(self._scan_enemy_ATK, self.device_state.take_screenshot())

        # 展牌
        self.device_state.u2_device.click(
            SHOW_CARDS_BUTTON[0] + random.randint(SHOW_CARDS_RANDOM_X[0], SHOW_CARDS_RANDOM_X[1]),
            SHOW_CARDS_BUTTON[1] + random.randint(SHOW_CARDS_RANDOM_Y[0], SHOW_CARDS_RANDOM_Y[1])
        )
        time.sleep(0.2)
        #移除手牌光标提高识别率
        self.device_state.u2_device.click(DEFAULT_ATTACK_TARGET[0] + random.randint(-2,2), DEFAULT_ATTACK_TARGET[1] + random.randint(-2,2))
        time.sleep(0.3)

        # 获取截图
        screenshot = self.device_state.take_screenshot()
        if screenshot is None:
            self.device_state.logger.warning("无法获取截图，跳过出牌")
            return

        # 转换为OpenCV格式
        image = np.array(screenshot)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        # 执行出牌逻辑
        self._play_cards(image)
        time.sleep(1)

        # # 点击绝对无遮挡处关闭可能扰乱识别的面板
        from src.config.game_constants import BLANK_CLICK_POSITION, BLANK_CLICK_RANDOM
        self.device_state.u2_device.click(
            BLANK_CLICK_POSITION[0] + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM),
            BLANK_CLICK_POSITION[1] + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM)
        )
        time.sleep(1.5)

        #获取并发调用的敌方检测结果
        try:
            enemy_check = enemy_future.result()
            # self.device_state.logger.info(f"出牌前有 {len(enemy_check)} 个敌方随从")
        except Exception as e:
            self.device_state.logger.warning(f"敌方随从检测失败: {str(e)}")
            enemy_check = []

        # 获取随从位置和类型
        screenshot = self.device_state.take_screenshot()
        if screenshot:
            our_followers_positions = self._scan_our_followers(screenshot)
            self.follower_manager.update_positions(our_followers_positions)
        

        # 进化/超进化条件判断：敌方有随从，或者我方绿色疾驰随从，或者有优先进化随从
        should_evolve = False
        
        # 检查敌方现在是否有随从
        screenshot = self.device_state.take_screenshot()
        if screenshot:
            enemy_followers = self._scan_enemy_ATK(screenshot)
            if enemy_followers and (self.device_state.evolution_point > 0 or self.device_state.super_evolution_point > 0):
                should_evolve = True
                self.device_state.logger.info(f"检测到敌方随从，满足进化/超进化条件")
        
        # 检查我方是否有绿色疾驰随从
        if not should_evolve:
            our_followers = self.follower_manager.get_positions()
            green_followers = [f for f in our_followers if f[2] == "green"]
            if green_followers and (self.device_state.evolution_point > 0 or self.device_state.super_evolution_point > 0):
                should_evolve = True
                self.device_state.logger.info(f"检测到我方疾驰随从，满足进化/超进化条件")
        
        # 检查是否有优先进化随从
        if not should_evolve:
            our_followers = self.follower_manager.get_positions()
            for follower in our_followers:
                follower_name = follower[3] if len(follower) > 3 else None
                if follower_name and is_evolve_priority_card(follower_name) and (self.device_state.evolution_point > 0 or self.device_state.super_evolution_point > 0):
                    should_evolve = True
                    self.device_state.logger.info(f"检测到优先进化随从[{follower_name}]，满足进化/超进化条件")
                    break
        
        if (self.device_state.evolution_point > 0 or self.device_state.super_evolution_point > 0) and should_evolve:
            self.perform_evolution_actions()
            # 等待最终进化/超进化动画完成
            time.sleep(3)
            # 点击空白处关闭面板
            from src.config.game_constants import BLANK_CLICK_POSITION, BLANK_CLICK_RANDOM
            self.device_state.u2_device.click(
                BLANK_CLICK_POSITION[0] + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM),
                BLANK_CLICK_POSITION[1] + random.randint(-BLANK_CLICK_RANDOM, BLANK_CLICK_RANDOM)
            )
            time.sleep(1)

            # 获取进化/超进化后的随从位置和类型
            screenshot = self.device_state.take_screenshot()
            if screenshot:
                our_followers_positions = self._scan_our_followers(screenshot)
                self.follower_manager.update_positions(our_followers_positions)


        # 检查是否有疾驰或突进随从
        can_attack_followers = self.follower_manager.get_positions()
        can_attack_followers = [f for f in can_attack_followers if f[2] in ['green', 'yellow']]

        if can_attack_followers:
            self.perform_follower_attacks(enemy_check)
        else:
            self.device_state.logger.info("未检测到可进行攻击的随从，跳过攻击操作")

        time.sleep(1)


    def _play_cards(self, image):
        """改进的出牌策略：每出一张牌都重新检测手牌，最多重试展牌次数为当前回合数"""
        # 获取当前回合可用费用
        current_round = self.device_state.current_round_count
        available_cost = min(10, current_round)  # 基础费用 = 当前回合数（最大10）
        
        # 检测手牌中是否有shield随从，如果有则跳过出牌阶段
        # if self.hand_manager.recognize_hand_shield_card():
        #     self.device_state.logger.warning("检测到护盾卡牌，跳过出牌阶段")
        #     return
        
        # 第一回合检查是否有额外费用点
        if current_round == 1 and self.device_state.extra_cost_available_this_match is None:
            extra_point = self._detect_extra_cost_point(image)
            if extra_point:
                self.device_state.extra_cost_available_this_match = True
                self.device_state.logger.info("本局为后手，有额外费用点")
            else:
                self.device_state.extra_cost_available_this_match = False
                self.device_state.logger.info("本局为先手，没有额外费用点")
        
        # 检测额外费用点（1-5回合可用一次，6回合后可用一次，且本局有额外费用点功能）
        if self.device_state.extra_cost_available_this_match:
            
            # 检查是否有激活的额外费用点（费用没用完）
            if self.device_state.extra_cost_active and self.device_state.extra_cost_remaining_uses > 0:
                # 检查上一回合是否用完费用（如果没用完才能继续使用）
                if current_round > 1:
                    cost_unused = self.device_state.last_round_available_cost - self.device_state.last_round_cost_used
                    if cost_unused <= 0:
                        # 上一回合费用用完了，关闭激活状态
                        self.device_state.extra_cost_active = False
                        self.device_state.logger.info(f"上一回合费用已用完，关闭额外费用点激活状态")
                    else:
                        # 上一回合费用没用完，可以继续使用
                        extra_point = self._detect_extra_cost_point(image)
                        if extra_point:
                            x, y, confidence = extra_point
                            self.device_state.logger.info(f"点击额外费用点按钮")
                            self.device_state.u2_device.click(x, y)
                            time.sleep(0.2)
                            available_cost += 1  # 增加1点费用
                            self.device_state.extra_cost_remaining_uses -= 1
                            self.device_state.logger.info(f"使用激活的额外费用点，当前可用费用: {available_cost}")
                            
                            # 如果使用完了，关闭激活状态
                            if self.device_state.extra_cost_remaining_uses <= 0:
                                self.device_state.extra_cost_active = False
                                self.device_state.logger.info("额外费用点使用完毕，关闭激活状态")
                else:
                    # 第一回合，直接使用
                    extra_point = self._detect_extra_cost_point(image)
                    if extra_point:
                        x, y, confidence = extra_point
                        self.device_state.logger.info(f"点击额外费用点按钮")
                        self.device_state.u2_device.click(x, y)
                        time.sleep(0.1)
                        available_cost += 1  # 增加1点费用
                        self.device_state.extra_cost_remaining_uses -= 1
                        self.device_state.logger.info(f"使用激活的额外费用点，当前可用费用: {available_cost}")
                        
                        # 如果使用完了，关闭激活状态
                        if self.device_state.extra_cost_remaining_uses <= 0:
                            self.device_state.extra_cost_active = False
                            self.device_state.logger.info("额外费用点使用完毕，关闭激活状态")
            
            # 检查是否可以激活新的额外费用点
            else:
                # 检查1-5回合是否可以使用
                can_use_early = (current_round <= 5 and not self.device_state.extra_cost_used_early)
                
                # 检查6回合后是否可以使用
                can_use_late = (current_round >= 6 and not self.device_state.extra_cost_used_late)
                
                if can_use_early or can_use_late:
                    extra_point = self._detect_extra_cost_point(image)
                    if extra_point:
                        x, y, confidence = extra_point
                        self.device_state.logger.info(f"点击额外费用点按钮")
                        self.device_state.u2_device.click(x, y)
                        time.sleep(0.1)
                        available_cost += 1  # 增加1点费用
                        
                        # 激活额外费用点（每次激活只有1次使用机会）
                        self.device_state.extra_cost_active = True
                        self.device_state.extra_cost_remaining_uses = 1  # 每次激活只有1次使用机会 
                        
                        # 根据当前回合标记使用状态
                        if current_round <= 5:
                            self.device_state.extra_cost_used_early = True
                            self.device_state.logger.info(f"当前可用费用: {available_cost}")
                        else:
                            self.device_state.extra_cost_used_late = True
                            self.device_state.logger.info(f"当前可用费用: {available_cost}")
        
        # 改进的出牌逻辑：每出一张牌都重新检测手牌
        self._play_cards_with_retry(available_cost, current_round)

    def _play_cards_with_retry(self, available_cost, current_round):
        """出牌顺序：优先卡（特殊牌+高优先级牌，组内按优先级和费用从高到低）先出，然后普通牌按费用从高到低出。每次出牌都重新识别手牌。"""
        max_retry_attempts = 2  # 最多重试次数
        total_cost_used = 0
        retry_count = 0
        # 当前回合需要忽略的卡牌（如剑士的斩击在没有敌方随从时）
        self._current_round_ignored_cards = set()
        # 同名牌连续出牌计数器
        card_attempt_count = {}
        self.device_state.logger.info(f"当前回合：{current_round}，可用费用: {available_cost}")

        hand_manager = self.hand_manager
        # 1. 获取初始手牌
        cards = hand_manager.get_hand_cards_with_retry(max_retries=3)
        if not cards:
            self.device_state.logger.warning("未能识别到任何手牌")
            return

        from src.config.card_priorities import get_high_priority_cards, get_card_priority
        high_priority_cards_cfg = get_high_priority_cards()
        high_priority_names = set(high_priority_cards_cfg.keys())
        
        # 过滤掉当前回合需要忽略的卡牌
        filtered_cards = [c for c in cards if c.get('name', '') not in self._current_round_ignored_cards]
        
        # 高优先级卡牌
        priority_cards = [c for c in filtered_cards if c.get('name', '') in high_priority_names]
        # 普通卡牌
        normal_cards = [c for c in filtered_cards if c.get('name', '') not in high_priority_names]
        # 高优先级卡牌排序：先按priority（数字小优先），再按费用从高到低
        priority_cards.sort(key=lambda x: (get_card_priority(x.get('name', '')), -x.get('cost', 0)))
        # 普通卡牌按费用从高到低排序
        normal_cards.sort(key=lambda x: x.get('cost', 0), reverse=True)
        planned_cards = priority_cards + normal_cards

        remain_cost = available_cost
        while planned_cards and (remain_cost > 0 or any(c.get('cost', 0) == 0 for c in planned_cards)):
            # 先找能出的高优先级卡牌
            affordable_priority = [c for c in planned_cards if c.get('name', '') in high_priority_names and c.get('cost', 0) <= remain_cost]
            # 找普通0费卡牌
            normal_zero_cost = [c for c in planned_cards if c.get('name', '') not in high_priority_names and c.get('cost', 0) == 0]
            # 找能出的普通付费卡牌
            affordable_normal = [c for c in planned_cards if c.get('name', '') not in high_priority_names and c.get('cost', 0) > 0 and c.get('cost', 0) <= remain_cost]
            
            if not affordable_priority and not normal_zero_cost and not affordable_normal:
                break
                
            if affordable_priority:
                # 高优先级卡牌按priority和费用排序（priority小优先，费用高优先）
                affordable_priority.sort(key=lambda x: (get_card_priority(x.get('name', '')), -x.get('cost', 0)))
                card_to_play = affordable_priority[0]
                self.device_state.logger.info(f"检测到高优先级卡牌[{card_to_play.get('name', '未知')}]，优先打出")
            elif normal_zero_cost:
                # 普通0费卡牌优先于普通付费卡牌
                card_to_play = normal_zero_cost[0]
                self.device_state.logger.info(f"检测到普通0费卡牌[{card_to_play.get('name', '未知')}]，优先打出")
            elif affordable_normal:
                # 普通付费卡牌按费用从高到低排序（高费优先）
                affordable_normal.sort(key=lambda x: x.get('cost', 0), reverse=True)
                card_to_play = affordable_normal[0]
            name = card_to_play.get('name', '未知')
            cost = card_to_play.get('cost', 0)
            self.device_state.logger.info(f"打出卡牌: {name} (费用: {cost})")
            result = self._play_single_card(card_to_play)
            
            # 处理额外的费用奖励
            extra_cost_bonus = getattr(self, '_current_extra_cost_bonus', 0)
            if extra_cost_bonus > 0:
                remain_cost += extra_cost_bonus
                # 清除额外费用奖励，避免重复使用
                self._current_extra_cost_bonus = 0
            
            # 记录最后打出的卡牌名称，用于特殊逻辑判断
            self._last_played_card = name
            
            # 检查是否应该消耗费用
            should_not_consume_cost = getattr(self, '_should_not_consume_cost', False)
            if should_not_consume_cost:
                self.device_state.logger.info(f"出不了 {name}卡牌 ，不用消耗费用")
                # 清除不消耗费用的标记，避免影响后续卡牌
                self._should_not_consume_cost = False
            elif cost > 0:
                remain_cost -= cost
                total_cost_used += cost
            
            # 检查是否需要从手牌中移除
            should_remove_from_hand = getattr(self, '_should_remove_from_hand', False)
            if should_remove_from_hand:
                self.device_state.logger.info(f"出不了 {name} ，已加入当前回合忽略列表")
                # 将卡牌加入当前回合忽略列表
                self._current_round_ignored_cards.add(name)
                # 清除需要移除的标记，避免影响后续卡牌
                self._should_remove_from_hand = False
                # 从planned_cards中移除这张卡，避免重复处理
                planned_cards.remove(card_to_play)
                continue  # 跳过后续的手牌更新逻辑

            # 增加同名牌连续出牌计数
            card_attempt_count[name] = card_attempt_count.get(name, 0) + 1
            if card_attempt_count[name] >= 3:
                self.device_state.logger.warning(f"卡牌 {name} 连续出牌3次，加入当前回合忽略列表")
                self._current_round_ignored_cards.add(name)
                self._should_remove_from_hand = False
                # 从planned_cards中移除这张卡，避免重复处理
                planned_cards.remove(card_to_play)
                continue
            
            # 检查卡牌是否成功打出
            if not result:
                self.device_state.logger.info(f"卡牌 {name} 未成功打出，跳过后续逻辑")
                continue
            
            planned_cards.remove(card_to_play)
            if planned_cards and (remain_cost > 0 or any(c.get('cost', 0) == 0 for c in planned_cards)):
                time.sleep(0.2)
                #点击展牌位置
                self.device_state.u2_device.click(SHOW_CARDS_BUTTON[0] + random.randint(-2,2), SHOW_CARDS_BUTTON[1] + random.randint(-2,2))
                time.sleep(0.2)
                #移除手牌光标提高识别率
                self.device_state.u2_device.click(DEFAULT_ATTACK_TARGET[0] + random.randint(-2,2), DEFAULT_ATTACK_TARGET[1] + random.randint(-2,2))
                time.sleep(1)
                new_cards = hand_manager.get_hand_cards_with_retry(max_retries=2, silent=True)
                if new_cards:
                    card_info = []
                    for card in new_cards:
                        name = card.get('name', '未知')
                        cost = card.get('cost', 0)
                        center = card.get('center', (0, 0))
                        card_info.append(f"{cost}费_{name}({center[0]},{center[1]})")
                    self.device_state.logger.info(f"出牌后更新手牌状态与位置: {' | '.join(card_info)}")
                    
                    # 修正：重建planned_cards时包含所有新检测到的卡牌，而不仅仅是初始计划中的卡牌
                    # 这样可以处理新抽到的卡牌（如0费卡牌）
                    # 过滤掉当前回合需要忽略的卡牌
                    filtered_cards = [c for c in new_cards if c.get('name', '') not in self._current_round_ignored_cards]
                    planned_cards = filtered_cards
                    
                    # 重新应用优先级排序
                    high_priority_names = set(high_priority_cards_cfg.keys())
                    priority_cards = [c for c in planned_cards if c.get('name', '') in high_priority_names]
                    normal_cards = [c for c in planned_cards if c.get('name', '') not in high_priority_names]
                    priority_cards.sort(key=lambda x: (get_card_priority(x.get('name', '')), -x.get('cost', 0)))
                    normal_cards.sort(key=lambda x: x.get('cost', 0), reverse=True)
                    planned_cards = priority_cards + normal_cards
                if not new_cards:
                    if retry_count < max_retry_attempts:
                        self.device_state.logger.info(f"检测不到手牌，重新识别 ({retry_count + 1}/2)")
                        retry_count += 1
                        continue
                    else:
                        self.device_state.logger.info("达到最大重试次数，停止出牌")
                        break
                if not planned_cards or (not any(c.get('cost', 0) <= remain_cost for c in planned_cards) and not any(c.get('cost', 0) == 0 for c in planned_cards)):
                    break

        # 特殊逻辑：如果最后打出的是"诅咒派对"且费用用完，再扫描一次手牌
        if (total_cost_used == available_cost and 
            hasattr(self, '_last_played_card') and 
            self._last_played_card == "诅咒派对"):
            
            extra_cost = self._extra_scan_after_add_newcards(hand_manager, high_priority_cards_cfg,self._last_played_card)
            total_cost_used += extra_cost  # 添加额外扫描打出的费用

        if not hasattr(self.device_state, 'cost_history'):
            self.device_state.cost_history = []
        self.device_state.cost_history.append(total_cost_used)
        self.device_state.logger.info(f"本回合出牌完成，消耗{total_cost_used}费 (可用费用: {available_cost})")

    def _extra_scan_after_add_newcards(self, hand_manager, high_priority_cards_cfg,last_played_card):
        """用完费用后的额外扫描逻辑"""
        self.device_state.logger.info(f"检测到打出{last_played_card}用完费用，额外扫描一次手牌")
        time.sleep(0.2)
        # 点击展牌位置
        self.device_state.u2_device.click(SHOW_CARDS_BUTTON[0] + random.randint(-2,2), SHOW_CARDS_BUTTON[1] + random.randint(-2,2))
        time.sleep(0.2)
        #移除手牌光标提高识别率
        self.device_state.u2_device.click(DEFAULT_ATTACK_TARGET[0] + random.randint(-2,2), DEFAULT_ATTACK_TARGET[1] + random.randint(-2,2))
        time.sleep(1)
        
        new_cards = hand_manager.get_hand_cards_with_retry(max_retries=2, silent=True)
        if new_cards:
            card_info = []
            for card in new_cards:
                name = card.get('name', '未知')
                cost = card.get('cost', 0)
                center = card.get('center', (0, 0))
                card_info.append(f"{cost}费_{name}({center[0]},{center[1]})")
            self.device_state.logger.info(f"额外扫描手牌状态: {' | '.join(card_info)}")
            
            # 过滤掉当前回合需要忽略的卡牌
            filtered_cards = [c for c in new_cards if c.get('name', '') not in self._current_round_ignored_cards]
            
            # 查找0费卡牌
            zero_cost_cards = [c for c in filtered_cards if c.get('cost', 0) == 0]
            if zero_cost_cards:
                # 按优先级排序0费卡牌
                high_priority_names = set(high_priority_cards_cfg.keys())
                priority_zero = [c for c in zero_cost_cards if c.get('name', '') in high_priority_names]
                normal_zero = [c for c in zero_cost_cards if c.get('name', '') not in high_priority_names]
                priority_zero.sort(key=lambda x: (get_card_priority(x.get('name', '')), -x.get('cost', 0)))
                normal_zero.sort(key=lambda x: x.get('cost', 0), reverse=True)
                sorted_zero_cards = priority_zero + normal_zero
                
                # 打出第一个0费卡牌
                card_to_play = sorted_zero_cards[0]
                name = card_to_play.get('name', '未知')
                cost = card_to_play.get('cost', 0)
                self.device_state.logger.info(f"额外扫描发现0费卡牌，打出: {name} (费用: {cost})")
                self._play_single_card(card_to_play)
                # 记录最后打出的卡牌名称
                self._last_played_card = name
                return cost  # 返回打出的费用
            else:
                self.device_state.logger.info("额外扫描未发现0费卡牌，进行第二次扫描")
                # 第二次扫描
                time.sleep(0.5)
                # 再次点击展牌位置
                self.device_state.u2_device.click(SHOW_CARDS_BUTTON[0] + random.randint(-2,2), SHOW_CARDS_BUTTON[1] + random.randint(-2,2))
                time.sleep(0.2)
                #移除手牌光标提高识别率
                self.device_state.u2_device.click(DEFAULT_ATTACK_TARGET[0] + random.randint(-2,2), DEFAULT_ATTACK_TARGET[1] + random.randint(-2,2))
                time.sleep(1)
                
                new_cards = hand_manager.get_hand_cards_with_retry(max_retries=3, silent=True)
                if new_cards:
                    card_info = []
                    for card in new_cards:
                        name = card.get('name', '未知')
                        cost = card.get('cost', 0)
                        center = card.get('center', (0, 0))
                        card_info.append(f"{cost}费_{name}({center[0]},{center[1]})")
                    self.device_state.logger.info(f"第二次额外扫描手牌状态: {' | '.join(card_info)}")
                    
                    # 过滤掉当前回合需要忽略的卡牌
                    filtered_cards = [c for c in new_cards if c.get('name', '') not in self._current_round_ignored_cards]
                    
                    # 查找0费卡牌
                    zero_cost_cards = [c for c in filtered_cards if c.get('cost', 0) == 0]
                    if zero_cost_cards:
                        # 按优先级排序0费卡牌
                        high_priority_names = set(high_priority_cards_cfg.keys())
                        priority_zero = [c for c in zero_cost_cards if c.get('name', '') in high_priority_names]
                        normal_zero = [c for c in zero_cost_cards if c.get('name', '') not in high_priority_names]
                        priority_zero.sort(key=lambda x: (get_card_priority(x.get('name', '')), -x.get('cost', 0)))
                        normal_zero.sort(key=lambda x: x.get('cost', 0), reverse=True)
                        sorted_zero_cards = priority_zero + normal_zero
                        
                        # 打出第一个0费卡牌
                        card_to_play = sorted_zero_cards[0]
                        name = card_to_play.get('name', '未知')
                        cost = card_to_play.get('cost', 0)
                        self.device_state.logger.info(f"第二次额外扫描发现0费卡牌，打出: {name} (费用: {cost})")
                        self._play_single_card(card_to_play)
                        # 记录最后打出的卡牌名称
                        self._last_played_card = name
                        return cost  # 返回打出的费用
                    else:
                        self.device_state.logger.info("第二次额外扫描仍未发现0费卡牌")
                else:
                    self.device_state.logger.info("第二次额外扫描仍未检测到手牌")
        else:
            self.device_state.logger.info("额外扫描未检测到手牌，进行第二次扫描")
            # 第二次扫描
            time.sleep(0.2)
            # 再次点击展牌位置
            self.device_state.u2_device.click(SHOW_CARDS_BUTTON[0] + random.randint(-2,2), SHOW_CARDS_BUTTON[1] + random.randint(-2,2))
            time.sleep(0.2)
            #移除手牌光标提高识别率
            self.device_state.u2_device.click(DEFAULT_ATTACK_TARGET[0] + random.randint(-2,2), DEFAULT_ATTACK_TARGET[1] + random.randint(-2,2))
            time.sleep(1.5)
            
            new_cards = hand_manager.get_hand_cards_with_retry(max_retries=3, silent=True)
            if new_cards:
                card_info = []
                for card in new_cards:
                    name = card.get('name', '未知')
                    cost = card.get('cost', 0)
                    center = card.get('center', (0, 0))
                    card_info.append(f"{cost}费_{name}({center[0]},{center[1]})")
                self.device_state.logger.info(f"第二次额外扫描手牌状态: {' | '.join(card_info)}")
                
                # 过滤掉当前回合需要忽略的卡牌
                filtered_cards = [c for c in new_cards if c.get('name', '') not in self._current_round_ignored_cards]
                
                # 查找0费卡牌
                zero_cost_cards = [c for c in filtered_cards if c.get('cost', 0) == 0]
                if zero_cost_cards:
                    # 按优先级排序0费卡牌
                    high_priority_names = set(high_priority_cards_cfg.keys())
                    priority_zero = [c for c in zero_cost_cards if c.get('name', '') in high_priority_names]
                    normal_zero = [c for c in zero_cost_cards if c.get('name', '') not in high_priority_names]
                    priority_zero.sort(key=lambda x: (get_card_priority(x.get('name', '')), -x.get('cost', 0)))
                    normal_zero.sort(key=lambda x: x.get('cost', 0), reverse=True)
                    sorted_zero_cards = priority_zero + normal_zero
                    
                    # 打出第一个0费卡牌
                    card_to_play = sorted_zero_cards[0]
                    name = card_to_play.get('name', '未知')
                    cost = card_to_play.get('cost', 0)
                    self.device_state.logger.info(f"第二次额外扫描发现0费卡牌，打出: {name} (费用: {cost})")
                    self._play_single_card(card_to_play)
                    # 记录最后打出的卡牌名称
                    self._last_played_card = name
                    return cost  # 返回打出的费用
                else:
                    self.device_state.logger.info("第二次额外扫描仍未发现0费卡牌")
            else:
                self.device_state.logger.info("第二次额外扫描仍未检测到手牌")
        
        return 0  # 没有打出卡牌，返回0

    def _play_single_card(self, card):
        """打出单张牌"""
        from .card_play_special_actions import CardPlaySpecialActions
        card_play_actions = CardPlaySpecialActions(self.device_state)
        result = card_play_actions.play_single_card(card)
        
        # 处理额外的费用奖励
        extra_cost_bonus = getattr(card_play_actions, '_extra_cost_bonus', 0)
        if extra_cost_bonus > 0:
            self.device_state.logger.info(f"获得额外费用: +{extra_cost_bonus}")
            # 将额外费用奖励存储到实例变量中，供调用方使用
            self._current_extra_cost_bonus = extra_cost_bonus
        
        # 处理不消耗费用的特殊情况
        should_not_consume_cost = getattr(card_play_actions, '_should_not_consume_cost', False)
        if should_not_consume_cost:
            # 将不消耗费用的标记存储到实例变量中，供调用方使用
            self._should_not_consume_cost = True
        
        # 处理需要从手牌中移除的特殊情况
        should_remove_from_hand = getattr(card_play_actions, '_should_remove_from_hand', False)
        if should_remove_from_hand:
            # 将需要移除的标记存储到实例变量中，供调用方使用
            self._should_remove_from_hand = True
        
        return result




    def _detect_extra_cost_point(self, image):
        """检测额外费用点按钮"""
        try:
            # 使用template_manager中已经设置好的模板目录
            templates_dir = self.device_state.game_manager.template_manager.templates_dir
            template_path = f"{templates_dir}/point.png"
            
            if not os.path.exists(template_path):
                self.device_state.logger.debug(f"额外费用点模板不存在: {template_path}")
                return None
            
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is None:
                self.device_state.logger.debug("无法加载额外费用点模板")
                return None
            
            # 转换为灰度图
            gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # 模板匹配
            result = cv2.matchTemplate(gray_image, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            # 如果匹配度足够高且位置在y轴大于340的区域
            if max_val > 0.7:
                x, y = max_loc
                # 检查y轴位置是否大于340
                if y > 340:
                    self.device_state.logger.info(f"检测到额外费用点按钮")
                    return (x, y, max_val)
            
            return None
        except Exception as e:
            self.device_state.logger.error(f"检测额外费用点时出错: {str(e)}")
            return None

    def _detect_change_card(self, debug_flag=False):
        """换牌阶段检测高费卡并换牌 - 绿色费用区域模板+SSIM匹配"""
        try:
            screenshot = self.device_state.take_screenshot()
            #screenshot = self.device_state.u2_device.screenshot()
            if screenshot is None:
                self.device_state.logger.warning("无法获取截图")
                return False
            image = np.array(screenshot)
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            # 换牌区
            roi_x1, roi_y1, roi_x2, roi_y2 = 173, 404, 838, 452
            change_area = image[roi_y1:roi_y2, roi_x1:roi_x2]
            
            # 创建用于绘制的换牌区副本
            change_area_draw = change_area.copy()
            
            hsv = cv2.cvtColor(change_area, cv2.COLOR_BGR2HSV)
            lower_green = np.array([43, 85, 70])
            upper_green = np.array([54, 255, 255])
            mask = cv2.inRange(hsv, lower_green, upper_green)

            #形态学操作
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.erode(mask, kernel, iterations=1)

            # mask合并
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            card_infos = []
            
            config_manager = ConfigManager()
            change_card_cost_threshold = config_manager.get_change_card_cost_threshold()

            # 先收集所有卡牌信息
            for cnt in contours:
                rect = cv2.minAreaRect(cnt)
                (x, y), (w, h), angle = rect
                if 25 < w < 45:
                    center_x = int(x) + roi_x1
                    center_y = int(y) + roi_y1
                    card_roi = image[int(center_y - 13):int(center_y + 14), int(center_x - 10):int(center_x + 10)]
                    
                    # 新的费用识别方法：灰度+二值化+轮廓分割+SSIM匹配
                    cost, confidence = self._recognize_cost_with_contour_ssim(card_roi, self.device_state, debug_flag)
                    
                    card_infos.append({'center_x': center_x, 'center_y': center_y, 'cost': cost, 'confidence': confidence})
                    
                    # 在换牌区绘制中心点和最小外接矩形
                    local_x = int(x)
                    local_y = int(y)
                    cv2.circle(change_area_draw, (local_x, local_y), 5, (0, 0, 255), -1)  # 红色圆点
                    box = cv2.boxPoints(rect)
                    box = box.astype(int)
                    cv2.drawContours(change_area_draw, [box], 0, (0, 255, 0), 2)  # 绿色矩形框
                    cv2.putText(change_area_draw, f"{w:.1f}x{h:.1f}", (local_x, local_y-10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)  # 蓝色尺寸文字
                    
                    if debug_flag:
                        debug_cost_dir = "debug_cost"
                        if not os.path.exists(debug_cost_dir):
                            os.makedirs(debug_cost_dir)
                        roi_filename = f"change_card_{center_x}_{center_y}_{int(time.time()*1000)}.png"
                        roi_path = os.path.join(debug_cost_dir, roi_filename)
                        cv2.imwrite(roi_path, card_roi)
                        # self.device_state.logger.info(f"已保存卡牌ROI: {roi_filename}")
            
            # 按x坐标排序（从左到右）
            card_infos.sort(key=lambda x: x['center_x'])
            
            # 按从左到右的顺序执行换牌
            for card_info in card_infos:
                cost = card_info['cost']
                center_x = card_info['center_x']
                center_y = card_info['center_y']
                
                if cost > change_card_cost_threshold:
                    self.device_state.logger.info(f"检测到费用{cost}的卡牌，换牌")
                    human_like_drag(self.device_state.u2_device, center_x+66, 516, center_x+66,208, duration=random.uniform(*settings.get_human_like_drag_duration_range()))
            
            # 保存带有所有绿点的原图
            if debug_flag:
                # self.device_state.logger.info(f"开始保存换牌debug图片，检测到{len(card_infos)}张卡牌")
                debug_cost_dir = "debug_cost"
                if not os.path.exists(debug_cost_dir):
                    os.makedirs(debug_cost_dir)
                
                try:
                    # 保存原图上标记所有绿点的图
                    debug_img = image.copy()
                    for card_info in card_infos:
                        center_x = card_info['center_x']
                        center_y = card_info['center_y']
                        cost = card_info['cost']
                        cv2.circle(debug_img, (center_x, center_y), 8, (0, 255, 0), 2)
                    debug_img_path = os.path.join(debug_cost_dir, f"change_card_all_{int(time.time()*1000)}.png")
                    cv2.imwrite(debug_img_path, debug_img)
                    # self.device_state.logger.info(f"已保存原图debug: {debug_img_path}")
                    
                    # 保存换牌区上标记中心点和最小外接矩形的图
                    change_area_draw_path = os.path.join(debug_cost_dir, f"change_card_area_draw_{int(time.time()*1000)}.png")
                    cv2.imwrite(change_area_draw_path, change_area_draw)
                    # self.device_state.logger.info(f"已保存换牌区debug: {change_area_draw_path}")
                except Exception as e:
                    self.device_state.logger.error(f"保存换牌debug图片时出错: {str(e)}")
            
            return True
            
        except Exception as e:
            self.device_state.logger.error(f"换牌检测出错: {str(e)}")
            return False

    def _recognize_cost_with_contour_ssim(self, card_roi, device_state=None, debug_flag=False):
        """使用轮廓检测+SSIM相似度匹配识别费用数字"""
        try:
            # 截取数字区域（左上角）
            digit_roi = card_roi[0:27, 0:20]  # 高27，宽20
            
            # 灰度化
            gray_digit = cv2.cvtColor(digit_roi, cv2.COLOR_BGR2GRAY)
            
            # 二值化（阈值170）
            _, binary_digit = cv2.threshold(gray_digit, 170, 255, cv2.THRESH_BINARY)
            
            # 保存二值化后的完整数字区域（用于调试）
            if debug_flag and device_state and device_state.logger:
                debug_cost_dir = "debug_cost"
                if not os.path.exists(debug_cost_dir):
                    os.makedirs(debug_cost_dir)
                binary_filename = f"binary_digit_{int(time.time()*1000)}.png"
                binary_path = os.path.join(debug_cost_dir, binary_filename)
                cv2.imwrite(binary_path, binary_digit)
                # device_state.logger.info(f"已保存二值化数字区域: {binary_filename}")
            
            # 轮廓检测（用于获取数字边界信息，但不分割）
            contours, _ = cv2.findContours(binary_digit, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                if device_state and device_state.logger:
                    device_state.logger.debug("未检测到数字轮廓")
                return 0, 0.0
            
            # 筛选合适的轮廓（面积和尺寸过滤）
            valid_contours = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area > 20:  # 最小面积阈值
                    x, y, w, h = cv2.boundingRect(cnt)
                    if w > 3 and h > 5:  # 最小尺寸阈值
                        valid_contours.append((cnt, x, y, w, h))
            
            if not valid_contours:
                if device_state and device_state.logger:
                    device_state.logger.debug("未找到有效的数字轮廓")
                return 0, 0.0
            
            # 按x坐标排序（从左到右）
            valid_contours.sort(key=lambda x: x[1])
            
            # 记录轮廓信息（用于调试）
            if device_state and device_state.logger:
                for i, (cnt, x, y, w, h) in enumerate(valid_contours):
                    device_state.logger.debug(f"检测到轮廓{i+1}: 位置({x},{y}), 尺寸({w}x{h}), 面积: {cv2.contourArea(cnt):.1f}")
            
            # 直接对完整数字区域进行SSIM匹配（使用轮廓信息但不分割）
            best_cost, best_confidence = self._ssim_match_digit(binary_digit, device_state, debug_flag, 1)
            
            if device_state and device_state.logger:
                device_state.logger.debug(f"轮廓检测+SSIM匹配结果: {best_cost}, 置信度: {best_confidence:.3f}")
            
            return best_cost, best_confidence
            
        except Exception as e:
            if device_state and device_state.logger:
                device_state.logger.error(f"轮廓检测+SSIM识别出错: {str(e)}")
            return 0, 0.0

    def _ssim_match_digit(self, digit_roi, device_state=None, debug_flag=False, digit_index=1):
        """使用SSIM相似度匹配单个数字"""
        try:
            # 使用template_manager中已经设置好的模板目录
            templates_dir = self.device_state.game_manager.template_manager.templates_dir
            template_dir = f"{templates_dir}/cost_numbers"
            best_cost = 0
            best_ssim = 0.0
            best_template_path = ""
            
            for cost in range(10):  # 0-9
                # 加载该数字的模板
                template_paths = glob.glob(os.path.join(template_dir, f"{cost}_*.png"))
                if not template_paths:
                    continue
                
                for template_path in template_paths:
                    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
                    if template is None:
                        continue
                    
                    # 二值化模板
                    _, template_binary = cv2.threshold(template, 170, 255, cv2.THRESH_BINARY)
                    
                    # 调整模板大小以匹配目标
                    h, w = digit_roi.shape
                    template_resized = cv2.resize(template_binary, (w, h))
                    
                    # 计算SSIM相似度
                    ssim_score = self._calculate_ssim(digit_roi, template_resized)
                    
                    if ssim_score > best_ssim:
                        best_ssim = ssim_score
                        best_cost = cost
                        best_template_path = template_path
                    
                    # 保存匹配过程（用于调试）
                    if debug_flag and device_state and device_state.logger and ssim_score > 0.5:
                        debug_cost_dir = "debug_cost"
                        if not os.path.exists(debug_cost_dir):
                            os.makedirs(debug_cost_dir)
                        
                        # 保存模板匹配对比图
                        template_name = os.path.basename(template_path).split('.')[0]
                        comparison_filename = f"comparison_digit{digit_index}_cost{cost}_{template_name}_ssim{ssim_score:.3f}_{int(time.time()*1000)}.png"
                        comparison_path = os.path.join(debug_cost_dir, comparison_filename)
                        
                        # 创建对比图：原数字 | 模板 | 差异
                        h_roi, w_roi = digit_roi.shape
                        h_tpl, w_tpl = template_resized.shape
                        max_h = max(h_roi, h_tpl)
                        comparison_img = np.zeros((max_h, w_roi + w_tpl + 10), dtype=np.uint8)
                        
                        # 放置原数字
                        comparison_img[:h_roi, :w_roi] = digit_roi
                        # 放置模板
                        comparison_img[:h_tpl, w_roi+10:w_roi+10+w_tpl] = template_resized
                        
                        cv2.imwrite(comparison_path, comparison_img)
                        device_state.logger.debug(f"已保存匹配对比图: {comparison_filename}")
            
            # 保存最佳匹配结果
            if debug_flag and device_state and device_state.logger and best_ssim > 0:
                debug_cost_dir = "debug_cost"
                if not os.path.exists(debug_cost_dir):
                    os.makedirs(debug_cost_dir)
                
                best_template_name = os.path.basename(best_template_path).split('.')[0]
                best_match_filename = f"best_match_digit{digit_index}_cost{best_cost}_{best_template_name}_ssim{best_ssim:.3f}_{int(time.time()*1000)}.png"
                best_match_path = os.path.join(debug_cost_dir, best_match_filename)
                
                # 创建最佳匹配对比图
                h_roi, w_roi = digit_roi.shape
                best_template = cv2.imread(best_template_path, cv2.IMREAD_GRAYSCALE)
                _, best_template_binary = cv2.threshold(best_template, 170, 255, cv2.THRESH_BINARY)
                best_template_resized = cv2.resize(best_template_binary, (w_roi, h_roi))
                
                max_h = max(h_roi, best_template_resized.shape[0])
                best_comparison_img = np.zeros((max_h, w_roi + w_roi + 10), dtype=np.uint8)
                best_comparison_img[:h_roi, :w_roi] = digit_roi
                best_comparison_img[:h_roi, w_roi+10:w_roi*2+10] = best_template_resized
                
                cv2.imwrite(best_match_path, best_comparison_img)
                device_state.logger.info(f"已保存最佳匹配结果: {best_match_filename}")
            
            return best_cost, best_ssim
            
        except Exception as e:
            if device_state and device_state.logger:
                device_state.logger.error(f"SSIM匹配出错: {str(e)}")
            return 0, 0.0

    def _calculate_ssim(self, img1, img2):
        """计算两个图像的SSIM相似度"""
        try:
            # 确保两个图像都是uint8类型
            img1 = img1.astype(np.uint8)
            img2 = img2.astype(np.uint8)
            
            # 计算均值
            mu1 = np.mean(img1)
            mu2 = np.mean(img2)
            
            # 计算方差
            sigma1_sq = np.var(img1)
            sigma2_sq = np.var(img2)
            
            # 计算协方差
            sigma12 = np.mean((img1 - mu1) * (img2 - mu2))
            
            # SSIM参数
            C1 = (0.01 * 255) ** 2
            C2 = (0.03 * 255) ** 2
            
            # 计算SSIM
            numerator = (2 * mu1 * mu2 + C1) * (2 * sigma12 + C2)
            denominator = (mu1 ** 2 + mu2 ** 2 + C1) * (sigma1_sq + sigma2_sq + C2)
            
            if denominator == 0:
                return 0.0
            
            ssim = numerator / denominator
            return max(0.0, min(1.0, ssim))  # 确保结果在[0,1]范围内
            
        except Exception as e:
            return 0.0

    def _scan_enemy_followers(self, screenshot):
        """检测场上的敌方随从位置与血量"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_enemy_followers(screenshot)
        return []

    def _scan_our_followers(self, screenshot):
        """检测场上的我方随从位置和状态"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_our_followers(screenshot)
        return []

    def _scan_shield_targets(self):
        """扫描护盾"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_shield_targets()
        return []

    def _scan_enemy_ATK(self, screenshot):
        """扫描敌方攻击力"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.scan_enemy_ATK(screenshot)
        return []

    def _detect_evolution_button(self, screenshot):
        """检测进化按钮是否出现，彩色"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.template_manager.detect_evolution_button(screenshot)
        return None, 0

    def _detect_super_evolution_button(self, screenshot):
        """检测超进化按钮是否出现，彩色"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.template_manager.detect_super_evolution_button(screenshot)
        return None, 0

    def _load_evolution_template(self):
        """加载进化按钮模板"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.template_manager.load_evolution_template()
        return None

    def _load_super_evolution_template(self):
        """加载超进化按钮模板"""
        if hasattr(self.device_state, 'game_manager') and self.device_state.game_manager:
            return self.device_state.game_manager.template_manager.load_super_evolution_template()
        return None 

def human_like_drag(u2_device, x1, y1, x2, y2, duration=None):
    """用一次swipe实现拟人拖动，兼容 uiautomator2 设备，强制参数合法"""
    import random
    # 屏幕分辨率范围（如有需要可根据实际设备动态获取）
    SCREEN_WIDTH = 1280
    SCREEN_HEIGHT = 720
    
    def clamp(val, minv, maxv):
        try:
            val = float(val)
        except Exception:
            val = minv
        return max(minv, min(maxv, val))

    # 起点终点加微小扰动（减少扰动范围，提高稳定性）
    sx = clamp(x1, 0, SCREEN_WIDTH) + random.randint(-2, 2)
    sy = clamp(y1, 0, SCREEN_HEIGHT) + random.randint(-2, 2)
    ex = clamp(x2, 0, SCREEN_WIDTH) + random.randint(-2, 2)
    ey = clamp(y2, 0, SCREEN_HEIGHT) + random.randint(-2, 2)
    # 再次强制扰动后仍在屏幕内
    sx = clamp(sx, 0, SCREEN_WIDTH)
    sy = clamp(sy, 0, SCREEN_HEIGHT)
    ex = clamp(ex, 0, SCREEN_WIDTH)
    ey = clamp(ey, 0, SCREEN_HEIGHT)
    if duration is None:
        duration = random.uniform(*settings.get_human_like_drag_duration_range())
    else:
        try:
            duration = float(duration)
        except Exception:
            duration = 0.02
        duration = max(0.05, min(1.0, duration))  # 限制拖动时长在0.05~1秒
    u2_device.swipe(sx, sy, ex, ey, duration) 