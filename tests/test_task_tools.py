import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from langchain.agents import create_agent
from langchain.tools import ToolRuntime
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver

from my_ai_agent.Tools import execute_python, job_cancel, job_output, job_start, math_compute, sleep
from my_ai_agent.Tools.jobs import JOBS
from test_local_tools import python_command


def runtime_for(thread_id):
    return ToolRuntime(
        state={}, context=None, config={"configurable": {"thread_id": thread_id}},
        stream_writer=lambda _: None, tool_call_id=None, store=None,
    )


class TaskToolsTests(unittest.TestCase):
    def setUp(self):
        self.thread_id = uuid4().hex
        self.runtime = runtime_for(self.thread_id)
        self.addCleanup(JOBS.close, self.thread_id)

    def call(self, tool, **parameters):
        return tool.invoke({"runtime": self.runtime, **parameters})

    def test_background_shell_pages_output_and_checks_ownership(self):
        job = self.call(job_start, command=python_command(
            "import sys; print('你好世界123'); print('warning', file=sys.stderr); sys.exit(7)"
        ), timeout_seconds=None)
        job_id = job["job_id"]
        denied = job_output.invoke({"runtime": runtime_for("different-thread"), "job_id": job_id})
        self.assertFalse(denied["ok"])
        first = self.call(job_output, job_id=job_id, wait_seconds=8, max_output_chars=3)
        self.assertEqual((first["status"], first["exit_code"]), ("failed", 7), first)
        self.assertEqual(first["stdout"]["text"], "你好世")
        self.assertTrue(first["stdout"]["has_more"])
        self.assertEqual(first["stderr"]["text"], "war")
        rest = self.call(job_output, job_id=job_id, stdout_offset=first["stdout"]["next_offset"],
                         stderr_offset=first["stderr"]["next_offset"])
        self.assertEqual(rest["stdout"]["text"].strip(), "界123")
        self.assertEqual(rest["stderr"]["text"].strip(), "ning")

    def test_python_executes_with_arguments_and_cleans_temporary_script(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.call(
                execute_python, code="import sys; print(sys.argv[1]); print(__file__)",
                workdir=directory, arguments=["含 空格"],
            )
        self.assertEqual(result["status"], "completed", result)
        lines = result["stdout"]["text"].splitlines()
        self.assertEqual(lines[0], "含 空格")
        self.assertFalse(Path(lines[1]).exists())

    def test_python_timeout_retains_output_and_job_can_be_cancelled(self):
        slow = "import time; print('started'); time.sleep(60)"
        timed_out = self.call(execute_python, code=slow, timeout_seconds=1.25)
        self.assertEqual(timed_out["status"], "timed_out", timed_out)
        self.assertIn("started", timed_out["stdout"]["text"])
        background = self.call(execute_python, code=slow, background=True, timeout_seconds=600)
        job_id = background["job_id"]
        self.assertEqual(self.call(job_output, job_id=job_id, wait_seconds=0.01)["status"], "running")
        self.assertTrue(self.call(job_cancel, job_id=job_id)["cancel_requested"])
        self.assertEqual(self.call(job_output, job_id=job_id, wait_seconds=8)["status"], "cancelled")

    def test_math_operations_and_tool_schemas(self):
        for name, arguments, expected in (
            ("sum", [[2**60, 1]], 2**60 + 1),
            ("pow", [2, 20, 17], 16),
            ("mod_inverse", [3, 11], 4),
            ("fraction", ["0.125"], {"numerator": 1, "denominator": 8}),
            ("prime_factors", [360], [2, 2, 2, 3, 3, 5]),
            ("bit_xor", [12, 10], 6),
            ("solve_linear", [[[2, 1], [1, 3]], [5, 5]], [2, 1]),
            ("matrix_multiply", [[[1, 2]], [[4], [5]]], [[14]]),
        ):
            with self.subTest(name=name):
                self.assertEqual(math_compute.invoke({"operation": name, "arguments": arguments}),
                                 {"ok": True, "result": expected})
        self.assertFalse(math_compute.invoke({"operation": "divide", "arguments": [1, 0]})["ok"])
        schema = convert_to_openai_tool(execute_python)["function"]["parameters"]["properties"]
        self.assertIn("arguments", schema)
        self.assertNotIn("runtime", schema)


class AsyncTaskToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_resumes_with_sleep_context_and_runs_python(self):
        class ToolCallingModel(GenericFakeChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        model = ToolCallingModel(messages=iter([
            AIMessage(content="", tool_calls=[{
                "name": "sleep", "args": {"seconds": 0.03, "context": "醒来后计算"},
                "id": "sleep-test",
            }]),
            AIMessage(content="", tool_calls=[{
                "name": "execute_python", "args": {"code": "print(sum(range(5)))"},
                "id": "python-test",
            }]),
            AIMessage(content="done"),
        ]))
        thread_id = uuid4().hex
        self.addCleanup(JOBS.close, thread_id)
        agent = create_agent(model, tools=[sleep, execute_python], checkpointer=InMemorySaver())
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "wait and compute"}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        woke, calculated = [
            json.loads(message.content) for message in result["messages"] if isinstance(message, ToolMessage)
        ]
        self.assertEqual(woke["status"], "awakened")
        self.assertGreaterEqual(woke["slept_seconds"], 0.03)
        self.assertEqual(woke["context"], "醒来后计算")
        self.assertIn("woke_at", woke)
        self.assertEqual(calculated["stdout"]["text"].strip(), "10")

    async def test_wait_can_be_cancelled(self):
        task = asyncio.create_task(sleep.ainvoke({"seconds": 60}))
        await asyncio.sleep(0.01)
        self.assertFalse(task.done())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
