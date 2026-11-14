"""Contract A shapes (docs/runner-tasks.md). Runner 2 serialises these straight to MCP JSON."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

Unit = Literal["L", "KG", "PCS"]


class ProductSummary(BaseModel):
    id: str
    name_en: str
    name_fi: str
    category: str
    sales_unit: str
    tags: list[str]  # nutrition claims, e.g. FREE_FROM_LACTOSE, VEGAN
    labels: list[str]  # packaging labels, e.g. EU_ORGANIC_FARMING


class Product(ProductSummary):
    allergens_contains: list[str]
    allergens_may_contain: list[str]
    allergens_free_from: list[str]
    allergen_info_missing: bool  # True when the supplier gave no allergen data at all
    vendor: str | None
    country: str | None
    description: str
    carbon_kg_per_kg: float | None
    delivery_reliability: float | None
    official_substitutes: list[str]


class UnitPlan(BaseModel):
    product_id: str
    sales_unit: str
    content_per_unit: float  # litres, kg or pieces in one sales unit
    content_unit: Unit
    units: int  # sales units to order, rounded up
    covers: float  # units * content_per_unit, always >= the amount asked for


class Offer(BaseModel):
    product_id: str
    unit_price_eur: float  # per sales unit, before tax
    unit_price_with_tax_eur: float
    comparison_price_eur: float | None  # per comparison_unit, before tax
    comparison_unit: Unit | None
    tax_rate: float  # percent
    list_price_eur: float | None
    price_valid_to: datetime | None
    orderable: bool  # False when sales-blocked, out of stock or not deliverable at all
    available_date: date | None
    closing_time: datetime | None  # order cut-off for available_date
    cutoff_passed: bool
    logistic_model: Literal["Stock", "Terminal"] | None  # None when the product can't be delivered
    available_units: int | None  # None means unknown. Placeholders (>= 999999) are never shown.
