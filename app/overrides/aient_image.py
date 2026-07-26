"""Configurable text-to-image generation.

The upstream plugin hardcodes an ``API`` environment variable and a DALL·E
style endpoint derived from ``BASE_URL``. That breaks whenever the chat gateway
and the image gateway differ. This override lets the image service be pointed
anywhere, falls back to the chat credentials, and supports both ``url`` and
``b64_json`` responses.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import requests

from .registry import register_tool

_ALLOWED_SIZES = {"256x256", "512x512", "1024x1024", "1024x1792", "1792x1024"}


def _timeout() -> int:
    try:
        return max(10, min(300, int(os.environ.get("IMAGE_TIMEOUT", 120))))
    except (TypeError, ValueError):
        return 120


def _endpoint() -> str:
    explicit = os.environ.get("IMAGE_BASE_URL", "").strip()
    if explicit:
        return explicit if "/images/" in explicit else explicit.rstrip("/") + "/images/generations"
    base = (os.environ.get("BASE_URL", "") or "").strip()
    if not base:
        return "https://api.openai.com/v1/images/generations"
    for suffix in ("/chat/completions", "/responses"):
        if base.endswith(suffix):
            return base[: -len(suffix)] + "/images/generations"
    return base.rstrip("/") + "/images/generations"


def _credentials() -> str:
    for name in ("IMAGE_API_KEY", "API", "API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _extract(payload: dict[str, Any]) -> str:
    entries = payload.get("data") or []
    if not entries:
        return ""
    entry = entries[0] if isinstance(entries[0], dict) else {}
    url = str(entry.get("url") or "").strip()
    if url:
        return url
    encoded = str(entry.get("b64_json") or "").strip()
    if not encoded:
        return ""
    try:
        base64.b64decode(encoded, validate=True)
    except Exception:
        return ""
    return "data:image/png;base64," + encoded


@register_tool()
def generate_image(text: str, size: str = "1024x1024") -> str:
    """根据文本描述生成一张图像。

    参数:
        text: 描述画面内容的提示词，越具体越好。
        size: 图像尺寸，可选 256x256、512x512、1024x1024、1024x1792、1792x1024。

    返回:
        图像 URL，或 data:image/png;base64 内联图像。
    """
    prompt = str(text or "").strip()
    if not prompt:
        return "<tool_error>请提供图像描述。</tool_error>"
    key = _credentials()
    if not key:
        return "<tool_error>图像服务尚未配置密钥，请先设置 IMAGE_API_KEY。</tool_error>"
    dimensions = str(size or "").strip() or "1024x1024"
    if dimensions not in _ALLOWED_SIZES:
        dimensions = "1024x1024"

    payload = {
        "model": os.environ.get("IMAGE_MODEL_NAME", "").strip() or "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": dimensions,
    }
    try:
        response = requests.post(
            _endpoint(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=_timeout(),
        )
    except Exception as exc:
        return f"<tool_error>图像服务连接失败：{type(exc).__name__}</tool_error>"

    if response.status_code != 200:
        return f"<tool_error>图像服务返回 {response.status_code}，请检查 IMAGE_BASE_URL 与 IMAGE_MODEL_NAME。</tool_error>"
    try:
        image = _extract(response.json())
    except ValueError:
        return "<tool_error>图像服务返回了无法解析的内容。</tool_error>"
    if not image:
        return "<tool_error>图像服务没有返回可用的图像。</tool_error>"
    return image
