from app.db import SessionLocal
from app.models import Product

# Fictional demonstration prices and stock, not current retail data.
PRODUCTS = [
    dict(id=1, name="Tapal Danedar Tea 450g", brand="Tapal", substitution_group="black-tea-450g", price_paisa=100000, stock=0),
    dict(id=2, name="Vital Tea 450g", brand="Vital", substitution_group="black-tea-450g", price_paisa=98000, stock=20),
    dict(id=3, name="Dalda Cooking Oil 1L", brand="Dalda", substitution_group="cooking-oil-1L", price_paisa=60000, stock=10),
    dict(id=4, name="Mezan Cooking Oil 1L", brand="Mezan", substitution_group="cooking-oil-1L", price_paisa=59000, stock=0),
    dict(id=5, name="Basmati Rice 1kg", brand="Demo Pantry", substitution_group="basmati-1kg", price_paisa=35000, stock=0),
    dict(id=6, name="Shan Biryani Masala 50g", brand="Shan", substitution_group="biryani-50g", price_paisa=15000, stock=24),
    dict(id=7, name="National Biryani Masala 50g", brand="National", substitution_group="biryani-50g", price_paisa=14500, stock=0),
    dict(id=8, name="Shangrila Tomato Ketchup 500g", brand="Shangrila", substitution_group="ketchup-500g", price_paisa=32000, stock=15),
    dict(id=9, name="Young's Mayonnaise 500ml", brand="Young's", substitution_group="mayo-500ml", price_paisa=45000, stock=12),
    dict(id=10, name="Wheat Flour 5kg", brand="Demo Pantry", substitution_group="flour-5kg", price_paisa=65000, stock=22),
]

if __name__ == "__main__":
    with SessionLocal.begin() as db:
        for product in PRODUCTS:
            if db.get(Product, product["id"]) is None:
                db.add(Product(**product))
    print("Seeded missing demo products. Existing stock was not reset.")
