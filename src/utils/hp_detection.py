"""
HP检测实用工具

从test_hp.py中提取，用于集成到主项目中。
提供滑动窗口检测、颜色分析和带有回退机制的识别功能。
"""

import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)


def sanitize_single_digit_result(prediction_str):
    """
    净化预测结果，确保输出为单个数字

    由于我们在将双位数输入模型前会手动分割，每个模型输入始终是单个数字图像。
    然而，EasyOCR可能仍会返回多个数字。

    规则：
    1. 首先尝试转换为整数（去除前导零："01" → 1 → "1"）
    2. 如果仍然是多个数字，取最左边的数字（"15" → 1 → "1"）
    3. 返回净化后的单个数字字符串

    示例：
        "5" → "5"（正确，无更改）
        "01" → 1 → "1"（前导零已去除）
        "15" → 15 → "1"（取最左边）
        "123" → 123 → "1"（取最左边）
        "" → ""（空字符串，无更改）
        "error" → "error"（特殊值，无更改）

    参数：
        prediction_str: 来自模型的原始预测字符串

    返回：
        净化后的单个字符数字字符串，错误/空字符串时返回原始值
    """
    if not prediction_str or prediction_str in ["error", "", "unknown", "none"]:
        return prediction_str

    # 尝试转换为整数以去除前导零
    try:
        num = int(prediction_str)
        prediction_str = str(num)
    except (ValueError, TypeError):
        # 如果无法转换，只取第一个数字字符
        prediction_str = ''.join(c for c in prediction_str if c.isdigit())[:1]
        return prediction_str if prediction_str else "error"

    # 如果仍然是多个数字，取最左边的数字
    if len(prediction_str) > 1:
        prediction_str = prediction_str[0]

    return prediction_str


def detect_hp_in_window(window, mask, red_bg_threshold=0.25, other_threshold=0.25,
                       digit_threshold=0.10, bright_red_v_threshold=210):
    """
    使用颜色分析在滑动窗口中检测HP

    分类：
    - RED_BG: 暗红色背景（低V值）
    - BRIGHT_RED: 亮红色数字（高V值 >= bright_red_v_threshold）
    - GREEN: 绿色数字
    - WHITE: 白色数字
    - OTHER: 噪声/未分类

    参数：
        window: BGR图像窗口
        mask: 二值掩码（0-255）
        red_bg_threshold: 红色背景比例阈值（默认0.25）
        other_threshold: 噪声比例阈值（默认0.25）
        digit_threshold: 数字像素比例阈值（默认0.10）
        bright_red_v_threshold: 亮红色数字的V值阈值（默认210）

    返回：
        (detected, red_count): 布尔值和整数的元组
    """
    mask_bool = mask > 0
    if not np.any(mask_bool):
        return False, 0

    # Extract masked pixels
    pixels_bgr = window[mask_bool]
    b = pixels_bgr[:, 0].astype(np.int32)
    g = pixels_bgr[:, 1].astype(np.int32)
    r = pixels_bgr[:, 2].astype(np.int32)

    # Convert to HSV for better color detection
    window_hsv = cv2.cvtColor(window, cv2.COLOR_BGR2HSV)
    pixels_hsv = window_hsv[mask_bool]
    h = pixels_hsv[:, 0].astype(np.int32)
    s = pixels_hsv[:, 1].astype(np.int32)
    v = pixels_hsv[:, 2].astype(np.int32)

    total = len(pixels_bgr)

    # 1. 红色背景：暗红色背景（r占主导，高饱和度，中低V值）
    is_red_bg = ((r > 90) & (r > g * 1.3) & (r > b * 1.3) &
                 (s > 100) & (np.abs(g - b) < 32))
    
    # 2. 亮红色数字：亮红色数字（r占主导，高V值 >= 阈值）
    is_bright_red = ((r > 140) & (r > g * 1.2) & (r > b * 1.2) &
                     (s > 100) & (v >= bright_red_v_threshold) & (np.abs(g - b) < 32))
    bright_red_count = int(np.sum(is_bright_red))

    bright_red_ratio = bright_red_count / total

    # 3. 绿色数字：绿色数字（放宽条件以捕获橙绿色过渡）
    is_green_rgb = (g > 70) & (g > r * 1.0) & (g > b * 1.1)
    is_green_hsv = (h >= 20) & (h <= 90) & (s > 140) & (g > 40)
    is_green = is_green_rgb | is_green_hsv
    green_count = int(np.sum(is_green))

    green_ratio = green_count / total

    if green_ratio > digit_threshold or bright_red_ratio > digit_threshold:
        is_red_bg = ((r > 90) & (r > g * 1.3) & (r > b * 1.3) &
                 (s > 100) & (np.abs(g - b) < 40))

    # 4. 白色数字：白色数字（高RGB值，低饱和度，高V值）
    min_channel = np.minimum(np.minimum(r, g), b)
    is_white = ((r > 150) & (g > 140) & (b > 100) &
                (s < 80) & (v > 150) & (min_channel > 100))

    # Calculate ratios
    red_bg_count = int(np.sum(is_red_bg))
    digit_count = int(np.sum(is_bright_red | is_green | is_white))
    other_count = int(np.sum(~(is_red_bg | is_bright_red | is_green | is_white)))

    red_bg_ratio = red_bg_count / total
    digit_ratio = digit_count / total
    other_ratio = other_count / total

    # Detection: RED_BG >= threshold AND OTHER < threshold AND DIGIT >= threshold
    detected = (red_bg_ratio >= red_bg_threshold and
                other_ratio < other_threshold and
                digit_ratio >= digit_threshold)

    return detected, red_bg_count


