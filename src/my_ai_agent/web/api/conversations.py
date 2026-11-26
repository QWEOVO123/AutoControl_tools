from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import authenticated, authorized_write
from ..schemas import TitleInput
from ..security import AuthContext

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations(request: Request, context: AuthContext = Depends(authenticated)):
    return request.app.state.conversations.list(context.user_id)


@router.post("", status_code=201)
def create(request: Request, context: AuthContext = Depends(authorized_write)):
    return request.app.state.conversations.create(context.user_id)


@router.get("/{conversation_id}")
def detail(conversation_id: str, request: Request, context: AuthContext = Depends(authenticated)):
    result = request.app.state.conversations.detail(context.user_id, conversation_id)
    result["running"] = conversation_id in request.app.state.runtime.active
    return result


@router.patch("/{conversation_id}")
def rename(conversation_id: str, payload: TitleInput, request: Request, context: AuthContext = Depends(authorized_write)):
    return request.app.state.conversations.rename(context.user_id, conversation_id, payload.title)


@router.delete("/{conversation_id}")
async def delete(conversation_id: str, request: Request, context: AuthContext = Depends(authorized_write)):
    runtime = request.app.state.runtime
    async with runtime.guard:
        with request.app.state.database.session() as db:
            request.app.state.conversations.owned(db, context.user_id, conversation_id)
        if conversation_id in runtime.active:
            raise HTTPException(409, "请先停止这个会话中的任务。")
        request.app.state.conversations.delete(context.user_id, conversation_id)
        await runtime.checkpointer.adelete_thread(f"{context.user_id}:{conversation_id}")
    return {"ok": True}
