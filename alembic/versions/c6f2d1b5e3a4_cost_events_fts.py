"""costi fuori chat e indice lessicale per la ricerca ibrida

Revision ID: c6f2d1b5e3a4
Revises: b5e1c0a4d2f3
Create Date: 2026-11-06 10:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c6f2d1b5e3a4'
down_revision: Union[str, Sequence[str], None] = 'b5e1c0a4d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """La spesa dell'advisor non è un messaggio di chat; il lessico serve alla ricerca ibrida."""
    op.create_table(
        'cost_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('model_used', sa.String(length=64), nullable=True),
        sa.Column('tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cost_eur', sa.Numeric(precision=10, scale=6), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_cost_events_source'), 'cost_events', ['source'], unique=False)
    op.create_index(
        op.f('ix_cost_events_created_at'), 'cost_events', ['created_at'], unique=False
    )
    # indice lessicale: la ricerca per parole affianca quella per similarità
    op.execute(
        "CREATE INDEX ix_document_chunks_content_fts "
        "ON document_chunks USING gin (to_tsvector('italian', content))"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_fts")
    op.drop_index(op.f('ix_cost_events_created_at'), table_name='cost_events')
    op.drop_index(op.f('ix_cost_events_source'), table_name='cost_events')
    op.drop_table('cost_events')
