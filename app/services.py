from datetime import timedelta, timezone
import hashlib
import secrets
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import Audit, Job, Offer, Order, OrderLine, Outbox, Product, utcnow, uid
from app.policy import choose_alternative, message_for_offer, offer_price
from app.agent import recommend


def aware(value):
    # SQLite is only used for unit tests; PostgreSQL retains timezone information.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def audit(db, order_id, action, **detail):
    db.add(Audit(order_id=order_id, action=action, detail=detail))


def lines_for(db, order_id):
    return list(db.scalars(select(OrderLine).where(OrderLine.order_id == order_id)
                           .order_by(OrderLine.id)))


def lock_catalog(db):
    # Small demo catalog: lock in a stable order to prevent overselling/deadlocks.
    # At scale, lock only affected SKU groups, always in the same sorted order.
    return {p.id: p for p in db.scalars(select(Product).order_by(Product.id).with_for_update())}


def risk_route(order_id):
    with SessionLocal() as db:
        return db.get(Order, order_id).risk_score >= settings.risk_threshold


def flag_audit(order_id):
    with SessionLocal.begin() as db:
        order = db.get(Order, order_id, with_for_update=True)
        if order.status != "manual_review":
            order.status = "manual_review"
            audit(db, order_id, "manual_review_required")


def inventory(order_id):
    with SessionLocal.begin() as db:
        order = db.get(Order, order_id, with_for_update=True)
        products = lock_catalog(db)
        missing = []
        any_active = False
        for line in lines_for(db, order_id):
            if line.dropped:
                continue
            any_active = True
            if line.reserved:
                continue
            product = products[line.product_id]
            if product.stock >= line.quantity:
                product.stock -= line.quantity
                line.reserved = True
                audit(db, order_id, "stock_reserved", line_id=line.id, product_id=product.id)
            else:
                missing.append(line.id)
        if missing:
            order.had_shortage = True
        # all_dropped: every line has been excluded from fulfillment (partial-
        # fulfillment rejected/no-alternative on every line) — nothing left to ship.
        return {"missing_line": missing[0] if missing else None, "all_dropped": not any_active}


def create_offer(order_id, line_id):
    # Model calls happen outside stock-locking transactions. Revalidate below.
    with SessionLocal() as db:
        line = db.get(OrderLine, line_id)
        order = db.get(Order, order_id)
        products = list(db.scalars(select(Product)))
        hint = recommend(products, db.get(Product, line.original_product_id), line.quantity,
                         line.unit_price_paisa, order.preferred_brands)
    with SessionLocal.begin() as db:
        order = db.get(Order, order_id, with_for_update=True)
        existing = db.scalar(select(Offer).where(Offer.line_id == line_id))
        if existing:
            return {"offer_id": existing.id}
        products = lock_catalog(db)
        line = db.get(OrderLine, line_id)
        original = products[line.original_product_id]
        alternative = choose_alternative(products.values(), original, line.quantity,
                                         line.unit_price_paisa, order.preferred_brands,
                                         settings.discount_bps)
        if hint in products:
            validated_hint = choose_alternative([products[hint]], original, line.quantity,
                line.unit_price_paisa, order.preferred_brands, settings.discount_bps)
            alternative = validated_hint or alternative
        if alternative is None:
            return {"offer_id": None}
        token = secrets.token_urlsafe(32)
        offer = Offer(id=uid(), order_id=order_id, line_id=line_id, product_id=alternative.id,
                      unit_price_paisa=offer_price(alternative.price_paisa, settings.discount_bps),
                      token_hash=hashlib.sha256(token.encode()).hexdigest(),
                      expires_at=utcnow() + timedelta(hours=settings.offer_ttl_hours))
        alternative.stock -= line.quantity
        db.add(offer)
        order.status = "awaiting_customer"
        order.first_action_at = order.first_action_at or utcnow()
        # Outbox and reservation commit together. This does not send a message.
        db.add(Outbox(event_key=f"offer:{offer.id}", order_id=order_id, kind="offer_email",
                      payload={"offer_id": offer.id, "to": order.customer_email,
                               "token": token, "expires_at": offer.expires_at.isoformat(),
                               "product_id": alternative.id, "quantity": line.quantity,
                               "unit_price_paisa": offer.unit_price_paisa,
                               "text": message_for_offer(original, alternative, line.quantity,
                                                         offer.unit_price_paisa)}))
        audit(db, order_id, "offer_created", offer_id=offer.id)
        return {"offer_id": offer.id}


def apply_offer(order_id, offer_id):
    with SessionLocal.begin() as db:
        order = db.get(Order, order_id, with_for_update=True)
        offer = db.get(Offer, offer_id, with_for_update=True)
        if offer.status == "accepted":
            return
        # Callback validates token and expiry; a timely accepted decision remains
        # valid even if the worker processes it after the deadline.
        if offer.decision != "accept" or not offer.held:
            raise ValueError("Offer must have a valid accepted decision and stock hold")
        line = db.get(OrderLine, offer.line_id)
        line.product_id = offer.product_id
        line.unit_price_paisa = offer.unit_price_paisa
        line.reserved = True
        offer.held = False  # Reservation ownership moves to the order line.
        offer.status = "accepted"
        order.final_total_paisa = sum(x.quantity * x.unit_price_paisa for x in lines_for(db, order_id))
        audit(db, order_id, "replacement_accepted", offer_id=offer_id)


