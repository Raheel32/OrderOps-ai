import base64
import hashlib
import hmac
import json
from datetime import timedelta
from sqlalchemy import select
from app import fraud
from app.config import settings
from app.models import Order, OrderLine, Product, utcnow


# --- Fraud scoring -----------------------------------------------------------

def test_fraud_score_zero_for_ordinary_first_order(env):
    _, dbs, _ = env
    with dbs() as db:
        s, reasons = fraud.score(db, "new@example.test", 50000)
    assert s == 0.0 and reasons == []


def test_fraud_score_flags_new_customer_high_value(env):
    _, dbs, _ = env
    with dbs() as db:
        s, reasons = fraud.score(db, "new@example.test", settings.fraud_new_customer_paisa_threshold)
    assert "new_customer_high_value" in reasons
    assert s == 0.4


def test_fraud_score_flags_order_far_above_customer_average(env):
    _, dbs, _ = env
    with dbs.begin() as db:
        for i in range(3):
            db.add(Order(external_id=f"hist-{i}", request_hash="h", customer_email="regular@example.test",
                        risk_score=0.0, payment_method="cod", original_total_paisa=10000,
                        final_total_paisa=10000))
    with dbs() as db:
        s, reasons = fraud.score(db, "regular@example.test", 10000 * settings.fraud_value_multiple + 1)
    assert "order_value_vs_average" in reasons


def test_fraud_score_flags_address_mismatch(env):
    _, dbs, _ = env
    billing = {"address_1": "123 A St", "city": "Karachi", "postcode": "74200", "country": "PK"}
    shipping = {"address_1": "456 B Ave", "city": "Lahore", "postcode": "54000", "country": "PK"}
    with dbs() as db:
        s, reasons = fraud.score(db, "gift@example.test", 5000, billing, shipping)
    assert "billing_shipping_mismatch" in reasons and s == 0.3


def test_fraud_score_flags_velocity(env):
    _, dbs, _ = env
    with dbs.begin() as db:
        for i in range(settings.fraud_velocity_max_orders - 1):
            db.add(Order(external_id=f"fast-{i}", request_hash="h", customer_email="fast@example.test",
                        risk_score=0.0, payment_method="cod", original_total_paisa=5000,
                        final_total_paisa=5000, created_at=utcnow()))
    with dbs() as db:
        s, reasons = fraud.score(db, "fast@example.test", 5000)
    assert "order_velocity" in reasons


def test_fraud_score_ignores_old_orders_outside_velocity_window(env):
    _, dbs, _ = env
    old = utcnow() - timedelta(minutes=settings.fraud_velocity_window_minutes + 10)
    with dbs.begin() as db:
        for i in range(settings.fraud_velocity_max_orders):
            db.add(Order(external_id=f"old-{i}", request_hash="h", customer_email="stale@example.test",
                        risk_score=0.0, payment_method="cod", original_total_paisa=5000,
                        final_total_paisa=5000, created_at=old))
    with dbs() as db:
        s, reasons = fraud.score(db, "stale@example.test", 5000)
    assert "order_velocity" not in reasons


def test_direct_api_computes_risk_score_when_omitted(env):
    c, dbs, g = env
    body = {"external_id": "no-risk-1", "customer_email": "auto@example.test",
            "payment_method": "cod", "items": [{"product_id": 3, "quantity": 1}]}
    r = c.post("/orders", json=body)
    assert r.status_code == 202
    with dbs() as db:
        order = db.get(Order, r.json()["order_id"])
        assert order.risk_score == 0.0  # ordinary low-value first order


# --- WooCommerce webhook ------------------------------------------------------

def sign(body_bytes):
    return base64.b64encode(hmac.new(settings.woocommerce_webhook_secret.encode(),
                                     body_bytes, hashlib.sha256).digest()).decode()


