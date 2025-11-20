"""
实用工具模块
提供各种辅助功能，包括GPU检测、资源管理、换牌策略等
"""

from .consent_utils import *
from .gpu_utils import *
from .hp_detection import *
from .mnist_preprocessor import *
from .resource_utils import *
from .swap_strategy_main_ui_integration import execute_swap_strategy_in_game

__all__ = [
    # consent_utils
    'check_consent',
    'get_consent_template_path',
    # gpu_utils
    'check_gpu',
    # hp_detection
    'detect_hp',
    # mnist_preprocessor
    'preprocess_mnist_image',
    # resource_utils
    'get_resource_path',
    # swap_strategy_main_ui_integration
    'execute_swap_strategy_in_game',
]