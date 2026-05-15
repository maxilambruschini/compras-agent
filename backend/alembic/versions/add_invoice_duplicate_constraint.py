"""add functional unique index for invoice duplicate detection

Revision ID: b1c2d3e4f5a6
Revises: 9f9e9cf65e1e
Create Date: 2026-05-14

References:
- D-15: Functional UNIQUE INDEX on (LOWER(numero_documento), LOWER(proveedor))
        backstops application-level duplicate check against concurrent INSERT races.
- Pitfall 6 (03-RESEARCH.md): Postgres UNIQUE ignores rows where either indexed
        column IS NULL — correct behavior for low-confidence extractions where
        numero_documento or proveedor may not have been extracted. The explicit
        WHERE clause reinforces this contract.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = '9f9e9cf65e1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add functional unique index on (LOWER(numero_documento), LOWER(proveedor)).

    Backstops application-level duplicate check against race conditions (D-15).
    Postgres UNIQUE ignores rows where either indexed column is NULL — correct
    behavior for low-confidence extractions (Pitfall 6 in 03-RESEARCH.md).
    The WHERE clause explicitly documents and enforces this NULL-exclusion behavior.
    """
    op.execute(
        "CREATE UNIQUE INDEX uq_invoices_numero_proveedor_lower "
        "ON invoices (LOWER(numero_documento), LOWER(proveedor)) "
        "WHERE numero_documento IS NOT NULL AND proveedor IS NOT NULL"
    )


def downgrade() -> None:
    """Remove the functional unique index (reversible)."""
    op.execute("DROP INDEX IF EXISTS uq_invoices_numero_proveedor_lower")
