"""Scoped multi-provider web search for Yoishizuku-bot.

Searches may aggregate Tavily, Exa, Google Programmable Search, and
DuckDuckGo. Providers without configured credentials are skipped; DuckDuckGo
remains a no-key fallback. The tool returns auditable URLs and extracted page
content, not a provider-generated answer.
"""

from __future__ import annotations

import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from .registry import register_tool
from .websearch import get_url_content

_PROVIDER_ORDER = {"tavily": 4, "exa": 3, "google": 2, "ddg": 1}
_SCOPE_DOMAINS = {
    "github": ("github.com",),
    "wiki": ("wikipedia.org", "zh.wikipedia.org"),
    "bilibili": ("bilibili.com", "b23.tv"),
}
_OFFICIAL_HINTS = {
    "openai": ("openai.com",),
    "anthropic": ("anthropic.com",),
    "telegram": ("telegram.org", "core.telegram.org"),
    "github": ("github.com",),
    "google": ("google.com", "blog.google"),
    "microsoft": ("microsoft.com",),
}


def _env_int(name: str, default: int, lower: int, upper: int) -> int:
    try:
        return max(lower, min(upper, int(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


def _providers() -> list[str]:
    configured = [
        value.strip().casefold()
        for value in os.environ.get("SEARCH_PROVIDERS", "tavily,exa,google,ddg").split(",")
        if value.strip().casefold() in _PROVIDER_ORDER
    ]
    return configured or ["ddg"]


def _clean_domain(value: str) -> str:
    value = str(value or "").strip().casefold()
    if not value:
        return ""
    if "://" in value:
        value = urlparse(value).netloc
    return value.strip("/ ")


def _domains(scope: str, sites: str, query: str) -> list[str]:
    values = [_clean_domain(value) for value in str(sites or "").split(",")]
    values = [value for value in values if value]
    normalized_scope = str(scope or "web").casefold()
    if not values:
        values = list(_SCOPE_DOMAINS.get(normalized_scope, ()))
    if normalized_scope == "official" and not values:
        lowered = str(query).casefold()
        for marker, domains in _OFFICIAL_HINTS.items():
            if marker in lowered:
                values.extend(domains)
    return list(dict.fromkeys(values))


def _query_with_domains(query: str, domains: list[str]) -> str:
    if not domains:
        return query
    clauses = [f"site:{domain}" for domain in domains]
    constraint = clauses[0] if len(clauses) == 1 else "(" + " OR ".join(clauses) + ")"
    return f"{query} {constraint}"


def _canonical_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    filtered_query = [
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in {"ref", "source"}
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.casefold(), parsed.netloc.casefold(), path, "", urlencode(filtered_query), ""))


def _domain_matches(url: str, domains: list[str]) -> bool:
    if not domains:
        return True
    host = urlparse(url).netloc.casefold().split(":", 1)[0]
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _hit(url: str, title: str = "", snippet: str = "", score: float = 0.0, provider: str = "") -> dict[str, Any] | None:
    canonical = _canonical_url(url)
    if not canonical:
        return None
    return {
        "url": canonical,
        "title": str(title or "").strip(),
        "snippet": str(snippet or "").strip(),
        "score": float(score or 0),
        "providers": [provider] if provider else [],
    }


def _search_ddg(query: str, limit: int, _: list[str], __: str) -> list[dict[str, Any]]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            rows = list(ddgs.text(query, safesearch="off", backend="lite", max_results=limit))
        return [
            candidate for candidate in (
                _hit(row.get("href", ""), row.get("title", ""), row.get("body", ""), 0, "ddg")
                for row in rows
            ) if candidate
        ]
    except Exception as exc:
        print(f"scoped search ddg failed: {type(exc).__name__}")
        return []


def _search_google(query: str, limit: int, _: list[str], __: str) -> list[dict[str, Any]]:
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    cx = os.environ.get("GOOGLE_CSE_ID", "").strip()
    if not key or not cx:
        return []
    try:
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"q": query, "key": key, "cx": cx, "num": min(limit, 10)},
            timeout=_env_int("SEARCH_PROVIDER_TIMEOUT", 8, 3, 30),
        )
        response.raise_for_status()
        return [
            candidate for candidate in (
                _hit(row.get("link", ""), row.get("title", ""), row.get("snippet", ""), 0, "google")
                for row in response.json().get("items", [])
            ) if candidate
        ]
    except Exception as exc:
        print(f"scoped search google failed: {type(exc).__name__}")
        return []


def _search_tavily(query: str, limit: int, domains: list[str], freshness: str) -> list[dict[str, Any]]:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        return []
    payload: dict[str, Any] = {
        "api_key": key,
        "query": query,
        "search_depth": "advanced",
        "max_results": limit,
        "include_answer": False,
        "include_raw_content": False,
    }
    if domains:
        payload["include_domains"] = domains
    days = {"day": 1, "week": 7, "month": 31}.get(str(freshness).casefold())
    if days:
        payload["days"] = days
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json=payload,
            timeout=_env_int("SEARCH_PROVIDER_TIMEOUT", 8, 3, 30),
        )
        response.raise_for_status()
        return [
            candidate for candidate in (
                _hit(row.get("url", ""), row.get("title", ""), row.get("content", ""), row.get("score", 0), "tavily")
                for row in response.json().get("results", [])
            ) if candidate
        ]
    except Exception as exc:
        print(f"scoped search tavily failed: {type(exc).__name__}")
        return []


