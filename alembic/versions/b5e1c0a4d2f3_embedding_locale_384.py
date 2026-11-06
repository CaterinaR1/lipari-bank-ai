"""embedding locale a 384 dimensioni

Revision ID: b5e1c0a4d2f3
Revises: 7dd331fffe5b
Create Date: 2026-11-06 10:00:00.000000

"""
from typing import Sequence, Union

import pgvector.sqlalchemy  # l'autogenerate lo usa e non lo importa
import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b5e1c0a4d2f3'
down_revision: Union[str, Sequence[str], None] = '7dd331fffe5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Passa da 1536 (OpenAI) a 384 (multilingual-e5-small locale)."""
    op.drop_index('ix_document_chunks_embedding', table_name='document_chunks')
    # i vettori di un modello non valgono per un altro: si svuota e si re-ingersce
    op.execute("DELETE FROM document_chunks")
    op.drop_column('document_chunks', 'embedding')
    op.add_column(
        'document_chunks',
        sa.Column(
            'embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False
        ),
    )
    op.create_index(
        'ix_document_chunks_embedding',
        'document_chunks',
        ['embedding'],
        unique=False,
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )


def downgrade() -> None:
    """Torna a 1536: anche qui i vettori vecchi non valgono, si svuota."""
    op.drop_index('ix_document_chunks_embedding', table_name='document_chunks')
    op.execute("DELETE FROM document_chunks")
    op.drop_column('document_chunks', 'embedding')
    op.add_column(
        'document_chunks',
        sa.Column(
            'embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False
        ),
    )
    op.create_index(
        'ix_document_chunks_embedding',
        'document_chunks',
        ['embedding'],
        unique=False,
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )
