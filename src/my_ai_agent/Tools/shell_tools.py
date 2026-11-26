"""Foreground shell execution with bounded output and process-tree timeouts."""

import base64
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

from langchain_core.tools import tool

from ._common import check_limit, tool_errors


def _stop_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def _working_directory(workdir: str) -> Path:
    directory = Path(workdir).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("workdir 必须是已存在的目录。")
    return directory


def _process_options(directory: Path) -> dict:
    platform_options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if os.name == "nt" else {"start_new_session": True}
    )
    return {
        "cwd": directory,
        "env": {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        "stdin": subprocess.DEVNULL,
        **platform_options,
    }


def _shell_command(command: str) -> list[str]:
    if not command.strip():
        raise ValueError("command 不能为空。")
    if os.name != "nt":
        return ["/bin/sh", "-c", command]

    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise ValueError("找不到 PowerShell，请安装 PowerShell 或检查 PATH。")
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "$global:LASTEXITCODE = 0\n"
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
        "$OutputEncoding = [Console]::OutputEncoding\n"
        f"{command}\n"
        "exit $LASTEXITCODE\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


@tool
@tool_errors
def execute_shell(
    command: str, workdir: str = ".", timeout_seconds: int = 30, max_output_chars: int = 12000,
) -> dict:
    """在本机执行非交互 Shell 命令：Windows 使用 PowerShell，其它系统使用 /bin/sh。

    workdir 显式指定目录；每次为独立进程，cd 和变量不会延续。stdin 关闭，不支持交互或后台服务。
    timeout_seconds 为 1..120，超时终止进程树；max_output_chars 为 1..20000，分别限制 stdout/stderr。
    返回实际 Shell、目录、exit_code、stdout、stderr、timed_out、truncated；ok 仅在成功退出时为 True。
    Shell 拥有当前用户权限，并非沙箱；只执行已获用户授权的操作，不读取或打印密钥。
    """
    check_limit(timeout_seconds, "timeout_seconds", 120)
    check_limit(max_output_chars, "max_output_chars", 20000)
    directory = _working_directory(workdir)
    args = _shell_command(command)
    timed_out = False
    # Files avoid accumulating an unbounded command output in Python memory.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        with subprocess.Popen(
            args, stdout=stdout, stderr=stderr, **_process_options(directory),
        ) as process:
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop_process_tree(process)
            output = []
            truncated = False
            for stream in (stdout, stderr):
                stream.seek(0)
                value = stream.read(max_output_chars * 4 + 1).decode("utf-8", errors="replace")
                truncated = truncated or len(value) > max_output_chars
                output.append(value[:max_output_chars])
    return {
        "ok": process.returncode == 0 and not timed_out, "shell": args[0],
        "workdir": str(directory), "exit_code": process.returncode,
        "stdout": output[0], "stderr": output[1],
        "timed_out": timed_out, "truncated": truncated,
    }
