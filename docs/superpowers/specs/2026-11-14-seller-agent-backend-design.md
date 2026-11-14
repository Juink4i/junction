# Backend rebuild with a seller agent: design

Date: Sat 14 Nov 2026. Status: design agreed in chat, waiting for review of this file.

## 1. What this changes

Today the buyer agent does the shopping work: it knows the catalog's tag codes, drops wrong products, ranks the offers and handles shortages, all from its Gemini prompt. The server only searches by substring, prices what it is given and checks the order.

After this rebuild the server does that work, so any agent can buy well, not only ours:

- The buyer agent turns the user's sentence into a structured request and passes it on. It knows no catalog codes.
- A **seller agent** inside the server removes products that do not do the job that was asked for.
- Plain code maps plain words to catalog tags, ranks the offers, builds a split order when stock is short, and offers alternatives when an order needs a person.
- A valid mandate is needed to connect at all, not only to order.

**The AI suggests. Plain code decides.** This still holds. The seller agent can only remove products from a search result. It never sees a price, a limit or a mandate, and no rule lives in its prompt.

## 2. Decisions already made

| Decision | Choice |
|---|---|
| Seller agent | Lives inside the tools. No free-text conversation between agents. |
| Missing parameters | Plain code replies with a structured question. No AI. |
| Words to tags | The server owns the mapping. The buyer agent sends plain words such as "lactose-free". |
| Onboarding | Unchanged, except that "Every product must be" offers all 21 properties in the product file instead of 2. |
| Unusual amount | The 5× rule stays, and now sends the order straight to a person. The ask-the-agent round trip is removed. |
| Ranking | Moves from the buyer agent's prompt into plain server code. Same order as today. |
| Shortage | The server builds the split by walking down the ranked list. No extra call. |
| Contract B | Changes: three tools and the connection. Contract A does not change. |
| Who builds it | One developer, on branch `backend-rebuild`, across `server/`, `catalog/`, `agent/`, `demo/`, `onboarding/` and `web/`. The folder rule is waived. |

## 3. The new flow

```
Kitchen ──signs──▶ mandate (onboarding, unchanged)

Buyer agent (Gemini + ADK): parses the sentence, passes it on, follows the answer
   │ MCP, with the mandate in the Authorization header
MCP server
   ├─ connection check        plain code   mandate valid, or 401 with the onboarding link
   ├─ search_products         plain code   words → tags, text search
   │                          seller agent removes products that don't do the job
   ├─ request_quote           plain code   unit maths, prices, ranking, split, signed quotes
   ├─ place_order             plain code   mandate, quote, Policy, alternatives, log
   └─ get_product, get_approval_status, get_audit_log (unchanged)
   │ shortlist only
Catalog ──▶ Valio Aimo price and availability APIs
```

1. **Onboarding.** As today. The kitchen ends with a signed mandate, registered with `POST /buyers`.
2. **Connect.** The buyer agent opens the MCP connection with the mandate in the header. A missing, invalid or expired mandate is refused with the reason and the onboarding link. The agent shows both to the user and stops.
3. **Parse.** The user says what they need. The buyer agent turns it into product words, must-have words, amount, unit and need-by date.
4. **Search.** The agent calls `search_products`. The server maps the words to tags, searches, and the seller agent removes what does not fit. The reply lists what was kept and what was dropped, with reasons.
5. **Quote.** The agent calls `request_quote` with the product ids from step 4. The server returns up to five ranked options. Each option is its own signed quote and says what the mandate would decide for it.
6. **Order.** The agent calls `place_order` with one option's `quote_id`. The server checks the mandate, the quote and the rules. The order is confirmed, sent to a person, or rejected. When it is not confirmed, the reply lists the alternatives from the same request that would go through alone.

## 4. Connection: the mandate is shown first

