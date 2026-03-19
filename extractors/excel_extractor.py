#!/usr/bin/env python3
"""Excel 表格提取器 - 支持图片和 XML 格式"""
import os
import re
import tempfile
import subprocess
import zipfile
from pathlib import Path
from typing import Optional, Dict, List
from xml.etree import ElementTree as ET

from pdf2image import convert_from_path
from PIL import Image
from io import BytesIO

from extractors.config import IMAGE_DPI, IMAGE_MAX_SIZE, IMAGE_JPEG_QUALITY


class ExcelExtractor:
    """将 Excel 文档提取为图片或 XML"""

    def __init__(self, dpi: int = None, max_size: int = None):
        """
        初始化 Excel 提取器

        Args:
            dpi: 渲染分辨率，默认使用配置值 IMAGE_DPI
            max_size: 图片最大尺寸，默认使用配置值 IMAGE_MAX_SIZE
        """
        self.dpi = dpi if dpi is not None else IMAGE_DPI
        self.max_size = max_size if max_size is not None else IMAGE_MAX_SIZE

    def _convert_to_xlsx(self, file_path: str, temp_dir: str) -> str:
        """
        将旧版 .xls 格式转换为 .xlsx 格式

        Args:
            file_path: 原始 .xls 文件路径
            temp_dir: 临时目录

        Returns:
            转换后的 .xlsx 文件路径
        """
        try:
            # 使用 LibreOffice 转换为 xlsx
            result = subprocess.run([
                'libreoffice',
                '--headless',
                '--convert-to', 'xlsx',
                '--outdir', temp_dir,
                file_path
            ], check=True, capture_output=True, timeout=60)

            # LibreOffice 会在 temp_dir 中生成同名 .xlsx 文件
            original_name = Path(file_path).stem
            converted_path = os.path.join(temp_dir, original_name + ".xlsx")

            if os.path.exists(converted_path):
                return converted_path

            # 尝试在 temp_dir 中查找
            for f in os.listdir(temp_dir):
                if f.endswith('.xlsx'):
                    return os.path.join(temp_dir, f)

            raise RuntimeError("LibreOffice 转换失败，未生成 .xlsx 文件")

        except subprocess.TimeoutExpired:
            raise RuntimeError("Excel 格式转换超时")
        except Exception as e:
            raise RuntimeError(f"Excel 格式转换失败: {e}")

    def extract(self, file_path: str) -> str:
        """
        将 Excel 文档转换为 base64 编码的图片

        Args:
            file_path: Excel 文件路径 (.xlsx, .xls)

        Returns:
            base64 编码的图片字符串

        Raises:
            FileNotFoundError: 如果文件不存在
            RuntimeError: 如果转换失败
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = Path(file_path).suffix.lower()
        if ext not in ['.xlsx', '.xls']:
            raise ValueError(f"不支持的 Excel 格式: {ext}")

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 如果是 .xls 格式，先转换为 .xlsx
                process_path = file_path
                if ext == '.xls':
                    process_path = self._convert_to_xlsx(file_path, temp_dir)

                # 使用 LibreOffice 将 Excel 转换为 PDF
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
                raise RuntimeError("Excel 转换超时，请检查文件是否损坏")
            except Exception as e:
                raise RuntimeError(f"Excel 转换失败: {e}")

    def extract_xml(self, file_path: str) -> str:
        """
        提取 Excel 文档的原始 XML 内容
        自动转换旧版 .xls 格式为 .xlsx

        Args:
            file_path: Excel 文件路径 (.xlsx, .xls)

        Returns:
            原始 XML 字符串（包含所有工作表的合并内容）

        Raises:
            FileNotFoundError: 如果文件不存在
            ValueError: 如果文件格式不支持
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = Path(file_path).suffix.lower()
        if ext not in ['.xlsx', '.xls']:
            raise ValueError("不支持的 Excel 格式")

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 如果是 .xls 格式，先转换为 .xlsx
                process_path = file_path
                if ext == '.xls':
                    process_path = self._convert_to_xlsx(file_path, temp_dir)

                with zipfile.ZipFile(process_path, 'r') as zf:
                    # 获取所有工作表
                    sheet_files = sorted([name for name in zf.namelist()
                                         if name.startswith('xl/worksheets/sheet')
                                         and name.endswith('.xml')])

                    all_xml_parts = []

                    # 添加工作簿信息
                    if 'xl/workbook.xml' in zf.namelist():
                        workbook_xml = zf.read('xl/workbook.xml').decode('utf-8')
                        all_xml_parts.append('<!-- Workbook -->\n' + workbook_xml)

                    # 添加每个工作表的内容
                    for sheet_file in sheet_files:
                        sheet_xml = zf.read(sheet_file).decode('utf-8')
                        sheet_name = Path(sheet_file).stem
                        all_xml_parts.append(f'<!-- Sheet: {sheet_name} -->\n' + sheet_xml)

                    # 添加共享字符串表（包含所有文本值）
                    if 'xl/sharedStrings.xml' in zf.namelist():
                        shared_strings = zf.read('xl/sharedStrings.xml').decode('utf-8')
                        all_xml_parts.append('<!-- Shared Strings -->\n' + shared_strings)

                    return '\n'.join(all_xml_parts)

            except zipfile.BadZipFile:
                raise RuntimeError(f"无效的 Excel 文件: {file_path}")
            except Exception as e:
                raise RuntimeError(f"Excel XML 提取失败: {e}")

    def clean_xml(self, file_path: str) -> str:
        """
        清理 Excel XML 内容，提取结构化表格数据
        自动转换旧版 .xls 格式为 .xlsx

        Args:
            file_path: Excel 文件路径 (.xlsx, .xls)

        Returns:
            清理后的表格文本内容，格式为 JSON 字符串

        Raises:
            FileNotFoundError: 如果文件不存在
            ValueError: 如果文件格式不支持
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = Path(file_path).suffix.lower()
        if ext not in ['.xlsx', '.xls']:
            raise ValueError("不支持的 Excel 格式")

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 如果是 .xls 格式，先转换为 .xlsx
                process_path = file_path
                if ext == '.xls':
                    process_path = self._convert_to_xlsx(file_path, temp_dir)

                with zipfile.ZipFile(process_path, 'r') as zf:
                    # 读取共享字符串表
                    shared_strings = []
                    if 'xl/sharedStrings.xml' in zf.namelist():
                        ss_xml = zf.read('xl/sharedStrings.xml').decode('utf-8')
                        ss_root = ET.fromstring(ss_xml)
                        ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                        for si in ss_root.findall('.//ns:si', ns):
                            text_parts = []
                            for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'):
                                if t.text:
                                    text_parts.append(t.text)
                            shared_strings.append(''.join(text_parts))

                    # 获取工作表列表
                    sheet_files = sorted([(name, name)
                                         for name in zf.namelist()
                                         if name.startswith('xl/worksheets/sheet')
                                         and name.endswith('.xml')])

                    all_sheets_data = []

                    for sheet_file, _ in sheet_files:
                        sheet_xml = zf.read(sheet_file).decode('utf-8')
                        sheet_root = ET.fromstring(sheet_xml)

                        ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                        sheet_data = []

                        for row in sheet_root.findall('.//ns:row', ns):
                            row_num = int(row.get('r', 0))
                            row_cells = {}

                            for cell in row.findall('ns:c', ns):
                                cell_ref = cell.get('r', '')
                                col_ref = ''.join([c for c in cell_ref if c.isalpha()])

                                cell_type = cell.get('t', '')
                                cell_value = ''

                                v_elem = cell.find('ns:v', ns)
                                if v_elem is not None and v_elem.text:
                                    if cell_type == 's':
                                        idx = int(v_elem.text)
                                        if idx < len(shared_strings):
                                            cell_value = shared_strings[idx]
                                    elif cell_type == 'b':
                                        cell_value = 'TRUE' if v_elem.text == '1' else 'FALSE'
                                    else:
                                        cell_value = v_elem.text

                                is_elem = cell.find('ns:is', ns)
                                if is_elem is not None:
                                    text_parts = []
                                    for t in is_elem.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'):
                                        if t.text:
                                            text_parts.append(t.text)
                                    cell_value = ''.join(text_parts)

                                if cell_value or cell_ref:
                                    row_cells[col_ref] = cell_value

                            if row_cells:
                                sorted_cells = dict(sorted(row_cells.items()))
                                sheet_data.append({
                                    'row': row_num,
                                    'cells': sorted_cells
                                })

                    # 转换为易读的文本格式
                    sheet_text_lines = []
                    for row_info in sheet_data:
                        row_num = row_info['row']
                        cells = row_info['cells']
                        row_text = ' | '.join([f"{col}:{val}" for col, val in cells.items() if val])
                        if row_text:
                            sheet_text_lines.append(f"Row {row_num}: {row_text}")

                    all_sheets_data.append({
                        'sheet': Path(sheet_file).stem,
                        'rows': sheet_text_lines
                    })

                # 格式化为 JSON 输出
                import json
                result = {
                    'sheets': []
                }

                for sheet_info in all_sheets_data:
                    result['sheets'].append({
                        'name': sheet_info['sheet'],
                        'data': sheet_info['rows']
                    })

                return json.dumps(result, ensure_ascii=False, indent=2)

            except zipfile.BadZipFile:
                raise RuntimeError(f"无效的 Excel 文件: {file_path}")
            except Exception as e:
                raise RuntimeError(f"Excel XML 清理失败: {e}")

    def clean_xml_simple(self, file_path: str) -> str:
        """
        清理 Excel XML 内容，提取纯文本（简化版）
        自动转换旧版 .xls 格式为 .xlsx

        Args:
            file_path: Excel 文件路径 (.xlsx, .xls)

        Returns:
            清理后的纯文本内容

        Raises:
            FileNotFoundError: 如果文件不存在
            ValueError: 如果文件格式不支持
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = Path(file_path).suffix.lower()
        if ext not in ['.xlsx', '.xls']:
            raise ValueError("不支持的 Excel 格式")

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 如果是 .xls 格式，先转换为 .xlsx
                process_path = file_path
                if ext == '.xls':
                    process_path = self._convert_to_xlsx(file_path, temp_dir)

                with zipfile.ZipFile(process_path, 'r') as zf:
                    # 读取共享字符串表
                    shared_strings = []
                    if 'xl/sharedStrings.xml' in zf.namelist():
                        ss_xml = zf.read('xl/sharedStrings.xml').decode('utf-8')
                        ss_root = ET.fromstring(ss_xml)
                        for si in ss_root.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                            text_parts = []
                            for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'):
                                if t.text:
                                    text_parts.append(t.text)
                            shared_strings.append(''.join(text_parts))

                    # 获取工作表列表
                    sheet_files = sorted([name for name in zf.namelist()
                                         if name.startswith('xl/worksheets/sheet')
                                         and name.endswith('.xml')])

                    all_lines = []

                    for i, sheet_file in enumerate(sheet_files):
                        sheet_xml = zf.read(sheet_file).decode('utf-8')
                        sheet_root = ET.fromstring(sheet_xml)

                        all_lines.append(f"=== Sheet {i + 1} ===")

                        for row in sheet_root.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
                            row_cells = []
                            for cell in row.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                                cell_type = cell.get('t', '')
                                v_elem = cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                                if v_elem is not None and v_elem.text:
                                    if cell_type == 's':
                                        idx = int(v_elem.text)
                                        if idx < len(shared_strings):
                                            row_cells.append(shared_strings[idx])
                                    elif cell_type == 'b':
                                        row_cells.append('TRUE' if v_elem.text == '1' else 'FALSE')
                                    else:
                                        row_cells.append(v_elem.text)
                                else:
                                    is_elem = cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is')
                                    if is_elem is not None:
                                        text_parts = []
                                        for t in is_elem.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'):
                                            if t.text:
                                                text_parts.append(t.text)
                                        row_cells.append(''.join(text_parts))

                            if row_cells:
                                all_lines.append('\t'.join(str(c) for c in row_cells))

                        all_lines.append('')

                    return '\n'.join(all_lines)

            except zipfile.BadZipFile:
                raise RuntimeError(f"无效的 Excel 文件: {file_path}")
            except Exception as e:
                raise RuntimeError(f"Excel XML 清理失败: {e}")
