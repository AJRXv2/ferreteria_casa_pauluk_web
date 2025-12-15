"""merge ab12cd34ef56 and d4e5f6a7b8c9

Revision ID: merge_ab12_d4e5f6_heads
Revises: ab12cd34ef56, d4e5f6a7b8c9
Create Date: 2025-12-15 13:35:00.000000

This is a synthetic merge migration to collapse multiple Alembic heads into a single head.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'merge_ab12_d4e5f6_heads'
down_revision = ('ab12cd34ef56', 'd4e5f6a7b8c9')
branch_labels = None
depend_on = None


def upgrade() -> None:
    # No DB changes; this migration only merges heads.
    pass


def downgrade() -> None:
    # Downgrade not supported for merge migration.
    pass
