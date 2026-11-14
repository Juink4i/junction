# catalog: products, unit maths and Valio Aimo prices

Contract A from `docs/runner-tasks.md`. Runner 2's server imports `catalog.api`.

## Setup

1. Put the four Valio Aimo files in `data/raw/`. They're on the portal at https://junction26.valioaimo.fi.
2. Put `VALIO_API_KEY=...` in `.env`.
3. Run these commands:

```
uv run python -m catalog.load        # builds data/catalog.db (17,546 products, about 8 s)
uv run pytest catalog                # all tests use recorded API answers, no network
uv run python -m catalog 1000 L 2026-11-16 --category 10400 --tags FREE_FROM_LACTOSE   # live check
```

## The five functions (plus helpers)

```python
from catalog import api

api.search_products(text, category=None, must_have_tags=[], limit=20) -> list[ProductSummary]
api.get_product(product_id) -> Product | None
api.units_needed(product_id, amount, unit) -> UnitPlan          # unit "L" or "KG"
api.price_and_availability(product_ids, delivery_date) -> dict[str, Offer]
api.substitute_candidates(product_id, must_keep_tags, max_price_increase_pct, delivery_date) -> list[Offer]

# Helpers, not in Contract A but useful for Policy and the agent:
api.allergen_status(product_id, code) -> "contains" | "may_contain" | "free_from" | "unknown"
api.category_name("10400") -> "Milk and sour milk"
api.allergen_name("AM") -> "Milk"
```

The models are pydantic, in `catalog/models.py`. Use `.model_dump(mode="json")` for MCP output.

## What callers must know

| Situation | What happens |
|---|---|
| Product has no price | Left out of the `price_and_availability` dict. A missing key means "no offer". |
| Product can't be delivered at all (e.g. `464440`) | `orderable=False`, `available_date=None`, `logistic_model=None`. Contract A typed it as Stock/Terminal only, but the data has none. |
| Stock unknown or placeholder (999999, 666666666, 9999999999) | `available_units=None`. Stock products often report real counts (e.g. 698). |
| Order cut-off passed | `cutoff_passed=True`. **Decision: we treat this as "won't arrive on `available_date`"**, even though the API still shows that date. The API docs say you must order before `closingTime` to receive goods on `availableDate`. |
| Litres asked for a product priced per kg (`472492`) | `units_needed` raises `catalog.units.UnitMismatch` (a `ValueError`). No density guessing. |
| Unknown product id | `units_needed` / `substitute_candidates` / `allergen_status` raise `KeyError`. `get_product` returns `None`. |
| API down or rate-limited | Retried once, then `catalog.valio_client.ValioApiError` with `.retryable`. Map it to `{code, message, retryable}`. |
| Allergen safety | `allergen_info_missing` is True only when the supplier gave no allergen data at all. A product can say "contains milk" and nothing else, so gluten is still unknown. **Policy should check each blocked allergen with `allergen_status` and treat `"unknown"` like missing info.** |

## How it decides

- **Search** matches every word as a substring of the fi/en/sv names and brand, because Finnish compounds hide words ("maito" is inside "kevytmaito"). `tags` are nutrition claims such as `FREE_FROM_LACTOSE`, `LOW_LACTOSE` and `VEGAN`. Allergen free-from codes are in `allergens_free_from`, not in `tags`.
- **Unit maths** uses the product file's litre/kg figure times the packaging ladder when that figure is clean. Otherwise it uses unit price ÷ price per litre or kilo from the API. Both prices are rounded to the cent, so the raw ratio is noisy (31.31 / 1.57 = 19.94). We pick the roundest pack size that fits both prices (20 L). When both sources exist and differ by more than 2%, Valio Aimo's price wins. A test checks that they agree for all 35 lactose-free milks.
- **Prices and availability** use one call to each endpoint per request, for ids not cached in the last 5 minutes. "Cut-off passed" is computed when the answer is read, so it stays right while cached. The API answers 403 to Python's default User-Agent, so we send our own.
- **Substitutes** must be in the same category, keep every must-keep tag, and be orderable and on time with the cut-off not passed. They must also be within the cap on price per litre or kilo, priced in the same unit. Valio Aimo's official substitutes come first, then the cheapest.

## Demo overrides: `data/overrides.json`

Patches any `Offer` field (by product id under `"offers"`) or `Product` field (under `"products"`). The file is re-read when it changes and applied on top of cached API answers. See `data/overrides.example.json` for the shortage, late-delivery and prompt-injection scenes. Keys starting with `_` are ignored.

## What the live data says (Sat 14 Nov, for Monday 16 Nov)

These affect the demo script (`docs/valio-aimo-discussion.md` §5):

1. **The cheapest on-time option is `464306` at EUR 1.01/L → EUR 1,010 for 1,000 L**, under the hotel's EUR 1,500 limit, so scene a would be confirmed without a human. Lower the demo mandate's `max_order_eur` (e.g. to 1,000), or the buyer must want a specific product.
2. **All supplier-delivered (Terminal) products missed their cut-off** (Thu 12 Nov 15:00). Only Valio Aimo's own stock (cut-off Sun 15 Nov 17:00) arrives on Monday.
3. **Real low stock exists**: `463380` has 698 units, `469363` 384 and `462775` 51. The shortage scene can run on real data. The override file is a back-up.
4. `464201`'s official substitute `464440` can't be delivered at all, a ready-made example of code finding another substitute.
