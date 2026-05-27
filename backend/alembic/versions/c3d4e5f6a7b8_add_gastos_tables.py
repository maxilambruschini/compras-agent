"""add gastos, conversations, and caja_cierres tables

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-05-27

References:
- CONV-01: DB-backed conversation state per sender, survives restarts
- D-01: Minimal Gasto field set (concepto + monto + fecha + optional ticket path)
- D-09: agent_mode demo isolation; tables needed regardless of which agent is active
- CajaCierre created here so all three tables land in one migration (no schema debt)

# RLS intentionally deferred (Phase 1 review concern 5): no policies + non-owner app role
# = prod default-deny. Revisit with explicit policies + app-role test in a hardening phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create conversations, gastos, and caja_cierres tables with indexes."""
    # conversations: per-sender state machine row
    # sender_phone is PK — uniqueness enforced by PK constraint, no extra unique index needed
    op.create_table(
        'conversations',
        sa.Column('sender_phone', sa.String(length=30), nullable=False),
        sa.Column('state', sa.String(length=30), nullable=False),
        sa.Column('draft_gasto', sa.Text(), nullable=True),
        sa.Column('last_message_id', sa.String(length=100), nullable=True),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('sender_phone'),
    )
    op.create_index('ix_conversations_sender_phone', 'conversations', ['sender_phone'], unique=False)

    # gastos: committed expense records — written only after explicit confirmation
    op.create_table(
        'gastos',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('concepto', sa.Text(), nullable=False),
        sa.Column('monto', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('ticket_image_path', sa.Text(), nullable=True),
        sa.Column('sender_phone', sa.String(length=30), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_gastos_fecha', 'gastos', ['fecha'], unique=False)
    op.create_index('ix_gastos_sender_phone', 'gastos', ['sender_phone'], unique=False)

    # caja_cierres: twice-daily cash-closing records (12:00 / 17:00)
    # Reactive write implemented in Phase 2; table created here to keep all schema in one migration
    op.create_table(
        'caja_cierres',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('hora_cierre', sa.String(length=5), nullable=False),
        sa.Column('efectivo_en_caja', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('sender_phone', sa.String(length=30), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_caja_cierres_fecha', 'caja_cierres', ['fecha'], unique=False)


def downgrade() -> None:
    """Drop gastos tables in reverse order (indexes first, then tables)."""
    op.drop_index('ix_caja_cierres_fecha', table_name='caja_cierres')
    op.drop_table('caja_cierres')

    op.drop_index('ix_gastos_sender_phone', table_name='gastos')
    op.drop_index('ix_gastos_fecha', table_name='gastos')
    op.drop_table('gastos')

    op.drop_index('ix_conversations_sender_phone', table_name='conversations')
    op.drop_table('conversations')
