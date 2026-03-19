#!/usr/bin/env python3
"""Word 文档提取器 - 支持图片和 XML 格式"""
import os
import re
import tempfile
import subprocess
import zipfile
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from pdf2image import convert_from_path
from PIL import Image
from io import BytesIO

from extractors.config import IMAGE_DPI, IMAGE_MAX_SIZE, IMAGE_JPEG_QUALITY


class WordExtractor:
    """将 Word 文档提取为图片或 XML"""

    def __init__(self, dpi: int = None, max_size: int = None):
        """
        初始化 Word 提取器

        Args:
            dpi: 渲染分辨率，默认使用配置值 IMAGE_DPI
            max_size: 图片最大尺寸，默认使用配置值 IMAGE_MAX_SIZE
        """
        self.dpi = dpi if dpi is not None else IMAGE_DPI
        self.max_size = max_size if max_size is not None else IMAGE_MAX_SIZE

    def _convert_to_docx(self, file_path: str, temp_dir: str) -> str:
        """
        将旧版 .doc 格式转换为 .docx 格式

        Args:
            file_path: 原始 .doc 文件路径
            temp_dir: 临时目录

        Returns:
            转换后的 .docx 文件路径
        """
        try:
            # 使用 LibreOffice 转换为 docx
            result = subprocess.run([
                'libreoffice',
                '--headless',
                '--convert-to', 'docx',
                '--outdir', temp_dir,
                file_path
            ], check=True, capture_output=True, timeout=60)

            # LibreOffice 会在同目录生成同名 .docx 文件
            original_name = Path(file_path).stem
            converted_path = os.path.join(temp_dir, original_name + ".docx")

            if os.path.exists(converted_path):
                return converted_path

            # 尝试在 temp_dir 中查找
            for f in os.listdir(temp_dir):
                if f.endswith('.docx'):
                    return os.path.join(temp_dir, f)

            raise RuntimeError("LibreOffice 转换失败，未生成 .docx 文件")

        except subprocess.TimeoutExpired:
            raise RuntimeError("Word 格式转换超时")
        except Exception as e:
            raise RuntimeError(f"Word 格式转换失败: {e}")

    def extract(self, file_path: str) -> str:
        """
        将 Word 文档转换为 base64 编码的图片

        Args:
            file_path: Word 文件路径 (.docx, .doc)

        Returns:
            base64 编码的图片字符串

        Raises:
            FileNotFoundError: 如果文件不存在
            RuntimeError: 如果转换失败
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = Path(file_path).suffix.lower()
        if ext not in ['.docx', '.doc']:
            raise ValueError(f"不支持的 Word 格式: {ext}")

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 如果是 .doc 格式，先转换为 .docx
                process_path = file_path
                if ext == '.doc':
                    process_path = self._convert_to_docx(file_path, temp_dir)

                # 使用 LibreOffice 将 Word 转换为 PDF
                subprocess.run([
                    'libreoffice',
                    '--headless',
                    '--convert-to', 'pdf',
                    '--outdir', temp_dir,
                    process_path
                ], check=True, timeout=60)

                pdf_name = Path(process_path).stem + ".pdf"
                pdf_path = os.path.join(temp_dir, pdf_name)

                if not os.path.exists(pdf_path):
                    raise RuntimeError(f"PDF 转换失败: {pdf_path}")

                # 渲染 PDF 所有页面
                images = convert_from_path(pdf_path, dpi=self.dpi)

                # 多页拼接
                if len(images) > 1:
                    total_height = sum(img.height for img in images)
                    max_width = max(img.width for img in images)
                    combined = Image.new('RGB', (max_width, total_height), 'white')
                    y_offset = 0
                    for img in images:
                        combined.paste(img, (0, y_offset))
                        y_offset += img.height
                    img = combined
                else:
                    img = images[0]

                # 限制图像大小
                if img.width > self.max_size or img.height > self.max_size:
                    ratio = min(self.max_size / img.width, self.max_size / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)

                buffered = BytesIO()
                img.convert("RGB").save(buffered, format="JPEG", quality=95)
                return base64.b64encode(buffered.getvalue()).decode('utf-8')

            except subprocess.TimeoutExpired:
                raise RuntimeError("Word 转换超时，请检查文件是否损坏")
            except Exception as e:
                raise RuntimeError(f"Word 转换失败: {e}")

    def extract_xml(self, file_path: str) -> str:
        """
        提取 Word 文档的原始 XML 内容
        自动转换旧版 .doc 格式为 .docx

        Args:
            file_path: Word 文件路径 (.docx, .doc)

        Returns:
            原始 XML 字符串

        Raises:
            FileNotFoundError: 如果文件不存在
            ValueError: 如果文件格式不支持
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = Path(file_path).suffix.lower()
        if ext not in ['.docx', '.doc']:
            raise ValueError("不支持的 Word 格式")

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 如果是 .doc 格式，先转换为 .docx
                process_path = file_path
                if ext == '.doc':
                    process_path = self._convert_to_docx(file_path, temp_dir)

                with zipfile.ZipFile(process_path, 'r') as zf:
                    # 读取主文档内容
                    xml_content = zf.read('word/document.xml').decode('utf-8')
                    return xml_content

            except zipfile.BadZipFile:
                raise RuntimeError(f"无效的 Word 文件: {file_path}")
            except KeyError:
                raise RuntimeError(f"Word 文件结构异常，缺少 document.xml")

    def clean_xml(self, file_path: str) -> str:
        """
        清理 Word XML 内容，提取纯文本
        自动转换旧版 .doc 格式为 .docx

        Args:
            file_path: Word 文件路径 (.docx, .doc)

        Returns:
            清理后的纯文本内容

        Raises:
            FileNotFoundError: 如果文件不存在
            ValueError: 如果文件格式不支持
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = Path(file_path).suffix.lower()
        if ext not in ['.docx', '.doc']:
            raise ValueError("不支持的 Word 格式")

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 如果是 .doc 格式，先转换为 .docx
                process_path = file_path
                if ext == '.doc':
                    process_path = self._convert_to_docx(file_path, temp_dir)

                with zipfile.ZipFile(process_path, 'r') as zf:
                    # 读取主文档内容
                    xml_content = zf.read('word/document.xml').decode('utf-8')

                # 解析 XML
                root = ET.fromstring(xml_content)

                # 提取所有文本段落
                paragraphs = []
                for paragraph in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                    texts = []
                    for text_elem in paragraph.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'):
                        if text_elem.text:
                            texts.append(text_elem.text)
                    para_text = ''.join(texts)
                    if para_text.strip():
                        paragraphs.append(para_text)

                # 提取表格内容
                for table in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl'):
                    table_rows = []
                    for row in table.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr'):
                        row_cells = []
                        for cell in row.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc'):
                            cell_texts = []
                            for para in cell.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                                for text_elem in para.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'):
                                    if text_elem.text:
                                        cell_texts.append(text_elem.text)
                            cell_text = ''.join(cell_texts)
                            if cell_text.strip():
                                row_cells.append(cell_text)
                        if row_cells:
                            table_rows.append(' | '.join(row_cells))
                    if table_rows:
                        paragraphs.append('[表格]')
                        paragraphs.extend(table_rows)
                        paragraphs.append('[/表格]')

                return '\n'.join(paragraphs)

            except zipfile.BadZipFile:
                raise RuntimeError(f"无效的 Word 文件: {file_path}")
            except KeyError:
                raise RuntimeError(f"Word 文件结构异常，缺少 document.xml")
            except ET.ParseError:
                raise RuntimeError(f"XML 解析失败")
