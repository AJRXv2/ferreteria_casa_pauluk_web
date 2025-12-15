"""remove unique constraint on products.sku

Revision ID: d4e5f6a7b8c9
Revises: f3a4b5c6d7e8
Create Date: 2025-12-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop unique constraint/index for sku if present (Postgres)
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_sku_key;")
    op.execute("DROP INDEX IF EXISTS products_sku_key;")


def downgrade() -> None:
    # Recreate unique constraint on sku
    op.create_unique_constraint('products_sku_key', 'products', ['sku'])
