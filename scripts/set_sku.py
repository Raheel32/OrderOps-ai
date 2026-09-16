"""Assign a SKU to a product so WooCommerce webhook orders can map to it.

Find the real SKU for each product in WooCommerce: WP Admin > Products >
(edit product) > Inventory tab > SKU field.

Usage: python -m scripts.set_sku <product_id> <sku>
Example: python -m scripts.set_sku 1 TAPAL-TEA-450G
"""
import sys
from app.db import SessionLocal
from app.models import Product


def main():
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.set_sku <product_id> <sku>")
        raise SystemExit(1)
    product_id, sku = int(sys.argv[1]), sys.argv[2]
    with SessionLocal.begin() as db:
        product = db.get(Product, product_id)
        if not product:
            print(f"No product with id {product_id}")
            raise SystemExit(1)
        product.sku = sku
    print(f"Product {product_id} ({product.name}) -> SKU {sku}")


if __name__ == "__main__":
    main()
