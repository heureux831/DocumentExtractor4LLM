#!/usr/bin/env python3
"""工具函数模块 - 数字解析、布尔值处理等辅助函数"""
import re


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
            match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", clean_value)
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
