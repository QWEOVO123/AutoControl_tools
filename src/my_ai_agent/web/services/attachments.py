"""Conversation-owned uploads and renewable DeepSeek Files references."""

import asyncio
from pathlib import Path
import re
from threading import Lock
import time
from uuid import uuid4

from fastapi import HTTPException, UploadFile
import httpx
from sqlalchemy import or_, select

from ...deepseek_api import BASE_URL, DeepSeekError, api_headers, json_object
from ..models import Attachment
from ..schemas import attachment_output
from .conversations import ConversationService

MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_CONVERSATION_BYTES = 64 * 1024 * 1024
MAX_FILES_PER_MESSAGE = 4
MAX_CONVERSATION_FILES = 20
REMOTE_TTL = 7 * 86400

IMAGES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp",
}
DOCUMENTS = {
    ".pdf": "application/pdf", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
OTHER = {
    ".txt": "text/plain", ".md": "text/markdown", ".log": "text/plain",
    ".csv": "text/csv", ".json": "application/json", ".yaml": "text/yaml", ".yml": "text/yaml",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


def classify(upload: UploadFile, rich: bool) -> tuple[str, str, str]:
    name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(name).suffix.lower()
    if not name or len(name) > 180 or any(ord(char) < 32 for char in name):
        raise HTTPException(422, "附件名称无效。")
    if suffix in IMAGES:
        prefix = upload.file.read(12)
        upload.file.seek(0)
        detected = (
            "image/jpeg" if prefix.startswith(b"\xff\xd8\xff") else
            "image/png" if prefix.startswith(b"\x89PNG\r\n\x1a\n") else
            "image/gif" if prefix.startswith((b"GIF87a", b"GIF89a")) else
            "image/webp" if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP" else ""
        )
        if detected != IMAGES[suffix]:
            raise HTTPException(415, "图片内容与文件格式不符。")
        return name, detected, "user_data"
    if suffix in DOCUMENTS:
        purpose = "rich_layout_recognition" if rich else "text_recognition"
        return name, DOCUMENTS[suffix], purpose
    if suffix in OTHER:
        return name, OTHER[suffix], "user_data"
    raise HTTPException(415, "此文件类型不支持作为对话附件。")


class AttachmentService:
    def __init__(self, database, data_dir):
        self.database = database
        self.root = data_dir / "attachments"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = Lock()

    def stage(self, user_id, conversation_id, uploads: list[UploadFile], rich: bool):
        if not 1 <= len(uploads) <= MAX_FILES_PER_MESSAGE:
            raise HTTPException(422, "每条消息最多可添加 4 个附件。")
        paths = []
        expired_paths = []
        with self.lock:
            try:
                with self.database.session() as db:
                    ConversationService.owned(db, user_id, conversation_id)
                    rows = list(db.scalars(select(Attachment).where(Attachment.conversation_id == conversation_id)))
                    old_draft = time.time() - 3600
                    for row in rows[:]:
                        if row.message_id is None and row.created_at < old_draft:
                            db.delete(row)
                            rows.remove(row)
                            expired_paths.append(self.root / row.id)
                    total = sum(row.size for row in rows)
                    if len(rows) + len(uploads) > MAX_CONVERSATION_FILES:
                        raise HTTPException(413, "这个会话的附件数量已达上限，请新建会话。")
                    result = []
                    for upload in uploads:
                        name, media_type, purpose = classify(upload, rich)
                        item_id = str(uuid4())
                        path = self.root / item_id
                        paths.append(path)
                        size = 0
                        with path.open("xb") as target:
                            while chunk := upload.file.read(256 * 1024):
                                size += len(chunk)
                                if size > MAX_FILE_BYTES or total + size > MAX_CONVERSATION_BYTES:
                                    raise HTTPException(413, "附件限单个 12 MiB，每个会话合计 64 MiB。")
                                target.write(chunk)
                        if not size:
                            raise HTTPException(422, "附件不能为空。")
                        total += size
                        item = Attachment(
                            id=item_id, conversation_id=conversation_id, name=name, size=size,
                            media_type=media_type, purpose=purpose,
                        )
                        db.add(item)
                        result.append(attachment_output(item))
            except BaseException:
                for path in paths:
                    path.unlink(missing_ok=True)
                raise
            for path in expired_paths:
                path.unlink(missing_ok=True)
        return result

    def bind(self, db, conversation_id, message_id, attachment_ids):
        for item_id in attachment_ids:
            item = db.get(Attachment, item_id)
            if not item or item.conversation_id != conversation_id or item.message_id is not None:
                raise HTTPException(404, "无法使用这个附件，请重新添加。")
            item.message_id = message_id

    async def references(self, conversation_id, current_ids):
        with self.database.session() as db:
            rows = list(db.scalars(select(Attachment).where(
                Attachment.conversation_id == conversation_id,
                Attachment.message_id.is_not(None),
                or_(Attachment.remote_id.is_not(None), Attachment.id.in_(current_ids)),
            ).order_by(Attachment.created_at)))
        if not rows:
            return {}
        soon = time.time() + 300
        references = {item.id: item.remote_id for item in rows if item.remote_id and item.expires_at and item.expires_at > soon}
        pending = [item for item in rows if item.id not in references]
        if pending:
            limit = asyncio.Semaphore(3)
            async with httpx.AsyncClient(
                base_url=BASE_URL, headers=api_headers(), timeout=httpx.Timeout(250, connect=15),
            ) as client:
                async def upload(item):
                    async with limit:
                        return await self._upload(client, item)

                results = await asyncio.gather(*(upload(item) for item in pending), return_exceptions=True)
                for item, result in zip(pending, results, strict=True):
                    if isinstance(result, BaseException):
                        if isinstance(result, (DeepSeekError, httpx.HTTPError, OSError)):
                            raise DeepSeekError(f"附件「{item.name}」上传或解析失败。") from result
                        raise result
                    references[item.id] = result
        return references

    async def _upload(self, client, item):
        data = {
            "purpose": item.purpose,
            "expires_after[anchor]": "created_at",
            "expires_after[seconds]": str(REMOTE_TTL),
        }
        with (self.root / item.id).open("rb") as source:
            result = json_object(await client.post(
                "/files", data=data, files={"file": (item.name, source, item.media_type)},
            ))
        remote_id = result.get("id")
        if not isinstance(remote_id, str) or not re.fullmatch(r"file-api-[A-Za-z0-9_-]{1,119}", remote_id):
            raise DeepSeekError("DeepSeek 没有返回有效的文件引用。")
        with self.database.session() as db:
            row = db.get(Attachment, item.id)
            row.remote_id = remote_id
            row.expires_at = result.get("expires_at") or time.time() + REMOTE_TTL
        return remote_id

    def discard(self, user_id, conversation_id, item_id):
        with self.lock, self.database.session() as db:
            ConversationService.owned(db, user_id, conversation_id)
            item = db.get(Attachment, item_id)
            if not item or item.conversation_id != conversation_id or item.message_id is not None:
                return
            db.delete(item)
        (self.root / item_id).unlink(missing_ok=True)

    def delete_conversation(self, user_id, conversation_id):
        with self.lock, self.database.session() as db:
            conversation = ConversationService.owned(db, user_id, conversation_id)
            rows = list(db.scalars(select(Attachment).where(Attachment.conversation_id == conversation_id)))
            db.delete(conversation)
        for row in rows:
            (self.root / row.id).unlink(missing_ok=True)
        return [row.remote_id for row in rows if row.remote_id]

    @staticmethod
    async def delete_remote(remote_ids):
        if not remote_ids:
            return
        try:
            async with httpx.AsyncClient(base_url=BASE_URL, headers=api_headers(), timeout=8) as client:
                await asyncio.gather(
                    *(client.delete(f"/files/{item}") for item in remote_ids), return_exceptions=True,
                )
        except (DeepSeekError, httpx.HTTPError):
            # Previously uploaded copies have an expiry even if deletion fails.
            pass
