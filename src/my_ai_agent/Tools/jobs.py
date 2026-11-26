"""Process-local jobs with bounded output and conversation ownership."""

import atexit
import codecs
from dataclasses import dataclass, field
import math
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
import time
from typing import BinaryIO
from uuid import uuid4

from .shell_tools import _process_options, _stop_process_tree

OUTPUT_LIMIT = 256_000
ACTIVE_LIMIT = 16
RETAINED_LIMIT = 64
RETENTION_SECONDS = 3600


def validate_seconds(value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError("时间必须是非负的有限秒数。")


@dataclass
class OutputBuffer:
    text: str = ""
    dropped: int = 0

    def append(self, text: str):
        self.text += text
        excess = len(self.text) - OUTPUT_LIMIT
        if excess > 0:
            self.dropped += excess
            self.text = self.text[excess:]

    def read(self, offset: int, size: int) -> dict:
        end = self.dropped + len(self.text)
        if not 0 <= offset <= end:
            raise ValueError("输出游标超出范围，请使用上次返回的 next_offset。")
        start = max(offset, self.dropped)
        text = self.text[start - self.dropped:start - self.dropped + size]
        return {
            "text": text,
            "next_offset": start + len(text),
            "has_more": start + len(text) < end,
            "dropped_chars": start - offset,
        }


@dataclass
class Job:
    id: str
    owner: str
    process: subprocess.Popen
    workdir: Path
    timeout_seconds: float | None
    script_dir: TemporaryDirectory | None = None
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    status: str = "running"
    error: str | None = None
    output_incomplete: bool = False
    stdout: OutputBuffer = field(default_factory=OutputBuffer)
    stderr: OutputBuffer = field(default_factory=OutputBuffer)
    lock: Lock = field(default_factory=Lock)
    cancel: Event = field(default_factory=Event)
    done: Event = field(default_factory=Event)

    def _read(self, stream: BinaryIO, buffer: OutputBuffer):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            with stream:
                while data := stream.read1(8192):
                    with self.lock:
                        if self.finished is not None:
                            return
                        buffer.append(decoder.decode(data))
                with self.lock:
                    if self.finished is None:
                        buffer.append(decoder.decode(b"", final=True))
        except OSError:
            with self.lock:
                self.output_incomplete = True

    def monitor(self):
        readers = [
            Thread(target=self._read, args=(stream, buffer), daemon=True)
            for stream, buffer in ((self.process.stdout, self.stdout), (self.process.stderr, self.stderr))
        ]
        status = "failed"
        try:
            for reader in readers:
                reader.start()
            status = self._wait_for_process()
        except (OSError, RuntimeError) as exc:
            self.error = str(exc)
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
        finally:
            for reader in readers:
                if reader.ident is not None:
                    reader.join(timeout=1)
            if self.script_dir is not None:
                try:
                    self.script_dir.cleanup()
                except OSError:
                    pass
            with self.lock:
                self.output_incomplete |= any(reader.is_alive() for reader in readers)
                self.status = status
                self.finished = time.monotonic()
            self.done.set()

    def _wait_for_process(self):
        while self.process.poll() is None:
            if self.cancel.is_set():
                _stop_process_tree(self.process)
                return "cancelled"
            interval = 0.2
            if self.timeout_seconds is not None:
                remaining = self.timeout_seconds - (time.monotonic() - self.started)
                if remaining <= 0:
                    _stop_process_tree(self.process)
                    return "timed_out"
                interval = min(interval, remaining)
            self.cancel.wait(interval)
        return "completed" if self.process.returncode == 0 else "failed"

    def snapshot(self, stdout_offset=0, stderr_offset=0, limit=8000):
        with self.lock:
            elapsed = (self.finished if self.finished is not None else time.monotonic()) - self.started
            return {
                "ok": self.status in {"running", "completed"},
                "job_id": self.id,
                "status": self.status,
                "exit_code": self.process.returncode if self.finished is not None else None,
                "elapsed_seconds": round(elapsed, 3),
                "timeout_seconds": self.timeout_seconds,
                "workdir": str(self.workdir),
                "stdout": self.stdout.read(stdout_offset, limit),
                "stderr": self.stderr.read(stderr_offset, limit),
                "output_incomplete": self.output_incomplete,
                "error": self.error,
            }


class JobRegistry:
    def __init__(self):
        self.lock = Lock()
        self.jobs: dict[str, Job] = {}

    def start(self, owner, args, directory, timeout_seconds, script_dir=None):
        if timeout_seconds is not None:
            validate_seconds(timeout_seconds)
            if timeout_seconds == 0:
                raise ValueError("任务超时须大于 0，或设为 null 以持续运行。")
        with self.lock:
            self._prune(reserve_slot=True)
            if sum(not job.done.is_set() for job in self.jobs.values()) >= ACTIVE_LIMIT:
                raise ValueError("后台任务数量已达上限，请等待或取消已有任务。")
            process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_process_options(directory)
            )
            job = Job(uuid4().hex, owner, process, directory, timeout_seconds, script_dir)
            self.jobs[job.id] = job
            try:
                Thread(target=job.monitor, daemon=True).start()
            except RuntimeError:
                del self.jobs[job.id]
                _stop_process_tree(process)
                process.stdout.close()
                process.stderr.close()
                raise ValueError("后台任务线程无法启动。") from None
            return job

    def _prune(self, *, reserve_slot=False):
        deadline = time.monotonic() - RETENTION_SECONDS
        finished = sorted(
            (job for job in self.jobs.values() if job.finished is not None),
            key=lambda job: job.finished,
        )
        for job in finished:
            if job.finished < deadline or (reserve_slot and len(self.jobs) >= RETAINED_LIMIT):
                del self.jobs[job.id]

    def get(self, owner, job_id):
        with self.lock:
            self._prune()
            job = self.jobs.get(job_id)
            if job is None or job.owner != owner:
                raise ValueError("当前会话找不到此任务，任务可能已过期。")
            return job

    def close(self, owner=None):
        with self.lock:
            jobs = [job for job in self.jobs.values() if owner is None or job.owner == owner]
            for job in jobs:
                job.cancel.set()
                del self.jobs[job.id]
        deadline = time.monotonic() + 15
        for job in jobs:
            job.done.wait(max(0, deadline - time.monotonic()))


JOBS = JobRegistry()
atexit.register(JOBS.close)
