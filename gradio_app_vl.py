#!/usr/bin/env python3
import os
import json
import re
import sys
import base64
import uuid
import tempfile
import subprocess
from pathlib import Path
from typing import Tuple, List
from io import BytesIO

# 强制不走代理，确保本地服务访问
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

# 设置CUDA调试模式（可选，用于调试）
# os.environ["CUDA_LAUNCH_BLOCKING"] = "1"

import gradio as gr
import pandas as pd
from openai import OpenAI
from pdf2image import convert_from_path
from PIL import Image

# 获取项目根目录
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# 导入外部提取器
from extractors.pdf_extractor import PDFProcessor

# ========== 1. 基础配置与路径 ==========
OS_TEMP_DIR = "/home/yangqi/workspace/DocumentExtractor/tmp"
LOCAL_TMP = "/home/yangqi/workspace/DocumentExtractor/tmp"
os.makedirs(LOCAL_TMP, exist_ok=True)

os.environ["TMPDIR"] = LOCAL_TMP
os.environ["GRADIO_TEMP_DIR"] = os.path.join(LOCAL_TMP, "gradio_cache")
os.system(f"chmod -R 777 {LOCAL_TMP}")

VLLM_API_URL = "http://127.0.0.1:38000/v1"
VLLM_MODEL_NAME = "Qwen3-VL-4B-Instruct"
EXCEL_PATH = "/home/yangqi/workspace/DocumentExtractor/data/port_map.xlsx"

os.makedirs(OS_TEMP_DIR, exist_ok=True)

# ========== 2. 辅助工具与数据映射 ==========

def parse_number(val) -> float:
    """从字符串中提取数字 - 优化版"""
    if isinstance(val, (int, float)):
        return float(val)
    if not val or not isinstance(val, str):
        return 0.0
    
    # 移除空格和常见单位
    clean_val = str(val).strip().upper()
    # 移除单位
    for unit in ['KGS', 'KG', 'LBS', 'LB', 'CBM', 'M3', 'CFT', 'FT3', 'CTN', 'CTNS', 'PCS', 'PKGS', 'MT', 'TON', 'G', 'CM', 'M', 'MM']:
        clean_val = clean_val.replace(unit, '')
    
    clean_val = clean_val.strip()
    
    # 处理千分位逗号和小数点
    if '.' in clean_val and ',' in clean_val:
        comma_pos = clean_val.rfind(',')
        dot_pos = clean_val.rfind('.')
        if comma_pos < dot_pos:
            # 逗号在点前，逗号是千分位: 1,234.56
            clean_val = clean_val.replace(',', '')
        else:
            # 点在逗号前，可能是欧式: 1.234,56
            clean_val = clean_val.replace('.', '').replace(',', '.')
    elif ',' in clean_val:
        # 只有逗号，判断是千分位还是小数点
        parts = clean_val.split(',')
        if len(parts) == 2 and len(parts[-1]) == 3 and len(parts[0]) > 0:
            # 最后一段是3位，可能是千分位: 1,234
            clean_val = clean_val.replace(',', '')
        elif len(parts) == 2 and len(parts[-1]) <= 2:
            # 最后一段是1-2位，可能是小数点: 1,5
            clean_val = clean_val.replace(',', '.')
        else:
            # 多个逗号，当作千分位: 1,234,567
            clean_val = clean_val.replace(',', '')
    
    # 提取数字
    nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", clean_val)
    return float(nums[0]) if nums else 0.0

def safe_parse_number(value) -> float:
    """安全解析数字，确保返回浮点数"""
    if isinstance(value, (int, float)):
        return float(value)
    
    if isinstance(value, str):
        clean_value = value.strip().upper()
        # 移除单位
        for unit in ['KGS', 'KG', 'LBS', 'LB', 'CBM', 'M3', 'CFT', 'FT3', 'CTN', 'CTNS', 'PCS', 'PKGS', 'MT', 'TON', 'G', 'CM', 'M', 'MM']:
            clean_value = clean_value.replace(unit, '')
        
        clean_value = clean_value.strip()
        
        # 处理逗号
        if '.' in clean_value and ',' in clean_value:
            comma_pos = clean_value.rfind(',')
            dot_pos = clean_value.rfind('.')
            if comma_pos < dot_pos:
                clean_value = clean_value.replace(',', '')
            else:
                clean_value = clean_value.replace('.', '').replace(',', '.')
        elif ',' in clean_value:
            parts = clean_value.split(',')
            if len(parts) == 2 and len(parts[-1]) == 3 and len(parts[0]) > 0:
                clean_value = clean_value.replace(',', '')
            elif len(parts) == 2 and len(parts[-1]) <= 2:
                clean_value = clean_value.replace(',', '.')
            else:
                clean_value = clean_value.replace(',', '')
        
        try:
            return float(clean_value)
        except ValueError:
            match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', clean_value)
            if match:
                try:
                    return float(match.group())
                except ValueError:
                    return 0.0
    
    try:
        return float(value) if value is not None else 0.0
    except (ValueError, TypeError):
        return 0.0

def normalize_bool_text(text: str) -> int:
    """根据描述判定布尔值"""
    return 1 if text and len(str(text).strip()) > 0 else 0

def safe_calculate_hwmd(totals: dict) -> float:
    """安全计算 HWMD（货物重量密度）"""
    weight = safe_parse_number(totals.get("total_gross_weight", 0))
    volume = safe_parse_number(totals.get("total_volume", 1))
    
    if abs(volume) < 1e-10:
        return 0.0
    
    try:
        return round(weight / volume, 2)
    except (ZeroDivisionError, TypeError, ValueError):
        return 0.0

# ========== 3. 港口代码映射类 ==========

import re
import pandas as pd
import os
from difflib import SequenceMatcher

