#!/usr/bin/env python3
"""文档处理模块 - 主处理逻辑"""
import os
import json
import time
from pathlib import Path
from typing import Tuple

from extractors.pdf_extractor import PDFProcessor
from extractors.excel_extractor import ExcelExtractor
from extractors.word_extractor import WordExtractor
from extractors.vision_service import vision_service
from extractors.prompts import SYSTEM_PROMPT, USER_PROMPT, SYSTEM_XML_PROMPT, USER_XML_PROMPT
from extractors.api_transformer import APITransformer
from extractors.config import (
    OUTPUT_GRADIO_DIR,
    OUTPUT_XML_DEBUG_DIR,
    OUTPUT_DEBUG_DIR,
    DEFAULT_USE_XML_MODE,
    DEFAULT_WRITE_DEBUG,
)


class DocumentProcessor:
    """文档处理器 - 统一处理各种文档格式"""

    def __init__(self, port_mapper, project_root: str):
        """
        初始化文档处理器

        Args:
            port_mapper: 港口代码映射器实例
            project_root: 项目根目录
        """
        self.port_mapper = port_mapper
        self.project_root = project_root
        self.api_transformer = APITransformer(port_mapper)

    def _write_xml_debug(self, file_path: str, cleaned_text: str, raw_json: str):
        """
        写入 XML 模式调试文件

        Args:
            file_path: 原始文件路径
            cleaned_text: 清理后的文本内容
            raw_json: VLM 原始返回的 JSON
        """
        debug_dir = OUTPUT_XML_DEBUG_DIR
        os.makedirs(debug_dir, exist_ok=True)

        timestamp = int(time.time())
        base_name = Path(file_path).stem

        # 写入清理后的文本
        txt_file = os.path.join(debug_dir, f"{base_name}_{timestamp}.txt")
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write(cleaned_text)
        print(f"📝 Debug文本已保存: {txt_file}")

        # 写入 VLM 原始返回
        raw_file = os.path.join(debug_dir, f"{base_name}_{timestamp}_raw.json")
        with open(raw_file, 'w', encoding='utf-8') as f:
            f.write(raw_json)
        print(f"📝 Debug原始JSON已保存: {raw_file}")

    def _write_vlm_debug(self, file_path: str, raw_json: str):
        """
        写入 VLM 返回结果到 debug 目录

        Args:
            file_path: 原始文件路径
            raw_json: VLM 原始返回的 JSON
        """
        debug_dir = OUTPUT_DEBUG_DIR
        os.makedirs(debug_dir, exist_ok=True)

        timestamp = int(time.time())
        base_name = Path(file_path).stem

        # 写入 VLM 原始返回
        debug_file = os.path.join(debug_dir, f"{base_name}_{timestamp}_vlm.json")
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(raw_json)
        print(f"📝 VLM结果已保存: {debug_file}")

    def process_file(self, file_path: str, doc_type: str, use_xml_mode: bool = None, write_debug: bool = None) -> Tuple[str, str, str]:
        """
        主处理函数

        Args:
            file_path: 文件路径
            doc_type: 文档类型 ("贸易委托书", "账单单单据")
            use_xml_mode: 是否使用 XML 模式处理（仅适用于 Word/Excel），默认使用配置值
            write_debug: 是否写入调试文件（仅适用于 XML 模式），默认使用配置值

        Returns:
            (VLM原始结果JSON, 转换后结果JSON, 文件扩展名)
        """
        # 使用配置值作为默认值
        if use_xml_mode is None:
            use_xml_mode = DEFAULT_USE_XML_MODE
        if write_debug is None:
            write_debug = DEFAULT_WRITE_DEBUG
        if not file_path or not os.path.exists(file_path):
            return json.dumps({"error": "文件不存在"}, ensure_ascii=False), json.dumps({"error": "文件不存在"}, ensure_ascii=False), "unknown"

        ext = Path(file_path).suffix.lower()

        excel_parser = ExcelExtractor()
        word_parser = WordExtractor()

        try:
            print(f"📄 开始处理文件: {Path(file_path).name}")
            print(f"📋 文件类型: {ext}, 单据类型: {doc_type}")

            raw_json = ""
            final_res = ""

            if ext in ['.pdf', '.png', '.jpg', '.jpeg']:
                # 视觉模型处理
                print("🖼️  处理图像文件...")
                img_b64 = vision_service.get_document_image_base64(file_path)
                raw_json = vision_service.call_vlm_service(SYSTEM_PROMPT, USER_PROMPT, img_b64)
                print(f"✅ VLM返回结果:\n{raw_json[:500]}...")
                self._write_vlm_debug(file_path, raw_json)
                final_res = self.api_transformer.transform(raw_json)

            elif ext in ['.xlsx', '.xls']:
                if use_xml_mode:
                    # XML 模式处理 Excel
                    print("📊 处理Excel文件 (XML模式)...")
                    cleaned_text = excel_parser.clean_xml_simple(file_path)
                    raw_json = vision_service.call_vlm_service(SYSTEM_XML_PROMPT, USER_XML_PROMPT, text_content=cleaned_text)
                    print(f"✅ VLM返回结果:\n{raw_json[:500]}...")
                    self._write_vlm_debug(file_path, raw_json)

                    if write_debug:
                        self._write_xml_debug(file_path, cleaned_text, raw_json)

                    final_res = self.api_transformer.transform(raw_json)
                else:
                    # 图片模式处理 Excel
                    print("📊 处理Excel文件...")
                    img_b64 = excel_parser.extract(file_path)

                    if doc_type == "贸易委托书":
                        raw_json = vision_service.call_vlm_service(SYSTEM_PROMPT, USER_PROMPT, img_b64)
                        print(f"✅ VLM返回结果:\n{raw_json[:500]}...")
                        self._write_vlm_debug(file_path, raw_json)
                        final_res = self.api_transformer.transform(raw_json)
                    else:
                        raw_json = ""
                        final_res = json.dumps({"error": "暂不支持 Excel 账单处理"}, ensure_ascii=False)

            elif ext in ['.docx', '.doc']:
                if use_xml_mode:
                    # XML 模式处理 Word
                    print("📝 处理Word文件 (XML模式)...")
                    cleaned_text = word_parser.clean_xml(file_path)
                    raw_json = vision_service.call_vlm_service(SYSTEM_XML_PROMPT, USER_XML_PROMPT, text_content=cleaned_text)
                    print(f"✅ VLM返回结果:\n{raw_json[:500]}...")
                    self._write_vlm_debug(file_path, raw_json)

                    if write_debug:
                        self._write_xml_debug(file_path, cleaned_text, raw_json)

                    final_res = self.api_transformer.transform(raw_json)
                else:
                    # 图片模式处理 Word
                    print("📝 处理Word文件...")
                    img_b64 = word_parser.extract(file_path)

                    if doc_type == "贸易委托书":
                        raw_json = vision_service.call_vlm_service(SYSTEM_PROMPT, USER_PROMPT, img_b64)
                        print(f"✅ VLM返回结果:\n{raw_json[:500]}...")
                        self._write_vlm_debug(file_path, raw_json)
                        final_res = self.api_transformer.transform(raw_json)
                    else:
                        raw_json = ""
                        final_res = json.dumps({"error": "暂不支持 Word 账单处理"}, ensure_ascii=False)

            else:
                raw_json = ""
                final_res = json.dumps({"error": f"暂不支持 {ext} 格式文件"}, ensure_ascii=False)

            # 结果持久化
            output_dir = OUTPUT_GRADIO_DIR
            os.makedirs(output_dir, exist_ok=True)
            output_file = os.path.join(output_dir, f"res_{Path(file_path).stem}.json")

            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(final_res)

            print(f"💾 结果已保存到: {output_file}")
            return raw_json, final_res, ext

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"❌ 处理失败: {e}\n{error_detail}")
            error_json = json.dumps({
                "error": str(e),
                "detail": error_detail
            }, ensure_ascii=False)
            return error_json, error_json, "error"


# 便捷函数
def process_file(file_path: str, doc_type: str, port_mapper, project_root: str) -> Tuple[str, str, str]:
    """处理文件的便捷函数"""
    processor = DocumentProcessor(port_mapper, project_root)
    return processor.process_file(file_path, doc_type)
