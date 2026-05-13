"""add server_default to sender_allowlist.is_active

Revision ID: 9f9e9cf65e1e
Revises: 0cd640399c29
Create Date: 2026-05-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f9e9cf65e1e'
down_revision: Union[str, Sequence[str], None] = '0cd640399c29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add database-level server_default='true' to sender_allowlist.is_active.

    The column was created as Boolean NOT NULL with an ORM-level default=True but
    without a server_default, meaning raw SQL inserts that omit the column would fail.
    """
    op.alter_column(
        'sender_allowlist',
        'is_active',
        server_default=sa.text('true'),
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Remove server_default from sender_allowlist.is_active."""
    op.alter_column(
        'sender_allowlist',
        'is_active',
        server_default=None,
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )
