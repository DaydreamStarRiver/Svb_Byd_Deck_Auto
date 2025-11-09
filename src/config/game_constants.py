"""
游戏常量配置文件
包含所有硬编码的数值，便于统一管理和调整
"""

# ============================= 屏幕坐标和区域 =============================

# 敌方随从血量检测区域 (左上角x, 左上角y, 右下角x, 右下角y)
# Updated for improved sliding window detection
ENEMY_HP_REGION = (322, 263, 1073, 302)
ENEMY_HP_REGION_UP = (322, 250, 1073, 289)

# 敌方随从攻击力检测区域 (左上角x, 左上角y, 右下角x, 右下角y)
ENEMY_ATK_REGION = (263, 297, 1015, 307)

# 我方随从检测区域
OUR_FOLLOWER_REGION = (176, 307, 1064, 334)  # 疾驰/突进随从区域
OUR_ATK_REGION = (263, 466, 1015, 480)  # 我方随从血量区域
OUR_HP_REGION = (263, 466, 1015, 480)

# 敌方护盾检测区域 (左上角x, 左上角y, 右下角x, 右下角y)
ENEMY_SHIELD_REGION = (164, 136, 1096, 228)

# 敌方随从位置偏移
ENEMY_FOLLOWER_OFFSET_X = -50  # 从血量中心到随从中心的X偏移
ENEMY_FOLLOWER_OFFSET_Y = -70  # 从血量中心到随从中心的Y偏移
ENEMY_HP_REGION_OFFSET_X = 249  # 敌方血量区域X偏移
ENEMY_HP_REGION_OFFSET_Y = 249  # 敌方血量区域Y偏移

# 我方随从位置调整
OUR_FOLLOWER_Y_ADJUST = 399  # 我方随从Y坐标基准
OUR_FOLLOWER_Y_RANDOM = 2    # Y坐标随机偏移范围
ENEMY_FOLLOWER_Y_ADJUST = 228  # 敌方随从Y坐标基准
ENEMY_FOLLOWER_Y_RANDOM = 5    # Y坐标随机偏移范围

# 默认攻击目标位置（敌方玩家）
DEFAULT_ATTACK_TARGET = (646, 64)
DEFAULT_ATTACK_RANDOM = 3  # 随机偏移范围

# 展牌按钮位置
SHOW_CARDS_BUTTON = (914, 669)
SHOW_CARDS_RANDOM_X = (-3, 2)  # X轴随机偏移范围
SHOW_CARDS_RANDOM_Y = (-4, 5)   # Y轴随机偏移范围

# 点击空白处位置（关闭面板）
BLANK_CLICK_POSITION = (27, 570)
BLANK_CLICK_RANDOM = 2  # 随机偏移范围

# OCR识别区域大小
OCR_CROP_SIZE = 45  # 用于血量识别的裁剪区域大小
OCR_CROP_HALF_SIZE = OCR_CROP_SIZE // 2  # 裁剪区域的一半大小

# ============================= HP Detection - Sliding Window Parameters =============================

# 滑动窗口参数
HP_WINDOW_WIDTH = 43        # 窗口宽度
HP_WINDOW_HEIGHT = 39       # 窗口高度
HP_SLIDE_STEP = 1           # 滑动步长
HP_MIN_FOLLOWER_GAP = 105   # 随从之间最小间隔
HP_MAX_FOLLOWERS = 5        # 最大随从数量

# 颜色检测阈值
HP_RED_BG_THRESHOLD = 0.26      # 红色背景阈值 >= 26%
HP_OTHER_THRESHOLD = 0.25       # 噪声阈值 < 25%
HP_DIGIT_THRESHOLD = 0.06       # 数字像素阈值 >= 6%
HP_BRIGHT_RED_V_THRESHOLD = 210 # 亮红色V值阈值 (HSV中的V分量，用于区分数字和背景)

# ============================= HSV颜色范围 =============================

# 敌方随从血量颜色（红色）
ENEMY_HP_HSV = {
    "red": [0, 111, 0, 7, 207, 255]
}

ENEMY_ATK_HSV = {
    "blue": [87, 124, 84, 120, 255, 255]
}

# 我方随从状态颜色
OUR_FOLLOWER_HSV = {
    "yellow1": [20, 133, 21, 26, 245, 255],  # 第一个黄色范围,小的
    "yellow2": [20, 56, 22, 29, 175, 255],   # 第二个黄色范围(匹配超进化的大框)
    "green": [32, 86, 62, 82, 255, 255],     # 绿色光框（可攻击敌方玩家或随从）
    "green2": [30, 60, 80, 90, 200, 255],    # 第二个绿色范围(匹配黏在一起的超进化疾驰)
    "blue": [87, 124, 84, 120, 255, 255],    # 蓝色血量
}


# ============================= 轮廓检测参数 =============================

# 敌方随从轮廓检测
ENEMY_CONTOUR_MIN_DIM = 15      # 最小尺寸
ENEMY_CONTOUR_MIN_AREA = 300    # 最小面积
ENEMY_CONTOUR_MAX_AREA = 5000   # 最大面积

# 我方随从轮廓检测
OUR_CONTOUR_MIN_DIM = 100       # 最小尺寸
OUR_CONTOUR_MAX_DIM = 300       # 最大尺寸
OUR_CONTOUR_MIN_AREA = 1000     # 最小面积

