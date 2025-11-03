
import cv2
import numpy as np
import time
from skimage.metrics import structural_similarity as ssim

def wait_for_screen_stable(device_state, timeout=10, threshold=0.90, interval=0.1, max_checks=1):
    """
    等待设备屏幕稳定

    :param device_state: 设备状态对象
    :param timeout: 超时时间（秒）
    :param threshold: 图像相似度阈值
    :param interval: 截图间隔时间（秒）
    :param max_checks: 连续稳定画面的次数
    :return: 如果屏幕稳定则返回True，超时返回False
    """
    start_time = time.time()
    last_screenshot = None
    stable_count = 0
    change_logged = False  # 添加状态标记，跟踪是否已经输出了画面变化日志

    while time.time() - start_time < timeout:
        screenshot = device_state.take_screenshot()
        if screenshot is None:
            time.sleep(interval)
            continue

        # 将PIL图像转换为OpenCV格式
        frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)

        if last_screenshot is not None:
            # 计算SSIM
            score, _ = ssim(last_screenshot, frame, full=True)
            
            if score > threshold:
                stable_count += 1
                change_logged = False  # 画面稳定时重置标记
                # device_state.logger.info(f"画面稳定检测: {stable_count}/{max_checks} (稳定度: {score:.3f})")
            else:
                if not change_logged:  # 只在第一次检测到变化时输出日志
                    # device_state.logger.info(f"画面变化，重置稳定计数 (稳定度: {score:.3f})")
                    device_state.logger.info(f"画面特效持续中... (稳定度: {score:.3f})")
                    change_logged = True  # 设置标记，避免重复输出
                stable_count = 0

            if stable_count >= max_checks:
                device_state.logger.info(f"画面已稳定 (稳定度: {score:.3f})")
                return True
        
        last_screenshot = frame
        time.sleep(interval)

    device_state.logger.warning("等待画面稳定超时")
    return False
