def offer_price(price_paisa: int, discount_bps: int) -> int:
    """Round discount down so it cannot exceed the configured percentage."""
    return price_paisa - (price_paisa * discount_bps // 10_000)


def choose_alternative(products, original, quantity, original_price, preferred_brands, discount_bps):
    eligible = [p for p in products if
                p.id != original.id and
                p.substitution_group == original.substitution_group and
                p.stock >= quantity and
                offer_price(p.price_paisa, discount_bps) <= original_price]
    # Preferences are a ranking signal; compatibility is a hard constraint.
    eligible.sort(key=lambda p: (p.brand not in preferred_brands,
                                offer_price(p.price_paisa, discount_bps), p.id))
    return eligible[0] if eligible else None


def message_for_offer(original, alternative, quantity, unit_price_paisa):
    return (f"{original.name} is unavailable. May we replace {quantity} unit(s) "
            f"with {alternative.name} at PKR {unit_price_paisa / 100:.2f} each "
            "after discount? Your order total will not increase. "
            "Please explicitly accept or reject before the offer expires.")
