"""
SIFT卡牌识别模块
基于SIFT特征匹配识别手牌区域中的卡牌及其费用
"""

import cv2
import numpy as np
import os
import glob
import logging
from typing import List, Tuple, Dict, Optional
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class SiftCardRecognition:
    """SIFT卡牌识别类"""
    
    def __init__(self, card_images_dir: str = "shadowverse_cards_cost"):
        """
        初始化SIFT卡牌识别器
        
        Args:
            card_images_dir: 卡牌图片目录路径
        """
        self.card_images_dir = card_images_dir
        self.card_templates = {}  # 缓存卡牌模板
        self.sift = cv2.SIFT_create()
        self.scale_factor = 0.3  # 缩放因子（匹配游戏中卡牌的实际大小）
        self.hand_area = (229, 539, 1130, 710)  # 手牌区域 (x1, y1, x2, y2) - 更新为新坐标
        self.min_matches = 4  # 最小匹配点数
        self.match_threshold = 0.01  # 匹配阈值
        
        # 加载卡牌模板
        self._load_card_templates()
    
    def _load_card_templates(self):
        """加载所有卡牌模板"""
        try:
            # 使用os.listdir来获取文件名列表，确保UTF-8编码
            if not os.path.exists(self.card_images_dir):
                logger.error(f"卡牌图片目录不存在: {self.card_images_dir}")
                return
                
            card_files = []
            for filename in os.listdir(self.card_images_dir):
                if filename.endswith('.png'):
                    card_files.append(os.path.join(self.card_images_dir, filename))
            
            logger.info(f"找到 {len(card_files)} 个PNG文件")
            
            for card_file in card_files:
                try:
                    # 提取文件名（不包含路径和扩展名）
                    filename = os.path.basename(card_file)
                    name_without_ext = os.path.splitext(filename)[0]
                    
                    # 解析费用和名称 - 格式为"(费用)_(名称)"
                    match = re.match(r'^(\d+)_(.+)$', name_without_ext)
                    if match:
                        cost = int(match.group(1))
                        card_name = match.group(2)
                        
                        # 使用PIL读取图片，确保UTF-8编码支持
                        from PIL import Image
                        
                        # 使用PIL读取图片
                        pil_image = Image.open(card_file)
                        template = np.array(pil_image)
                        
                        # 转换为BGR格式（OpenCV格式）
                        if len(template.shape) == 3 and template.shape[2] == 4:  # RGBA
                            template = cv2.cvtColor(template, cv2.COLOR_RGBA2BGR)
                        elif len(template.shape) == 3 and template.shape[2] == 3:  # RGB
                            template = cv2.cvtColor(template, cv2.COLOR_RGB2BGR)
                        
                        if template is not None:
                            # 缩放到0.3倍以匹配游戏中卡牌的实际大小
                            height, width = template.shape[:2]
                            new_height = int(height * self.scale_factor)
                            new_width = int(width * self.scale_factor)
                            scaled_template = cv2.resize(template, (new_width, new_height))
                            
                            # 转换为灰度图像进行SIFT特征提取
                            scaled_template_gray = cv2.cvtColor(scaled_template, cv2.COLOR_BGR2GRAY)
                            
                            # 计算SIFT特征
                            keypoints, descriptors = self.sift.detectAndCompute(scaled_template_gray, None)
                            
                            if descriptors is not None:
                                self.card_templates[name_without_ext] = {
                                    'cost': cost,
                                    'name': card_name,
                                    'template': scaled_template,
                                    'keypoints': keypoints,
                                    'descriptors': descriptors
                                }
                                logger.debug(f"加载卡牌模板: {name_without_ext} (费用: {cost})")
                        else:
                            logger.warning(f"无法读取图片: {card_file}")
                    else:
                        logger.warning(f"文件名格式不正确: {filename}")
                        
                except Exception as e:
                    logger.error(f"处理文件 {card_file} 时出错: {str(e)}")
                    continue
            
            logger.info(f"成功加载 {len(self.card_templates)} 张卡牌模板")
            
        except Exception as e:
            logger.error(f"加载卡牌模板时出错: {str(e)}")
    
    def recognize_hand_cards(self, screenshot) -> List[Dict]:
        """
        识别手牌区域中的卡牌（支持同名卡牌多张识别，支持多模板并发SIFT加速）
        """
        try:
            # 转换为OpenCV格式
            if hasattr(screenshot, 'shape'):
                image = screenshot
            else:
                image = np.array(screenshot)
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            x1, y1, x2, y2 = self.hand_area
            hand_region = image[y1:y2, x1:x2]
            
            # 转换为灰度图像进行SIFT特征提取
            hand_region_gray = cv2.cvtColor(hand_region, cv2.COLOR_BGR2GRAY)
            hand_keypoints, hand_descriptors = self.sift.detectAndCompute(hand_region_gray, None)
            if hand_descriptors is None:
                logger.warning("手牌区域未检测到SIFT特征")
                return []
            logger.debug(f"手牌区域SIFT特征点数: {len(hand_keypoints)}")

            def match_and_cluster(template_name, template_info):
                recognized_cards = []
                template_descriptors = template_info['descriptors']
                FLANN_INDEX_KDTREE = 1
                index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
                search_params = dict(checks=50)
                flann = cv2.FlannBasedMatcher(index_params, search_params)
                try:
                    matches = flann.knnMatch(template_descriptors, hand_descriptors, k=2)
                except Exception as e:
                    logger.debug(f"模板 {template_name} 匹配失败: {str(e)}")
                    return []
                good_matches = []
                for match_pair in matches:
                    if len(match_pair) == 2:
                        m, n = match_pair
                        if m.distance < 0.7 * n.distance:
                            good_matches.append(m)
                if len(good_matches) >= self.min_matches:
                    dst_pts = np.float32([hand_keypoints[m.trainIdx].pt for m in good_matches])
                    clusters = []
                    cluster_indices = []
                    distance_thresh = 80  # 像素距离阈值
                    for i, pt in enumerate(dst_pts):
                        found = False
                        for cidx, c in enumerate(clusters):
                            if np.linalg.norm(pt - c) < distance_thresh:
                                cluster_indices[cidx].append(i)
                                clusters[cidx] = (clusters[cidx] * (len(cluster_indices[cidx])-1) + pt) / len(cluster_indices[cidx])
                                found = True
                                break
                        if not found:
                            clusters.append(pt.copy())
                            cluster_indices.append([i])
                    for idx_list in cluster_indices:
                        if len(idx_list) < self.min_matches:
                            continue
                        cluster_good_matches = [good_matches[i] for i in idx_list]
                        src_pts = np.float32([template_info['keypoints'][m.queryIdx].pt for m in cluster_good_matches]).reshape(-1, 1, 2)
                        dst_pts_c = np.float32([hand_keypoints[m.trainIdx].pt for m in cluster_good_matches]).reshape(-1, 1, 2)
                        M, mask = cv2.findHomography(src_pts, dst_pts_c, cv2.RANSAC, 5.0)
                        if M is not None:
                            h, w = template_info['template'].shape[:2]
                            template_center = np.array([[w/2, h/2, 1]], dtype=np.float32)
                            target_center = M.dot(template_center.T)
                            # 检查除零和无效值
                            if target_center[2] == 0 or np.isnan(target_center[0]) or np.isnan(target_center[1]) or np.isnan(target_center[2]):
                                continue  # 跳过异常结果
                            target_center = target_center / target_center[2]
                            if np.isnan(target_center[0]) or np.isnan(target_center[1]):
                                 continue  # 跳过异常结果
                            global_x = int(target_center[0]) + x1
                            global_y = int(target_center[1]) + y1
                            avg_distance = np.mean([m.distance for m in cluster_good_matches])
                            if avg_distance <= 100:
                                distance_score = 1.0
                            elif avg_distance <= 200:
                                distance_score = 1.0 - (avg_distance - 100) / 100
                            else:
                                distance_score = max(0, 1.0 - (avg_distance - 200) / 100)
                            match_ratio = len(cluster_good_matches) / len(template_descriptors)
                            confidence = distance_score * match_ratio
                            if confidence >= self.match_threshold:
                                recognized_cards.append({
                                    'center': (global_x, global_y),
                                    'cost': template_info['cost'],
                                    'name': template_info['name'],
                                    'confidence': confidence,
                                    'template_name': template_name
                                })
                                logger.debug(f"识别到卡牌: {template_name} (费用: {template_info['cost']}, 置信度: {confidence:.3f})")
                return recognized_cards

            # 动态获取可用核心数，优先8核
            try:
                max_workers = min(8, os.cpu_count() or 4)
            except Exception:
                max_workers = 4
            recognized_cards = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for template_name, template_info in self.card_templates.items():
                    futures.append(executor.submit(match_and_cluster, template_name, template_info))
                for future in as_completed(futures):
                    try:
                        recognized_cards.extend(future.result())
                    except Exception as e:
                        logger.error(f"SIFT并发识别任务异常: {str(e)}")
            # --- 同名卡牌中心点去重 ---
            final_cards = []
            for card in recognized_cards:
                too_close = False
                for fc in final_cards:
                    if card['name'] == fc['name']:
                        dx = card['center'][0] - fc['center'][0]
                        dy = card['center'][1] - fc['center'][1]
                        if dx*dx + dy*dy < 900:  # 30像素内认为是同一张
                            too_close = True
                            break
                if not too_close:
                    final_cards.append(card)
            final_cards.sort(key=lambda card: card['center'][0])
            return final_cards
        except Exception as e:
            logger.error(f"SIFT卡牌识别出错: {str(e)}")
            return []
    
    def get_card_cost_by_name(self, card_name: str) -> Optional[int]:
        """
        根据卡牌名称获取费用
        
        Args:
            card_name: 卡牌名称
            
        Returns:
            Optional[int]: 卡牌费用，如果未找到返回None
        """
        for template_name, template_info in self.card_templates.items():
            if template_info['name'] == card_name:
                return template_info['cost']
        return None
    
    def get_all_card_names(self) -> List[str]:
        """
        获取所有卡牌名称
        
        Returns:
            List[str]: 所有卡牌名称列表
        """
        return [template_info['name'] for template_info in self.card_templates.values()]
    
    def get_all_card_costs(self) -> Dict[str, int]:
        """
        获取所有卡牌的费用映射
        
        Returns:
            Dict[str, int]: 卡牌名称到费用的映射
        """
        return {template_info['name']: template_info['cost'] 
                for template_info in self.card_templates.values()} 