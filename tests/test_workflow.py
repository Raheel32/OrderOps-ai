from datetime import timedelta
import hashlib
from sqlalchemy import select, func
from langgraph.types import Command
from app import services, worker
from app.models import Offer, Order, Outbox, Product, Job, utcnow


def create(client, *, product=1, risk=.1, payment="cod", external="test-1", items=None):
    response = client.post("/orders", json={"external_id": external,
        "customer_email": "customer@example.test", "risk_score": risk,
        "payment_method": payment, "preferred_brands": ["Vital"],
        "items": items or [{"product_id": product, "quantity": 1}]})
    assert response.status_code == 202, response.text
    return response.json()["order_id"]


def run(graph, order_id):
    worker.drive(graph, order_id)


def latest_offer(client, order_id):
    return [x["payload"] for x in client.get(f"/orders/{order_id}/outbox").json()
            if x["kind"] == "offer_email"][-1]


def answer(client, offer, decision="accept"):
    return client.post(f"/offers/{offer['offer_id']}/reply",
                       json={"token": offer["token"], "decision": decision})


def test_in_stock_and_replay(env):
    c, dbs, g = env
    oid = create(c, product=3)
    run(g, oid)
    run(g, oid)
    services.inventory(oid)
    services.fulfill(oid)
    assert c.get(f"/orders/{oid}").json()["status"] == "ready_for_fulfillment"
    with dbs() as db:
        assert db.get(Product, 3).stock == 9
        # order_confirmation (issued at intake) + fulfillment
        assert db.scalar(select(func.count()).select_from(Outbox)) == 2


def test_customer_accept_updates_price_and_partial_refund(env):
    c, dbs, g = env
    oid = create(c, payment="prepaid")
    run(g, oid)
    assert c.get(f"/orders/{oid}").json()["status"] == "awaiting_customer"
    offer = latest_offer(c, oid)
    assert offer["unit_price_paisa"] == 93100
    assert answer(c, offer).status_code == 202
    run(g, oid)
    detail = c.get(f"/orders/{oid}").json()
    assert detail["items"][0]["product_id"] == 2
    assert detail["final_total_paisa"] == 93100
    assert detail["recovered"] is True
    events = c.get(f"/orders/{oid}/outbox").json()
    assert [e for e in events if e["kind"] == "partial_refund_request"][0]["payload"]["amount_paisa"] == 6900
    with dbs() as db:
        assert db.get(Product, 2).stock == 19
    metric = c.get("/metrics").json()
    assert metric["revenue_recovery_rate"] == .931


def test_reject_drops_only_that_line_and_fulfills_the_rest(env):
    # Partial fulfillment: product 1 (no stock) gets rejected; product 3
    # (in stock) should still ship instead of cancelling the whole order.
    c, dbs, g = env
    oid = create(c, payment="prepaid", items=[{"product_id": 1, "quantity": 2}, {"product_id": 3, "quantity": 1}])
    run(g, oid)
    offer = latest_offer(c, oid)
    assert answer(c, offer, "reject").status_code == 202
    run(g, oid)
    detail = c.get(f"/orders/{oid}").json()
    assert detail["status"] == "ready_for_fulfillment"
    dropped = [x for x in detail["items"] if x["dropped"]]
    assert len(dropped) == 1 and dropped[0]["product_id"] == 1
    assert detail["final_total_paisa"] == 60000  # only product 3's line ships
    with dbs() as db:
        assert db.get(Product, 2).stock == 20  # offered alternative's hold released
        assert db.get(Product, 3).stock == 9   # product 3's line still reserved/shipped
    events = c.get(f"/orders/{oid}/outbox").json()
    dropped_refund = [e for e in events if e["kind"] == "partial_refund_request"][0]
    assert dropped_refund["payload"]["amount_paisa"] == 200000  # product 1's line, 2 units @ 1000


def test_all_lines_dropped_cancels_whole_order(env):
    # Both lines fail to resolve -> nothing left to fulfill -> full cancel.
    c, dbs, g = env
    oid = create(c, payment="prepaid", items=[{"product_id": 1, "quantity": 1}, {"product_id": 5, "quantity": 1}])
    run(g, oid)
    offer = latest_offer(c, oid)
    assert answer(c, offer, "reject").status_code == 202
    run(g, oid)
    detail = c.get(f"/orders/{oid}").json()
    assert detail["status"] == "refund_pending"
    with dbs() as db:
        assert db.get(Product, 2).stock == 20
    events = c.get(f"/orders/{oid}/outbox").json()
    # No double refund: the cancel-path refund_request should be 0 since both
    # lines were already refunded individually via drop_line().
    cancel_refund = [e for e in events if e["kind"] == "refund_request"][0]
    assert cancel_refund["payload"]["amount_paisa"] == 0


def test_fraud_pauses_until_audit_and_approval_continues(env):
    c, dbs, g = env
    oid = create(c, product=3, risk=.8)
    run(g, oid)
    with dbs() as db:
        assert db.get(Product, 3).stock == 10
    assert c.get(f"/orders/{oid}").json()["status"] == "manual_review"
    assert c.post(f"/orders/{oid}/audit", json={"decision": "approve"}).status_code == 202
    run(g, oid)
    assert c.get(f"/orders/{oid}").json()["status"] == "ready_for_fulfillment"


