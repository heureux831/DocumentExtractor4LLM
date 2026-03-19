#!/usr/bin/env python3
"""批量文档处理脚本 - 命令行批量处理文档"""
import os
import sys
import argparse
import json
from pathlib import Path
from typing import List, Tuple

# 强制不走代理
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

# 获取项目根目录
project_root = str(Path(__file__).resolve().parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from extractors import (
    port_mapper,
    DocumentProcessor,
    OUTPUT_GRADIO_DIR,
    ensure_output_dirs,
)


# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.xlsx', '.xls', '.docx', '.doc'}


def get_files_to_process(path: str) -> List[str]:
    """获取要处理的文件列表"""
    path_obj = Path(path)

    if path_obj.is_file():
        return [str(path_obj)]
    elif path_obj.is_dir():
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend([str(f) for f in path_obj.rglob(f"*{ext}")])
            files.extend([str(f) for f in path_obj.rglob(f"*{ext.upper()}")])
        return sorted(set(files))
    else:
        return []


def process_single_file(processor: DocumentProcessor, file_path: str, doc_type: str, use_xml_mode: bool, write_debug: bool) -> Tuple[bool, str, str]:
    """处理单个文件"""
    try:
        print(f"\n{'='*60}")
        print(f"📄 处理文件: {file_path}")
        print(f"{'='*60}")

        raw_json, result, ext = processor.process_file(file_path, doc_type, use_xml_mode=use_xml_mode, write_debug=write_debug)

        # 解析结果
        try:
            result_obj = json.loads(result)
            if "error" in result_obj:
                print(f"❌ 处理失败: {result_obj.get('error', '未知错误')}")
                return False, file_path, result_obj.get('error', '未知错误')
        except:
            pass

        print(f"✅ 处理成功")
        return True, file_path, "成功"
    except Exception as e:
        print(f"❌ 处理异常: {e}")
        return False, file_path, str(e)


def main():
    parser = argparse.ArgumentParser(
        description="批量文档处理脚本 - 支持单文件和目录批量处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 处理单个文件
  python batch_process.py /path/to/document.pdf --doc-type 贸易委托书

  # 处理整个目录
  python batch_process.py /path/to/documents/

  # 使用XML模式处理Excel/Word
  python batch_process.py /path/to/document.xlsx --xml-mode

  # 不生成调试文件
  python batch_process.py /path/to/document.xlsx --no-debug

  # 完整示例
  python batch_process.py /path/to/documents/ --doc-type 贸易委托书 --xml-mode
"""
    )

    parser.add_argument(
        "path",
        help="文件路径或目录路径"
    )

    parser.add_argument(
        "--doc-type", "-t",
        default="贸易委托书",
        choices=["贸易委托书", "账单单据"],
        help="单据类型 (默认: 贸易委托书)"
    )

    parser.add_argument(
        "--xml-mode", "-x",
        action="store_true",
        help="使用XML模式处理Excel/Word文件"
    )

    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="不生成调试文件"
    )

    parser.add_argument(
        "--output", "-o",
        help="结果输出目录 (默认: output/gradio)"
    )

    args = parser.parse_args()

    # 初始化
    print("=" * 60)
    print("📄 批量文档处理脚本")
    print("=" * 60)
    print(f"📁 项目目录: {project_root}")
    print(f"📋 单据类型: {args.doc_type}")
    print(f"🔧 XML模式: {'开启' if args.xml_mode else '关闭'}")
    print(f"🐛 调试模式: {'开启' if not args.no_debug else '关闭'}")
    print("=" * 60)

    # 初始化港口映射
    excel_path = os.path.join(project_root, "港口代码映射表.xlsx")
    if os.path.exists(excel_path):
        port_mapper.initialize(excel_path)
    else:
        print(f"⚠️  警告: 港口映射表不存在 ({excel_path})")

    # 确保输出目录存在
    ensure_output_dirs()

    # 创建处理器
    processor = DocumentProcessor(port_mapper, project_root)

    # 获取文件列表
    files = get_files_to_process(args.path)

    if not files:
        print(f"❌ 未找到支持的文件: {args.path}")
        return 1

    print(f"\n📋 共找到 {len(files)} 个文件待处理\n")

    # 统计结果
    success_count = 0
    fail_count = 0
    results = []

    # 逐个处理文件
    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}]", end="")
        success, path, msg = process_single_file(
            processor, file_path, args.doc_type,
            use_xml_mode=args.xml_mode,
            write_debug=not args.no_debug
        )
        results.append({"file": path, "success": success, "message": msg})
        if success:
            success_count += 1
        else:
            fail_count += 1

    # 输出统计
    print("\n" + "=" * 60)
    print("📊 处理完成统计")
    print("=" * 60)
    print(f"✅ 成功: {success_count}")
    print(f"❌ 失败: {fail_count}")
    print(f"📁 总计: {len(files)}")
    print(f"📂 输出目录: {OUTPUT_GRADIO_DIR}")
    print("=" * 60)

    # 保存处理结果到JSON文件
    if args.output:
        output_dir = args.output
    else:
        output_dir = OUTPUT_GRADIO_DIR

    os.makedirs(output_dir, exist_ok=True)
    result_file = os.path.join(output_dir, "batch_results.json")
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump({
            "summary": {
                "total": len(files),
                "success": success_count,
                "fail": fail_count
            },
            "results": results
        }, f, ensure_ascii=False, indent=2)
    print(f"📝 处理结果已保存: {result_file}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
