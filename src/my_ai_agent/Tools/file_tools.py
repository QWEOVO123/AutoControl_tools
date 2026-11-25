"""Small, bounded file operations with no external executable dependency."""

import os
from pathlib import Path, PurePosixPath

from langchain_core.tools import tool

from ._common import (
    IGNORED_DIRECTORIES, MAX_OUTPUT_CHARS, MAX_SCAN_FILES,
    check_limit, clip, is_sensitive, read_document, resolve_path, tool_errors,
)


def _matches(relative: str, pattern: str) -> bool:
    pattern = pattern.replace("\\", "/")
    target = PurePosixPath(relative)
    if "/" not in pattern:
        target = PurePosixPath(target.name)
    return target.full_match(pattern, case_sensitive=os.name != "nt")


def _files(root: Path, include_hidden: bool):
    if not root.is_dir():
        raise ValueError("path 必须是一个已存在的目录。")
    for directory, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name for name in directories
            if name.lower() not in IGNORED_DIRECTORIES
            and (include_hidden or not name.startswith("."))
            and not Path(directory, name).is_symlink()
        )
        for name in sorted(files):
            path = Path(directory, name)
            if path.is_symlink() or is_sensitive(path):
                continue
            if include_hidden or not name.startswith("."):
                yield path


@tool
@tool_errors
def list_directory(path: str = ".", limit: int = 100, include_hidden: bool = False) -> dict:
    """列出目录的直接子项，不递归。相对路径基于启动目录；limit 为 1..500。

    默认排除隐藏项、缓存、虚拟环境和凭据；include_hidden 可显示普通隐藏项。
    """
    check_limit(limit, "limit", 500)
    root = resolve_path(path)
    entries = []
    for item in sorted(root.iterdir(), key=lambda entry: entry.name.lower()):
        if is_sensitive(item) or item.name.lower() in IGNORED_DIRECTORIES:
            continue
        if not include_hidden and item.name.startswith("."):
            continue
        entries.append({"name": item.name, "type": "directory" if item.is_dir() else "file"})
        if len(entries) > limit:
            break
    return {"ok": True, "path": str(root), "entries": entries[:limit], "truncated": len(entries) > limit}


@tool
@tool_errors
def find_files(
    pattern: str = "*", path: str = ".", limit: int = 100, include_hidden: bool = False,
) -> dict:
    """递归按 glob 检索文件名，如 *.py、**/test_*.py、src/**/*.py。

    path 为搜索目录，limit 为 1..500；默认跳过隐藏项、缓存、凭据和符号链接。
    最多检查 10000 个文件；结果截断时应缩小目录或 pattern。
    """
    check_limit(limit, "limit", 500)
    root = resolve_path(path)
    matches = []
    for scanned, item in enumerate(_files(root, include_hidden), 1):
        if scanned > MAX_SCAN_FILES:
            return {"ok": True, "path": str(root), "files": matches, "truncated": True}
        relative = item.relative_to(root).as_posix()
        if _matches(relative, pattern):
            if len(matches) == limit:
                return {"ok": True, "path": str(root), "files": matches, "truncated": True}
            matches.append(relative)
    return {"ok": True, "path": str(root), "files": matches, "truncated": False}


