"""Add products.sku for mapping WooCommerce (or any external store) line
items to this catalog's products. Nullable: existing demo products have no
real-world SKU until you assign one.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("products", sa.Column("sku", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_products_sku"), "products", ["sku"], unique=True)


def downgrade():
    op.drop_index(op.f("ix_products_sku"), table_name="products")
    op.drop_column("products", "sku")
