import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..LLM_init.deepseek_init import OutputMode, ReasoningEffort


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class TitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class RunInput(BaseModel):
    content: str = Field(default="", max_length=8000)
    reasoning_effort: ReasoningEffort = "none"
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=4)
    output_mode: OutputMode = "text"


class ConversationOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    created_at: float
    updated_at: float


def message_output(message):
    return {
        "id": message.id, "role": message.role, "content": message.content,
        "status": message.status, "created_at": message.created_at,
        "tool_events": json.loads(message.tool_events),
    }


def attachment_output(item):
    return {"id": item.id, "name": item.name, "size": item.size, "media_type": item.media_type}


def usage_output(usage):
    return {
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
    }
