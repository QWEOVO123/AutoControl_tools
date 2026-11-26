import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch

import httpx2
from fastapi.testclient import TestClient
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import select

from my_ai_agent.LLM_init.deepseek_init import AgentChatDeepSeek
from my_ai_agent.web.app import create_app
from my_ai_agent.web.config import Settings
from my_ai_agent.web.models import User

PASSWORD = "testing-password-2026"


class FakeAgent:
    async def astream_events(self, inputs, config, version):
        if inputs["messages"][0]["content"] == "slow":
            await asyncio.sleep(3)
        if inputs["messages"][0]["content"] == "fail":
            raise RuntimeError("simulated provider failure")
        if inputs["messages"][0]["content"] == "flood":
            for _ in range(400):
                yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="x")}}
            return
        yield {"event": "on_tool_start", "run_id": "test-tool", "name": "list_directory", "data": {"input": {"path": "."}}}
        yield {"event": "on_tool_end", "run_id": "test-tool", "name": "list_directory", "data": {"output": {"ok": True, "entries": []}}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="你好，工作台。")}}


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agent-web-tests-")
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(_env_file=None, data_dir=Path(self.directory.name), frontend_dist=Path(self.directory.name) / "frontend", cookie_secure=False)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.app = create_app(self.settings, agent_factory=lambda saver: FakeAgent())
        self.client = self.stack.enter_context(TestClient(self.app))
        self.app.state.auth.set_password("tester", PASSWORD, create=True)
        self.app.state.auth.set_password("another", PASSWORD, create=True)

    def login(self, username="tester"):
        response = self.client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        self.headers = {"X-CSRF-Token": response.json()["csrf_token"]}
        return response

    def conversation(self):
        response = self.client.post("/api/conversations", headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_authentication_cookie_csrf_and_origin(self):
        self.assertEqual(self.client.get("/api/system").status_code, 401)
        self.assertEqual(self.client.get("/api/conversations").status_code, 401)
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD}, headers={"Origin": "https://untrusted.example"}).status_code, 403)
        response = self.login()
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        self.assertNotIn("password", response.text)
        self.assertEqual(self.client.post("/api/conversations").status_code, 403)
        self.assertEqual(self.client.get("/api/auth/me").json()["username"], "tester")
        self.assertEqual(self.client.get("/api/system", headers={"Host": "untrusted.example"}).status_code, 400)
        tools = {item["name"] for item in self.client.get("/api/system").json()["tools"]}
        self.assertTrue({"job_start", "job_output", "job_cancel", "sleep", "math_compute", "execute_python"} <= tools)
        token = self.client.cookies.get("agent_session")
        self.assertEqual(self.client.post("/api/auth/logout", headers=self.headers).status_code, 200)
        self.client.cookies.set("agent_session", token)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_password_hash_rotation_and_validation_privacy(self):
        self.login()
        with self.app.state.database.session() as db:
            user = db.scalar(select(User).where(User.username == "tester"))
            self.assertTrue(user.password_hash.startswith("$argon2"))
            self.assertNotEqual(user.password_hash, PASSWORD)
        token = self.client.cookies.get("agent_session")
        invalid = self.client.post("/api/auth/password", headers=self.headers, json={"current_password": PASSWORD, "new_password": "short"})
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn(PASSWORD, invalid.text)
        self.assertNotIn('"input"', invalid.text)
        response = self.client.post("/api/auth/password", headers=self.headers, json={"current_password": PASSWORD, "new_password": PASSWORD + "-new"})
        self.assertEqual(response.status_code, 200)
        self.client.cookies.set("agent_session", token)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD + "-new"}).status_code, 200)

    def test_rate_limiting(self):
        for _ in range(10):
            self.assertEqual(self.client.post("/api/auth/login", json={"username": "missing", "password": "bad"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "missing", "password": "bad"}).status_code, 429)

    def test_user_isolation_and_conversation_crud(self):
        self.login()
        conversation = self.conversation()
        response = self.client.patch(f"/api/conversations/{conversation}", headers=self.headers, json={"title": "测试会话"})
        self.assertEqual(response.json()["title"], "测试会话")
        self.login("another")
        self.assertEqual(self.client.get("/api/conversations").json(), [])
        self.assertEqual(self.client.get(f"/api/conversations/{conversation}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/conversations/{conversation}/runs", headers=self.headers, json={"content": "test"}).status_code, 404)
        self.assertEqual(self.client.post(f"/api/conversations/{conversation}/stop", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/conversations/{conversation}", headers=self.headers).status_code, 404)
        self.login()
        self.assertEqual(self.client.delete(f"/api/conversations/{conversation}", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(f"/api/conversations/{conversation}").status_code, 404)

    def test_stream_and_persisted_history_keep_tools_separate(self):
        self.login()
        conversation = self.conversation()
        response = self.client.post(f"/api/conversations/{conversation}/runs", headers=self.headers, json={"content": "hello"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        stream = events(response)
        self.assertEqual([item["type"] for item in stream], ["run.started", "tool.started", "tool.completed", "message.delta", "run.completed"])
        detail = self.client.get(f"/api/conversations/{conversation}").json()
        self.assertEqual([item["role"] for item in detail["messages"]], ["user", "assistant"])
        reply = detail["messages"][-1]
        self.assertEqual(reply["content"], "你好，工作台。")
        self.assertEqual(reply["tool_events"][0]["status"], "completed")
        self.assertFalse(detail["running"])
        self.assertEqual(detail["conversation"]["title"], "hello")

    def test_stream_failure_is_persisted(self):
        self.login()
        conversation = self.conversation()
        response = self.client.post(f"/api/conversations/{conversation}/runs", headers=self.headers, json={"content": "fail"})
        self.assertEqual(events(response)[-1]["type"], "run.failed")
        reply = self.client.get(f"/api/conversations/{conversation}").json()["messages"][-1]
        self.assertEqual(reply["status"], "failed")
        self.assertIn("simulated provider failure", reply["error"])

    def test_terminal_event_survives_queue_backpressure(self):
        self.login()
        conversation = self.conversation()
        response = self.client.post(f"/api/conversations/{conversation}/runs", headers=self.headers, json={"content": "flood"})
        output = events(response)
        self.assertEqual(output[-1]["type"], "run.completed")
        self.assertEqual(''.join(item["text"] for item in output if item["type"] == "message.delta"), "x" * 400)

    def test_conflict_and_cancellation(self):
        self.login()
        conversation = self.conversation()
        output = []
        thread = Thread(target=lambda: output.append(self.client.post(f"/api/conversations/{conversation}/runs", headers=self.headers, json={"content": "slow"})), daemon=True)
        thread.start()
        for _ in range(100):
            if conversation in self.app.state.runtime.active:
                break
            time.sleep(0.01)
        self.assertIn(conversation, self.app.state.runtime.active)
        conflict = self.client.post(f"/api/conversations/{conversation}/runs", headers=self.headers, json={"content": "another"})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.delete(f"/api/conversations/{conversation}", headers=self.headers).status_code, 409)
        self.assertEqual(self.client.post(f"/api/conversations/{conversation}/stop", headers=self.headers).status_code, 200)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(events(output[0])[-1]["type"], "run.cancelled")
        reply = self.client.get(f"/api/conversations/{conversation}").json()["messages"][-1]
        self.assertEqual(reply["status"], "cancelled")


class CheckpointPersistenceTests(unittest.TestCase):
    def test_restart_preserves_memory_and_conversations_are_isolated(self):
        class HistoryModel(BaseChatModel):
            @property
            def _llm_type(self):
                return "offline-history-test"

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                count = sum(isinstance(message, HumanMessage) for message in messages)
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content=f"turns={count}"))])

        def factory(saver):
            return create_agent(model=HistoryModel(), tools=[], checkpointer=saver)

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(_env_file=None, data_dir=Path(directory), cookie_secure=False)
            for iteration in range(2):
                app = create_app(settings, agent_factory=factory)
                with TestClient(app) as client:
                    if iteration == 0:
                        app.state.auth.set_password("tester", PASSWORD, create=True)
                    csrf = client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD}).json()["csrf_token"]
                    headers = {"X-CSRF-Token": csrf}
                    if iteration == 0:
                        conversation = client.post("/api/conversations", headers=headers).json()["id"]
                    response = client.post(f"/api/conversations/{conversation}/runs", headers=headers, json={"content": "hello"})
                    self.assertEqual(events(response)[-1]["type"], "run.completed", response.text)
                    content = ''.join(event["text"] for event in events(response) if event["type"] == "message.delta")
                    self.assertEqual(content, f"turns={iteration + 1}")
                    if iteration == 1:
                        other = client.post("/api/conversations", headers=headers).json()["id"]
                        response = client.post(f"/api/conversations/{other}/runs", headers=headers, json={"content": "fresh"})
                        self.assertIn('turns=1', response.text)
                        detail = client.get(f"/api/conversations/{conversation}").json()
                        self.assertEqual(len(detail["messages"]), 4)


