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


# Nutrition claims (the product file's nutritionalClaim ids) in plain words. These are all 21
# that occur, most common first. A claim is made by the supplier: a product without the claim
# is treated as not having the property.
TAG_NAMES = {
    "FREE_FROM_LACTOSE": "lactose-free",
    "FREE_FROM_GLUTEN": "gluten-free",
    "VEGAN": "vegan",
    "VEGETARIAN": "vegetarian",
    "FREE_FROM_PRESERVATIVES": "preservative-free",
    "FREE_FROM_COLOURING_AGENTS": "no colouring agents",
    "FREE_FROM_ADDITIVES": "additive-free",
    "NO_ADDED_SUGARS": "no added sugar",
    "HIGH_FIBRE": "high-fibre",
    "FREE_FROM_EGGS": "egg-free",
    "HIGH_PROTEIN": "high-protein",
    "LOW_SODIUM_SALT": "low-salt",
    "FREE_FROM_SWEETENERS": "no sweeteners",
    "FREE_FROM_SOY": "soy-free",
    "LOW_LACTOSE": "low-lactose",
    "FREE_FROM_FAT": "fat-free",
    "FREE_FROM_WHEAT": "wheat-free",
    "LOW_FAT": "low-fat",
    "FREE_FROM_ARTIFICIAL_SWEETENERS": "no artificial sweeteners",
    "FREE_FROM_GMO": "GMO-free",
    "FREE_FROM_SODIUM_SALT": "salt-free",
}


def tag_name(code: str) -> str:
    """The plain words for a tag. An unlisted code is shown in lower case rather than hidden."""
    return TAG_NAMES.get(code) or code.replace("_", " ").lower()
