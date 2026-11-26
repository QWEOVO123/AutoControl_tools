import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2
from fastapi.testclient import TestClient
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import select

from my_ai_agent.Agents.context_archive import ContextArchive
from my_ai_agent.Agents.core import init_agent
from my_ai_agent.LLM_init.deepseek_init import AgentChatDeepSeek
from my_ai_agent.LLM_init.model_catalog import DeepSeekModelCatalog, ModelLimits
from my_ai_agent.web.app import create_app
from my_ai_agent.web.config import Settings
from my_ai_agent.web.database import Database
from my_ai_agent.web.models import ContextRecord


LOG = "A" * 9000 + "早期唯一错误码" + "Z" * 9000
SUMMARY = "本轮诊断：查过服务日志，之后需继续验证。"


@tool
def fixture_log() -> str:
    """返回集成测试的模拟服务日志。"""
    return LOG


class ModelFixture:
    def __init__(self):
        self.requests = []
        self.model_requests = 0
        self.context_window = 1048576
        self.max_output_tokens = 393216
        self.overflow_prompt = None
        self.overflow_count = 0
        self.empty_summary = False

    def __call__(self, request):
        if request.url.path == "/models":
            self.model_requests += 1
            return httpx2.Response(200, json={"data": [{
                "id": "deepseek-flash", "context_window": self.context_window,
                "max_output_tokens": self.max_output_tokens,
            }]})
        payload = json.loads(request.content)
        self.requests.append(payload)
        messages = payload["messages"]
        prompt = messages[-1]["content"]
        is_summary = "会话检查点" in messages[0]["content"] and not payload.get("tools")
        if is_summary:
            answer = {"content": " " if self.empty_summary else SUMMARY}
        elif self.overflow_prompt and prompt == self.overflow_prompt and self.overflow_count == 0:
            self.overflow_count += 1
            return httpx2.Response(400, json={"error": {
                "code": "context_length_exceeded", "type": "invalid_request_error", "message": "maximum context length",
            }})
        elif prompt == "查服务日志":
            answer = self.tool_call("fixture_log", "log-call", {})
        elif prompt == "回查诊断":
            answer = self.tool_call("context_search", "recall-call", {"query": "本轮诊断", "scope": "checkpoints"})
        elif messages[-1].get("tool_call_id") == "recall-call":
            match = json.loads(prompt)["matches"][0]
            answer = self.tool_call("context_read", "read-call", {"record_id": match["id"]})
        elif payload.get("response_format") == {"type": "json_object"}:
            answer = {"content": json.dumps({"result": "继续处理"}, ensure_ascii=False)}
        else:
            answer = {"content": "继续处理"}

        answer["role"] = "assistant"
        finish_reason = "tool_calls" if "tool_calls" in answer else "stop"
        common = {"id": f"response-{len(self.requests)}", "created": 123, "model": "deepseek-flash"}
        if not payload.get("stream"):
            return httpx2.Response(200, json={
                **common, "object": "chat.completion", "choices": [
                    {"index": 0, "message": answer, "finish_reason": finish_reason},
                ],
            })
        if "tool_calls" in answer:
            answer["tool_calls"][0]["index"] = 0
        chunks = [
            {"index": 0, "delta": answer, "finish_reason": None},
            {"index": 0, "delta": {}, "finish_reason": finish_reason},
        ]
        lines = [
            "data: " + json.dumps({**common, "object": "chat.completion.chunk", "choices": [chunk]})
            for chunk in chunks
        ]
        return httpx2.Response(
            200, text="\n\n".join([*lines, "data: [DONE]"]) + "\n\n",
            headers={"Content-Type": "text/event-stream"},
        )

    @staticmethod
    def tool_call(name, call_id, arguments):
        return {
            "content": None, "reasoning_content": "测试推理字段",
            "tool_calls": [{
                "id": call_id, "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }],
        }

    def model(self, **kwargs):
        kwargs.setdefault("api_base", "https://deepseek.test")
        return AgentChatDeepSeek(
            **kwargs,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self)),
            http_async_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self)),
        )


