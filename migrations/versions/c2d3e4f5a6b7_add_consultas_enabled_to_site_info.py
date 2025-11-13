"""add consultas_enabled to site_info

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2025-11-13 19:25:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_info') as batch_op:
        batch_op.add_column(sa.Column('consultas_enabled', sa.Boolean(), server_default='true', nullable=False))


def downgrade():
    with op.batch_alter_table('site_info') as batch_op:
        batch_op.drop_column('consultas_enabled')
