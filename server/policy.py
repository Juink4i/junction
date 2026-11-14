"""Policy: plain code that decides what happens to an order. No AI in here."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

UNUSUAL_FACTOR = 5
PERIOD_WORDS = {"week": ("this week's", "weekly"), "month": ("this month's", "monthly")}


def period_start(period: str, now: datetime) -> datetime:
    """When the current budget period began: Monday 00:00 for a week, the 1st for a month."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return midnight - timedelta(days=midnight.weekday())
    return midnight.replace(day=1)


@dataclass
class Decision:
    status: str
    reasons: list[str]
    question: str | None = None


def eur(amount: float) -> str:
    return f"€{amount:,.2f}"


def _unknown_blocked(product, blocked: set[str]) -> list[str]:
    """Blocked allergens the product neither lists nor declares free from. Unknown is not safe."""
    listed = {a.upper() for a in product.allergens_contains + product.allergens_may_contain
              + product.allergens_free_from}
    return sorted(blocked - listed)


def _hard_stops(quote: dict, mandate: dict, products: dict) -> list[str]:
    allowed = mandate["auto_approve"].get("allowed_categories")
    rules = mandate["hard_rules"]
    blocked = {code.upper() for code in rules.get("blocked_allergens", [])}
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
        contains = sorted(blocked & {a.upper() for a in product.allergens_contains})
        may_contain = sorted(blocked & {a.upper() for a in product.allergens_may_contain} - set(contains))
        if contains:
            reasons.append(f"{line['name']} contains an allergen the mandate blocks: {', '.join(contains)}.")
        if may_contain:
            reasons.append(f"{line['name']} may contain an allergen the mandate blocks: {', '.join(may_contain)}.")
        unknown = _unknown_blocked(product, blocked)
        if rules.get("unknown_allergens") == "reject":
            if product.allergen_info_missing:
                reasons.append(f"{line['name']} has no allergen information, and the mandate rejects such products.")
            elif unknown:
                reasons.append(f"Whether {line['name']} contains {', '.join(unknown)} is unknown, "
                               "and the mandate rejects such products.")
    return reasons


def _unusual(quote: dict, products: dict, history: list[dict]) -> list[str]:
    # Add up lines of the same kind first, or splitting an order would get around the check.
    asked: dict[tuple[str, str], float] = {}
    for line in quote["lines"]:
        key = (products[line["product_id"]].category, line["content_unit"])
        asked[key] = asked.get(key, 0) + line["covers"]
    reasons = []
    for (category, unit), amount in asked.items():
        past = [h["amount"] for h in history if h["category"] == category and h["content_unit"] == unit]
        if not past:
            continue
        usual = median(past)
        if amount > UNUSUAL_FACTOR * usual:
            names = sorted({l["name"] for l in quote["lines"]
                            if products[l["product_id"]].category == category})
            reasons.append(
                f"{amount:g} {unit} of {', '.join(names)} is more than {UNUSUAL_FACTOR} times "
                f"this buyer's usual order of {usual:g} {unit}."
            )
    return reasons


def _needs_human(quote: dict, mandate: dict, products: dict, spent_in_period: float = 0.0) -> list[str]:
    limits = mandate["auto_approve"]
    rules = mandate["hard_rules"]
    must_keep = mandate.get("substitution", {}).get("must_keep", [])
    reasons = []
    max_order = limits.get("max_order_eur")
    if max_order is not None and quote["total_eur"] > max_order:
        reasons.append(f"The order total of {eur(quote['total_eur'])} is over the mandate's "
                       f"order limit of {eur(max_order)}.")
    max_line = limits.get("max_line_eur")
    per_product: dict[str, float] = {}
    for line in quote["lines"]:
        per_product[line["name"]] = per_product.get(line["name"], 0) + line["line_total_eur"]
    for name, total in per_product.items():
        if max_line is not None and total > max_line:
            reasons.append(f"{name} costs {eur(total)}, over the mandate's "
                           f"limit of {eur(max_line)} per line.")
    budget = mandate.get("budget")
    if budget:
        total = round(spent_in_period + quote["total_eur"], 2)
        if total > budget["max_eur"]:
            this, adjective = PERIOD_WORDS[budget["period"]]
            reasons.append(f"This order of {eur(quote['total_eur'])} would bring {this} spending "
                           f"to {eur(total)}, over the {adjective} budget of {eur(budget['max_eur'])}.")
    for line in quote["lines"]:
        product = products[line["product_id"]]
        if line["cutoff_passed"]:
            reasons.append(f"The order cut-off for {line['name']} has already passed, "
                           "so on-time delivery is not certain.")
        if line["available_date"] is None:
            reasons.append(f"Valio Aimo gave no delivery date for {line['name']}.")
        elif line["available_date"] > quote["need_by"]:
            reasons.append(f"{line['name']} would arrive on {line['available_date']}, "
                           f"after the need-by date {quote['need_by']}.")
        if rules.get("unknown_allergens", "human") == "human":
            unknown = _unknown_blocked(product, {c.upper() for c in rules.get("blocked_allergens", [])})
            if product.allergen_info_missing:
                reasons.append(f"{line['name']} has no allergen information. Unknown is not treated "
                               "as safe, so a person must check it.")
            elif unknown:
                reasons.append(f"The product data does not say whether {line['name']} contains "
                               f"{', '.join(unknown)}, which the mandate blocks. Unknown is not "
                               "treated as safe, so a person must check it.")
        missing_tags = [t for t in must_keep if t not in product.tags]
        if missing_tags:
            reasons.append(f"{line['name']} does not have the tag the mandate requires: "
                           f"{', '.join(missing_tags)}.")
    return reasons


def decide(quote: dict, mandate: dict, products: dict, history: list[dict],
           confirm_unusual: bool = False, ai_unusual: str | None = None,
           spent_in_period: float = 0.0) -> Decision:
    """quote is a verified quote plus its need_by date; mandate is already verified.

    ai_unusual is an optional reason from an outside scorer. It can only add a question.
    spent_in_period is what the buyer's other live orders add up to in the current budget period.
    """
    stops = _hard_stops(quote, mandate, products)
    if stops:
        return Decision("rejected", stops)

    unusual = _unusual(quote, products, history) + ([ai_unusual] if ai_unusual else [])
    if unusual and not confirm_unusual:
        return Decision(
            "needs_clarification", unusual,
            question="This is far more than this buyer usually orders. If the amount is right, "
                     "place the order again with confirm_unusual = true. It will then go to a "
                     "person for approval.",
        )

    for_human = _needs_human(quote, mandate, products, spent_in_period)
    if unusual:
        for_human += [f"{r} The agent confirmed the amount." for r in unusual]
    if for_human:
        return Decision("pending_approval", for_human)

    return Decision("confirmed", ["The order is within every limit of the buyer's mandate."])
