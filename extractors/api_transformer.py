#!/usr/bin/env python3
"""API 格式转换模块 - 将 LLM 输出转换为系统 API 格式"""
import json

from extractors.utils import safe_parse_number, safe_calculate_hwmd


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
TRANSPORT_MAPPINGS = [
    {"code": "YSFS_HY", "keywords": ["海运", "sea", "ocean", "船运", "maritime", "shipping", "vessel", "b/l", "bill of lading", "sea freight"]},
    {"code": "YSFS_TL", "keywords": ["铁路", "rail", "train", "railway", "rail transport", "rail freight"]},
    {"code": "YSFS_KY", "keywords": ["空运", "air", "航空", "air freight", "air transport", "air cargo", "awb", "airway bill", "flight", "by air"]}
]

SHIPMENT_MAPPINGS = [
    {"code": "YSBZ_PX", "keywords": ["拼箱", "lcl", "less than container", "拼柜", "consolidation", "consol", "less container load"]},
    {"code": "YSBZ_ZX", "keywords": ["整箱", "fcl", "full container", "整柜", "full container load"]},
    {"code": "YSBZ_SZH", "keywords": ["break bulk", "散杂货", "散货", "bulk", "bulk cargo", "break-bulk"]}
]

AIR_SERVICE_MAPPINGS = [
    {"code": "GDFWLX_2", "keywords": ["door to airport", "门到机场", "d2a", "door-airport"]},
    {"code": "GDFWLX_3", "keywords": ["airport to door", "机场到门", "a2d", "airport-door"]},
    {"code": "GDFWLX_4", "keywords": ["airport to airport", "机场到机场", "a2a", "airport-airport", "port to port"]}
]

SEA_SERVICE_MAPPINGS = [
    {"code": "GDFWLX_1", "keywords": ["door to door", "门到门", "d2d", "door-door"]},
    {"code": "GDFWLX_6", "keywords": ["door to cfs", "门到cfs", "d2cfs", "door-cfs"]},
    {"code": "GDFWLX_7", "keywords": ["cfs to door", "cfs到门", "cfs2d", "cfs-door"]},
    {"code": "GDFWLX_8", "keywords": ["cfs to cfs", "cfs到cfs", "cfs2cfs", "cfs-cfs"]},
    {"code": "GDFWLX_9", "keywords": ["door to cy", "门到cy", "d2cy", "door-cy"]},
    {"code": "GDFWLX_10", "keywords": ["cy to door", "cy到门", "cy2d", "cy-door"]},
    {"code": "GDFWLX_11", "keywords": ["cy to cy", "cy到cy", "cy2cy", "cy-cy", "port to port", "pier to pier"]}
]

PAYMENT_MAPPINGS = [
    {"code": "YFTK_1", "keywords": ["prepaid", "预付", "pp", "pre pay", "prepaid freight", "freight prepaid", "pre-paid"]},
    {"code": "YFTK_2", "keywords": ["collected", "到付", "collect", "cc", "freight collect", "freight collected"]}
]

CARGO_TYPE_MAPPINGS = [
    {"code": "HWLX_WXP", "keywords": ["dangerous", "hazardous", "dg", "dangerous goods", "hazardous material", "危险品", "危", "un", "imdg", "class"]},
    {"code": "HWLX_WKHW", "keywords": ["temperature control", "温控", "temperature controlled", "reefer", "冷藏", "冷冻", "refrigerated", "frozen"]},
    {"code": "HWLX_XHYF", "keywords": ["perishable", "fresh", "易腐", "perishable goods", "鲜活"]},
    {"code": "HWLX_GZWP", "keywords": ["valuable", "precious", "valuable goods", "高价值", "贵重"]},
    {"code": "HWLX_PH", "keywords": ["general cargo", "普货", "普通货物", "general", "regular cargo", "dry cargo"]}
]

