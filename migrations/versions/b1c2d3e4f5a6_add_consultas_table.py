"""add consultas table

Revision ID: b1c2d3e4f5a6
Revises: a1f2c3d4e5f6
Create Date: 2025-11-13 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = 'a1f2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('consultas',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('nombre', sa.String(length=160), nullable=False),
        sa.Column('email', sa.String(length=160), nullable=False),
        sa.Column('telefono', sa.String(length=80), nullable=True),
        sa.Column('consulta', sa.String(length=500), nullable=False),
        sa.Column('image1', sa.String(length=200), nullable=True),
        sa.Column('image2', sa.String(length=200), nullable=True),
        sa.Column('image3', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('consultas') as batch_op:
        batch_op.create_index('ix_consultas_created_at', ['created_at'], unique=False)
        batch_op.create_index('ix_consultas_read_at', ['read_at'], unique=False)

def downgrade():
    with op.batch_alter_table('consultas') as batch_op:
        batch_op.drop_index('ix_consultas_read_at')
        batch_op.drop_index('ix_consultas_created_at')
    op.drop_table('consultas')