# 血量轮廓检测
HP_CONTOUR_MIN_DIM = 100        # 最小尺寸
HP_CONTOUR_MAX_DIM = 300        # 最大尺寸
HP_CONTOUR_MIN_AREA = 1200      # 最小面积

# 形态学操作核大小
MORPHOLOGY_KERNEL_SIZE = 4

# ============================= 费用识别参数 =============================

# 费用识别相关常量
COST_CONFIDENCE_THRESHOLD = 0.6  # 费用识别的置信度阈值
COST_MIN = 1                     # 最小费用
COST_MAX = 10                    # 最大费用
COST_DIGIT_HEIGHT = 27           # 费用数字高度
COST_DIGIT_WIDTH = 20            # 费用数字宽度

# 费用识别失败时的默认值
DEFAULT_HP_VALUE = "99"  # OCR识别失败时的默认血量值

# ============================= 图像处理参数 =============================

# 边缘检测阈值
EDGE_THRESHOLDS = (50, 200)

# 金字塔层数

# ============================= Shield随从列表 =============================

# 手牌检测到下面卡牌名称，停止出牌
SHIELD_FOLLOWER_NAMES = [
    "丰丽的玫瑰皇后",
    "云海龙骑兵",
    "交响之心枷薇",
    "兽性铁人",
    "卓越的鲁米那斯法师",
    "叮当天使莉亚",
    "圣盾祭司",
    "大地守护神米维",
    "天之守护神埃忒耳",
    "女仆天使切蕾塔",
    "怪奇探索者尤娜",
    "惊涛龙骑士扎哈尔",
    "战斧屠龙者",
    "无畏的副团长格尔德",
    "水之守护神萨蕾法",
    "流动堕落的冥河凯伦",
    "激震的歌利亚",
    "热情的精灵莱昂内尔",
    "煌刃勇者阿玛利亚",
    "燃烧魔剑欧特鲁斯",
    "爱之骑士尹安",
    "玛纳利亚剑士欧文",
    "疯狂的创造者历亚姆",
    "神圣守护",
    "神圣狮鹫",
    "粉碎的圣职者",
    "纯白圣女贞德",
    "纯洁白狐",
    "苍诲的制裁尼普顿",
    "治愈的修女",
    "起源剑师阿玛兹",
    "闪光魔法剑士",
    "霜寒冰晶艾琳",
    "飓风天业格里姆尼尔",
    "魔钢骑兵",
    "鸣咽的圣骑士维尔伯特",
    "双面魔女蕾米拉米",
    "黎明炼金术师诺诺",
    "五行之巅久苑",
    "玛纳利亚密友安古蕾雅",
    "抗拒叹息之人",
    "安息的肯定者",
    "安息的祈祷者",
    "海洋骑手",
    "破坏的继承者阿克西娅",
    "破坏的肯定者",
    "侮蔑的祈祷者",
    "混融的团姐者",
    "不弑的团结者",
    "侮蔑的继承者安吉拉弗利特"
]
PYRAMID_LEVELS = 2

# 角度匹配参数
ANGLE_RANGE = 30        # 角度搜索范围
ANGLE_STEPS = [5.0, 1.0, 0.2]  # 三级角度扫描步长

# 模板匹配阈值
TEMPLATE_MATCH_THRESHOLD = 0.85

# ============================= 调试参数 =============================

# 调试绘制参数
DEBUG_CIRCLE_RADIUS = 5
DEBUG_LINE_THICKNESS = 2
DEBUG_TEXT_SCALE = 0.5
DEBUG_TEXT_THICKNESS = 1

# 调试颜色 (BGR格式)
DEBUG_COLORS = {
    "green": (0, 255, 0),
    "red": (0, 0, 255),
    "blue": (255, 0, 0),
    "yellow": (0, 255, 255),
    "cyan": (255, 255, 0)
}

# ============================= 游戏逻辑参数 =============================

# 手牌区域参数
HAND_AREA_ROI = {
    "x1": 291,
    "y1": 602,
    "x2": 815,
    "y2": 430
}

# 护盾检测参数
SHIELD_DETECTION_TIMEOUT = 1.0  # 护盾检测超时时间

# 随机偏移范围
POSITION_RANDOM_RANGE = {
    "small": 2,    # 小范围随机偏移
    "medium": 3,   # 中等范围随机偏移
    "large": 5     # 大范围随机偏移
}

# ============================= 分辨率相关参数 =============================

# 720p分辨率参数
RESOLUTION_720P = {
    "width": 1280,
    "height": 720,
    "scale_factor": 1.0
}


# ============================= 时间参数 =============================

# 各种超时时间（秒）
TIMEOUTS = {
    "shield_detection": 1.0,    # 护盾检测超时
    "template_match": 0.5,      # 模板匹配超时
    "action_delay": 0.1,        # 动作间隔延迟
    "screenshot_delay": 0.05,   # 截图延迟
}

# ============================= 文件路径 =============================

# 模板文件路径
TEMPLATE_PATHS = {
    "cost_numbers": "templates/cost_numbers",
    "digits": "templates/digits",
    "cost_numbers_all": "templates/cost_numbers/all",
    "cost_numbers_backup": "templates/cost_numbers/backup",
    "cost_numbers_circle": "templates/cost_numbers/circle",
    "digits_backup": "templates/digits/backup"
}

# 调试文件路径
DEBUG_PATHS = {
    "debug_dir": "debug",
    "debug_cost_dir": "debug_cost"
} 