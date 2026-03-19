#!/usr/bin/env python3
"""配置文件 - 集中管理所有配置项"""
import os
from pathlib import Path

# ========== 项目路径配置 ==========
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT_MAPPING_EXCEL = os.path.join(PROJECT_ROOT, "港口代码映射表.xlsx")

# ========== 输出目录配置 ==========
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
OUTPUT_GRADIO_DIR = os.path.join(OUTPUT_DIR, "gradio")
OUTPUT_XML_DEBUG_DIR = os.path.join(OUTPUT_DIR, "xml_debug")
OUTPUT_DEBUG_DIR = os.path.join(OUTPUT_DIR, "debug")

# ========== VLM 服务配置 ==========
VLLM_API_URL = "http://documentextractor.cpolar.top/v1"
VLLM_MODEL_NAME = "Qwen3-VL-4B-Instruct"
VLLM_API_KEY = "EMPTY"
VLLM_TIMEOUT = 300.0  # 超时时间（秒）
VLLM_MAX_TOKENS = 4096
VLLM_TEMPERATURE = 0.1
VLLM_TOP_P = 0.9

# ========== 图像处理配置 ==========
# PDF/图片转换 DPI
IMAGE_DPI = 350
# 图片最大尺寸（像素）
IMAGE_MAX_SIZE = 4096
# 图片压缩后的最大尺寸（像素）
IMAGE_COMPRESS_MAX_SIZE = 2048
# JPEG 压缩质量
IMAGE_JPEG_QUALITY = 95
# 压缩后 JPEG 质量
IMAGE_COMPRESS_JPEG_QUALITY = 90

# ========== Excel/Word 处理配置 ==========
# 是否使用 XML 模式处理 Excel/Word（替代图片模式）
DEFAULT_USE_XML_MODE = True
# XML 模式是否写入调试文件
DEFAULT_WRITE_DEBUG = True

# ========== API 转换配置 ==========
# 是否启用 API 转换
ENABLE_API_TRANSFORM = True


def ensure_output_dirs():
    """确保输出目录存在"""
    os.makedirs(OUTPUT_GRADIO_DIR, exist_ok=True)
    os.makedirs(OUTPUT_XML_DEBUG_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DEBUG_DIR, exist_ok=True)


def get_config_dict():
    """获取配置字典（用于调试）"""
    return {
        "VLLM_API_URL": VLLM_API_URL,
        "VLLM_MODEL_NAME": VLLM_MODEL_NAME,
        "VLLM_TIMEOUT": VLLM_TIMEOUT,
        "VLLM_MAX_TOKENS": VLLM_MAX_TOKENS,
        "VLLM_TEMPERATURE": VLLM_TEMPERATURE,
        "VLLM_TOP_P": VLLM_TOP_P,
        "IMAGE_DPI": IMAGE_DPI,
        "IMAGE_MAX_SIZE": IMAGE_MAX_SIZE,
        "IMAGE_COMPRESS_MAX_SIZE": IMAGE_COMPRESS_MAX_SIZE,
        "DEFAULT_USE_XML_MODE": DEFAULT_USE_XML_MODE,
        "DEFAULT_WRITE_DEBUG": DEFAULT_WRITE_DEBUG,
        "PORT_MAPPING_EXCEL": PORT_MAPPING_EXCEL,
    }