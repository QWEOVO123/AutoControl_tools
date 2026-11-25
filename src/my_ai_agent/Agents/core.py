from pathlib import Path

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from ..LLM_init import LLM_init
from ..Tools import TOOLS


BASE_DIR = Path(__file__).resolve().parents[1]


def init_agent():
    """初始化 AI Agent。"""

    llm = LLM_init()

    system_prompt = (
        BASE_DIR / "Prompts" / "system.md"
    ).read_text(encoding="utf-8")

    agent = create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=system_prompt,
        checkpointer=InMemorySaver(),
    )

    print("[Agent] 初始化成功")

    return agent
