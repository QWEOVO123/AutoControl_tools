import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
import httpx2
from fastapi.testclient import TestClient

from my_ai_agent.LLM_init.deepseek_init import AgentChatDeepSeek
from my_ai_agent.Tools import web_fetch, web_search
from my_ai_agent.web.app import create_app
from my_ai_agent.web.config import Settings
from my_ai_agent.web.models import Attachment


class WebToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_use_official_endpoints_and_bound_the_results(self):
        requests = []

        def upstream(request):
            requests.append((request.url.path, json.loads(request.content)))
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json={"results": [
                    {"title": "Official Docs", "summary": "Useful summary", "url": "https://example.org/docs"},
                ]})
            return httpx.Response(200, json={"title": "Official Docs", "content": "x" * 18000})

        sync_client, async_client = httpx.Client, httpx.AsyncClient
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "offline-test-key"}), patch(
            "my_ai_agent.Tools.web_tools.httpx.Client",
            side_effect=lambda **kwargs: sync_client(transport=httpx.MockTransport(upstream), **kwargs),
        ), patch(
            "my_ai_agent.Tools.web_tools.httpx.AsyncClient",
            side_effect=lambda **kwargs: async_client(transport=httpx.MockTransport(upstream), **kwargs),
        ):
            found = web_search.invoke({"query": " SDK documentation ", "count": 2})
            page = await web_fetch.ainvoke({"url": "https://example.org/docs#install"})
            rejected = await web_fetch.ainvoke({"url": "https://user:secret@example.org/docs"})
        self.assertEqual(requests, [
            ("/v1/tools/search", {"query": "SDK documentation", "count": 2}),
            ("/v1/tools/fetch", {"url": "https://example.org/docs"}),
        ])
        self.assertEqual(found["results"][0]["title"], "Official Docs")
        self.assertTrue(page["truncated"])
        self.assertEqual(len(page["content"]), 16000)
        self.assertFalse(rejected["ok"])


