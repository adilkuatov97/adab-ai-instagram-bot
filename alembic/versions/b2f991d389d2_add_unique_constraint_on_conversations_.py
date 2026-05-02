"""add unique constraint on conversations client_user

Revision ID: b2f991d389d2
Revises: 001
Create Date: 2026-05-03 01:07:55.651602

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2f991d389d2'
down_revision: Union[str, Sequence[str], None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "conversations_client_user_unique",
        "conversations",
        ["client_id", "instagram_user_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "conversations_client_user_unique",
        "conversations",
        type_="unique",
    )
