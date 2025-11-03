"""
随从工具模块
提供随从数据查询和处理的工具函数
"""

from src.config.game_constants import FOLLOWER_DATA


def get_follower_info(follower_name):
    """
    获取指定随从的默认攻击力和血量信息
    
    Args:
        follower_name (str): 随从名称
        
    Returns:
        dict: 包含攻击力和血量的字典，如果未找到则返回None
    """
    return FOLLOWER_DATA.get(follower_name)


def get_follower_attack(follower_name):
    """
    获取指定随从的默认攻击力
    
    Args:
        follower_name (str): 随从名称
        
    Returns:
        int: 攻击力，如果未找到则返回0
    """
    info = get_follower_info(follower_name)
    return info["attack"] if info else 0


def get_follower_hp(follower_name):
    """
    获取指定随从的默认血量
    
    Args:
        follower_name (str): 随从名称
        
    Returns:
        int: 血量，如果未找到则返回0
    """
    info = get_follower_info(follower_name)
    return info["hp"] if info else 0


def get_all_followers():
    """
    获取所有随从的列表
    
    Returns:
        list: 所有随从名称的列表
    """
    return list(FOLLOWER_DATA.keys())


def get_followers_by_attack_range(min_attack, max_attack):
    """
    根据攻击力范围获取随从列表
    
    Args:
        min_attack (int): 最小攻击力
        max_attack (int): 最大攻击力
        
    Returns:
        list: 符合条件的随从名称列表
    """
    return [
        name for name, data in FOLLOWER_DATA.items()
        if min_attack <= data["attack"] <= max_attack
    ]


def get_followers_by_hp_range(min_hp, max_hp):
    """
    根据血量范围获取随从列表
    
    Args:
        min_hp (int): 最小血量
        max_hp (int): 最大血量
        
    Returns:
        list: 符合条件的随从名称列表
    """
    return [
        name for name, data in FOLLOWER_DATA.items()
        if min_hp <= data["hp"] <= max_hp
    ]


def is_follower_exists(follower_name):
    """
    检查随从是否存在
    
    Args:
        follower_name (str): 随从名称
        
    Returns:
        bool: 随从是否存在
    """
    return follower_name in FOLLOWER_DATA 