class PortMapper:
    _instance = None
    _is_initialized = False
    
    # 美国州代码映射
    US_STATE_CODES = {
        'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
        'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
        'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
        'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
        'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
        'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
        'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
        'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
        'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
        'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
        'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
        'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
        'WI': 'Wisconsin', 'WY': 'Wyoming'
    }
    
    # 常见国家代码
    COUNTRY_CODES = {
        'US': 'United States', 'GB': 'United Kingdom', 'UK': 'United Kingdom',
        'CN': 'China', 'JP': 'Japan', 'KR': 'Korea', 'SG': 'Singapore',
        'MY': 'Malaysia', 'TH': 'Thailand', 'VN': 'Vietnam', 'ID': 'Indonesia',
        'IN': 'India', 'AE': 'UAE', 'DE': 'Germany', 'FR': 'France',
        'NL': 'Netherlands', 'BE': 'Belgium', 'AU': 'Australia', 'CA': 'Canada'
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PortMapper, cls).__new__(cls)
        return cls._instance

    def initialize(self, excel_path: str):
        if self._is_initialized or not os.path.exists(excel_path):
            return
        try:
            df = pd.read_excel(excel_path)
            code_col = next((c for c in df.columns if "jcdm" in c.lower() or "代码" in c), None)
            name_col = next((c for c in df.columns if "jcmc" in c.lower() or "名称" in c), None)
            
            if code_col and name_col:
                self.lookup_dict = {}
                self.structured_ports = []
                self.exact_match_index = {}  # 精确匹配索引
                
                for _, row in df.iterrows():
                    code = str(row[code_col]).strip()
                    if code == 'nan' or not code:
                        continue
                    name = str(row[name_col]).strip()
                    
                    # 解析港口名称结构
                    port_info = self._parse_port_name(name, code)
                    self.structured_ports.append(port_info)
                    
                    # 建立精确匹配索引（标准化后的完整名称）
                    normalized_key = self._normalize_for_exact_match(name)
                    self.exact_match_index[normalized_key] = code
                    
                    # 存储原始名称
                    self.lookup_dict[name.lower()] = code
                
                print(f"✅ 港口映射表加载成功，共 {len(self.structured_ports)} 条记录")
                self._print_sample_ports()
            self._is_initialized = True
        except Exception as e:
            print(f"❌ 港口映射加载失败: {e}")
            self.lookup_dict = {}
            self.structured_ports = []

    def _print_sample_ports(self):
        """打印部分数据用于调试"""
        charleston_ports = [p for p in self.structured_ports if 'charleston' in p['city'].lower()]
        if charleston_ports:
            print("\n📍 Charleston 相关港口:")
            for port in charleston_ports[:5]:
                print(f"  {port['original_name']} -> {port['code']} "
                      f"[城市:{port['city']}, 州:{port['state']}, 国家:{port['country']}]")

    def _normalize_for_exact_match(self, name: str) -> str:
        """标准化用于精确匹配"""
        normalized = name.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = re.sub(r'\s*,\s*', ',', normalized)
        return normalized

    def _parse_port_name(self, name: str, code: str) -> dict:
        """
        解析港口名称，提取城市、州/省、国家信息
        支持多种格式：
        - "Charleston,SC,US"
        - "Charleston, SC"  
        - "Charleston,WV,US"
        - "Chichester, UK" (GBCHD)
        """
        # 从港口代码推断国家（UNLOC标准：前2位是国家代码）
        country_from_code = ''
        if len(code) >= 2:
            country_from_code = code[:2].upper()
        
        parts = [p.strip() for p in name.split(',')]
        
        port_info = {
            'original_name': name,
            'code': code,
            'city': '',
            'state': '',
            'country': country_from_code,  # 默认使用代码推断的国家
            'normalized_name': name.lower()
        }
        
        if len(parts) >= 1:
            port_info['city'] = parts[0].strip()
        
        # 从名称中提取州和国家信息
        for i, part in enumerate(parts[1:], 1):
            part_stripped = part.strip()
            part_upper = part_stripped.upper()
            
            # 美国州代码（2字母）
            if part_upper in self.US_STATE_CODES:
                port_info['state'] = part_upper
                port_info['country'] = 'US'  # 有州代码说明是美国
            # 其他2字母国家代码
            elif len(part_upper) == 2 and part_upper.isalpha():
                # 如果不是州代码，就是国家代码
                if part_upper not in self.US_STATE_CODES:
                    port_info['country'] = part_upper
            # 国家全称
            elif len(part_stripped) > 2:
                country_normalized = part_stripped.lower()
                # 映射到2字母代码
                for code_2letter, full_name in self.COUNTRY_CODES.items():
                    if full_name.lower() in country_normalized or country_normalized in full_name.lower():
                        port_info['country'] = code_2letter
                        break
                else:
                    port_info['country'] = part_upper[:2] if len(part_upper) >= 2 else part_upper
        
        return port_info

    def _parse_input_port(self, raw_name: str) -> dict:
        """解析输入的港口名称"""
        parts = [p.strip() for p in raw_name.split(',')]
        
        input_info = {
            'city': '',
            'state': '',
            'country': '',
            'original': raw_name,
            'has_explicit_state': False,
            'has_explicit_country': False
        }
        
        if len(parts) >= 1:
            input_info['city'] = parts[0].strip()
        
        for part in parts[1:]:
            part_stripped = part.strip()
            part_upper = part_stripped.upper()
            
            # 州代码
            if part_upper in self.US_STATE_CODES:
                input_info['state'] = part_upper
                input_info['country'] = 'US'
                input_info['has_explicit_state'] = True
                input_info['has_explicit_country'] = True
            # 国家代码
            elif len(part_upper) == 2 and part_upper.isalpha():
                if part_upper not in self.US_STATE_CODES:
                    input_info['country'] = part_upper
                    input_info['has_explicit_country'] = True
        
        return input_info

    def _calculate_match_score(self, input_info: dict, port_info: dict) -> float:
        """
        计算匹配分数（改进版）
        
        评分规则：
        1. 城市名匹配：基础40分
        2. 国家匹配：必须匹配（不匹配直接-100分）
        3. 州代码匹配：40分（美国港口）
        4. 代码格式加分：海运5字母代码+5分
        """
        score = 0.0
        
        # ===== 关键：国家代码强制匹配 =====
        if input_info['has_explicit_country'] or input_info['has_explicit_state']:
            # 用户明确指定了国家或州（州意味着美国）
            expected_country = input_info['country'].upper()
            actual_country = port_info['country'].upper()
            
            if expected_country and actual_country:
                if expected_country != actual_country:
                    # 国家不匹配，直接淘汰
                    return -100.0
                else:
                    score += 30  # 国家匹配奖励
        
        # ===== 城市名匹配 =====
        city_input = input_info['city'].lower()
        city_port = port_info['city'].lower()
        
        if city_input == city_port:
            score += 40
        elif city_input in city_port or city_port in city_input:
            # 部分匹配（例如 Charleston 可能匹配 Charleston Port）
            ratio = SequenceMatcher(None, city_input, city_port).ratio()
            score += 40 * ratio
        else:
            # 城市名完全不匹配
            return -100.0
        
        # ===== 州代码匹配（美国特有） =====
        if input_info['state']:
            if port_info['state']:
                if input_info['state'] == port_info['state']:
                    score += 40  # 州代码完全匹配
                else:
                    # 州代码不匹配，严重扣分
                    score -= 50
            else:
                # 用户提供了州代码，但港口数据没有
                score -= 20
        
        return score

    def get_code(self, raw_name: str, default_val: str = "", transport_mode: str = "") -> str:
        """
        根据港口名称获取代码（最终版）
        
        Args:
            raw_name: 原始港口名称，例如 "CHARLESTON, SC"
            default_val: 默认返回值
            transport_mode: 运输方式
        """
        if not raw_name:
            return default_val
        
        # 解析输入
        input_info = self._parse_input_port(raw_name)
        
        # 1. 精确匹配
        normalized = self._normalize_for_exact_match(raw_name)
        if normalized in self.exact_match_index:
            result = self.exact_match_index[normalized]
            print(f"✅ 精确匹配: '{raw_name}' -> {result}")
            return result
        
        # 2. 结构化打分匹配
        is_sea_transport = transport_mode.upper() in ['SEA', 'OCEAN', 'YSFS_HY', '海运', 'VESSEL', 'SHIP']
        
        candidates = []
        for port_info in self.structured_ports:
            score = self._calculate_match_score(input_info, port_info)
            
            if score > 0:  # 只保留正分候选
                # 海运优先UNLOC代码
                if is_sea_transport:
                    code = port_info['code']
                    if len(code) == 5 and code.isalpha():
                        score += 5
                
                candidates.append((score, port_info['code'], port_info['original_name'], port_info))
        
        if candidates:
            # 按分数排序
            candidates.sort(reverse=True, key=lambda x: x[0])
            best_match = candidates[0]
            
            # 调试输出（显示前3个候选）
            print(f"\n🔍 匹配结果: '{raw_name}'")
            for i, (s, c, n, info) in enumerate(candidates[:3], 1):
                print(f"  {i}. {n} ({c}) [得分:{s:.1f}] 国家:{info['country']} 州:{info['state']}")
            
            return best_match[1]
        
        print(f"⚠️  未找到匹配: '{raw_name}'")
        return default_val


