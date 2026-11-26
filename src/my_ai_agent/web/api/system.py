import os
import platform
from pathlib import Path

from fastapi import APIRouter, Depends

from ...Tools import TOOLS
from ..dependencies import authenticated

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/system", dependencies=[Depends(authenticated)])
def system():
    return {
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(), "workspace": str(Path.cwd()),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        "model_configured": bool(os.getenv("DEEPSEEK_API_KEY")),
        "transport": "HTTP / SSE", "elevation_enabled": False,
        "tools": [{"name": item.name, "description": item.description.splitlines()[0]} for item in TOOLS],
    }
