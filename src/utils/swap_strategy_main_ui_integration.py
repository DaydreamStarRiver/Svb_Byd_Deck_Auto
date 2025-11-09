"""
换牌策略与Main UI集成示例
提供在main_ui中使用换牌策略功能的示例代码
"""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


def execute_swap_strategy_in_game(game_actions_instance, target_cost: str = "3费档次") -> bool:
    """
    在游戏中执行换牌策略的完整流程
    这个函数可以直接在main_ui中调用，用于执行换牌操作
    
    Args:
        game_actions_instance: GameActions类的实例
        target_cost: 目标费用档次策略名称，默认为"3费档次"
    
    Returns:
        bool: 换牌操作是否成功执行
    """
    try:
        import cv2
        import numpy as np
        import logging
        from typing import List, Dict
        
        logger = logging.getLogger(__name__)
        device_state = game_actions_instance.device_state
        
        # 1. 获取截图
        screenshot = device_state.take_screenshot()
        if screenshot is None:
            logger.warning("无法获取截图")
            return False
        
        image = np.array(screenshot)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        # 2. 使用game_actions中的方法获取手牌费用和位置信息
        # 换牌区ROI
        roi_x1, roi_y1, roi_x2, roi_y2 = 173, 404, 838, 452
        change_area = image[roi_y1:roi_y2, roi_x1:roi_x2]
        
        # 使用HSV颜色空间检测绿色费用区域
        hsv = cv2.cvtColor(change_area, cv2.COLOR_BGR2HSV)
        lower_green = np.array([43, 85, 70])
        upper_green = np.array([54, 255, 255])
        mask = cv2.inRange(hsv, lower_green, upper_green)
        
        # 形态学操作
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.erode(mask, kernel, iterations=1)
        
        # 查找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        card_infos = []
        
        # 收集所有卡牌信息
        for cnt in contours:
            rect = cv2.minAreaRect(cnt)
            (x, y), (w, h), angle = rect
            if 25 < w < 45:
                center_x = int(x) + roi_x1
                center_y = int(y) + roi_y1
                card_roi = image[int(center_y - 13):int(center_y + 14), int(center_x - 10):int(center_x + 10)]
                
                # 使用game_actions中的费用识别方法
                cost, confidence = game_actions_instance._recognize_cost_with_contour_ssim(card_roi, device_state)
                
                if cost is not None:
                    card_infos.append({
                        'center_x': center_x,
                        'center_y': center_y,
                        'cost': cost,
                        'confidence': confidence
                    })
        
        # 按x坐标排序（从左到右）
        card_infos.sort(key=lambda x: x['center_x'])
        
        # 确保不超过4张手牌
        card_infos = card_infos[:4]
        
        if not card_infos:
            logger.warning("未能识别到卡牌信息")
            return False
        
        # 3. 从卡牌信息中提取费用列表
        hand_costs = [card['cost'] for card in card_infos]
        
        # 4. 确定换牌策略
        from .card_swap_strategy import determine_card_swaps
        # 直接使用策略名称
        keep_indices, swap_indices = determine_card_swaps(hand_costs, target_cost)
        
        logger.info(f"手牌费用: {hand_costs}")
        logger.info(f"保留卡牌索引: {keep_indices}")
        logger.info(f"更换卡牌索引: {swap_indices}")
        
        # 5. 如果需要换牌，执行换牌操作
        if swap_indices:
            # 执行换牌操作
            from .card_swap_strategy import execute_card_swaps
            return execute_card_swaps(game_actions_instance, swap_indices, card_infos)
        else:
            logger.info("无需换牌，当前手牌已经满足策略要求")
            return True
            
    except Exception as e:
        logger.error(f"执行换牌策略时出错: {str(e)}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return False


def _get_card_infos_with_positions(game_actions_instance) -> List[Dict]:
    """
    获取带位置信息的卡牌数据
    这是一个辅助函数，用于获取卡牌的位置和费用信息
    
    Args:
        game_actions_instance: GameActions类的实例
    
    Returns:
        List[Dict]: 包含卡牌位置和费用信息的列表
    """
    try:
        import cv2
        import numpy as np
        
        # 从GameActions实例获取device_state
        device_state = game_actions_instance.device_state
        
        # 获取截图
        screenshot = device_state.take_screenshot()
        if screenshot is None:
            logger.warning("无法获取截图")
            return []
        
        # 转换为BGR格式
        image = np.array(screenshot)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        # 换牌区ROI
        roi_x1, roi_y1, roi_x2, roi_y2 = 173, 404, 838, 452
        change_area = image[roi_y1:roi_y2, roi_x1:roi_x2]
        
        # 转换为HSV颜色空间以检测绿色费用区域
        hsv = cv2.cvtColor(change_area, cv2.COLOR_BGR2HSV)
        lower_green = np.array([43, 85, 70])
        upper_green = np.array([54, 255, 255])
        mask = cv2.inRange(hsv, lower_green, upper_green)
        
        # 形态学操作
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.erode(mask, kernel, iterations=1)
        
        # 寻找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        card_infos = []
        
        # 收集所有卡牌信息
        for cnt in contours:
            rect = cv2.minAreaRect(cnt)
            (x, y), (w, h), angle = rect
            if 25 < w < 45:  # 过滤合适大小的轮廓
                center_x = int(x) + roi_x1
                center_y = int(y) + roi_y1
                # 截取卡牌费用区域
                card_roi = image[int(center_y - 13):int(center_y + 14), int(center_x - 10):int(center_x + 10)]
                
                # 使用GameActions实例的_recognize_cost_with_contour_ssim方法识别费用
                cost, confidence = game_actions_instance._recognize_cost_with_contour_ssim(card_roi, device_state)
                
                # 只保留置信度较高的结果
                if confidence > 0.6:
                    card_infos.append({
                        'center_x': center_x,
                        'center_y': center_y,
                        'cost': cost,
                        'confidence': confidence
                    })
        
        # 按x坐标排序（从左到右）
        card_infos.sort(key=lambda x: x['center_x'])
        
        return card_infos
        
    except Exception as e:
        logger.error(f"获取卡牌位置信息时出错: {str(e)}")
        return []


def main_ui_integration_example():
    """
    在main_ui中集成换牌策略的示例代码
    这个函数提供了一个模板，展示如何在main_ui.py中使用换牌策略功能
    """
    # 以下是在main_ui.py中可以使用的代码示例
    '''
    # 1. 在main_ui.py的导入部分添加
    from src.utils import execute_swap_strategy_in_game
    
    # 2. 在适当的位置（例如在开始游戏或换牌阶段的处理函数中）添加
    def handle_swap_phase(self):
        # 假设self.game_actions是GameActions的实例
        # 参数1: game_actions实例
        # 参数2: 目标费用档次（可选，默认为3）
        success = execute_swap_strategy_in_game(self.game_actions, target_cost=4)
        
        if success:
            print("换牌策略执行成功")
        else:
            print("换牌策略执行失败")
    
    # 3. 或者创建一个按钮事件处理器
    def on_swap_strategy_button_clicked(self):
        # 获取用户选择的费用档次（例如从UI控件中获取）
        target_cost = self.swap_strategy_combo.currentText()  # 假设返回"3费档次"、"4费档次"或"5费档次"
        
        # 执行换牌策略
        success = execute_swap_strategy_in_game(self.game_actions, target_cost)
        
        # 更新UI状态
        if success:
            self.status_label.setText(f"换牌策略执行成功，目标费用档次: {target_cost}")
        else:
            self.status_label.setText("换牌策略执行失败")
    '''
    pass