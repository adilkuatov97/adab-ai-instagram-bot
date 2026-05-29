"""add_whatsapp_system_prompt

Revision ID: 4a88b64ab48b
Revises: b2f991d389d2
Create Date: 2026-05-29 05:08:52.745189

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a88b64ab48b'
down_revision: Union[str, Sequence[str], None] = 'b2f991d389d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('whatsapp_system_prompt', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('clients', 'whatsapp_system_prompt')