class ContextMemoryTests(unittest.TestCase):
    def test_web_prunes_then_compacts_and_recalls_after_restart(self):
        upstream = ModelFixture()
        upstream.context_window = 12000
        upstream.max_output_tokens = 1800
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            "os.environ", {"DEEPSEEK_API_KEY": "offline-test-key", "DEEPSEEK_MODEL": "deepseek-flash"}
        ), patch("my_ai_agent.Agents.core.TOOLS", [fixture_log]), patch(
            "my_ai_agent.LLM_init.deepseek_init.AgentChatDeepSeek", side_effect=upstream.model,
        ):
            settings = Settings(
                _env_file=None, data_dir=Path(folder), cookie_secure=False,
                context_keep_tokens=3000,
            )
            with TestClient(create_app(settings)) as client:
                client.app.state.auth.set_password("tester", "temporary-testing-password", create=True)
                headers = self.login(client)
                conversation = client.post("/api/conversations", headers=headers).json()["id"]
                path = f"/api/conversations/{conversation}"
                self.send(client, path, headers, "查服务日志")
                tool_response = upstream.requests[-1]["messages"]
                self.assertEqual(tool_response[-1]["content"], LOG)
                self.assertEqual(tool_response[-2]["reasoning_content"], "测试推理字段")

                self.send(client, path, headers, "甲" * 4800)
                pruned = upstream.requests[-1]["messages"]
                record_id = json.loads(next(message["content"] for message in pruned if message["role"] == "tool"))["record_id"]
                self.assertEqual(pruned[2]["tool_calls"][0]["id"], pruned[3]["tool_call_id"])
                self.assertEqual(pruned[2]["reasoning_content"], "测试推理字段")
                self.assertNotIn("早期唯一错误码", json.dumps(pruned, ensure_ascii=False))
                self.assertFalse(any(not item.get("tools") for item in upstream.requests))

                output = self.send(client, path, headers, "乙" * 4600, output_mode="json")
                self.assertNotIn(SUMMARY, output)
                self.assertIn(SUMMARY, upstream.requests[-1]["messages"][1]["content"])
                self.assertFalse(upstream.requests[-2].get("tools"))
                self.assertIsNone(upstream.requests[-2].get("response_format"))
                self.assertEqual(upstream.requests[-2]["thinking"], {"type": "disabled"})
                self.assertEqual(upstream.requests[-2]["max_tokens"], 1800)
                self.assertEqual(upstream.requests[-1]["response_format"], {"type": "json_object"})
                self.assertEqual(upstream.model_requests, 1)

                history = client.get(path).json()["messages"]
                self.assertEqual(len(history), 6)
                self.assertEqual(history[1]["tool_events"][0]["output"], LOG[:18000] + "\n[内容已截断]")
                with client.app.state.database.session() as db:
                    tool_record = db.scalar(select(ContextRecord).where(ContextRecord.id == record_id))
                    self.assertEqual(tool_record.content, LOG)
                    thread_id = tool_record.thread_id
                archive = client.app.state.runtime.archive
                match = archive.search(thread_id, "早期唯一错误码", "tools", 5)["matches"][0]
                self.assertEqual(match["id"], record_id)
                self.assertEqual(archive.read(thread_id, record_id, match["match_offset"], 7)["content"], "早期唯一错误码")
                self.assertFalse(archive.read("other:" + conversation, record_id, 0, 8000)["ok"])

            with TestClient(create_app(settings)) as client:
                headers = self.login(client)
                output = self.send(client, path, headers, "回查诊断")
                self.assertIn("context_search", output)
                self.assertIn("context_read", output)
                self.assertIn(SUMMARY, output)
                archive = client.app.state.runtime.archive
                checkpoint = archive.search(thread_id, "本轮诊断", "checkpoints", 5)["matches"][0]
                self.assertTrue(checkpoint["id"].startswith("checkpoint-"))
                self.assertIn(SUMMARY, archive.read(thread_id, checkpoint["id"], 0, 8000)["content"])
                self.assertEqual(client.delete(path, headers=headers).status_code, 200)
                self.assertFalse(archive.search(thread_id, "本轮诊断", "all", 5)["matches"])

    def test_model_limits_reserve_output_and_tolerate_missing_window(self):
        limits = ModelLimits(1048576, 393216)
        self.assertEqual(limits.input_budget("high"), 878182)
        self.assertEqual(limits.input_budget("max"), 812646)
        self.assertEqual(limits.input_budget("high", requested_output=4096), 939622)
        upstream = ModelFixture()
        upstream.context_window = None
        model = upstream.model(model="deepseek-flash", api_key="offline-test-key", api_base="https://api.deepseek.com/v1")
        catalog = DeepSeekModelCatalog()
        self.assertIsNone(catalog.limits_for(model))
        self.assertIsNone(catalog.limits_for(model))
        self.assertEqual(upstream.model_requests, 1)

    def test_sync_agent_retries_only_the_model_on_context_overflow(self):
        upstream = ModelFixture()
        upstream.overflow_prompt = "触发窗口超限"
        with tempfile.TemporaryDirectory() as folder, patch("my_ai_agent.Agents.core.TOOLS", [fixture_log]), patch(
            "my_ai_agent.Agents.core.LLM_init",
            return_value=upstream.model(model="deepseek-flash", api_key="offline-test-key"),
        ):
            settings = Settings(_env_file=None, data_dir=Path(folder))
            database = Database(settings.database_url)
            try:
                database.initialize()
                archive = ContextArchive(database)
                with SqliteSaver.from_conn_string(str(Path(folder, "cli-checkpoints.sqlite3"))) as saver:
                    agent = init_agent(checkpointer=saver, archive=archive)
                    config = {"configurable": {"thread_id": "cli"}}
                    agent.invoke({"messages": [{"role": "user", "content": "查服务日志"}]}, config)
                with SqliteSaver.from_conn_string(str(Path(folder, "cli-checkpoints.sqlite3"))) as saver:
                    agent = init_agent(checkpointer=saver, archive=archive)
                    result = agent.invoke({"messages": [{"role": "user", "content": "触发窗口超限"}]}, config)
                self.assertEqual(result["messages"][-1].content, "继续处理")
                self.assertIn(SUMMARY, result["messages"][0].content)
                normal = [request for request in upstream.requests if request.get("tools")]
                self.assertEqual(sum(item["messages"][-1]["content"] == "触发窗口超限" for item in normal), 2)
                self.assertEqual(len(archive.search("cli", "早期唯一错误码", "tools", 10)["matches"]), 1)
            finally:
                database.engine.dispose()

    def test_empty_summary_does_not_replace_history(self):
        upstream = ModelFixture()
        upstream.empty_summary = True
        first = "甲" * 4500
        followup = "乙" * 4500
        with tempfile.TemporaryDirectory() as folder, patch("my_ai_agent.Agents.core.TOOLS", []), patch(
            "my_ai_agent.Agents.core.LLM_init",
            return_value=upstream.model(model="deepseek-flash", api_key="offline-test-key"),
        ):
            database = Database(Settings(_env_file=None, data_dir=Path(folder)).database_url)
            try:
                database.initialize()
                archive = ContextArchive(database)
                agent = init_agent(
                    checkpointer=InMemorySaver(), archive=archive, context_token_budget=8000, context_keep_tokens=2000,
                )
                config = {"configurable": {"thread_id": "cli"}}
                agent.invoke({"messages": [{"role": "user", "content": first}]}, config)
                with self.assertLogs("my_ai_agent.Agents.context", level="WARNING"):
                    result = agent.invoke({"messages": [{"role": "user", "content": followup}]}, config)
                self.assertEqual(result["messages"][0].content, first)
                self.assertEqual(result["messages"][-1].content, "继续处理")
                self.assertEqual(upstream.requests[-1]["messages"][1]["content"], first)
                self.assertEqual(archive.search("cli", "甲甲", "checkpoints", 5)["matches"], [])
            finally:
                database.engine.dispose()

    @staticmethod
    def login(client):
        response = client.post("/api/auth/login", json={
            "username": "tester", "password": "temporary-testing-password",
        })
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    def send(self, client, path, headers, content, *, output_mode="text"):
        response = client.post(path + "/runs", headers=headers, json={
            "content": content, "reasoning_effort": "high", "output_mode": output_mode,
        })
        self.assertIn("event: run.completed", response.text, response.text[-1200:])
        return response.text
