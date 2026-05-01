import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, ForeignKey, Integer, String, Text, DateTime
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


def _now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Client(Base):
    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    business_name = Column(String, nullable=False)
    owner_email = Column(String, nullable=False)
    instagram_account_id = Column(String, unique=True, nullable=False, index=True)
    instagram_username = Column(String, nullable=True)
    instagram_access_token_encrypted = Column(Text, nullable=False)
    system_prompt = Column(Text, nullable=True)
    whatsapp_link = Column(String, nullable=True)
    telegram_manager_chat_id = Column(String, nullable=True)
    groq_api_key_encrypted = Column(Text, nullable=True)

    plan = Column(String, default="basic", nullable=False)
    status = Column(String, default="trial", nullable=False)
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    conversations = relationship("Conversation", back_populates="client", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="client", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    instagram_user_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    last_message_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    messages_count = Column(Integer, default=0, nullable=False)
    highest_temperature = Column(String, default="cold", nullable=False)

    client = relationship("Client", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    is_voice = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")


class Lead(Base):
    __tablename__ = "leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    instagram_user_id = Column(String, nullable=False)
    temperature = Column(String, nullable=False)
    triggered_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    notified_to_telegram = Column(Boolean, default=False, nullable=False)
    last_message = Column(Text, nullable=True)

    client = relationship("Client", back_populates="leads")
    conversation = relationship("Conversation", back_populates="leads")
