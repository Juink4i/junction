# Runner 1: Catalog

You own `catalog/` and `data/`. Branch: `catalog`. Do not edit `server/`, `agent/`, `web/` or `demo/`.

## Goal

A Python package the server imports to answer: what matches a request, how many units to order, what it costs and when it can arrive.

You provide **Contract A** in `docs/runner-tasks.md` (five functions in `catalog/api.py`). The done-checklist is in the same file under "Prompts for each runner → Runner 1".

## Context you need

- Source files in `data/raw/`: `valio_aimo_junction26_product_data.json` (87 MB), its schema, `..._delivery_reliability.csv`, `..._carbon_footprint.csv`. Load them once into `data/catalog.db`.
- Product shape: top-level `id`, `salesUnit`, `baseUnit`, `units` (packaging ladder with `sizeInBaseUnits`), `category`, `vendorName`, `substitutions`. Supplier details are under `synkkaData`: `names` (fi/en/sv), `classifications`, `unitConversions`, `marketingTexts`, `keyIngredients`.
- `classifications` groups: `allergen` (unit `CONTAINS` or `MAY_CONTAIN`), `nonAllergen` (`FREE_FROM`), `nutritionalClaim` (e.g. `FREE_FROM_LACTOSE`, `LOW_LACTOSE`, `VEGAN`), `packagingMarkedLabel` (e.g. `EU_ORGANIC_FARMING`).
- A product with no `allergen` and no `nonAllergen` values has `allergen_info_missing = True`.
- Unit maths: litres or kg per sales unit = base-unit volume/weight × ladder size. When `unitConversions` lacks it (e.g. `463038`), use unit price ÷ comparison price from the price API, rounded.
- API: base URL `https://junction26.valioaimo.fi`, header `X-API-Key`. Body: `{customer, requestedDate, products}` with up to 1,000 codes. Any customer value works.
- Availability: `scheduleLines` is empty when undeliverable. `logisticModel` is `Stock` or `Terminal`.

## Known values for tests

- Category `10400` + tag `FREE_FROM_LACTOSE` → 35 products.
- 1,000 L → `464201`: 1,000 units, `465039`: 200, `463038`: 50, `464179`: 100.
- `460004` has no allergen info. `460000` contains `AE` and `BM`.
- Only 189 products have official substitutes, e.g. `460025` → `460150`.

## Don't

- Don't call the APIs for the whole catalog.
- Don't make live API calls in tests. Use recorded responses in `catalog/tests/fixtures/`.