port_mapper = PortMapper()
port_mapper.initialize(EXCEL_PATH)    

    

    

    


# ========== 4. 视觉推理与图像处理 ==========

def get_document_image_base64(file_path: str) -> str:
    """PDF/图片转base64编码 - 优化版，支持多页拼接"""
    file_ext = Path(file_path).suffix.lower()
    
    try:
        if file_ext == '.pdf':
            # 转换所有页面，提高DPI确保小字清晰
            images = convert_from_path(file_path, dpi=350)
            
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
        else:
            img = Image.open(file_path).convert("RGB")
        
        # 限制图像大小，避免CUDA内存问题
        max_size = 4096
        if img.width > max_size or img.height > max_size:
            ratio = min(max_size / img.width, max_size / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=95)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"❌ 图像处理失败: {e}")
        raise
def compress_image_b64(image_b64: str, max_size: int = 2048) -> str:
    """压缩base64图片"""
    import io
    import base64
    from PIL import Image
    img_data = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(img_data))
    
    w, h = img.size
    if max(w, h) > max_size:
        img.thumbnail((max_size, max_size))
    
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()
def call_vlm_service(system_prompt: str, user_prompt: str, image_b64: str = None):
    """调用 VLLM 多模态接口 - 优化版，添加错误处理"""
    try:
        client = OpenAI(
            api_key="EMPTY", 
            base_url=VLLM_API_URL,
            timeout=300.0  # 增加超时时间
        )
        
        content = [{"type": "text", "text": user_prompt}]
        if image_b64:
            image_b64 = compress_image_b64(image_b64)  # ← 加这一行
            content.insert(0, {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
            })
        if image_b64:
            content.insert(0, {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
            })
        
        response = client.chat.completions.create(
            model=VLLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            max_tokens=4096,
            temperature=0.1,
            # 添加额外参数以提高稳定性
            top_p=0.9,
        )
        
        res = response.choices[0].message.content.strip()
        # 清理可能的 markdown 代码块标记
        res = re.sub(r'```json\s*|\s*```', '', res, flags=re.DOTALL)
        return res
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ VLM推理失败: {e}\n{error_detail}")
        return json.dumps({"error": f"推理失败: {str(e)}"}, ensure_ascii=False)

# ========== 5. Excel/Word 处理类 ==========

class ExcelExtractor:
    """将 Excel 渲染为图片，返回 Base64 - 优化版"""
    def extract(self, file_path: str) -> str:
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 转换 PDF
                subprocess.run([
                    'libreoffice', 
                    '--headless', 
                    '--convert-to', 'pdf',
                    '--outdir', temp_dir,
                    file_path
                ], check=True, timeout=60)
                
                pdf_name = Path(file_path).stem + ".pdf"
                pdf_path = os.path.join(temp_dir, pdf_name)
                
                if not os.path.exists(pdf_path):
                    raise FileNotFoundError(f"PDF conversion failed: {pdf_path}")
                
                # 渲染所有页面，提高DPI
                images = convert_from_path(pdf_path, dpi=350)
                
                img = images[0]
                
                # 限制图像大小
                max_size = 4096
                if img.width > max_size or img.height > max_size:
                    ratio = min(max_size / img.width, max_size / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)
                
                buffered = BytesIO()
                img.convert("RGB").save(buffered, format="JPEG", quality=95)
                return base64.b64encode(buffered.getvalue()).decode('utf-8')
            except Exception as e:
                print(f"❌ Excel转换失败: {e}")
                raise

class WordExtractor:
    """将 Word 渲染为图片，返回 Base64 - 优化版"""
    def extract(self, file_path: str) -> str:
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 转换 PDF
                subprocess.run([
                    'libreoffice', 
                    '--headless', 
                    '--convert-to', 'pdf',
                    '--outdir', temp_dir,
                    file_path
                ], check=True, timeout=60)
                
                pdf_name = Path(file_path).stem + ".pdf"
                pdf_path = os.path.join(temp_dir, pdf_name)
                
                if not os.path.exists(pdf_path):
                    raise FileNotFoundError(f"PDF conversion failed: {pdf_path}")
                
                # 渲染所有页面
                images = convert_from_path(pdf_path, dpi=350)
                
                img = images[0]
                
                # 限制图像大小
                max_size = 4096
                if img.width > max_size or img.height > max_size:
                    ratio = min(max_size / img.width, max_size / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)
                
                buffered = BytesIO()
                img.convert("RGB").save(buffered, format="JPEG", quality=95)
                return base64.b64encode(buffered.getvalue()).decode('utf-8')
            except Exception as e:
                print(f"❌ Word转换失败: {e}")
                raise

