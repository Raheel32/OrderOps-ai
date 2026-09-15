import hashlib
import json
import secrets
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from app import auth
from app.config import settings
from app.db import SessionLocal
from app.models import Audit, Job, Offer, Order, OrderLine, Outbox, Product, User, utcnow
from app.schemas import (AuditDecision, CustomerCancel, CustomerReply, OrderInput,
                          TokenOut, UserCreate, UserLogin)
from app.services import audit, aware, cancel_before_resolution, lines_for

app = FastAPI(title="OrderOps AI — local learning MVP", version="0.1.0")

# Role floors per route: viewer (read-only) < auditor (+ audit decisions) < admin (+ everything else).
view = Depends(auth.require_role("viewer"))
audit_role = Depends(auth.require_role("auditor"))
admin = Depends(auth.require_role("admin"))


def serialize(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def get_order_or_404(db, order_id):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


def wake(job):
    job.pending, job.attempts, job.available_at, job.last_error = True, 0, utcnow(), None


@app.post("/auth/register", status_code=201, dependencies=[admin])
def register_user(body: UserCreate):
    """Admin-only: creates a per-user login. Bootstrap the first admin via
    scripts.create_admin (there is no user yet to authorize this endpoint)."""
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email == body.email)):
            raise HTTPException(409, "Email already registered")
        user = User(email=body.email, role=body.role, password_hash=auth.hash_password(body.password))
        db.add(user)
        db.flush()
        return {"id": user.id, "email": user.email, "role": user.role}


@app.post("/auth/login", response_model=TokenOut)
def login(body: UserLogin):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == body.email))
        if not user or not auth.verify_password(body.password, user.password_hash):
            raise HTTPException(401, "Invalid email or password")
        token = auth.create_access_token(user.id, user.email, user.role)
        return TokenOut(access_token=token, role=user.role)


@app.get("/health")
def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Database unavailable")
    return {"status": "ok", "integrations": "demo_only"}


@app.get("/products", dependencies=[view])
def products():
    with SessionLocal() as db:
        return [serialize(p) for p in db.scalars(select(Product).order_by(Product.id))]


@app.get("/dashboard", dependencies=[view])
def dashboard():
    """Bounded admin snapshot. Never expose offer tokens in the polling response."""
    with SessionLocal() as db:
        catalog = {p.id: p for p in db.scalars(select(Product).order_by(Product.id))}
        orders = list(db.scalars(select(Order).order_by(Order.created_at.desc(), Order.id).limit(100)))
        ids = [o.id for o in orders]
        lines = list(db.scalars(select(OrderLine).where(OrderLine.order_id.in_(ids)).order_by(OrderLine.id)))
        offers = list(db.scalars(select(Offer).where(Offer.order_id.in_(ids))))
        rows = []
        for order in orders:
            row = serialize(order)
            row.pop("request_hash", None)
            row.pop("cancel_token_hash", None)
            row["items"] = [{**serialize(i), "name": catalog[i.product_id].name}
                            for i in lines if i.order_id == order.id]
            row["offers"] = [{**{k: v for k, v in serialize(o).items() if k != "token_hash"},
                              "name": catalog[o.product_id].name,
                              "quantity": next(i.quantity for i in lines if i.id == o.line_id)}
                             for o in offers if o.order_id == order.id]
            rows.append(row)
        events = []
        for e in db.scalars(select(Outbox).order_by(Outbox.created_at.desc(), Outbox.id.desc()).limit(30)):
            payload = {k: v for k, v in e.payload.items() if k not in {"token", "to"}}
            if not payload.get("text"):
                summary = {"fulfillment": "Stock reserved; order ready for fulfillment.",
                           "refund_request": "Full refund requested; provider confirmation pending.",
                           "partial_refund_request": "Price difference refund requested; confirmation pending.",
                           "cancel_cod": "COD order cancelled. No payment refund required."}.get(e.kind, e.kind)
                amount = payload.get("amount_paisa")
                payload["text"] = f"#{e.order_id[:5]} · {summary}" + (f" Rs. {amount / 100:,.2f}" if amount else "")
            events.append({**serialize(e), "payload": payload})
        counts = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())
        recovered = db.scalar(select(func.coalesce(func.sum(Order.final_total_paisa), 0))
                              .where(Order.recovered.is_(True)))
        return {"products": [serialize(p) for p in catalog.values()], "orders": rows,
                "events": events, "metrics": {"orders": sum(counts.values()),
                "ready": counts.get("ready_for_fulfillment", 0),
                "refunds": counts.get("refund_pending", 0), "recovered_value_paisa": recovered}}


