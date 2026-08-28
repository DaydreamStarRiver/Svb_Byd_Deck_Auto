"""
配置设置
包含默认配置、免责声明等常量
"""

import json
import logging

from src.config.paths import get_config_path
from src.config.io_guard import is_in_battle


logger = logging.getLogger(__name__)

# Maa 识别仍处于联调阶段。发布版本暂时隐藏入口，并统一沿用旧版识别；
# 待识别精度和运行库兼容性验证完成后，只需开启此开关即可恢复入口。
EXPERIMENTAL_MAA_RECOGNITION_ENABLED = False

# ============================= 免责声明内容 =============================
# 内容变更时递增版本号，使旧版同意状态失效并重新提示。
DISCLAIMER_VERSION = 1
DISCLAIMER_RISK_ITEMS = (
    "本工具仅供个人学习研究使用，严禁用于任何商业盈利目的。",
    "使用本工具可能违反游戏用户协议，并可能导致账号被封禁等严重后果。",
    "开发者不对使用本工具造成的任何损失承担法律责任。",
    "本工具免费发布，禁止任何形式倒卖。",
)
COMMUNITY_GROUPS = (
    ("工具交流群", "892100160"),
    ("工具交流群", "1070074638"),
    ("工具开发群", "883457604"),
)
DISCLAIMER = "\n".join(
    (
        "==================== 免责声明 ====================",
        *[f"{index}. {text}" for index, text in enumerate(DISCLAIMER_RISK_ITEMS, 1)],
        "",
        "交流与反馈",
        *[f"{label}：{number}" for label, number in COMMUNITY_GROUPS],
    )
)

# ============================= 默认配置 =============================
DEFAULT_CONFIG = {
    "adb_port": 5037,
    "extra_templates_dir": "extra_templates",
    "auto_restart": {
        "enabled": True,
        "stage_timeout": 300,   # 5分钟无新阶段超时（秒）
        "max_restarts": 3,       # 自动重启次数上限（再次触发则停脚本）
    },
    "run_settings": {
        "max_run_duration": 0,  # 脚本最大运行时长（秒），0表示不限制
        "target_wins": 0,  # 本次运行达到指定胜场后停止，0表示不限制
    },
    "recognition": {
        # 发布默认继续使用 legacy（EasyOCR + MNIST）。
        "backend": "legacy",
        "maa_model_dir": "models/maa_ocr",
        "maa_threshold": 0.3,
        "page_text_fallback": True,
    },
    "deck_rotation": {
        "enabled": False,
        "interval_matches": 5,
        "sequence": [1, 2, 3],
        # 九宫格游戏槽位 -> saved_decks 下的本地构筑文件。
        "slot_profiles": {},
        # 启动后首次到达可选卡组的结算页时，先同步到序列首项。
        "switch_on_start": True,
        # cycle=循环；once=执行一轮；random=从序列中随机选择且避免连续重复。
        "mode": "cycle",
        "failure_policy": "pause",
        "page_timeout_seconds": 8,
    },
    "devices": [
        {
            "name": "MuMu模拟器",
            "serial": "127.0.0.1:16384",
            "screenshot_deep_color": False,
            "is_global": False
        }
    ],
    "game": {
        "resolution": "720p",  # 支持的分辨率: 720p, 1080p
        "evolution_rounds": [5, 6, 7, 8, 9],  # 进化回合
        "evolution_rounds_with_extra_cost": [4, 5, 6, 7, 8],  # 有额外费用时的进化回合
        "max_follower_count": 5,  # 最大随从数量
        "cost_recognition": {
            "confidence_threshold": 0.6,
            "max_cost": 10,
            "min_cost": 0
        }
    },
    "ui": {
        "notification_enabled": True,
        "log_level": "INFO",
        "save_screenshots": False,
        "debug_mode": False,
        "custom_background": {
            "enabled": False,
            "path": "",
            "opacity": 22
        }
    },
    "templates": {
        "threshold": 0.85,
        "pyramid_levels": 2,
        "edge_thresholds": [50, 200]
    },
    # 策略结构默认不预填效果；档案结构预留给界面组合卡组与策略。
    "profiles": {
        "deck": {"name": "inline", "source": "config.json"},
        "strategy": {"name": "inline", "source": "config.json"},
    },
    "strategy": {
        "effects": {}
    },
}

# ============================= 拖动相关配置 =============================
# 拖动总时间区间（秒），全局统一，(最小值, 最大值)
HUMAN_LIKE_DRAG_DURATION_RANGE_DEFAULT = (0.12, 0.16)

# 可选的运行时配置注入，用于避免重复读取磁盘。
_runtime_config = None
_cached_drag_range = None
_warned_battle_fallback = False


def set_runtime_config(config):
    """注入运行时配置字典，例如 ``ConfigManager.config``。"""
    global _runtime_config
    _runtime_config = config


def _extract_drag_range(config):
    val = None
    try:
        val = config.get("game", {}).get("human_like_drag_duration_range", None)
    except Exception:
        val = None

    if (
        isinstance(val, list)
        and len(val) == 2
        and isinstance(val[0], (int, float))
        and isinstance(val[1], (int, float))
        and 0 < val[0] < val[1] < 10
    ):
        return (float(val[0]), float(val[1]))
    return None

def get_human_like_drag_duration_range():
    # 已注入配置时优先使用内存数据。
    if isinstance(_runtime_config, dict):
        return _extract_drag_range(_runtime_config) or HUMAN_LIKE_DRAG_DURATION_RANGE_DEFAULT

    # 对战热路径中禁止回退到磁盘读取。
    global _warned_battle_fallback
    if is_in_battle():
        if not _warned_battle_fallback:
            _warned_battle_fallback = True
            logger.warning(
                "[IO] battle context: runtime config not injected; "
                "using default drag range without disk read"
            )
        return HUMAN_LIKE_DRAG_DURATION_RANGE_DEFAULT

    global _cached_drag_range
    if _cached_drag_range is not None:
        return _cached_drag_range

    config_path = get_config_path()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            _cached_drag_range = _extract_drag_range(config) or HUMAN_LIKE_DRAG_DURATION_RANGE_DEFAULT
            return _cached_drag_range
    except Exception:
        _cached_drag_range = HUMAN_LIKE_DRAG_DURATION_RANGE_DEFAULT
        return _cached_drag_range
