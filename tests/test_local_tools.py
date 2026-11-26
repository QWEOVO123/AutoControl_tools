import base64
from contextlib import redirect_stdout
from io import StringIO
import os
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage

from my_ai_agent.Agents import core
from my_ai_agent.Tools import TOOLS
from my_ai_agent.Tools.file_tools import (
    edit_file, find_files, list_directory, read_file, search_text, write_file,
)
from my_ai_agent.Tools.shell_tools import execute_shell


def python_command(source):
    payload = base64.b64encode(source.encode()).decode()
    loader = f'import base64; exec(base64.b64decode("{payload}"))'
    if os.name == "nt":
        executable = sys.executable.replace("'", "''")
        return f"& '{executable}' -c '{loader}'"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(loader)}"


class FileToolsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agent tools 中文 ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "nested").mkdir()
        (self.root / "nested" / "demo.py").write_text("Alpha\nhello 中文\nalpha\n", encoding="utf-8")
        (self.root / "root.py").write_text("print('root')\n", encoding="utf-8")
        (self.root / ".env").write_text("DO_NOT_READ=private-value", encoding="utf-8")
        (self.root / ".env.example").write_text("EXAMPLE=", encoding="utf-8")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "ignored.py").write_text("Alpha", encoding="utf-8")

    def test_glob_listing_and_secret_exclusion(self):
        result = find_files.invoke({"path": str(self.root), "pattern": "**/*.py"})
        self.assertEqual(set(result["files"]), {"root.py", "nested/demo.py"})
        hidden = find_files.invoke({"path": str(self.root), "include_hidden": True})
        self.assertIn(".env.example", hidden["files"])
        self.assertNotIn(".env", hidden["files"])
        listing = list_directory.invoke({"path": str(self.root)})
        self.assertEqual({item["name"] for item in listing["entries"]}, {"root.py", "nested"})
        limited = find_files.invoke({"path": str(self.root), "pattern": "*.py", "limit": 1})
        self.assertTrue(limited["truncated"])

    def test_literal_regex_search_and_line_numbers(self):
        args = {"path": str(self.root), "pattern": "alpha", "file_glob": "*.py"}
        result = search_text.invoke(args)
        self.assertEqual([item["line"] for item in result["matches"]], [1, 3])
        result = search_text.invoke({**args, "case_sensitive": True})
        self.assertEqual([item["line"] for item in result["matches"]], [3])
        result = search_text.invoke({**args, "pattern": "^hello", "regex": True})
        self.assertEqual(result["matches"][0]["text"], "hello 中文")
        result = search_text.invoke({**args, "pattern": "[", "regex": True})
        self.assertFalse(result["ok"])
        result = search_text.invoke({**args, "pattern": "["})
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"], [])
        result = search_text.invoke({**args, "limit": 1})
        self.assertTrue(result["truncated"])

    def test_paged_read_and_invalid_files(self):
        result = read_file.invoke({"path": str(self.root / "nested/demo.py"), "start_line": 2, "max_lines": 1})
        self.assertEqual(result["content"], "2: hello 中文")
        self.assertTrue(result["has_more"])
        self.assertFalse(read_file.invoke({"path": str(self.root / ".env")})["ok"])
        self.assertFalse(write_file.invoke({"path": str(self.root / ".env"), "content": "bad"})["ok"])
        self.assertFalse(read_file.invoke({"path": str(self.root / "missing")})["ok"])
        self.assertFalse(read_file.invoke({"path": str(self.root / "root.py"), "start_line": 0})["ok"])
        binary = self.root / "binary.bin"
        binary.write_bytes(b"binary\x00data")
        self.assertFalse(read_file.invoke({"path": str(binary)})["ok"])
        binary.write_bytes(b"x" * (1024 * 1024 + 1))
        self.assertFalse(read_file.invoke({"path": str(binary)})["ok"])

    def test_create_guarded_overwrite_and_exact_edit(self):
        path = self.root / "new folder" / "new.txt"
        self.assertTrue(write_file.invoke({"path": str(path), "content": "same\nsame\n"})["ok"])
        self.assertFalse(write_file.invoke({"path": str(path), "content": "lost"})["ok"])
        self.assertEqual(path.read_text(), "same\nsame\n")
        self.assertFalse(edit_file.invoke({"path": str(path), "old_text": "same", "new_text": "changed"})["ok"])
        result = edit_file.invoke({"path": str(path), "old_text": "same", "new_text": "changed", "replace_all": True})
        self.assertEqual(result["replacements"], 2)
        self.assertEqual(path.read_text(), "changed\nchanged\n")
        self.assertTrue(write_file.invoke({"path": str(path), "content": "replacement", "overwrite": True})["ok"])

    def test_edit_preserves_bom_and_windows_newlines(self):
        path = self.root / "crlf.txt"
        path.write_bytes(b"\xef\xbb\xbffirst\r\nsecond\r\n")
        result = edit_file.invoke({"path": str(path), "old_text": "first\nsecond", "new_text": "new\nsecond"})
        self.assertTrue(result["ok"])
        self.assertEqual(path.read_bytes(), b"\xef\xbb\xbfnew\r\nsecond\r\n")

    def test_long_output_is_flagged(self):
        path = self.root / "long.txt"
        path.write_text("x" * 30000, encoding="utf-8")
        result = read_file.invoke({"path": str(path)})
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["content"]), 20000)


