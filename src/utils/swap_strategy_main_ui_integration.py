"""
换牌策略与Main UI集成模块（已升级为SIFT识别）
提供在main_ui中使用增强换牌策略功能
"""

import logging

logger = logging.getLogger(__name__)


def execute_swap_strategy_in_game(game_actions_instance, target_cost: str = "4费档次") -> bool:
    """
    在游戏中执行换牌策略的完整流程（使用SIFT识别 + 增强策略）

    此函数已升级为使用SIFT特征识别卡牌，替代旧的HSV+SSIM费用检测方式。
    直接调用 GameActions._detect_change_card_sift() 方法。

    Args:
        game_actions_instance: GameActions类的实例
        target_cost: 目标费用档次策略名称（已弃用，从config.json读取）

    Returns:
        bool: 换牌操作是否成功执行

    注意:
        - target_cost 参数已弃用，策略从 config.json 的 card_replacement_strategy 读取
        - 如需临时修改策略，请修改 ConfigManager 的配置
    """
    try:
        logger.info(f"[换牌集成] 调用SIFT换牌方法")

        # 直接调用新的SIFT换牌方法
        # 策略会自动从 config.json 中读取
        # debug_flag 默认为 True，会保存调试图片到 debug_mulligan_sift/
        success = game_actions_instance._detect_change_card_sift()

        if success:
            logger.info("[换牌集成] SIFT换牌执行成功")
        else:
            logger.warning("[换牌集成] SIFT换牌执行失败")

        return success

    except Exception as e:
        logger.error(f"[换牌集成] 执行换牌策略时出错: {str(e)}")
        import traceback
        logger.error(f"[换牌集成] 错误详情:\n{traceback.format_exc()}")
        return False


def main_ui_integration_example():
    """
    在main_ui中集成换牌策略的示例代码

    这个函数提供了一个模板，展示如何在main_ui.py中使用新的SIFT换牌策略功能
    """
    # 以下是在main_ui.py中可以使用的代码示例
    '''
    # 1. 在main_ui.py的导入部分添加
    from src.utils.swap_strategy_main_ui_integration import execute_swap_strategy_in_game

    # 2. 在适当的位置（例如在开始游戏或换牌阶段的处理函数中）添加
    def handle_swap_phase(self):
        """处理换牌阶段"""
        # 直接调用，策略自动从config.json读取
        success = execute_swap_strategy_in_game(self.game_actions)

        if success:
            print("换牌策略执行成功")
        else:
            print("换牌策略执行失败")

    # 3. 或者创建一个按钮事件处理器
    def on_swap_strategy_button_clicked(self):
        """换牌按钮点击处理"""
        # 执行换牌策略（策略从配置文件读取）
        success = execute_swap_strategy_in_game(self.game_actions)

        # 更新UI状态
        if success:
            self.status_label.setText("SIFT换牌策略执行成功")
        else:
            self.status_label.setText("SIFT换牌策略执行失败")

    # 4. 修改策略（如需临时修改）
    def change_strategy_temp(self, new_strategy: str):
        """
        临时修改换牌策略

        Args:
            new_strategy: "3费档次" / "4费档次" / "5费档次"
        """
        from src.config.config_manager import ConfigManager

        config_manager = ConfigManager()
        # 注意：这只会影响当前运行时，不会保存到config.json
        config_manager.config["game"]["card_replacement_strategy"] = new_strategy

        print(f"策略已临时修改为: {new_strategy}")

        # 执行换牌
        execute_swap_strategy_in_game(self.game_actions)
    '''
    pass


# 向后兼容函数（已弃用）
def _get_card_infos_with_positions(game_actions_instance):
    """
    [已弃用] 获取带位置信息的卡牌数据

    此函数已被SIFT识别替代，仅保留用于向后兼容。
    新代码请使用 GameActions._detect_change_card_sift()

    Returns:
        空列表（已废弃功能）
    """
    logger.warning("[已弃用] _get_card_infos_with_positions 函数已废弃，请使用SIFT识别")
    return []