- Every request to `/mcp` must carry `Authorization: Bearer <mandate token>`.
- Plain code checks it the same way `place_order` does today: the buyer's key is registered, the signature is valid, the fields are well formed, and it has not expired.
- A refusal is HTTP 401 with `{code, message, retryable: false, onboarding_url}`. The codes are `mandate_missing`, `mandate_invalid` and `mandate_expired`. Refusals are logged.
- Every tool call checks the mandate again, because a session can outlive a mandate. A mandate that expires mid-session gets the same error from the tool.
- The buyer is known from the first call. So search can apply the mandate, quotes are issued to one buyer, and the log names the mandate's agent instead of whatever name the client declares.
- `place_order` no longer takes `mandate_token`. It uses the connection's mandate.
- The other HTTP routes (`/buyers`, `/approvals`, `/log`) are unchanged.

Known limit: a copied mandate token can search and quote. It cannot order when the mandate names an agent key, because the agent still signs every order. Production path: OAuth 2.1 as in the MCP authorization spec, with proof of possession.

## 5. Contract B, new shapes

Six tools, as before. `get_product`, `get_approval_status` and `get_audit_log` keep their shapes. `get_product` and every product summary gain `properties`: the readable names of the product's tags.

### `search_products`

Input: `product` (plain words), `must_have?` (list of plain words), `amount?`, `unit?`.

```
SearchResult:
  status: "ok"
  understood:  {product, must_have: [names], from_mandate: [names]}
  products:    [ProductSummary + properties]
  dropped:     [{id, name, reason}]
  screened_by: "seller agent" | "keyword rules"
  total_matches, truncated: bool, hint?
```

### `request_quote`

Input: `product_ids` (1 to 40, from search), `amount`, `unit` ("L" or "KG"), `need_by`, `preferences?: {priorities?, pack_size?}`.

```
QuoteSet:
  status: "ok"
  set_id
  asked:       {amount, unit, need_by}
  options:     [{rank, label, trade_off, expected: {status, reasons}, quote: Quote}]   # up to 5, best first
  not_offered: [{product_id, name, reason}]
```

`Quote` keeps today's shape. Each line gains `closing_time`, the order cut-off. `label` is "best", "better", "good", "other" or "split". `expected` is what the mandate would decide if that option were ordered now. It is a forecast, and the decision at order time is the one that counts.

### `place_order`

Input: `quote_id`, `rationale`, `agent_signature?`. The agent signature now covers `{quote_id, mandate_id}`.

```
OrderResult:
  status: "confirmed" | "pending_approval" | "rejected"
  order_id?, approval_id?, reasons: [str]
  alternatives?: [{quote_id, rank, label, summary, total_eur}]   # up to 3, best first
```

### Questions from the server

`search_products` and `request_quote` reply like this when something is missing or not understood:

```
{status: "needs_clarification", missing: [fields], unknown: [words], known_properties: [names], question}
```

Every error is still `{code, message, retryable}`.

## 6. Words to tags: the server's vocabulary

The product file has exactly 21 nutrition claims. `catalog/names.py` gains one map from each code to a readable name, beside the allergen and category maps it already holds. A test fails if the product file has a tag without a name.

| Code | Name | Products |
|---|---|---|
| `FREE_FROM_LACTOSE` | lactose-free | 4,178 |
| `FREE_FROM_GLUTEN` | gluten-free | 3,049 |
| `VEGAN` | vegan | 2,959 |
| `VEGETARIAN` | vegetarian | 2,358 |
| `FREE_FROM_PRESERVATIVES` | preservative-free | 1,526 |
| `FREE_FROM_COLOURING_AGENTS` | no colouring agents | 932 |
| `FREE_FROM_ADDITIVES` | additive-free | 690 |
| `NO_ADDED_SUGARS` | no added sugar | 662 |
| `HIGH_FIBRE` | high-fibre | 420 |
| `FREE_FROM_EGGS` | egg-free | 418 |
| `HIGH_PROTEIN` | high-protein | 417 |
| `LOW_SODIUM_SALT` | low-salt | 390 |
| `FREE_FROM_SWEETENERS` | no sweeteners | 358 |
| `FREE_FROM_SOY` | soy-free | 337 |
| `LOW_LACTOSE` | low-lactose | 321 |
| `FREE_FROM_FAT` | fat-free | 158 |
| `FREE_FROM_WHEAT` | wheat-free | 141 |
| `LOW_FAT` | low-fat | 110 |
| `FREE_FROM_ARTIFICIAL_SWEETENERS` | no artificial sweeteners | 24 |
| `FREE_FROM_GMO` | GMO-free | 14 |
| `FREE_FROM_SODIUM_SALT` | salt-free | 13 |