class ShellToolsTests(unittest.TestCase):
    def test_unicode_workdir_stdout_stderr_and_exit_code(self):
        with tempfile.TemporaryDirectory(prefix="agent shell 中文 ") as directory:
            code = "import os,sys; print(os.getcwd()); print('中文输出'); print('stderr-marker', file=sys.stderr); sys.exit(7)"
            result = execute_shell.invoke({"command": python_command(code), "workdir": directory})
            self.assertEqual(result["exit_code"], 7, result)
            self.assertFalse(result["ok"])
            self.assertIn("中文输出", result["stdout"])
            self.assertIn(directory, result["stdout"])
            self.assertIn("stderr-marker", result["stderr"])

    def test_output_limit_and_validation(self):
        result = execute_shell.invoke({"command": python_command("print('x' * 10000)"), "max_output_chars": 100})
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["stdout"]), 100)
        self.assertFalse(execute_shell.invoke({"command": "", "timeout_seconds": 1})["ok"])
        self.assertFalse(execute_shell.invoke({"command": "echo test", "timeout_seconds": 0})["ok"])

    def test_timeout(self):
        result = execute_shell.invoke({"command": python_command("import time; print('started', flush=True); time.sleep(30)"), "timeout_seconds": 2})
        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertIn("started", result["stdout"])

    @unittest.skipUnless(os.name == "nt", "Windows process tree cleanup")
    def test_timeout_stops_child_process(self):
        code = "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(child.pid, flush=True); time.sleep(30)"
        result = execute_shell.invoke({"command": python_command(code), "timeout_seconds": 2})
        self.assertTrue(result["timed_out"])
        pid = int(result["stdout"].strip())
        processes = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace", check=True,
        ).stdout
        self.assertNotIn(f'"{pid}"', processes)


class AgentIntegrationTests(unittest.TestCase):
    def test_registered_tools_complete_real_agent_tool_cycle(self):
        class ToolCallingModel(GenericFakeChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        with tempfile.TemporaryDirectory(prefix="agent integration ") as directory:
            path = Path(directory) / "example.txt"
            path.write_text("verified tool content", encoding="utf-8")
            model = ToolCallingModel(messages=iter([
                AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": str(path)}, "id": "read-test"}]),
                AIMessage(content="done"),
            ]))
            with patch.object(core, "LLM_init", return_value=model), redirect_stdout(StringIO()):
                agent = core.init_agent()
                result = agent.invoke({"messages": [{"role": "user", "content": "read the file"}]}, config={"configurable": {"thread_id": "test"}})
        self.assertEqual(result["messages"][-1].content, "done")
        tool_message = next(message for message in result["messages"] if isinstance(message, ToolMessage))
        output = json.loads(tool_message.content)
        self.assertTrue(output["ok"])
        self.assertEqual(output["content"], "1: verified tool content")
        self.assertEqual(len({tool.name for tool in TOOLS}), len(TOOLS))


if __name__ == "__main__":
    unittest.main()
