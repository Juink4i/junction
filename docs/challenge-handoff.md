# Handoff: Junction 2026 challenge selection (Valio Aimo focus)

## Context
- User is competing at **Junction 2026 "European Tech Renaissance"**, Hype Areena, Espoo, 13–15 Nov 2026. Teams are 1–4 people. The basics and deadlines are in memory: `~/.claude/projects/-Users-jove-fong-personal/memory/junction-2026-hackathon.md`.
  - Key deadlines (Helsinki time): preliminary submission **Fri 13 Nov 23:55**, final submission **Sun 15 Nov 10:00**.
- **Team:** mostly junior full-stack engineers, with some cybersecurity background.
- The challenge platform (`hackjunction.app/participate/45/challenges`) needs a login. Claude in Chrome hit a sign-in wall, and the extension later showed no connected browsers. **Ask the user to paste page content.** Don't try to log in.

## Where we are
- We compared five challenges: Valio Aimo, Exa, S-Pankki, Bahn Spread and Stoa.
- **Recommendation:** Valio Aimo "Trusted Trade Agents" first, Exa "Internet Butler" second. Bahn and Stoa are weak fits: an optimisation game, and computer vision on drawings.
- I explained the Valio Aimo problem at several levels of detail. The user asked for a simpler version, then for why "owning the customer" matters: platform lock-in, Booking.com / Wolt precedent, open standards = building your own front door.
- **The user has not confirmed the final pick and has not asked to start building yet.**

## Valio Aimo: brief summary (the user pasted the full text in chat; it isn't saved anywhere else)
- **The ask:** build the interface and operating model that lets an *external* AI purchasing agent use Valio Aimo's mock webshop/backend, on open standards. It is not a marketplace and not a chatbot.
- **Core requirements:**
  1. Structured product, price and availability lookup.
  2. Quote at a fixed price, then order.
  3. Permissions plus human approval.
- **Optional:** delivery and sustainability comparison, substitution/exception handling, a readable audit trail.
- **Insight problems:** trust protocol, guardrails model, good/better/best substitution logic, audit trail.
- **Scenarios:** allergen-safe substitution (school/hospital kitchen), last-minute event, mid-week stock-out, Valio Aimo's own proactive selling agent, detecting drift in standing orders.
- **Demo request:** "1,000 L lactose-free milk by Monday" → structured options → order within the agent's authority, or escalate to a human.
- **Judging:**
  - End-to-end demo: 30%
  - Matches the user need: 20%
  - Autonomy and controls: 20%
  - Exception robustness: 15%
  - Openness / path to production: 15%
- **Prizes:** €4k / €2k / €1k.
- **Resources:** a portal at `https://junction26.valioaimo.fi/` with datasets, API docs and mock backend access.
  - The portal password and API key are in the user's paste on the challenge page. **They're redacted here, so ask the user.** Keep them in `.env`, never in a public repo.
  - Webshop test accounts will be shared later.

## The angle we proposed (security as the edge)
- Scoped per-agent capability tokens: category, spend limit, whether substitution is allowed. Enforced server-side by a deterministic policy engine. "The LLM proposes, the policy decides."
- Signed quotes (JWS) with price, stock claim and expiry.
- Idempotency keys on orders.
- Aggregate spend limits, to block splitting one order to stay under the threshold.
- Hash-chained audit log with a plain-language reason for each entry.
- Data minimisation: no cost prices, other customers' prices or exact stock. Rate limiting against scraping.
- **Demo differentiator:** a prompt-injection string planted in a product description, shown being blocked.
- **Caution we gave:** the 30% demo criterion comes first, so keep the crypto light.
- **Questions for mentors on Friday night:**
  - Does a quote endpoint exist in the mock APIs?
  - Which fields count as confidential?
  - What real approval rules do customers use?
  - MCP or OpenAPI preference?

## Exa fallback idea
"Is this legit?" checker for international students and newcomers in Finland. It vets rental listings, job offers and landlords against live web sources, flags scams and cites every source.

## Likely next steps
1. Confirm the challenge choice with the user. Check the platform Guide for whether a team can enter several challenges.
2. Architecture sketch plus a task split across the team.
3. Read the Valio Aimo portal docs once the user shares the access details. Then scaffold the repo.

## Suggested skills
- `superpowers:brainstorming`: before designing the architecture or picking the build scope.
- `superpowers:writing-plans`: to turn the chosen design into a 48h task plan and team split.
- `claude-api`: if the purchasing agent is built on Claude (tool use / MCP).
- `excalidraw-diagram-generator` or `figma:figma-generate-diagram`: for the architecture or flow diagram for the pitch.
- `frontend-design`: for the approval dashboard / audit-log UI.
- `anthropic-skills:pptx`: only if the user wants the pitch deck as a .pptx. Otherwise use the Artifact quickstart for slides.
