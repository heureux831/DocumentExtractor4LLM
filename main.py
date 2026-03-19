#!/usr/bin/env python3
"""Gradio UI 主入口 - 多模态单据智能识别系统"""
import os
import sys
from pathlib import Path

# 强制不走代理，确保本地服务访问
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

import gradio as gr

# 获取项目根目录（当前文件所在目录）
project_root = str(Path(__file__).resolve().parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# 导入模块
from extractors import (
    port_mapper,
    DocumentProcessor,
)

# ========== 1. 基础配置与路径 ==========
OS_TEMP_DIR = os.path.join(project_root, "tmp")
LOCAL_TMP = OS_TEMP_DIR
os.makedirs(LOCAL_TMP, exist_ok=True)

os.environ["TMPDIR"] = LOCAL_TMP
os.environ["GRADIO_TEMP_DIR"] = os.path.join(LOCAL_TMP, "gradio_cache")
os.system(f"chmod -R 777 {LOCAL_TMP}")

VLLM_API_URL = "http://documentextractor.cpolar.top/v1"
VLLM_MODEL_NAME = "Qwen3-VL-4B-Instruct"
EXCEL_PATH = os.path.join(project_root, "data", "port_map.xlsx")

os.makedirs(OS_TEMP_DIR, exist_ok=True)

# 初始化港口映射器
port_mapper.initialize(EXCEL_PATH)

# 创建文档处理器
document_processor = DocumentProcessor(port_mapper, project_root)


def process_file(file_path: str, doc_type: str):
    """处理文件的包装函数"""
    raw_json, final_res, ext = document_processor.process_file(file_path, doc_type)
    return raw_json, final_res


# ========== 2. Gradio UI ==========

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
                result_type = gr.Radio(
                    choices=["转换结果", "原始结果"],
                    value="转换结果",
                    label="📊 结果类型"
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
                raw_json_out = gr.Code(
                    label="🔍 VLM原始结果",
                    language="json",
                    lines=30,
                    visible=False
                )

                gr.Markdown("### 💡 使用提示")
                gr.Markdown("""
                1. 上传单据文件（支持多页PDF）
                2. 选择单据类型
                3. 选择结果类型（转换结果/原始结果）
                4. 点击"开始识别"按钮
                5. 等待识别完成（通常10-30秒）
                6. 查看提取结果，可复制JSON用于API调用

                **注意事项：**
                - 确保文档清晰，字迹可辨
                - Excel/Word文件会自动转换为图像处理
                - 多页文档会自动拼接处理
                - 识别结果会自动保存到 output/gradio 目录
                """)

        def show_result(result_type, raw_json, final_res):
            """根据选择显示不同结果"""
            if result_type == "原始结果":
                return gr.update(visible=True), gr.update(visible=False), raw_json
            else:
                return gr.update(visible=False), gr.update(visible=True), final_res

        btn.click(
            fn=process_file,
            inputs=[f_in, d_type],
            outputs=[raw_json_out, res_json]
        )

        result_type.change(
            fn=show_result,
            inputs=[result_type, raw_json_out, res_json],
            outputs=[raw_json_out, res_json, res_json]
        )

    return demo


# ========== 3. 主入口 ==========

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
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        allowed_paths=[project_root, LOCAL_TMP]
    )
