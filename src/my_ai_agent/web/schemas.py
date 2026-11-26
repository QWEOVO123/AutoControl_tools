import json

from pydantic import BaseModel, ConfigDict, Field


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class TitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class RunInput(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


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
