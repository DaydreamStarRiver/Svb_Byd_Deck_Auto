"""
游戏管理器
实现核心游戏逻辑和操作
"""

import cv2
import numpy as np
import random
import time
import logging
import os
from typing import Any, cast
from PIL import Image
from src.game.follower_manager import FollowerManager
from src.game.template_manager import TemplateManager
from src.game.game_actions import GameActions
from src.utils.gpu_utils import get_easyocr_reader
from src.utils.image_io import safe_imread
from src.utils.resource_utils import resource_path
from src.utils.card_filename import (
    normalize_card_base_name,
    parse_card_stem,
    parse_follower_stat_suffix,
)
from src.utils.hp_detection import (
    sliding_window_detect,
    merge_detections,
    recognize_hp_with_fallback,
)
from src.utils.mnist_preprocessor import MNISTPreprocessor
from src.config.paths import get_card_cost_dir
from src.config.game_constants import (
    ENEMY_HP_REGION,
    ENEMY_HP_REGION_UP,
    ENEMY_FOLLOWER_Y_ADJUST,
    ENEMY_FOLLOWER_Y_RANDOM,
    OUR_FOLLOWER_REGION,
    OUR_ATK_REGION,
    OUR_FOLLOWER_HSV,
    ENEMY_FOLLOWER_OFFSET_X,
    ENEMY_ATK_REGION,
    ENEMY_SHIELD_REGION,
    ENEMY_SHIELD_REGION_UP,
    ENEMY_ATK_HSV,
    HP_WINDOW_WIDTH,
    HP_WINDOW_HEIGHT,
    HP_SLIDE_STEP,
    HP_MIN_FOLLOWER_GAP,
    HP_MAX_FOLLOWERS,
    HP_RED_BG_THRESHOLD,
    HP_OTHER_THRESHOLD,
    HP_DIGIT_THRESHOLD,
    HP_BRIGHT_RED_V_THRESHOLD,
)

logger = logging.getLogger(__name__)
cv2 = cast(Any, cv2)


