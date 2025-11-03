from typing import List, Tuple, Optional
import random


class FollowerManager:
    """随从管理器，用于管理我方和敌方随从的位置信息"""
    
    def __init__(self):
        self.positions: List[Tuple[int, int, str, str]] = []
        self.enemy_positions: List[Tuple[int, int, str, str]] = []
    
    def update_positions(self, positions: List[Tuple[int, int, str, str]]):
        """更新我方随从位置"""
        self.positions = positions
    
    def get_positions(self) -> List[Tuple[int, int, str, str]]:
        """获取我方随从位置"""
        return self.positions
    
    def get_count(self) -> int:
        """获取我方随从数量"""
        return len(self.positions)
    
    def get_by_type(self, follower_type: str) -> List[Tuple[int, int]]:
        """根据类型获取随从位置"""
        return [(x, y) for x, y, ftype, _ in self.positions if ftype == follower_type]
    
    def update_enemy_positions(self, enemy_positions: List[Tuple[int, int, str, str]]):
        """更新敌方随从位置"""
        self.enemy_positions = enemy_positions
    
    def get_enemy_positions(self) -> List[Tuple[int, int, str, str]]:
        """获取敌方随从位置"""
        return self.enemy_positions 