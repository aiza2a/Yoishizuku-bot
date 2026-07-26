"""Reverse image search backed by SauceNAO.

Given an image URL the tool returns the most likely source: site, title,
author, original page links and similarity. It never fabricates a source; a
low-similarity match is reported as uncertain so the model can say so plainly.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .registry import register_tool

_ENDPOINT = "https://saucenao.com/search.php"

# db=999 searches every index. Anime/manga/illustration indexes dominate, which
# matches the usual "where is this picture from" question.
_DEFAULT_DB = "999"

_SOURCE_LABELS = {
    "pixiv": "Pixiv",
    "danbooru": "Danbooru",
    "gelbooru": "Gelbooru",
    "yandere": "yande.re",
    "konachan": "Konachan",
    "anime": "动画",
    "manga": "漫画",
    "twitter": "X / Twitter",
    "deviantart": "DeviantArt",
    "fanbox": "Fanbox",
    "fantia": "Fantia",
    "nijie": "Nijie",
    "seiga": "ニコニコ静画",
    "bcy": "半次元",
}


def _timeout() -> int:
    try:
        return max(5, min(60, int(os.environ.get("SAUCENAO_TIMEOUT", 20))))
    except (TypeError, ValueError):
        return 20


def _min_similarity() -> float:
    try:
        return max(0.0, min(100.0, float(os.environ.get("SAUCENAO_MIN_SIMILARITY", 55))))
    except (TypeError, ValueError):
        return 55.0


def _source_name(index_name: str) -> str:
    lowered = str(index_name or "").casefold()
    for marker, label in _SOURCE_LABELS.items():
        if marker in lowered:
            return label
    return str(index_name or "未知来源").split("-")[0].strip() or "未知来源"


def _collect_links(data: dict[str, Any]) -> list[str]:
    links: list[str] = []
    for value in data.get("ext_urls") or []:
        text = str(value or "").strip()
        if text and text not in links:
            links.append(text)
    pixiv_id = data.get("pixiv_id")
    if pixiv_id:
        url = f"https://www.pixiv.net/artworks/{pixiv_id}"
        if url not in links:
            links.append(url)
    return links


def _format_result(entry: dict[str, Any]) -> list[str]:
    header = entry.get("header") or {}
    data = entry.get("data") or {}
    similarity = float(header.get("similarity") or 0)
    lines = [
        f"来源：{_source_name(header.get('index_name', ''))}",
        f"相似度：{similarity:.1f}%",
    ]
    title = data.get("title") or data.get("jp_name") or data.get("eng_name") or data.get("source")
    if title:
        lines.append(f"标题：{str(title).strip()}")
    author = (
        data.get("member_name")
        or data.get("author_name")
        or data.get("creator")
        or data.get("artist")
    )
    if isinstance(author, list):
        author = "、".join(str(item) for item in author if item)
    if author:
        lines.append(f"作者：{str(author).strip()}")
    if data.get("part"):
        lines.append(f"集数/页码：{data['part']}")
    if data.get("est_time"):
        lines.append(f"时间点：{data['est_time']}")
    for url in _collect_links(data)[:3]:
        lines.append(f"链接：{url}")
    return lines


@register_tool()
def search_image_source(image_url: str, max_results: int = 3) -> str:
    """以图搜图：根据图片地址查找原始出处、作者与原图链接。

    参数:
        image_url: 图片的公开 URL。用户直接发送图片时，请使用系统提供的图片地址。
        max_results: 返回的候选数量，1 到 5，默认 3。

    适用于「这张图出自哪里」「这是谁画的」「帮我找原图」。
    结果包含相似度；相似度偏低时必须说明不确定，不要断言来源。
    """
    url = str(image_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return "<tool_error>请提供以 http/https 开头的图片地址。</tool_error>"
    key = os.environ.get("SAUCENAO_API_KEY", "").strip()
    if not key:
        return "<tool_error>以图搜图尚未配置密钥，请先设置 SAUCENAO_API_KEY。</tool_error>"
    try:
        limit = max(1, min(5, int(max_results)))
    except (TypeError, ValueError):
        limit = 3

    try:
        response = requests.get(
            _ENDPOINT,
            params={
                "api_key": key,
                "url": url,
                "output_type": 2,
                "db": os.environ.get("SAUCENAO_DB", _DEFAULT_DB),
                "numres": limit,
            },
            timeout=_timeout(),
        )
    except Exception as exc:
        return f"<tool_error>以图搜图服务连接失败：{type(exc).__name__}</tool_error>"

    if response.status_code == 403:
        return "<tool_error>以图搜图密钥无效或已被拒绝，请检查 SAUCENAO_API_KEY。</tool_error>"
    if response.status_code == 429:
        return "<tool_error>以图搜图已达到调用频率上限，请稍后再试。</tool_error>"
    if response.status_code != 200:
        return f"<tool_error>以图搜图服务返回 {response.status_code}。</tool_error>"

    try:
        payload = response.json()
    except ValueError:
        return "<tool_error>以图搜图返回了无法解析的内容。</tool_error>"

    header = payload.get("header") or {}
    if int(header.get("status", 0) or 0) < 0:
        return f"<tool_error>以图搜图无法读取该图片：{header.get('message', '未知错误')}</tool_error>"

    results = payload.get("results") or []
    threshold = _min_similarity()
    accepted = [
        item for item in results
        if float(((item.get("header") or {}).get("similarity")) or 0) >= threshold
    ][:limit]

    if not accepted:
        best = 0.0
        if results:
            best = float(((results[0].get("header") or {}).get("similarity")) or 0)
        return (
            "没有找到足够可信的出处。\n"
            f"最高相似度只有 {best:.1f}%，低于 {threshold:.0f}% 的判定门槛。\n"
            "请如实说明没有查到可靠来源，不要猜测作者或作品名。"
        )

    lines = ["以下是以图搜图得到的候选出处，请按相似度如实转述，不要补充未出现的信息。"]
    remaining = header.get("long_remaining")
    if remaining is not None:
        lines.append(f"（今日剩余查询次数：{remaining}）")
    for index, entry in enumerate(accepted, 1):
        lines.append(f"\n[候选 {index}]")
        lines.extend(_format_result(entry))
    lines.append("\n数据来源：https://saucenao.com/")
    return "\n".join(lines)
