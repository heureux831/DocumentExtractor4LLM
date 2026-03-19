#!/usr/bin/env python3
"""视觉服务模块 - 图像处理和 VLLM 调用"""
import base64
import io
import re
from pathlib import Path
from typing import Optional

from openai import OpenAI
from pdf2image import convert_from_path
from PIL import Image
from io import BytesIO

from extractors.config import (
    VLLM_API_URL,
    VLLM_MODEL_NAME,
    VLLM_API_KEY,
    VLLM_TIMEOUT,
    VLLM_MAX_TOKENS,
    VLLM_TEMPERATURE,
    VLLM_TOP_P,
    IMAGE_DPI,
    IMAGE_MAX_SIZE,
    IMAGE_COMPRESS_MAX_SIZE,
    IMAGE_JPEG_QUALITY,
    IMAGE_COMPRESS_JPEG_QUALITY,
)


class VisionService:
    """视觉服务类 - 处理图像和调用 VLLM"""

    def __init__(self, api_url: str = None, model_name: str = None):
        """
        初始化视觉服务

        Args:
            api_url: VLLM API 地址
            model_name: 模型名称
        """
        self.api_url = api_url or VLLM_API_URL
        self.model_name = model_name or VLLM_MODEL_NAME

    def get_document_image_base64(self, file_path: str) -> str:
        """PDF/图片转base64编码 - 优化版，支持多页拼接"""
        file_ext = Path(file_path).suffix.lower()

        try:
            if file_ext == '.pdf':
                # 转换所有页面，提高DPI确保小字清晰
                images = convert_from_path(file_path, dpi=IMAGE_DPI)

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
            if img.width > IMAGE_MAX_SIZE or img.height > IMAGE_MAX_SIZE:
                ratio = min(IMAGE_MAX_SIZE / img.width, IMAGE_MAX_SIZE / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            buffered = BytesIO()
            img.save(buffered, format="JPEG", quality=IMAGE_JPEG_QUALITY)
            return base64.b64encode(buffered.getvalue()).decode('utf-8')
        except Exception as e:
            print(f"❌ 图像处理失败: {e}")
            raise

    def compress_image_b64(self, image_b64: str) -> str:
        """压缩base64图片"""
        img_data = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(img_data))

        w, h = img.size
        if max(w, h) > IMAGE_COMPRESS_MAX_SIZE:
            img.thumbnail((IMAGE_COMPRESS_MAX_SIZE, IMAGE_COMPRESS_MAX_SIZE))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=IMAGE_COMPRESS_JPEG_QUALITY)
        return base64.b64encode(buf.getvalue()).decode()

    def call_vlm_service(self, system_prompt: str, user_prompt: str, image_b64: str = None, text_content: str = None) -> str:
        """调用 VLLM 多模态接口 - 优化版，添加错误处理

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            image_b64: 图片base64编码（可选）
            text_content: 文本内容（当image_b64为None时，会附加到user_prompt中）
        """
        try:
            client = OpenAI(
                api_key=VLLM_API_KEY,
                base_url=self.api_url,
                timeout=VLLM_TIMEOUT
            )

            # 当没有图片时，将文本内容附加到user_prompt中
            if image_b64 is None and text_content:
                full_user_prompt = f"{user_prompt}\n\n文档内容：\n{text_content}"
            else:
                full_user_prompt = user_prompt

            content = [{"type": "text", "text": full_user_prompt}]
            if image_b64 is not None:
                image_b64 = self.compress_image_b64(image_b64)
                content.insert(0, {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                })

            response = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                max_tokens=VLLM_MAX_TOKENS,
                temperature=VLLM_TEMPERATURE,
                top_p=VLLM_TOP_P,
            )

            res = response.choices[0].message.content.strip()
            # 清理可能的 markdown 代码块标记
            res = re.sub(r'```json\s*|\s*```', '', res, flags=re.DOTALL)
            return res
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"❌ VLM推理失败: {e}\n{error_detail}")
            return '{"error": "推理失败: ' + str(e) + '"}'


# 创建默认实例
vision_service = VisionService()
