"""Rule-based fraud scoring — the actual implementation of the "Fraud
scoring: rule-based" design decision. Previously, `risk_score` was only ever
a caller-supplied number with no internal logic computing it; this module is
that logic, used whenever a caller (the WooCommerce webhook, or the direct
API when it omits risk_score) doesn't already have a trusted score.

Four independent binary signals, each with a fixed weight, summed and capped
at 1.0. Two co-occurring signals are enough to clear the default 0.8 review
threshold; a single signal alone (e.g. a gift order shipped to someone else)
is not, since each one in isolation has legitimate innocent explanations.
These weights and thresholds are a reasonable starting point, not a
calibrated model — tune app/config.py's fraud_* settings against your own
order history once you have some.
"""
from datetime import timedelta
from sqlalchemy import func, select
from app.config import settings
from app.models import Order, utcnow
from app.services import aware

WEIGHT_VALUE_MULTIPLE = 0.4      # order far above this customer's own average
WEIGHT_ADDRESS_MISMATCH = 0.3    # billing and shipping addresses don't match
WEIGHT_NEW_CUSTOMER_HIGH_VALUE = 0.4  # no order history + a large first order
WEIGHT_VELOCITY = 0.4            # too many orders from this customer, too fast


def _customer_history(db, customer_email):
    """Prior orders for this email, most recent first. Excludes nothing by
    order_id since this is always called before the new order is inserted."""
    return list(db.scalars(select(Order).where(func.lower(Order.customer_email) ==
                customer_email.lower()).order_by(Order.created_at.desc())))


def _addresses_mismatch(billing: dict | None, shipping: dict | None) -> bool:
    if not billing or not shipping:
        return False  # No shipping address supplied (e.g. digital-only order): not a signal.
    keys = ("address_1", "city", "postcode", "country")
    return any((billing.get(k) or "").strip().lower() != (shipping.get(k) or "").strip().lower()
               for k in keys)


def score(db, customer_email: str, order_total_paisa: int,
          billing: dict | None = None, shipping: dict | None = None) -> float:
    """Computes a 0.0-1.0 risk score for a not-yet-created order. Call this
    with the same `db` session/transaction that will insert the order, so the
    velocity/history check sees a consistent view."""
    history = _customer_history(db, customer_email)
    triggered = []

    if history:
        average = sum(o.original_total_paisa for o in history) / len(history)
        if average > 0 and order_total_paisa > average * settings.fraud_value_multiple:
            triggered.append(("order_value_vs_average", WEIGHT_VALUE_MULTIPLE))
    else:
        if order_total_paisa >= settings.fraud_new_customer_paisa_threshold:
            triggered.append(("new_customer_high_value", WEIGHT_NEW_CUSTOMER_HIGH_VALUE))

    if _addresses_mismatch(billing, shipping):
        triggered.append(("billing_shipping_mismatch", WEIGHT_ADDRESS_MISMATCH))

    window_start = utcnow() - timedelta(minutes=settings.fraud_velocity_window_minutes)
    recent = sum(1 for o in history if aware(o.created_at) >= window_start)
    if recent >= settings.fraud_velocity_max_orders - 1:  # -1: this new order will be the Nth
        triggered.append(("order_velocity", WEIGHT_VELOCITY))

    return min(1.0, sum(weight for _, weight in triggered)), [name for name, _ in triggered]