def woo_payload(order_id=5001, sku_qty=(("TEA-450", 1),), payment_method="bacs",
                billing_city="Karachi", shipping_city="Karachi"):
    return {
        "id": order_id,
        "payment_method": payment_method,
        "billing": {"email": "woo-customer@example.test", "address_1": "1 Main St",
                    "city": billing_city, "postcode": "74200", "country": "PK"},
        "shipping": {"address_1": "1 Main St", "city": shipping_city, "postcode": "74200", "country": "PK"},
        "line_items": [{"id": i, "sku": sku, "quantity": qty} for i, (sku, qty) in enumerate(sku_qty)],
    }


def post_webhook(c, payload):
    body = json.dumps(payload).encode()
    return c.post("/webhooks/woocommerce/order-created", content=body,
                  headers={"Content-Type": "application/json", "X-WC-Webhook-Signature": sign(body)})


def test_webhook_rejects_bad_signature(env):
    c, _, _ = env
    body = json.dumps(woo_payload()).encode()
    r = c.post("/webhooks/woocommerce/order-created", content=body,
              headers={"Content-Type": "application/json", "X-WC-Webhook-Signature": "wrong"})
    assert r.status_code == 401


def test_webhook_rejects_unmapped_sku(env):
    c, _, _ = env
    r = post_webhook(c, woo_payload(sku_qty=(("NOT-A-REAL-SKU", 1),)))
    assert r.status_code == 422
    assert "NOT-A-REAL-SKU" in r.json()["detail"]


def test_webhook_creates_order_with_mapped_sku_and_computed_risk(env):
    c, dbs, _ = env
    with dbs.begin() as db:
        db.get(Product, 3).sku = "OIL-1L"
    r = post_webhook(c, woo_payload(sku_qty=(("OIL-1L", 2),), payment_method="cod"))
    assert r.status_code == 202
    with dbs() as db:
        order = db.get(Order, r.json()["order_id"])
        assert order.payment_method == "cod"
        assert order.original_total_paisa == 60000 * 2
        assert order.customer_email == "woo-customer@example.test"
        assert order.risk_score == 0.0


def test_webhook_maps_non_cod_payment_method_to_prepaid(env):
    c, dbs, _ = env
    with dbs.begin() as db:
        db.get(Product, 3).sku = "OIL-1L"
    r = post_webhook(c, woo_payload(sku_qty=(("OIL-1L", 1),), payment_method="stripe"))
    with dbs() as db:
        assert db.get(Order, r.json()["order_id"]).payment_method == "prepaid"


def test_webhook_flags_address_mismatch_as_risk(env):
    c, dbs, _ = env
    with dbs.begin() as db:
        db.get(Product, 3).sku = "OIL-1L"
    r = post_webhook(c, woo_payload(sku_qty=(("OIL-1L", 1),), billing_city="Karachi", shipping_city="Lahore"))
    with dbs() as db:
        assert db.get(Order, r.json()["order_id"]).risk_score == 0.3


def test_webhook_redelivery_is_idempotent(env):
    c, dbs, _ = env
    with dbs.begin() as db:
        db.get(Product, 3).sku = "OIL-1L"
    payload = woo_payload(order_id=5099, sku_qty=(("OIL-1L", 1),))
    first = post_webhook(c, payload)
    second = post_webhook(c, payload)
    assert first.json()["order_id"] == second.json()["order_id"]
    assert second.json()["duplicate"] is True
    with dbs() as db:
        assert db.scalar(select(Order.id).where(Order.external_id == "woo-5099"))


def test_webhook_combines_duplicate_sku_line_items(env):
    c, dbs, _ = env
    with dbs.begin() as db:
        db.get(Product, 3).sku = "OIL-1L"
    r = post_webhook(c, woo_payload(sku_qty=(("OIL-1L", 1), ("OIL-1L", 2))))
    with dbs() as db:
        lines = list(db.scalars(select(OrderLine).where(OrderLine.order_id == r.json()["order_id"])))
        assert len(lines) == 1 and lines[0].quantity == 3
