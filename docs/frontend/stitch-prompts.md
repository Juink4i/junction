# Google Stitch prompts: frontend structure and screens

Stitch works best with one brief to set the style, then one prompt per screen. Paste **Prompt 0** first and keep the result as the style reference. Then paste each screen prompt in the same project. Use **Web** mode for screens 1, 2, 4, 5 and 6, and **Mobile** mode for screen 3.

---

## Prompt 0: app brief and visual style

```
Design a B2B web app called "Trusted Trade". It lets professional kitchens (hotels, cafés, school kitchens) see and control what their AI purchasing agent orders from a Finnish food wholesaler. The core idea: "The AI suggests. Plain code decides." The agent proposes orders; a rules engine on the server decides; people approve the exceptions; every step is in a tamper-evident log.

Users: a kitchen's procurement manager (on a phone, approving orders), and a presenter showing the system on a laptop.

Visual style: calm, trustworthy, Nordic. Lots of white space, clear hierarchy, no decoration. Primary colour deep teal (#0F5E6B), neutral greys, white cards with 12px radius and a subtle border instead of heavy shadows. Font: Inter. Numbers and IDs in a monospace font (JetBrains Mono).

Four order statuses appear everywhere and must be instantly recognisable, each with an icon and a label, never colour alone:
- Confirmed: green, check icon
- Needs clarification: blue, question-mark icon
- Pending approval: amber, person icon
- Rejected: red, stop icon

Also design two trust badges: "Log intact" (green, lock icon) and "Log broken at entry 12" (red, broken-chain icon).

Navigation: a left sidebar on desktop with Stage, Agent activity, Approvals, Audit log, Buy manually, Mandates. A bottom tab bar on mobile. A buyer switcher at the top shows "Hotel Chain Oy / Helsinki Central", "Café Kallio" and "Espoo School Kitchens".
```

## Prompt 1: Stage view (Web, 1440 px)

```
Screen "Stage" for presenting live to an audience on a projector. Large type, high contrast.
Top: a scene bar with the scene number and title, "1 · The everyday order", and a one-line subtitle: "A hotel needs 1,000 L of lactose-free milk by Monday."
Left two-thirds: the live agent activity feed (as in the Agent activity screen) with large text.
Right third: a realistic phone frame showing the Approvals screen with one pending card and big Approve / Reject buttons.
Below the phone: a QR code labelled "Approve on your phone".
Bottom strip: four small counters: Confirmed 2, Needs clarification 1, Pending approval 1, Rejected 1. Plus the "Log intact" badge.
```

## Prompt 2: Agent activity (Web)

```
Screen "Agent activity": a live stream of what the AI buyer agent is doing, newest at the bottom, like a chat transcript, but three kinds of rows must look clearly different:
1. Agent messages: chat bubbles with a small robot avatar, e.g. "Dropped coffee milk, latte and sour milk. 4 candidates left."
2. Tool calls to the server: compact monospace rows with an arrow, e.g. "→ request_quote(464306 · 1,000 L · by 2026-11-16)" and the result below in grey: "← quote q_f21665 · 1 line · €1,010.00".
3. Server decisions: full-width banners using the status colours, e.g. amber "Pending approval: Line costs €1,010.00, over the mandate's limit of €800.00 per line."
Also show an "Options" card with three choices labelled Best, Better and Good. Each has the product name, "1,000 × 1 L (1,000 L)", the total price and a one-line trade-off.
Also show a question row where the agent asks the buyer: "This is 10× Café Kallio's usual order. Can you confirm 200 L?" with the buyer's answer below it.
Top: filter chips for All, Hotel, Café and School, and a live indicator dot. A floating "Jump to latest" pill.
```

## Prompt 3: Approvals (Mobile, 375 px)

