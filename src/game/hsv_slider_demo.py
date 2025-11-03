import cv2
import numpy as np
import os

# 读取图片
script_dir = os.path.dirname(os.path.abspath(__file__))
img_before = cv2.imread(os.path.join(script_dir, 'before.png'))
img_after = cv2.imread(os.path.join(script_dir, 'after.png'))

if img_before is None or img_after is None:
    print('before.png 或 after.png 未找到！')
    exit(1)

# 创建窗口和滑动条
def nothing(x):
    pass

cv2.namedWindow('HSV Demo', cv2.WINDOW_NORMAL)
cv2.createTrackbar('H_min', 'HSV Demo', 19, 179, nothing)
cv2.createTrackbar('H_max', 'HSV Demo', 25, 179, nothing)
cv2.createTrackbar('S_min', 'HSV Demo', 150, 255, nothing)
cv2.createTrackbar('S_max', 'HSV Demo', 255, 255, nothing)
cv2.createTrackbar('V_min', 'HSV Demo', 184, 255, nothing)
cv2.createTrackbar('V_max', 'HSV Demo', 255, 255, nothing)
cv2.createTrackbar('Image', 'HSV Demo', 0, 1, nothing)  # 0:before, 1:after

# 鼠标回调，点击显示该点HSV
last_hsv = (0,0,0)
def mouse_callback(event, x, y, flags, param):
    global last_hsv
    if event == cv2.EVENT_LBUTTONDOWN:
        img = param['img']
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        last_hsv = tuple(hsv[y, x])
        print(f'点击点({x},{y}) HSV: {last_hsv}')

cv2.setMouseCallback('HSV Demo', mouse_callback, param={'img': img_before})

while True:
    # 选择图片
    img = img_before if cv2.getTrackbarPos('Image', 'HSV Demo') == 0 else img_after
    img_show = img.copy()
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    cv2.setMouseCallback('HSV Demo', mouse_callback, param={'img': img})

    # 获取滑动条的值
    h_min = cv2.getTrackbarPos('H_min', 'HSV Demo')
    h_max = cv2.getTrackbarPos('H_max', 'HSV Demo')
    s_min = cv2.getTrackbarPos('S_min', 'HSV Demo')
    s_max = cv2.getTrackbarPos('S_max', 'HSV Demo')
    v_min = cv2.getTrackbarPos('V_min', 'HSV Demo')
    v_max = cv2.getTrackbarPos('V_max', 'HSV Demo')

    # 生成掩膜
    lower = np.array([h_min, s_min, v_min])
    upper = np.array([h_max, s_max, v_max])
    mask = cv2.inRange(hsv, lower, upper)

    # 查找轮廓并统计均值
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mean_hsvs = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 50:
            continue
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect)
        box = box.astype(int)
        center = (int(rect[0][0]), int(rect[0][1]))
        # 绘制外接矩形和中心点
        cv2.drawContours(img_show, [box], 0, (0,255,0), 2)
        cv2.circle(img_show, center, 5, (0,0,255), -1)
        # 统计该区域HSV均值
        mask_cnt = np.zeros(mask.shape, np.uint8)
        cv2.drawContours(mask_cnt, [cnt], -1, 255, -1)
        mean_h = hsv[...,0][mask_cnt==255].mean() if np.any(mask_cnt==255) else 0
        mean_s = hsv[...,1][mask_cnt==255].mean() if np.any(mask_cnt==255) else 0
        mean_v = hsv[...,2][mask_cnt==255].mean() if np.any(mask_cnt==255) else 0
        mean_hsvs.append((mean_h, mean_s, mean_v))
        # 显示均值
        cv2.putText(img_show, f"HSV:({mean_h:.0f},{mean_s:.0f},{mean_v:.0f})", (center[0]+10, center[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)

    # 显示所有区域均值或无有效区域
    if mean_hsvs:
        txt = 'Mean HSVs: ' + ', '.join([f'({h:.0f},{s:.0f},{v:.0f})' for h,s,v in mean_hsvs])
    else:
        txt = '无有效区域'
    cv2.putText(img_show, txt, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,128,255), 2)

    # 显示鼠标点击点HSV
    if last_hsv != (0,0,0):
        cv2.putText(img_show, f'Click HSV: {last_hsv}', (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,0,0), 2)

    # 显示结果
    cv2.imshow('HSV Demo', img_show)
    cv2.imshow('Mask', mask)
    key = cv2.waitKey(30) & 0xFF
    if key == 27:
        break

cv2.destroyAllWindows() 