from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..dependencies import authorized_write
from ..schemas import RunInput
from ..security import AuthContext

router = APIRouter(prefix="/conversations", tags=["runs"])


@router.post("/{conversation_id}/runs")
async def run(conversation_id: str, payload: RunInput, request: Request, context: AuthContext = Depends(authorized_write)):
    stream = await request.app.state.runtime.start(
        context.user_id, conversation_id, payload.content, payload.reasoning_effort,
        tuple(dict.fromkeys(str(item) for item in payload.attachment_ids)),
        payload.output_mode,
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/{conversation_id}/stop")
async def stop(conversation_id: str, request: Request, context: AuthContext = Depends(authorized_write)):
    return request.app.state.runtime.cancel(context.user_id, conversation_id)
