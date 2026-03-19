# DocumentExtractor - Extractors
# 提取器模块 - 负责从各种文档格式中提取原始内容

from extractors.pdf_extractor import PDFProcessor
from extractors.excel_extractor import ExcelExtractor
from extractors.word_extractor import WordExtractor
from extractors.port_mapper import PortMapper, port_mapper
from extractors.utils import (
    parse_number,
    safe_parse_number,
    normalize_bool_text,
    safe_calculate_hwmd
)
from extractors.vision_service import VisionService, vision_service
from extractors.prompts import SYSTEM_PROMPT, USER_PROMPT, SYSTEM_XML_PROMPT, USER_XML_PROMPT
from extractors.api_transformer import APITransformer, transform_to_api_format
from extractors.document_processor import DocumentProcessor, process_file
from extractors.config import (
    get_config_dict,
    ensure_output_dirs,
    # VLM 配置
    VLLM_API_URL,
    VLLM_MODEL_NAME,
    VLLM_TIMEOUT,
    VLLM_MAX_TOKENS,
    VLLM_TEMPERATURE,
    VLLM_TOP_P,
    # 图像处理配置
    IMAGE_DPI,
    IMAGE_MAX_SIZE,
    IMAGE_COMPRESS_MAX_SIZE,
    IMAGE_JPEG_QUALITY,
    IMAGE_COMPRESS_JPEG_QUALITY,
    # 输出配置
    OUTPUT_DIR,
    OUTPUT_GRADIO_DIR,
    OUTPUT_XML_DEBUG_DIR,
    OUTPUT_DEBUG_DIR,
    # XML 模式配置
    DEFAULT_USE_XML_MODE,
    DEFAULT_WRITE_DEBUG,
)

__all__ = [
    # Extractors
    'PDFProcessor',
    'ExcelExtractor',
    'WordExtractor',
    'PortMapper',
    'port_mapper',
    # Utils
    'parse_number',
    'safe_parse_number',
    'normalize_bool_text',
    'safe_calculate_hwmd',
    # Vision
    'VisionService',
    'vision_service',
    # Prompts
    'SYSTEM_PROMPT',
    'USER_PROMPT',
    'SYSTEM_XML_PROMPT',
    'USER_XML_PROMPT',
    # API Transformer
    'APITransformer',
    'transform_to_api_format',
    # Document Processor
    'DocumentProcessor',
    'process_file',
    # Config
    'get_config_dict',
    'ensure_output_dirs',
    'VLLM_API_URL',
    'VLLM_MODEL_NAME',
    'VLLM_TIMEOUT',
    'VLLM_MAX_TOKENS',
    'VLLM_TEMPERATURE',
    'VLLM_TOP_P',
    'IMAGE_DPI',
    'IMAGE_MAX_SIZE',
    'IMAGE_COMPRESS_MAX_SIZE',
    'IMAGE_JPEG_QUALITY',
    'IMAGE_COMPRESS_JPEG_QUALITY',
    'OUTPUT_DIR',
    'OUTPUT_GRADIO_DIR',
    'OUTPUT_XML_DEBUG_DIR',
    'OUTPUT_DEBUG_DIR',
    'DEFAULT_USE_XML_MODE',
    'DEFAULT_WRITE_DEBUG',
]
