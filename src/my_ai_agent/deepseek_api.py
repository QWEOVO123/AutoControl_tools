"""Shared HTTP helpers for DeepSeek's non-chat endpoints."""

from contextvars import ContextVar
import os

import httpx
from dotenv import load_dotenv

BASE_URL = "https://api.deepseek.com"
ATTACHMENT_REFERENCES: ContextVar[dict[str, str] | None] = ContextVar("attachment_references", default=None)


class DeepSeekError(Exception):
    """An upstream failure with a message safe to show in the workspace."""


def api_headers() -> dict[str, str]:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        load_dotenv()
        key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise DeepSeekError("请先在后端配置 DEEPSEEK_API_KEY。")
    return {"Authorization": f"Bearer {key}"}


def ensure_success(response: httpx.Response) -> None:
    if response.is_success:
        return
    messages = {
        400: "DeepSeek 无法处理此请求。",
        401: "DeepSeek API Key 无效。",
        402: "DeepSeek 账号余额不足。",
        403: "DeepSeek 拒绝访问该资源。",
        404: "DeepSeek 未找到可用内容。",
        413: "请求超过 DeepSeek 的大小限制。",
        429: "DeepSeek 请求过多，请稍后重试。",
    }
    raise DeepSeekError(messages.get(response.status_code, f"DeepSeek 返回 HTTP {response.status_code}。"))


def json_object(response: httpx.Response) -> dict:
    ensure_success(response)
    try:
        data = response.json()
    except ValueError as exc:
        raise DeepSeekError("DeepSeek 返回了无法解析的数据。") from exc
    if not isinstance(data, dict) or "error" in data:
        raise DeepSeekError("DeepSeek 未能完成这次请求。")
    return data