The one map is used in three places:

- **Onboarding.** "Every product must be" lists all 21 names, most common first. The mandate still stores codes, so the mandate format and the server's checks do not change.
- **Search.** The buyer agent sends names. Plain code turns them into codes.
- **Messages.** Search results, reasons and log entries show names, not codes.

How search matches words (plain code, no AI):

- Each property has a short list of synonyms in English and Finnish, for example "lactose free", "no lactose", "laktoositon". Case, hyphens and spaces are ignored.
- A property named inside the `product` words is lifted out. "lactose-free milk" becomes the text "milk" with the must-have "lactose-free".
- A must-have word the vocabulary does not know is never guessed. The server replies `needs_clarification` with the 21 known names. A must-have is a safety property, so an unknown one is not treated as met.
- A tag is a claim. A product that does not carry the claim is treated as not having the property.

## 7. `search_products`, step by step

1. **Check (plain code).** No product words: ask for them.
2. **Map (plain code).** Turn must-have words into tags, as in section 6.
3. **Apply the mandate (plain code).** Add the mandate's must-keep tags. If the mandate allows only some categories, keep only those. The reply says what came from the mandate.
4. **Search (plain code).** Text search with the tags, as the catalog does today. Up to 100 candidates. More than that sets `truncated` and a hint to narrow the request.
5. **Screen (seller agent).** One Gemini call decides, for each candidate, whether it does the job that was asked for.
6. **Reply and log.** Kept products, dropped products with reasons, and which screener ran.

Step 4 has no widening to "the most common category". On the real data that step added one product for milk and 152 bakery products for butter.

For lactose-free milk under the hotel's mandate, step 4 gives 34 candidates. At least nine of them are wrong and should be dropped: three coffee milks, one café milk, four sour milks and a 2 cl portion pack. Small cartons of 2 to 5 dl are a judgement call that depends on the amount asked for.

## 8. The seller agent

One job: given a need and a list of candidates, say which ones to keep.

- **Sees:** the product words as sent, the must-have names, the amount and unit, and for each candidate its id, English and Finnish name, sales unit and property names.
- **Never sees:** descriptions, prices, stock, the mandate, limits, or anything about another buyer. Descriptions are free text from suppliers, which is where an injected instruction could sit.
- **Answers:** for each candidate id, keep or drop, with a reason of a few words.
- **Runs on:** Gemini through `google-genai`, structured output, temperature 0, a 10-second limit. The model is set by `SELLER_MODEL`.

What code enforces around it:

- Only ids from the candidate list count. It cannot add a product.
- A candidate it gave no answer for is judged by the keyword rules.
- If the call fails, times out or returns something unusable, the keyword rules judge every candidate. Search never fails because of the AI.
- Every screening is logged with the counts and the reasons.

The keyword rules are the list scripted mode uses today (coffee, latte, chocolate, sour milk, yoghurt, low-lactose, plant drinks, cream, portion packs), moved into the server. A kind the buyer asked for by name is not dropped. `SELLER=keyword` forces these rules, for tests and rehearsals without Gemini.

The Gemini call runs outside the server's database lock, so the approval and log pages stay responsive while it runs.

## 9. `request_quote`, step by step

1. **Check (plain code).** Amount, unit and need-by date must be there and valid. Otherwise ask.
2. **Prices and availability.** One call to each Valio Aimo API for all the product ids.
3. **Unit maths.** Sales units needed for each product, rounded up. This runs after step 2 so it reuses the prices just fetched.
4. **Leave out what cannot be offered.** No price, not orderable, measured in the other unit, not in the catalog, or the mandate would reject it outright (a blocked allergen, a category that is not allowed). Each goes into `not_offered` with the reason.
5. **Rank (plain code).** See below.
6. **Split if the first choice is short.** See below.
7. **Forecast.** Run Policy on each option without saving anything, to fill `expected`.
8. **Sign and store.** Each of the top five options becomes a signed quote, valid for 15 minutes, stored with the buyer it was issued to, its set and its rank.

