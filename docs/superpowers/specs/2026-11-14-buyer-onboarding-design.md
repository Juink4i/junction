# Buyer onboarding: design

Date: Sat 14 Nov 2026. Status: design agreed in chat, waiting for review of this file.

## 1. What this adds

Today each buyer's mandate is hard-coded in `server/make_mandate.py`, with made-up order history. Nothing lets a kitchen state its own rules.

Onboarding is that missing step. A kitchen answers one page of questions, signs the result, and its agent can order straight away. It also becomes the first scene of the demo, so judges see where the rules come from.

## 2. Decisions already made

| Decision | Choice |
|---|---|
| Size | A new demo scene. If time runs out, it stays as a working feature off-stage. |
| Who builds it | Runner 3, on branch `bot`, including the `server/` parts. The folder rule is waived for this feature only. Tell Runner 2 before starting. |
| Form | One page with kitchen-type templates. No AI takes part in onboarding. |
| Agent key | Included, late in the build order so it can be dropped. |
| Contract B | Gains one HTTP endpoint (`POST /buyers`) and one optional `place_order` input (`agent_signature`). No existing shape changes. |

Existing behaviour is protected: a mandate without the new sections is treated exactly as today. The hotel, café and school mandates and the five current scenes are not touched.

## 3. Every answer is a rule or a preference

- A **rule** goes into the signed mandate. Server code enforces it.
- A **preference** goes into a profile that only the buyer's agent reads. It helps the agent choose between products that already fit. Nothing enforces it, and the server never receives it.

The page shows one of these two labels beside every answer.

| Group | Question | Lands in | Enforced by |
|---|---|---|---|
| Kitchen | Name, type, approver | Mandate `buyer`, `approvers` | Existing |
| Safety | Allergens that must never arrive (the 14 EU allergens) | Mandate `hard_rules.blocked_allergens` | Server rejects. Existing |
| Safety | When a product has no allergen information: a person checks (`human`), or refuse (`reject`) | Mandate `hard_rules.unknown_allergens` | Existing |
| Safety | Every product must be: lactose-free (`FREE_FROM_LACTOSE`), vegan (`VEGAN`) | Mandate `substitution.must_keep` | A person. Existing |
| Money | What the agent may buy (categories, or anything) | Mandate `auto_approve.allowed_categories` | Server rejects. Existing |
| Money | The agent may spend alone, per order | Mandate `auto_approve.max_order_eur` | A person above it. Existing |
| Money | Budget per week or per month | Mandate `budget` | A person when the total would pass it. **New** |
| Money | What matters most: price, reliable delivery, Finnish origin, sustainability | Profile `priorities` | Nothing |
| Delivery | Days the kitchen can receive goods | Mandate `delivery.days` | A person on another day. **New** |
| Delivery | Preferred pack size: small or large | Profile `pack_size` | Nothing |
| Rhythm | Usual orders: what, how much, every week or month | Mandate `usual_orders`, and the profile | The existing 5× check, with a new source |

Notes:

- **"Every product must be"** is the honest wording for `substitution.must_keep`. The server checks that tag on every order line, not only on substitutes.
- **The page does not offer `allow`** for missing allergen information, although the server accepts it. Unknown is never safe.
- **Optional answers:** the budget, the delivery days and the usual orders can be left empty. The mandate then has no such part. The per-order amount is required.
- **Weekly or monthly does two jobs.** It is the budget period, and it is the rhythm of each usual order.
- **Usual orders give a new kitchen a baseline.** Today the 5× unusual-order check skips a buyer with no history. With declared usual orders it works from the first order.
- **Not asked:** the per-line cap, `substitution.allowed` and `substitution.max_price_increase_pct`. The server does not enforce the last two today, so the page must not present them as rules. Templates set them to the current demo defaults.

## 4. What onboarding produces

Example: a day-care, "Päiväkoti Aurinko".

**Mandate** (signed by the kitchen; new parts marked):

