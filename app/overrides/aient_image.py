"""Configurable text-to-image generation.

The upstream plugin hardcodes an ``API`` environment variable and a DALL·E
style endpoint derived from ``BASE_URL``. That breaks whenever the chat gateway
and the image gateway differ. This override lets the image service be pointed
anywhere, falls back to the chat credentials, and supports both ``url`` and
``b64_json`` responses.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any

import requests

from .registry import register_tool

_LOGGER = logging.getLogger("yoishizuku.image")

_ALLOWED_SIZES = {"256x256", "512x512", "1024x1024", "1024x1792", "1792x1024"}


def _timeout() -> int:
    try:
        return max(10, min(600, int(os.environ.get("IMAGE_TIMEOUT", 180))))
    except (TypeError, ValueError):
        return 180


def _endpoint() -> str:
    """Resolve the image endpoint from either a full URL or a gateway base.

    Accepts values such as ``https://host/v1``, ``https://host/v1/responses``
    and ``https://host/v1/chat/completions``; all of them resolve to the
    gateway's ``/images/generations`` path so a mistyped suffix does not
    produce ``/v1/responses/images/generations``.
    """
    explicit = os.environ.get("IMAGE_BASE_URL", "").strip()
    base = explicit or (os.environ.get("BASE_URL", "") or "").strip()
    if not base:
        return "https://api.openai.com/v1/images/generations"
    base = base.rstrip("/")
    if base.endswith("/images/generations"):
        return base
    for suffix in ("/chat/completions", "/responses", "/completions", "/images"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base.rstrip("/") + "/images/generations"


def _credentials() -> str:
    for name in ("IMAGE_API_KEY", "API", "API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _model_name() -> str:
    """Prefer the model chosen in the Telegram panel, then the env default."""
    try:
        import config

        selected = str(config.get_image_engine(None) or "").strip()
        if selected:
            return selected
    except Exception:
        pass
    return os.environ.get("IMAGE_MODEL_NAME", "").strip() or "dall-e-3"


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
        "model": _model_name(),
        "prompt": prompt,
        "n": 1,
        "size": dimensions,
    }
    # Upstream gateways intermittently fail with 4xx/5xx or drop the connection
    # mid-response. Retry a few times: the same prompt usually succeeds later.
    try:
        attempts = max(1, min(5, int(os.environ.get("IMAGE_RETRY_ATTEMPTS", 3))))
    except (TypeError, ValueError):
        attempts = 3
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            started = time.monotonic()
            response = requests.post(
                _endpoint(),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=_timeout(),
            )
        except Exception as exc:
            last_error = type(exc).__name__
            _LOGGER.warning("image request failed: %s attempt=%d/%d", last_error, attempt, attempts)
            if attempt < attempts:
                time.sleep(2)
                continue
            return f"<tool_error>图像服务连接失败：{last_error}</tool_error>"

        _LOGGER.warning(
            "image request finished in %.1fs status=%s attempt=%d/%d",
            time.monotonic() - started, response.status_code, attempt, attempts,
        )
        if response.status_code == 200:
            break
        # 401/403 mean the credentials are wrong; retrying cannot help.
        if response.status_code in (401, 403):
            return f"<tool_error>图像服务拒绝了请求（{response.status_code}），请检查 IMAGE_API_KEY。</tool_error>"
        last_error = str(response.status_code)
        if attempt < attempts:
            _LOGGER.warning("image gateway returned %s, retrying", response.status_code)
            time.sleep(2)
            continue
        return (
            f"<tool_error>图像服务多次返回 {response.status_code}，本次没有生成成功。"
            "请如实说明这次没有画出来，不要编造结果。</tool_error>"
        )

    if response.status_code != 200:
        return f"<tool_error>图像服务返回 {response.status_code}，请检查 IMAGE_BASE_URL 与 IMAGE_MODEL_NAME。</tool_error>"
    try:
        image = _extract(response.json())
    except ValueError:
        return "<tool_error>图像服务返回了无法解析的内容。</tool_error>"
    except Exception as exc:
        # A truncated body (ChunkedEncodingError) surfaces here as well.
        _LOGGER.warning("image response unreadable: %s", type(exc).__name__)
        return f"<tool_error>图像结果传输中断（{type(exc).__name__}），本次没有拿到图片。</tool_error>"
    if not image:
        return "<tool_error>图像服务没有返回可用的图像。</tool_error>"
    return image
