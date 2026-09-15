"""Partial-order fulfillment, customer cancellation, and per-user auth/RBAC.

- order_lines.dropped: a line excluded from fulfillment under partial-order
  fulfillment (rejected offer / no alternative), instead of cancelling the
  whole order.
- order_lines.original_unit_price_paisa: snapshot of the line's price at
  intake, needed to compute exact per-line refunds without double counting.
- orders.cancel_token_hash: bearer capability for customer self-cancellation
  before resolution starts (POST /orders/{id}/cancel).
- users: per-user login backing role-based access control (admin/auditor/viewer).
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("cancel_token_hash", sa.String(length=64), nullable=True))

    # original_unit_price_paisa is NOT NULL but existing rows have no history
    # of what they were charged before any replacement was applied; backfill
    # from the current unit_price_paisa as the closest available approximation.
    op.add_column("order_lines", sa.Column("original_unit_price_paisa", sa.Integer(), nullable=True))
    op.execute("UPDATE order_lines SET original_unit_price_paisa = unit_price_paisa "
               "WHERE original_unit_price_paisa IS NULL")
    with op.batch_alter_table("order_lines") as batch:
        batch.alter_column("original_unit_price_paisa", nullable=False)
        batch.add_column(sa.Column("dropped", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("order_lines", "dropped", server_default=None)

    op.create_table("users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)


def downgrade():
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    with op.batch_alter_table("order_lines") as batch:
        batch.drop_column("dropped")
        batch.drop_column("original_unit_price_paisa")
    op.drop_column("orders", "cancel_token_hash")