def drop_line(order_id, line_id):
    """Exclude one line from fulfillment (customer rejected its replacement
    offer, or no compatible alternative existed) without cancelling the rest
    of the order. Any stock hold on that line's offer is released and, for
    prepaid orders, the line's paid value is queued for refund."""
    with SessionLocal.begin() as db:
        order = db.get(Order, order_id, with_for_update=True)
        line = db.get(OrderLine, line_id, with_for_update=True)
        if line.dropped:
            return  # Idempotent if this node is replayed.
        offer = db.scalar(select(Offer).where(Offer.line_id == line_id))
        if offer and offer.held:
            products = lock_catalog(db)
            products[offer.product_id].stock += line.quantity
            offer.held = False
        if offer and offer.status == "pending":
            offer.status = offer.decision or "cancelled"
        line.dropped = True
        payload = {"line_id": line.id, "product_id": line.original_product_id, "quantity": line.quantity}
        if order.payment_method == "prepaid":
            payload["amount_paisa"] = line.original_unit_price_paisa * line.quantity
            db.add(Outbox(event_key=f"line_drop:{line.id}", order_id=order_id,
                          kind="partial_refund_request", payload=payload))
        else:
            db.add(Outbox(event_key=f"line_drop:{line.id}", order_id=order_id,
                          kind="line_dropped_cod", payload=payload))
        audit(db, order_id, "line_dropped", line_id=line.id)


def fulfill(order_id):
    with SessionLocal.begin() as db:
        order = db.get(Order, order_id, with_for_update=True)
        if order.status == "ready_for_fulfillment":
            return
        lines = [x for x in lines_for(db, order_id) if not x.dropped]
        if not lines or not all(x.reserved for x in lines):
            raise ValueError("Cannot fulfill without all active-line inventory reserved")
        order.final_total_paisa = sum(x.quantity * x.unit_price_paisa for x in lines)
        order.recovered = order.had_shortage
        order.status = "ready_for_fulfillment"
        order.first_action_at = order.first_action_at or utcnow()
        db.add(Outbox(event_key=f"fulfill:{order_id}", order_id=order_id, kind="fulfillment",
                      payload={"items": [{"product_id": x.product_id, "quantity": x.quantity}
                                         for x in lines], "total_paisa": order.final_total_paisa}))
        # Only reflects accepted cheaper-replacement savings on lines that shipped;
        # any dropped line's refund was already queued separately in drop_line().
        difference = sum((x.original_unit_price_paisa - x.unit_price_paisa) * x.quantity for x in lines)
        if order.payment_method == "prepaid" and difference > 0:
            db.add(Outbox(event_key=f"adjustment:{order_id}", order_id=order_id,
                          kind="partial_refund_request", payload={"amount_paisa": difference}))
        audit(db, order_id, "fulfillment_requested", recovered=order.recovered)


def cancel(order_id):
    """Cancels the whole order: used for a manual-review rejection (nothing
    reserved yet) and for the all-lines-dropped case under partial fulfillment
    (each line's holds/refund were already released/queued in drop_line())."""
    with SessionLocal.begin() as db:
        order = db.get(Order, order_id, with_for_update=True)
        if order.status in {"refund_pending", "cancelled_cod"}:
            return
        products = lock_catalog(db)
        lines = lines_for(db, order_id)
        by_id = {x.id: x for x in lines}
        # Refund only lines not already dropped/refunded individually, so a
        # prior partial refund from drop_line() is never counted twice.
        refund_paisa = sum(x.original_unit_price_paisa * x.quantity for x in lines if not x.dropped)
        for line in lines:
            if line.reserved:
                products[line.product_id].stock += line.quantity
                line.reserved = False
        for offer in db.scalars(select(Offer).where(Offer.order_id == order_id)):
            if offer.held:
                products[offer.product_id].stock += by_id[offer.line_id].quantity
                offer.held = False
            if offer.status == "pending":
                offer.status = offer.decision or "cancelled"
        order.status = "refund_pending" if order.payment_method == "prepaid" else "cancelled_cod"
        order.first_action_at = order.first_action_at or utcnow()
        db.add(Outbox(event_key=f"cancel:{order_id}", order_id=order_id,
                      kind="refund_request" if order.payment_method == "prepaid" else "cancel_cod",
                      payload={"amount_paisa": refund_paisa if order.payment_method == "prepaid" else 0}))
        audit(db, order_id, "cancellation_requested", status=order.status)


def cancel_before_resolution(order_id):
    """Customer-initiated cancellation while the order is still `received`
    (fraud/inventory has not started, nothing is reserved). Disables the job
    so the worker never picks it up. Returns False if resolution already
    began, in which case the caller should reject the request."""
    with SessionLocal.begin() as db:
        order = db.get(Order, order_id, with_for_update=True)
        job = db.get(Job, order_id, with_for_update=True)
        if order.status != "received":
            return False
        job.pending = False
        order.status = "refund_pending" if order.payment_method == "prepaid" else "cancelled_cod"
        order.first_action_at = order.first_action_at or utcnow()
        db.add(Outbox(event_key=f"customer_cancel:{order_id}", order_id=order_id,
                      kind="refund_request" if order.payment_method == "prepaid" else "cancel_cod",
                      payload={"amount_paisa": order.original_total_paisa
                               if order.payment_method == "prepaid" else 0}))
        audit(db, order_id, "customer_cancelled_before_resolution")
        return True
