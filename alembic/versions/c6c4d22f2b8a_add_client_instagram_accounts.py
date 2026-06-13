"""add client instagram accounts

Revision ID: c6c4d22f2b8a
Revises: 4a88b64ab48b
Create Date: 2026-06-13 15:45:00
"""
from __future__ import annotations

from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "c6c4d22f2b8a"
down_revision: Union[str, Sequence[str], None] = "4a88b64ab48b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "client_instagram_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("instagram_account_id", sa.Text(), nullable=False),
        sa.Column("account_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("instagram_account_id", name="uq_client_instagram_accounts_account_id"),
    )
    op.create_index(
        "ix_client_instagram_accounts_client_id",
        "client_instagram_accounts",
        ["client_id"],
    )
    op.create_index(
        "ix_client_instagram_accounts_instagram_account_id",
        "client_instagram_accounts",
        ["instagram_account_id"],
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, instagram_account_id, instagram_username
            FROM clients
            WHERE instagram_account_id IS NOT NULL
              AND instagram_account_id <> ''
            """
        )
    ).mappings()
    for row in rows:
        connection.execute(
            sa.text(
                """
                INSERT INTO client_instagram_accounts (
                    id,
                    client_id,
                    instagram_account_id,
                    account_name,
                    status
                )
                VALUES (
                    :id,
                    :client_id,
                    :instagram_account_id,
                    :account_name,
                    'active'
                )
                ON CONFLICT (instagram_account_id) DO NOTHING
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "client_id": str(row["id"]),
                "instagram_account_id": row["instagram_account_id"],
                "account_name": row["instagram_username"],
            },
        )


def downgrade() -> None:
    op.drop_index("ix_client_instagram_accounts_instagram_account_id", table_name="client_instagram_accounts")
    op.drop_index("ix_client_instagram_accounts_client_id", table_name="client_instagram_accounts")
    op.drop_table("client_instagram_accounts")
