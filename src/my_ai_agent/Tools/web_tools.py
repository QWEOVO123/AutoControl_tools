"""Read-only search tools backed by DeepSeek Search and Fetch."""

import ipaddress
from urllib.parse import urlsplit

import httpx
from langchain_core.tools import StructuredTool

from ..deepseek_api import BASE_URL, DeepSeekError, api_headers, json_object


def _search_payload(query, count):
    query = query.strip()
    if not 1 <= len(query) <= 128:
        raise ValueError("搜索词长度须在 1 到 128 个字符之间。")
    if not 1 <= count <= 10:
        raise ValueError("count 须在 1 到 10 之间。")
    return {"query": query, "count": count}


def _fetch_payload(url):
    url = url.strip()
    parsed = urlsplit(url)
    host = parsed.hostname
    if len(url) > 8192 or parsed.scheme not in {"http", "https"} or not host or parsed.username is not None:
        raise ValueError("请提供不含登录凭据的 HTTP(S) 网页链接。")
    try:
        public = ipaddress.ip_address(host).is_global
    except ValueError:
        domain = host.rstrip(".").lower()
        public = "." in domain and not domain.endswith((".localhost", ".local", ".internal"))
    if not public:
        raise ValueError("请提供可公开访问的网页地址。")
    return {"url": parsed._replace(fragment="").geturl()}


def _post(endpoint, payload):
    with httpx.Client(base_url=BASE_URL, headers=api_headers(), timeout=30) as client:
        return json_object(client.post(f"/v1/tools/{endpoint}", json=payload))


async def _apost(endpoint, payload):
    async with httpx.AsyncClient(base_url=BASE_URL, headers=api_headers(), timeout=30) as client:
        return json_object(await client.post(f"/v1/tools/{endpoint}", json=payload))


def _search_result(data, count):
    rows = data.get("results")
    if not isinstance(rows, list):
        raise DeepSeekError("DeepSeek 搜索结果格式异常。")
    return {"ok": True, "results": [
        {
            "title": str(row.get("title") or "")[:300],
            "url": str(row.get("url") or "")[:8192],
            "summary": str(row.get("summary") or row.get("snippet") or "")[:1400],
            "site": row.get("site_name"), "published_at": row.get("date"),
        }
        for row in rows[:count] if isinstance(row, dict)
    ]}


def _fetch_result(data, url):
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        raise DeepSeekError("没有可提取的网页正文。")
    return {
        "ok": True, "url": url, "title": str(data.get("title") or "")[:300],
        "content": content[:16000], "truncated": len(content) > 16000,
    }


def _error(exc):
    if isinstance(exc, httpx.TimeoutException):
        return {"ok": False, "error": "DeepSeek 联网工具请求超时。"}
    if isinstance(exc, httpx.HTTPError):
        return {"ok": False, "error": "无法连接 DeepSeek 联网工具。"}
    return {"ok": False, "error": str(exc)}


def _search(query: str, count: int = 5) -> dict:
    """搜索公开网页并返回标题、链接、摘要与日期。优先检索官方资料，引用时保留结果链接。"""
    try:
        return _search_result(_post("search", _search_payload(query, count)), count)
    except (ValueError, httpx.HTTPError, DeepSeekError) as exc:
        return _error(exc)


async def _asearch(query: str, count: int = 5) -> dict:
    try:
        return _search_result(await _apost("search", _search_payload(query, count)), count)
    except (ValueError, httpx.HTTPError, DeepSeekError) as exc:
        return _error(exc)


def _fetch(url: str) -> dict:
    """通过 DeepSeek 读取一个公开的 HTTP(S) 网页，返回最多 16000 字符的 Markdown 和截断状态。"""
    try:
        payload = _fetch_payload(url)
        return _fetch_result(_post("fetch", payload), payload["url"])
    except (ValueError, httpx.HTTPError, DeepSeekError) as exc:
        return _error(exc)


async def _afetch(url: str) -> dict:
    try:
        payload = _fetch_payload(url)
        return _fetch_result(await _apost("fetch", payload), payload["url"])
    except (ValueError, httpx.HTTPError, DeepSeekError) as exc:
        return _error(exc)


web_search = StructuredTool.from_function(_search, coroutine=_asearch, name="web_search")
web_fetch = StructuredTool.from_function(_fetch, coroutine=_afetch, name="web_fetch")