def _search_exa(query: str, limit: int, domains: list[str], _: str) -> list[dict[str, Any]]:
    key = os.environ.get("EXA_API_KEY", "").strip()
    if not key:
        return []
    payload: dict[str, Any] = {
        "query": query,
        "numResults": limit,
        "type": "auto",
        "contents": {"text": {"maxCharacters": 2400}},
    }
    if domains:
        payload["includeDomains"] = domains
    try:
        response = requests.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=payload,
            timeout=_env_int("SEARCH_PROVIDER_TIMEOUT", 8, 3, 30),
        )
        response.raise_for_status()
        return [
            candidate for candidate in (
                _hit(
                    row.get("url", ""), row.get("title", ""),
                    row.get("text", "") or row.get("highlights", ""), row.get("score", 0), "exa",
                )
                for row in response.json().get("results", [])
            ) if candidate
        ]
    except Exception as exc:
        print(f"scoped search exa failed: {type(exc).__name__}")
        return []


def _collect_hits(query: str, limit: int, domains: list[str], freshness: str) -> list[dict[str, Any]]:
    full_query = _query_with_domains(query, domains)
    callbacks = {
        "tavily": _search_tavily,
        "exa": _search_exa,
        "google": _search_google,
        "ddg": _search_ddg,
    }
    hits: list[dict[str, Any]] = []
    enabled = _providers()
    with ThreadPoolExecutor(max_workers=len(enabled)) as pool:
        futures = [pool.submit(callbacks[name], full_query, limit, domains, freshness) for name in enabled]
        for future in as_completed(futures):
            try:
                hits.extend(future.result())
            except Exception as exc:
                print(f"scoped search provider failed: {type(exc).__name__}")
    merged: dict[str, dict[str, Any]] = {}
    for item in hits:
        if not _domain_matches(item["url"], domains):
            continue
        current = merged.get(item["url"])
        if current is None:
            merged[item["url"]] = item
            continue
        current["providers"] = list(dict.fromkeys(current["providers"] + item["providers"]))
        if len(item["snippet"]) > len(current["snippet"]):
            current["snippet"] = item["snippet"]
        if len(item["title"]) > len(current["title"]):
            current["title"] = item["title"]
        current["score"] = max(current["score"], item["score"])
    return sorted(
        merged.values(),
        key=lambda item: (
            len(item["providers"]),
            item["score"],
            max((_PROVIDER_ORDER.get(name, 0) for name in item["providers"]), default=0),
        ),
        reverse=True,
    )[:limit]


def _read_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not hits:
        return []
    workers = min(4, len(hits))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(get_url_content, item["url"]): item for item in hits}
        for future in as_completed(pending):
            item = pending[future]
            try:
                content = str(future.result() or "").strip()
            except Exception:
                content = ""
            item["content"] = content[:6000]
    return hits


def _format_hits(query: str, scope: str, domains: list[str], hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "<tool_error>没有找到可核验的结果。请更换关键词、放宽站点范围或稍后重试。</tool_error>"
    lines = [
        "以下是限定检索得到的可核验来源。回答时必须显示实际 URL；没有来源支持的内容不要补充。",
        f"查询：{query}",
        f"范围：{scope or 'web'}" + (f"；站点：{', '.join(domains)}" if domains else ""),
    ]
    for index, item in enumerate(hits, 1):
        lines.extend([
            f"\n[来源 {index}]",
            f"标题：{item['title'] or '（未提供标题）'}",
            f"URL：{item['url']}",
            f"检索源：{', '.join(item['providers']) or 'unknown'}",
        ])
        if item["snippet"]:
            lines.append(f"搜索摘要：{item['snippet'][:1200]}")
        if item.get("content"):
            lines.append(f"网页正文：{item['content']}")
    return "\n".join(lines)


@register_tool()
async def search_scoped(
    query: str,
    scope: str = "web",
    sites: str = "",
    freshness: str = "any",
    max_results: int = 5,
):
    """聚合限定范围的实时网页搜索，并返回可核验的 URL 与正文。

    参数：
    - query：要检索的问题或关键词。
    - scope：web（全网）、official（官方来源，建议同时给 sites）、github、docs、wiki、bilibili。
    - sites：可选，逗号分隔的限定域名，例如 "openai.com,developers.openai.com"。
    - freshness：any、day、week、month。
    - max_results：返回 1 到 8 个来源。

    适用于实时信息、官方公告、GitHub 项目、技术文档、Wiki 或视频页面。
    直接给出链接时优先使用 get_url_content；不要把搜索结果中未出现的 URL、日期或事实当作已确认内容。
    """
    query = str(query or "").strip()
    if not query:
        yield "<tool_error>搜索关键词不能为空。</tool_error>"
        return
    scope = str(scope or "web").strip().casefold()
    if scope not in {"web", "official", "github", "docs", "wiki", "bilibili"}:
        scope = "web"
    freshness = str(freshness or "any").strip().casefold()
    if freshness not in {"any", "day", "week", "month"}:
        freshness = "any"
    limit = _env_int("SEARCH_MAX_RESULTS", max_results, 1, 8)
    domains = _domains(scope, sites, query)

    yield "message_search_stage_1"
    hits = await asyncio.to_thread(_collect_hits, query, limit, domains, freshness)
    yield "message_search_stage_2"
    if not hits:
        yield _format_hits(query, scope, domains, [])
        return
    yield "message_search_stage_3"
    hits = await asyncio.to_thread(_read_hits, hits)
    yield "message_search_stage_4"
    yield _format_hits(query, scope, domains, hits)
