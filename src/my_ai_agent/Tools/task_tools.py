"""LangChain tools for background commands, Python scripts, and timed waits."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from langchain.tools import ToolRuntime
from langchain_core.tools import StructuredTool, tool

from ._common import MAX_FILE_BYTES, check_limit, tool_errors
from .jobs import JOBS, validate_seconds
from .shell_tools import _shell_command, _working_directory


def _owner(runtime: ToolRuntime):
    thread_id = runtime.config.get("configurable", {}).get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("后台任务需要有效的 Agent 会话。")
    return thread_id


@tool
@tool_errors
def job_start(
    command: str, runtime: ToolRuntime, workdir: str = ".", timeout_seconds: float | None = None,
) -> dict:
    """启动后台 Shell 任务并立即返回 job_id，随后用 job_output 获取状态与输出。

    Windows 使用 PowerShell，其他系统使用 /bin/sh。timeout_seconds 是从启动计时的
    任意正秒数（支持小数），null 表示无任务超时。进程不接受交互输入。
    保留 job_id；若要提前结束，调用 job_cancel。只可访问当前会话的任务。
    """
    job = JOBS.start(_owner(runtime), _shell_command(command), _working_directory(workdir), timeout_seconds)
    return {"ok": True, "job_id": job.id, "timeout_seconds": timeout_seconds, "workdir": str(job.workdir)}


def _job_for_output(runtime, job_id, stdout_offset, stderr_offset, max_output_chars, wait_seconds):
    check_limit(max_output_chars, "max_output_chars", 16000)
    validate_seconds(wait_seconds)
    if min(stdout_offset, stderr_offset) < 0:
        raise ValueError("输出游标不能为负数。")
    return JOBS.get(_owner(runtime), job_id)


async def _wait_for_job(job, wait_seconds=None):
    deadline = None if wait_seconds is None else time.monotonic() + wait_seconds
    while not job.done.is_set():
        remaining = 0.2 if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.2, remaining))


@tool_errors
def _job_output(
    job_id: str, runtime: ToolRuntime, stdout_offset: int = 0, stderr_offset: int = 0,
    max_output_chars: int = 8000, wait_seconds: float = 0,
) -> dict:
    """查询后台任务的状态、退出码和 stdout/stderr，可分页读取运行中或已结束任务。

    wait_seconds 是本次最多等待任务结束的时间，默认 0 立即返回，不改变任务自身超时。
    stdout_offset 和 stderr_offset 分别传上次对应的 next_offset，从 0 开始。
    has_more 表示还有已缓冲的输出；dropped_chars 表示较早输出已被滚动缓冲淘汰。
    """
    job = _job_for_output(runtime, job_id, stdout_offset, stderr_offset, max_output_chars, wait_seconds)
    deadline = time.monotonic() + wait_seconds
    while (remaining := deadline - time.monotonic()) > 0:
        if job.done.wait(min(remaining, 86400)):
            break
    return job.snapshot(stdout_offset, stderr_offset, max_output_chars)


async def _ajob_output(
    job_id: str, runtime: ToolRuntime, stdout_offset: int = 0, stderr_offset: int = 0,
    max_output_chars: int = 8000, wait_seconds: float = 0,
) -> dict:
    try:
        job = _job_for_output(runtime, job_id, stdout_offset, stderr_offset, max_output_chars, wait_seconds)
        await _wait_for_job(job, wait_seconds)
        return job.snapshot(stdout_offset, stderr_offset, max_output_chars)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


job_output = StructuredTool.from_function(_job_output, coroutine=_ajob_output, name="job_output")


@tool
@tool_errors
def job_cancel(job_id: str, runtime: ToolRuntime) -> dict:
    """请求停止当前会话的后台任务，随后用 job_output 确认最终状态和已生成的输出。"""
    job = JOBS.get(_owner(runtime), job_id)
    job.cancel.set()
    return {"ok": True, "job_id": job_id, "cancel_requested": not job.done.is_set()}


def _python_job(code, runtime, workdir, args, timeout_seconds, background):
    if not code.strip():
        raise ValueError("code 不能为空。")
    source = code.encode("utf-8")
    if len(source) > MAX_FILE_BYTES:
        raise ValueError("Python 脚本超过 1 MiB。")
    if timeout_seconds is None and not background:
        raise ValueError("无超时的 Python 任务请设置 background=true，再用 job_output 查询。")
    owner = _owner(runtime)
    directory = _working_directory(workdir)
    script_dir = TemporaryDirectory(prefix="my-ai-agent-python-")
    try:
        script = Path(script_dir.name, "agent_script.py")
        script.write_bytes(source)
        return JOBS.start(
            owner, [sys.executable, "-u", str(script), *(args or [])],
            directory, timeout_seconds, script_dir,
        )
    except BaseException:
        script_dir.cleanup()
        raise


@tool_errors
def _execute_python(
    code: str, runtime: ToolRuntime, workdir: str = ".", arguments: list[str] | None = None,
    timeout_seconds: float | None = 30, background: bool = False,
) -> dict:
    """创建临时 Python 脚本，用当前项目的解释器执行，返回退出码和输出。

    code 是完整 Python 源码，arguments 可传入 sys.argv。可用于批量计算、数据处理和自定义算法。
    默认等待完成。耗时任务设 background=true 后通过 job_output 获取状态和输出，支持 null 超时。
    stdout/stderr 可通过 job_id 续读。脚本在结束后清理，执行权限与当前应用相同。
    """
    job = _python_job(code, runtime, workdir, arguments, timeout_seconds, background)
    if not background:
        job.done.wait()
    return job.snapshot()


async def _aexecute_python(
    code: str, runtime: ToolRuntime, workdir: str = ".", arguments: list[str] | None = None,
    timeout_seconds: float | None = 30, background: bool = False,
) -> dict:
    try:
        job = _python_job(code, runtime, workdir, arguments, timeout_seconds, background)
        if not background:
            try:
                await _wait_for_job(job)
            except asyncio.CancelledError:
                job.cancel.set()
                raise
        return job.snapshot()
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


execute_python = StructuredTool.from_function(_execute_python, coroutine=_aexecute_python, name="execute_python")


def _sleep_result(seconds, context, started_at, started):
    return {
        "ok": True, "status": "awakened",
        "requested_seconds": seconds,
        "slept_seconds": round(time.monotonic() - started, 3),
        "started_at": started_at.isoformat(),
        "woke_at": datetime.now(timezone.utc).isoformat(),
        "context": context,
    }


@tool_errors
def _sleep(seconds: float, context: str = "") -> dict:
    """暂停当前 Agent 任务，定时器到期后自动继续，并带回等待前保存的上下文。

    seconds 支持小数。context 写入等待原因、任务 ID 和醒来后的下一步。
    等待时间和实际唤醒时间会随结果返回；Web 上可通过停止生成取消等待。
    """
    validate_seconds(seconds)
    started_at, started = datetime.now(timezone.utc), time.monotonic()
    remaining = seconds
    while remaining > 0:
        time.sleep(min(remaining, 86400))
        remaining = seconds - (time.monotonic() - started)
    return _sleep_result(seconds, context, started_at, started)


async def _asleep(seconds: float, context: str = "") -> dict:
    try:
        validate_seconds(seconds)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    started_at, started = datetime.now(timezone.utc), time.monotonic()
    await asyncio.sleep(seconds)
    return _sleep_result(seconds, context, started_at, started)


sleep = StructuredTool.from_function(_sleep, coroutine=_asleep, name="sleep")
