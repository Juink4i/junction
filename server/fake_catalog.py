"""Stand-in for Runner 1's catalog/api.py. Same function shapes as Contract A.

All data here is made up for development, apart from the product ids and the
demo prices noted in the handoff.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from math import ceil


@dataclass
class ProductSummary:
    id: str
    name_en: str
    name_fi: str
    category: str
    sales_unit: str
    tags: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


@dataclass
class Product(ProductSummary):
    allergens_contains: list[str] = field(default_factory=list)
    allergens_may_contain: list[str] = field(default_factory=list)
    allergens_free_from: list[str] = field(default_factory=list)
    allergen_info_missing: bool = False
    vendor: str = ""
    country: str = ""
    description: str = ""
    carbon_kg_per_kg: float | None = None
    delivery_reliability: float | None = None
    official_substitutes: list[str] = field(default_factory=list)


@dataclass
class UnitPlan:
    product_id: str
    sales_unit: str
    content_per_unit: float
    content_unit: str
    units: int
    covers: float


@dataclass
class Offer:
    product_id: str
    unit_price_eur: float
    unit_price_with_tax_eur: float
    comparison_price_eur: float
    comparison_unit: str
    tax_rate: float
    list_price_eur: float
    price_valid_to: datetime
    orderable: bool
    available_date: date | None
    closing_time: datetime | None
    cutoff_passed: bool
    logistic_model: str
    available_units: int | None


TAX_RATE = 0.135


def _milk(id, name_en, name_fi, sales_unit, **extra) -> Product:
    return Product(
        id=id, name_en=name_en, name_fi=name_fi, category="10400", sales_unit=sales_unit,
        tags=["FREE_FROM_LACTOSE"], allergens_contains=["BM"], vendor="Valio", country="FI",
        description=name_en, **extra,
    )


_PRODUCTS = {
    p.id: p
    for p in [
        _milk("464201", "Lactose-free skimmed milk drink 1 L", "Laktoositon rasvaton maitojuoma 1 l",
              "1 L", official_substitutes=["464179"]),
        _milk("465039", "Lactose-free semi-skimmed milk drink 5 x 1 L",
              "Laktoositon kevytmaitojuoma 5 x 1 l", "5 x 1 L"),
        _milk("463038", "Lactose-free skimmed milk drink 2 x 10 L",
              "Laktoositon rasvaton maitojuoma 2 x 10 l", "2 x 10 L"),
        _milk("464179", "Lactose-free semi-skimmed milk drink 10 L",
              "Laktoositon kevytmaitojuoma 10 l", "10 L"),
        _milk("464500", "Lactose-free coffee milk 1 L", "Laktoositon kahvimaito 1 l", "1 L"),
        Product(
            id="460004", name_en="Tomberry tomato 1 kg", name_fi="Tomberry tomaatti 1 kg",
            category="20100", sales_unit="1 KG", allergen_info_missing=True, country="NL",
            description="Tomberry tomato",
        ),
        Product(
            id="460000", name_en="Pancake 2 kg", name_fi="Pannukakku 2 kg", category="30500",
            sales_unit="2 KG", allergens_contains=["AE", "BM"], vendor="Fake Bakery", country="FI",
            description="Oven pancake",
        ),
        Product(
            id="460500", name_en="Wholegrain bread roll 30 pcs", name_fi="Täysjyväsämpylä 30 kpl",
            category="41760", sales_unit="BAG", allergens_contains=["AW"], vendor="Fake Bakery",
            country="FI", description="Wholegrain bread rolls",
        ),
        # Eggs claim nothing. Only the allergen data can show whether they are free from milk.
        Product(
            id="460600", name_en="Barn egg 30 pcs", name_fi="Kananmuna 30 kpl", category="10590",
            sales_unit="30 PCS", allergens_contains=["AE"], allergens_free_from=["AM", "AW", "AY"],
            vendor="Fake Farm", country="FI", description="Barn eggs",
        ),
        Product(
            id="460601", name_en="Free range egg 10 pcs", name_fi="Vapaan kanan muna 10 kpl",
            category="10590", sales_unit="10 PCS", allergens_contains=["AE"], vendor="Fake Farm",
            country="FI", description="Free range eggs",
        ),
        Product(
            id="460602", name_en="Egg custard 1 kg", name_fi="Munavanukas 1 kg", category="30500",
            sales_unit="1 KG", allergens_contains=["AE", "AM"], vendor="Fake Bakery", country="FI",
            description="Egg custard",
        ),
    ]
}

# product id -> (content per sales unit, content unit, unit price ex VAT, logistic model, cut-off passed)
_TERMS = {
    "464201": (1.0, "L", 1.56, "Stock", False),
    "465039": (5.0, "L", 8.10, "Stock", False),
    "463038": (20.0, "L", 27.40, "Terminal", True),
    "464179": (10.0, "L", 16.20, "Stock", False),
    "464500": (1.0, "L", 1.89, "Stock", False),
    "460004": (1.0, "KG", 6.50, "Stock", False),
    "460000": (2.0, "KG", 9.80, "Stock", False),
    "460500": (30.0, "PCS", 7.20, "Stock", False),
    "460600": (30.0, "PCS", 6.90, "Stock", False),
    "460601": (10.0, "PCS", 3.40, "Stock", False),
    "460602": (1.0, "KG", 8.50, "Stock", False),
}


def search_products(text: str, category: str | None = None,
                    must_have_tags: list[str] = [], limit: int = 20) -> list[ProductSummary]:
    words = text.lower().split()
    found = []
    for p in _PRODUCTS.values():
        name = f"{p.name_en} {p.name_fi}".lower()
        if category and p.category != category:
            continue
        if not set(must_have_tags) <= set(p.tags):
            continue
        if not all(w in name for w in words):
            continue
        found.append(ProductSummary(p.id, p.name_en, p.name_fi, p.category, p.sales_unit,
                                    p.tags, p.labels))
    return found[:limit]


def get_product(product_id: str) -> Product | None:
    return _PRODUCTS.get(product_id)


def units_needed(product_id: str, amount: float, unit: str) -> UnitPlan:
    content, content_unit, *_ = _TERMS[product_id]
    if unit != content_unit:
        raise ValueError(f"Product {product_id} is sold by {content_unit}, not {unit}")
    units = ceil(amount / content)
    return UnitPlan(product_id, _PRODUCTS[product_id].sales_unit, content, content_unit,
                    units, units * content)


def _offer(product_id: str, delivery_date: date) -> Offer:
    content, content_unit, price, model, cutoff_passed = _TERMS[product_id]
    now = datetime.now(timezone.utc)
    # Open until the end of the delivery day, so a test clock set anywhere before it sees an open cut-off.
    closing = (now - timedelta(hours=2) if cutoff_passed else
               datetime.combine(delivery_date, time(23, 59), tzinfo=timezone.utc))
    return Offer(
        product_id=product_id,
        unit_price_eur=price,
        unit_price_with_tax_eur=round(price * (1 + TAX_RATE), 2),
        comparison_price_eur=round(price / content, 2),
        comparison_unit=content_unit,
        tax_rate=TAX_RATE,
        list_price_eur=price,
        price_valid_to=now + timedelta(days=1),
        orderable=True,
        available_date=delivery_date,
        closing_time=closing,
        cutoff_passed=cutoff_passed,
        logistic_model=model,
        available_units=None,
    )


def price_and_availability(product_ids: list[str], delivery_date: date) -> dict[str, Offer]:
    return {pid: _offer(pid, delivery_date) for pid in product_ids if pid in _TERMS}


def substitute_candidates(product_id: str, must_keep_tags: list[str],
                          max_price_increase_pct: float, delivery_date: date) -> list[Offer]:
    original = _PRODUCTS[product_id]
    cap = _offer(product_id, delivery_date).comparison_price_eur * (1 + max_price_increase_pct / 100)
    offers = []
    for p in _PRODUCTS.values():
        if p.id == product_id or p.category != original.category:
            continue
        if not set(must_keep_tags) <= set(p.tags):
            continue
        offer = _offer(p.id, delivery_date)
        if offer.comparison_price_eur <= cap and not offer.cutoff_passed:
            offers.append(offer)
    return sorted(offers, key=lambda o: o.product_id not in original.official_substitutes)