```json
{
  "mandate_id": "mnd_paivakoti-aurinko-3f2a_001",
  "buyer": "Päiväkoti Aurinko",
  "agent_id": "agent-paivakoti-aurinko-3f2a",
  "agent_key": "-----BEGIN PUBLIC KEY----- ...",
  "valid_until": "2027-11-14",
  "auto_approve": { "max_order_eur": 100, "allowed_categories": ["10400"] },
  "substitution": { "allowed": true, "must_keep": ["FREE_FROM_LACTOSE"], "max_price_increase_pct": 10 },
  "hard_rules": { "blocked_allergens": ["AP", "AN"], "unknown_allergens": "human", "no_delivery_after": "need_by_date" },
  "budget": { "period": "week", "max_eur": 150 },
  "delivery": { "days": ["MON", "THU"] },
  "usual_orders": [ { "category": "10400", "amount": 40, "content_unit": "L", "every": "week" } ],
  "approvers": ["kitchen.lead@aurinko.example"]
}
```

New and optional: `agent_key`, `budget`, `delivery`, `usual_orders`. `valid_until` is one year after signing.

**Profile** (never sent to the server):

```json
{
  "buyer_id": "paivakoti-aurinko-3f2a",
  "name": "Päiväkoti Aurinko",
  "kitchen_type": "daycare",
  "priorities": ["price", "reliability", "finnish", "sustainability"],
  "pack_size": "small",
  "usual_orders": [ { "what": "lactose-free milk", "amount": 40, "unit": "L", "every": "week" } ]
}
```

**Review sentences.** Before signing, the page shows the result as plain sentences, each labelled. Examples:

| Label | Sentence |
|---|---|
| Rule | Never deliver products that contain or may contain: Peanuts, Tree nuts. |
| Rule | If a product does not say whether it has those allergens, a person must check it. |
| Rule | The agent may spend up to €100 on one order by itself. Above that, a person approves. |
| Rule | Spending is capped at €150 per week. An order that would pass it goes to a person. |
| Rule | Goods can arrive on Monday and Thursday. Any other day needs a person's approval. |
| Rule | An order more than 5 times the usual (40 L of milk each week) is checked with the kitchen first. |
| Rule | Orders must be signed by this kitchen's agent. A copy of this mandate alone cannot place an order. |
| Preference | When several products fit, prefer the lowest price, then reliable delivery, then Finnish origin, then sustainability. |
| Preference | Prefer small packs. |

A sentence is labelled Rule only once the server enforces it. See section 11 for the two that start as something less.

**Buyer id.** A slug of the kitchen name plus four random hex characters, e.g. `paivakoti-aurinko-3f2a`. Each sign-up gets a new id, so rehearsals never collide.

**Files**, in `data/buyers/<buyer_id>/`, which must be git-ignored before the first file is written:

| File | Holds |
|---|---|
| `mandate.jwt` | The signed mandate |
| `profile.json` | The profile |
| `buyer_key.pem` | The kitchen's private key |
| `agent_key.pem` | The agent's private key |

**Templates.** Four kitchen types prefill the form:

| | Day-care | School | Hotel | Café |
|---|---|---|---|---|
| Blocked allergens | AP, AN | AP, AN, AE | none | none |
| No allergen info | person | person | person | person |
| Every product must be | lactose-free | none | lactose-free | none |
| May buy | 10400 | anything | 10400 | 10400 |
| Alone, per order | €100 | €800 | €1,500 | €500 |
| Budget | €150 a week | €3,000 a month | €6,000 a month | €600 a week |
| Delivery days | Mon, Thu | Mon, Wed, Fri | Mon to Fri | Mon to Fri |
| Pack size | small | large | large | small |
| Usual order (milk) | 40 L a week | 200 L a week | 1,000 L a week | 20 L a week |

All four start with priorities in the order price, reliability, Finnish origin, sustainability.

## 5. Keys: who signs what

Two key pairs. Each private key stays where it was made. Only public keys travel.

| Key pair | Made by | Private half | Public half |
|---|---|---|---|
| Buyer key | The kitchen, at onboarding | Stays with the kitchen. Signs the mandate. | Sent to Valio Aimo in `POST /buyers` |
| Agent key | The agent | Stays in the agent's process. Tool code uses it; the AI model never sees it. Signs each order. | Written into the mandate as `agent_key`, so the kitchen's signature covers it |

On each order the server follows the chain: buyer key → mandate → agent key → this order.

| Threat | Result |
|---|---|
| Someone copies the mandate | Useless without the agent's private key |
| Someone steals the agent's key | Still held to the mandate's rules. The kitchen signs a new mandate naming a new agent key; its own key does not change. |
| Someone replays a captured order | Gets the same order back. A quote id can be used once. |
| The agent is fooled by a prompt injection | The order is still signed. The signature proves who sent it, not that it is sensible. Policy handles this, as today. |

