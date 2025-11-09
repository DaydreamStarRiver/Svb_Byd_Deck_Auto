"""
MNIST预处理模块
将裁剪的HP图像(43x39)转换为适合MNIST分类的格式(28x28灰度图)

设计原则:
1. 保留数字特征，去除背景干扰
2. 标准化为MNIST格式(28x28, 黑底白字)
3. 处理三种HP数字类型(红/绿/白)
"""

import cv2
import numpy as np
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class MNISTPreprocessor:
    """HP图像预处理器，转换为MNIST兼容格式"""

    def __init__(
        self,
        target_size: Tuple[int, int] = (28, 28),
        intermediate_size: Tuple[int, int] = (128, 128),
        margin: int = 2,
        remove_brown_edges: bool = True,
        denoise_strength: int = 3,
        dilation_iterations: int = 0,      # 膨胀次数（修复断裂笔画）
        debug: bool = False,
        # 双数字检测参数
        detect_double_digit: bool = True,  # 是否检测双数字
        split_threshold: int = 10,         # 中线白色像素阈值（小于此值认为是双数字）
        # 颜色检测参数
        bright_red_v_threshold: int = 180,  # 亮红色V值阈值（区分数字和背景）
        # 腐蚀和边缘裁剪参数
        red_erosion_iterations: int = 0,    # 红色数字腐蚀次数
        red_edge_margin: int = 1,           # 红色数字边缘裁剪列数
        green_erosion_iterations: int = 1,  # 绿色/白色数字腐蚀次数
        green_edge_margin: int = 3          # 绿色/白色数字边缘裁剪列数
    ):
        """
        初始化预处理器

        参数:
            target_size: 目标尺寸 (宽, 高), 默认(28, 28)
            intermediate_size: 中间处理尺寸 (宽, 高), 默认(128, 128) - 先放大到此尺寸处理，再缩小到目标尺寸
            margin: 数字周围的边距, 默认2像素
            remove_brown_edges: 是否去除金棕色边缘杂色, 默认True
            denoise_strength: 去噪强度 (奇数, 0表示不去噪), 默认3
            dilation_iterations: 膨胀次数 (修复断裂笔画, 0表示不膨胀), 默认0
            debug: 是否输出调试信息

            双数字检测参数:
            detect_double_digit: 是否检测双数字, 默认True
            split_threshold: 中线白色像素阈值 (小于此值认为是双数字), 默认10

            颜色检测参数:
            bright_red_v_threshold: 亮红色V值阈值, 默认180 (V>此值认为是数字，否则是背景)

            腐蚀和边缘裁剪参数:
            red_erosion_iterations: 红色数字腐蚀次数, 默认0 (不腐蚀)
            red_edge_margin: 红色数字边缘裁剪列数, 默认1
            green_erosion_iterations: 绿色/白色数字腐蚀次数, 默认1
            green_edge_margin: 绿色/白色数字边缘裁剪列数, 默认3
        """
        self.target_size = target_size
        self.intermediate_size = intermediate_size
        self.margin = margin
        self.remove_brown_edges = remove_brown_edges
        self.denoise_strength = max(1, denoise_strength if denoise_strength % 2 == 1 else denoise_strength + 1) if denoise_strength > 0 else 0
        self.dilation_iterations = dilation_iterations
        self.debug = debug

        # 双数字检测参数
        self.detect_double_digit = detect_double_digit
        self.split_threshold = split_threshold

        # 颜色检测阈值
        self.bright_red_v_threshold = bright_red_v_threshold

        # 腐蚀和边缘裁剪参数
        self.red_erosion_iterations = red_erosion_iterations
        self.red_edge_margin = red_edge_margin
        self.green_erosion_iterations = green_erosion_iterations
        self.green_edge_margin = green_edge_margin

    def preprocess(self, img: np.ndarray, mask: Optional[np.ndarray] = None) -> list:
        """
        完整预处理流程

        参数:
            img: 输入图像 (BGR或BGRA格式, 43x39像素)
            mask: 可选掩码 (255=有效, 0=透明)

        返回:
            预处理后的图像列表:
            - 单数字: [28x28灰度图]
            - 双数字: [左数字28x28, 右数字28x28]
        """
        if self.debug:
            logger.info(f"输入图像: shape={img.shape}, dtype={img.dtype}")

        # 步骤1: 提取数字前景 (去除红色背景)
        digit_mask = self._extract_digit_mask(img, mask)

        # 步骤2: 应用掩码，提取数字区域
        if len(img.shape) == 3 and img.shape[2] == 4:
            # BGRA图像，转为BGR
            img_bgr = img[:, :, :3].copy()
        else:
            img_bgr = img.copy()

        # 步骤2.5: 检测数字像素，过滤OTHER像素（在转灰度前！）
        if self.remove_brown_edges:
            digit_protection_mask = self._create_digit_protection_mask(img_bgr, mask)
        else:
            digit_protection_mask = None

        # 创建前景图像 (黑底白字)
        # 关键：只复制数字像素（GREEN/WHITE/PINK），不复制OTHER像素（金棕色括号）
        foreground = np.zeros_like(img_bgr)
        if digit_protection_mask is not None:
            # 使用保护掩码：只复制被保护的数字像素
            foreground[digit_protection_mask > 0] = img_bgr[digit_protection_mask > 0]
        else:
            # 如果不去除边缘，使用原来的digit_mask
            foreground[digit_mask > 0] = img_bgr[digit_mask > 0]

        # 步骤3: 转灰度 (OTHER区域已经是黑色0，不会产生灰度值)
        gray = cv2.cvtColor(foreground, cv2.COLOR_BGR2GRAY)

        # 步骤4: 放大到中间尺寸进行精细处理
        # 由于OTHER像素在转灰度前已被过滤，放大时不会产生灰度渐变
        if self.intermediate_size != img.shape[:2][::-1]:
            gray = cv2.resize(gray, self.intermediate_size, interpolation=cv2.INTER_CUBIC)
        else:
            pass

        if self.debug:
            logger.info(f"放大到中间尺寸: {self.intermediate_size}")

        # 步骤5: 增强对比度
        gray = self._enhance_contrast(gray)

        # 步骤6: 二值化
        binary = self._binarize(gray)

        # 步骤7: 去噪
        denoised = self._denoise(binary)

        # 步骤8: 检测双数字
        if self.detect_double_digit:
            is_double = self._detect_double_digit(denoised)
        else:
            is_double = False

        if self.debug:
            logger.info(f"双数字检测: {is_double}")

        # 步骤9: 根据检测结果处理
        if is_double:
            # 分割成两个数字
            left_half, right_half = self._split_double_digit(denoised)
            left_28 = self._resize_with_aspect_ratio(left_half, self.target_size, self.margin)
            right_28 = self._resize_with_aspect_ratio(right_half, self.target_size, self.margin)

            if self.debug:
                logger.info(f"双数字分割: 左={left_28.shape}, 右={right_28.shape}")

            return [left_28, right_28]
        else:
            # 单数字，直接缩放
            resized = self._resize_with_aspect_ratio(denoised, self.target_size, self.margin)

            if self.debug:
                logger.info(f"单数字输出: shape={resized.shape}, dtype={resized.dtype}, "
                           f"min={resized.min()}, max={resized.max()}")

            return [resized]

    def _extract_digit_mask(self, img: np.ndarray, external_mask: Optional[np.ndarray] = None) -> np.ndarray:
        """
        提取数字前景掩码 (去除红色背景)

        策略:
        - 绿色数字: HSV绿色范围 + RGB绿色通道
        - 白色数字: 高亮度 + 低饱和度
        - 红色数字: 使用PINK抗锯齿像素作为边界
        """
        if len(img.shape) == 3 and img.shape[2] == 4:
            img_bgr = img[:, :, :3]
        else:
            img_bgr = img

        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        b, g, r = cv2.split(img_bgr)
        h, s, v = cv2.split(hsv)

        # 转为int32避免溢出
        b = b.astype(np.int32)
        g = g.astype(np.int32)
        r = r.astype(np.int32)
        h = h.astype(np.int32)
        s = s.astype(np.int32)
        v = v.astype(np.int32)

        # GREEN: 绿色数字 (放宽条件以捕获过渡像素)
        is_green_rgb = (g > 70) & (g > r * 1.0) & (g > b * 1.1)
        is_green_hsv = (h >= 20) & (h <= 90) & (s > 140) & (g > 40)
        is_green = (is_green_rgb | is_green_hsv).astype(np.uint8) * 255

        # WHITE: 白色数字 (严格条件)
        min_channel = np.minimum(np.minimum(r, g), b)
        is_white = ((r > 150) & (g > 140) & (b > 100) &
                   (s < 80) & (v > 150) & (min_channel > 100)).astype(np.uint8) * 255

        # PINK: 粉色抗锯齿 (红色数字的边缘)
        # 排除金棕色括号：限制G值上限
        is_pink = ((r > 140) & (g > 70) & (g < 140) & (b > 40) & (b < 150) &
                  (s > 40) & (s < 130) & (r > g * 1.15) & (r > b * 1.2) &
                  (v > 140)).astype(np.uint8) * 255

        # BRIGHT_RED: 亮红色数字中心（之前被错误地归类为RED背景）
        # 区分亮红色（数字）和暗红色（背景）：使用可配置的V阈值
        is_bright_red = ((r > 140) & (r > g * 1.3) & (r > b * 1.2) &
                        (s > 80) & (v > self.bright_red_v_threshold) & (np.abs(g - b) < 60)).astype(np.uint8) * 255

        # 合并所有数字类型（不包括PINK，避免误判括号）
        digit_mask = cv2.bitwise_or(is_green, is_white)
        digit_mask = cv2.bitwise_or(digit_mask, is_bright_red)

        # 应用外部掩码 (如果提供)
        if external_mask is not None:
            digit_mask = cv2.bitwise_and(digit_mask, external_mask)

        # 形态学操作：闭运算填补数字内部的空洞
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        digit_mask = cv2.morphologyEx(digit_mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        # 膨胀以连接断开的笔画
        digit_mask = cv2.dilate(digit_mask, kernel, iterations=1)

        return digit_mask

    def _create_digit_protection_mask(self, img_bgr: np.ndarray, external_mask: Optional[np.ndarray] = None) -> np.ndarray:
        """
        在原始尺寸创建数字保护掩码（在放大前检测，避免插值改变颜色）

        策略:
        1. 使用颜色分类检测数字像素 (GREEN + WHITE + PINK)
        2. 膨胀创建保护区
        3. 返回掩码：255=保留（数字区域），0=删除（OTHER区域）
        """
        if len(img_bgr.shape) == 2:
            # 灰度图，返回全保留
            return np.ones(img_bgr.shape, dtype=np.uint8) * 255

        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        b, g, r = cv2.split(img_bgr)
        hue, s, v = cv2.split(hsv)

        # 转int32避免溢出
        b = b.astype(np.int32)
        g = g.astype(np.int32)
        r = r.astype(np.int32)
        hue = hue.astype(np.int32)
        s = s.astype(np.int32)
        v = v.astype(np.int32)

        # 检测数字像素 (GREEN + WHITE + PINK)
        # GREEN
        is_green_rgb = (g > 70) & (g > r * 1.0) & (g > b * 1.1)
        is_green_hsv = (hue >= 20) & (hue <= 90) & (s > 140) & (g > 40)
        is_green = is_green_rgb | is_green_hsv

        # WHITE
        min_channel = np.minimum(np.minimum(r, g), b)
        is_white = ((r > 150) & (g > 140) & (b > 100) &
                   (s < 80) & (v > 150) & (min_channel > 100))

        # PINK - 红色数字的抗锯齿像素
        # 排除金棕色括号：限制G值上限（括号G值高达142）
        is_pink = ((r > 140) & (g > 70) & (g < 140) & (b > 40) & (b < 150) &
                  (s > 40) & (s < 130) &
                  (r > g * 1.15) & (r > b * 1.2) &
                  (v > 140))

        # BRIGHT_RED - 亮红色数字中心
        # 区分亮红色（数字）和暗红色（背景）：使用可配置的V阈值
        is_bright_red = ((r > 140) & (r > g * 1.3) & (r > b * 1.2) &
                        (s > 80) & (v > self.bright_red_v_threshold) & (np.abs(g - b) < 60))

        # 合并所有数字像素（不包括PINK，避免误判括号）
        is_digit = (is_green | is_white | is_bright_red).astype(np.uint8) * 255

        # 应用外部掩码（如果提供）
        if external_mask is not None:
            is_digit = cv2.bitwise_and(is_digit, external_mask)

        # 改进1: 腐蚀操作 - 根据数字类型动态调整（使用可配置参数）
        # BRIGHT_RED数字（红色数字）通常较细
        # GREEN/WHITE数字较粗
        bright_red_count = np.sum(is_bright_red)
        green_white_count = np.sum(is_green | is_white)

        if bright_red_count > green_white_count:
            # 主要是BRIGHT_RED数字（红色）
            erosion_iterations = self.red_erosion_iterations
            left_margin = self.red_edge_margin
            right_margin = self.red_edge_margin
        else:
            # 主要是GREEN/WHITE数字
            erosion_iterations = self.green_erosion_iterations
            left_margin = self.green_edge_margin
            right_margin = self.green_edge_margin

        # 执行腐蚀（如果iterations > 0）
        if erosion_iterations > 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            is_digit = cv2.erode(is_digit, kernel, iterations=erosion_iterations)

        # 改进2: 空间约束，移除最左和最右边缘列（括号通常在边缘）
        width = img_bgr.shape[1]
        is_digit[:, :left_margin] = 0  # 移除左边缘
        is_digit[:, width-right_margin:] = 0  # 移除右边缘

        return is_digit

    def _enhance_contrast(self, gray: np.ndarray) -> np.ndarray:
        """
        增强对比度使用CLAHE (Contrast Limited Adaptive Histogram Equalization)
        """
        if gray.max() == 0:
            return gray

        # CLAHE参数
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        enhanced = clahe.apply(gray)

        return enhanced

    def _binarize(self, gray: np.ndarray) -> np.ndarray:
        """
        二值化图像

        使用Otsu's方法自动确定阈值
        """
        if gray.max() == 0:
            return gray

        # Otsu二值化
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        return binary

    def _denoise(self, binary: np.ndarray) -> np.ndarray:
        """
        去噪和修复: 移除小的噪点，修复断裂笔画

        去噪使用形态学开运算，修复使用膨胀
        """
        result = binary.copy()

        # 步骤1: 去噪（如果denoise_strength > 0）
        if self.denoise_strength > 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                              (self.denoise_strength, self.denoise_strength))
            result = cv2.morphologyEx(result, cv2.MORPH_OPEN, kernel, iterations=1)

        # 步骤2: 膨胀修复断裂笔画（如果dilation_iterations > 0）
        if self.dilation_iterations > 0:
            kernel_dilation = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            result = cv2.dilate(result, kernel_dilation, iterations=self.dilation_iterations)

        return result

    def _resize_with_aspect_ratio(self, img: np.ndarray, target_size: Tuple[int, int],
                                  margin: int) -> np.ndarray:
        """
        缩放图像到目标尺寸，保持宽高比，居中放置

        参数:
            img: 输入图像
            target_size: 目标尺寸 (宽, 高)
            margin: 边距

        返回:
            缩放后的图像 (黑色背景)
        """
        if img.size == 0:
            # 空图像，返回黑色背景
            return np.zeros(target_size[::-1], dtype=np.uint8)

        h, w = img.shape
        target_w, target_h = target_size

        # 计算可用空间 (减去边距)
        available_w = target_w - 2 * margin
        available_h = target_h - 2 * margin

        # 计算缩放比例 (保持宽高比)
        scale = min(available_w / w, available_h / h)

        # 新尺寸
        new_w = int(w * scale)
        new_h = int(h * scale)

        # 确保至少1像素
        new_w = max(1, new_w)
        new_h = max(1, new_h)

        # 缩放 (使用INTER_AREA对于缩小效果更好)
        if scale < 1.0:
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            # 放大使用INTER_CUBIC
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

        # 创建黑色背景
        canvas = np.zeros((target_h, target_w), dtype=np.uint8)

        # 计算居中位置
        offset_x = (target_w - new_w) // 2
        offset_y = (target_h - new_h) // 2

        # 放置图像
        canvas[offset_y:offset_y+new_h, offset_x:offset_x+new_w] = resized

        return canvas

    def _detect_double_digit(self, binary_128: np.ndarray) -> bool:
        """
        检测128x128图像是否包含两个数字

        策略:
        在中线(64和65列)检测白色像素数量
        如果白色像素 < split_threshold，认为是双数字

        参数:
            binary_128: 128x128二值化图像

        返回:
            True=双数字, False=单数字
        """
        h, w = binary_128.shape
        mid_col1 = w // 2 - 1  # 第63列(0-indexed)
        mid_col2 = w // 2      # 第64列(0-indexed)

        # 统计中线两列的白色像素
        white_pixels_col1 = np.sum(binary_128[:, mid_col1] > 0)
        white_pixels_col2 = np.sum(binary_128[:, mid_col2] > 0)
        total_white = white_pixels_col1 + white_pixels_col2

        if self.debug:
            logger.info(f"中线白色像素: 列{mid_col1}={white_pixels_col1}, "
                       f"列{mid_col2}={white_pixels_col2}, "
                       f"总计={total_white}, 阈值={self.split_threshold}")

        return total_white < self.split_threshold

    def _split_double_digit(self, binary_128: np.ndarray) -> tuple:
        """
        分割双数字为左右两半

        参数:
            binary_128: 128x128二值化图像

        返回:
            (left_half, right_half) 都是64x128的图像
        """
        h, w = binary_128.shape
        mid = w // 2  # 64

        # 分割
        left_half = binary_128[:, :mid]     # 0-63列
        right_half = binary_128[:, mid:]    # 64-127列

        if self.debug:
            logger.info(f"分割结果: 左={left_half.shape}, 右={right_half.shape}")

        return left_half, right_half

    def preprocess_batch(self, images: list, masks: Optional[list] = None) -> list:
        """
        批量预处理

        参数:
            images: 图像列表
            masks: 掩码列表 (可选)

        返回:
            预处理后的图像列表，每个元素是一个列表:
            - 单数字: [28x28灰度图]
            - 双数字: [左数字28x28, 右数字28x28]
        """
        if masks is None:
            masks = [None] * len(images)

        results = []
        for img, mask in zip(images, masks):
            preprocessed = self.preprocess(img, mask)  # 返回列表
            results.append(preprocessed)

        return results


def create_default_preprocessor(debug: bool = False) -> MNISTPreprocessor:
    """
    创建默认配置的预处理器

    参数:
        debug: 是否启用调试模式

    返回:
        MNISTPreprocessor实例
    """
    return MNISTPreprocessor(
        target_size=(28, 28),
        intermediate_size=(128, 128),
        margin=2,
        remove_brown_edges=True,
        denoise_strength=3,
        debug=debug
    )


def preprocess_for_mnist(img: np.ndarray, mask: Optional[np.ndarray] = None,
                        debug: bool = False) -> np.ndarray:
    """
    便捷函数: 单张图像预处理

    参数:
        img: 输入图像 (BGR或BGRA, 43x39像素)
        mask: 可选掩码
        debug: 是否输出调试信息

    返回:
        预处理后的图像 (28x28灰度图)
    """
    preprocessor = create_default_preprocessor(debug=debug)
    return preprocessor.preprocess(img, mask)