def sliding_window_detect(region_img, mask, window_width=43, window_height=39,
                          slide_step=1, **color_kwargs):
    """
    使用滑动窗口从右到左检测HP位置

    参数：
        region_img: HP区域的BGR图像
        mask: 窗口的二值掩码
        window_width: 窗口宽度（默认43）
        window_height: 窗口高度（默认39）
        slide_step: 滑动步长（默认1）
        **color_kwargs: detect_hp_in_window的额外参数

    返回：
        (center_x, width, score)元组的列表
    """
    h, w = region_img.shape[:2]
    detections = []

    # Slide from right to left
    x = w - window_width
    while x >= 0:
        window = region_img[0:h, x:x+window_width]
        detected, red_count = detect_hp_in_window(window, mask, **color_kwargs)

        if detected:
            center_x = x + window_width // 2
            detections.append((center_x, window_width, red_count))

        x -= slide_step

    return detections


def merge_detections(detections, min_gap=105, max_followers=5):
    """
    合并重叠的检测结果

    参数：
        detections: (center_x, width, score)元组的列表
        min_gap: 随从之间的最小间隔（默认105）
        max_followers: 最大随从数量（默认5）

    返回：
        (center_x, width)元组的列表（已合并并限制数量）
    """
    if not detections:
        return []

    sorted_dets = sorted(detections, key=lambda d: d[0])
    merged = []
    current = list(sorted_dets[0])

    for det in sorted_dets[1:]:
        cx, w, score = det
        if cx - current[0] < min_gap:
            # Overlapping, keep higher score
            if score > current[2]:
                current = list(det)
        else:
            # New follower
            merged.append((current[0], current[1]))
            current = list(det)

    merged.append((current[0], current[1]))

    # Limit to max_followers
    if len(merged) > max_followers:
        logger.warning(f"Detected {len(merged)} followers, limiting to {max_followers}")
        merged = merged[:max_followers]

    return merged


def predict_digit_easyocr(reader, digit_28x28):
    """
    使用EasyOCR预测单个数字并净化结果

    参数：
        reader: EasyOCR Reader实例
        digit_28x28: 28x28灰度图像

    返回：
        单个数字字符串，失败时返回""
    """
    if reader is None:
        return ""

    try:
        img_uint8 = digit_28x28.astype(np.uint8)
        result = reader.readtext(img_uint8, allowlist='0123456789', detail=0)
        prediction = ''.join(result) if result else ""

        # Sanitize to single digit
        sanitized = sanitize_single_digit_result(prediction)
        return sanitized
    except Exception as e:
        logger.error(f"EasyOCR prediction failed: {e}")
        return "error"


def predict_digit_mnist(session, digit_28x28):
    """
    使用MNIST ONNX模型预测单个数字

    参数：
        session: ONNX推理会话
        digit_28x28: 28x28灰度图像

    返回：
        预测的数字（0-9），失败时返回-1
    """
    if session is None:
        return -1

    try:
        input_shape = session.get_inputs()[0].shape
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name

        x = digit_28x28.astype(np.float32) / 255.0

        if len(input_shape) == 2:
            x = x.reshape(1, 784)
        elif len(input_shape) == 4:
            x = np.expand_dims(np.expand_dims(x, axis=0), axis=0)
        else:
            logger.warning(f"Unexpected MNIST input shape: {input_shape}")
            return -1

        result = session.run([output_name], {input_name: x})
        prediction = int(np.argmax(result[0]))
        return prediction
    except Exception as e:
        logger.error(f"MNIST prediction failed: {e}")
        return -1


def recognize_hp_with_fallback(digit_list, easyocr_reader, mnist_session):
    """
    使用按数字回退策略识别HP数字：
    - 首先对每个数字尝试EasyOCR（带净化）
    - 如果EasyOCR失败/为空，则对该数字回退到MNIST
    - 两个模型都可能为None（对该数字回退到"?"）

    参数：
        digit_list: 28x28灰度图像列表（1或2个数字）
        easyocr_reader: EasyOCR Reader实例（或None）
        mnist_session: ONNX推理会话（或None）

    返回：
        HP值字符串（例如"5"，"12"），全部失败时返回"?"
    """
    final_digits = []

    for digit_img in digit_list:
        # Try EasyOCR first
        easyocr_pred = predict_digit_easyocr(easyocr_reader, digit_img)

        # Use EasyOCR if valid (not empty, not error)
        if easyocr_pred and easyocr_pred not in ["error", ""]:
            final_digits.append(easyocr_pred)
        else:
            # Fall back to MNIST
            mnist_pred = predict_digit_mnist(mnist_session, digit_img)
            if mnist_pred >= 0:
                final_digits.append(str(mnist_pred))
            else:
                # Both failed
                final_digits.append('?')

    return ''.join(final_digits)