# ========== 6. Prompt 定义 ==========

SYSTEM_PROMPT = """你是一个专业的物流单据信息提取助手。请根据提供的图像，仔细分析布局，提取关键信息。

## 核心提取原则：
1. **只提取指定字段**：只提取JSON模板中列出的字段。
2. **直接提取原始文本**：不要进行任何代码转换或映射。
3. **保持原始格式**：保持原始拼写和格式。
4. **不编造信息**：未找到的信息返回空字符串 ""。
5. **严格JSON输出**：只返回JSON，不添加任何注释。
6. **数值处理**：
   - 提取数字时保留数值，去掉单位（如 "100 KGS" → "100"）
   - 注意区分千分位逗号和小数点
   - 如果有多个货物项，每项的重量/体积分别提取
   - **重要**：如果看到单件重量，需要乘以件数得到该项总重量

## 特别注意事项：

### 1. 运输方式识别
- **空运标识**：AIR, BY AIR, AIR FREIGHT, 航空, 空运, Flight No., AWB, MAWB, HAWB
- **海运标识**：SEA, OCEAN, BY SEA, VESSEL, 海运, 船运, B/L, BILL OF LADING, Voyage No., MBL, HBL
- **铁路标识**：RAIL, TRAIN, RAILWAY, 铁路, 火车

### 2. 港口识别
- **起运港**：Port of Loading, POL, Origin, Departure, 起运港, 始发地, From
- **目的港**：Port of Discharge, POD, Destination, 目的港, 卸货港, To
- **收货地**：Port of Receipt, Place of Receipt（这不是目的港，不要混淆）
- 提取完整的港口名称（如 "SHANGHAI, CHINA" 或 "SHANGHAI"）
- 注意：海运港口通常是完整的城市名（如SHANGHAI, SINGAPORE）

### 3. 通知方识别
- 如果看到 "SAME AS CONSIGNEE", "AS ABOVE", "SAME AS ABOVE", "同收货人" 等，
  将 notify_party_full_information 填写为与 consignee_full_information 相同的内容

### 4. 发货人识别
- 发货人信息可能出现在：
  - 文档标题区域
  - "Shipper", "Consignor", "发货人", "托运人" 标签后
  - 表格的第一栏
  - 页面顶部的公司信息
- 提取完整的公司名、地址、联系方式

### 5. 计费方式识别
- **现结**：现结, 现金, 现付, 现金结算, CASH, CASH SETTLEMENT, CASH PAYMENT
- **月结**：月结, 月付, 月度结算, MONTHLY, MONTHLY SETTLEMENT, MONTHLY PAYMENT

### 6. 货物信息提取（重要）
- **麦头/唛头** (marks)：包装上的标记、符号、编号（如 "N/M", "C/NO", 箱号等）
- **长宽高**：注意单位，可能是CM或M，统一提取数值
- **件数和重量**：
  - 如果文档显示 "10 CTN x 50 KG"，表示10件，每件50KG
  - 此时 quantity = 10, gross_weight = 500（10 x 50）
  - **关键**：需要计算总重量而非单件重量
- **多行货物**：每行货物单独提取，不要合并
- **体积**：可能标注为CBM, M3, 立方米等

### 7. 集装箱识别
- **箱型**：
  - 20GP, 20DC, 20', 20FT, 20尺 → 20尺干货箱
  - 40GP, 40DC, 40', 40FT, 40尺 → 40尺干货箱
  - 40HQ, 40HC, 40HQS → 40尺高柜
  - 45HC → 45尺高柜
  - 20OT, 40OT → 开顶箱
  - RF, REEFER → 冷藏箱
- 注意识别小字，可能在表格底部或角落

### 8. 运输单号识别
- **海运**：
  - B/L No., Bill of Lading No., 提单号
  - Booking No., 订舱号
  - Voyage No.(航次), 格式如 V123, 024E
  - Vessel(船名), 如 MSC ANNA, EVER GIVEN
- **空运**：
  - AWB No., MAWB, HAWB, 运单号
  - Flight No.(航班号), 格式如 CX123, CA456, MU789
  - 航班号通常是2-3个字母+3-4个数字

### 9. 危险品识别
- 看到以下标识时，推断为危险品：
  - DG, Dangerous, Hazardous, UN, 危险品, 危
  - UN编号（如UN1234）
  - Class标识（如Class 3, Class 8）
  - IMO标识
  
### 10. 重量和体积
- **重量单位**：KGS, KG, LBS, LB, MT, TON, G
- **体积单位**：CBM, M3, CFT, FT3, 立方米
- 注意识别：
  - "G.W."(毛重), "Gross Weight"
  - "N.W."(净重), "Net Weight"
  - "Total"(总计)
  - 单件重量 vs 总重量
- **关键**：如果有总计行，优先提取总计数据

### 11. 发货人在标题的特殊情况
- 有些托书的发货人信息出现在文档标题或页眉位置
- 注意检查整个文档顶部区域

## 必须提取的字段：

### 1. 联系信息（必填）
- **shipper_full_information**：发货人完整信息（包括公司名、地址、联系方式）
- **consignee_full_information**：收货人完整信息
- **notify_party_full_information**：通知人完整信息（注意"SAME AS CONSIGNEE"情况）
- **sales_contact**：销售联系人姓名

### 2. 运输信息（必填）
- **booking_number**：提单号/订舱号/运单号
- **transport_mode_raw**：运输方式原文（如 "Sea Freight", "Air Cargo"）
- **shipment_type_raw**：装运类型原文（如 "FCL", "LCL"）
- **freight_term_raw**：运费条款原文（如 "Prepaid", "Collect"）
- **payment_method_raw**：计费方式原文（现结/月结）

### 3. 港口信息（必填）
- **port_of_loading**：起运港英文全名（如 "SHANGHAI, CHINA"）
- **port_of_discharge**：目的港英文全名（如 "LOS ANGELES, USA"）

### 4. 货物汇总（必填）
- **total_quantity**：总件数（纯数字）
- **total_gross_weight**：总毛重（纯数字，单位KG）
- **total_volume**：总体积（纯数字，单位CBM）

### 5. 货物明细（必填，数组）
每个货物项包含：
- **description**：货物品名
- **quantity**：件数（纯数字）
- **package_unit_raw**：包装单位原文（如 "Cartons", "Pallets"）
- **gross_weight**：该项毛重（纯数字，**如有单件重量需乘以件数**）
- **volume**：该项体积（纯数字）
- **length**, **width**, **height**：长宽高（纯数字）
- **marks**：麦头/唛头

### 6. 集装箱信息（如有）
- **container_type_raw**：箱型原文（如 "40HQ", "20GP"）

### 7. 运输详情（如有）
- **flight_number_raw**：航班号（空运，如 "CX123"）
- **voyage_number_raw**：航次号（海运，如 "V123"）
- **vessel_name_raw**：船名（海运，如 "MSC ANNA"）
"""

