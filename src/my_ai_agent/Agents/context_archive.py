"""Durable, conversation-scoped search for messages and compaction checkpoints."""

import json
import time
from typing import Literal

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert

from ..redaction import redact_secrets
from ..web.models import ContextRecord

SearchScope = Literal["all", "checkpoints", "messages", "tools"]
CHECKPOINT_PREFIX = "checkpoint-"


def thread_id_from(config):
    return config.get("configurable", {}).get("thread_id")


def describe_message(message):
    content = message.content
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, default=str)
    if isinstance(message, AIMessage) and (message.tool_calls or message.invalid_tool_calls):
        calls = json.dumps([*message.tool_calls, *message.invalid_tool_calls], ensure_ascii=False, default=str)
        content = f"{content}\n[工具调用] {calls}".lstrip()
    attachment_ids = message.additional_kwargs.get("attachment_ids", ())
    if attachment_ids:
        content = f"{content}\n[附件 ID] {', '.join(attachment_ids)}".lstrip()
    return redact_secrets(content)


class ContextArchive:
    def __init__(self, database, *, web_threads=False):
        self.database = database
        self.web_threads = web_threads

    def _conversation_id(self, thread_id):
        return thread_id.split(":", 1)[1] if self.web_threads else None

    def save_messages(self, thread_id: str, messages):
        now = time.time()
        rows = [
            {
                "thread_id": thread_id,
                "id": message.id,
                "conversation_id": self._conversation_id(thread_id),
                "kind": {"human": "user", "ai": "assistant"}.get(message.type, message.type),
                "name": message.name,
                "content": describe_message(message),
                "source_end_id": None,
                "created_at": now + index * 0.000001,
            }
            for index, message in enumerate(messages)
            if message.id and not message.id.startswith(CHECKPOINT_PREFIX)
        ]
        if rows:
            with self.database.session() as db:
                db.execute(insert(ContextRecord).on_conflict_do_nothing(), rows)

    def save_checkpoint(self, thread_id: str, checkpoint_id: str, summary: str, source_end_id: str | None):
        with self.database.session() as db:
            db.add(ContextRecord(
                thread_id=thread_id, id=checkpoint_id, kind="checkpoint", content=redact_secrets(summary),
                conversation_id=self._conversation_id(thread_id), source_end_id=source_end_id, created_at=time.time(),
            ))

    def search(self, thread_id: str, query: str, scope: SearchScope, limit: int):
        query = query.strip()
        if not 1 <= len(query) <= 160 or not 1 <= limit <= 10:
            return {"ok": False, "error": "关键词长度须为 1–160 字符，结果数量须为 1–10。"}
        position = func.instr(func.lower(ContextRecord.content), func.lower(query))
        preview = func.substr(ContextRecord.content, func.max(1, position - 100), 380)
        statement = select(
            ContextRecord.id, ContextRecord.kind, ContextRecord.name, ContextRecord.created_at,
            (position - 1).label("match_offset"), preview.label("preview"),
        ).where(ContextRecord.thread_id == thread_id, position > 0)
        kinds = {"checkpoints": ("checkpoint",), "messages": ("user", "assistant"), "tools": ("tool",)}
        if scope != "all":
            statement = statement.where(ContextRecord.kind.in_(kinds[scope]))
        with self.database.session() as db:
            matches = db.execute(statement.order_by(ContextRecord.created_at.desc(), ContextRecord.id).limit(limit))
            return {"ok": True, "matches": [dict(row) for row in matches.mappings()]}

    def read(self, thread_id: str, record_id: str, offset: int, max_chars: int):
        if offset < 0 or not 1 <= max_chars <= 8000 or not 1 <= len(record_id) <= 160:
            return {"ok": False, "error": "记录 ID、偏移量或读取长度无效。"}
        with self.database.session() as db:
            row = db.get(ContextRecord, (thread_id, record_id))
            if row is None:
                return {"ok": False, "error": "当前会话中找不到该记录。"}
            end = min(offset + max_chars, len(row.content))
            return {
                "ok": True, "id": row.id, "kind": row.kind, "name": row.name, "content": row.content[offset:end],
                "source_end_id": row.source_end_id, "next_offset": end if end < len(row.content) else None,
            }


def context_tools(archive: ContextArchive):
    @tool
    def context_search(
        query: str, runtime: ToolRuntime, scope: SearchScope = "all", limit: int = 5,
    ) -> dict:
        """按字面关键词搜索当前会话保存的检查点与原始记录。

        scope 可选 all、checkpoints、messages、tools。结果包含记录 ID 和命中片段。
        可搜索报错、文件名或用户用语，使用 context_read 获取原文。
        """
        thread_id = thread_id_from(runtime.config)
        if not thread_id:
            return {"ok": False, "error": "会话检索需要有效的会话。"}
        return archive.search(thread_id, query, scope, limit)

    @tool
    def context_read(record_id: str, runtime: ToolRuntime, offset: int = 0, max_chars: int = 4000) -> dict:
        """按记录 ID 分页读取当前会话里的一条检查点、消息或工具输出。

        offset 从 0 开始，下一页使用 next_offset，null 表示读完。
        """
        thread_id = thread_id_from(runtime.config)
        if not thread_id:
            return {"ok": False, "error": "会话检索需要有效的会话。"}
        return archive.read(thread_id, record_id, offset, max_chars)

    return [context_search, context_read]
