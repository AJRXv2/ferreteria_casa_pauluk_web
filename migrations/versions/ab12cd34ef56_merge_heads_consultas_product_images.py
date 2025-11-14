"""merge heads for consultas and product images

Revision ID: ab12cd34ef56
Revises: c2d3e4f5a6b7, f3a4b5c6d7e8
Create Date: 2025-11-14 18:00:00.000000

"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision = 'ab12cd34ef56'
down_revision = ('c2d3e4f5a6b7', 'f3a4b5c6d7e8')
branch_labels = None
depends_on = None


def upgrade():
    # No-op merge point to join previously diverging heads.
    pass


def downgrade():
    # No-op downgrade because this revision only merges heads.
    pass