USER_PROMPT = """
## 输出要求：
请严格返回以下JSON结构：

{
  "parties": {
    "shipper_full_information": "发货人完整信息（检查标题区域）",
    "consignee_full_information": "收货人完整信息",
    "notify_party_full_information": "通知人完整信息（注意SAME AS CONSIGNEE）",
    "sales_contact": "销售/联系人姓名"
  },
  "basic_info": {
    "booking_number": "提单号/订舱号/运单号",
    "transport_mode_raw": "运输方式原文",
    "shipment_type_raw": "装运类型原文",
    "freight_term_raw": "运费条款原文",
    "payment_method_raw": "计费方式原文（现结/月结）",
    "flight_number_raw": "航班号（空运，如CX123）",
    "voyage_number_raw": "航次号（海运，如V123）",
    "vessel_name_raw": "船名（海运）"
  },
  "locations": {
    "port_of_loading": "起运港英文全名（区分Port of Receipt）",
    "port_of_discharge": "目的港英文全名"
  },
  "cargo_totals": {
    "total_quantity": "总件数（纯数字）",
    "total_gross_weight": "总毛重（纯数字，单位KG）",
    "total_volume": "总体积（纯数字，单位CBM）"
  },
  "cargo_items": [
    {
      "description": "货物品名",
      "quantity": "件数（纯数字）",
      "package_unit_raw": "包装单位原文",
      "gross_weight": "该项毛重（需乘以件数）",
      "volume": "该项体积（纯数字）",
      "length": "长度（纯数字）",
      "width": "宽度（纯数字）",
      "height": "高度（纯数字）",
      "marks": "麦头/唛头"
    }
  ],
  "container_list": [
    {
      "container_type_raw": "箱型原文（如40HQ, 20GP）"
    }
  ]
}

请直接返回JSON结果，不要添加任何说明文字。"""

# ========== 7. API 格式转换（继续下一部分）==========

