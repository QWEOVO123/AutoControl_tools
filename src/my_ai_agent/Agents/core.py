from pathlib import Path
import platform
import sys

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from ..LLM_init import LLM_init
from ..LLM_init.deepseek_init import ReasoningEffort
from ..Tools import TOOLS


BASE_DIR = Path(__file__).resolve().parents[1]


def init_agent(*, checkpointer=None, probe: bool = True, reasoning_effort: ReasoningEffort = "none"):
    """初始化 AI Agent。"""

    llm = LLM_init(check_connection=probe, reasoning_effort=reasoning_effort)

    system_prompt = (
        BASE_DIR / "Prompts" / "system.md"
    ).read_text(encoding="utf-8")
    system_prompt += (
        "\n\n# 本次运行环境\n"
        f"- 启动工作目录：{Path.cwd()}\n"
        f"- 操作系统：{platform.system()} {platform.release()}\n"
        f"- Python：{platform.python_version()}\n"
        f"- Python 解释器：{sys.executable}\n"
        "- 相对路径均以启动工作目录为基准；Shell 内 cd 不影响后续工具。\n"
    )

    agent = create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=system_prompt,
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
    )

    print("[Agent] 初始化成功")

    return agent