### Ranking

The same order the buyer agent's prompt uses today, now in code:

1. Arrives by the need-by date, and the cut-off has not passed.
2. The buyer's preference order if it sent one. Otherwise: price, earliest delivery, reliability, sustainability.
3. Preferred pack size, if sent.
4. Product id, so the order is stable.

| Preference | Better means |
|---|---|
| price | Lower total. Totals are compared in steps of 2% above the cheapest, so near-equal prices tie and the next preference decides. |
| reliability | Higher delivery reliability, in whole percent. Unknown counts as lowest. |
| finnish | Country of origin is Finland. |
| sustainability | Carries an organic or eco label, then lower carbon footprint. |

Preferences only order products that already fit. They are not rules, and they arrive as an input to `request_quote`, never as part of the mandate.

Each option carries a one-line trade-off written by code: the price difference to the best option, the delivery date and the pack size.

### Shortage

A product whose confirmed stock is below what is needed is not offered on its own. If that product is the first choice:

- The first option is a split: all that is left of the first choice, then the remainder from the next products down the list.
- It is labelled "split", and the trade-off says how much comes from each product.
- The other options follow, each a single product that covers the whole amount.

Stock that Valio Aimo reports as a placeholder is "unconfirmed" and counts as enough, as today.

## 10. `place_order`, step by step

Checks, in order. The first failure decides.

1. The connection's mandate is still valid.
2. The agent's signature, when the mandate names an agent key.
3. A repeat call with the same `quote_id` returns the same order.
4. The quote exists, was issued to this buyer, has a valid signature and has not expired.
5. One live order per request (below).
6. Policy.

What changes in Policy:

- **Unusual amount.** More than 5× the usual order in the mandate now gives `pending_approval`, with the reason. The Decisions API stays as a second opinion that can only add a reason for the person. It is not called when forecasting.
- **Cut-off.** A line whose `closing_time` has passed by the time of the order counts as past its cut-off, so the order goes to a person. No API call is needed.
- `confirm_unusual` and the `needs_clarification` order status are removed. Orders end as `confirmed`, `pending_approval` or `rejected`.

Everything else in Policy is unchanged: allergens, categories, order limit, line limit, budget, delivery days, late delivery, missing allergen information, must-keep tags.

### Alternatives

When an order is not confirmed, the reply lists up to three other options from the same quote set that have not expired and that Policy would confirm on their own, best first. Spending by the order they would replace is not counted against them. The log records which alternatives were offered.

### One live order per request

Offering alternatives must not lead to buying twice.

- Ordering another option from a set that has an order waiting for approval withdraws the waiting one. It ends as `rejected` with the reason "Withdrawn: the buyer's agent ordered another option from the same request", and its approval closes.
- If the set already has a confirmed order, the new one is refused with that order's id.

## 11. Caching and API calls

- Quotes stay valid for 15 minutes. Price and availability answers stay cached for 5 minutes.
- A quote request is exactly two API calls, however many products it covers. Today a full order makes two or more: unit maths adds two for each product whose pack size is missing from the product file, and a shortage adds two for the substitute hint.
- The recorded responses show prices fixed until at least 31 December. Only stock and cut-off go stale, and the cut-off is now checked at order time from the quote itself.
- Stock is still not held. The mock API has no reservations.

## 12. The buyer agent

- Sends the mandate in the connection header. Stops with the server's message and the onboarding link when refused.
- Its instructions shrink to: parse the request, search, answer the server's questions from the request or by asking the buyer, quote every product the search returned, order the best option unless the buyer said otherwise, follow the decision, summarise.
- The Finnish vocabulary, the drop rules and the ranking rules leave its prompt.
- Tool code, not the AI, attaches the buyer's preferences to `request_quote` and shows the options card from the reply. `present_options` is removed.
- `record_request`, `ask_buyer`, `get_product`, `get_approval_status` and `get_audit_log` stay.
- Scripted mode gets a new, shorter plan for the new flow.

