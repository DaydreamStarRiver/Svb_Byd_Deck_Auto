"""
配置管理器
负责配置的加载、验证和管理
"""

import json
import os
import logging
from typing import Dict, Any, Optional
from src.config.settings import DEFAULT_CONFIG
from src.config.constants_manager import ConstantsManager

logger = logging.getLogger(__name__)


class ConfigManager:
    """配置管理器类"""
    
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.config = self._load_config()
        self.constants_manager = ConstantsManager(self.config)
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        # 如果配置文件不存在，创建默认配置
        if not os.path.exists(self.config_file):
            logger.info(f"创建默认配置文件: {self.config_file}")
            self._save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 合并默认配置和用户配置
                merged_config = self._merge_configs(DEFAULT_CONFIG, config)
                return merged_config
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}，使用默认配置")
            return DEFAULT_CONFIG.copy()
    
    def _merge_configs(self, default_config: Dict[str, Any], user_config: Dict[str, Any]) -> Dict[str, Any]:
        """递归合并配置"""
        merged = default_config.copy()
        
        for key, value in user_config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value
        
        return merged
    
    def _save_config(self, config: Dict[str, Any]) -> bool:
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"保存配置文件失败: {str(e)}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> bool:
        """设置配置值"""
        keys = key.split('.')
        config = self.config
        
        # 导航到父级
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # 设置值
        config[keys[-1]] = value
        return self._save_config(self.config)
    
    def get_devices(self) -> list:
        """获取设备配置列表"""
        return self.config.get("devices", [])
    
    def get_device_by_serial(self, serial: str) -> Optional[Dict[str, Any]]:
        """根据序列号获取设备配置"""
        devices = self.get_devices()
        for device in devices:
            if device.get("serial") == serial:
                return device
        return None
    
    def add_device(self, device_config: Dict[str, Any]) -> bool:
        """添加设备配置"""
        devices = self.get_devices()
        devices.append(device_config)
        return self.set("devices", devices)
    
    def remove_device(self, serial: str) -> bool:
        """移除设备配置"""
        devices = self.get_devices()
        devices = [d for d in devices if d.get("serial") != serial]
        return self.set("devices", devices)
    
    def validate_config(self) -> bool:
        """验证配置的有效性"""
        try:
            # 验证设备配置
            devices = self.get_devices()
            if not devices:
                logger.error("配置文件中未找到设备列表")
                return False
            
            for device in devices:
                if not device.get("serial"):
                    logger.error("设备配置缺少serial字段")
                    return False
            
            # 验证游戏配置
            game_config = self.config.get("game", {})
            if not game_config.get("resolution"):
                logger.error("游戏配置缺少resolution字段")
                return False
            
            # 验证其他必要配置
            if not self.config.get("auto_restart"):
                logger.error("配置缺少auto_restart字段")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"配置验证失败: {str(e)}")
            return False
    
    def reload(self) -> bool:
        """重新加载配置"""
        try:
            self.config = self._load_config()
            return self.validate_config()
        except Exception as e:
            logger.error(f"重新加载配置失败: {str(e)}")
            return False
    
    def export_config(self, export_path: str) -> bool:
        """导出配置到指定路径"""
        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info(f"配置已导出到: {export_path}")
            return True
        except Exception as e:
            logger.error(f"导出配置失败: {str(e)}")
            return False
    
    def import_config(self, import_path: str) -> bool:
        """从指定路径导入配置"""
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                imported_config = json.load(f)
            
            # 合并配置
            self.config = self._merge_configs(DEFAULT_CONFIG, imported_config)
            
            # 重新初始化常量管理器
            self.constants_manager = ConstantsManager(self.config)
            
            # 保存并验证
            if self._save_config(self.config) and self.validate_config():
                logger.info(f"配置已从 {import_path} 导入")
                return True
            else:
                logger.error("导入的配置验证失败")
                return False
                
        except Exception as e:
            logger.error(f"导入配置失败: {str(e)}")
            return False 
    
    def get_constants_manager(self) -> ConstantsManager:
        """获取常量管理器"""
        return self.constants_manager 

    def get_change_card_cost_threshold(self) -> int:
        """获取换牌费用阈值，默认3"""
        return self.get("change_card_cost_threshold", 3) 