class GameManager:
    """游戏管理器类"""

    def __init__(self, device_state):
        self.device_state = device_state
        self.follower_manager = FollowerManager()
        # 传递设备配置给模板管理器
        self.template_manager = TemplateManager(device_state.device_config)
        self.game_actions = GameActions(device_state)
        self.state_machine: Any = None
        self._board_sift_templates: dict[str, dict[str, Any]] | None = None
        self.reader = get_easyocr_reader()

        # 加载MNIST模型用于HP识别的后备方案
        self.mnist_session = None
        self.logger = logger
        mnist_path = "models/mnist_adv.onnx"
        if not os.path.exists(mnist_path):
            mnist_path = resource_path(mnist_path)
        if os.path.exists(mnist_path):
            try:
                import onnxruntime
                self.mnist_session = onnxruntime.InferenceSession(mnist_path, providers=["CPUExecutionProvider"])
                logger.info(f"MNIST模型已加载: {mnist_path}")
            except Exception as e:
                logger.warning(f"加载MNIST模型失败: {e}，将仅使用EasyOCR")
        else:
            logger.warning(f"未找到MNIST模型: {mnist_path}，将仅使用EasyOCR")

        # 加载HP检测遮罩（内部资源，不作为用户可编辑模板的一部分）
        self.hp_mask = None
        self._hp_mask_warning_logged = False
        mask_candidates = [
            resource_path(os.path.join("src", "masks", "hp_mask.png")),
            # Backward compatibility (older layouts might ship it under templates).
            self.template_manager.get_template_path("hp_mask.png"),
        ]

        mask_path = ""
        for p in mask_candidates:
            if p and os.path.exists(p):
                mask_path = p
                break

        if mask_path:
            self.hp_mask = safe_imread(mask_path, cv2.IMREAD_GRAYSCALE)
            if self.hp_mask is not None:
                logger.info(f"HP遮罩已加载: {mask_path}, 尺寸: {self.hp_mask.shape}")
            else:
                logger.warning(f"HP遮罩文件读取失败: {mask_path}，将不使用遮罩")
        else:
            logger.warning("未找到HP遮罩文件，将不使用遮罩")

        # 创建MNIST预处理器用于HP识别
        self.hp_preprocessor = MNISTPreprocessor(
            target_size=(28, 28),
            intermediate_size=(128, 128),
            margin=0,
            remove_brown_edges=True,
            denoise_strength=2,
            dilation_iterations=2,
            detect_double_digit=True,
            split_threshold=10,
            bright_red_v_threshold=HP_BRIGHT_RED_V_THRESHOLD,
            red_erosion_iterations=0,
            red_edge_margin=0,
            green_erosion_iterations=1,
            green_edge_margin=0
        )
        logger.info("HP识别预处理器已初始化")

        # 设置设备状态中的随从管理器
        device_state.follower_manager = self.follower_manager

    def scan_enemy_ATK(self, screenshot, debug_flag=False):
        """扫描敌方攻击力数值位置，返回敌方随从位置列表"""
        enemy_atk_positions = []

        # 确保debug目录存在
        if debug_flag:
            os.makedirs("debug", exist_ok=True)

        region_blue = screenshot.crop(ENEMY_ATK_REGION)
        region_blue_np = np.array(region_blue)
        region_blue_cv = cv2.cvtColor(region_blue_np, cv2.COLOR_RGB2BGR)
        hsv_blue = cv2.cvtColor(region_blue_cv, cv2.COLOR_BGR2HSV)
        settings = ENEMY_ATK_HSV
        lower_blue = np.array(settings["blue"][:3])
        upper_blue = np.array(settings["blue"][3:])
        blue_mask = cv2.inRange(hsv_blue, lower_blue, upper_blue)

        kernel = np.ones((1, 1), np.uint8)
        blue_eroded = cv2.erode(
            cv2.dilate(blue_mask, kernel, iterations=1), kernel, iterations=1
        )
        blue_contours, _ = cv2.findContours(
            blue_eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # 创建用于调试的图像
        debug_img = region_blue_cv.copy() if debug_flag else None

        for cnt in blue_contours:
            rect = cv2.minAreaRect(cnt)
            (x, y), (w, h), angle = rect
            area = cv2.contourArea(cnt)
            max_dim = max(w, h)
            min_dim = min(w, h)
            center_x, center_y = rect[0]

            if 15 < max_dim < 40 and 3 < min_dim < 15 and area < 200:
                # 区域截图中敌方随从的中心位置
                in_card_center_x_full = center_x + 50
                # 全局中敌方随从中心位置
                center_x_full = in_card_center_x_full + 263

                # 添加到结果列表
                enemy_atk_positions.append((center_x_full, 227 + random.randint(-5, 5)))

                # Debug 标注
                if debug_flag:
                    # 画中心点
                    if debug_img is not None:
                        cv2.circle(
                            debug_img, (int(center_x), int(center_y)), 5, (0, 0, 255), -1
                        )
                    # 画外接矩形
                    box = cv2.boxPoints(rect).astype(int)
                    if debug_img is not None:
                        cv2.drawContours(debug_img, [box], 0, (0, 255, 0), 2)
                    # 添加标注文字
                    label = f"W:{w:.1f} H:{h:.1f} Area:{area:.0f}"
                    if debug_img is not None:
                        cv2.putText(
                            debug_img,
                            label,
                            (int(center_x), int(center_y)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 0, 0),
                            1,
                        )

        # 保存debug图像
        if debug_flag and debug_img is not None:
            timestamp = int(time.time() * 1000)
            cv2.imwrite(f"debug/enemy_ATK_debug_{timestamp}.png", debug_img)
            cv2.imwrite(f"debug/enemy_ATK_mask_{timestamp}.png", blue_eroded)

        return enemy_atk_positions

    def scan_enemy_followers(
        self,
        screenshot,
        debug_flag: bool = False,
        is_select: bool = False,
    ):
        """
        检测场上的敌方随从位置与血量 (Improved with sliding window + fallback recognition)

        Returns:
            List[Tuple[int, int, str, str]]: [(x, y, "normal", hp_value), ...]
            - x, y: Screen coordinates (calibrated)
            - "normal": Follower type (always "normal" for compatibility)
            - hp_value: HP as string (e.g., "5", "99")
        """
        timestamp = int(time.time() * 1000)
        hp_region = ENEMY_HP_REGION
        if is_select:
            hp_region = ENEMY_HP_REGION_UP
        try:
            # 确保debug目录存在
            if debug_flag:
                os.makedirs("debug", exist_ok=True)
                screenshot_np = np.array(screenshot)
                screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)
                cv2.imwrite(f"debug/screenshot_{timestamp}.png", screenshot_cv)

            # Step 1: Crop enemy HP region
            x1, y1, x2, y2 = hp_region
            region = screenshot.crop(hp_region)
            region_np = np.array(region)
            region_cv = cv2.cvtColor(region_np, cv2.COLOR_RGB2BGR)

            if self.hp_mask is None and not self._hp_mask_warning_logged:
                logger.warning("HP遮罩不可用：启用无遮罩兜底检测（精度可能下降）")
                self._hp_mask_warning_logged = True

            # Step 2: Sliding window detection with color analysis
            detections_raw = sliding_window_detect(
                region_cv,
                self.hp_mask,
                window_width=HP_WINDOW_WIDTH,
                window_height=HP_WINDOW_HEIGHT,
                slide_step=HP_SLIDE_STEP,
                red_bg_threshold=HP_RED_BG_THRESHOLD,
                other_threshold=HP_OTHER_THRESHOLD,
                digit_threshold=HP_DIGIT_THRESHOLD,
                bright_red_v_threshold=HP_BRIGHT_RED_V_THRESHOLD
            )

            # Step 3: Merge overlapping detections
            detections = merge_detections(
                detections_raw,
                min_gap=HP_MIN_FOLLOWER_GAP,
                max_followers=HP_MAX_FOLLOWERS
            )

            logger.info(f"检测到 {len(detections)} 个敌方随从HP位置")

            # Step 4: Recognize HP for each detection
            enemy_followers = []
            for idx, (center_x, width) in enumerate(detections):
                # Crop HP window
                crop_x1 = max(0, center_x - width // 2)
                crop_x2 = min(region_cv.shape[1], center_x + width // 2)
                hp_crop = region_cv[0:HP_WINDOW_HEIGHT, crop_x1:crop_x2].copy()

                # Convert to RGBA and apply mask
                hp_crop_rgba = cv2.cvtColor(hp_crop, cv2.COLOR_BGR2BGRA)
                if self.hp_mask is not None:
                    mask_resized = cv2.resize(self.hp_mask, (hp_crop_rgba.shape[1], hp_crop_rgba.shape[0]), interpolation=cv2.INTER_NEAREST)
                    hp_crop_rgba[:, :, 3] = mask_resized
                else:
                    # If no mask, use full alpha
                    hp_crop_rgba[:, :, 3] = 255

                # Save debug crop if requested
                if debug_flag:
                    debug_path = f"debug/hp_crop_{idx}_{timestamp}.png"
                    cv2.imwrite(debug_path, hp_crop_rgba)

                # Preprocess to 28x28
                digit_list = self.hp_preprocessor.preprocess(hp_crop_rgba, None)

                # Recognize with fallback (EasyOCR → MNIST)
                hp_value = recognize_hp_with_fallback(
                    digit_list,
                    self.reader,
                    self.mnist_session
                )

                # Fallback to "99" if recognition completely failed
                if not hp_value or hp_value in ["?", "error", "unknown", "none"]:
                    hp_value = "99"
                    logger.warning(f"HP识别失败，使用默认值99 (位置: x={center_x})")

                # Calculate global screen coordinates
                enemy_x = x1 + center_x + ENEMY_FOLLOWER_OFFSET_X
                enemy_y = ENEMY_FOLLOWER_Y_ADJUST + random.randint(
                    -ENEMY_FOLLOWER_Y_RANDOM,
                    ENEMY_FOLLOWER_Y_RANDOM
                )

                enemy_followers.append((enemy_x, enemy_y, "normal", hp_value))

                logger.info(f"随从 {idx+1}: HP={hp_value}, X={enemy_x}, Y={enemy_y}")

            # Debug visualization if requested
            if debug_flag and enemy_followers:
                timestamp = int(time.time() * 1000)
                debug_img = region_cv.copy()
                for idx, (center_x, width) in enumerate(detections):
                    # Draw detection window
                    x_left = center_x - width // 2
                    x_right = center_x + width // 2
                    cv2.rectangle(debug_img, (x_left, 0), (x_right, HP_WINDOW_HEIGHT), (0, 255, 0), 2)
                    cv2.circle(debug_img, (center_x, HP_WINDOW_HEIGHT // 2), 5, (0, 255, 255), -1)
                    # Add HP label
                    hp_text = enemy_followers[idx][3] if idx < len(enemy_followers) else "?"
                    cv2.putText(debug_img, f"HP:{hp_text}", (center_x - 20, 15),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                cv2.imwrite(f"debug/enemy_hp_detection_{timestamp}.png", debug_img)

            if enemy_followers:
                return enemy_followers

            return []

        except Exception as e:
            logger.error(f"Enemy follower detection failed: {e}", exc_info=True)
            return []

    def scan_our_followers(
        self,
        screenshot,
        debug_flag: bool = False,
        extra_shots: int = 2,
        sort_desc: bool = False,
        shot_delay_range=(0.12, 0.22),
        with_names: bool = True,
    ):
        """检测场上的我方随从位置和状态。

        当前策略：单帧检测，不做跨帧合并。
        为兼容调用方，保留 ``extra_shots`` / ``shot_delay_range`` 参数，
        但不再用于跨帧采样。

        Args:
            screenshot: 当前截图（PIL Image）
            debug_flag: 是否输出debug图片
            extra_shots: 保留参数（单帧模式下不使用）
            sort_desc: True=按x坐标从右到左排序；False=从左到右排序
            shot_delay_range: 保留参数（单帧模式下不使用）
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        base_shot = screenshot
        if base_shot is None and hasattr(self.device_state, "take_screenshot"):
            try:
                base_shot = self.device_state.take_screenshot()
            except Exception:
                base_shot = None
        if base_shot is None:
            return []

        def _type_priority(t: str) -> int:
            return {"green": 3, "yellow": 2, "normal": 1}.get(t, 0)

        # Wider x-axis dedup threshold to absorb animation jitter and mixed
        # contour artifacts (e.g. one follower detected as both green+normal).
        dedup_x_thresh = 96

        def _dedup_by_x(followers, x_thresh: int = dedup_x_thresh):
            """按x轴聚类去重：同一随从保留更高优先级类型，并尽量保留名字"""
            if not followers:
                return []
            followers_sorted = sorted(followers, key=lambda p: p[0])
            clusters = []  # [{'x':float, 'items':[...]}]
            for item in followers_sorted:
                x = int(item[0])
                matched = False
                for c in clusters:
                    if abs(x - c["x"]) < x_thresh:
                        c["items"].append(item)
                        # 更新中心（简单平均即可）
                        c["x"] = (c["x"] * (len(c["items"]) - 1) + x) / len(c["items"])
                        matched = True
                        break
                if not matched:
                    clusters.append({"x": float(x), "items": [item]})

            merged = []
            for c in clusters:
                items = c["items"]
                # 选类型优先级最高的条目
                best = max(items, key=lambda it: _type_priority(it[2]))
                bx, by, bt = int(best[0]), best[1], best[2]

                # 名字：优先取任意非空名字（若冲突取出现次数最多）
                names = [it[3] for it in items if len(it) > 3 and it[3]]
                name = None
                if names:
                    from collections import Counter

                    name = Counter(names).most_common(1)[0][0]

                merged.append((bx, by, bt, name))

            return merged

        # 单帧识别：返回(positions, rectangles)
        def recognize_followers(shot, debug_flag, *, collect_rectangles: bool):
            # 原有的单次随从识别逻辑
            if shot is None:
                return [], []
            # 创建debug文件夹
            if debug_flag:
                os.makedirs("debug", exist_ok=True)
            region_color = shot.crop(OUR_FOLLOWER_REGION)
            region_color_np = np.array(region_color)
            region_color_cv = cv2.cvtColor(region_color_np, cv2.COLOR_RGB2BGR)
            region_blue = shot.crop(OUR_ATK_REGION)
            region_blue_np = np.array(region_blue)
            region_blue_cv = cv2.cvtColor(region_blue_np, cv2.COLOR_RGB2BGR)
            if debug_flag:
                # 为debug创建更大的区域，包含文字空间
                debug_region_color = (
                    OUR_FOLLOWER_REGION[0],
                    OUR_FOLLOWER_REGION[1] - 30,
                    OUR_FOLLOWER_REGION[2],
                    OUR_FOLLOWER_REGION[3] + 30,
                )
                debug_color = shot.crop(debug_region_color)
                debug_color_np = np.array(debug_color)
                debug_img_color = cv2.cvtColor(debug_color_np, cv2.COLOR_RGB2BGR)

                debug_region_blue = (
                    OUR_ATK_REGION[0],
                    OUR_ATK_REGION[1] - 30,
                    OUR_ATK_REGION[2],
                    OUR_ATK_REGION[3] + 30,
                )
                debug_blue = shot.crop(debug_region_blue)
                debug_blue_np = np.array(debug_blue)
                debug_img_blue = cv2.cvtColor(debug_blue_np, cv2.COLOR_RGB2BGR)
            else:
                debug_img_color = None
                debug_img_blue = None
            dbg_color = cast(Any, debug_img_color)
            dbg_blue = cast(Any, debug_img_blue)
            cv2_any = cast(Any, cv2)
            hsv_color = cv2.cvtColor(region_color_cv, cv2.COLOR_BGR2HSV)
            hsv_blue = cv2.cvtColor(region_blue_cv, cv2.COLOR_BGR2HSV)
            settings = OUR_FOLLOWER_HSV

            # 说明：游戏里“可攻击”的光圈/边框在不同动画/超进化等状态下颜色范围会漂移。
            # 这里把 green/green2、yellow1/yellow2 合并成一个mask，提高检出率。
            lower_green = np.array(settings["green"][:3])
            upper_green = np.array(settings["green"][3:])
            lower_green2 = np.array(settings.get("green2", settings["green"])[:3])
            upper_green2 = np.array(settings.get("green2", settings["green"])[3:])

            lower_yellow1 = np.array(settings["yellow1"][:3])
            upper_yellow1 = np.array(settings["yellow1"][3:])
            lower_yellow2 = np.array(settings.get("yellow2", settings["yellow1"])[:3])
            upper_yellow2 = np.array(settings.get("yellow2", settings["yellow1"])[3:])
            lower_blue = np.array(settings["blue"][:3])
            upper_blue = np.array(settings["blue"][3:])
            green_mask1 = cv2.inRange(hsv_color, lower_green, upper_green)
            green_mask2 = cv2.inRange(hsv_color, lower_green2, upper_green2)
            green_mask = cv2.bitwise_or(green_mask1, green_mask2)

            yellow_mask1 = cv2.inRange(hsv_color, lower_yellow1, upper_yellow1)
            yellow_mask2 = cv2.inRange(hsv_color, lower_yellow2, upper_yellow2)
            yellow1_mask = cv2.bitwise_or(yellow_mask1, yellow_mask2)
            blue_mask = cv2.inRange(hsv_blue, lower_blue, upper_blue)

            def vote_blue_only_follower_type(center_x_full: float):
                """对即将落为 normal 的 blue-only 随从做局部颜色投票。"""
                xhalf = 60
                mask_width = green_mask.shape[1]
                center_x_in_crop = int(round(center_x_full - OUR_FOLLOWER_REGION[0]))
                center_x_in_crop = max(0, min(mask_width - 1, center_x_in_crop))
                x1 = max(0, center_x_in_crop - xhalf)
                x2 = min(mask_width, center_x_in_crop + xhalf + 1)
                green_pixels = int(cv2.countNonZero(green_mask[:, x1:x2]))
                yellow_pixels = int(cv2.countNonZero(yellow1_mask[:, x1:x2]))
                follower_type = "normal"
                if green_pixels >= 120 and green_pixels > yellow_pixels * 2:
                    follower_type = "green"
                elif yellow_pixels >= 120 and yellow_pixels > green_pixels * 2:
                    follower_type = "yellow"
                return follower_type, green_pixels, yellow_pixels, x1, x2

            kernel = np.ones((1, 1), np.uint8)
            green_eroded = cv2.erode(
                cv2.dilate(green_mask, kernel, iterations=1), kernel, iterations=1
            )
            yellow1_eroded = cv2.erode(
                cv2.dilate(yellow1_mask, kernel, iterations=1), kernel, iterations=1
            )
            blue_eroded = cv2.erode(
                cv2.dilate(blue_mask, kernel, iterations=1), kernel, iterations=1
            )

            # NOTE: These are cheap and deterministic; threadpool overhead is larger
            # than the benefit for such small workloads.
            green_contours = cv2.findContours(
                green_eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )[0]
            yellow1_contours = cv2.findContours(
                yellow1_eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )[0]
            blue_contours = cv2.findContours(
                blue_eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )[0]
            follower_positions = []
            shot_all_follower_positions = []
            green_rects = []
            green_centers = []
            yellow_centers = []
            # 处理绿色框
            for cnt in green_contours:
                rect = cv2.minAreaRect(cnt)
                (x, y), (w, h), angle = rect
                area = cv2.contourArea(cnt)
                min_dim = min(w, h)
                max_dim = max(w, h)
                # 新增：如果max_dim大于230，尝试用分水岭算法分割
                if max_dim > 230:
                    # 1. 提取该轮廓的mask
                    mask = np.zeros(region_color_cv.shape[:2], np.uint8)
                    cv2.drawContours(mask, [cnt], -1, 255, -1)
                    # 2. 对mask做距离变换
                    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
                    ret, sure_fg = cv2.threshold(dist, 0.5 * dist.max(), 255, 0)
                    sure_fg = np.uint8(sure_fg)
                    # 3. 标记不同目标
                    ret, markers = cv2_any.connectedComponents(sure_fg)
                    markers = markers + 1
                    markers[mask == 0] = 0
                    # 4. 分水岭
                    color_img = region_color_cv.copy()
                    cv2.watershed(color_img, markers)
                    # 5. 提取分割后每个目标的中心点
                    for label in range(2, np.max(markers) + 1):
                        pts = np.column_stack(np.where(markers == label))
                        if len(pts) == 0:
                            continue
                        cy, cx = np.mean(pts, axis=0)
                        center_x_full = cx + 0  # region_color区域内坐标，加偏移
                        center_y_full = cy + 0
                        center_x_full += 176
                        center_y_full += 295
                        # 绿色随从去重检查（分水岭分割后）
                        is_duplicate = False
                        for gx, gy in green_centers:
                            if abs(center_x_full - gx) < 50:
                                is_duplicate = True
                                break
                        if is_duplicate:
                            continue
                        green_centers.append((center_x_full, center_y_full))
                        follower_positions.append(
                            (center_x_full, center_y_full, "green")
                        )
                        if debug_flag:
                            # 调整debug坐标，因为debug图像包含了更大的区域
                            debug_cx = int(cx)
                            debug_cy = int(cy) + 30  # 向下偏移30像素
                            cv2_any.circle(
                                dbg_color,
                                (debug_cx, debug_cy),
                                7,
                                (0, 255, 255),
                                2,
                            )
                    continue  # 分水岭分割后不再走后续大随从分左右中心逻辑
                if 230 > max_dim > 80:
                    if max_dim > 230:
                        box = cv2.boxPoints(rect)
                        box = box.astype(np.int32)
                        if w > h:
                            cx, cy = rect[0]
                            left_center = (cx - w / 4, cy)
                            right_center = (cx + w / 4, cy)
                        else:
                            cx, cy = rect[0]
                            left_center = (cx, cy - h / 4)
                            right_center = (cx, cy + h / 4)
                        left_center_full = (left_center[0] + 176, left_center[1] + 295)
                        right_center_full = (
                            right_center[0] + 176,
                            right_center[1] + 295,
                        )
                        green_centers.append(left_center_full)
                        green_centers.append(right_center_full)
                        follower_positions.append(
                            (left_center_full[0], left_center_full[1], "green")
                        )
                        follower_positions.append(
                            (right_center_full[0], right_center_full[1], "green")
                        )
                        if debug_flag:
                            # 绘制外接矩形、中心点、长宽、面积
                            # 调整debug坐标，因为debug图像包含了更大的区域
                            debug_box = box.copy()
                            debug_box[:, 1] += 30  # Y坐标向下偏移30像素
                            cv2_any.drawContours(
                                dbg_color, [debug_box], 0, (0, 255, 0), 2
                            )
                            lcx, lcy = int(left_center[0]), int(left_center[1])
                            rcx, rcy = int(right_center[0]), int(right_center[1])
                            # 调整debug坐标，因为debug图像包含了更大的区域
                            debug_lcx = lcx
                            debug_lcy = lcy + 30
                            debug_rcx = rcx
                            debug_rcy = rcy + 30
                            cv2_any.circle(
                                dbg_color,
                                (debug_lcx, debug_lcy),
                                5,
                                (0, 0, 255),
                                -1,
                            )
                            cv2_any.circle(
                                dbg_color,
                                (debug_rcx, debug_rcy),
                                5,
                                (0, 0, 255),
                                -1,
                            )
                            label = f"W:{w:.1f} H:{h:.1f} Area:{area:.0f}"
                            cv2_any.putText(
                                dbg_color,
                                label,
                                (debug_lcx, debug_lcy - 10),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                (255, 0, 0),
                                1,
                            )
                            cv2_any.putText(
                                dbg_color,
                                label,
                                (debug_rcx, debug_rcy - 10),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                (255, 0, 0),
                                1,
                            )
                    else:
                        center_x, center_y = rect[0]
                        center_x_full = center_x + 176
                        center_y_full = center_y + 295
                        green_centers.append((center_x_full, center_y_full))
                        follower_positions.append(
                            (center_x_full, center_y_full, "green")
                        )
                        if debug_flag:
                            box = cv2.boxPoints(rect)
                            box = box.astype(np.int32)
                            # 调整debug坐标，因为debug图像包含了更大的区域
                            debug_box = box.copy()
                            debug_box[:, 1] += 30  # Y坐标向下偏移30像素
                            cv2_any.drawContours(
                                dbg_color, [debug_box], 0, (0, 255, 0), 2
                            )
                            cx, cy = int(center_x), int(center_y)
                            # 调整debug坐标，因为debug图像包含了更大的区域
                            debug_cx = cx
                            debug_cy = cy + 30  # 向下偏移30像素
                            cv2_any.circle(
                                dbg_color,
                                (debug_cx, debug_cy),
                                5,
                                (0, 0, 255),
                                -1,
                            )
                            label = f"W:{w:.1f} H:{h:.1f} Area:{area:.0f}"
                            cv2_any.putText(
                                dbg_color,
                                label,
                                (debug_cx, debug_cy - 10),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                (255, 0, 0),
                                1,
                            )
            # 处理黄色框
            for cnt in yellow1_contours:
                rect = cv2.minAreaRect(cnt)
                (x, y), (w, h), angle = rect
                area = cv2.contourArea(cnt)
                min_dim = min(w, h)
                max_dim = max(w, h)
                if max_dim > 230:
                    # 1. 提取该轮廓的mask
                    mask = np.zeros(region_color_cv.shape[:2], np.uint8)
                    cv2.drawContours(mask, [cnt], -1, 255, -1)
                    # 2. 距离变换
                    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
                    ret, sure_fg = cv2.threshold(dist, 0.5 * dist.max(), 255, 0)
                    sure_fg = np.uint8(sure_fg)
                    # 3. 连通域
                    ret, markers = cv2_any.connectedComponents(sure_fg)
                    markers = markers + 1
                    markers[mask == 0] = 0
                    # 4. 分水岭
                    color_img = region_color_cv.copy()
                    cv2.watershed(color_img, markers)
                    # 5. 提取分割后每个目标的中心点
                    for label in range(2, np.max(markers) + 1):
                        pts = np.column_stack(np.where(markers == label))
                        if len(pts) == 0:
                            continue
                        cy, cx = np.mean(pts, axis=0)
                        center_x_full = cx + 176
                        center_y_full = cy + 295
                        # 判断是否在绿色框内
                        is_inside_green = False
                        for g_box in green_rects:
                            g_box_full = g_box.copy()
                            g_box_full[:, 0] += 176
                            g_box_full[:, 1] += 295
                            if (
                                cv2.pointPolygonTest(
                                    g_box_full, (center_x_full, center_y_full), False
                                )
                                >= 0
                            ):
                                is_inside_green = True
                                break
                        if is_inside_green:
                            continue  # 跳过该黄色点
                        # 黄色随从去重检查（分水岭分割后）
                        is_duplicate = False
                        for yx, yy in yellow_centers:
                            if abs(center_x_full - yx) < 50:
                                is_duplicate = True
                                break
                        if is_duplicate:
                            continue
                        follower_positions.append(
                            (center_x_full, center_y_full, "yellow")
                        )
                        yellow_centers.append((center_x_full, center_y_full))
                        if debug_flag:
                            # 调整debug坐标，因为debug图像包含了更大的区域
                            debug_cx = int(cx)
                            debug_cy = int(cy) + 30  # 向下偏移30像素
                            cv2_any.circle(
                                dbg_color,
                                (debug_cx, debug_cy),
                                7,
                                (0, 255, 255),
                                2,
                            )
                    continue  # 分水岭后不再走后续逻辑
                if 120 > max_dim > 90 or 230 > max_dim > 200:
                    center_x, center_y = rect[0]
                    center_x_full = center_x + 176
                    center_y_full = center_y + 295
                    box = cv2.boxPoints(rect)
                    yellow_box_poly = cv2.convexHull(box.astype(np.int32))
                    yellow_area = cv2.contourArea(yellow_box_poly)
                    is_inside_green = False
                    for g_box in green_rects:
                        g_poly = cv2.convexHull(g_box.astype(np.int32))
                        inter_area = cv2.intersectConvexConvex(yellow_box_poly, g_poly)[
                            0
                        ]
                        if yellow_area > 0 and inter_area / yellow_area > 0.7:
                            is_inside_green = True
                            break
                    follower_type = "green" if is_inside_green else "yellow"
                    follower_positions.append(
                        (center_x_full, center_y_full, follower_type)
                    )
                    if debug_flag:
                        box = cv2.boxPoints(rect)
                        box = box.astype(np.int32)
                        # 调整debug坐标，因为debug图像包含了更大的区域
                        debug_box = box.copy()
                        debug_box[:, 1] += 30  # Y坐标向下偏移30像素
                        cv2_any.drawContours(
                            dbg_color, [debug_box], 0, (0, 255, 255), 2
                        )
                        cx, cy = int(center_x), int(center_y)
                        # 调整debug坐标，因为debug图像包含了更大的区域
                        debug_cx = cx
                        debug_cy = cy + 30  # 向下偏移30像素
                        cv2_any.circle(
                            dbg_color, (debug_cx, debug_cy), 5, (0, 0, 255), -1
                        )
                        label = f"W:{w:.1f} H:{h:.1f} Area:{area:.0f}"
                        cv2_any.putText(
                            dbg_color,
                            label,
                            (debug_cx, debug_cy - 10),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 0, 0),
                            1,
                        )

            # 所有随从的蓝色攻击力位置
            for cnt in blue_contours:
                rect = cv2.minAreaRect(cnt)
                (x, y), (w, h), angle = rect
                area = cv2.contourArea(cnt)
                center_x, center_y = rect[0]
                min_dim = min(w, h)
                max_dim = max(w, h)
                if 15 < max_dim < 40 and 3 < min_dim < 15 and area < 200:
                    if collect_rectangles:
                        shot_all_follower_positions.append(
                            ((int(center_x + 263), 330), (int(center_x + 263 + 103), 463))
                        )
                    # 区域截图中卡我方随从的中心位置
                    in_card_center_x_full = center_x + 50
                    in_card_center_y_full = center_y - 46
                    # 全局中我方随从中心位置
                    center_x_full = in_card_center_x_full + 263
                    center_y_full = in_card_center_y_full + 466  # 420
                    # 检查是否在绿色中心点或黄色中心点x轴50像素以内
                    is_near_green_or_yellow = False

                    # 检查绿色中心点
                    for gx, gy in green_centers:
                        if abs(center_x_full - gx) <= 50:
                            is_near_green_or_yellow = True
                            break

                    # 检查黄色中心点
                    if not is_near_green_or_yellow:
                        for yx, yy in yellow_centers:
                            if abs(center_x_full - yx) <= 50:
                                is_near_green_or_yellow = True
                                break

                    # 如果距离所有绿色和黄色中心点都在50像素以外，则认为是普通随从
                    if not is_near_green_or_yellow:
                        (
                            follower_type,
                            vote_green_pixels,
                            vote_yellow_pixels,
                            vote_x1,
                            vote_x2,
                        ) = vote_blue_only_follower_type(center_x_full)
                        follower_positions.append(
                            (center_x_full, center_y_full, follower_type)
                        )
                        if debug_flag:
                            debug_vote_x1 = vote_x1
                            debug_vote_x2 = max(vote_x1, vote_x2 - 1)
                            cv2_any.rectangle(
                                dbg_color,
                                (debug_vote_x1, 30),
                                (debug_vote_x2, dbg_color.shape[0] - 31),
                                (255, 0, 255),
                                1,
                            )
                            vote_label = (
                                f"vote {follower_type} G:{vote_green_pixels} "
                                f"Y:{vote_yellow_pixels}"
                            )
                            cv2_any.putText(
                                dbg_color,
                                vote_label,
                                (debug_vote_x1, 25),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.45,
                                (255, 0, 255),
                                1,
                            )
                    if debug_flag:
                        box = cv2.boxPoints(rect)
                        box = box.astype(np.int32)
                        # 调整debug坐标，因为debug图像包含了更大的区域
                        debug_box = box.copy()
                        debug_box[:, 1] += 30  # Y坐标向下偏移30像素
                        cv2_any.drawContours(dbg_blue, [debug_box], 0, (255, 0, 0), 2)
                        cx, cy = int(center_x), int(center_y)
                        # 调整debug坐标，因为debug图像包含了更大的区域
                        debug_cx = cx
                        debug_cy = cy + 30  # 向下偏移30像素
                        cv2_any.circle(
                            dbg_blue, (debug_cx, debug_cy), 5, (0, 0, 255), -1
                        )
                        label = f"W:{w:.1f} H:{h:.1f} Area:{area:.0f}"
                        cv2_any.putText(
                            dbg_blue,
                            label,
                            (debug_cx, debug_cy - 10),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 0, 0),
                            1,
                        )

            if debug_flag:
                import time

                timestamp = int(time.time() * 1000)
                cv2_any.imwrite(
                    f"debug/our_follower_region_{timestamp}.png", dbg_color
                )
                cv2_any.imwrite(f"debug/our_hp_region_{timestamp}.png", dbg_blue)

            follower_positions.sort(key=lambda pos: pos[0], reverse=sort_desc)
            return follower_positions, shot_all_follower_positions

        # 单帧HSV识别（不做跨帧合并）
        collect_rectangles = bool(with_names)
        followers, all_rectangles = recognize_followers(
            base_shot, debug_flag, collect_rectangles=collect_rectangles
        )
        followers = _dedup_by_x([(x, y, t, None) for (x, y, t) in followers])

        # 矩形区域去重（仅用于SIFT命名；左上角x轴在阈值内视为同一个随从区域）
        deduplicated_follower_positions = []
        if with_names and all_rectangles:
            for rect_coords in all_rectangles:
                (x1, y1), (x2, y2) = rect_coords
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                found = False
                for existing_rect in deduplicated_follower_positions:
                    (ex1, ey1), (ex2, ey2) = existing_rect
                    if abs(x1 - ex1) < dedup_x_thresh:
                        found = True
                        break
                if not found:
                    deduplicated_follower_positions.append(((x1, y1), (x2, y2)))

        # 新的SIFT识别逻辑：基于去重后的all_follower_positions矩形区域
        def perform_sift_recognition_on_rectangles(base_screenshot):
            """对去重后的all_follower_positions中的每个矩形区域进行SIFT识别"""
            import os
            cv2_any = cast(Any, cv2)

            supported_exts = (".png", ".jpg", ".jpeg", ".webp")

            # 准备截图数据
            if hasattr(base_screenshot, "shape"):
                cv_img = base_screenshot
            else:
                cv_img = np.array(base_screenshot)
                cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)

            # 加载模板图片
            def load_template_features(filename):
                """加载单个模板的特征"""
                if not str(filename or "").lower().endswith(supported_exts):
                    return None
                template_path = os.path.join(get_card_cost_dir(ensure=True), filename)
                if not os.path.exists(template_path):
                    return None
                tname = os.path.splitext(filename)[0]
                try:
                    # 使用PIL读取图片（处理P/LA/L等模式，避免OpenCV通道数异常）
                    with Image.open(template_path) as pil_img:
                        if pil_img.mode not in ("RGB", "RGBA"):
                            pil_img = pil_img.convert("RGBA")
                        template_img = np.array(pil_img)

                    if template_img is None:
                        return None
                    if template_img.dtype != np.uint8:
                        template_img = template_img.astype(np.uint8, copy=False)

                    # 转为OpenCV常用BGR三通道
                    if template_img.ndim == 2:  # Gray
                        template_img = cv2.cvtColor(template_img, cv2.COLOR_GRAY2BGR)
                    elif template_img.ndim == 3:
                        ch = template_img.shape[2]
                        if ch == 4:
                            template_img = cv2.cvtColor(template_img, cv2.COLOR_RGBA2BGR)
                        elif ch == 3:
                            template_img = cv2.cvtColor(template_img, cv2.COLOR_RGB2BGR)
                        elif ch == 1:
                            template_img = cv2.cvtColor(template_img[:, :, 0], cv2.COLOR_GRAY2BGR)
                        else:
                            return None
                    else:
                        return None
                except Exception:
                    return None

                TEMPLATE_SCALE_FACTOR = 0.4

                # 截取模板图片中的指定区域
                TEMPLATE_RECT = (101, 151, 442, 568)
                tx1, ty1, tx2, ty2 = TEMPLATE_RECT
                template = template_img[ty1:ty2, tx1:tx2]
                if template.size == 0:
                    return None

                # 仅对模板应用缩放（关键修改）
                if TEMPLATE_SCALE_FACTOR != 1.0:
                    new_width = int(template.shape[1] * TEMPLATE_SCALE_FACTOR)
                    new_height = int(template.shape[0] * TEMPLATE_SCALE_FACTOR)
                    if new_width <= 0 or new_height <= 0:
                        return None
                    template = cv2.resize(
                        template, (new_width, new_height), interpolation=cv2.INTER_AREA
                    )

                # 图像预处理
                template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                template_gray = cv2.equalizeHist(template_gray)
                template_gray = cv2.GaussianBlur(template_gray, (3, 3), 0.5)

                # SIFT特征提取
                sift = cv2_any.SIFT_create(
                    nfeatures=0, contrastThreshold=0.02, edgeThreshold=15, sigma=1.6
                )
                tkp, tdes = sift.detectAndCompute(template_gray, None)
                if tdes is not None:
                    return tname, {
                        "template": template,
                        "keypoints": tkp,
                        "descriptors": tdes,
                    }
                return None

            # 加载所有模板（缓存，避免每次扫描重复读取磁盘）
            if getattr(self, "_board_sift_templates", None) is None:
                template_dir = get_card_cost_dir(ensure=True)
                template_files = [
                    f
                    for f in os.listdir(template_dir)
                    if str(f or "").lower().endswith(supported_exts)
                ]
                card_templates = {}

                with ThreadPoolExecutor(max_workers=min(8, len(template_files) or 1)) as executor:
                    futures = [
                        executor.submit(load_template_features, filename)
                        for filename in template_files
                    ]
                    for future in as_completed(futures):
                        try:
                            result = future.result()
                            if result is not None:
                                tname, template_info = result
                                card_templates[tname] = template_info
                        except Exception as e:
                            import logging

                            logging.error(f"模板加载异常: {e}")
                            continue

                self._board_sift_templates = card_templates
            else:
                card_templates = cast(dict[str, dict[str, Any]], self._board_sift_templates)

            # Build a stable runtime name map for board recognition.
            # Prefer names with explicit follower stats suffix (e.g. _4_4), so
            # runtime can derive attacker ATK/HP and apply evolve(+2/+2,+3/+3)
            # correctly. When matched template is *_evo without stats, fallback
            # to a sibling template of the same base card that has stats.
            runtime_name_map = {}
            stat_name_by_base = {}
            for tname in list(card_templates.keys()):
                try:
                    _c, _e, parsed_name = parse_card_stem(str(tname or ""))
                except Exception:
                    parsed_name = str(tname or "")
                parsed_name = str(parsed_name or "")
                base_key = normalize_card_base_name(parsed_name)
                _base, atk_i, hp_i = parse_follower_stat_suffix(parsed_name)
                if base_key and atk_i is not None and hp_i is not None and base_key not in stat_name_by_base:
                    stat_name_by_base[base_key] = parsed_name

            for tname in list(card_templates.keys()):
                try:
                    _c, _e, parsed_name = parse_card_stem(str(tname or ""))
                except Exception:
                    parsed_name = str(tname or "")
                parsed_name = str(parsed_name or "")
                _base, atk_i, hp_i = parse_follower_stat_suffix(parsed_name)
                if atk_i is not None and hp_i is not None:
                    runtime_name_map[str(tname)] = parsed_name
                    continue

                base_key = normalize_card_base_name(parsed_name)
                fallback_with_stats = stat_name_by_base.get(base_key)
                runtime_name_map[str(tname)] = str(fallback_with_stats or parsed_name)

            # 对每个矩形区域进行SIFT识别
            results = []
            for rect_coords in deduplicated_follower_positions:
                (x1, y1), (x2, y2) = rect_coords

                # 确保坐标为整数
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

                # 截取矩形区域
                rect_img = cv_img[y1:y2, x1:x2]
                if rect_img.size == 0:
                    continue

                # 图像预处理
                rect_gray = cv2.cvtColor(rect_img, cv2.COLOR_BGR2GRAY)
                rect_gray = cv2.equalizeHist(rect_gray)
                rect_gray = cv2.GaussianBlur(rect_gray, (3, 3), 0.5)

                # SIFT特征提取
                sift = cv2_any.SIFT_create(
                    nfeatures=0, contrastThreshold=0.02, edgeThreshold=15, sigma=1.2
                )
                rkp, rdes = sift.detectAndCompute(rect_gray, None)

                if rdes is None or len(rdes) < 2:
                    continue

                # 与所有模板进行匹配
                best_match = None
                best_confidence = 0

                for tname, tinfo in card_templates.items():
                    tdes = tinfo["descriptors"]
                    if tdes is None or len(tdes) < 2:
                        continue

                    # FLANN匹配
                    FLANN_INDEX_KDTREE = 1
                    index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=8)
                    search_params = dict(checks=100)
                    flann = cv2_any.FlannBasedMatcher(
                        cast(dict[str, Any], index_params),
                        cast(dict[str, Any], search_params),
                    )
                    try:
                        matches = flann.knnMatch(tdes, rdes, k=2)
                    except Exception:
                        continue

                    good_matches = []
                    for match_pair in matches:
                        if len(match_pair) != 2:
                            continue
                        m, n = match_pair
                        if m.distance < 0.7 * n.distance:
                            good_matches.append(m)

                    if len(good_matches) < 3:
                        continue

                    # 计算置信度
                    avg_distance = np.mean([m.distance for m in good_matches])
                    if avg_distance <= 120:
                        distance_score = 1.0
                    elif avg_distance <= 250:
                        distance_score = 1.0 - (avg_distance - 120) / 130
                    else:
                        distance_score = max(0, 1.0 - (avg_distance - 250) / 150)

                    match_ratio = len(good_matches) / len(tdes)
                    confidence = distance_score * match_ratio

                    if confidence >= 0.01 and confidence > best_confidence:
                        best_confidence = confidence
                        best_match = tname

                if best_match is not None:
                    # 计算矩形中心点
                    center_x = int((x1 + x2) // 2)
                    center_y = int((y1 + y2) // 2)

                    name = runtime_name_map.get(str(best_match), "")
                    if not name:
                        if "_" in best_match:
                            try:
                                _, _, name = parse_card_stem(best_match)
                            except Exception:
                                name = best_match.split("_", 1)[1]
                        else:
                            name = best_match

                    name = str(name or "").strip()
                    if not name:
                        continue

                    results.append((center_x, center_y, name))

            return results

        sift_results = []
        if with_names and deduplicated_follower_positions:
            try:
                sift_results = perform_sift_recognition_on_rectangles(base_shot)
            except Exception as e:
                logger.debug(f"我方随从SIFT命名失败，保留位置/类型结果: {e}")

        def attach_names(followers):
            named = []
            for x, y, t, _ in followers:
                x = int(x)
                name = None
                best_match_distance = float("inf")
                for cx, cy, sift_name in sift_results:
                    x_distance = abs(cx - x)
                    if x_distance < 30 and x_distance < best_match_distance:
                        name = sift_name
                        best_match_distance = x_distance
                named.append((x, y, t, name))
            return named

        if with_names and sift_results:
            followers = attach_names(followers)

        merged = [
            (int(x), 399 + random.randint(-7, 7), t, name)
            for (x, y, t, name) in followers
        ]
        merged = sorted(merged, key=lambda pos: pos[0], reverse=sort_desc)
        if len(merged) > 5:
            merged = sorted(
                merged,
                key=lambda it: (1 if (len(it) > 3 and it[3]) else 0, _type_priority(it[2]), int(it[0])),
                reverse=True,
            )[:5]
            merged = sorted(merged, key=lambda pos: pos[0], reverse=sort_desc)

        if debug_flag:
            self.device_state.logger.info(f"我方当前场上随从(单帧): {merged}")
        else:
            self.device_state.logger.debug(f"我方当前场上随从(单帧): {merged}")
        return merged

    def scan_shield_targets(self, debug_flag=False):
        """扫描护盾（三帧检测，2/3 命中才判定为真守护）。"""

        shot_results = []
        max_shots = 3

        try:
            debug_mode = bool(
                isinstance(getattr(self.device_state, "config", None), dict)
                and self.device_state.config.get("ui", {}).get("debug_mode")
            )
        except Exception:
            debug_mode = False

        for idx in range(max_shots):
            screenshot = self.device_state.take_screenshot()
            if screenshot is None:
                targets = []
            else:
                targets = list(self._scan_shield_targets_single(screenshot, debug_flag) or [])

            if debug_flag or debug_mode:
                try:
                    self.device_state.logger.info(
                        f"[Scan][ward/full][{idx + 1}/{max_shots}] count={len(targets)} result={targets}"
                    )
                except Exception:
                    pass

            shot_results.append(list(targets))

            if idx < max_shots - 1:
                time.sleep(random.uniform(0.10, 0.15))

        if not shot_results:
            return []

        bucket_width = 55
        support = {}

        for rows in list(shot_results or []):
            seen_buckets = set()
            for pos in list(rows or []):
                if not isinstance(pos, (list, tuple)) or len(pos) < 2:
                    continue
                try:
                    px = int(pos[0])
                    py = int(pos[1])
                except Exception:
                    continue

                bucket = int(round(float(px) / float(bucket_width)))
                row = support.setdefault(bucket, {"count": 0, "samples": []})
                row["samples"].append((int(px), int(py)))
                if bucket not in seen_buckets:
                    row["count"] = int(row.get("count", 0) or 0) + 1
                    seen_buckets.add(bucket)

        consensus = []
        for bucket, info in list(support.items()):
            if int(info.get("count", 0) or 0) < 2:
                continue
            samples = list(info.get("samples") or [])
            if not samples:
                continue
            avg_x = int(round(sum(int(s[0]) for s in samples) / float(len(samples))))
            avg_y = int(round(sum(int(s[1]) for s in samples) / float(len(samples))))
            consensus.append((avg_x, avg_y))

        consensus.sort(key=lambda pos: int(pos[0]))
        return consensus

    def scan_shield_targets_for_enemy_followers(self, screenshot, enemy_followers, debug_flag=False, is_select=False):
        """在同一帧内将守护图标映射到敌方随从坐标。

        用于 target_resolver 的 `ward_or_highest_hp`：
        - enemy_followers 来自同一张 screenshot 的 HP 扫描结果
        - wards 直接按 x 轴映射到 enemy_followers，避免跨帧错配
        """

        if screenshot is None or not enemy_followers:
            return []

        detected_shields = self._extract_shield_points(
            screenshot,
            debug_flag=debug_flag,
            is_select=bool(is_select),
        )
        if not detected_shields:
            return []

        shield_targets = self._match_positions_with_shields(
            enemy_followers,
            detected_shields,
            x_tolerance=50,
        )
        shield_targets = sorted(shield_targets, key=lambda pos: int(pos[0]))
        return shield_targets

    def _extract_shield_points(self, screenshot, debug_flag=False, is_select=False):
        """Extract raw shield icon centers (global coordinates) from screenshot."""

        if screenshot is None:
            return []
        try:
            shield_region = ENEMY_SHIELD_REGION_UP if bool(is_select) else ENEMY_SHIELD_REGION
            region = screenshot.crop(shield_region)
            bgr_image = cv2.cvtColor(np.array(region), cv2.COLOR_RGB2BGR)
            return self._process_shield_image(
                bgr_image,
                debug_flag,
                region_offset=(int(shield_region[0]), int(shield_region[1])),
            )
        except Exception as e:
            import logging

            logging.error(f"护盾检测异常: {str(e)}")
            return []

    def _match_positions_with_shields(self, positions, detected_shields, x_tolerance=50):
        """Match arbitrary position list to shield centers by x-axis proximity."""

        if not positions or not detected_shields:
            return []

        out = []
        tol = max(1, int(x_tolerance))
        shield_xs = []
        for sp in list(detected_shields or []):
            try:
                shield_xs.append(int(sp[0]))
            except Exception:
                continue

        if not shield_xs:
            return []

        for p in list(positions or []):
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            try:
                px = int(p[0])
                py = int(p[1])
            except Exception:
                continue
            if any(abs(px - sx) < tol for sx in shield_xs):
                out.append((px, py))

        return out

    def _scan_shield_targets_single(self, screenshot, debug_flag=False):
        if screenshot is None:
            return []

        try:
            enemy_atk_positions = self.scan_enemy_ATK(screenshot, debug_flag)
            if not enemy_atk_positions:
                return []
        except Exception as e:
            import logging

            logging.error(f"敌方随从位置检测异常: {str(e)}")
            return []

        detected_shields = self._extract_shield_points(screenshot, debug_flag=debug_flag)
        if not detected_shields:
            return []

        shield_targets = self._match_positions_with_shields(
            enemy_atk_positions,
            detected_shields,
            x_tolerance=50,
        )

        # 按x轴排序，校准y轴坐标
        if shield_targets:
            shield_targets.sort(key=lambda pos: pos[0])
            shield_targets = [
                (pos[0], 227 + random.randint(-3, 3)) for pos in shield_targets
            ]

        return shield_targets

    def _process_shield_image(self, image, debug_flag, region_offset=None):
        """处理护盾图像"""
        shield_targets = []
        if isinstance(region_offset, (list, tuple)) and len(region_offset) >= 2:
            offset_x, offset_y = int(region_offset[0]), int(region_offset[1])
        else:
            offset_x, offset_y = ENEMY_SHIELD_REGION[0], ENEMY_SHIELD_REGION[1]

        if debug_flag:
            os.makedirs("debug", exist_ok=True)
            timestamp = int(time.time() * 1000)
            filename = f"debug/shield_debug_{timestamp}_raw.png"
            result = cv2.imwrite(filename, image)

        # 转换为HSV颜色空间
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([23, 46, 30]), np.array([89, 255, 255]))

        # # 形态学操作 - 使用椭圆核，分别进行腐蚀和膨胀（新方法）
        # kernel_size = 2  # 椭圆核大小
        # kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))

        # # 分别进行腐蚀和膨胀操作
        # erode_iterations = 1
        # dilate_iterations = 1

        # # 先进行腐蚀操作
        # if erode_iterations > 0:
        #     mask = cv2.erode(mask, kernel, iterations=erode_iterations)

        # # 再进行膨胀操作
        # if dilate_iterations > 0:
        #     mask = cv2.dilate(mask, kernel, iterations=dilate_iterations)

        # 形态学操作
        kernel = np.ones((1, 1), np.uint8)
        mask = cv2.erode(cv2.dilate(mask, kernel, iterations=1), kernel, iterations=1)
        # 查找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = cv2.contourArea(cnt)
            min_dim = min(w, h)
            max_dim = max(w, h)

            if 140 > max_dim > 80 and 72 > min_dim > 55 and area > 700:
                cx, cy = x + w // 2, y + h // 2
                # 自动转换为全屏坐标
                global_cx = cx + offset_x
                global_cy = cy + offset_y
                shield_targets.append((global_cx, global_cy))
                if debug_flag:
                    # 创建调试图像
                    debug_img = image.copy()
                    logging.info(
                        f"debug_img shape: {debug_img.shape}, dtype: {debug_img.dtype}"
                    )
                    # 画中心点
                    cv2.circle(debug_img, (cx, cy), 10, (0, 0, 255), -1)

                    # 最小外接矩形
                    rect = cv2.minAreaRect(cnt)
                    box = cv2.boxPoints(rect).astype(int)
                    cv2.drawContours(debug_img, [box], 0, (0, 255, 0), 2)

                    # 宽高面积标注
                    label = f"W:{w} H:{h} Area:{area:.0f}"
                    cv2.putText(
                        debug_img,
                        label,
                        (x, y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 255),
                        2,
                    )

                    # 保存调试图像
                    os.makedirs("debug", exist_ok=True)
                    timestamp = int(time.time() * 1000)
                    filename = (
                        f"debug/shield_debug_{timestamp}_{global_cx}_{global_cy}.png"
                    )
                    logging.info(f"准备保存护盾debug图片: {filename}")
                    result = cv2.imwrite(filename, debug_img)
                    if result:
                        logging.info(f"护盾debug图片已保存: {filename}")
                    else:
                        logging.error(f"护盾debug图片保存失败: {filename}")

        return shield_targets

    def card_can_choose_target_like_amulet(self, debug_flag=False):
        """扫描敌方可攻击目标，比如护符"""
        can_choosetargets = []
        screenshot = self.device_state.take_screenshot()
        if screenshot is None:
            return []
        can_choose_region = (160, 302, 1068, 315)
        region = screenshot.crop(can_choose_region)
        bgr_image = cv2.cvtColor(np.array(region), cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)
        lower_bound = np.array([4, 151, 28])
        upper_bound = np.array([89, 255, 255])
        mask = cv2.inRange(hsv, lower_bound, upper_bound)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = cv2.contourArea(cnt)
            if 500 < area < 1200:
                # 转换为全局坐标
                cx = x + w // 2
                global_x = can_choose_region[0] + cx
                can_choosetargets.append((global_x, 216 + random.randint(-5, 5)))
            if debug_flag:
                os.makedirs("debug", exist_ok=True)
                timestamp = int(time.time() * 1000)
                # 画出轮廓和中心点
                debug_img = bgr_image.copy()
                cv2.drawContours(debug_img, [cnt], 0, (0, 0, 255), 2)
                cv2.circle(debug_img, (x, y), 10, (0, 0, 255), -1)
                filename = f"debug/can_choose_target_{timestamp}_{x}_{y}.png"
                result = cv2.imwrite(filename, debug_img)
                if result:
                    logging.info(f"can_choose_target图片已保存: {filename}")

        if can_choosetargets:
            can_choosetargets.sort(key=lambda pos: pos[0])

        return can_choosetargets

    def detect_existing_match(self, gray_screenshot, templates):
        """检测是否已经在游戏中"""
        # 检查是否检测到"决斗"按钮
        war_template = templates.get("war")
        if war_template:
            max_loc, max_val = self.template_manager.match_template(
                gray_screenshot, war_template
            )
            if max_val >= war_template["threshold"] and max_loc is not None:
                return True

        # 检查是否检测到"结束回合"按钮
        end_round_template = templates.get("end_round")
        if end_round_template:
            max_loc, max_val = self.template_manager.match_template(
                gray_screenshot, end_round_template
            )
            if max_val >= end_round_template["threshold"] and max_loc is not None:
                return True

        # 检查是否检测到"敌方回合"按钮
        enemy_round_template = templates.get("enemy_round")
        if enemy_round_template:
            max_loc, max_val = self.template_manager.match_template(
                gray_screenshot, enemy_round_template
            )
            if max_val >= enemy_round_template["threshold"] and max_loc is not None:
                return True

        return False