def transform_to_api_format(llm_json_str: str) -> str:
    """
    处理VLM模型返回的JSON，转换为系统API需要的格式 - 完整优化版
    """
    try:
        data = json.loads(llm_json_str)
        basic = data.get("basic_info", {})
        locs = data.get("locations", {})
        parties = data.get("parties", {})
        totals = data.get("cargo_totals", {})
        cargo_items = data.get("cargo_items", [])
        container_list = data.get("container_list", [])
        
        # ========== 辅助函数 ==========
        def fuzzy_map_safe(raw_value, mapping_list, default_value=""):
            """安全的模糊匹配，匹配失败返回空"""
            if not raw_value:
                return default_value
            
            raw_lower = str(raw_value).lower().strip()
            
            # 完全匹配
            for mapping in mapping_list:
                for key in mapping.get("keywords", []):
                    if key.lower() == raw_lower:
                        return mapping["code"]
            
            # 部分匹配（优先长词）
            sorted_mappings = sorted(mapping_list, 
                                    key=lambda x: max(len(k) for k in x.get("keywords", [""])), 
                                    reverse=True)
            
            for mapping in sorted_mappings:
                for key in mapping.get("keywords", []):
                    if len(key) >= 3 and (key.lower() in raw_lower or raw_lower in key.lower()):
                        return mapping["code"]
            
            return ""
        
        # ========== 映射表定义 ==========
        transport_mappings = [
            {"code": "YSFS_HY", "keywords": ["海运", "sea", "ocean", "船运", "maritime", "shipping", "vessel", "b/l", "bill of lading", "sea freight"]},
            {"code": "YSFS_TL", "keywords": ["铁路", "rail", "train", "railway", "rail transport", "rail freight"]},
            {"code": "YSFS_KY", "keywords": ["空运", "air", "航空", "air freight", "air transport", "air cargo", "awb", "airway bill", "flight", "by air"]}
        ]
        
        shipment_mappings = [
            {"code": "YSBZ_PX", "keywords": ["拼箱", "lcl", "less than container", "拼柜", "consolidation", "consol", "less container load"]},
            {"code": "YSBZ_ZX", "keywords": ["整箱", "fcl", "full container", "整柜", "full container load"]},
            {"code": "YSBZ_SZH", "keywords": ["break bulk", "散杂货", "散货", "bulk", "bulk cargo", "break-bulk"]}
        ]
        
        # 空运服务类型
        air_service_mappings = [
            {"code": "GDFWLX_2", "keywords": ["door to airport", "门到机场", "d2a", "door-airport"]},
            {"code": "GDFWLX_3", "keywords": ["airport to door", "机场到门", "a2d", "airport-door"]},
            {"code": "GDFWLX_4", "keywords": ["airport to airport", "机场到机场", "a2a", "airport-airport", "port to port"]}
        ]
        
        # 海运/铁路服务类型
        sea_service_mappings = [
            {"code": "GDFWLX_1", "keywords": ["door to door", "门到门", "d2d", "door-door"]},
            {"code": "GDFWLX_6", "keywords": ["door to cfs", "门到cfs", "d2cfs", "door-cfs"]},
            {"code": "GDFWLX_7", "keywords": ["cfs to door", "cfs到门", "cfs2d", "cfs-door"]},
            {"code": "GDFWLX_8", "keywords": ["cfs to cfs", "cfs到cfs", "cfs2cfs", "cfs-cfs"]},
            {"code": "GDFWLX_9", "keywords": ["door to cy", "门到cy", "d2cy", "door-cy"]},
            {"code": "GDFWLX_10", "keywords": ["cy to door", "cy到门", "cy2d", "cy-door"]},
            {"code": "GDFWLX_11", "keywords": ["cy to cy", "cy到cy", "cy2cy", "cy-cy", "port to port", "pier to pier"]}
        ]
        
        payment_mappings = [
            {"code": "YFTK_1", "keywords": ["prepaid", "预付", "pp", "pre pay", "prepaid freight", "freight prepaid", "pre-paid"]},
            {"code": "YFTK_2", "keywords": ["collected", "到付", "collect", "cc", "freight collect", "freight collected"]}
        ]
        
        cargo_type_mappings = [
            {"code": "HWLX_WXP", "keywords": ["dangerous", "hazardous", "dg", "dangerous goods", "hazardous material", "危险品", "危", "un", "imdg", "class"]},
            {"code": "HWLX_WKHW", "keywords": ["temperature control", "温控", "temperature controlled", "reefer", "冷藏", "冷冻", "refrigerated", "frozen"]},
            {"code": "HWLX_XHYF", "keywords": ["perishable", "fresh", "易腐", "perishable goods", "鲜活"]},
            {"code": "HWLX_GZWP", "keywords": ["valuable", "precious", "valuable goods", "高价值", "贵重"]},
            {"code": "HWLX_PH", "keywords": ["general cargo", "普货", "普通货物", "general", "regular cargo", "dry cargo"]}
        ]
        
        package_mappings = [
            {"code": "BZLX_ZX", "keywords": ["纸箱", "carton", "cartons", "纸盒", "cardboard box", "ctn", "ctns"]},
            {"code": "BZLX_TP", "keywords": ["托盘", "pallet", "pallets", "托", "wooden pallet", "plt", "plts", "skid"]},
            {"code": "BZLX_MX", "keywords": ["木箱", "wooden case", "木盒", "wooden box", "wooden crate", "case", "cases"]},
            {"code": "BZLX_BTX", "keywords": ["板条箱", "crate", "crates"]},
            {"code": "BZLX_B", "keywords": ["包", "bag", "bags", "sack", "sacks"]},
            {"code": "BZLX_TT", "keywords": ["铁桶", "iron drum", "steel drum", "metal drum", "drum", "drums"]},
            {"code": "BZLX_J", "keywords": ["件", "package", "packages", "piece", "pc", "pcs", "pieces", "pkg", "pkgs"]}
        ]
        
        container_mappings = [
            {"code": "JZXGG_1", "keywords": ["20gp", "20'gp", "20dc", "20'dc", "20'", "20尺", "20' dry", "20ft", "20 gp", "20 dc"]},
            {"code": "JZXGG_2", "keywords": ["40gp", "40'gp", "40dc", "40'dc", "40'", "40尺", "40' dry", "40ft", "40 gp", "40 dc"]},
            {"code": "JZXGG_3", "keywords": ["40hq", "40'hq", "40hc", "40'hc", "40'high", "40尺高柜", "40' high cube", "40 hq", "40 hc"]},
            {"code": "JZXGG_26", "keywords": ["45hc", "45'hc", "45'", "45尺", "45' high cube", "45 hc"]},
            {"code": "JZXGG_19", "keywords": ["reefer", "冷箱", "冷柜", "refrigerated", "rf"]},
            {"code": "JZXGG_8", "keywords": ["20ot", "20' open top", "20'open", "20尺开顶", "20 ot", "20 open"]},
            {"code": "JZXGG_18", "keywords": ["40ot", "40' open top", "40'open", "40尺开顶", "40 ot", "40 open"]}
        ]
        
        payment_method_mappings = [
            {"code": "JSYQ_XJ", "keywords": ["现结", "现金", "现金结算", "现付", "cash", "cash settlement", "cash payment"]},
            {"code": "JSYQ_YJ", "keywords": ["月结", "月度结算", "月付", "monthly", "monthly settlement", "monthly payment"]}
        ]
        
        incoterm_mappings = [
            {"code": "GDTK_16", "keywords": ["fob", "free on board", "船上交货"]},
            {"code": "GDTK_12", "keywords": ["cif", "cost insurance and freight", "成本加保险费运费"]},
            {"code": "GDTK_13", "keywords": ["cfr", "c&f", "c and f", "cost and freight", "成本加运费"]},
            {"code": "GDTK_3", "keywords": ["exw", "ex works", "工厂交货", "ex-works"]},
            {"code": "GDTK_2", "keywords": ["ddp", "delivered duty paid", "完税后交货"]},
            {"code": "GDTK_1", "keywords": ["dap", "delivered at place", "目的地交货"]},
            {"code": "GDTK_8", "keywords": ["fca", "free carrier", "货交承运人"]},
            {"code": "GDTK_7", "keywords": ["cip", "carriage and insurance paid", "运费保险费付至"]},
            {"code": "GDTK_6", "keywords": ["cpt", "carriage paid to", "运费付至"]}
        ]
        
        # ========== 运输方式识别 ==========
        transport_raw = basic.get("transport_mode_raw", "")
        ysfs_code = fuzzy_map_safe(transport_raw, transport_mappings, "")
        
        # ========== 装运类型识别 ==========
        shipment_raw = basic.get("shipment_type_raw", "")
        # 空运默认不填cplb和ysbz
        if ysfs_code == "YSFS_KY":
            cplb_code = ""
            ysbz_code = ""
        else:
            cplb_code = fuzzy_map_safe(shipment_raw, shipment_mappings, "")
            ysbz_code = cplb_code
        
        # ========== 服务类型识别 ==========
        freight_term_raw = basic.get("freight_term_raw", "")
        fwlx_code = ""
        
        if ysfs_code == "YSFS_KY":
            # 空运服务类型
            fwlx_code = fuzzy_map_safe(freight_term_raw, air_service_mappings, "GDFWLX_4")
        else:
            # 海运/铁路服务类型
            fwlx_code = fuzzy_map_safe(freight_term_raw, sea_service_mappings, "")
            # 根据cplb推断
            if not fwlx_code and cplb_code:
                if cplb_code == "YSBZ_ZX":
                    fwlx_code = "GDFWLX_11"
                elif cplb_code == "YSBZ_PX":
                    fwlx_code = "GDFWLX_8"
        
        # ========== 预付/到付条款 ==========
        yftk_code = fuzzy_map_safe(freight_term_raw, payment_mappings, "")
        
        # ========== 运费条款 (Incoterm) ==========
        incoterm_raw = basic.get("incoterm_raw", "")
        if not incoterm_raw:
            incoterm_raw = freight_term_raw
        gdtk_code = fuzzy_map_safe(incoterm_raw, incoterm_mappings, "")
        
        # ========== 计费方式 ==========
        payment_method_raw = basic.get("payment_method_raw", "")
        jsyq_code = fuzzy_map_safe(payment_method_raw, payment_method_mappings, "")
        
        # ========== 港口代码转换 ==========
        raw_sfg = locs.get("port_of_loading", "")
        raw_mdg = locs.get("port_of_discharge", "")
        
        # 传入运输方式辅助判断
        sfg_code = port_mapper.get_code(raw_sfg, default_val=raw_sfg, transport_mode=ysfs_code)
        mdg_code = port_mapper.get_code(raw_mdg, default_val=raw_mdg, transport_mode=ysfs_code)
        
        # ========== 运输单号识别 ==========
        flight_number = basic.get("flight_number_raw", "")
        voyage_number = basic.get("voyage_number_raw", "")
        vessel_name = basic.get("vessel_name_raw", "")
        
        hbh = ""
        if ysfs_code == "YSFS_KY" and flight_number:
            hbh = flight_number
        elif ysfs_code == "YSFS_HY":
            if voyage_number:
                hbh = voyage_number
            elif vessel_name:
                hbh = vessel_name
        
        # ========== 集装箱规格 ==========
        container_type = ""
        if container_list and len(container_list) > 0:
            container_type_raw = container_list[0].get("container_type_raw", "")
            container_type = fuzzy_map_safe(container_type_raw, container_mappings, "")
        
        # ========== 货物列表处理 ==========
        hw_list = []
        marks = ""
        description = ""
        
        for item in cargo_items:
            package_unit = item.get("package_unit_raw", "")
            bzlx_code = fuzzy_map_safe(package_unit, package_mappings, "")
            
            if not marks:
                marks = item.get("marks", "")
            if not description:
                description = item.get("description", "")
            
            quantity = safe_parse_number(item.get("quantity", 0))
            gross_weight = safe_parse_number(item.get("gross_weight", 0))
            volume = safe_parse_number(item.get("volume", 0))
            
            hw_list.append({
                "isTrue": True,
                "hhjs": quantity,
                "zl": gross_weight,
                "tj": volume,
                "cd": safe_parse_number(item.get("length", 0)),
                "kd": safe_parse_number(item.get("width", 0)),
                "gd": safe_parse_number(item.get("height", 0)),
                "sfkdd": "",
                "sfwxp": "",
                "sfkwdkz": "",
                "bzlx": bzlx_code,
                "jldw": "0",
                "kjdw": "1"
            })
        
        # ========== 海运信息列表 ==========
        hyxxList = []
        if container_list:
            for container in container_list:
                container_type_raw = container.get("container_type_raw", "")
                jzxgg = fuzzy_map_safe(container_type_raw, container_mappings, "")
                if jzxgg:  # 只添加成功识别的
                    hyxxList.append({
                        "jzxgg": jzxgg,
                        "tenantid": "",
                        "jzxjsbygg": "1"
                    })
        elif container_type:
            hyxxList.append({
                "jzxgg": container_type,
                "tenantid": "",
                "jzxjsbygg": "1"
            })
        
        # ========== 汇总信息 ==========
        total_quantity = safe_parse_number(totals.get("total_quantity", 0))
        total_weight = safe_parse_number(totals.get("total_gross_weight", 0))
        total_volume = safe_parse_number(totals.get("total_volume", 0))
        
        # 如果汇总为0，从明细计算
        if total_quantity == 0 and hw_list:
            total_quantity = sum(item["hhjs"] for item in hw_list)
        if total_weight == 0 and hw_list:
            total_weight = sum(item["zl"] for item in hw_list)
        if total_volume == 0 and hw_list:
            total_volume = sum(item["tj"] for item in hw_list)
        
        # 计算密度
        hwmd = safe_calculate_hwmd({
            "total_gross_weight": total_weight,
            "total_volume": total_volume
        })
        
        # ========== 通知方处理 ==========
        notify_info = parties.get("notify_party_full_information", "")
        consignee_info = parties.get("consignee_full_information", "")
        
        notify_lower = notify_info.lower()
        if any(keyword in notify_lower for keyword in ["same as consignee", "same as above", "as above", "as consignee", "同收货人", "同上"]):
            notify_info = consignee_info
        
        # ========== 货物类型推断 ==========
        hwlx_code = "HWLX_PH"  # 默认普货
        
        # 从货物描述推断
        all_descriptions = " ".join([item.get("description", "") for item in cargo_items]).lower()
        
        # 优先检查危险品
        for mapping in cargo_type_mappings:
            if mapping["code"] == "HWLX_WXP":
                for keyword in mapping["keywords"]:
                    if keyword.lower() in all_descriptions:
                        hwlx_code = mapping["code"]
                        break
                if hwlx_code == "HWLX_WXP":
                    break
        
        # 如果不是危险品，检查其他类型
        if hwlx_code == "HWLX_PH":
            for mapping in cargo_type_mappings:
                if mapping["code"] != "HWLX_PH":
                    for keyword in mapping["keywords"]:
                        if keyword.lower() in all_descriptions:
                            hwlx_code = mapping["code"]
                            break
                    if hwlx_code != "HWLX_PH":
                        break
        
        # ========== 构造最终API数据 ==========
        api_data = {
            # 基础信息
            "placeReceipt": "",
            "portDischarge": raw_mdg,
            "ysfs": ysfs_code,
            "cplb": cplb_code,
            "fwtk": gdtk_code,
            "fwlx": fwlx_code,
            "tkdd": "",
            "yftk": yftk_code,
            "sfg": sfg_code,
            "mdg": mdg_code,
            "lhgbh": basic.get("booking_number", ""),
            
            # 货物信息
            "hwList": hw_list,
            
            # 货物汇总
            "hwhjjs": total_quantity,
            "hwhjzl": total_weight,
            "hwtj": total_volume,
            "hwhjfzl": "",
            "hwmd": hwmd,
            "jzxsl": len(hyxxList),
            "jfd": "0",
            "hwjfzl": "0.00",
            
            # 额度与结算
            "sxed": "",
            "sysxed": "",
            "jsyq": jsyq_code,
            
            # 联系信息
            "fhrjtxx": parties.get("shipper_full_information", ""),
            "shrjtxx": consignee_info,
            "tzfjtxx": notify_info,
            "xsmc": parties.get("sales_contact", ""),
            
            # 客户与合作伙伴
            "tenantid": "",
            "kh": "",
            "khz": "",
            "fhr": "",
            "csshr": "",
            
            # 货物属性
            "hwlx": hwlx_code,
            "minwd": "",
            "maxwd": "",
            "hwwxplb": "",
            "ysbz": ysbz_code,
            "gdbq": "",
            "hwms": description,
            "hwmt": marks,
            "hwbq": "",
            
            # 任务信息
            "gjysgdRwList": [{
                "rwdm": "",
                "rwmc": "国际运输",
                "rwdd": "",
                "hbXXList": [{
                    "sfjc": sfg_code,
                    "ddjc": mdg_code,
                    "hbh": hbh
                }]
            }],
            
            # 集装箱信息
            "jzxgg": container_type,
            "jzxjsbygg": "1",
            "hyxxList": hyxxList,
            
            # 其他
            "hdGdFymxList": [],
            "hdGdFyjlList": [],
            "fjList": [],
            "sycpdm": "",
            "sfggdRwList": [],
            "mdggdRwList": [],
            "yjtime": "",
            "isTimeChange": "0",
            "sfgsq": "",
            "mdgsq": ""
        }
        
        return json.dumps(api_data, ensure_ascii=False, indent=2)
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ API格式转换失败: {e}\n{error_detail}")
        return json.dumps({
            "error": f"API格式转换失败: {str(e)}",
            "detail": error_detail,
            "raw_response": llm_json_str
        }, ensure_ascii=False)

