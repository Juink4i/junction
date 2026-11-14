"""Rank the products that can fill a request, and turn the ranking into options to order.

Plain code, no AI. The order is the one the buyer agent's prompt used to describe:
on time first, then the buyer's preferences (or price, delivery date, reliability,
sustainability), then pack size, then product id so the result is stable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

PRIORITIES = ("price", "reliability", "finnish", "sustainability")
DEFAULT_ORDER = ("price", "delivery", "reliability", "sustainability")
PRICE_STEP = 0.02  # totals are compared in steps of 2% above the cheapest
LABELS = ("best", "better", "good")
ECO_LABELS = frozenset({
    "EU_ORGANIC_FARMING", "SVANEN", "RAINFOREST_ALLIANCE", "EU_ECO_LABEL", "FAIR_TRADE_MARK",
    "MARINE_STEWARDSHIP_COUNCIL_LABEL", "AQUACULTURE_STEWARDSHIP_COUNCIL", "KRAV_MARK",
    "OFFICIAL_ECO_LABEL_SUN", "SOIL_ASSOCIATION_ORGANIC_SYMBOL", "UTZ_CERTIFIED",
})


def eur(amount: float) -> str:
    return f"€{amount:,.2f}"


@dataclass(frozen=True)
class Candidate:
    """One product, sized and priced for the full amount asked for."""
    product_id: str
    name: str
    sales_unit: str
    content_per_unit: float  # litres or kilos in one sales unit
    content_unit: str  # "L" or "KG"
    units: int  # sales units that cover the full amount
    unit_price_eur: float
    unit_price_with_tax_eur: float
    available_date: date | None
    closing_time: datetime | None
    cutoff_passed: bool
    available_units: int | None  # None: Valio Aimo gave no real stock figure
    reliability: float | None = None
    country: str | None = None
    labels: tuple[str, ...] = ()
    carbon: float | None = None
    tags: tuple[str, ...] = ()  # nutrition claims, e.g. LOW_SODIUM_SALT

    @property
    def total_eur(self) -> float:
        return round(self.units * self.unit_price_eur, 2)

    @property
    def short(self) -> bool:
        """Confirmed stock is below what the full amount needs."""
        return self.available_units is not None and self.available_units < self.units

    def on_time(self, need_by: date) -> bool:
        return (not self.cutoff_passed and self.available_date is not None
                and self.available_date <= need_by)


@dataclass(frozen=True)
class Line:
    candidate: Candidate
    units: int

    @property
    def covers(self) -> float:
        return round(self.units * self.candidate.content_per_unit, 4)

    @property
    def total_eur(self) -> float:
        return round(self.units * self.candidate.unit_price_eur, 2)


@dataclass(frozen=True)
class Option:
    label: str
    lines: tuple[Line, ...]
    trade_off: str = ""

    @property
    def total_eur(self) -> float:
        return round(sum(line.total_eur for line in self.lines), 2)


def _order(priorities: list[str] | None) -> tuple[str, ...]:
    chosen = list(dict.fromkeys(p for p in priorities or [] if p in PRIORITIES))
    if not chosen:
        return DEFAULT_ORDER
    return tuple(chosen + [key for key in ("price", "delivery") if key not in chosen])


def rank(candidates: list[Candidate], need_by: date, priorities: list[str] | None = None,
         pack_size: str | None = None, prefer: list[str] | None = None) -> list[Candidate]:
    """Best first. `priorities` is the buyer's own order of price, reliability, finnish, sustainability.
    `prefer` lists claims the buyer would like, such as LOW_SODIUM_SALT; they only break ties."""
    if not candidates:
        return []
    cheapest = min(c.total_eur for c in candidates) or 1.0
    order = _order(priorities)

    def key(c: Candidate) -> tuple:
        parts: list = [0 if c.on_time(need_by) else 1]
        for name in order:
            if name == "price":
                parts.append(int((c.total_eur / cheapest - 1) / PRICE_STEP + 1e-9))
            elif name == "delivery":
                parts.append(c.available_date.toordinal() if c.available_date else 10 ** 7)
            elif name == "reliability":
                parts.append(-round((c.reliability or 0.0) * 100))
            elif name == "finnish":
                parts.append(0 if (c.country or "").upper() in ("FI", "FINLAND") else 1)
            elif name == "sustainability":
                parts.append(0 if ECO_LABELS & set(c.labels) else 1)
                parts.append(c.carbon if c.carbon is not None else math.inf)
        if prefer:
            parts.append(-len(set(prefer) & set(c.tags)))
        if pack_size == "small":
            parts.append(c.content_per_unit)
        elif pack_size == "large":
            parts.append(-c.content_per_unit)
        parts += [c.total_eur, c.product_id]
        return tuple(parts)

    return sorted(candidates, key=key)


def _split(ranked: list[Candidate], amount: float) -> tuple[Line, ...] | None:
    """All that is left of the first choice, then the rest from the next products down the list.

    None when the list cannot cover the whole amount.
    """
    first = ranked[0]
    if not first.available_units:
        return None
    lines = [Line(first, first.available_units)]
    remaining = amount - first.available_units * first.content_per_unit
    for c in ranked[1:]:
        if remaining <= 1e-9:
            break
        wanted = math.ceil(remaining / c.content_per_unit - 1e-9)
        take = wanted if c.available_units is None else min(wanted, c.available_units)
        if take > 0:
            lines.append(Line(c, take))
            remaining -= take * c.content_per_unit
    return tuple(lines) if remaining <= 1e-9 and len(lines) > 1 else None


def _describe(lines: tuple[Line, ...], best_total: float | None, need_by: date) -> str:
    parts = []
    for line in lines:
        c = line.candidate
        parts.append(f"{line.units:,} × {c.sales_unit} of {c.name} ({line.covers:g} {c.content_unit})")
    text = " + ".join(parts)
    dates = [line.candidate.available_date for line in lines]
    if all(dates):
        text += f", arrives {max(dates).isoformat()}"
    total = round(sum(line.total_eur for line in lines), 2)
    if best_total is not None and total != best_total:
        more = total - best_total
        text += f", {eur(abs(more))} {'more' if more > 0 else 'less'} than the best option"
    late = [line.candidate.name for line in lines if not line.candidate.on_time(need_by)]
    if late:
        text += ". Not certain to arrive on time: " + ", ".join(late)
    return text + "."


def options(ranked: list[Candidate], amount: float, need_by: date, limit: int = 5) -> list[Option]:
    """Up to `limit` orderable options, best first.

    A product without enough confirmed stock is never offered on its own. When that product
    is the first choice, the first option is a split: what is left of it plus the next
    products down the list.
    """
    plans: list[tuple[str, tuple[Line, ...]]] = []
    if ranked and ranked[0].short:
        split = _split(ranked, amount)
        if split:
            plans.append(("split", split))
    for c in ranked:
        if not c.short:
            plans.append(("", (Line(c, c.units),)))
    plans = plans[:limit]
    out, best_total = [], None
    for position, (label, lines) in enumerate(plans):
        if not label:
            label = LABELS[position] if position < len(LABELS) else "other"
        option = Option(label, lines, _describe(lines, best_total, need_by))
        if best_total is None:
            best_total = option.total_eur
        out.append(option)
    return out
