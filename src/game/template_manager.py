"""
模板管理器
负责模板的加载、管理和匹配
"""

import cv2
import os
import logging
import numpy as np
from typing import Dict, Any, Optional, Tuple
from src.utils.image_io import safe_imread
from src.utils.resource_utils import resource_path

logger = logging.getLogger(__name__)


# 结算页的“返回乐园”文字会随渲染后端产生轻微抗锯齿差异，单独放宽阈值。
GALA_BACK_PARK_THRESHOLD = 0.82
SETTLEMENT_TEMPLATE_THRESHOLD = 0.80
DECK_SELECTION_TEMPLATE_THRESHOLD = 0.80


PAGE_TEXT_ALIASES = {
    "decision": ("决定", "決定", "DECIDE"),
    "end_round": ("结束回合", "結束回合", "回合结束", "回合結束", "END TURN"),
    # “散方”是 Maa zh_cn 对繁体花字“敵方”的稳定输出，保留为校准别名。
    "enemy_round": ("敌方回合", "敵方回合", "散方", "OPPONENT TURN"),
    "mainPage": (
        "随机对战",
        "隨機對戰",
        "随機對戰",
        # Maa 对入口花字的已校准输出；保持为完整短语，避免使用单机页也会出现的“随机”。
        "随機封戟",
        "随機对",
        "随机对",
        "阶级对战",
        "階級對戰",
    ),
    "LoginPage": ("正在排队", "正在排隊", "MATCHING"),
    "enterGame": ("进入对战", "進入對戰", "ENTER"),
    "error_retry": ("重试", "重試", "RETRY"),
    "win": ("WIN", "胜利", "勝利"),
    "result": ("RESULT", "失败", "失敗", "败北", "敗北"),
    "deck_confirm_dialog": ("确认牌组", "確認牌組"),
    "deck_selection_page": ("选择牌组", "選擇牌組"),
}


