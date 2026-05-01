"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-01
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("business_name", sa.String, nullable=False),
        sa.Column("owner_email", sa.String, nullable=False),
        sa.Column("instagram_account_id", sa.String, nullable=False, unique=True),
        sa.Column("instagram_username", sa.String, nullable=True),
        sa.Column("instagram_access_token_encrypted", sa.Text, nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("whatsapp_link", sa.String, nullable=True),
        sa.Column("telegram_manager_chat_id", sa.String, nullable=True),
        sa.Column("groq_api_key_encrypted", sa.Text, nullable=True),
        sa.Column("plan", sa.String, nullable=False, server_default="basic"),
        sa.Column("status", sa.String, nullable=False, server_default="trial"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_clients_instagram_account_id", "clients", ["instagram_account_id"])

    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instagram_user_id", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("messages_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("highest_temperature", sa.String, nullable=False, server_default="cold"),
    )
    op.create_index("ix_conversations_client_id", "conversations", ["client_id"])
    op.create_index("ix_conversations_instagram_user_id", "conversations", ["instagram_user_id"])

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("is_voice", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "leads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instagram_user_id", sa.String, nullable=False),
        sa.Column("temperature", sa.String, nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("notified_to_telegram", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_message", sa.Text, nullable=True),
    )
    op.create_index("ix_leads_client_id", "leads", ["client_id"])


def downgrade() -> None:
    op.drop_table("leads")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("clients")
