"""Shared limits, path checks, and recoverable errors for local tools."""

from functools import wraps
from pathlib import Path

MAX_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_CHARS = 20_000
MAX_SCAN_FILES = 10_000
IGNORED_DIRECTORIES = {
    ".git", ".venv", "venv", "__pycache__", ".idea", ".vscode",
    ".ruff_cache", ".pytest_cache", ".mypy_cache", "node_modules",
    "dist", "build", "secrets",
}


def tool_errors(function):
    """Return expected local failures to the model so it can adjust its call."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, ValueError, UnicodeError) as exc:
            return {"ok": False, "error": str(exc)}

    return wrapped


def is_sensitive(path: Path) -> bool:
    return (
        (path.name.lower().startswith(".env") and path.name != ".env.example")
        or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
        or any(part.lower() in {".git", "secrets"} for part in path.parts)
    )


def resolve_path(path: str) -> Path:
    result = Path(path).expanduser().resolve()
    if is_sensitive(result):
        raise ValueError("该路径包含凭据文件或 Git 内部数据，专用文件工具不访问此路径。")
    return result


def check_limit(value: int, name: str, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} 必须在 1 到 {maximum} 之间。")


def read_document(path: Path) -> tuple[str, bool]:
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("文件超过 1 MiB，请通过 Shell 按需提取指定范围，避免读取整个文件。")
    if b"\x00" in data:
        raise ValueError("不支持读取二进制文件。")
    return data.decode("utf-8-sig"), data.startswith(b"\xef\xbb\xbf")


def clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    return text[:limit], len(text) > limit
