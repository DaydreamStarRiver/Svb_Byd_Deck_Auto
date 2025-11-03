"""
常量管理器
统一管理游戏中的所有常量配置
"""

from typing import Dict, Any, Tuple, List
from src.config.game_constants import *


class ConstantsManager:
    """常量管理器类"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化常量管理器
        
        Args:
            config: 配置字典，如果为None则使用默认常量
        """
        self.config = config or {}
        self._load_constants()
    
    def _load_constants(self):
        """从配置文件加载常量，如果没有则使用默认值"""
        constants = self.config.get("constants", {})
        
        # 屏幕坐标和区域
        self.enemy_hp_region = tuple(constants.get("enemy_hp_region", ENEMY_HP_REGION))
        self.our_follower_region = tuple(constants.get("our_follower_region", OUR_FOLLOWER_REGION))
        self.our_hp_region = tuple(constants.get("our_hp_region", OUR_HP_REGION))
        
        # 偏移参数
        enemy_offset = constants.get("enemy_follower_offset", [ENEMY_FOLLOWER_OFFSET_X, ENEMY_FOLLOWER_OFFSET_Y])
        self.enemy_follower_offset_x = enemy_offset[0]
        self.enemy_follower_offset_y = enemy_offset[1]
        
        self.our_follower_y_adjust = constants.get("our_follower_y_adjust", OUR_FOLLOWER_Y_ADJUST)
        self.our_follower_y_random = constants.get("our_follower_y_random", OUR_FOLLOWER_Y_RANDOM)
        self.enemy_follower_y_adjust = constants.get("enemy_follower_y_adjust", ENEMY_FOLLOWER_Y_ADJUST)
        self.enemy_follower_y_random = constants.get("enemy_follower_y_random", ENEMY_FOLLOWER_Y_RANDOM)
        
        # 攻击目标
        default_target = constants.get("default_attack_target", DEFAULT_ATTACK_TARGET)
        self.default_attack_target = tuple(default_target)
        self.default_attack_random = constants.get("default_attack_random", DEFAULT_ATTACK_RANDOM)
        
        # OCR参数
        self.ocr_crop_size = constants.get("ocr_crop_size", OCR_CROP_SIZE)
        
        # 轮廓检测参数
        enemy_contour = constants.get("enemy_contour_params", {})
        self.enemy_contour_min_dim = enemy_contour.get("min_dim", ENEMY_CONTOUR_MIN_DIM)
        self.enemy_contour_min_area = enemy_contour.get("min_area", ENEMY_CONTOUR_MIN_AREA)
        self.enemy_contour_max_area = enemy_contour.get("max_area", ENEMY_CONTOUR_MAX_AREA)
        
        our_contour = constants.get("our_contour_params", {})
        self.our_contour_min_dim = our_contour.get("min_dim", OUR_CONTOUR_MIN_DIM)
        self.our_contour_max_dim = our_contour.get("max_dim", OUR_CONTOUR_MAX_DIM)
        self.our_contour_min_area = our_contour.get("min_area", OUR_CONTOUR_MIN_AREA)
        
        hp_contour = constants.get("hp_contour_params", {})
        self.hp_contour_min_dim = hp_contour.get("min_dim", HP_CONTOUR_MIN_DIM)
        self.hp_contour_max_dim = hp_contour.get("max_dim", HP_CONTOUR_MAX_DIM)
        self.hp_contour_min_area = hp_contour.get("min_area", HP_CONTOUR_MIN_AREA)
        
        self.morphology_kernel_size = constants.get("morphology_kernel_size", MORPHOLOGY_KERNEL_SIZE)
        
        # 费用识别参数
        cost_digit_size = constants.get("cost_digit_size", [COST_DIGIT_HEIGHT, COST_DIGIT_WIDTH])
        self.cost_digit_height = cost_digit_size[0]
        self.cost_digit_width = cost_digit_size[1]
        
        cost_range = constants.get("cost_range", [COST_MIN, COST_MAX])
        self.cost_min = cost_range[0]
        self.cost_max = cost_range[1]
        
        self.cost_confidence_threshold = constants.get("cost_confidence_threshold", COST_CONFIDENCE_THRESHOLD)
        self.default_hp_value = constants.get("default_hp_value", DEFAULT_HP_VALUE)
        
        # 图像处理参数
        edge_thresholds = constants.get("edge_thresholds", EDGE_THRESHOLDS)
        self.edge_thresholds = tuple(edge_thresholds)
        self.pyramid_levels = constants.get("pyramid_levels", PYRAMID_LEVELS)
        self.angle_range = constants.get("angle_range", ANGLE_RANGE)
        self.angle_steps = constants.get("angle_steps", ANGLE_STEPS)
        self.template_match_threshold = constants.get("template_match_threshold", TEMPLATE_MATCH_THRESHOLD)
        
        # 调试参数
        debug_params = constants.get("debug_params", {})
        self.debug_circle_radius = debug_params.get("circle_radius", DEBUG_CIRCLE_RADIUS)
        self.debug_line_thickness = debug_params.get("line_thickness", DEBUG_LINE_THICKNESS)
        self.debug_text_scale = debug_params.get("text_scale", DEBUG_TEXT_SCALE)
        self.debug_text_thickness = debug_params.get("text_thickness", DEBUG_TEXT_THICKNESS)
        
        # 游戏逻辑参数
        hand_area_roi = constants.get("hand_area_roi", HAND_AREA_ROI)
        self.hand_area_roi = hand_area_roi
        
        self.shield_detection_timeout = constants.get("shield_detection_timeout", SHIELD_DETECTION_TIMEOUT)
        
        position_random = constants.get("position_random_range", POSITION_RANDOM_RANGE)
        self.position_random_small = position_random.get("small", POSITION_RANDOM_RANGE["small"])
        self.position_random_medium = position_random.get("medium", POSITION_RANDOM_RANGE["medium"])
        self.position_random_large = position_random.get("large", POSITION_RANDOM_RANGE["large"])
        
        # 时间参数
        timeouts = constants.get("timeouts", TIMEOUTS)
        self.timeout_shield_detection = timeouts.get("shield_detection", TIMEOUTS["shield_detection"])
        self.timeout_template_match = timeouts.get("template_match", TIMEOUTS["template_match"])
        self.timeout_action_delay = timeouts.get("action_delay", TIMEOUTS["action_delay"])
        self.timeout_screenshot_delay = timeouts.get("screenshot_delay", TIMEOUTS["screenshot_delay"])
    
    def get_enemy_hp_region(self) -> Tuple[int, int, int, int]:
        """获取敌方血量检测区域"""
        return self.enemy_hp_region
    
    def get_our_follower_region(self) -> Tuple[int, int, int, int]:
        """获取我方随从检测区域"""
        return self.our_follower_region
    
    def get_our_hp_region(self) -> Tuple[int, int, int, int]:
        """获取我方血量检测区域"""
        return self.our_hp_region
    
    def get_enemy_follower_offset(self) -> Tuple[int, int]:
        """获取敌方随从偏移"""
        return (self.enemy_follower_offset_x, self.enemy_follower_offset_y)
    
    def get_default_attack_target(self) -> Tuple[int, int]:
        """获取默认攻击目标"""
        return self.default_attack_target
    
    def get_cost_digit_size(self) -> Tuple[int, int]:
        """获取费用数字区域大小"""
        return (self.cost_digit_height, self.cost_digit_width)
    
    def get_cost_range(self) -> Tuple[int, int]:
        """获取费用范围"""
        return (self.cost_min, self.cost_max)
    
    def get_edge_thresholds(self) -> Tuple[int, int]:
        """获取边缘检测阈值"""
        return self.edge_thresholds
    
    def get_angle_steps(self) -> List[float]:
        """获取角度扫描步长"""
        return self.angle_steps
    
    def get_hand_area_roi(self) -> Dict[str, int]:
        """获取手牌区域ROI"""
        return self.hand_area_roi
    
    def get_position_random_range(self, size: str = "medium") -> int:
        """获取位置随机偏移范围"""
        if size == "small":
            return self.position_random_small
        elif size == "large":
            return self.position_random_large
        else:
            return self.position_random_medium
    
    def get_timeout(self, timeout_type: str) -> float:
        """获取超时时间"""
        timeout_map = {
            "shield_detection": self.timeout_shield_detection,
            "template_match": self.timeout_template_match,
            "action_delay": self.timeout_action_delay,
            "screenshot_delay": self.timeout_screenshot_delay
        }
        return timeout_map.get(timeout_type, 1.0)
    
    def get_debug_color(self, color_name: str) -> Tuple[int, int, int]:
        """获取调试颜色"""
        return DEBUG_COLORS.get(color_name, (0, 255, 0))
    
    def get_template_path(self, path_type: str) -> str:
        """获取模板路径"""
        return TEMPLATE_PATHS.get(path_type, "")
    
    def get_debug_path(self, path_type: str) -> str:
        """获取调试路径"""
        return DEBUG_PATHS.get(path_type, "")
    
    def get_hsv_ranges(self) -> Dict[str, List[int]]:
        """获取HSV颜色范围"""
        return {
            "enemy_hp": ENEMY_HP_HSV,
            "our_follower": OUR_FOLLOWER_HSV
        }
    
    def get_resolution_params(self, resolution: str) -> Dict[str, Any]:
        """获取分辨率参数"""
        if resolution == "1080p":
            return RESOLUTION_1080P
        else:
            return RESOLUTION_720P 