class AttachmentsIntegrationTests(unittest.TestCase):
    def test_attachment_ownership_replay_renewal_and_usage(self):
        file_requests = []
        chat_requests = []

        def file_api(request):
            file_requests.append(request)
            if request.method == "DELETE":
                return httpx.Response(200, json={"deleted": True})
            self.assertEqual(request.url.path, "/files")
            body = request.read()
            self.assertLess(body.index(b'name="purpose"'), body.index(b'name="file"'))
            self.assertIn(b"rich_layout_recognition", body)
            self.assertIn(b'expires_after[seconds]', body)
            return httpx.Response(200, json={
                "id": f"file-api-record-{len(file_requests)}", "expires_at": int(time.time()) + 86400,
            })

        def model_api(request):
            if request.url.path == "/models":
                return httpx2.Response(200, json={"data": [{"id": "deepseek-flash", "context_window": 1048576}]})
            payload = json.loads(request.content)
            chat_requests.append(payload)
            wants_json = payload.get("response_format") == {"type": "json_object"}
            prompt = payload["messages"][-1]["content"]
            content = ('{"status":"ok"}' if prompt != "empty JSON" else " ") if wants_json else "已读取附件"
            base = {"id": "mock-id", "object": "chat.completion.chunk", "created": 123, "model": "deepseek-flash"}
            chunks = [
                {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {**base, "choices": [], "usage": {
                    "prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25,
                    "prompt_cache_hit_tokens": 12, "prompt_cache_miss_tokens": 8,
                }},
            ]
            stream = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            return httpx2.Response(200, text=stream + "data: [DONE]\n\n", headers={"Content-Type": "text/event-stream"})

        def test_model(**kwargs):
            return AgentChatDeepSeek(
                **kwargs, api_base="https://deepseek.test",
                http_client=httpx2.Client(transport=httpx2.MockTransport(model_api)),
                http_async_client=httpx2.AsyncClient(transport=httpx2.MockTransport(model_api)),
            )

        file_http = SimpleNamespace(
            AsyncClient=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(file_api), **kwargs),
            Timeout=httpx.Timeout,
            HTTPError=httpx.HTTPError,
        )
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            "os.environ", {"DEEPSEEK_API_KEY": "offline-test-key", "DEEPSEEK_MODEL": "deepseek-flash"}
        ), patch(
            "my_ai_agent.web.services.attachments.httpx", file_http,
        ), patch("my_ai_agent.LLM_init.deepseek_init.AgentChatDeepSeek", side_effect=test_model):
            settings = Settings(_env_file=None, data_dir=Path(folder), cookie_secure=False)
            with TestClient(create_app(settings)) as client:
                for username in ("tester", "other"):
                    client.app.state.auth.set_password(username, "temporary-testing-password", create=True)

                def login(username):
                    response = client.post("/api/auth/login", json={
                        "username": username, "password": "temporary-testing-password",
                    })
                    return {"X-CSRF-Token": response.json()["csrf_token"]}

                headers = login("tester")
                conversation = client.post("/api/conversations", headers=headers).json()["id"]
                path = f"/api/conversations/{conversation}"
                forged = client.post(path + "/attachments", headers=headers, files={
                    "files": ("fake.png", b"<html>", "image/png"),
                })
                self.assertEqual(forged.status_code, 415)
                staged = client.post(path + "/attachments", headers=headers, data={"rich": "true"}, files={
                    "files": ("report.pdf", b"%PDF-mock", "application/pdf"),
                })
                self.assertEqual(staged.status_code, 201, staged.text)
                attachment = staged.json()[0]
                self.assertNotIn("remote_id", attachment)
                self.assertFalse(file_requests)
                download = path + f"/attachments/{attachment['id']}"
                self.assertEqual(client.get(download).content, b"%PDF-mock")

                other_headers = login("other")
                other = client.post("/api/conversations", headers=other_headers).json()["id"]
                self.assertEqual(client.get(download).status_code, 404)
                denied = client.post(f"/api/conversations/{other}/runs", headers=other_headers, json={
                    "attachment_ids": [attachment["id"]],
                })
                self.assertEqual(denied.status_code, 404)
                self.assertFalse(file_requests)
                self.assertFalse(chat_requests)

                headers = login("tester")
                initial = client.post(path + "/runs", headers=headers, json={
                    "content": "分析报告", "attachment_ids": [attachment["id"]],
                })
                self.assertIn("attachment.preparing", initial.text)
                self.assertIn("usage.completed", initial.text)
                self.assertIn("run.completed", initial.text)
                self.assertEqual(chat_requests[0]["messages"][-1]["content"][0], {
                    "type": "file", "file_id": "file-api-record-1",
                })
                detail = client.get(path).json()["messages"]
                self.assertEqual(detail[0]["attachments"], [attachment])
                self.assertEqual(detail[1]["usage"], {
                    "input_tokens": 20, "output_tokens": 5, "cache_read_tokens": 12,
                })
                followup = client.post(path + "/runs", headers=headers, json={"content": "继续"})
                self.assertIn("run.completed", followup.text)
                self.assertEqual(len(file_requests), 1)
                self.assertIn("file-api-record-1", json.dumps(chat_requests[-1]["messages"]))

                with client.app.state.database.session() as db:
                    db.get(Attachment, attachment["id"]).expires_at = 0
                renewal = client.post(path + "/runs", headers=headers, json={"content": "再看一次"})
                self.assertIn("run.completed", renewal.text)
                self.assertEqual(len(file_requests), 2)
                self.assertIn("file-api-record-2", json.dumps(chat_requests[-1]["messages"]))
                self.assertNotIn("file-api-record-1", json.dumps(chat_requests[-1]["messages"]))

                json_run = client.post(path + "/runs", headers=headers, json={
                    "content": "返回状态", "output_mode": "json",
                })
                self.assertIn("run.completed", json_run.text)
                self.assertEqual(chat_requests[-1]["response_format"], {"type": "json_object"})
                self.assertIn("JSON", chat_requests[-1]["messages"][0]["content"])
                self.assertEqual(json.loads(client.get(path).json()["messages"][-1]["content"]), {"status": "ok"})
                invalid_json = client.post(path + "/runs", headers=headers, json={
                    "content": "empty JSON", "output_mode": "json",
                })
                self.assertIn("run.failed", invalid_json.text)
                self.assertEqual(client.get(path).json()["messages"][-1]["content"], "")

                self.assertEqual(client.delete(path, headers=headers).status_code, 200)
                self.assertEqual(client.get(download).status_code, 404)
                self.assertFalse((Path(folder) / "attachments" / attachment["id"]).exists())
                self.assertEqual(file_requests[-1].url.path, "/files/file-api-record-2")