class DeepSeekThinkingTests(unittest.TestCase):
    def test_thinking_stream_tools_and_effort_switching(self):
        requests = []

        def deepseek(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertEqual(request.url.path, "/chat/completions")
            self.assertTrue(body["stream"])
            self.assertNotIn("thinking", body)
            is_first = len(requests) == 1
            delta = []
            if body["reasoning_effort"] != "none":
                delta.extend([
                    {"role": "assistant", "reasoning_content": "第一段"},
                    {"reasoning_content": "推理"},
                ])
            if is_first:
                delta.append({"tool_calls": [{
                    "index": 0,
                    "id": "multiply_test",
                    "type": "function",
                    "function": {"name": "multiply", "arguments": '{"a": 3, "b": 4}'},
                }]})
            else:
                delta.append({"role": "assistant", "content": "最终回答"})
            chunks = [
                {"id": f"mock-{len(requests)}", "object": "chat.completion.chunk",
                 "created": 0, "model": "deepseek-flash",
                 "choices": [{"index": 0, "delta": item, "finish_reason": None}]}
                for item in delta
            ]
            chunks.append({
                **chunks[-1],
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if is_first else "stop"}],
            })
            stream = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            return httpx2.Response(
                200, text=stream + "data: [DONE]\n\n",
                headers={"Content-Type": "text/event-stream"},
            )

        def create_test_model(**kwargs):
            return AgentChatDeepSeek(
                **kwargs, http_async_client=httpx2.AsyncClient(transport=httpx2.MockTransport(deepseek)),
                api_base="https://deepseek.test",
            )

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"DEEPSEEK_API_KEY": "offline-test-key", "DEEPSEEK_MODEL": "deepseek-flash"}
        ), patch("my_ai_agent.LLM_init.deepseek_init.AgentChatDeepSeek", side_effect=create_test_model):
            settings = Settings(_env_file=None, data_dir=Path(directory), cookie_secure=False)
            with TestClient(create_app(settings)) as client:
                client.app.state.auth.set_password("tester", PASSWORD, create=True)
                login = client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                conversation = client.post("/api/conversations", headers=headers).json()["id"]
                path = f"/api/conversations/{conversation}/runs"

                invalid = client.post(path, headers=headers, json={"content": "hi", "reasoning_effort": "medium"})
                self.assertEqual(invalid.status_code, 422)
                for effort in ("max", "low", "none", "high"):
                    response = client.post(path, headers=headers, json={"content": "multiply", "reasoning_effort": effort})
                    output = events(response)
                    self.assertEqual(output[-1]["type"], "run.completed", response.text)
                    self.assertEqual("".join(x["text"] for x in output if x["type"] == "message.delta"), "最终回答")
                    thinking = "".join(x["text"] for x in output if x["type"] == "reasoning.delta")
                    expected = {"max": "第一段推理\n\n第一段推理", "none": ""}
                    self.assertEqual(thinking, expected.get(effort, "第一段推理"))
                    reply = client.get(f"/api/conversations/{conversation}").json()["messages"][-1]
                    self.assertEqual(reply["reasoning"], thinking or None)
                    self.assertEqual(reply["content"], "最终回答")

        self.assertEqual([request["reasoning_effort"] for request in requests], ["max", "max", "low", "none", "high"])
        self.assertEqual(requests[1]["messages"][-1]["role"], "tool")
        self.assertEqual(requests[1]["messages"][-1]["content"], "12.0")
        self.assertEqual(requests[1]["messages"][-2]["reasoning_content"], "第一段推理")
        assistants = [item for item in requests[-1]["messages"] if item["role"] == "assistant"]
        self.assertEqual([item["reasoning_content"] for item in assistants], ["第一段推理", "第一段推理", "第一段推理", ""])


if __name__ == "__main__":
    unittest.main()
