from collections import defaultdict
import time

from fastapi import HTTPException
from sqlalchemy import select

from ..models import Attachment, Conversation, Message, MessageReasoning, MessageUsage, Run
from ..schemas import ConversationOutput, attachment_output, message_output, usage_output


class ConversationService:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def owned(db, user_id, conversation_id):
        item = db.get(Conversation, conversation_id)
        if not item or item.user_id != user_id:
            raise HTTPException(404, "会话不存在。")
        return item

    def list(self, user_id):
        with self.database.session() as db:
            items = db.scalars(select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc()).limit(200))
            return [ConversationOutput.model_validate(item) for item in items]

    def create(self, user_id):
        with self.database.session() as db:
            item = Conversation(user_id=user_id)
            db.add(item)
            db.flush()
            return ConversationOutput.model_validate(item)

    def detail(self, user_id, conversation_id):
        with self.database.session() as db:
            item = self.owned(db, user_id, conversation_id)
            messages = db.execute(
                select(Message, MessageReasoning.content, MessageUsage)
                .outerjoin(MessageReasoning, MessageReasoning.message_id == Message.id)
                .outerjoin(MessageUsage, MessageUsage.message_id == Message.id)
                .where(Message.conversation_id == item.id)
                .order_by(Message.created_at, Message.id)
            )
            errors = {run.message_id: run.error for run in db.scalars(select(Run).where(Run.conversation_id == item.id))}
            attached = defaultdict(list)
            for file in db.scalars(select(Attachment).where(
                Attachment.conversation_id == item.id, Attachment.message_id.is_not(None),
            ).order_by(Attachment.created_at)):
                attached[file.message_id].append(attachment_output(file))
            return {
                "conversation": ConversationOutput.model_validate(item),
                "messages": [
                    {
                        **message_output(message), "reasoning": reasoning, "error": errors.get(message.id),
                        "attachments": attached[message.id], "usage": usage_output(usage) if usage else None,
                    }
                    for message, reasoning, usage in messages
                ],
            }

    def rename(self, user_id, conversation_id, title):
        title = title.strip()
        if not title:
            raise HTTPException(422, "标题不能为空。")
        with self.database.session() as db:
            item = self.owned(db, user_id, conversation_id)
            item.title = title
            item.updated_at = time.time()
            db.flush()
            return ConversationOutput.model_validate(item)
