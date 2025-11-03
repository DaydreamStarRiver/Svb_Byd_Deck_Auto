"""
GPU工具模块
处理GPU检测和配置
"""

import os
import logging

logger = logging.getLogger(__name__)

# 全局GPU状态缓存
_gpu_status = None
_gpu_initialized = False

# 全局EasyOCR实例缓存
_easyocr_reader = None
_easyocr_initialized = False


def setup_gpu():
    """
    检测和配置GPU
    
    Returns:
        bool: 是否成功启用GPU
    """
    global _gpu_status, _gpu_initialized
    
    # 如果已经初始化过，直接返回缓存的结果
    if _gpu_initialized:
        return _gpu_status
    
    try:
        import torch
        
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            memory_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
            
            logger.info(f"检测到GPU: {device_name}")
            logger.info(f"GPU内存: {memory_gb:.1f} GB")
            
            # 设置CUDA优化
            torch.backends.cudnn.benchmark = True
            torch.backends.cudnn.deterministic = False
            
            # 设置默认设备
            torch.cuda.set_device(0)
            
            # 启用pin_memory（GPU模式下）
            os.environ["PIN_MEMORY"] = "true"
            
            logger.info("GPU加速已启用")
            _gpu_status = True
        else:
            #logger.info("未检测到GPU，使用CPU模式")
            # 如果没有GPU，则禁用pin_memory以避免警告
            os.environ["PIN_MEMORY"] = "false"
            
            # 设置torch的默认pin_memory行为
            try:
                # 尝试设置torch的默认pin_memory为False
                torch.utils.data.DataLoader.pin_memory = False
            except:
                pass
                
            _gpu_status = False
            
    except ImportError:
        logger.warning("PyTorch未安装，无法检测GPU")
        os.environ["PIN_MEMORY"] = "false"
        _gpu_status = False
    except Exception as e:
        logger.error(f"GPU检测失败: {str(e)}")
        os.environ["PIN_MEMORY"] = "false"
        _gpu_status = False
    
    _gpu_initialized = True
    return _gpu_status


def get_easyocr_reader(gpu_enabled: bool = None, model_dir: str = None):
    """
    获取EasyOCR读取器实例（全局单例）
    
    Args:
        gpu_enabled: 是否启用GPU，None表示自动检测
        model_dir: 模型目录路径（已废弃，始终用项目根目录下models）
        
    Returns:
        EasyOCR Reader实例
    """
    global _easyocr_reader, _easyocr_initialized
    
    # 如果已经初始化过，直接返回缓存的实例
    if _easyocr_initialized:
        return _easyocr_reader
    
    try:
        import easyocr
        # 使用resource_utils来正确处理PyInstaller打包后的路径
        from src.utils.resource_utils import resource_path
        fixed_model_dir = resource_path("models")
        logger.info(f"EasyOCR模型目录: {fixed_model_dir}")
        
        if gpu_enabled is None:
            gpu_enabled = bool(setup_gpu())
        _easyocr_reader = easyocr.Reader(
            ['en'], 
            gpu=gpu_enabled, 
            model_storage_directory=fixed_model_dir, 
            download_enabled=False  # 禁止联网下载，只用本地模型
        )
        if gpu_enabled:
            logger.info("EasyOCR已启用GPU加速")
        else:
            logger.info("EasyOCR使用CPU模式")
        _easyocr_initialized = True
        return _easyocr_reader
    except ImportError:
        logger.error("EasyOCR导入失败")
        return None
    except Exception as e:
        logger.error(f"初始化EasyOCR失败: {str(e)}")
        return None 