In the demo both private keys sit on one laptop. They are in separate files and made by separate code: `onboarding/` makes the buyer key, `agent/` makes the agent key and hands over only the public half. Browser-side signing is ruled out, because the phone reaches the page over plain HTTP, where the browser's crypto API is unavailable.

## 6. Server changes (`server/`)

### 6.1 `POST /buyers`

Plain HTTP, not a seventh MCP tool. An agent must never be able to register or change a mandate.

Request: `{"public_pem": "...", "mandate_token": "<signed mandate>"}`. The buyer id is the token's `kid` header.

Checks, in order:

| # | Check | If it fails |
|---|---|---|
| 1 | Body is JSON with both fields as text | 400 `bad_request` |
| 2 | `kid` is 3 to 64 lowercase letters, digits or hyphens | 400 `mandate_invalid` |
| 3 | No buyer with this id exists | 409 `buyer_exists` |
| 4 | `public_pem` is an Ed25519 public key | 400 `bad_key` |
| 5 | The token is signed by that key, has the right shape and has not expired | 400 `mandate_invalid`, listing the problems in plain language |

Then, in one transaction: store the buyer and its key, and add one `order_history` row for each usual order. Write a `register_buyer` entry to the hash-chained log, naming the kitchen, the mandate id and the declared usual orders.

Response: 201 `{"buyer_id", "mandate_id", "status": "registered"}`. Errors use the usual `{code, message, retryable}`.

`verify_mandate` is split so that registration and ordering share one function that checks a token against a given key.

### 6.2 Mandate shape

`_shape_problems` gains checks for the four optional parts. A typo must stop the order, as for existing fields.

| Part | Valid when |
|---|---|
| `agent_key` | Text that loads as an Ed25519 public key |
| `budget` | An object with `period` of `week` or `month`, and `max_eur` a number of euros |
| `delivery` | An object with `days`, a non-empty list drawn from `MON` to `SUN` |
| `usual_orders` | A list of objects with `category` text, `amount` above zero, `content_unit` of `L` or `KG`, `every` of `week` or `month` |

### 6.3 Two new policy rules

Both produce `pending_approval`. The order of checks is unchanged: hard stops, then the unusual-amount question, then "needs a person", then confirmed.

**Budget.** `decide` gains one input, `spent_in_period`, so it stays pure. The service works it out:

- It is the sum of `total_eur` over the buyer's other orders in the current period whose status is `confirmed` or `pending_approval`. Rejected orders drop out, including those a person rejected.
- A week runs from Monday 00:00 to the next Monday. A month is the calendar month. Both use the server clock (UTC), like every other server timestamp.
- If `spent_in_period + total_eur` is above `budget.max_eur`, a person decides. Example reason: "This order of €64.00 would bring this week's spending to €172.00, over the weekly budget of €150.00."

**Delivery days.** For each line with a delivery date whose weekday is not in `delivery.days`, a person decides. Example reason: "Milk 1 L would arrive on a Wednesday. This kitchen receives goods on Monday and Thursday only."

### 6.4 Signed orders

`place_order` gains an optional input, `agent_signature`: a signed token (EdDSA) whose payload is exactly `{"quote_id", "mandate_id", "confirm_unusual"}`.

- If the verified mandate has an `agent_key`, the signature is required. It must verify with that key and its payload must match the call. Otherwise the order is `rejected` with a plain reason: the mandate names an agent key, the order was not signed by it, and a copy of the mandate alone cannot place orders.
- That rejection uses the existing refusal path that is not tied to an order, so it cannot use up someone's quote.
- If the mandate has no `agent_key`, the input is ignored and everything works as today.
- A successful order's log entry says it was signed by the agent key named in the mandate.

## 7. Buyer-side code

### 7.1 `onboarding/` (new package, plain code)

| Part | Does |
|---|---|
| Templates | The four kitchen types in section 4 |
| `build(answers)` | Returns the mandate, the profile and the review sentences. A pure function. |
| `problems(answers)` | Plain-language problems, shown before signing |
| `new_buyer_id(name)` | The slug plus four random hex characters |
| `enroll(answers, buyer_id, agent_public_pem, trade_http)` | Makes the buyer key, signs the mandate, calls `POST /buyers`, saves the files |

