import asyncio
from contextlib import suppress
import json
import os
import re
import time

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from sqlalchemy import select

from ...Agents.context import COMPACTION_TAG
from ...Agents.context_archive import ContextArchive, describe_message
from ...Agents.core import init_agent
from ...LLM_init.deepseek_init import OutputMode, ReasoningEffort
from ...LLM_init.model_catalog import DeepSeekModelCatalog
from ...Tools.jobs import JOBS
from ...deepseek_api import ATTACHMENT_REFERENCES, DeepSeekError
from ...redaction import redact_secrets
from ..models import ContextRecord, Message, MessageReasoning, MessageUsage, Run
from .conversations import ConversationService


def public_data(value):
    """Keep credentials and excessive tool output out of browser traces."""
    if isinstance(value, dict):
        return {str(key): "[已隐藏]" if re.search(r"password|api.?key|authorization|secret|access.?token", str(key), re.I) else public_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_data(item) for item in value]
    text = str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
    if isinstance(text, str):
        text = redact_secrets(text)
        return text[:18000] + ("\n[内容已截断]" if len(text) > 18000 else "")
    return text


def sse(event):
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


class AgentRuntime:
    def __init__(self, database, checkpointer, settings, agent_factory=None, *, attachments=None):
        self.database = database
        self.checkpointer = checkpointer
        self.settings = settings
        self.agent_factory = agent_factory
        self.attachments = attachments
        self.archive = ContextArchive(database, web_threads=True)
        self.model_catalog = DeepSeekModelCatalog()
        self.agents = {}
        self.agent_lock = asyncio.Lock()
        self.guard = asyncio.Lock()
        self.active = {}

    async def get_agent(self, effort: ReasoningEffort, output_mode: OutputMode):
        key = (effort, output_mode)
        async with self.agent_lock:
            if key not in self.agents:
                if self.agent_factory is not None:
                    agent = await asyncio.to_thread(self.agent_factory, self.checkpointer)
                else:
                    agent = await asyncio.to_thread(
                        init_agent, checkpointer=self.checkpointer, probe=False,
                        reasoning_effort=effort, output_mode=output_mode,
                        archive=self.archive, context_token_budget=self.settings.context_token_budget,
                        context_keep_tokens=self.settings.context_keep_tokens, model_catalog=self.model_catalog,
                    )
                self.agents[key] = agent
            return self.agents[key]

    async def start(
        self, user_id, conversation_id, content, effort: ReasoningEffort = "none",
        attachment_ids=(), output_mode: OutputMode = "text",
    ):
        content = content.strip()
        if not content and not attachment_ids:
            raise HTTPException(422, "消息不能为空。")
        if attachment_ids and os.getenv("DEEPSEEK_MODEL", "deepseek-flash") != "deepseek-flash":
            raise HTTPException(422, "附件问答需要 deepseek-flash。")
        async with self.guard:
            with self.database.session() as db:
                conversation = ConversationService.owned(db, user_id, conversation_id)
                if conversation_id in self.active:
                    raise HTTPException(409, "这个会话已有任务正在运行。")
                if len(self.active) >= self.settings.max_parallel_runs:
                    raise HTTPException(429, "运行中的任务较多，请稍后重试。")
                now = time.time()
                user_message = Message(conversation_id=conversation_id, role="user", content=content, created_at=now)
                db.add(user_message)
                reply = Message(conversation_id=conversation_id, role="assistant", status="running", created_at=now + 0.000001)
                db.add(reply)
                db.flush()
                if attachment_ids:
                    self.attachments.bind(db, conversation_id, user_message.id, attachment_ids)
                thread_id = f"{user_id}:{conversation_id}"
                archived_input = HumanMessage(content=content, additional_kwargs={"attachment_ids": attachment_ids})
                db.add(ContextRecord(
                    thread_id=thread_id, id=user_message.id, conversation_id=conversation_id, kind="user",
                    content=describe_message(archived_input), created_at=now,
                ))
                run = Run(conversation_id=conversation_id, message_id=reply.id)
                db.add(run)
                db.flush()
                conversation.updated_at = time.time()
                if conversation.title == "新会话":
                    conversation.title = content[:40] or "附件问答"
                handle = {
                    "id": run.id, "message_id": reply.id, "task": None,
                    "user_message_id": user_message.id, "thread_id": thread_id, "cancelled": False,
                    "attachment_ids": attachment_ids, "output_mode": output_mode,
                }
            self.active[conversation_id] = handle
        return self._stream(conversation_id, content, handle, effort)

    async def _stream(self, conversation_id, content, handle, effort):
        queue = asyncio.Queue(maxsize=256)
        task = asyncio.create_task(self._execute(conversation_id, content, handle, queue, effort))
        handle["task"] = task
        try:
            yield sse({"type": "run.started", "run_id": handle["id"], "message_id": handle["message_id"]})
            while True:
                if not queue.empty():
                    yield sse(queue.get_nowait())
                elif task.done():
                    break
                else:
                    waiter = asyncio.create_task(queue.get())
                    try:
                        done, _ = await asyncio.wait({waiter, task}, timeout=15, return_when=asyncio.FIRST_COMPLETED)
                        if waiter in done:
                            yield sse(waiter.result())
                        elif not done:
                            yield ": keepalive\n\n"
                    finally:
                        if not waiter.done():
                            waiter.cancel()
                        await asyncio.gather(waiter, return_exceptions=True)
            self._finish_unstarted(handle)
            with self.database.session() as db:
                run = db.get(Run, handle["id"])
                yield sse({"type": f"run.{run.status}", "run_id": run.id, "error": run.error})
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._finish_unstarted(handle)
            self.active.pop(conversation_id, None)

    def _finish_unstarted(self, handle):
        # A request may be cancelled before the execution coroutine first runs.
        with self.database.session() as db:
            run = db.get(Run, handle["id"])
            if run and run.status == "running":
                run.status = "cancelled"
                run.finished_at = time.time()
                message = db.get(Message, run.message_id)
                if message:
                    message.status = "cancelled"

    async def _execute(self, conversation_id, content, handle, queue, effort):
        text = []
        reasoning = []
        tools = {}
        status = "completed"
        error = None
        streamed_text = set()
        streamed_reasoning = set()
        usage_by_call = {}
        usage = None
        references_token = None
        output_mode = handle["output_mode"]
        json_segments = {}
        final_model_id = ""
        final_finish_reason = None
        try:
            if handle["cancelled"]:
                raise asyncio.CancelledError()
            agent = await self.get_agent(effort, output_mode)
            attachment_ids = handle["attachment_ids"]
            user_message = {"role": "user", "content": content, "id": handle["user_message_id"]}
            if self.attachments and os.getenv("DEEPSEEK_MODEL", "deepseek-flash") == "deepseek-flash":
                if attachment_ids:
                    await queue.put({"type": "attachment.preparing"})
                references = await self.attachments.references(conversation_id, attachment_ids)
                references_token = ATTACHMENT_REFERENCES.set(references)
                if attachment_ids:
                    await queue.put({"type": "attachment.ready"})
            if attachment_ids:
                user_message = HumanMessage(
                    id=handle["user_message_id"],
                    content=content or "请阅读这条消息的附件并概述要点。",
                    additional_kwargs={"attachment_ids": list(attachment_ids)},
                )
            async for event in agent.astream_events(
                {"messages": [user_message]},
                config={"configurable": {"thread_id": handle["thread_id"]}, "recursion_limit": 64},
                version="v2",
            ):
                kind = event["event"]
                data = event.get("data", {})
                if COMPACTION_TAG in event.get("tags", ()):
                    if kind == "on_chat_model_end" and (tokens := getattr(data.get("output"), "usage_metadata", None)):
                        usage_by_call[str(event["run_id"])] = tokens
                    continue
                if kind in {"on_chat_model_stream", "on_chat_model_end"}:
                    model_id = str(event.get("run_id", ""))
                    streamed = kind == "on_chat_model_stream"
                    chunk = data.get("chunk") if streamed else data.get("output")
                    if output_mode == "json":
                        final_model_id = model_id
                        if not streamed:
                            final_finish_reason = getattr(chunk, "response_metadata", {}).get("finish_reason")
                    tokens = getattr(chunk, "usage_metadata", None)
                    if tokens:
                        usage_by_call[model_id] = tokens
                    fragment = getattr(chunk, "additional_kwargs", {}).get("reasoning_content")
                    if effort != "none" and isinstance(fragment, str) and fragment and (streamed or model_id not in streamed_reasoning):
                        separator = "\n\n" if reasoning and model_id not in streamed_reasoning else ""
                        streamed_reasoning.add(model_id)
                        delta = separator + redact_secrets(fragment)
                        reasoning.append(delta)
                        await queue.put({"type": "reasoning.delta", "text": delta})
                    if not streamed and model_id in streamed_text:
                        continue
                    for block in getattr(chunk, "content_blocks", []):
                        if block.get("type") == "text" and block.get("text"):
                            streamed_text.add(model_id)
                            delta = public_data(block["text"])
                            if output_mode == "json":
                                json_segments.setdefault(model_id, []).append(block["text"])
                            else:
                                text.append(delta)
                                await queue.put({"type": "message.delta", "text": delta})
                elif kind == "on_tool_start":
                    tool_id = str(event["run_id"])
                    item = {"id": tool_id, "name": event["name"], "input": public_data(data.get("input")), "status": "running", "started_at": time.time()}
                    tools[tool_id] = item
                    await queue.put({"type": "tool.started", "tool": item.copy()})
                elif kind in {"on_tool_end", "on_tool_error"}:
                    tool_id = str(event["run_id"])
                    output = data.get("output", data.get("error"))
                    failed = kind == "on_tool_error" or getattr(output, "status", None) == "error"
                    output = getattr(output, "content", output)
                    if isinstance(output, str):
                        with suppress(json.JSONDecodeError):
                            output = json.loads(output)
                    if isinstance(output, dict) and output.get("ok") is False:
                        failed = True
                    item = tools.setdefault(tool_id, {"id": tool_id, "name": event["name"], "input": None})
                    item.update(output=public_data(output), status="failed" if failed else "completed", finished_at=time.time())
                    await queue.put({"type": "tool.completed", "tool": item.copy()})
            if output_mode == "json":
                try:
                    if final_finish_reason == "length":
                        raise ValueError("truncated")
                    result = json.loads(redact_secrets("".join(json_segments.get(final_model_id, []))))
                    if not isinstance(result, dict):
                        raise ValueError("expected object")
                    formatted = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
                except (ValueError, RecursionError) as exc:
                    raise DeepSeekError("模型没有返回完整的 JSON 对象。请调整提示词后重试。") from exc
                text.append(formatted)
                await queue.put({"type": "message.delta", "text": formatted})
            if usage_by_call:
                counts = list(usage_by_call.values())
                hits = [entry.get("input_token_details", {}).get("cache_read") for entry in counts]
                usage = {
                    "input_tokens": sum(entry["input_tokens"] for entry in counts),
                    "output_tokens": sum(entry["output_tokens"] for entry in counts),
                    "cache_read_tokens": sum(hits) if all(hit is not None for hit in hits) else None,
                }
                await queue.put({"type": "usage.completed", "usage": usage})
        except asyncio.CancelledError:
            status = "cancelled"
        except DeepSeekError as exc:
            status = "failed"
            error = str(exc)
        except Exception as exc:
            status = "failed"
            error = public_data(str(exc))
        finally:
            if references_token is not None:
                ATTACHMENT_REFERENCES.reset(references_token)
            for item in tools.values():
                if item["status"] == "running":
                    item["status"] = "interrupted"
            with self.database.session() as db:
                message = db.get(Message, handle["message_id"])
                run = db.get(Run, handle["id"])
                if message:
                    message.content = "".join(text)
                    message.status = status
                    message.tool_events = json.dumps(list(tools.values()), ensure_ascii=False)
                    if status == "completed" and usage:
                        db.add(MessageUsage(message_id=message.id, **usage))
                    if reasoning:
                        db.add(MessageReasoning(message_id=message.id, content=redact_secrets("".join(reasoning))))
                    if status != "completed" and message.content:
                        db.add(ContextRecord(
                            thread_id=handle["thread_id"], id=message.id, conversation_id=conversation_id,
                            kind="assistant", content=redact_secrets(message.content), created_at=message.created_at,
                        ))
                if run:
                    run.status = status
                    run.error = error
                    run.finished_at = time.time()

    def cancel(self, user_id, conversation_id):
        with self.database.session() as db:
            ConversationService.owned(db, user_id, conversation_id)
        handle = self.active.get(conversation_id)
        if handle:
            handle["cancelled"] = True
            if handle["task"]:
                handle["task"].cancel()
        return {"ok": True, "was_running": handle is not None}

    async def shutdown(self):
        tasks = [item["task"] for item in self.active.values() if item["task"]]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.to_thread(JOBS.close)

    def recover(self):
        with self.database.session() as db:
            for run in db.scalars(select(Run).where(Run.status == "running")):
                run.status = "interrupted"
                run.finished_at = time.time()
                message = db.get(Message, run.message_id)
                if message:
                    message.status = "interrupted"
