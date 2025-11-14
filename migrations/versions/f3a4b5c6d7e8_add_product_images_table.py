"""add product images table

Revision ID: f3a4b5c6d7e8
Revises: e763cb475c9c
Create Date: 2025-11-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f3a4b5c6d7e8'
down_revision = 'e763cb475c9c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'product_images',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(length=200), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_product_images_product_id_position', 'product_images', ['product_id', 'position'])


def downgrade() -> None:
    op.drop_index('ix_product_images_product_id_position', table_name='product_images')
    op.drop_table('product_images')
