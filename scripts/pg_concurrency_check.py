"""Concurrency hardening check: does SELECT ... FOR UPDATE actually prevent
overselling the last unit of stock under real concurrent Postgres connections?

This CANNOT be verified by the pytest suite, because that suite runs on
SQLite, which doesn't have real concurrent row-locking the way Postgres does.
This script talks to your real database (settings.database_url — same one
your app already uses) with two genuinely parallel threads/connections.

It is SAFE to run against your Neon dev database: it creates its own
throwaway product, races against only that product, and deletes it
afterwards (even on failure). It does not touch your demo orders/products.

Usage:  python -m scripts.pg_concurrency_check
"""
import threading
import time
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Product


PROBE_ID = 999001  # Unlikely to collide with your seeded demo catalog (1-5).
RACERS = 8          # Number of concurrent "orders" competing for 1 unit of stock.


def make_probe_product():
    with SessionLocal.begin() as db:
        db.merge(Product(id=PROBE_ID, name="__concurrency_probe__", brand="__probe__",
                         substitution_group="__probe__", price_paisa=100, stock=1))


def cleanup_probe_product():
    with SessionLocal.begin() as db:
        row = db.get(Product, PROBE_ID)
        if row:
            db.delete(row)


def try_reserve_one_unit(results, index):
    """Mirrors app.services.lock_catalog()'s locking pattern exactly:
    SELECT ... FOR UPDATE, then check-and-decrement, inside one transaction."""
    try:
        with SessionLocal.begin() as db:
            product = db.scalar(select(Product).where(Product.id == PROBE_ID).with_for_update())
            # A short, deliberate window between the lock and the decrement:
            # if FOR UPDATE isn't actually serializing these transactions,
            # this is where a second thread would see stale stock and both
            # would succeed, oversold.
            time.sleep(0.05)
            if product.stock >= 1:
                product.stock -= 1
                results[index] = "reserved"
            else:
                results[index] = "rejected"
    except Exception as exc:
        results[index] = f"error: {type(exc).__name__}: {exc}"


def main():
    print(f"Connecting to your configured database and racing {RACERS} threads "
          f"for 1 unit of stock...")
    make_probe_product()
    try:
        results = [None] * RACERS
        threads = [threading.Thread(target=try_reserve_one_unit, args=(results, i))
                  for i in range(RACERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with SessionLocal() as db:
            final_stock = db.get(Product, PROBE_ID).stock

        reserved = results.count("reserved")
        rejected = results.count("rejected")
        errors = [r for r in results if r and r.startswith("error")]

        print(f"\nResults: {reserved} reserved, {rejected} rejected, {len(errors)} errors")
        print(f"Final stock: {final_stock} (started at 1)")
        for e in errors:
            print(f"  {e}")

        if reserved == 1 and final_stock == 0 and not errors:
            print("\nPASS: exactly one thread won the last unit. No overselling, "
                  "row locking is working as intended.")
        else:
            print("\nFAIL: this indicates a real overselling risk under concurrent load. "
                  "Do not treat this as a demo-only issue — investigate before relying "
                  "on this code path with real traffic.")
    finally:
        cleanup_probe_product()
        print("\nProbe product cleaned up.")


if __name__ == "__main__":
    main()
