"""llm_calls

Revision ID: 7fa2ccc549a7
Revises: c76035b27890
Create Date: 2026-11-13 12:28:02.863094

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7fa2ccc549a7'
down_revision: Union[str, Sequence[str], None] = 'c76035b27890'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'llm_calls',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('endpoint', sa.String(length=32), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('tokens', sa.Integer(), nullable=False),
        sa.Column('cost_eur', sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_llm_calls_endpoint'), 'llm_calls', ['endpoint'], unique=False)
    op.create_index(op.f('ix_llm_calls_username'), 'llm_calls', ['username'], unique=False)
    op.create_index(op.f('ix_llm_calls_run_id'), 'llm_calls', ['run_id'], unique=False)
    op.create_index(op.f('ix_llm_calls_created_at'), 'llm_calls', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # IF EXISTS: questa revisione era stata applicata vuota, quindi su un database già a
    # head la tabella può non esserci. Il downgrade non deve fermarsi per questo.
    op.execute('DROP TABLE IF EXISTS llm_calls')
