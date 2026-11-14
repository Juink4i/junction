"""Plain words to catalog tags, so a buyer's agent never needs a tag code.

Plain code, no AI. A must-have word this file does not know is reported as unknown, never
guessed: a must-have is a safety property.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from catalog.names import TAG_NAMES, tag_name

# Other spellings of what a claim is about. The first one is the usual word.
_SUBJECTS = {
    "SOY": ("soy", "soya"),
    "FIBRE": ("fibre", "fiber"),
    "SODIUM_SALT": ("salt", "sodium"),
    "EGGS": ("egg", "eggs"),
    "ADDITIVES": ("additive", "additives"),
    "PRESERVATIVES": ("preservative", "preservatives"),
    "SWEETENERS": ("sweetener", "sweeteners"),
    "ARTIFICIAL_SWEETENERS": ("artificial sweetener", "artificial sweeteners"),
    "COLOURING_AGENTS": ("colouring agents", "colouring", "colourings", "coloring agents",
                         "coloring", "colorings"),
}
# Phrases the rules below cannot build, including the Finnish words kitchens use.
_EXTRA = {
    "FREE_FROM_LACTOSE": ("laktoositon",),
    "LOW_LACTOSE": ("vähälaktoosinen",),
    "FREE_FROM_GLUTEN": ("gluteeniton",),
    "VEGAN": ("vegaaninen",),
    "VEGETARIAN": ("kasvisruoka",),
    "NO_ADDED_SUGARS": ("no added sugar", "without added sugar"),
}


def normalise(text: str) -> str:
    """Lower case, with hyphens and underscores as spaces, so "Lactose-Free" equals "lactose free"."""
    return " ".join(re.sub(r"[-_]+", " ", str(text).lower()).split())


def _phrases(code: str) -> set[str]:
    found = {normalise(tag_name(code)), normalise(code), *map(normalise, _EXTRA.get(code, ()))}
    for prefix, patterns in (("FREE_FROM_", ("{} free", "free from {}", "no {}", "without {}")),
                             ("LOW_", ("low {}", "low in {}")),
                             ("HIGH_", ("high {}", "high in {}", "rich in {}"))):
        if code.startswith(prefix):
            subject = code[len(prefix):]
            for word in _SUBJECTS.get(subject, (normalise(subject),)):
                found.update(pattern.format(word) for pattern in patterns)
    return found


PHRASES: dict[str, str] = {phrase: code for code in TAG_NAMES for phrase in _phrases(code)}
_LONGEST_FIRST = sorted(PHRASES, key=len, reverse=True)


@dataclass
class Understood:
    text: str  # the product words left for the text search
    tags: list[str] = field(default_factory=list)  # tag codes
    unknown: list[str] = field(default_factory=list)  # must-have words that are not a known property


def names(codes) -> list[str]:
    return [tag_name(code) for code in codes]


def known_names() -> list[str]:
    return [tag_name(code) for code in TAG_NAMES]


def understand(product: str, must_have: list[str] | None = None) -> Understood:
    """Split a request into search words and tags.

    A property named inside the product words is lifted out: "lactose-free milk" becomes the
    text "milk" with the tag FREE_FROM_LACTOSE. Longer phrases win, so "no artificial
    sweeteners" is not read as "no sweeteners".
    """
    text, tags, unknown = normalise(product or ""), [], []
    for word in must_have or []:
        code = PHRASES.get(normalise(word))
        if code is None:
            unknown.append(str(word))
        elif code not in tags:
            tags.append(code)
    for phrase in _LONGEST_FIRST:
        pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
        if re.search(pattern, text):
            text = " ".join(re.sub(pattern, " ", text).split())
            if PHRASES[phrase] not in tags:
                tags.append(PHRASES[phrase])
    return Understood(text, tags, unknown)


UNIT_WORDS = {"L": "litres", "KG": "kilograms", "PCS": "pieces"}
_UNITS = {
    "L": ("l", "ltr", "litre", "litres", "liter", "liters", "litra", "litraa"),
    "KG": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "kiloa"),
    "PCS": ("pcs", "pc", "piece", "pieces", "kpl", "kappale", "kappaletta", "each", "ea"),
}
_UNIT_CODES = {word: code for code, words in _UNITS.items() for word in words}


def unit_code(word: str | None) -> str | None:
    """ "L", "KG" or "PCS" for a unit word, or None when the server cannot measure in it.

    Grams, crates or product words such as "eggs" are None: the buyer must say it again in a
    unit the server can measure, so no number is ever carried over to a different unit.
    """
    return _UNIT_CODES.get(normalise(word or ""))
