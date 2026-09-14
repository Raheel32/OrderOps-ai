"""Exercise one replacement via HTTP. Requires running API, worker and seed data."""
import time
from uuid import uuid4
import httpx
from app.config import settings


def wait_for(client, order_id, states, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/orders/{order_id}")
        response.raise_for_status()
        result = response.json()
        if result["status"] in states:
            return result
        if result["job"]["attempts"] >= 5:
            raise RuntimeError(f"Worker exhausted retries: {result['job']['last_error']}")
        time.sleep(.5)
    raise TimeoutError("Order did not advance. Check the separate worker terminal.")


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=15,
                      headers={"X-API-Key": settings.admin_api_key}) as client:
        response = client.post("/orders", json={
            "external_id": f"demo-{uuid4()}", "customer_email": "customer@example.test",
            "risk_score": .1, "payment_method": "prepaid", "preferred_brands": ["Vital"],
            "items": [{"product_id": 1, "quantity": 1}]})
        response.raise_for_status()
        oid = response.json()["order_id"]
        print("Created:", oid)
        first = wait_for(client, oid, {"awaiting_customer", "refund_pending"})
        if first["status"] == "refund_pending":
            raise RuntimeError("Demo alternative stock exhausted; inspect /products.")
        events = client.get(f"/orders/{oid}/outbox").json()
        offer = next(x["payload"] for x in events if x["kind"] == "offer_email")
        print("Demo message:", offer["text"])
        response = client.post(f"/offers/{offer['offer_id']}/reply",
            json={"token": offer["token"], "decision": "accept"})
        response.raise_for_status()
        final = wait_for(client, oid, {"ready_for_fulfillment"})
        print("Status:", final["status"])
        print("Final total (PKR):", final["final_total_paisa"] / 100)
        print("No real message, payment, or warehouse action was performed.")


if __name__ == "__main__":
    main()
