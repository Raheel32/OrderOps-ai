from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("stock >= 0"), CheckConstraint("price_paisa > 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(80))
    # A merchant-curated compatibility group, including type and pack size.
    substitution_group: Mapped[str] = mapped_column(String(100), index=True)
    price_paisa: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer)
    # WooCommerce (or any external store's) SKU, for mapping webhook order
    # line items to this catalog. Nullable: a product only becomes orderable
    # via the webhook once you assign it a real SKU.
    sku: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    external_id: Mapped[str] = mapped_column(String(100), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    customer_email: Mapped[str] = mapped_column(String(254))
    preferred_brands: Mapped[list] = mapped_column(JSON, default=list)
    risk_score: Mapped[float] = mapped_column(Float)
    payment_method: Mapped[str] = mapped_column(String(20))
    original_total_paisa: Mapped[int] = mapped_column(Integer)
    final_total_paisa: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="received", index=True)
    manual_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    had_shortage: Mapped[bool] = mapped_column(Boolean, default=False)
    recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    first_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Bearer capability for pre-resolution self-service cancellation (see /orders/{id}/cancel).
    cancel_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class OrderLine(Base):
    __tablename__ = "order_lines"
    __table_args__ = (CheckConstraint("quantity > 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    original_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_paisa: Mapped[int] = mapped_column(Integer)
    # Snapshot at intake; unit_price_paisa mutates when a replacement is accepted.
    # Needed to compute an exact per-line refund without double-counting dropped lines.
    original_unit_price_paisa: Mapped[int] = mapped_column(Integer)
    reserved: Mapped[bool] = mapped_column(Boolean, default=False)
    # True once this line has been excluded from fulfillment (rejected/no alternative)
    # under partial-order fulfillment. The order can still complete around it.
    dropped: Mapped[bool] = mapped_column(Boolean, default=False)


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    unit_price_paisa: Mapped[int] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    held: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(100), unique=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    # Recorded locally; never claim sent, fulfilled or refunded.
    status: Mapped[str] = mapped_column(String(30), default="demo_recorded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    # One row per order serializes that order's graph and callback writes.
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    # "admin": full access. "auditor": read + audit decisions. "viewer": read-only.
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
