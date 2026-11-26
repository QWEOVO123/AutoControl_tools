import time
import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def identifier():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(80), default="新会话")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="completed")
    tool_events: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class MessageReasoning(Base):
    __tablename__ = "message_reasoning"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    content: Mapped[str] = mapped_column(Text)


class ContextRecord(Base):
    __tablename__ = "context_records"
    __table_args__ = (Index("ix_context_records_thread_time", "thread_id", "created_at"),)

    thread_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    source_end_id: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[float] = mapped_column(Float)


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    size: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(32))
    remote_id: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class MessageUsage(Base):
    __tablename__ = "message_usage"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="running")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    finished_at: Mapped[float | None] = mapped_column(Float, default=None)
