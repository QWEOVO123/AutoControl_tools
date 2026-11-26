import os
from typing import Literal

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_deepseek import ChatDeepSeek

from ..deepseek_api import ATTACHMENT_REFERENCES

ReasoningEffort = Literal["none", "low", "high", "max"]
OutputMode = Literal["text", "json"]


class AgentChatDeepSeek(ChatDeepSeek):
    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_)
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        references = ATTACHMENT_REFERENCES.get() or {}
        replay_reasoning = payload.get("tools") and payload.get("reasoning_effort") != "none"
        for original, outgoing in zip(messages.to_messages(), payload["messages"], strict=True):
            if replay_reasoning and isinstance(original, AIMessage):
                # DeepSeek needs reasoning from earlier assistant messages when tools are supplied.
                outgoing["reasoning_content"] = original.additional_kwargs.get("reasoning_content") or ""
            if outgoing["role"] != "user":
                continue
            files = [
                {"type": "file", "file_id": references[key]}
                for key in original.additional_kwargs.get("attachment_ids", ())
                if key in references
            ]
            if files:
                content = outgoing["content"]
                text_blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
                outgoing["content"] = [*files, *text_blocks]
        return payload


def LLM_init(
    *, check_connection: bool = True, reasoning_effort: ReasoningEffort = "none",
    output_mode: OutputMode = "text",
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
        stream_usage=True,
        reasoning_effort=reasoning_effort,
        model_kwargs={"response_format": {"type": "json_object"}} if output_mode == "json" else {},
    )
    if check_connection:
        try:
            response = llm.invoke("仅回复OK")
        except Exception as e:
            raise RuntimeError(f"LLM API 测试失败: {e}") from e
        print(f"[LLM] 测试响应: {response.content}")
    print("[LLM] 模型初始化成功")
    return llm