It does not import `agent/` or `server/`. Signing uses `jwt` and `cryptography`, which are already dependencies.

`agent_public_pem` may be empty; the mandate then has no `agent_key`. If the trade server does not accept the registration, `enroll` removes `data/buyers/<buyer_id>/`, so no half-registered kitchen is left behind.

Problems it reports: an empty kitchen name or approver; a per-order amount that is not a number of euros; a budget that is not above zero, or below the per-order amount; a usual order without an amount above zero, or in a category the agent may not buy; priorities that do not list each of the four once; any unknown allergen, category, tag or weekday code.

### 7.2 `web/`

| Route | Does |
|---|---|
| `GET /onboarding` | The page. `?preset=daycare` preselects a template. |
| `GET /api/onboarding/options` | Templates plus the names of allergens, categories, tags, weekdays and priorities, so the page hard-codes no list |
| `POST /api/onboarding/preview` | `{problems, sentences}` for the current answers |
| `POST /api/onboarding` | Enrols the kitchen. 201 with `{buyer_id, name, sentences}`, or the usual error shape |

The page is built for phone width first, because it sits inside the stage's phone frame. It has template chips, the four groups, the labelled review sentences (refreshed from the preview route as answers change) and one button, **Sign and register**.

The sign-up route picks the buyer id, asks `agent/identity.py` for that buyer's agent public key, and passes both to `enroll`.

On success the web server publishes an `onboarded` event. The chat page shows it as a card listing the rules and preferences.

### 7.3 `agent/`

- **Any buyer id.** `--buyer` accepts an onboarded id. The mandate is also looked up in `data/buyers/<id>/mandate.jwt`. An id that is neither a seeded buyer nor onboarded stops with a plain message.
- **Profile.** Loaded if `profile.json` exists. With no profile the agent behaves exactly as today.
- **Preferences block.** `build_instruction` gains an optional profile and adds a block that says: these are preferences, not rules; use them only to choose between products that already fit; this order of priorities replaces ranking points c to e; the preferred pack size; and the usual orders, so that "the usual" has a meaning.
- **The block holds no rule.** It must pass the same no-rule-words test as the rest of the instructions (`agent/tests/test_instructions.py`).
- **Agent key.** `agent/identity.py` creates the agent key for a buyer and returns the public half. The `place_order` tool attaches a signature when the buyer has an agent key. The model sees neither the key nor the signature.
- **Visible in the demo.** The run-start event lists the preferences in use.

## 8. The demo scene

A new first scene, key `o`: **"1 · A new kitchen signs up"**. The current scenes keep their keys (`a` to `e`) and are renumbered 2 to 6.

1. The stage's phone frame shows `/onboarding?preset=daycare`, labelled as the kitchen manager's phone.
2. The presenter adjusts an answer and taps **Sign and register**. The chat side shows the rules and preferences card.
3. Three seconds later the phone frame returns to the approvals page, which is empty.
4. The agent runs as the new kitchen: "We need 40 litres of lactose-free milk by Monday."
5. The order is **confirmed with no person involved**, and the approvals page stays empty. No current scene shows this outcome.

Keeping the demo hands-off:

- With `--scripted`, the runner submits the day-care preset itself after the usual pause.
- Otherwise it waits up to 45 seconds for the presenter, then submits the preset itself, so the demo never stalls.

The fake server (`demo/fake_server.py`) gains `POST /buyers` and remembers the registered mandate. It does not check signatures, the budget, delivery days or the agent signature. It is for rehearsals only.

Cost to the demo: about 25 seconds in a 2-minute run that is already full. The video edit has to make room.

## 9. When things go wrong

| Problem | What happens |
|---|---|
| Answers have problems | Shown in plain language. The sign button stays disabled. |
| Trade server not answering | The page says so. The buyer's folder is removed. |
| Trade server refuses (id taken, bad mandate) | The page shows the server's reason. The buyer's folder is removed. |
| Saving files fails after registration | The page reports it. The registered buyer cannot be used; sign up again to get a new id. |
| Agent run for a buyer with no profile | Works as today. |
| Order without a valid agent signature, for a mandate that names an agent key | Rejected and logged. The quote is not used up. |

## 10. Tests (written first)

