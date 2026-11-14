"""The seller's side of a search: removes products that do not do the job the buyer asked for.

It can only remove. It sees product names and properties, never descriptions, prices, stock
or a mandate, and no rule lives here. This file holds the plain keyword rules; the Gemini
seller agent that uses them as its fallback is added below them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Kinds of product that match a search word but do a different job. A kind is skipped when
# the buyer asked for it by name.
WRONG_KINDS = [
    ("coffee milk or coffee drink", ("coffee", "kahvi", "café", "cafè", "cafe", "latte", "cappuccino")),
    ("chocolate or flavoured drink", ("chocolate", "kaakao", "cocoa", "vanilla", "vanilja")),
    ("sour milk", ("sour", "piimä", "buttermilk")),
    ("yoghurt", ("yogurt", "yoghurt", "jogurtti")),
    ("low-lactose, not lactose-free", ("low-lactose", "low lactose", "vähälaktoosinen")),
    ("plant drink", ("oat", "kaura", "soy", "soija", "almond", "manteli")),
    ("cream", ("cream", "kerma")),
    ("portion pack", ("portion", "annos")),
]

# Finnish words are stems: Finnish builds compounds, so "kahvimaito" and "ruokakerma" hide
# the stem inside a longer word. These match anywhere in the text.
FINNISH_STEMS = frozenset({"kahvi", "kaakao", "vanilja", "piimä", "jogurtti", "vähälaktoosinen",
                           "kaura", "soija", "manteli", "kerma", "annos"})


def _mentions(word: str, text: str) -> bool:
    # English words are separate words, so "oat" must not match inside "goat" and "sour" not
    # inside "sourdough"; an optional plural "s" is allowed. Finnish stems match anywhere.
    if word in FINNISH_STEMS:
        return word in text
    return re.search(rf"(?<!\w){re.escape(word)}s?(?!\w)", text) is not None


@dataclass(frozen=True)
class Need:
    product: str  # the product words as the buyer sent them
    must_have: tuple[str, ...] = ()  # property names, e.g. "lactose-free"
    amount: float | None = None
    unit: str | None = None


@dataclass(frozen=True)
class Verdict:
    keep: bool
    reason: str = ""


@dataclass
class Screening:
    verdicts: dict[str, Verdict] = field(default_factory=dict)  # by product id
    screened_by: str = "keyword rules"


def keyword_verdict(need: Need, candidate: Any) -> Verdict:
    asked = need.product.lower()
    name = f"{candidate.name_en} {candidate.name_fi}".lower()
    for kind, words in WRONG_KINDS:
        if any(_mentions(word, asked) for word in words):
            continue
        if any(_mentions(word, name) for word in words):
            return Verdict(False, kind)
    return Verdict(True)


class KeywordSeller:
    name = "keyword rules"

    def screen(self, need: Need, candidates: list[Any]) -> Screening:
        return Screening({c.id: keyword_verdict(need, c) for c in candidates}, self.name)
