import asyncio
from contextlib import suppress
import json
import os
import re
import time

from fastapi import HTTPException
from sqlalchemy import select

from ...Agents.core import init_agent
from ...LLM_init.deepseek_init import ReasoningEffort
from ...Tools.jobs import JOBS
from ..models import Message, MessageReasoning, Run
from .conversations import ConversationService


def redact_secrets(text):
    for key, secret in os.environ.items():
        if len(secret) >= 8 and re.search(r"api.?key|password|secret|access.?token", key, re.I):
            text = text.replace(secret, "[已隐藏]")
    return text


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
    def __init__(self, database, checkpointer, settings, agent_factory=None):
        self.database = database
        self.checkpointer = checkpointer
        self.settings = settings
        self.agent_factory = agent_factory
        self.agents = {}
        self.agent_lock = asyncio.Lock()
        self.guard = asyncio.Lock()
        self.active = {}

    async def get_agent(self, effort: ReasoningEffort):
        async with self.agent_lock:
            if effort not in self.agents:
                if self.agent_factory is not None:
                    agent = await asyncio.to_thread(self.agent_factory, self.checkpointer)
                else:
                    agent = await asyncio.to_thread(
                        init_agent, checkpointer=self.checkpointer, probe=False, reasoning_effort=effort
                    )
                self.agents[effort] = agent
            return self.agents[effort]

    async def start(self, user_id, conversation_id, content, effort: ReasoningEffort = "none"):
        content = content.strip()
        if not content:
            raise HTTPException(422, "消息不能为空。")
        async with self.guard:
            with self.database.session() as db:
                conversation = ConversationService.owned(db, user_id, conversation_id)
                if conversation_id in self.active:
                    raise HTTPException(409, "这个会话已有任务正在运行。")
                if len(self.active) >= self.settings.max_parallel_runs:
                    raise HTTPException(429, "运行中的任务较多，请稍后重试。")
                now = time.time()
                db.add(Message(conversation_id=conversation_id, role="user", content=content, created_at=now))
                reply = Message(conversation_id=conversation_id, role="assistant", status="running", created_at=now + 0.000001)
                db.add(reply)
                db.flush()
                run = Run(conversation_id=conversation_id, message_id=reply.id)
                db.add(run)
                db.flush()
                conversation.updated_at = time.time()
                if conversation.title == "新会话":
                    conversation.title = content[:40]
                handle = {"id": run.id, "message_id": reply.id, "owner": user_id, "task": None, "cancelled": False}
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
        try:
            if handle["cancelled"]:
                raise asyncio.CancelledError()
            agent = await self.get_agent(effort)
            async for event in agent.astream_events(
                {"messages": [{"role": "user", "content": content}]},
                config={"configurable": {"thread_id": f"{handle['owner']}:{conversation_id}"}, "recursion_limit": 64},
                version="v2",
            ):
                kind = event["event"]
                data = event.get("data", {})
                if kind in {"on_chat_model_stream", "on_chat_model_end"}:
                    model_id = str(event.get("run_id", ""))
                    streamed = kind == "on_chat_model_stream"
                    chunk = data.get("chunk") if streamed else data.get("output")
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
        except asyncio.CancelledError:
            status = "cancelled"
        except Exception as exc:
            status = "failed"
            error = public_data(str(exc))
        finally:
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
                    if reasoning:
                        db.add(MessageReasoning(message_id=message.id, content=redact_secrets("".join(reasoning))))
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
