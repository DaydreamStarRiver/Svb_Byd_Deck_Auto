import json
import os

"""
卡牌优先级配置
定义各种卡牌的使用优先级
"""

# 默认高优先级卡牌（在可用费用内优先使用）
DEFAULT_HIGH_PRIORITY_CARDS = {
    "蛇神之怒": {"priority": 3},
    "无极猎人阿拉加维": {"priority": 2},
    "命运黄昏奥丁": {"priority": 1},
    "怨灵": {"priority": 5}
}

# 默认进化优先卡牌（进化/超进化时优先考虑）
DEFAULT_EVOLVE_PRIORITY_CARDS = {
    "无极猎人阿拉加维": {"priority": 3},
    "婪魇维莉": {"priority": 2},
    "蝙蝠": {"priority": 4},
    "爽朗的天宫菲尔德亚": {"priority": 3}
}

def load_user_config():
    """加载用户配置文件，支持PyInstaller打包后的路径"""
    import sys
    
    # 尝试多种路径来找到config.json
    possible_paths = []
    
    # 1. 相对于当前文件的路径（开发环境）
    current_dir = os.path.dirname(__file__)
    possible_paths.append(os.path.join(current_dir, '../../config.json'))
    
    # 2. 相对于可执行文件的路径（PyInstaller打包后）
    if getattr(sys, 'frozen', False):
        # PyInstaller打包后的情况
        exe_dir = os.path.dirname(sys.executable)
        possible_paths.append(os.path.join(exe_dir, 'config.json'))
    
    # 3. 相对于工作目录的路径
    possible_paths.append('config.json')
    
    # 4. 相对于脚本运行目录的路径
    script_dir = os.getcwd()
    possible_paths.append(os.path.join(script_dir, 'config.json'))
    
    for config_path in possible_paths:
        config_path = os.path.abspath(config_path)
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    print(f"成功加载配置文件: {config_path}")
                    return config
            except Exception as e:
                print(f"加载配置文件失败 {config_path}: {e}")
                continue
    
    print("警告: 未找到config.json文件，使用默认配置")
    return {}

# 全局变量，用于缓存配置
_user_config = None
_HIGH_PRIORITY_CARDS = None
_EVOLVE_PRIORITY_CARDS = None

def reload_config():
    """重新加载配置文件"""
    global _user_config, _HIGH_PRIORITY_CARDS, _EVOLVE_PRIORITY_CARDS
    _user_config = load_user_config()
    _HIGH_PRIORITY_CARDS = _user_config.get('high_priority_cards', DEFAULT_HIGH_PRIORITY_CARDS)
    _EVOLVE_PRIORITY_CARDS = _user_config.get('evolve_priority_cards', DEFAULT_EVOLVE_PRIORITY_CARDS)
    print(f"重新加载配置完成，高优先级卡牌: {list(_HIGH_PRIORITY_CARDS.keys())}")
    print(f"重新加载配置完成，进化优先级卡牌: {list(_EVOLVE_PRIORITY_CARDS.keys())}")

# 初始化配置
reload_config()

def get_high_priority_cards():
    """获取高优先级卡牌列表"""
    return _HIGH_PRIORITY_CARDS

def get_special_cards():
    """获取特殊处理卡牌列表"""
    from src.game.card_play_special_actions import get_special_cards
    return get_special_cards()

def is_high_priority_card(card_name):
    """检查是否为高优先级卡牌"""
    return card_name in _HIGH_PRIORITY_CARDS

def is_special_card(card_name):
    """检查是否为特殊处理卡牌"""
    from src.game.card_play_special_actions import get_special_cards
    special_cards = get_special_cards()
    return card_name in special_cards

def get_card_priority(card_name):
    """获取卡牌优先级（数字越小优先级越高）"""
    if card_name in _HIGH_PRIORITY_CARDS:
        return _HIGH_PRIORITY_CARDS[card_name].get("priority", 999)
    return 999  # 默认低优先级

def get_card_info(card_name):
    """获取卡牌信息"""
    if card_name in _HIGH_PRIORITY_CARDS:
        return _HIGH_PRIORITY_CARDS[card_name]
    else:
        from src.game.card_play_special_actions import get_special_cards
        special_cards = get_special_cards()
        if card_name in special_cards:
            return special_cards[card_name]
    return None 

def get_evolve_priority_cards():
    """获取进化优先卡牌列表"""
    return _EVOLVE_PRIORITY_CARDS

def is_evolve_priority_card(card_name):
    """检查是否为进化优先卡牌"""
    return card_name in _EVOLVE_PRIORITY_CARDS 

def get_evolve_special_actions():
    """获取进化/超进化特殊操作卡牌列表"""
    from src.game.evolution_special_actions import get_evolve_special_actions
    return get_evolve_special_actions()

def is_evolve_special_action_card(card_name):
    """检查是否为进化/超进化特殊操作卡牌"""
    from src.game.evolution_special_actions import is_evolve_special_action_card
    return is_evolve_special_action_card(card_name)

def get_card_priority_pre_evolution(card_name):
    """
    获取卡牌在进化解锁前的优先级（数字越小优先级越高）
    用于：换牌阶段（回合0）和前期出牌（回合1-3/4）

    Args:
        card_name: 卡牌名称

    Returns:
        int: 优先级数字（越小优先级越高，默认999）
    """
    if card_name in _HIGH_PRIORITY_CARDS:
        cfg = _HIGH_PRIORITY_CARDS[card_name]
        # 优先读取新格式的 priority_pre_evolution
        if "priority_pre_evolution" in cfg:
            return cfg["priority_pre_evolution"]
        # 向后兼容：如果没有新字段，使用旧的 priority
        if "priority" in cfg:
            return cfg["priority"]
    return 999  # 默认低优先级

def get_card_priority_post_evolution(card_name):
    """
    获取卡牌在进化解锁后的优先级（数字越小优先级越高）
    用于：中后期出牌（回合4/5+，进化解锁后）

    Args:
        card_name: 卡牌名称

    Returns:
        int: 优先级数字（越小优先级越高，默认999）
    """
    if card_name in _HIGH_PRIORITY_CARDS:
        cfg = _HIGH_PRIORITY_CARDS[card_name]
        # 优先读取新格式的 priority_post_evolution
        if "priority_post_evolution" in cfg:
            return cfg["priority_post_evolution"]
        # 向后兼容：如果没有新字段，使用旧的 priority
        if "priority" in cfg:
            return cfg["priority"]
    return 999  # 默认低优先级

def is_evolution_unlocked(device_state):
    """
    判断当前回合进化是否已解锁

    Args:
        device_state: DeviceState 对象，包含回合数和先后手信息

    Returns:
        bool: True=进化已解锁，False=进化未解锁
    """
    # 如果还没检测到先后手，假定未解锁
    if device_state.extra_cost_available_this_match is None:
        return False

    # 后手（有额外费用点）：回合4开始进化解锁
    if device_state.extra_cost_available_this_match is True:
        return device_state.current_round_count >= 4

    # 先手（无额外费用点）：回合5开始进化解锁
    if device_state.extra_cost_available_this_match is False:
        return device_state.current_round_count >= 5

    return False