@app.post("/orders", status_code=202, dependencies=[admin])
def create_order(body: OrderInput):
    digest = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    with SessionLocal.begin() as db:
        existing = db.scalar(select(Order).where(Order.external_id == body.external_id))
        if existing:
            if existing.request_hash != digest:
                raise HTTPException(409, "external_id already used with different data")
            return {"order_id": existing.id, "status": existing.status, "duplicate": True}
        catalog = {p.id: p for p in db.scalars(select(Product).where(
            Product.id.in_([x.product_id for x in body.items])))}
        if len(catalog) != len(body.items):
            raise HTTPException(422, "Unknown product_id")
        total = sum(catalog[x.product_id].price_paisa * x.quantity for x in body.items)
        cancel_token = secrets.token_urlsafe(32)
        order = Order(external_id=body.external_id, request_hash=digest,
                      customer_email=body.customer_email, preferred_brands=body.preferred_brands,
                      risk_score=body.risk_score, payment_method=body.payment_method,
                      original_total_paisa=total, final_total_paisa=total,
                      cancel_token_hash=hashlib.sha256(cancel_token.encode()).hexdigest())
        db.add(order)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            # Another concurrent request may have won the same external ID.
            with SessionLocal() as retry_db:
                other = retry_db.scalar(select(Order).where(Order.external_id == body.external_id))
                if other and other.request_hash == digest:
                    return {"order_id": other.id, "status": other.status, "duplicate": True}
            raise HTTPException(409, "external_id conflict")
        for item in body.items:
            price = catalog[item.product_id].price_paisa
            db.add(OrderLine(order_id=order.id, original_product_id=item.product_id,
                             product_id=item.product_id, quantity=item.quantity,
                             unit_price_paisa=price, original_unit_price_paisa=price))
        db.add(Job(order_id=order.id))
        audit(db, order.id, "order_received")
        # Demo email: this token is the customer's only way to self-cancel
        # via POST /orders/{id}/cancel before resolution starts.
        db.add(Outbox(event_key=f"confirm:{order.id}", order_id=order.id, kind="order_confirmation",
                      payload={"to": body.customer_email, "cancel_token": cancel_token}))
        return {"order_id": order.id, "status": "received", "duplicate": False}


@app.get("/orders/pending", dependencies=[view])
def orders_pending(kind: str = "all"):
    """Orders currently sitting in manual_review and/or awaiting_customer,
    for an admin/auditor worklist. kind: 'audit' | 'customer' | 'all'."""
    statuses = {"audit": ["manual_review"], "customer": ["awaiting_customer"],
                "all": ["manual_review", "awaiting_customer"]}.get(kind)
    if statuses is None:
        raise HTTPException(422, "kind must be one of: audit, customer, all")
    with SessionLocal() as db:
        orders = list(db.scalars(select(Order).where(Order.status.in_(statuses))
                                 .order_by(Order.created_at)))
        ids = [o.id for o in orders]
        offers = list(db.scalars(select(Offer).where(Offer.order_id.in_(ids), Offer.status == "pending")))
        rows = []
        for o in orders:
            row = serialize(o)
            row.pop("request_hash", None)
            row.pop("cancel_token_hash", None)
            row["pending_offers"] = [{k: v for k, v in serialize(x).items() if k != "token_hash"}
                                     for x in offers if x.order_id == o.id]
            rows.append(row)
        return rows


@app.post("/orders/{order_id}/cancel", status_code=202)
def cancel_order(order_id: str, body: CustomerCancel):
    """Customer self-service cancellation, valid only before shortage
    resolution has started (order still in `received`). Once fraud/inventory
    has begun, use the normal offer/audit flow instead."""
    digest = hashlib.sha256(body.token.encode()).hexdigest()
    with SessionLocal() as db:
        order = get_order_or_404(db, order_id)
        if not order.cancel_token_hash or not secrets.compare_digest(order.cancel_token_hash, digest):
            raise HTTPException(404, "Order not found")
    if not cancel_before_resolution(order_id):
        raise HTTPException(409, "Resolution has already started; this order can no longer be self-cancelled")
    return {"accepted": True}


@app.get("/orders/{order_id}", dependencies=[view])
def order_detail(order_id: str):
    with SessionLocal() as db:
        result = serialize(get_order_or_404(db, order_id))
        result.pop("request_hash")
        result.pop("cancel_token_hash", None)
        result["items"] = [serialize(x) for x in lines_for(db, order_id)]
        result["offers"] = [{k: v for k, v in serialize(o).items() if k != "token_hash"}
                            for o in db.scalars(select(Offer).where(Offer.order_id == order_id))]
        result["job"] = serialize(db.get(Job, order_id))
        return result


