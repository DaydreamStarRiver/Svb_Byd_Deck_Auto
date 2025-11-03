"""
模板管理器
负责模板的加载、管理和匹配
"""

import cv2
import os
import logging
import numpy as np
from typing import Dict, Any, Optional, Tuple, Union
from src.utils.resource_utils import get_resource_path

logger = logging.getLogger(__name__)


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
        
        # 记录模板目录选择
        logger.info(f"模板管理器初始化: 使用目录 '{self.templates_dir}'")
    
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
            'mainPage': self._create_template_info('mainPage.png', "游戏主页面"),
            'MuMuPage': self._create_template_info('MuMuPage.png', "MuMu主页面"),
            'LoginPage': self._create_template_info('LoginPage.png', "排队主界面"),
            'enterGame': self._create_template_info('enterGame.png', "排队进入"),
            'dailyCard': self._create_template_info('dailyCard.png', "跳过每日一抽"),
        }

        # 加载额外模板
        extra_dir = config.get("extra_templates_dir", "")
        if extra_dir and os.path.isdir(extra_dir):
            logger.info(f"开始加载额外模板目录: {extra_dir}")
            # 只合并非None的模板，避免类型不兼容
            extra_templates = self._load_extra_templates(extra_dir)
            for k, v in extra_templates.items():
                if v is not None:
                    templates[k] = v

        self.templates = {k: v for k, v in templates.items() if v is not None}
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
        if not os.path.exists(path):
            logger.error(f"模板文件不存在: {path}")
            return None
        # 只对进化和超进化按钮用彩色，其余用灰度
        if filename in ["evolution.png", "super_evolution.png"]:
            template = cv2.imread(path, cv2.IMREAD_COLOR)
        else:
            template = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            logger.error(f"无法加载模板: {path}")
        return template

    def _create_template_info(self, filename: str, name: str, threshold: float = 0.85, hsv_range: dict = None) -> Optional[Dict[str, Any]]:
        """创建模板信息字典"""
        template_img = self._load_template(self.templates_dir, filename)
        if template_img is None:
            return None

        return self._create_template_info_from_image(template_img, name, threshold, hsv_range)

    def _create_template_info_from_image(self, template: np.ndarray, name: str, threshold: float = 0.85, hsv_range: dict = None) -> Dict[str, Any]:
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
        """执行模板匹配并返回结果，支持灰度和三通道。若模板注册了hsv_range，则匹配后自动做颜色判定。"""
        if not template_info:
            return None, 0
        tpl = template_info['template']
        hsv_range = template_info.get('hsv_range', None)
        # 灰度模板
        if len(tpl.shape) == 2:
            result = cv2.matchTemplate(image, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_loc is not None and isinstance(max_loc, tuple) and len(max_loc) == 2:
                return (int(max_loc[0]), int(max_loc[1])), float(max_val)
            else:
                return None, float(max_val)
        # 彩色模板
        else:
            result = cv2.matchTemplate(image, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_loc is not None and isinstance(max_loc, tuple) and len(max_loc) == 2:
                h, w, _ = tpl.shape
                x, y = int(max_loc[0]), int(max_loc[1])
                roi = image[y:y+h, x:x+w]
                if roi.shape[0] != h or roi.shape[1] != w:
                    return None, float(max_val)
                # 只用V通道判定
                if hsv_range:
                    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
                    if 'min_v' in hsv_range:
                        mean_v = hsv[..., 2].mean()
                        min_v = hsv_range['min_v']
                        if mean_v > min_v:
                            return (x, y), float(max_val)
                        else:
                            return None, 0.0
                    elif 'min' in hsv_range and 'max' in hsv_range:
                        min_h, min_s, min_v = hsv_range['min']
                        max_h, max_s, max_v = hsv_range['max']
                        # 只要有一个像素在区间内即判定成功
                        mask = (
                            (hsv[..., 0] >= min_h) & (hsv[..., 0] <= max_h) &
                            (hsv[..., 1] >= min_s) & (hsv[..., 1] <= max_s) &
                            (hsv[..., 2] >= min_v) & (hsv[..., 2] <= max_v)
                        )
                        if np.any(mask):
                            return (x, y), float(max_val)
                        else:
                            return None, 0.0
                    else:
                        # 没有有效的判定区间，直接返回
                        return (x, y), float(max_val)
                else:
                    # 没有颜色判定，直接返回
                    return (x, y), float(max_val)
            else:
                return None, float(max_val)

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