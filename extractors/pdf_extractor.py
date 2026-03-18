import os
import time
from pathlib import Path
from pdf2image import convert_from_path

class PDFProcessor:
    """处理 PDF 和图片，利用 OCR 引擎提取带坐标的结构化文本"""

    def __init__(self):
        self.supported_formats = {'.png', '.pdf'}

    def process(self, file_path: str, ocr_pipeline,temp_dir) -> str:
        """
        核心处理方法
        :param file_path: 文件路径 (pdf, png, jpg)
        :param ocr_pipeline: 传入的 PaddleX OCR 引擎实例
        :return: 格式化后的字符串 (序号 | OCR结果 | bbox)
        """
        path_obj = Path(file_path)
        ext = path_obj.suffix.lower()
        
        # 1. 统一转换为图片路径
        process_path = file_path
        if ext == '.pdf':
            # 将 PDF 第一页转为临时图片
            imgs = convert_from_path(file_path, dpi=200)
            process_path = os.path.join(temp_dir, f"ocr_tmp_{int(time.time())}.png")
            imgs[0].save(process_path, "PNG")

        # 2. 调用 OCR 引擎推理
        # 注意：这里假设传入的是 PaddleX 的 pipeline
        output = ocr_pipeline.predict(input=process_path)

        # 3. 转换为 “序号 | OCR结果 | bbox” 格式
        formatted_result = self._format_ocr_output(output)
        
        return formatted_result

    import numpy as np

    def _format_ocr_output(self, ocr_output) -> str:
        """
        修改版内部私有方法：
        1. 实现坐标归一化 [0, 1000]
        2. 实现逻辑行排序 (Bucket Sort)，优化 8B 模型阅读顺序
        """
        raw_results = []
        
        # --- 1. 数据解析与初步提取 ---
        for res in ocr_output:
            # 获取图像尺寸用于归一化
            # PaddleX 输出通常包含输入图像或其 shape
            # 假设 res 中可以直接获取宽高，或者从第一个 poly 的尺度估算
            img_h, img_w = 1, 1 # 默认值
            if hasattr(res, 'input_path'): # 尝试通过某种方式获取图宽，这里通常在 pipeline 输出的 metadata 中
                # 如果 res 对象里没有，建议在调用此方法前传入 w, h
                # 暂时尝试从 dt_polys 的最大值推断（若无元数据时的兜底方案）
                pass 

            if 'dt_polys' in res and 'rec_texts' in res:
                for poly, text in zip(res['dt_polys'], res['rec_texts']):
                    clean_text = text.replace('\n', ' ').strip()
                    points = poly.tolist() if hasattr(poly, 'tolist') else poly
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    
                    # 记录绝对坐标
                    abs_bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
                    raw_results.append({
                        "text": clean_text,
                        "bbox": abs_bbox
                    })

        if not raw_results:
            return "未识别到文字内容"

        # --- 2. 逻辑行排序 (Bucket Sort with Tolerance) ---
        # 按照 ymin 排序
        raw_results.sort(key=lambda x: x['bbox'][1])
        
        sorted_rows = []
        if raw_results:
            # 计算行合并阈值：通常设为平均高度的一半
            avg_height = sum([(r['bbox'][3] - r['bbox'][1]) for r in raw_results]) / len(raw_results)
            tolerance = avg_height * 0.5 

            current_row = [raw_results[0]]
            for i in range(1, len(raw_results)):
                # 如果当前项与上一项的 ymin 差距在容差内，视为同一行
                if abs(raw_results[i]['bbox'][1] - current_row[-1]['bbox'][1]) <= tolerance:
                    current_row.append(raw_results[i])
                else:
                    # 桶内按 xmin 排序
                    sorted_rows.append(sorted(current_row, key=lambda x: x['bbox'][0]))
                    current_row = [raw_results[i]]
            sorted_rows.append(sorted(current_row, key=lambda x: x['bbox'][0]))

        # --- 3. 坐标归一化 (Normalization to 0-1000) ---
        # 获取整个页面的最大跨度作为归一化基准
        max_x = max([r['bbox'][2] for r in raw_results])
        max_y = max([r['bbox'][3] for r in raw_results])

        lines = []
        # 更新表头：显示归一化后的坐标 [nx1, ny1, nx2, ny2]
        header = f"{'序号':<6} | {'OCR结果':<40} | {'Normalized bbox [0-1000]'}"
        lines.append(header)
        lines.append("-" * 100)

        counter = 1
        for row in sorted_rows:
            for item in row:
                b = item['bbox']
                # 归一化计算
                norm_bbox = [
                    int(b[0] * 1000 / max_x),
                    int(b[1] * 1000 / max_y),
                    int(b[2] * 1000 / max_x),
                    int(b[3] * 1000 / max_y)
                ]
                
                line = f"{counter:<8} | {item['text']:<42} | {norm_bbox}"
                lines.append(line)
                counter += 1
                
        return "\n".join(lines)