@app.post("/orders/{order_id}/audit", status_code=202, dependencies=[audit_role])
def decide_audit(order_id: str, body: AuditDecision):
    with SessionLocal.begin() as db:
        # All callback/retry handlers lock Job before changing graph-related data.
        job = db.get(Job, order_id, with_for_update=True)
        order = get_order_or_404(db, order_id)
        if order.manual_decision:
            if order.manual_decision != body.decision:
                raise HTTPException(409, "Audit decision already recorded")
            return {"accepted": True, "duplicate": True}
        if order.status != "manual_review":
            raise HTTPException(409, "Order is not awaiting audit")
        order.manual_decision = body.decision
        audit(db, order_id, "audit_decision", decision=body.decision)
        wake(job)
        return {"accepted": True}


@app.post("/offers/{offer_id}/reply", status_code=202)
def reply(offer_id: str, body: CustomerReply):
    # Bearer capability scoped to this one offer; do not log request bodies.
    digest = hashlib.sha256(body.token.encode()).hexdigest()
    with SessionLocal() as db:
        offer = db.get(Offer, offer_id)
        if offer is None or not secrets.compare_digest(offer.token_hash, digest):
            raise HTTPException(404, "Offer not found")
        order_id = offer.order_id
    with SessionLocal.begin() as db:
        job = db.get(Job, order_id, with_for_update=True)
        offer = db.get(Offer, offer_id, with_for_update=True)
        if offer.decision:
            if offer.decision != body.decision:
                raise HTTPException(409, "Offer already decided or expired")
            return {"accepted": True, "duplicate": True}
        if offer.status != "pending" or aware(offer.expires_at) <= utcnow():
            raise HTTPException(410, "Offer expired or closed")
        offer.decision = body.decision
        audit(db, order_id, "customer_decision", offer_id=offer_id, decision=body.decision)
        wake(job)
        return {"accepted": True}


@app.post("/orders/{order_id}/retry", status_code=202, dependencies=[admin])
def retry(order_id: str):
    with SessionLocal.begin() as db:
        job = db.get(Job, order_id, with_for_update=True)
        get_order_or_404(db, order_id)
        wake(job)
        return {"queued": True}


@app.get("/orders/{order_id}/outbox", dependencies=[view])
def outbox(order_id: str):
    with SessionLocal() as db:
        get_order_or_404(db, order_id)
        return [serialize(x) for x in db.scalars(select(Outbox).where(Outbox.order_id == order_id)
                                                 .order_by(Outbox.id))]


@app.get("/orders/{order_id}/audit-log", dependencies=[view])
def audit_log(order_id: str):
    with SessionLocal() as db:
        get_order_or_404(db, order_id)
        return [serialize(x) for x in db.scalars(select(Audit).where(Audit.order_id == order_id)
                                                 .order_by(Audit.id))]


@app.get("/metrics", dependencies=[view])
def metrics():
    with SessionLocal() as db:
        orders = list(db.scalars(select(Order)))
        shortages = [o for o in orders if o.had_shortage]
        recovered = [o for o in shortages if o.recovered]
        denominator = sum(o.original_total_paisa for o in shortages)
        numerator = sum(o.final_total_paisa for o in recovered)
        times = sorted((aware(o.first_action_at) - aware(o.created_at)).total_seconds()
                       for o in orders if o.first_action_at)
        # Nearest-rank percentile; queued offer time is a demo proxy for send time.
        import math
        return {"orders": len(orders), "shortage_orders": len(shortages),
                "recovered_orders": len(recovered), "recovered_value_paisa": numerator,
                "revenue_recovery_rate": numerator / denominator if denominator else None,
                "order_recovery_rate": len(recovered) / len(shortages) if shortages else None,
                "processing_seconds_p50": times[math.ceil(.5 * len(times)) - 1] if times else None,
                "processing_seconds_p95": times[math.ceil(.95 * len(times)) - 1] if times else None,
                "exhausted_jobs": db.scalar(select(func.count()).select_from(Job)
                                            .where(Job.attempts >= 5)),
                "uptime": "Measure with an external /health probe; not inferred from orders",
                "measurement": "All-time demo metrics; fulfillment-ready is a recovery proxy"}


# Compiled frontend is included in the downloadable project. No Node.js is
# required to run it; rebuilding after frontend edits is documented separately.
STATIC_DIR = Path(__file__).resolve().parent / "static"
if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="dashboard-assets")


@app.get("/", include_in_schema=False)
def dashboard_page():
    page = STATIC_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(404, "Dashboard build missing. Build frontend and run scripts.build_frontend.")
    return FileResponse(page)
