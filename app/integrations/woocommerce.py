"""WooCommerce order-webhook support.

Set up in WordPress admin: WooCommerce > Settings > Advanced > Webhooks >
Add webhook. Topic: "Order created". Delivery URL: this app's
/webhooks/woocommerce/order-created. Secret: same value as
settings.woocommerce_webhook_secret.

WooCommerce signs each delivery with header X-WC-Webhook-Signature:
base64(HMAC-SHA256(raw_request_body, secret)). It must be verified against
the *raw* bytes, before any JSON parsing — a re-serialized body will not
produce the same signature even with identical field values.
"""
import base64
import hashlib
import hmac


def verify_signature(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    expected = base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest())
    try:
        return hmac.compare_digest(expected, signature_header.encode())
    except (AttributeError, UnicodeEncodeError):
        return False


def parse_order(payload: dict) -> dict:
    """Normalizes a WooCommerce order payload into the fields OrderOps needs.
    Raises KeyError/ValueError on a payload that doesn't look like a real
    WooCommerce order — the caller should turn that into a 422."""
    billing = payload.get("billing") or {}
    shipping = payload.get("shipping") or {}
    email = billing.get("email")
    if not email:
        raise ValueError("Order has no billing email")
    line_items = payload.get("line_items") or []
    if not line_items:
        raise ValueError("Order has no line items")
    items = []
    for li in line_items:
        sku = (li.get("sku") or "").strip()
        if not sku:
            raise ValueError(f"Line item {li.get('id')} has no SKU set in WooCommerce")
        items.append({"sku": sku, "quantity": int(li.get("quantity", 0))})
    # WooCommerce's own payment gateway id. "cod" is WooCommerce's own code
    # for Cash on Delivery; anything else (stripe/paypal/bacs/etc.) is
    # treated as already collected -> "prepaid". Adjust this mapping if your
    # store uses a COD-like gateway under a different id.
    payment_method = "cod" if payload.get("payment_method") == "cod" else "prepaid"
    return {
        "external_id": f"woo-{payload['id']}",
        "customer_email": email,
        "payment_method": payment_method,
        "items": items,
        "billing": billing,
        "shipping": shipping,
    }
