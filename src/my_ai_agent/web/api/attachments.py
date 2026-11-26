import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..dependencies import authenticated, authorized_write
from ..models import Attachment
from ..security import AuthContext

router = APIRouter(prefix="/conversations", tags=["attachments"])


@router.post("/{conversation_id}/attachments", status_code=201)
def upload(
    conversation_id: str,
    request: Request,
    files: Annotated[list[UploadFile], File()],
    rich: Annotated[bool, Form()] = False,
    context: AuthContext = Depends(authorized_write),
):
    if os.getenv("DEEPSEEK_MODEL", "deepseek-flash") != "deepseek-flash":
        raise HTTPException(422, "附件问答需要 deepseek-flash。")
    return request.app.state.attachments.stage(context.user_id, conversation_id, files, rich)


@router.get("/{conversation_id}/attachments/{item_id}")
def download(
    conversation_id: str, item_id: UUID, request: Request,
    context: AuthContext = Depends(authenticated),
):
    with request.app.state.database.session() as db:
        request.app.state.conversations.owned(db, context.user_id, conversation_id)
        item = db.get(Attachment, str(item_id))
        if not item or item.conversation_id != conversation_id:
            raise HTTPException(404, "附件不存在。")
        path = request.app.state.attachments.root / item.id
        if not path.is_file():
            raise HTTPException(404, "本地附件不存在。")
        return FileResponse(path, media_type="application/octet-stream", filename=item.name)


@router.delete("/{conversation_id}/attachments/{item_id}")
def discard(
    conversation_id: str, item_id: UUID, request: Request,
    context: AuthContext = Depends(authorized_write),
):
    request.app.state.attachments.discard(context.user_id, conversation_id, str(item_id))
    return {"ok": True}