## 13. What else is touched

- **State database.** `quotes` gains the buyer, the set and the rank. An existing database is upgraded on start.
- **Fake trade server.** Stays for rehearsals and tests and follows the new contract. It reuses the server's vocabulary, ranking and keyword rules instead of copying them.
- **Demo scenes.**
  - Ten times the usual: goes straight to a person. No confirmation step.
  - Shortage: the split comes from the server as the first option.
  - Injection: the gullible agent still reads descriptions and orders ten times too much. The 5× rule sends it to a person, who rejects it. The seller agent never saw the description.
- **Docs.** `CLAUDE.md`, the folder `CLAUDE.md` files, `docs/runner-tasks.md` (Contract B), `docs/valio-aimo-discussion.md` and `README.md`.

## 14. Testing

Tests first, as before. No test calls Gemini or Valio Aimo: the seller agent is replaced by a fixed fake, and the catalog by the fake catalog or recorded responses.

| Area | What the tests show |
|---|---|
| Connection | No mandate, a bad one and an expired one each get 401 with the right code. A mandate that expires mid-session fails the next tool call. |
| Vocabulary | Every tag in the product file has a name. Synonyms match. A property inside the product words is lifted out. An unknown must-have gets a question, not a guess. |
| Search | Mandate tags and categories are applied. The seller agent cannot add a product. A missing answer and a failed call fall back to the keyword rules. Dropped products are returned and logged. |
| Ranking | Each key, each preference, the 2% price tie and the stable last key. |
| Quote | Two API calls per request. One signed quote per option. A quote issued to one buyer is refused for another. Rejected products are never offered. The forecast matches Policy. |
| Shortage | A short first choice gives a split first. A short product is never offered alone. |
| Order | Unusual amount goes to a person. A cut-off passed since the quote goes to a person. Alternatives are only options Policy would confirm. Ordering an alternative withdraws the waiting order. A second order after a confirmed one is refused. |
| Agent | The header is sent. A refusal stops the run with the onboarding link. The new instructions contain no rule and no catalog code. |
| Demo | All scenes play in scripted mode against the fake server. |

## 15. Build order and cut lines

Feature freeze is Sun 02:00. Each step leaves the tests passing.

1. Vocabulary: the name map, the matcher, the onboarding list.
2. Connection check on `/mcp`, and the agent sending the header.
3. `search_products` with the keyword rules only.
4. `request_quote`: ranking, quote sets, forecast.
5. `place_order`: connection mandate, unusual amount to a person, cut-off check.
6. Buyer agent: new tools, instructions and scripted plan. Fake server follows.
7. **The flow works end to end here.**
8. Seller agent on Gemini.
9. Shortage split.
10. Alternatives and one live order per request.
11. Demo scenes and docs.

If time runs short, cut from the bottom. Steps 8 to 10 each stand alone: without 8 the keyword rules screen, without 9 a short product is left out and the next one is offered, without 10 a refused order has no alternatives.

## 16. Not in this rebuild

- A free-text conversation between the buyer and seller agents.
- AI mapping of unknown words to tags.
- Packaging labels such as organic as must-haves.
- Enforcing the mandate's `substitution.allowed` and `max_price_increase_pct`. They stay unenforced, as today.
- Revoking a replaced mandate before it expires.
- Holding stock for a quote.
- Alternatives on the approval page. They are in the order reply and the log.

## 17. Open decision

The request said the server should check whether "the quantity exceeds that given in the mandate". The mandate has no quantity limit today. It has euro limits and the kitchen's usual orders.

This design reads the quantity check as the existing rule: more than 5× the usual order goes to a person. Nothing is added to the mandate or to onboarding.

The other reading is a new, explicit limit such as "at most 200 L of milk per order", set at onboarding. That would add one onboarding question, one mandate field and one Policy rule. It is not in this design unless asked for.
