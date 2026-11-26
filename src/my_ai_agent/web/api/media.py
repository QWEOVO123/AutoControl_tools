"""Explicit OCR, transcription, and speech requests from the workspace."""

from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...deepseek_api import BASE_URL, DeepSeekError, api_headers, ensure_success, json_object
from ..dependencies import authorized_write
from ..services.attachments import DOCUMENTS, IMAGES, MAX_FILE_BYTES, classify

router = APIRouter(prefix="/media", tags=["media"], dependencies=[Depends(authorized_write)])


async def read_upload(file: UploadFile, limit: int):
    data = await file.read(limit + 1)
    if not data:
        raise HTTPException(422, "文件不能为空。")
    if len(data) > limit:
        raise HTTPException(413, f"文件大小超过 {limit // (1024 * 1024)} MiB。")
    return data


def media_error(exc):
    if isinstance(exc, DeepSeekError):
        return HTTPException(502, str(exc))
    if isinstance(exc, httpx.TimeoutException):
        return HTTPException(504, "DeepSeek 媒体处理超时。")
    return HTTPException(502, "无法连接 DeepSeek 媒体服务。")


async def upload_tool(endpoint, filename, content, media_type, data=None):
    try:
        async with httpx.AsyncClient(
            base_url=BASE_URL, headers=api_headers(), timeout=httpx.Timeout(190, connect=15),
        ) as client:
            response = await client.post(
                f"/v1/tools/{endpoint}", data=data, files={"file": (filename, content, media_type)},
            )
            return json_object(response)
    except (DeepSeekError, httpx.HTTPError) as exc:
        raise media_error(exc) from exc


@router.post("/ocr")
async def ocr(
    file: Annotated[UploadFile, File()],
    layout: Annotated[bool, Form()] = False,
):
    name, media_type, _ = classify(file, layout)
    if Path(name).suffix.lower() not in DOCUMENTS | IMAGES:
        raise HTTPException(415, "OCR 支持图片、PDF、Word 和 PowerPoint。")
    content = await read_upload(file, MAX_FILE_BYTES)
    purpose = "rich_layout_recognition" if layout else "text_recognition"
    result = await upload_tool("ocr", name, content, media_type, {"purpose": purpose})
    pages = result.get("pages")
    if not isinstance(pages, list):
        raise HTTPException(502, "DeepSeek 未返回逐页 OCR 结果。")
    return {"pages": [
        {"index": page.get("index", index), "text": page["text"], "truncated": page.get("finish_reason") == "length"}
        for index, page in enumerate(pages) if isinstance(page, dict) and isinstance(page.get("text"), str)
    ]}


@router.post("/transcribe")
async def transcribe(file: Annotated[UploadFile, File()]):
    data = await read_upload(file, 8 * 1024 * 1024)
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        name, media_type = "recording.wav", "audio/wav"
    elif data.startswith(b"OggS") and b"OpusHead" in data[:128]:
        name, media_type = "recording.ogg", "audio/ogg"
    else:
        raise HTTPException(415, "请选择 16 位 PCM WAV 或 Ogg Opus 音频。")
    result = await upload_tool("asr", name, data, media_type)
    if not isinstance(result.get("text"), str):
        raise HTTPException(502, "DeepSeek 未返回语音转写结果。")
    return {"text": result["text"], "duration_ms": result.get("duration_ms")}


class SpeechInput(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    voice: Literal["stella", "tide"] = "stella"


@router.post("/speech")
async def speech(payload: SpeechInput):
    text = payload.text.strip()
    if not text:
        raise HTTPException(422, "请提供需要朗读的文字。")
    client = None
    try:
        client = httpx.AsyncClient(base_url=BASE_URL, headers=api_headers(), timeout=60)
        request = client.build_request("POST", "/v1/tools/tts", json={
            "text": text, "voice_id": payload.voice, "format": "wav", "filter_markdown": True,
        })
        response = await client.send(request, stream=True)
        ensure_success(response)
        if "audio/wav" not in response.headers.get("content-type", "").lower():
            raise DeepSeekError("DeepSeek 未返回 WAV 音频。")
    except (DeepSeekError, httpx.HTTPError) as exc:
        if client is not None:
            await client.aclose()
        raise media_error(exc) from exc
    except BaseException:
        if client is not None:
            await client.aclose()
        raise

    async def audio():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            try:
                await response.aclose()
            finally:
                await client.aclose()

    return StreamingResponse(audio(), media_type="audio/wav", headers={"X-Accel-Buffering": "no"})
