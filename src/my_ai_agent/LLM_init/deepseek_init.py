import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_core.language_models import BaseChatModel
def LLM_init() -> BaseChatModel:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        raise ValueError("请在env文件中配置deepseek_api_key")
    print("正在初始化")
    llm = ChatDeepSeek(
        model="deepseek-flash",
        api_key=api_key,
        timeout=60,
        extra_body={"thinking": {"type": "disabled"}},
    )
    try:
        response = llm.invoke("仅回复OK")
    except Exception as e:
        raise RuntimeError(f"LLM API 测试失败: {e}") from e
    print(f"[LLM] 测试响应: {response.content}")
    print("[LLM] 模型初始化成功")
    return llm