PACKAGE_MAPPINGS = [
    {"code": "BZLX_ZX", "keywords": ["纸箱", "carton", "cartons", "纸盒", "cardboard box", "ctn", "ctns"]},
    {"code": "BZLX_TP", "keywords": ["托盘", "pallet", "pallets", "托", "wooden pallet", "plt", "plts", "skid"]},
    {"code": "BZLX_MX", "keywords": ["木箱", "wooden case", "木盒", "wooden box", "wooden crate", "case", "cases"]},
    {"code": "BZLX_BTX", "keywords": ["板条箱", "crate", "crates"]},
    {"code": "BZLX_B", "keywords": ["包", "bag", "bags", "sack", "sacks"]},
    {"code": "BZLX_TT", "keywords": ["铁桶", "iron drum", "steel drum", "metal drum", "drum", "drums"]},
    {"code": "BZLX_J", "keywords": ["件", "package", "packages", "piece", "pc", "pcs", "pieces", "pkg", "pkgs"]}
]

CONTAINER_MAPPINGS = [
    {"code": "JZXGG_1", "keywords": ["20gp", "20'gp", "20dc", "20'dc", "20'", "20尺", "20' dry", "20ft", "20 gp", "20 dc"]},
    {"code": "JZXGG_2", "keywords": ["40gp", "40'gp", "40dc", "40'dc", "40'", "40尺", "40' dry", "40ft", "40 gp", "40 dc"]},
    {"code": "JZXGG_3", "keywords": ["40hq", "40'hq", "40hc", "40'hc", "40'high", "40尺高柜", "40' high cube", "40 hq", "40 hc"]},
    {"code": "JZXGG_26", "keywords": ["45hc", "45'hc", "45'", "45尺", "45' high cube", "45 hc"]},
    {"code": "JZXGG_19", "keywords": ["reefer", "冷箱", "冷柜", "refrigerated", "rf"]},
    {"code": "JZXGG_8", "keywords": ["20ot", "20' open top", "20'open", "20尺开顶", "20 ot", "20 open"]},
    {"code": "JZXGG_18", "keywords": ["40ot", "40' open top", "40'open", "40尺开顶", "40 ot", "40 open"]}
]

PAYMENT_METHOD_MAPPINGS = [
    {"code": "JSYQ_XJ", "keywords": ["现结", "现金", "现金结算", "现付", "cash", "cash settlement", "cash payment"]},
    {"code": "JSYQ_YJ", "keywords": ["月结", "月度结算", "月付", "monthly", "monthly settlement", "monthly payment"]}
]

