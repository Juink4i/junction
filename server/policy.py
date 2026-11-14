"""Policy: plain code that decides what happens to an order. No AI in here."""

from dataclasses import dataclass
from statistics import median

UNUSUAL_FACTOR = 5


@dataclass
class Decision:
    status: str
    reasons: list[str]
    question: str | None = None


def eur(amount: float) -> str:
    return f"€{amount:,.2f}"


def _hard_stops(quote: dict, mandate: dict, products: dict) -> list[str]:
    allowed = mandate["auto_approve"].get("allowed_categories")
    rules = mandate["hard_rules"]
    blocked = set(rules.get("blocked_allergens", []))
    reasons = []
    for line in quote["lines"]:
        product = products.get(line["product_id"])
        if product is None:
            reasons.append(f"Product {line['product_id']} is not in the Valio Aimo catalog.")
            continue
        if allowed is not None and product.category not in allowed:
            reasons.append(
                f"{line['name']} is in category {product.category}, which the mandate does not "
                f"allow. Allowed: {', '.join(allowed) or 'none'}."
            )
        contains = sorted(blocked & set(product.allergens_contains))
        may_contain = sorted(blocked & set(product.allergens_may_contain) - set(contains))
        if contains:
            reasons.append(f"{line['name']} contains an allergen the mandate blocks: {', '.join(contains)}.")
        if may_contain:
            reasons.append(f"{line['name']} may contain an allergen the mandate blocks: {', '.join(may_contain)}.")
        if product.allergen_info_missing and rules.get("unknown_allergens") == "reject":
            reasons.append(f"{line['name']} has no allergen information, and the mandate rejects such products.")
    return reasons


def _unusual(quote: dict, products: dict, history: list[dict]) -> list[str]:
    reasons = []
    for line in quote["lines"]:
        category = products[line["product_id"]].category
        past = [h["amount"] for h in history
                if h["category"] == category and h["content_unit"] == line["content_unit"]]
        if not past:
            continue
        usual = median(past)
        if line["covers"] > UNUSUAL_FACTOR * usual:
            reasons.append(
                f"{line['covers']:g} {line['content_unit']} of {line['name']} is more than "
                f"{UNUSUAL_FACTOR} times this buyer's usual order of {usual:g} {line['content_unit']}."
            )
    return reasons


def _needs_human(quote: dict, mandate: dict, products: dict) -> list[str]:
    limits = mandate["auto_approve"]
    rules = mandate["hard_rules"]
    must_keep = mandate.get("substitution", {}).get("must_keep", [])
    reasons = []
    max_order = limits.get("max_order_eur")
    if max_order is not None and quote["total_eur"] > max_order:
        reasons.append(f"The order total of {eur(quote['total_eur'])} is over the mandate's "
                       f"order limit of {eur(max_order)}.")
    max_line = limits.get("max_line_eur")
    for line in quote["lines"]:
        product = products[line["product_id"]]
        if max_line is not None and line["line_total_eur"] > max_line:
            reasons.append(f"{line['name']} costs {eur(line['line_total_eur'])}, over the mandate's "
                           f"limit of {eur(max_line)} per line.")
        if line["cutoff_passed"]:
            reasons.append(f"The order cut-off for {line['name']} has already passed, "
                           "so on-time delivery is not certain.")
        if line["available_date"] is None:
            reasons.append(f"Valio Aimo gave no delivery date for {line['name']}.")
        elif line["available_date"] > quote["need_by"]:
            reasons.append(f"{line['name']} would arrive on {line['available_date']}, "
                           f"after the need-by date {quote['need_by']}.")
        if product.allergen_info_missing and rules.get("unknown_allergens") == "human":
            reasons.append(f"{line['name']} has no allergen information. Unknown is not treated "
                           "as safe, so a person must check it.")
        missing_tags = [t for t in must_keep if t not in product.tags]
        if missing_tags:
            reasons.append(f"{line['name']} does not have the tag the mandate requires: "
                           f"{', '.join(missing_tags)}.")
    return reasons


def decide(quote: dict, mandate: dict, products: dict, history: list[dict],
           confirm_unusual: bool = False) -> Decision:
    """quote is a verified quote plus its need_by date; mandate is already verified."""
    stops = _hard_stops(quote, mandate, products)
    if stops:
        return Decision("rejected", stops)

    unusual = _unusual(quote, products, history)
    if unusual and not confirm_unusual:
        return Decision(
            "needs_clarification", unusual,
            question="This is far more than this buyer usually orders. If the amount is right, "
                     "place the order again with confirm_unusual = true. It will then go to a "
                     "person for approval.",
        )

    for_human = _needs_human(quote, mandate, products)
    if unusual:
        for_human += [f"{r} The agent confirmed the amount." for r in unusual]
    if for_human:
        return Decision("pending_approval", for_human)

    return Decision("confirmed", ["The order is within every limit of the buyer's mandate."])
