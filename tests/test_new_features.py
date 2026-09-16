from datetime import timedelta
from app import auth
from app.models import Job, User, utcnow
from tests.test_workflow import answer, create, latest_offer, run


def confirmation_token(client, order_id):
    events = client.get(f"/orders/{order_id}/outbox").json()
    return [e["payload"]["cancel_token"] for e in events if e["kind"] == "order_confirmation"][-1]


# --- Customer cancellation before resolution starts ------------------------

def test_customer_can_cancel_before_resolution_starts(env):
    c, dbs, g = env
    oid = create(c, payment="prepaid")
    token = confirmation_token(c, oid)
    response = c.post(f"/orders/{oid}/cancel", json={"token": token})
    assert response.status_code == 202
    assert c.get(f"/orders/{oid}").json()["status"] == "refund_pending"
    events = c.get(f"/orders/{oid}/outbox").json()
    assert [e for e in events if e["kind"] == "refund_request"][0]["payload"]["amount_paisa"] == 100000


def test_customer_cannot_cancel_after_resolution_starts(env):
    c, _, g = env
    oid = create(c)
    token = confirmation_token(c, oid)
    run(g, oid)  # fraud/inventory have now run
    response = c.post(f"/orders/{oid}/cancel", json={"token": token})
    assert response.status_code == 409


def test_customer_cancel_rejects_bad_token(env):
    c, _, _ = env
    oid = create(c)
    response = c.post(f"/orders/{oid}/cancel", json={"token": "wrong-token-1234567890123456"})
    assert response.status_code == 404


def test_customer_cancel_is_idempotent_on_retry_with_same_token(env):
    c, _, _ = env
    oid = create(c)
    token = confirmation_token(c, oid)
    assert c.post(f"/orders/{oid}/cancel", json={"token": token}).status_code == 202
    # Second call: order is no longer "received", so it correctly reports
    # that resolution (in this case, the cancellation itself) already happened.
    assert c.post(f"/orders/{oid}/cancel", json={"token": token}).status_code == 409


# --- Per-user auth / RBAC ---------------------------------------------------

def make_user(dbs, email, role, password="a-strong-password"):
    with dbs.begin() as db:
        db.add(User(email=email, role=role, password_hash=auth.hash_password(password)))


def login(client, email, password="a-strong-password"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_admin_register_requires_admin_role(env):
    c, dbs, _ = env
    make_user(dbs, "viewer@example.test", "viewer")
    token = login(c, "viewer@example.test")
    c2 = c.__class__(app=c.app)
    r = c2.post("/auth/register", json={"email": "new@example.test", "password": "a-strong-password"},
                headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_login_wrong_password_rejected(env):
    c, dbs, _ = env
    make_user(dbs, "someone@example.test", "viewer")
    r = c.post("/auth/login", json={"email": "someone@example.test", "password": "not-it"})
    assert r.status_code == 401


def test_viewer_can_read_but_not_create_orders(env):
    c, dbs, _ = env
    make_user(dbs, "viewer2@example.test", "viewer")
    token = login(c, "viewer2@example.test")
    c2 = c.__class__(app=c.app)
    c2.headers["Authorization"] = f"Bearer {token}"
    assert c2.get("/products").status_code == 200
    assert c2.post("/orders", json={"external_id": "x", "customer_email": "a@b.test",
                                     "risk_score": .1, "items": [{"product_id": 1, "quantity": 1}]}
                   ).status_code == 401


def test_auditor_can_decide_audit_but_not_create_orders(env):
    c, dbs, g = env
    oid = create(c, product=3, risk=.9)
    run(g, oid)
    make_user(dbs, "auditor@example.test", "auditor")
    token = login(c, "auditor@example.test")
    c2 = c.__class__(app=c.app)
    c2.headers["Authorization"] = f"Bearer {token}"
    assert c2.post(f"/orders/{oid}/audit", json={"decision": "approve"}).status_code == 202
    assert c2.post("/orders", json={"external_id": "y", "customer_email": "a@b.test",
                                     "risk_score": .1, "items": [{"product_id": 1, "quantity": 1}]}
                   ).status_code == 401


# --- Pending-orders worklist endpoint ---------------------------------------

def test_orders_pending_failed_surfaces_exhausted_retries(env, monkeypatch):
    c, dbs, g = env
    from app import services, worker
    oid = create(c)
    monkeypatch.setattr(services, "create_offer",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("simulated permanent failure")))
    for _ in range(5):
        with dbs.begin() as db:
            job = db.get(Job, oid)
            job.available_at = utcnow() - timedelta(seconds=1)
        worker.process_one(g)
    with dbs() as db:
        job = db.get(Job, oid)
        assert job.pending is False and job.attempts == 5

    failed = c.get("/orders/pending?kind=failed").json()
    assert len(failed) == 1 and failed[0]["id"] == oid
    assert failed[0]["job"]["attempts"] == 5
    assert "RuntimeError" in failed[0]["job"]["last_error"]
    assert "cancel_token_hash" not in failed[0]

    assert c.post(f"/orders/{oid}/retry").status_code == 202
    with dbs() as db:
        job = db.get(Job, oid)
        assert job.pending is True and job.attempts == 0 and job.last_error is None
    assert c.get("/orders/pending?kind=failed").json() == []


def test_orders_pending_lists_only_manual_review_and_awaiting_customer(env):
    c, _, g = env
    audit_order = create(c, product=3, risk=.9, external="pending-audit")
    run(g, audit_order)
    offer_order = create(c, external="pending-offer")
    run(g, offer_order)
    done_order = create(c, product=3, external="pending-done")
    run(g, done_order)

    all_pending = {o["id"] for o in c.get("/orders/pending").json()}
    assert all_pending == {audit_order, offer_order}

    audit_only = {o["id"] for o in c.get("/orders/pending?kind=audit").json()}
    assert audit_only == {audit_order}

    customer_only = {o["id"] for o in c.get("/orders/pending?kind=customer").json()}
    assert customer_only == {offer_order}