class TemplateManager:
    """模板管理器类"""
    
    def __init__(self, device_config: Optional[Dict[str, Any]] = None):
        self.device_config = device_config or {}
        # 根据设备配置选择模板目录
        is_global = self.device_config.get('is_global', False)
        self.templates_dir = "templates_global" if is_global else "templates"
        self.templates: Dict[str, Dict[str, Any]] = {}
        self.evolution_template = None
        self.super_evolution_template = None
        self.text_recognition = None
        
        # 记录模板目录选择
        logger.info(f"模板管理器初始化: 使用目录 '{self.templates_dir}'")

    def get_templates_dir(self) -> str:
        """返回当前选择的模板目录名称。"""

        return self.templates_dir

    def set_text_recognition(self, recognition: Any) -> None:
        """Attach the optional Maa page-text fallback service."""

        self.text_recognition = recognition

    def get_template_path(self, filename: str) -> str:
        """获取模板文件路径（尽量与旧逻辑兼容）。

        - 若相对路径在当前工作目录下存在，优先使用（兼容旧运行方式）
        - 否则按 app root（源码/打包）解析
        """

        rel_path = os.path.join(self.templates_dir, filename)
        if os.path.exists(rel_path):
            return rel_path
        return resource_path(rel_path)
    
    def load_templates(self, config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """加载所有模板"""
        templates = {
            'rank': self._create_template_info('rank.png', "阶级积分"),
            'missionCompleted': self._create_template_info('missionCompleted.png', "任务完成"),
            'backTitle': self._create_template_info('backTitle.png', "返回标题"),
            'Yes': self._create_template_info('Yes.png', "继续战斗"),
            'rankUp': self._create_template_info('rankUp.png', "阶位提升"),
            'groupUp': self._create_template_info('groupUp.png', "分组升级"),
            'error_retry': self._create_template_info('error_retry.png', "重试"),
            'Ok': self._create_template_info('Ok.png', "好的"),
            'decision': self._create_template_info('decision.png', "决定"),
            'end_round': self._create_template_info('end_round.png', "结束回合"),
            'enemy_round': self._create_template_info('enemy_round.png', "敌方回合"),
            'end': self._create_template_info('end.png', "结束"),
            'war': self._create_template_info('war.png', "决斗"),
            'win': self._create_template_info(
                'win.png',
                "胜利结算",
                threshold=SETTLEMENT_TEMPLATE_THRESHOLD,
                multiscale=True,
            ),
            'result': self._create_template_info(
                'result.png',
                "失败结算",
                threshold=SETTLEMENT_TEMPLATE_THRESHOLD,
                multiscale=True,
            ),
            'deck_confirm_dialog': self._create_optional_template_info(
                'deck_confirm_dialog.png',
                "确认牌组弹窗",
                threshold=0.72,
                multiscale=True,
                # 弹窗标题只会出现在画面上方偏下。限定搜索区域可避免
                # 选择页标题以及结算页装饰被误当成弹窗标识。
                search_region=(0.30, 0.10, 0.70, 0.28),
            ),
            'deck_selection_page': self._create_optional_template_info(
                'Select_Deck.png',
                "选择牌组页面",
                threshold=DECK_SELECTION_TEMPLATE_THRESHOLD,
                multiscale=True,
                # 选择牌组的标题位于顶部栏；确认弹窗与结算页中的相似
                # 纹理均在更低位置，不应参与该页面的状态判定。
                search_region=(0.30, 0.02, 0.70, 0.16),
            ),
            'mainPage': self._create_template_info('mainPage.png', "游戏主页面"),
            'MuMuPage': self._create_template_info('MuMuPage.png', "MuMu主页面"),
            'LoginPage': self._create_template_info('LoginPage.png', "排队主界面"),
            'enterGame': self._create_template_info('enterGame.png', "排队进入"),
            'dailyCard': self._create_template_info('dailyCard.png', "跳过每日一抽"),
            'gala_Ok': self._create_template_info('gala_Ok.png', "庆典广场_准备完成"),
            'gala_war': self._create_template_info('gala_war.png', "庆典广场_对战"),
            'gala_index': self._create_template_info('gala_index.png', "庆典广场_索引对战"),
            'gala_BackPark': self._create_template_info(
                'gala_BackPark.png',
                "庆典广场_返回乐园",
                threshold=GALA_BACK_PARK_THRESHOLD,
            ),
        }

        # 加载额外模板
        extra_dir = config.get("extra_templates_dir", "")
        extra_dir_resolved = extra_dir
        if extra_dir and not os.path.isabs(extra_dir) and not os.path.isdir(extra_dir):
            extra_dir_resolved = resource_path(extra_dir)

        if extra_dir_resolved and os.path.isdir(extra_dir_resolved):
            logger.info(f"开始加载额外模板目录: {extra_dir_resolved}")
            # 只合并非None的模板，避免类型不兼容
            extra_templates = self._load_extra_templates(extra_dir_resolved)
            for k, v in extra_templates.items():
                if v is not None:
                    templates[k] = v

        self.templates = {k: v for k, v in templates.items() if v is not None}
        for key, template_info in self.templates.items():
            aliases = PAGE_TEXT_ALIASES.get(key)
            if aliases:
                template_info["text_aliases"] = aliases
        logger.info("模板加载完成")
        return self.templates

    def _load_extra_templates(self, extra_dir: str) -> Dict[str, Dict[str, Any]]:
        """加载额外模板"""
        extra_templates = {}
        
        # 支持的图片扩展名
        valid_extensions = ['.png', '.jpg', '.jpeg', '.bmp']

        for filename in os.listdir(extra_dir):
            filepath = os.path.join(extra_dir, filename)

            # 检查是否是图片文件
            if os.path.isfile(filepath) and os.path.splitext(filename)[1].lower() in valid_extensions:
                template_name = os.path.splitext(filename)[0]  # 使用文件名作为模板名称

                # 加载模板
                template_img = self._load_template(extra_dir, filename)
                if template_img is None:
                    logger.warning(f"无法加载额外模板: {filename}")
                    continue

                # 创建模板信息（使用全局阈值）
                template_info = self._create_template_info_from_image(
                    template_img,
                    f"额外模板-{template_name}",
                    threshold=0.85
                )

                # 添加到模板字典（如果已存在则覆盖）
                extra_templates[template_name] = template_info
                logger.info(f"已添加额外模板: {template_name} (来自: {filename})")

        return extra_templates

    def _load_template(self, templates_dir: str, filename: str) -> Optional[np.ndarray]:
        """加载模板图像，进化/超进化为彩色，其余为灰度"""
        path = os.path.join(templates_dir, filename)
        if not os.path.exists(path) and not os.path.isabs(path):
            path = resource_path(path)
        if not os.path.exists(path):
            logger.error(f"模板文件不存在: {path}")
            return None
        # 只对进化和超进化按钮用彩色，其余用灰度
        if filename in ["evolution.png", "super_evolution.png"]:
            template = safe_imread(path, cv2.IMREAD_COLOR)
        else:
            template = safe_imread(path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            logger.error(f"无法加载模板: {path}")
        return template

    def _create_template_info(
        self,
        filename: str,
        name: str,
        threshold: float = 0.85,
        hsv_range: Optional[Dict[str, Any]] = None,
        multiscale: bool = False,
        search_region: Optional[Tuple[float, float, float, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """创建模板信息字典"""
        template_img = self._load_template(self.templates_dir, filename)
        if template_img is None:
            return None

        info = self._create_template_info_from_image(template_img, name, threshold, hsv_range)
        info["multiscale"] = bool(multiscale)
        if search_region is not None:
            info["search_region"] = tuple(float(value) for value in search_region)
        return info

    def _create_optional_template_info(
        self,
        filename: str,
        name: str,
        threshold: float = 0.85,
        hsv_range: Optional[Dict[str, Any]] = None,
        multiscale: bool = False,
        search_region: Optional[Tuple[float, float, float, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load an optional feature template without emitting a startup error."""

        if not os.path.exists(self.get_template_path(filename)):
            return None
        return self._create_template_info(
            filename,
            name,
            threshold=threshold,
            hsv_range=hsv_range,
            multiscale=multiscale,
            search_region=search_region,
        )

    def _create_template_info_from_image(
        self,
        template: np.ndarray,
        name: str,
        threshold: float = 0.85,
        hsv_range: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """从图像创建模板信息字典，支持灰度和三通道"""
        if len(template.shape) == 2:
            h, w = template.shape
        else:
            h, w, _ = template.shape
        return {
            'name': name,
            'template': template,
            'w': w,
            'h': h,
            'threshold': threshold,
            'hsv_range': hsv_range  # 可选颜色判定区间
        }

    def match_template(self, image: np.ndarray, template_info: Dict[str, Any]) -> Tuple[Optional[Tuple[int, int]], float]:
        """执行模板匹配并返回结果，支持灰度、多尺度和颜色判定。"""
        if not template_info:
            return None, 0
        template_info.pop("matched_w", None)
        template_info.pop("matched_h", None)
        tpl = template_info['template']
        hsv_range = template_info.get('hsv_range', None)

        # 部分页面标题在全屏上有高度相似的装饰纹理。对这类模板只在
        # 其固定的 UI 区域内匹配，避免一个低阈值假阳性封死整个状态机。
        search_image = image
        offset_x = 0
        offset_y = 0
        search_region = template_info.get("search_region")
        if search_region is not None and len(search_region) == 4:
            image_h, image_w = image.shape[:2]
            left, top, right, bottom = (
                max(0.0, min(1.0, float(value))) for value in search_region
            )
            x1 = int(round(image_w * min(left, right)))
            x2 = int(round(image_w * max(left, right)))
            y1 = int(round(image_h * min(top, bottom)))
            y2 = int(round(image_h * max(top, bottom)))
            if x2 <= x1 or y2 <= y1:
                return None, 0.0
            search_image = image[y1:y2, x1:x2]
            offset_x = x1
            offset_y = y1

        if len(tpl.shape) == 2:
            if template_info.get("multiscale"):
                best_loc = None
                best_value = -1.0
                best_width = int(tpl.shape[1])
                best_height = int(tpl.shape[0])
                for scale in (0.90, 0.95, 1.0, 1.05, 1.10, 1.15, 1.20):
                    scaled = cv2.resize(
                        tpl,
                        None,
                        fx=scale,
                        fy=scale,
                        interpolation=cv2.INTER_CUBIC,
                    )
                    if (
                        scaled.shape[0] > search_image.shape[0]
                        or scaled.shape[1] > search_image.shape[1]
                    ):
                        continue
                    result = cv2.matchTemplate(
                        search_image, scaled, cv2.TM_CCOEFF_NORMED
                    )
                    _, value, _, loc = cv2.minMaxLoc(result)
                    if value > best_value:
                        best_value = float(value)
                        best_loc = (
                            int(loc[0]) + offset_x,
                            int(loc[1]) + offset_y,
                        )
                        best_width = int(scaled.shape[1])
                        best_height = int(scaled.shape[0])
                if best_loc is not None:
                    template_info["matched_w"] = best_width
                    template_info["matched_h"] = best_height
                    return best_loc, best_value
                return None, 0.0

            if (
                tpl.shape[0] > search_image.shape[0]
                or tpl.shape[1] > search_image.shape[1]
            ):
                return None, 0.0
            result = cv2.matchTemplate(search_image, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_loc is not None and isinstance(max_loc, tuple) and len(max_loc) == 2:
                return (
                    int(max_loc[0]) + offset_x,
                    int(max_loc[1]) + offset_y,
                ), float(max_val)
            return None, float(max_val)

        if (
            tpl.shape[0] > search_image.shape[0]
            or tpl.shape[1] > search_image.shape[1]
        ):
            return None, 0.0
        result = cv2.matchTemplate(search_image, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_loc is None or not isinstance(max_loc, tuple) or len(max_loc) != 2:
            return None, float(max_val)

        h, w, _ = tpl.shape
        x = int(max_loc[0]) + offset_x
        y = int(max_loc[1]) + offset_y
        roi = image[y:y+h, x:x+w]
        if roi.shape[0] != h or roi.shape[1] != w:
            return None, float(max_val)
        if not hsv_range:
            return (x, y), float(max_val)

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        if 'min_v' in hsv_range:
            return ((x, y), float(max_val)) if hsv[..., 2].mean() > hsv_range['min_v'] else (None, 0.0)
        if 'min' in hsv_range and 'max' in hsv_range:
            min_h, min_s, min_v = hsv_range['min']
            max_h, max_s, max_v = hsv_range['max']
            mask = (
                (hsv[..., 0] >= min_h) & (hsv[..., 0] <= max_h) &
                (hsv[..., 1] >= min_s) & (hsv[..., 1] <= max_s) &
                (hsv[..., 2] >= min_v) & (hsv[..., 2] <= max_v)
            )
            return ((x, y), float(max_val)) if np.any(mask) else (None, 0.0)
        return (x, y), float(max_val)

    def match_text_key(
        self,
        image: np.ndarray,
        key: str,
    ) -> Tuple[Optional[Tuple[int, int]], float]:
        """Match one registered page key through Maa page OCR only."""

        template_info = self.templates.get(key)
        recognition = self.text_recognition
        if not template_info or recognition is None:
            return None, 0.0
        aliases = template_info.get("text_aliases", ())
        if not aliases:
            return None, 0.0
        item = recognition.match_page_aliases(image, aliases)
        if item is None:
            return None, 0.0
        x, y, width, height = item.box
        template_info["matched_w"] = max(1, int(width))
        template_info["matched_h"] = max(1, int(height))
        return (int(x), int(y)), max(float(item.score), float(template_info["threshold"]))

    def find_page_text_match(
        self,
        image: np.ndarray,
    ) -> Optional[Tuple[str, Tuple[int, int], float]]:
        """Return the first strong page-text fallback among registered keys."""

        for key in PAGE_TEXT_ALIASES:
            if key not in self.templates:
                continue
            location, score = self.match_text_key(image, key)
            if location is not None:
                return key, location, score
        return None

    def load_evolution_template(self) -> Optional[Dict[str, Any]]:
        """加载进化按钮模板，完整HSV区间判定"""
        if self.evolution_template is None:
            evo_hsv = {'min': (19, 150, 184), 'max': (25, 255, 255)}
            self.evolution_template = self._create_template_info('evolution.png', "进化按钮", threshold=0.85, hsv_range=evo_hsv)
        return self.evolution_template

    def load_super_evolution_template(self) -> Optional[Dict[str, Any]]:
        """加载超进化按钮模板，完整HSV区间判定"""
        if self.super_evolution_template is None:
            evo_hsv = {'min': (120, 26, 129), 'max': (156, 180, 255)}
            self.super_evolution_template = self._create_template_info('super_evolution.png', "超进化按钮", threshold=0.85, hsv_range=evo_hsv)
        return self.super_evolution_template

    def detect_evolution_button(self, screenshot: np.ndarray) -> Tuple[Optional[Tuple[int, int]], float]:
        """检测进化按钮是否出现，彩色"""
        evolution_info = self.load_evolution_template()
        if not evolution_info:
            return None, 0
        return self.match_template(screenshot, evolution_info)

    def detect_super_evolution_button(self, screenshot: np.ndarray) -> Tuple[Optional[Tuple[int, int]], float]:
        """检测超进化按钮是否出现，彩色"""
        evolution_info = self.load_super_evolution_template()
        if not evolution_info:
            return None, 0
        return self.match_template(screenshot, evolution_info) 