class MediaTests(unittest.TestCase):
    def test_media_uses_authenticated_routes_and_correct_deepseek_wire_formats(self):
        seen = []

        def upstream(request):
            seen.append(request.url.path)
            self.assertEqual(request.headers["authorization"], "Bearer offline-test-key")
            if request.url.path.endswith("/ocr"):
                self.assertIn(b'rich_layout_recognition', request.read())
                return httpx.Response(200, json={"pages": [
                    {"index": 0, "text": "ERROR: timeout", "finish_reason": "length"},
                ]})
            if request.url.path.endswith("/asr"):
                self.assertIn(b'recording.ogg', request.read())
                return httpx.Response(200, json={"text": "重启服务", "duration_ms": 1000})
            self.assertEqual(json.loads(request.content), {
                "text": "回答", "voice_id": "stella", "format": "wav", "filter_markdown": True,
            })
            return httpx.Response(200, content=b"RIFFmockWAVE", headers={"Content-Type": "audio/wav"})

        media_http = SimpleNamespace(
            AsyncClient=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(upstream), **kwargs),
            Timeout=httpx.Timeout, HTTPError=httpx.HTTPError, TimeoutException=httpx.TimeoutException,
        )
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            "os.environ", {"DEEPSEEK_API_KEY": "offline-test-key"},
        ), patch("my_ai_agent.web.api.media.httpx", media_http):
            settings = Settings(_env_file=None, data_dir=Path(folder), cookie_secure=False)
            with TestClient(create_app(settings)) as client:
                self.assertEqual(client.post("/api/media/speech", json={"text": "回答"}).status_code, 401)
                client.app.state.auth.set_password("operator", "temporary-testing-password", create=True)
                login = client.post("/api/auth/login", json={
                    "username": "operator", "password": "temporary-testing-password",
                })
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                invalid = client.post("/api/media/transcribe", headers=headers, files={
                    "file": ("capture.webm", b"invalid"),
                })
                self.assertEqual(invalid.status_code, 415)
                ocr = client.post("/api/media/ocr", headers=headers, data={"layout": "true"}, files={
                    "file": ("screen.png", b"\x89PNG\r\n\x1a\nfixture", "image/png"),
                })
                self.assertEqual(ocr.status_code, 200, ocr.text)
                self.assertEqual(ocr.json()["pages"], [{"index": 0, "text": "ERROR: timeout", "truncated": True}])
                audio = client.post("/api/media/transcribe", headers=headers, files={
                    "file": ("recording.ogg", b"OggS\x00OpusHead", "audio/ogg"),
                })
                self.assertEqual(audio.json()["text"], "重启服务")
                spoken = client.post("/api/media/speech", headers=headers, json={"text": "回答"})
                self.assertEqual(spoken.headers["content-type"], "audio/wav")
                self.assertEqual(spoken.content, b"RIFFmockWAVE")
        self.assertEqual(seen, ["/v1/tools/ocr", "/v1/tools/asr", "/v1/tools/tts"])
