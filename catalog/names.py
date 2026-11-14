"""Readable names for codes. The product file only has category codes and GS1 allergen codes.

Category names are ours, read off sample products, and cover only the categories we demo.
Allergen names follow the GS1 AllergenTypeCode list; codes we couldn't confirm are left out.
"""

CATEGORY_NAMES = {
    "10400": "Milk and sour milk",
    "10401": "Cream",
    "10402": "Plant-based drinks",
    "17301": "Ready-made salads",
    "17401": "Tomatoes",
    "17402": "Pumpkins and courgettes",
}

ALLERGEN_NAMES = {
    # The 14 allergens EU law requires on labels
    "AW": "Cereals containing gluten",
    "AC": "Crustaceans",
    "AE": "Eggs",
    "AF": "Fish",
    "AP": "Peanuts",
    "AY": "Soybeans",
    "AM": "Milk",
    "AN": "Tree nuts",
    "BC": "Celery",
    "BM": "Mustard",
    "AS": "Sesame seeds",
    "AU": "Sulphur dioxide and sulphites",
    "NL": "Lupin",
    "UM": "Molluscs",
    # More specific codes
    "ML": "Lactose",
    "UW": "Wheat",
    "NR": "Rye",
    "GB": "Barley",
    "GO": "Oats",
    "GS": "Spelt",
    "GK": "Kamut",
    "SA": "Almonds",
    "SC": "Cashews",
    "SH": "Hazelnuts",
    "SM": "Macadamia nuts",
    "SP": "Pecan nuts",
    "SR": "Brazil nuts",
    "ST": "Pistachios",
    "SW": "Walnuts",
}


def category_name(code: str) -> str | None:
    return CATEGORY_NAMES.get(str(code))


def allergen_name(code: str) -> str | None:
    return ALLERGEN_NAMES.get(code)