# ========== 8. 主处理逻辑 ==========

def process_file(file_path: str, doc_type: str) -> Tuple[str, str]:
    """主处理函数 - 优化版"""
    if not file_path or not os.path.exists(file_path):
        return json.dumps({"error": "文件不存在"}, ensure_ascii=False), "unknown"

    ext = Path(file_path).suffix.lower()
    
    # 实例化解析器
    excel_parser = ExcelExtractor()
    word_parser = WordExtractor()
    pdf_parser = PDFProcessor()

    try:
        print(f"📄 开始处理文件: {Path(file_path).name}")
        print(f"📋 文件类型: {ext}, 单据类型: {doc_type}")
        
        if ext in ['.pdf', '.png', '.jpg', '.jpeg']:
            # 视觉模型处理
            print("🖼️  处理图像文件...")
            img_b64 = get_document_image_base64(file_path)
            raw_json = call_vlm_service(SYSTEM_PROMPT, USER_PROMPT, img_b64)
            print(f"✅ VLM返回结果:\n{raw_json[:500]}...")
            final_res = transform_to_api_format(raw_json)
            
        elif ext in ['.xlsx', '.xls']:
            # Excel 处理
            print("📊 处理Excel文件...")
            img_b64 = excel_parser.extract(file_path)
            
            if doc_type == "贸易委托书":
                raw_json = call_vlm_service(SYSTEM_PROMPT, USER_PROMPT, img_b64)
                print(f"✅ VLM返回结果:\n{raw_json[:500]}...")
                final_res = transform_to_api_format(raw_json)
            else:
                final_res = json.dumps({"error": "暂不支持 Excel 账单处理"}, ensure_ascii=False)
                
        elif ext in ['.docx', '.doc']:
            # Word 处理
            print("📝 处理Word文件...")
            img_b64 = word_parser.extract(file_path)
            
            if doc_type == "贸易委托书":
                raw_json = call_vlm_service(SYSTEM_PROMPT, USER_PROMPT, img_b64)
                print(f"✅ VLM返回结果:\n{raw_json[:500]}...")
                final_res = transform_to_api_format(raw_json)
            else:
                final_res = json.dumps({"error": "暂不支持 Word 账单处理"}, ensure_ascii=False)
                
        else:
            final_res = json.dumps({"error": f"暂不支持 {ext} 格式文件"}, ensure_ascii=False)
        
        # 结果持久化
        output_dir = "/home/yangqi/workspace/DocumentExtractor/output/gradio"
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"res_{Path(file_path).stem}.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(final_res)
        
        print(f"💾 结果已保存到: {output_file}")
        return final_res, ext
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ 处理失败: {e}\n{error_detail}")
        return json.dumps({
            "error": str(e),
            "detail": error_detail
        }, ensure_ascii=False), "error"