def test_fraud_rejection_cancels_cod(env):
    c, _, g = env
    oid = create(c, product=3, risk=.99)
    run(g, oid)
    c.post(f"/orders/{oid}/audit", json={"decision": "reject"})
    run(g, oid)
    assert c.get(f"/orders/{oid}").json()["status"] == "cancelled_cod"
    kinds = [e["kind"] for e in c.get(f"/orders/{oid}/outbox").json()]
    assert "cancel_cod" in kinds


def test_no_alternative(env):
    c, _, g = env
    oid = create(c, product=5, payment="prepaid")
    run(g, oid)
    assert c.get(f"/orders/{oid}").json()["status"] == "refund_pending"


def test_multi_line_negotiation_loop(env):
    c, _, g = env
    oid = create(c, items=[{"product_id": 1, "quantity": 1}, {"product_id": 4, "quantity": 1}])
    run(g, oid)
    first = latest_offer(c, oid)
    answer(c, first)
    run(g, oid)
    second = latest_offer(c, oid)
    assert second["offer_id"] != first["offer_id"]
    answer(c, second)
    run(g, oid)
    detail = c.get(f"/orders/{oid}").json()
    assert detail["status"] == "ready_for_fulfillment"
    assert len(detail["offers"]) == 2


def test_idempotent_input_and_conflicting_replay(env):
    c, _, _ = env
    oid = create(c)
    assert create(c) == oid
    result = c.post("/orders", json={"external_id": "test-1", "customer_email": "customer@example.test",
        "risk_score": .9, "items": [{"product_id": 1, "quantity": 1}]})
    assert result.status_code == 409


def test_offer_auth_duplicate_and_conflicting_decision(env):
    c, _, g = env
    oid = create(c)
    run(g, oid)
    offer = latest_offer(c, oid)
    assert answer(c, {**offer, "token": "bad-token-1234567890123456"}).status_code == 404
    assert answer(c, offer).status_code == 202
    assert answer(c, offer).json()["duplicate"] is True
    assert answer(c, offer, "reject").status_code == 409


def test_expiry_releases_offer_stock(env):
    c, dbs, g = env
    oid = create(c)
    run(g, oid)
    offer = latest_offer(c, oid)
    with dbs.begin() as db:
        db.get(Offer, offer["offer_id"]).expires_at = utcnow() - timedelta(seconds=1)
    assert answer(c, offer).status_code == 410
    worker.expire_offers()
    run(g, oid)
    with dbs() as db:
        assert db.get(Product, 2).stock == 20
        assert db.get(Order, oid).status == "cancelled_cod"


def test_timely_accept_processed_after_deadline(env):
    c, dbs, g = env
    oid = create(c)
    run(g, oid)
    offer = latest_offer(c, oid)
    answer(c, offer)
    with dbs.begin() as db:
        db.get(Offer, offer["offer_id"]).expires_at = utcnow() - timedelta(seconds=1)
    worker.expire_offers()
    run(g, oid)
    assert c.get(f"/orders/{oid}").json()["status"] == "ready_for_fulfillment"


def test_shared_stock_is_reserved_once_across_orders(env):
    c, dbs, g = env
    with dbs.begin() as db:
        db.get(Product, 3).stock = 1
    a = create(c, product=3, external="A")
    b = create(c, product=3, external="B")
    run(g, a)
    run(g, b)
    assert c.get(f"/orders/{a}").json()["status"] == "ready_for_fulfillment"
    assert c.get(f"/orders/{b}").json()["status"] == "cancelled_cod"
    with dbs() as db:
        assert db.get(Product, 3).stock == 0


def test_worker_recovers_after_effect_commits_before_checkpoint(env, monkeypatch):
    c, dbs, g = env
    oid = create(c)
    original = services.create_offer
    def fail_after_commit(*args):
        original(*args)
        raise RuntimeError("simulated crash after database commit")
    monkeypatch.setattr(services, "create_offer", fail_after_commit)
    assert worker.process_one(g)
    monkeypatch.setattr(services, "create_offer", original)
    with dbs.begin() as db:
        job = db.get(Job, oid)
        assert job.attempts == 1
        job.available_at = utcnow() - timedelta(seconds=1)
    assert worker.process_one(g)
    with dbs() as db:
        assert db.get(Product, 2).stock == 19
        assert db.scalar(select(func.count()).select_from(Offer)) == 1
        # order_confirmation (issued at intake) + the offer, not duplicated by the retry
        assert db.scalar(select(func.count()).select_from(Outbox)) == 2
        assert db.get(Job, oid).last_error is None


def test_auth_and_bad_order_validation(env):
    c, _, _ = env
    assert c.get("/products", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/orders", json={"external_id": "bad", "customer_email": "x@y",
        "risk_score": .1, "items": [{"product_id": 1, "quantity": 0}]}).status_code == 422
