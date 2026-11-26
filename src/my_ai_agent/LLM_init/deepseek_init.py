import os
from typing import Literal

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_deepseek import ChatDeepSeek

ReasoningEffort = Literal["none", "low", "high", "max"]


class AgentChatDeepSeek(ChatDeepSeek):
    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_)
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        if payload.get("tools") and payload.get("reasoning_effort") != "none":
            # The OpenAI serializer omits DeepSeek's reasoning field. Its tool
            # requests require the original reasoning on prior assistant messages.
            for original, outgoing in zip(messages.to_messages(), payload["messages"], strict=True):
                if isinstance(original, AIMessage):
                    outgoing["reasoning_content"] = original.additional_kwargs.get("reasoning_content") or ""
        return payload


def LLM_init(
    *, check_connection: bool = True, reasoning_effort: ReasoningEffort = "none"
) -> BaseChatModel:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        raise ValueError("请在env文件中配置deepseek_api_key")
    print("正在初始化")
    llm = AgentChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        api_key=api_key,
        timeout=60,
        use_responses_api=False,
        reasoning_effort=reasoning_effort,
    )
    if check_connection:
        try:
            response = llm.invoke("仅回复OK")
        except Exception as e:
            raise RuntimeError(f"LLM API 测试失败: {e}") from e
        print(f"[LLM] 测试响应: {response.content}")
    print("[LLM] 模型初始化成功")
    return llm