@tool
@tool_errors
def search_text(
    pattern: str, path: str = ".", file_glob: str = "*", regex: bool = False,
    case_sensitive: bool = False, limit: int = 100, include_hidden: bool = False,
) -> dict:
    """递归搜索 UTF-8 文本，返回相对文件名、行号和匹配行预览。

    默认字面匹配且忽略大小写；regex=True 使用 Python 正则。file_glob 限定文件名。
    limit 为 1..200；跳过凭据、缓存、符号链接、二进制和超过 1 MiB 的文件。
    truncated=True 时应缩小范围；skipped_files 表示无法读取或被大小限制跳过的文件数。
    """
    import re

    check_limit(limit, "limit", 200)
    if not pattern:
        raise ValueError("pattern 不能为空。")
    try:
        expression = re.compile(pattern if regex else re.escape(pattern), 0 if case_sensitive else re.I)
    except re.error as exc:
        raise ValueError(f"无效正则表达式: {exc}") from exc
    root = resolve_path(path)
    matches = []
    skipped = 0
    output_size = 0
    truncated = False
    for scanned, item in enumerate(_files(root, include_hidden), 1):
        if scanned > MAX_SCAN_FILES:
            truncated = True
            break
        relative = item.relative_to(root).as_posix()
        if not _matches(relative, file_glob):
            continue
        try:
            text, _ = read_document(item)
        except (OSError, ValueError, UnicodeError):
            skipped += 1
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if expression.search(line):
                preview, shortened = clip(line, 500)
                if len(matches) == limit or output_size + len(relative) + len(preview) > MAX_OUTPUT_CHARS:
                    truncated = True
                    break
                matches.append({"path": relative, "line": number, "text": preview, "line_truncated": shortened})
                output_size += len(relative) + len(preview)
        if truncated:
            break
    return {"ok": True, "path": str(root), "matches": matches, "truncated": truncated, "skipped_files": skipped}


@tool
@tool_errors
def read_file(path: str, start_line: int = 1, max_lines: int = 200) -> dict:
    """分段读取 UTF-8 文件，返回带行号的文本。start_line 从 1 开始，max_lines 为 1..500。

    文件上限 1 MiB，输出上限 20000 字符；拒绝凭据、Git 内部文件和二进制。
    truncated=True 时可调小 max_lines；has_more 表示所选行段后还有内容。
    """
    check_limit(start_line, "start_line", 1_000_000)
    check_limit(max_lines, "max_lines", 500)
    target = resolve_path(path)
    text, _ = read_document(target)
    lines = text.splitlines()
    selected = lines[start_line - 1:start_line - 1 + max_lines]
    content, truncated = clip("\n".join(f"{number}: {line}" for number, line in enumerate(selected, start_line)))
    return {
        "ok": True, "path": str(target), "content": content, "total_lines": len(lines),
        "start_line": start_line, "has_more": start_line - 1 + len(selected) < len(lines),
        "truncated": truncated,
    }


@tool
@tool_errors
def write_file(path: str, content: str, overwrite: bool = False) -> dict:
    """创建 UTF-8 文本文件并自动创建父目录，默认拒绝覆盖；有意全量替换才传 overwrite=True。

    已存在文件的局部修改优先用 edit_file。内容上限 1 MiB，拒绝凭据和 Git 内部路径。
    """
    if len(content.encode("utf-8")) > 1024 * 1024:
        raise ValueError("写入内容超过 1 MiB。")
    target = resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w" if overwrite else "x", encoding="utf-8", newline="") as stream:
        stream.write(content)
    return {"ok": True, "path": str(target), "bytes_written": target.stat().st_size}


@tool
@tool_errors
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> dict:
    """精确替换已有 UTF-8 文件中的文本；先 read_file，再提供原样 old_text。

    默认 old_text 必须恰好匹配一次；明确批量替换才用 replace_all=True。
    按 LF 匹配，并保留原文件的 UTF-8 BOM 和 CRLF/LF 换行风格。
    """
    if not old_text:
        raise ValueError("old_text 不能为空。")
    target = resolve_path(path)
    original, has_bom = read_document(target)
    newline = "\r\n" if "\r\n" in original else "\n"
    normalized = original.replace("\r\n", "\n")
    old_text = old_text.replace("\r\n", "\n")
    new_text = new_text.replace("\r\n", "\n")
    count = normalized.count(old_text)
    if count == 0 or (count != 1 and not replace_all):
        raise ValueError(f"old_text 匹配到 {count} 处；请提供唯一上下文，或明确使用 replace_all。")
    updated = normalized.replace(old_text, new_text).replace("\n", newline)
    data = (b"\xef\xbb\xbf" if has_bom else b"") + updated.encode("utf-8")
    if len(data) > 1024 * 1024:
        raise ValueError("修改后文件超过 1 MiB。")
    target.write_bytes(data)
    return {"ok": True, "path": str(target), "replacements": count}