# ========== 9. Gradio UI ==========

def create_ui():
    with gr.Blocks(title="智能单据识别系统", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 📄 多模态单据智能识别系统 v2.0")
        gr.Markdown("支持PDF、图片、Excel、Word等多种格式的物流单据识别")
        
        with gr.Row():
            with gr.Column(scale=1):
                f_in = gr.File(
                    label="📎 上传单据文件",
                    file_types=['.pdf', '.png', '.jpg', '.jpeg', '.xlsx', '.xls', '.doc', '.docx']
                )
                d_type = gr.Radio(
                    choices=["贸易委托书", "账单单据"],
                    value="贸易委托书",
                    label="📋 单据类型"
                )
                btn = gr.Button("🚀 开始识别", variant="primary", size="lg")
                
                gr.Markdown("### ℹ️ 支持的文件格式")
                gr.Markdown("""
                - ✅ PDF 文件 (.pdf)
                - ✅ 图片文件 (.png, .jpg, .jpeg)
                - ✅ Word 文档 (.docx, .doc)
                - ✅ Excel 表格 (.xlsx, .xls)
                """)
                
                gr.Markdown("### 🎯 识别能力")
                gr.Markdown("""
                - 自动识别运输方式（海运/空运/铁路）
                - 提取发货人、收货人、通知人信息
                - 识别港口、航班号、船名等
                - 提取货物明细（重量、体积、件数）
                - 智能判断货物类型（普货/危险品等）
                - 识别集装箱规格和数量
                """)
                
            with gr.Column(scale=2):
                res_json = gr.Code(
                    label="🎯 提取结果 (JSON格式)",
                    language="json",
                    lines=30
                )
                
                gr.Markdown("### 💡 使用提示")
                gr.Markdown("""
                1. 上传单据文件（支持多页PDF）
                2. 选择单据类型
                3. 点击"开始识别"按钮
                4. 等待识别完成（通常10-30秒）
                5. 查看提取结果，可复制JSON用于API调用
                
                **注意事项：**
                - 确保文档清晰，字迹可辨
                - Excel/Word文件会自动转换为图像处理
                - 多页文档会自动拼接处理
                - 识别结果会自动保存到 output/gradio 目录
                """)
        
        btn.click(
            fn=process_file,
            inputs=[f_in, d_type],
            outputs=[res_json, gr.Textbox(visible=False)]
        )
    
    return demo

# ========== 10. 主入口 ==========

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 启动智能单据识别系统...")
    print("=" * 60)
    print(f"📁 临时目录: {LOCAL_TMP}")
    print(f"🌐 vLLM服务: {VLLM_API_URL}")
    print(f"🤖 模型名称: {VLLM_MODEL_NAME}")
    print(f"🗺️  港口映射: {EXCEL_PATH}")
    print("=" * 60)
    
    demo = create_ui()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        allowed_paths=["/home/yangqi/workspace/DocumentExtractor/", LOCAL_TMP]
    )
