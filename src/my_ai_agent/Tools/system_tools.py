from datetime import datetime
import platform
from pathlib import Path
import sys

from langchain_core.tools import tool

@tool
def get_current_time() -> str:
    """获取当前计算机的本地日期、时间和时区。"""
    return datetime.now().astimezone().isoformat()

@tool
def get_system_info() -> dict:
    """获取当前计算机的操作系统、处理器和架构信息。"""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cwd": str(Path.cwd()),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
    }


@tool
def multiply(a: float, b: float) -> float:
    """计算两个数字的乘积。"""
    return a * b