```
Screen "Approvals" on a phone, for a procurement manager.
Header: "Waiting for you · 1".
One card per pending order:
- Buyer name and time ("Hotel Chain Oy / Helsinki Central · 2 min ago")
- Big total: "€1,010.00" with "€1,150.00 incl. VAT" below it in small text
- Line: "1,000 × 1 L Valio Eila lactose-free semi-skimmed milk drink (1,000 L)", "Arrives Mon 16 Nov", a small grey "stock unconfirmed" tag
- "Why it needs you": an amber box listing the reasons, e.g. "Line costs €1,010.00, over your €800.00 per-line limit."
- "Agent's reason": one quoted sentence in grey
- Two full-width buttons: Approve (teal, filled) and Reject (red outline)
Also design: the empty state ("Nothing is waiting. Your agent is within its limits."), the Reject confirmation bottom sheet ("Reject this order? The agent will be told and won't retry."), and a success toast ("Approved. The agent has been told.").
```

## Prompt 4: Audit log (Web)

```
Screen "Audit log": the plain-language decision trail, readable by a kitchen manager.
Top: a big "Verify log" button. Next to it, the result state: a green banner "Intact: all 57 entries are chained, none edited", or a red banner "Broken at entry 12: this entry was changed after it was written".
Main: a timeline grouped by order ("Order ord_6a9e0a41 · Hotel Chain Oy · €1,010.00 · Approved"). Each entry has: seq number, time, actor chip (valio-buyer-agent, policy, procurement.manager@hotel.example), action (request_quote, decision:pending_approval, approval:approved) and the reason sentence, e.g. "Quoted 1,000 × Valio Eila milk drink 1 l lactose free for €1,010.00. Valid for 15 minutes."
Each row ends with a short hash ("a3f9…c21e") that expands to show prev_hash and hash in monospace.
Filters: buyer, order id, action type.
```

## Prompt 5: Buy manually (Web)

```
Screen "Buy manually": a person places an order by hand, without the AI, as one of three buyers. A four-step horizontal stepper: Search → Choose → Quote → Order.
Step 1 Search: a text field ("milk"), a category dropdown ("10400 · Milk and sour milk") and tag chips ("Lactose-free", "Vegan", "Gluten-free"). Results as a table: product id, name, category, sales unit, tags.
Step 2 Choose: a product detail panel. Allergens in three groups: "Contains" (red chips: Milk), "May contain" and "Free from" (green chips). If allergen info is missing, an amber warning: "Allergen information not provided. Unknown is not safe."
Step 3 Quote: lines with amount and unit (L or KG) and a need-by date picker. The quote result table shows: units × sales unit (litres covered), price per unit, line total, arrival date, stock confirmed/unconfirmed, and a red "cut-off passed" tag when relevant. A 15-minute expiry countdown and a "Signed quote" badge.
Step 4 Order: a "Place order" button, and four result states using the status colours. Needs clarification shows the server's question and a "Yes, confirm the amount" button. Pending approval shows "Waiting for procurement.manager@hotel.example" with a live spinner.
```

## Prompt 6: Mandates (Web)

```
Screen "Mandates": what each buyer's AI agent may do on its own, as signed rules. One card per buyer (Hotel Chain Oy / Helsinki Central, Café Kallio, Espoo School Kitchens).
Each card has a "Signed · Ed25519 · valid until 31 Dec 2026" badge and the rules in plain words with icons:
Hotel: orders alone up to €1,500 per order and €800 per line · only Milk and sour milk · substitutes allowed if still lactose-free and at most 10% more per litre · no blocked allergens · allergen info unknown → ask a person · approver procurement.manager@hotel.example
Café: up to €500 per order and €400 per line · only Milk and sour milk · substitutes allowed, at most 15% more per litre · allergen info unknown → ask a person · approver owner@cafe.example
School kitchen: up to €800 per order and €500 per line · any category · no substitutes · blocked allergens: peanuts, tree nuts, eggs (shown as red chips) · allergen info unknown → ask a person · approver kitchen.lead@school.example
A footer note: "These rules are enforced by the server's code, not by the AI. The agent cannot change them."
```