| Area | Tests |
|---|---|
| `onboarding/` | One per row of the table in section 3. Preferences never appear in the mandate. Every template builds a mandate that passes the server's shape check. Each problem in 7.1 is reported. |
| Mandate shape | A bad `budget.period`, a bad weekday, a bad `usual_orders` row and a bad `agent_key` are each refused. |
| Policy | Under budget is confirmed. Over budget needs a person. Week and month boundaries. A delivery day outside the list needs a person. A mandate without the new parts behaves as before. |
| Registration | Accepted and logged, and the log still verifies. A duplicate id, a wrong key, a bad `kid` and an expired mandate are refused. Declared usual orders make a first order of more than 5× ask for confirmation. Two orders in one week take the second over the weekly budget. |
| Signed orders | A correct signature is accepted. A missing one, one from another key and one for another quote are rejected without using up the quote. A mandate without `agent_key` ignores the input. |
| Agent | The preferences block passes the no-rule-words test. No profile gives today's instructions unchanged. Mandate and profile load from `data/buyers/<id>/`. |
| Web | Preview returns problems and sentences. Sign-up calls the trade server, writes the files and publishes the event. With the trade server down, nothing is written. |
| Demo | The new scene ends `confirmed` with the fake server in scripted mode. |

## 11. Build order

Build order is priority order. Stop after any step and everything above it still works.

| # | Step | About |
|---|---|---|
| 1 | `onboarding/`: templates, `build`, `problems`, sentences | 45 min |
| 2 | Server: mandate shape, `POST /buyers`, log entry | 60 min |
| 3 | Server: budget rule | 30 min |
| 4 | `enroll`, web routes and the page. Add `data/buyers/` to `.gitignore` first. | 90 min |
| 5 | Agent: any buyer id, profile, preferences block | 40 min |
| 6 | Demo scene, scripted preset, fake-server endpoint | 50 min |
| 7 | Docs (section 14) | 20 min |
| 8 | Stage phone frame switches to the onboarding page | 20 min |
| 9 | Agent key: `agent/identity.py`, signed orders, server check | 60 min |
| 10 | Server: delivery-days rule | 30 min |

About 7.5 hours in total. Steps 1 to 7 are the feature, at about 5.5 hours. Until a later step is built:

- Without step 8, the onboarding page opens in its own browser tab.
- Without step 9, an onboarded mandate has no `agent_key` and is the only credential, like the seeded ones. The page shows no "orders must be signed" sentence. The two-key chain goes on the path-to-production slide.
- Without step 10, `build` puts delivery days in the profile and the page labels them a Preference. Step 10 moves them into the mandate and changes the label to Rule.

Step 2 adds the shape checks for `budget` and `usual_orders`. Steps 9 and 10 each add the shape check for their own part (`agent_key`, `delivery`).

## 12. Not in this feature

- Changing a mandate after sign-up, replacing a key, or revoking one.
- Proving who the kitchen is at registration. In the demo anyone can register. In production this sits behind Valio Aimo's customer login.
- Standing orders that run on a schedule. Usual orders only feed the baseline and the agent's "the usual".
- Adding real orders to the order history.
- AI help with filling in the form.
- Enforcing `substitution.allowed` and `max_price_increase_pct` on the server. This is an existing gap.
- Agent keys for the seeded hotel, café and school.
- The new rules in the fake server.

## 13. Open check before recording

The scene's "confirmed with no person" outcome depends on real data. The server treats an allergen that a product does not mention as unknown, and sends it to a person. So the milk the agent picks must declare every blocked allergen as free-from.

This could not be checked while designing: the machine had no `data/raw/` files. On a machine that has them:

```bash
uv run python -m catalog 40 L 2026-11-16 --category 10400 --tags FREE_FROM_LACTOSE
```

Then, for the best on-time product, `catalog.api.allergen_status(product_id, "AP")` and `"AN"` must both return `"free_from"`.

If they do not, pick one:

- Change the preset's blocked allergens to ones the product does declare.
- Keep them, and let the scene end with a person approving. That is still a true story: unknown is never safe.

## 14. Docs to update

| File | Change |
|---|---|
| `README.md` | The onboarding page in the screens table, the new scene, scene numbers |
| `docs/runner-tasks.md` | Contract B: `POST /buyers`, and `agent_signature?` on `place_order` |
| `docs/valio-aimo-discussion.md` | The mandate example's optional parts, two new rows in "Who decides", the demo list |
| `demo/shot-list.md` | The new scene |
| `.gitignore` | `data/buyers/` |
