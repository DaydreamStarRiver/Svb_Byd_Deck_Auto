"""
配置设置
包含默认配置、免责声明等常量
"""

import datetime
import json
import os

# ============================= 免责声明内容 =============================
DISCLAIMER = """
                ================================================
                |          软件使用免责声明与许可协议               |
                ================================================

一、免责声明
1. 本软件为免费开源项目，按"原样"提供，开发者不提供任何明示或暗示的担保。
2. 使用本软件的风险完全由用户自行承担，开发者对因使用或无法使用本软件导致的任何损失不承担责任。
3. 本软件不构成任何专业建议，用户应自行判断其适用性。

二、许可条款
1. 本软件基于[MIT许可证]开源，用户可自由使用、修改和分发。
2. 禁止任何形式的商业售卖行为，包括但不限于：
   - 出售软件副本或修改版本
   - 提供付费激活服务
   - 捆绑收费服务

三、用户义务
1. 用户承诺不将本软件用于任何非法用途。
2. 用户同意不逆向工程、反编译或试图获取源代码（已开源的除外）。

四、反诈骗声明
制作者从未也永远不会：
- 通过任何渠道要求付款
- 索取账号密码或支付信息

""".format(date=datetime.date.today().strftime("%Y-%m-%d"))

# ============================= 默认配置 =============================
DEFAULT_CONFIG = {
    "adb_port": 5037,
    "extra_templates_dir": "extra_templates",
    "auto_restart": {
        "enabled": True,
        "output_timeout": 300,  # 5分钟无输出超时（秒）
        "match_timeout": 1200    # 20分钟无新战斗超时（秒）
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
        "debug_mode": False
    },
    "templates": {
        "threshold": 0.85,
        "pyramid_levels": 2,
        "edge_thresholds": [50, 200]
    }
}

# ============================= 拖动相关配置 =============================
# 拖动总时间区间（秒），全局统一，(最小值, 最大值)
HUMAN_LIKE_DRAG_DURATION_RANGE_DEFAULT = (0.12, 0.16)

def get_human_like_drag_duration_range():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            val = config.get('game', {}).get('human_like_drag_duration_range', None)
            if (
                isinstance(val, list) and len(val) == 2 and
                isinstance(val[0], (int, float)) and isinstance(val[1], (int, float)) and
                0 < val[0] < val[1] < 10
            ):
                return tuple(val)
    except Exception:
        pass
    return HUMAN_LIKE_DRAG_DURATION_RANGE_DEFAULT 