#!/usr/bin/env python3
"""港口代码映射器 - 根据港口名称获取对应代码"""
import re
import os
from difflib import SequenceMatcher

import pandas as pd


class PortMapper:
    """港口代码映射类 - 单例模式"""

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
        """初始化港口映射表"""
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


# 创建全局单例实例
port_mapper = PortMapper()