INCOTERM_MAPPINGS = [
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


class APITransformer:
    """API 格式转换器"""

    def __init__(self, port_mapper):
        """
        初始化转换器

        Args:
            port_mapper: 港口代码映射器实例
        """
        self.port_mapper = port_mapper

    def transform(self, llm_json_str: str) -> str:
        """
        处理VLM模型返回的JSON，转换为系统API需要的格式

        Args:
            llm_json_str: LLM 返回的 JSON 字符串

        Returns:
            API 格式的 JSON 字符串
        """
        try:
            data = json.loads(llm_json_str)
            basic = data.get("basic_info", {})
            locs = data.get("locations", {})
            parties = data.get("parties", {})
            totals = data.get("cargo_totals", {})
            cargo_items = data.get("cargo_items", [])
            container_list = data.get("container_list", [])

            # ========== 运输方式识别 ==========
            transport_raw = basic.get("transport_mode_raw", "")
            ysfs_code = fuzzy_map_safe(transport_raw, TRANSPORT_MAPPINGS, "")

            # ========== 装运类型识别 ==========
            shipment_raw = basic.get("shipment_type_raw", "")
            
            cplb_code = fuzzy_map_safe(shipment_raw, SHIPMENT_MAPPINGS, "")
            ysbz_code = cplb_code

            # ========== 服务类型识别 ==========
            freight_term_raw = basic.get("freight_term_raw", "")
            fwlx_code = ""

            if ysfs_code == "YSFS_KY":
                fwlx_code = fuzzy_map_safe(freight_term_raw, AIR_SERVICE_MAPPINGS, "")
            else:
                fwlx_code = fuzzy_map_safe(freight_term_raw, SEA_SERVICE_MAPPINGS, "")
                if not fwlx_code and cplb_code:
                    if cplb_code == "YSBZ_ZX":
                        fwlx_code = "GDFWLX_11"
                    elif cplb_code == "YSBZ_PX":
                        fwlx_code = "GDFWLX_8"

            # ========== 预付/到付条款 ==========
            yftk_code = fuzzy_map_safe(freight_term_raw, PAYMENT_MAPPINGS, "")

            # ========== 运费条款 (Incoterm) ==========
            incoterm_raw = basic.get("incoterm_raw", "")
            if not incoterm_raw:
                incoterm_raw = freight_term_raw
            gdtk_code = fuzzy_map_safe(incoterm_raw, INCOTERM_MAPPINGS, "")

            # ========== 计费方式 ==========
            payment_method_raw = basic.get("payment_method_raw", "")
            jsyq_code = fuzzy_map_safe(payment_method_raw, PAYMENT_METHOD_MAPPINGS, "")

            # ========== 港口代码转换 ==========
            raw_sfg = locs.get("port_of_loading", "")
            raw_mdg = locs.get("port_of_discharge", "")

            sfg_code = self.port_mapper.get_code(raw_sfg, default_val=raw_sfg, transport_mode=ysfs_code)
            mdg_code = self.port_mapper.get_code(raw_mdg, default_val=raw_mdg, transport_mode=ysfs_code)

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
                container_type = fuzzy_map_safe(container_type_raw, CONTAINER_MAPPINGS, "")

            # ========== 货物列表处理 ==========
            hw_list = []
            marks = ""
            description = ""

            for item in cargo_items:
                package_unit = item.get("package_unit_raw", "")
                bzlx_code = fuzzy_map_safe(package_unit, PACKAGE_MAPPINGS, "")

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
                    jzxgg = fuzzy_map_safe(container_type_raw, CONTAINER_MAPPINGS, "")
                    if jzxgg:
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

            if total_quantity == 0 and hw_list:
                total_quantity = sum(item["hhjs"] for item in hw_list)
            if total_weight == 0 and hw_list:
                total_weight = sum(item["zl"] for item in hw_list)
            if total_volume == 0 and hw_list:
                total_volume = sum(item["tj"] for item in hw_list)

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
            hwlx_code = "HWLX_PH"

            all_descriptions = " ".join([item.get("description", "") for item in cargo_items]).lower()

            for mapping in CARGO_TYPE_MAPPINGS:
                if mapping["code"] == "HWLX_WXP":
                    for keyword in mapping["keywords"]:
                        if keyword.lower() in all_descriptions:
                            hwlx_code = mapping["code"]
                            break
                    if hwlx_code == "HWLX_WXP":
                        break

            if hwlx_code == "HWLX_PH":
                for mapping in CARGO_TYPE_MAPPINGS:
                    if mapping["code"] != "HWLX_PH":
                        for keyword in mapping["keywords"]:
                            if keyword.lower() in all_descriptions:
                                hwlx_code = mapping["code"]
                                break
                    if hwlx_code != "HWLX_PH":
                        break

            # ========== 构造最终API数据 ==========
            api_data = {
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

                "hwList": hw_list,

                "hwhjjs": total_quantity,
                "hwhjzl": total_weight,
                "hwtj": total_volume,
                "hwhjfzl": "",
                "hwmd": hwmd,
                "jzxsl": len(hyxxList),
                "jfd": "0",
                "hwjfzl": "0.00",

                "sxed": "",
                "sysxed": "",
                "jsyq": jsyq_code,

                "fhrjtxx": parties.get("shipper_full_information", ""),
                "shrjtxx": consignee_info,
                "tzfjtxx": notify_info,
                "xsmc": parties.get("sales_contact", ""),

                "tenantid": "",
                "kh": "",
                "khz": "",
                "fhr": "",
                "csshr": "",

                "hwlx": hwlx_code,
                "minwd": "",
                "maxwd": "",
                "hwwxplb": "",
                "ysbz": ysbz_code,
                "gdbq": "",
                "hwms": description,
                "hwmt": marks,
                "hwbq": "",

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

                "jzxgg": container_type,
                "jzxjsbygg": "1",
                "hyxxList": hyxxList,

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


# 便捷函数
def transform_to_api_format(llm_json_str: str, port_mapper) -> str:
    """处理VLM模型返回的JSON，转换为系统API需要的格式"""
    transformer = APITransformer(port_mapper)
    return transformer.transform(llm_json_str)
