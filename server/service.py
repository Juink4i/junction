"""What the six tools and the approval endpoints do. Plain code, no AI."""

import dataclasses
import functools
import json
import math
import secrets
import sqlite3
import threading
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Callable

import jwt

from server import audit, ranking, signing, vocabulary
from server.agent_auth import AgentTokenError, check_session_token
from server.db import transaction
from server.mandate import BUYER_ID, MandateError, check_mandate, verify_mandate
from server.seller import KeywordSeller, Need, keyword_verdict
from server.policy import decide, eur, hard_stops, period_start
from server.unusual import MODEL, THRESHOLD, flag_reason
from server.vocabulary import UNIT_WORDS, unit_code

QUOTE_TTL = timedelta(minutes=15)
CANDIDATE_LIMIT = 100  # the most products one search hands to the seller
MAX_QUOTE_PRODUCTS = 40  # the most products one quote request prices
MAX_OPTIONS = 5
MAX_ALTERNATIVES = 3
WITHDRAWN = "Withdrawn: the buyer's agent ordered another option from the same request."
SUMMARY_FIELDS = ("id", "name_en", "name_fi", "category", "sales_unit", "tags", "labels")
PRODUCT_FIELDS = SUMMARY_FIELDS + (
    "allergens_contains", "allergens_may_contain", "allergens_free_from", "allergen_info_missing",
    "vendor", "country", "description", "carbon_kg_per_kg", "delivery_reliability",
    "official_substitutes",
)


def error(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable}


def _unknown_unit_question(unit: Any) -> str:
    return (f'The server cannot measure in "{unit}". Ask the buyer how much they need in litres '
            '(L), kilograms (KG) or pieces (PCS). Do not convert the number yourself.')


def _pick(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """Only the contract's fields, so nothing extra from the catalog reaches the agent."""
    if dataclasses.is_dataclass(obj):
        obj = dataclasses.asdict(obj)
    elif hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    picked = {f: obj[f] for f in fields}
    picked["properties"] = vocabulary.names(picked["tags"])  # the tags in plain words
    return picked


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def locked(method):
    """Tools run on worker threads but share one SQLite connection, so one call at a time."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclasses.dataclass(frozen=True)
class Buyer:
    """Who a tool call is from: the buyer behind the mandate the connection showed."""
    buyer_id: str
    mandate: dict

    @property
    def actor(self) -> str:
        return str(self.mandate["agent_id"])

    @property
    def name(self) -> str:
        return str(self.mandate["buyer"])

    @property
    def caller(self) -> dict:
        """Who is asking, for the checks that keep each kitchen to its own records."""
        return {"buyer_id": self.buyer_id, "agent_id": self.actor,
                "mandate_id": str(self.mandate["mandate_id"])}


class Service:
    def __init__(self, conn: sqlite3.Connection, catalog: Any, now: Callable[[], datetime],
                 unusual_scorer: Any = None, require_enrolment_code: bool = False,
                 seller: Any = None):
        self.conn = conn
        self.unusual_scorer = unusual_scorer
        self.require_enrolment_code = require_enrolment_code
        self.seller = seller or KeywordSeller()
        self.catalog = catalog
        self.now = now
        self.key = signing.server_key(conn)
        self._lock = threading.RLock()
        # buyer id -> (amount, unit) of the last request the server could not measure.
        self._unit_asked: dict[str, tuple[float, str]] = {}

    def _log(self, actor: str, action: str, reason: str, order_id: str | None = None,
             quote_id: str | None = None) -> None:
        audit.append(self.conn, self.now(), actor, action, reason, order_id, quote_id)

    @locked
    def authenticate(self, token: str | None) -> Buyer:
        """The buyer behind a mandate token. Raises MandateError; every refusal is logged."""
        try:
            if not token:
                raise MandateError("No mandate was shown. Connect with the kitchen's signed mandate "
                                   "in X-Mandate.", code="mandate_missing")
            buyer_id, mandate = verify_mandate(token, self.conn, self.now().date())
        except MandateError as e:
            self._log("unknown agent", "connect:refused", f"A connection was refused. {e}")
            raise
        return Buyer(buyer_id, mandate)

    # Buyers

    @locked
    def register_buyer(self, public_pem: Any, mandate_token: Any,
                       enrolment_code: Any = None) -> tuple[int, dict]:
        """A kitchen registers its signing key and its signed mandate. Returns (HTTP status, body).

        Plain HTTP only, never an MCP tool: an agent must not be able to register a mandate.
        With require_enrolment_code, the registration must carry the code Valio Aimo shows that
        customer, which ties the key to a customer Valio Aimo already knows.
        """
        if not (isinstance(public_pem, str) and public_pem
                and isinstance(mandate_token, str) and mandate_token):
            return 400, error("bad_request", "Send public_pem and mandate_token as text.")
        customer = None
        if self.require_enrolment_code:
            customer = self.conn.execute(
                "SELECT customer_no, name FROM customers WHERE enrolment_code = ?",
                (enrolment_code if isinstance(enrolment_code, str) else "",)).fetchone()
            if customer is None:
                self._log("unknown", "register_buyer:refused",
                          "Someone tried to register a buyer without a valid Valio Aimo enrolment code.")
                return 403, error("enrolment_code_invalid", "This enrolment code is not known to "
                                  "Valio Aimo. Find yours in your Valio Aimo webshop account.")
        try:
            buyer_id = jwt.get_unverified_header(mandate_token).get("kid")
        except jwt.InvalidTokenError:
            buyer_id = None
        if not (isinstance(buyer_id, str) and BUYER_ID.fullmatch(buyer_id)):
            return 400, error("mandate_invalid", "The mandate token must carry a buyer id of 3 to 64 "
                              "lowercase letters, digits or hyphens.")
        if self.conn.execute("SELECT 1 FROM buyers WHERE buyer_id = ?", (buyer_id,)).fetchone():
            self._log("unknown", "register_buyer:refused",
                      f"Someone tried to register buyer id {buyer_id}, which is already registered.")
            return 409, error("buyer_exists", f"A buyer with id {buyer_id} is already registered.")
        if not signing.is_ed25519_public(public_pem):
            return 400, error("bad_key", "public_pem is not an Ed25519 public key.")
        now = self.now()
        try:
            mandate = check_mandate(mandate_token, signing.load_public(public_pem), now.date())
        except MandateError as e:
            return 400, error("mandate_invalid", str(e))

        usual = mandate.get("usual_orders", [])
        name = customer["name"] if customer else mandate["buyer"]
        with transaction(self.conn):
            self.conn.execute("INSERT INTO buyers (buyer_id, name, public_pem) VALUES (?, ?, ?)",
                              (buyer_id, name, public_pem))
            self.conn.executemany(
                "INSERT INTO order_history (buyer_id, category, amount, content_unit, ordered_on) "
                "VALUES (?, ?, ?, ?, ?)",
                [(buyer_id, o["category"], o["amount"], o["content_unit"], now.date().isoformat())
                 for o in usual])
        declared = "; ".join(f"{o['amount']:g} {o['content_unit']} of category {o['category']} "
                             f"each {o['every']}" for o in usual)
        known_as = (f" Its enrolment code ties it to Valio Aimo customer {customer['customer_no']} "
                    f"({customer['name']})." if customer else "")
        self._log(mandate["buyer"], "register_buyer",
                  f"{mandate['buyer']} registered its signing key and mandate "
                  f"{mandate['mandate_id']} as buyer {buyer_id}. "
                  + (f"Declared usual orders: {declared}." if declared else "No usual orders declared.")
                  + known_as)
        body = {"buyer_id": buyer_id, "mandate_id": mandate["mandate_id"], "status": "registered"}
        if customer:
            body["customer_no"] = customer["customer_no"]
        return 201, body

    # Who is calling: only a registered kitchen's agent may use the MCP endpoint.

    @locked
    def authenticate_agent(self, mandate_token: Any, agent_token: Any) -> dict:
        """{buyer_id, agent_id, mandate_id} for a valid mandate plus agent session token, else an
        error {code, message, retryable}. Every refusal is logged; no token is ever written."""
        def refuse(code: str, message: str, reason: str) -> dict:
            self._log("unknown agent", "connect:refused", reason)
            return error(code, message)

        if not (isinstance(mandate_token, str) and mandate_token
                and isinstance(agent_token, str) and agent_token):
            return refuse("agent_not_authenticated",
                          "Send the kitchen's signed mandate in X-Mandate and the agent's session "
                          "token in Authorization: Bearer.",
                          "An agent tried to connect without a mandate and an agent token.")
        now = self.now()
        try:
            buyer_id, mandate = verify_mandate(mandate_token, self.conn, now.date())
        except MandateError as e:
            return refuse("mandate_not_accepted", f"The mandate was not accepted. {e}",
                          f"An agent tried to connect with a mandate that was not accepted: {e}")
        if not signing.is_ed25519_public(mandate.get("agent_key")):
            return refuse("agent_key_missing",
                          "This mandate names no agent key, so no agent may act for this kitchen. "
                          "The kitchen must sign a mandate that names its agent's key.",
                          f"An agent tried to connect for {mandate['buyer']}, whose mandate "
                          f"{mandate['mandate_id']} names no agent key.")
        try:
            check_session_token(agent_token, mandate, now)
        except AgentTokenError as e:
            return refuse("agent_token_invalid", f"The agent's session token is not valid: {e}.",
                          f"An agent tried to connect for {mandate['buyer']} with mandate "
                          f"{mandate['mandate_id']}, but {e}.")
        return {"buyer_id": buyer_id, "agent_id": str(mandate["agent_id"]),
                "mandate_id": str(mandate["mandate_id"])}

    # Search and details: static data only.

    def _ask(self, buyer: Buyer, action: str, question: str, missing: list[str] | None = None,
             unknown: list[str] | None = None) -> dict:
        """The seller's side asks for what a request lacks. Plain code, no AI."""
        with self._lock:
            self._log(buyer.actor, action, f"Asked the agent: {question}")
        return {"status": "needs_clarification", "missing": missing or [], "unknown": unknown or [],
                "known_properties": vocabulary.known_names(), "question": question}

    def search_products(self, buyer: Buyer, product: str | None, must_have: list[str] | None = None,
                        amount: float | None = None, unit: str | None = None) -> dict:
        """The products that fit a request, and what was dropped and why.

        Not @locked as a whole: the seller agent can take seconds, and the approval and log
        pages must not wait for it. Only the log write takes the lock.
        """
        understood = vocabulary.understand(product or "", must_have)
        if understood.unknown:
            words = ", ".join(f'"{w}"' for w in understood.unknown)
            return self._ask(buyer, "search_products", unknown=understood.unknown,
                             question=f"I don't know the product property {words}. Use one of the "
                                      "known properties, or leave it out.")
        if not understood.text:
            return self._ask(buyer, "search_products", missing=["product"],
                             question='What product do you need? Give it in plain words, '
                                      'for example "milk".')
        if unit is not None and unit_code(unit) is None:
            return self._ask(buyer, "search_products", missing=["unit"],
                             question=_unknown_unit_question(unit))
        unit = unit_code(unit)

        # The mandate's own must-haves and categories always apply. Plain code, before any AI.
        from_mandate = list(buyer.mandate.get("substitution", {}).get("must_keep", []))
        tags = list(dict.fromkeys(understood.tags + from_mandate))
        allowed = buyer.mandate["auto_approve"].get("allowed_categories")
        found = []
        for category in allowed if allowed is not None else [None]:
            found += self.catalog.search_products(understood.text, category, tags, CANDIDATE_LIMIT + 1)
        truncated = len(found) > CANDIDATE_LIMIT
        candidates = found[:CANDIDATE_LIMIT]

        need = Need(" ".join(str(product).split()), tuple(vocabulary.names(tags)), amount, unit)
        try:
            screening = self.seller.screen(need, candidates)
        except Exception:  # a search never fails because of the seller
            screening = KeywordSeller().screen(need, candidates)
        kept, dropped = [], []
        for p in candidates:  # only candidates are looked at, so the seller cannot add a product
            verdict = screening.verdicts.get(p.id) or keyword_verdict(need, p)
            if verdict.keep:
                kept.append(_pick(p, SUMMARY_FIELDS))
            else:
                dropped.append({"id": p.id, "name": p.name_en, "reason": verdict.reason})

        must = f", must be {', '.join(need.must_have)}" if need.must_have else ""
        why = Counter(d["reason"] for d in dropped).most_common(4)
        dropped_text = (" Dropped: " + ", ".join(f"{reason} ({n})" for reason, n in why) + "."
                        if dropped else "")
        with self._lock:
            self._log(buyer.actor, "search_products",
                      f'Searched for "{understood.text}"{must}. {len(candidates)} candidates; '
                      f"{screening.screened_by} kept {len(kept)} and dropped {len(dropped)}."
                      f"{dropped_text}")

        result = {
            "status": "ok",
            "understood": {"product": understood.text, "must_have": vocabulary.names(understood.tags),
                           "from_mandate": vocabulary.names(from_mandate)},
            "products": kept,
            "dropped": dropped,
            "screened_by": screening.screened_by,
            "total_matches": len(candidates),
            "truncated": truncated,
        }
        if truncated:
            result["hint"] = (f"More than {CANDIDATE_LIMIT} products match. Add a must-have or "
                              "more specific words.")
        elif not candidates:
            result["hint"] = (f'Nothing matches "{understood.text}"{must}. Try fewer or different '
                              "words. A product only counts as having a property when its "
                              "supplier claims it.")
        return result

    @locked
    def get_product(self, product_id: str, actor: str = "agent") -> dict:
        product = self.catalog.get_product(product_id)
        if product is None:
            self._log(actor, "get_product", f"Asked for product {product_id}, which does not exist.")
            return error("product_not_found", f"No product with id {product_id}.")
        self._log(actor, "get_product", f"Read the details of {product.name_en} ({product_id}).")
        return _pick(product, PRODUCT_FIELDS)

    # Quotes

    @locked
    def quote_lines(self, lines: list[dict], need_by: date | str, actor: str = "agent") -> dict:
        """One signed quote for exactly these lines. The low-level builder; not a tool."""
        result = self._build_quote(lines, need_by)
        if "quote_id" in result:
            summary = "; ".join(f"{l['units']:,} × {l['name']} for {eur(l['line_total_eur'])}"
                                for l in result["lines"])
            self._log(actor, "request_quote",
                      f"Quoted {summary}. Total {eur(result['total_eur'])} without VAT, valid for "
                      "15 minutes. The stock hold is simulated.", quote_id=result["quote_id"])
        else:
            self._log(actor, "request_quote", f"No quote given: {result['message']}")
        return result

    def _offers(self, product_ids: list[str], need_by: date) -> dict | dict[str, Any]:
        """The offers, or an error. The real catalog already retries once, so only the fake needs it."""
        attempts = 1 if hasattr(self.catalog, "allergen_status") else 2
        failure: Exception | None = None
        for _ in range(attempts):
            try:
                return self.catalog.price_and_availability(product_ids, need_by)
            except Exception as e:
                failure = e
        # The catalog's message can include upstream details, so it never reaches the agent.
        retryable = getattr(failure, "retryable", True)
        message = ("Valio Aimo's price and availability service did not answer. Try again shortly."
                   if retryable else
                   "Valio Aimo's price and availability service cannot be reached from this server. "
                   "Retrying will not help; the operator must fix the setup.")
        return error("valio_api_unavailable", message, retryable=retryable)

    def _substitute_hint(self, product: Any, need_by: date) -> str:
        try:
            offers = self.catalog.substitute_candidates(product.id, list(product.tags), 25, need_by)
        except Exception:
            return ""
        options = []
        for offer in offers[:3]:
            substitute = self.catalog.get_product(offer.product_id)
            if substitute is None:
                continue
            price = (f"{eur(offer.comparison_price_eur)} per {offer.comparison_unit}"
                     if offer.comparison_price_eur is not None else
                     f"{eur(offer.unit_price_eur)} per sales unit")
            options.append(f"{offer.product_id} {substitute.name_en} ({price})")
        if not options:
            return " No substitute with the same tags can arrive on time."
        return " Substitutes with the same tags that can arrive on time: " + "; ".join(options) + "."

    def _build_quote(self, lines: list[dict], need_by: date | str) -> dict:
        now = self.now()
        try:
            need_by = need_by if isinstance(need_by, date) else date.fromisoformat(need_by)
        except ValueError:
            return error("bad_date", "need_by must be a date like 2026-11-16.")
        if need_by < now.date():
            return error("need_by_in_past", f"The need-by date {need_by.isoformat()} is in the past.")
        if not lines:
            return error("no_lines", "A quote needs at least one line.")

        plans = []
        for line in lines:
            product = self.catalog.get_product(line["product_id"])
            if product is None:
                return error("product_not_found", f"No product with id {line['product_id']}.")
            if not (line["amount"] > 0 and math.isfinite(line["amount"])):
                return error("bad_amount", f"The amount for {product.name_en} must be a number above zero.")
            try:
                plans.append((product, self.catalog.units_needed(product.id, line["amount"], line["unit"])))
            except Exception:
                return error("bad_unit", f"{product.name_en} cannot be measured in {line['unit']}. "
                             "Use L, KG or PCS, whichever it is sold in.")

        offers = self._offers([product.id for product, _ in plans], need_by)
        if "code" in offers and "retryable" in offers:
            return offers

        quoted = []
        for product, plan in plans:
            offer = offers.get(product.id)
            if offer is None or not offer.orderable:
                return error("not_orderable", f"{product.name_en} ({product.id}) cannot be ordered "
                             f"for {need_by.isoformat()}.")
            if offer.available_units is not None and offer.available_units < plan.units:
                in_stock = offer.available_units * plan.content_per_unit
                return error(
                    "insufficient_stock",
                    f"Only {offer.available_units} sales units of {product.name_en} ({product.id}) "
                    f"are available, which covers {in_stock:g} {plan.content_unit} of the "
                    f"{plan.covers:g} {plan.content_unit} asked for. Quote what is available and "
                    "cover the rest with a substitute." + self._substitute_hint(product, need_by),
                )
            quoted.append(ranking.Line(self._candidate(product, plan, offer), plan.units))
        return self._issue_quote(quoted, need_by, now)

    def _candidate(self, product: Any, plan: Any, offer: Any) -> ranking.Candidate:
        """One product sized and priced, in the shape the ranking and the quote both use."""
        return ranking.Candidate(
            product_id=product.id, name=product.name_en, sales_unit=plan.sales_unit,
            content_per_unit=plan.content_per_unit, content_unit=plan.content_unit, units=plan.units,
            unit_price_eur=offer.unit_price_eur,
            unit_price_with_tax_eur=offer.unit_price_with_tax_eur,
            available_date=offer.available_date, closing_time=offer.closing_time,
            cutoff_passed=bool(offer.cutoff_passed), available_units=offer.available_units,
            reliability=product.delivery_reliability, country=product.country,
            labels=tuple(product.labels), carbon=product.carbon_kg_per_kg)

    def _issue_quote(self, lines: list[ranking.Line], need_by: date, now: datetime,
                     buyer_id: str | None = None, set_id: str | None = None,
                     rank: int | None = None, label: str | None = None) -> dict:
        """Sign and store one quote for these lines."""
        quote_lines, total_with_tax = [], 0.0
        for line in lines:
            c = line.candidate
            quote_lines.append({
                "product_id": c.product_id,
                "name": c.name,
                "units": line.units,
                "sales_unit": c.sales_unit,
                "covers": line.covers,
                "content_unit": c.content_unit,
                "unit_price_eur": c.unit_price_eur,
                "line_total_eur": line.total_eur,
                "available_date": c.available_date.isoformat() if c.available_date else None,
                "cutoff_passed": c.cutoff_passed,
                "closing_time": c.closing_time.isoformat(timespec="seconds") if c.closing_time else None,
                "stock": "confirmed" if c.available_units is not None else "unconfirmed",
            })
            total_with_tax += line.units * c.unit_price_with_tax_eur
        body = {
            "quote_id": _new_id("q"),
            "lines": quote_lines,
            "total_eur": round(sum(l["line_total_eur"] for l in quote_lines), 2),
            "total_with_tax_eur": round(total_with_tax, 2),
            "expires_at": (now + QUOTE_TTL).isoformat(),
        }
        signature = signing.sign_quote(body, need_by, self.key)
        self.conn.execute(
            "INSERT INTO quotes (quote_id, body_json, signature, created_at, buyer_id, set_id, rank, "
            "label) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (body["quote_id"], json.dumps(body), signature, now.isoformat(), buyer_id, set_id, rank,
             label),
        )
        return {**body, "signature": signature}

    def _forecast(self, quote: dict, need_by: date, buyer: Buyer, products: dict,
                  history: list[dict], now: datetime, set_id: str | None = None):
        """What Policy would decide for this quote now. Nothing is saved, and the Decisions
        API is not asked. The decision at order time is the one that counts."""
        return decide({**quote, "need_by": need_by.isoformat()}, buyer.mandate, products, history,
                      None, self._spent_in_period(buyer.buyer_id, buyer.mandate, now, quote["quote_id"],
                                                         set_id), now)

    @locked
    def request_quote(self, buyer: Buyer, product_ids: list[str] | None, amount: float | None,
                      unit: str | None, need_by: date | str | None,
                      preferences: dict | None = None) -> dict:
        """Ranked options for one need. Each option is its own signed quote."""
        missing = [name for name, value in (("product_ids", product_ids), ("amount", amount),
                                            ("unit", unit), ("need_by", need_by)) if not value]
        if missing:
            return self._ask(buyer, "request_quote", missing=missing,
                             question="To price this I need: " + ", ".join(missing) + ". Give "
                                      "product_ids from search_products, the amount and unit "
                                      '("L", "KG" or "PCS"), and need_by as a date like 2026-11-16.')

        def refuse(problem: dict) -> dict:
            self._log(buyer.actor, "request_quote", f"No quote given: {problem['message']}")
            return problem

        now = self.now()
        try:
            need_by = need_by if isinstance(need_by, date) else date.fromisoformat(str(need_by))
        except ValueError:
            return refuse(error("bad_date", "need_by must be a date like 2026-11-16."))
        if need_by < now.date():
            return refuse(error("need_by_in_past",
                                f"The need-by date {need_by.isoformat()} is in the past."))
        if unit_code(unit) is None:
            return self._ask(buyer, "request_quote", missing=["unit"],
                             question=_unknown_unit_question(unit))
        unit = unit_code(unit)
        if not (isinstance(amount, (int, float)) and not isinstance(amount, bool)
                and amount > 0 and math.isfinite(amount)):
            return refuse(error("bad_amount", "The amount must be a number above zero."))
        # An agent that cannot get a quote in one unit may re-send the same number in another,
        # turning 200 eggs into 200 kg. The first time, the buyer is asked instead.
        before = self._unit_asked.pop(buyer.buyer_id, None)
        if before and before[0] == amount and before[1] != unit:
            return self._ask(buyer, "request_quote", missing=["unit"], question=(
                f"Earlier the request was {amount:g} {before[1]}. {amount:g} {unit} is a different "
                f"amount. Ask the buyer how many {UNIT_WORDS[unit]} they need. Do not convert the "
                "number yourself."))

        ids = list(dict.fromkeys(str(i) for i in product_ids))[:MAX_QUOTE_PRODUCTS]
        not_offered: list[dict] = []
        products: dict[str, Any] = {}
        for pid in ids:
            product = self.catalog.get_product(pid)
            if product is None:
                not_offered.append({"product_id": pid, "name": None,
                                    "reason": "Not in the Valio Aimo catalog."})
                continue
            # A product the mandate would reject outright is never offered.
            stops = hard_stops({"lines": [{"product_id": pid, "name": product.name_en}]},
                               buyer.mandate, {pid: product})
            if stops:
                not_offered.append({"product_id": pid, "name": product.name_en,
                                    "reason": " ".join(stops)})
                continue
            products[pid] = product

        # One price call and one availability call, before the unit maths, which reuses them.
        offers = self._offers(list(products), need_by) if products else {}
        if "code" in offers and "retryable" in offers:
            return refuse(offers)

        candidates, measured_in = [], set()
        for pid, product in products.items():
            offer = offers.get(pid)
            if offer is None or not offer.orderable:
                not_offered.append({"product_id": pid, "name": product.name_en,
                                    "reason": f"Cannot be ordered for {need_by.isoformat()}."})
                continue
            try:
                plan = self.catalog.units_needed(pid, amount, unit)
            except Exception:
                other = self._measured_in(pid, amount, unit)
                measured_in |= other
                sold_in = (" It is sold in " + " or ".join(UNIT_WORDS[u] for u in sorted(other)) + "."
                           if other else "")
                not_offered.append({"product_id": pid, "name": product.name_en,
                                    "reason": f"It cannot be measured in {UNIT_WORDS[unit]}.{sold_in}"})
                continue
            candidates.append(self._candidate(product, plan, offer))
        if not candidates and measured_in:
            self._unit_asked[buyer.buyer_id] = (amount, unit)
            words = " or ".join(UNIT_WORDS[u] for u in sorted(measured_in))
            return self._ask(buyer, "request_quote", missing=["unit"], question=(
                f"None of these products can be measured in {UNIT_WORDS[unit]}. They are sold in "
                f"{words}. Ask the buyer how much they need in {words}. Do not convert "
                f"{amount:g} {unit} yourself."))

        prefs = preferences or {}
        ranked = ranking.rank(candidates, need_by, prefs.get("priorities"), prefs.get("pack_size"))
        plans = ranking.options(ranked, amount, need_by, MAX_OPTIONS)
        offered = {line.candidate.product_id for plan in plans for line in plan.lines}
        for c in ranked:
            if c.short and c.product_id not in offered:
                in_stock = c.available_units * c.content_per_unit
                not_offered.append({"product_id": c.product_id, "name": c.name,
                                    "reason": f"Only {in_stock:g} {c.content_unit} is in stock, less "
                                              f"than the {amount:g} {unit} asked for."})

        set_id = _new_id("qs")
        history = self._history(buyer.buyer_id)
        options = []
        for rank_no, plan in enumerate(plans, 1):
            quote = self._issue_quote(list(plan.lines), need_by, now, buyer.buyer_id, set_id,
                                      rank_no, plan.label)
            decision = self._forecast(quote, need_by, buyer, products, history, now)
            options.append({"rank": rank_no, "label": plan.label, "trade_off": plan.trade_off,
                            "expected": {"status": decision.status, "reasons": decision.reasons},
                            "quote": quote})
            self._log(buyer.actor, "request_quote",
                      f"Option {rank_no} of {len(plans)} ({plan.label}) for {buyer.name}: "
                      f"{plan.trade_off} Total {eur(quote['total_eur'])} without VAT, valid for "
                      "15 minutes. The stock hold is simulated.", quote_id=quote["quote_id"])
        if not options:
            self._log(buyer.actor, "request_quote",
                      f"Nothing could be offered for {amount:g} {unit} by {need_by.isoformat()}: "
                      f"{len(not_offered)} products were left out.")
        return {"status": "ok", "set_id": set_id,
                "asked": {"amount": amount, "unit": unit, "need_by": need_by.isoformat()},
                "options": options, "not_offered": not_offered}

    def _measured_in(self, product_id: str, amount: float, unit: str) -> set[str]:
        """The other units this product can be measured in. Prices are cached by now."""
        found = set()
        for other in UNIT_WORDS:
            if other == unit:
                continue
            try:
                self.catalog.units_needed(product_id, amount, other)
                found.add(other)
            except Exception:
                pass
        return found

    # Orders

    @locked
    def place_order(self, quote_id: str, mandate_token: str, rationale: str,
                    agent_signature: str | None = None) -> dict:
        return self._place_order(quote_id, mandate_token, rationale, agent_signature)

    def _refuse(self, quote_id: str, reason: str) -> dict:
        """A refusal that is not tied to an order, so it cannot use up someone's quote."""
        known = self.conn.execute("SELECT 1 FROM quotes WHERE quote_id = ?", (quote_id,)).fetchone()
        self._log("policy", "decision:rejected", reason, quote_id=quote_id if known else None)
        return {"status": "rejected", "reasons": [reason]}

    def _order_result(self, order: sqlite3.Row) -> dict:
        result = {"status": order["status"], "order_id": order["order_id"]}
        if order["approval_id"]:
            result["approval_id"] = order["approval_id"]
        result["reasons"] = json.loads(order["reasons_json"])
        if order["alternatives_json"] and order["status"] != "confirmed":
            result["alternatives"] = json.loads(order["alternatives_json"])
        return result

    def _order(self, **where: str) -> sqlite3.Row | None:
        (column, value), = where.items()
        return self.conn.execute(f"SELECT * FROM orders WHERE {column} = ?", (value,)).fetchone()

    def _history(self, buyer_id: str) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            "SELECT category, amount, content_unit FROM order_history WHERE buyer_id = ?", (buyer_id,))]

    def _live_siblings(self, set_id: str, quote_id: str) -> list[sqlite3.Row]:
        """Orders from the same request, other than this quote's, that are confirmed or waiting."""
        return self.conn.execute(
            "SELECT o.* FROM orders o JOIN quotes q USING (quote_id) WHERE q.set_id = ? "
            "AND o.quote_id != ? AND o.status IN ('confirmed', 'pending_approval')",
            (set_id, quote_id)).fetchall()

    def _withdraw(self, order: sqlite3.Row, actor: str, now: datetime) -> None:
        """Marks a waiting order rejected and closes its approval; it never commits or logs."""
        reasons = json.loads(order["reasons_json"]) + [WITHDRAWN]
        self.conn.execute(
            "UPDATE orders SET status = 'rejected', reasons_json = ?, alternatives_json = NULL "
            "WHERE order_id = ?", (json.dumps(reasons), order["order_id"]))
        self.conn.execute(
            "UPDATE approvals SET status = 'rejected', decided_by = ?, decided_at = ? "
            "WHERE order_id = ? AND status = 'pending'",
            (actor, now.isoformat(), order["order_id"]))

    def _alternatives(self, set_id: str, quote_id: str, buyer: Buyer, history: list[dict],
                      now: datetime) -> list[dict]:
        """Other options from the same request that Policy would confirm on their own, best first.

        Orders from this request are not counted against their budget: they would replace them.
        """
        found = []
        rows = self.conn.execute(
            "SELECT * FROM quotes WHERE set_id = ? AND quote_id != ? ORDER BY rank",
            (set_id, quote_id)).fetchall()
        for row in rows:
            quote = {**json.loads(row["body_json"]), "signature": row["signature"]}
            try:
                need_by = signing.check_quote(quote, self.key.public_key(), now)
            except signing.QuoteError:
                continue  # expired, or changed after it was issued
            if self._order(quote_id=row["quote_id"]) is not None:
                continue  # already ordered
            products = {l["product_id"]: self.catalog.get_product(l["product_id"])
                        for l in quote["lines"]}
            products = {pid: p for pid, p in products.items() if p is not None}
            if self._forecast(quote, need_by, buyer, products, history, now, set_id).status != "confirmed":
                continue
            summary = " + ".join(f"{l['units']:,} × {l['sales_unit']} {l['name']} "
                                 f"({l['covers']:g} {l['content_unit']})" for l in quote["lines"])
            found.append({"quote_id": row["quote_id"], "rank": row["rank"], "label": row["label"],
                          "summary": summary, "total_eur": quote["total_eur"]})
            if len(found) == MAX_ALTERNATIVES:
                break
        return found

    def _place_order(self, quote_id: str, mandate_token: str, rationale: str,
                     agent_signature: str | None = None) -> dict:
        now = self.now()
        try:
            buyer_id, mandate = verify_mandate(mandate_token, self.conn, now.date())
        except MandateError as e:
            self._log("unknown agent", "place_order", f"Asked to order quote {quote_id} without a "
                      "valid mandate.")
            return self._refuse(quote_id, f"The mandate was not accepted. {e}")
        actor = str(mandate["agent_id"])
        signed_by_agent = "agent_key" in mandate
        if signed_by_agent:
            problem = signing.order_signature_problem(agent_signature, mandate, quote_id)
            if problem:
                self._log("unknown agent", "place_order",
                          f"Asked to order quote {quote_id} for {mandate['buyer']} with a copy of its "
                          "mandate, but without a valid signature from its agent.")
                return self._refuse(quote_id, problem)
        quote_row = self.conn.execute("SELECT * FROM quotes WHERE quote_id = ?", (quote_id,)).fetchone()
        self._log(actor, "place_order",
                  f"Asked to order quote {quote_id} for {mandate['buyer']}. "
                  f"{'The order is signed by the agent key named in the mandate. ' if signed_by_agent else ''}"
                  f"The agent's reason: \"{rationale[:500]}\"",
                  quote_id=quote_id if quote_row else None)

        existing = self._order(quote_id=quote_id)
        if existing is not None:
            if existing["buyer_id"] != buyer_id:
                return self._refuse(quote_id, "This quote has already been used by another buyer.")
            return self._order_result(existing)

        if quote_row is None:
            return self._refuse(quote_id, f"There is no quote with id {quote_id}. Request a new quote.")
        if quote_row["buyer_id"] and quote_row["buyer_id"] != buyer_id:
            return self._refuse(quote_id, "This quote was issued to another buyer.")
        quote = {**json.loads(quote_row["body_json"]), "signature": quote_row["signature"]}
        try:
            need_by = signing.check_quote(quote, self.key.public_key(), now)
        except signing.QuoteError as e:
            return self._refuse(quote_id, str(e))
        set_id = quote_row["set_id"]
        waiting: list[sqlite3.Row] = []
        if set_id:
            siblings = self._live_siblings(set_id, quote_id)
            for order in siblings:
                if order["status"] == "confirmed":
                    return self._refuse(quote_id, f"This request was already ordered as "
                                                  f"{order['order_id']}. Request a new quote to order again.")
            waiting = siblings

        products = {l["product_id"]: self.catalog.get_product(l["product_id"]) for l in quote["lines"]}
        products = {pid: p for pid, p in products.items() if p is not None}
        history = self._history(buyer_id)
        ai_unusual = self._ai_unusual(mandate["buyer"], history, quote, products, quote_id)
        decision = decide({**quote, "need_by": need_by.isoformat()}, mandate, products, history,
                          ai_unusual, self._spent_in_period(buyer_id, mandate, now, quote_id, set_id), now)
        alternatives = []
        if decision.status != "confirmed" and set_id:
            alternatives = self._alternatives(set_id, quote_id, Buyer(buyer_id, mandate), history, now)

        order_id = _new_id("ord")
        approval_id = _new_id("apr") if decision.status == "pending_approval" else None
        withdrawn = waiting if decision.status != "rejected" else []
        with transaction(self.conn):
            for order in withdrawn:
                self._withdraw(order, actor, now)
            self.conn.execute(
                "INSERT INTO orders (order_id, quote_id, buyer_id, mandate_id, status, approval_id, "
                "reasons_json, rationale, created_at, alternatives_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, quote_id, buyer_id, mandate["mandate_id"], decision.status, approval_id,
                 json.dumps(decision.reasons), rationale, now.isoformat(),
                 json.dumps(alternatives) if alternatives else None),
            )
            if approval_id:
                self.conn.execute(
                    "INSERT INTO approvals (approval_id, order_id, status, approvers_json) "
                    "VALUES (?, ?, 'pending', ?)",
                    (approval_id, order_id, json.dumps(mandate.get("approvers", []))),
                )
        for order in withdrawn:
            self._log(actor, "order:withdrawn",
                      f"{WITHDRAWN} Order {order['order_id']} no longer waits for approval.",
                      order_id=order["order_id"], quote_id=order["quote_id"])
        self._log("policy", f"decision:{decision.status}", " ".join(decision.reasons),
                  order_id=order_id, quote_id=quote_id)
        if alternatives:
            self._log("policy", "alternatives",
                      "Alternatives from the same request that would go through without a person: "
                      + "; ".join(f"{a['summary']} for {eur(a['total_eur'])}" for a in alternatives) + ".",
                      order_id=order_id, quote_id=quote_id)
        return self._order_result(self._order(order_id=order_id))

    def _spent_in_period(self, buyer_id: str, mandate: dict, now: datetime, quote_id: str,
                         set_id: str | None = None) -> float:
        """What this buyer's other live orders in the current budget period add up to, in euros.

        Orders whose quote belongs to set_id are left out: the new order would replace them.
        """
        budget = mandate.get("budget")
        if not budget:
            return 0.0
        rows = self.conn.execute(
            "SELECT q.body_json FROM orders o JOIN quotes q USING (quote_id) "
            "WHERE o.buyer_id = ? AND o.quote_id != ? AND o.created_at >= ? "
            "AND o.status IN ('confirmed', 'pending_approval') "
            "AND (? IS NULL OR q.set_id IS NULL OR q.set_id != ?)",
            (buyer_id, quote_id, period_start(budget["period"], now).isoformat(), set_id, set_id))
        return round(sum(json.loads(row["body_json"])["total_eur"] for row in rows), 2)

    def _ai_unusual(self, buyer: str, history: list[dict], quote: dict, products: dict,
                    quote_id: str) -> str | None:
        if self.unusual_scorer is None or not history:
            return None
        lines = [{**l, "category": products[l["product_id"]].category}
                 for l in quote["lines"] if l["product_id"] in products]
        try:
            score = self.unusual_scorer.score(buyer, history, lines)
        except Exception:
            score = None
        if score is None:
            self._log(MODEL, "unusual_score", "No score from Google's Decisions API. The 5 times "
                      "rule still applies on its own.", quote_id=quote_id)
            return None
        verdict = "unusual, so a person is asked" if score >= THRESHOLD else "not unusual"
        self._log(MODEL, "unusual_score", f"Scored {score:.2f} that this amount is unusual for "
                  f"{buyer}: {verdict}. The 5 times rule also applies.", quote_id=quote_id)
        return flag_reason(score) if score >= THRESHOLD else None

    # Approvals

    @locked
    def get_approval_status(self, approval_id: str, actor: str = "agent",
                            caller: dict | None = None) -> dict:
        row = self.conn.execute(
            "SELECT a.*, o.buyer_id FROM approvals a JOIN orders o USING (order_id) "
            "WHERE a.approval_id = ?", (approval_id,)).fetchone()
        # Another kitchen's approval looks exactly like one that does not exist.
        if row is not None and caller and row["buyer_id"] != caller["buyer_id"]:
            row = None
        if row is None:
            self._log(actor, "get_approval_status", f"Asked about approval {approval_id}, which does not exist.")
            return error("approval_not_found", f"No approval with id {approval_id}.")
        self._log(actor, "get_approval_status", f"Checked approval {approval_id}: {row['status']}.")
        status = {"status": row["status"]}
        if row["decided_by"]:
            status.update(decided_by=row["decided_by"], decided_at=row["decided_at"])
        return status

    @locked
    def list_approvals(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT a.*, o.quote_id, o.reasons_json, o.rationale, o.created_at, b.name AS buyer, "
            "q.body_json FROM approvals a JOIN orders o USING (order_id) "
            "JOIN buyers b USING (buyer_id) JOIN quotes q USING (quote_id) "
            "WHERE a.status = 'pending' ORDER BY o.created_at"
        ).fetchall()
        approvals = []
        for row in rows:
            quote = json.loads(row["body_json"])
            approvals.append({
                "approval_id": row["approval_id"],
                "order_id": row["order_id"],
                "quote_id": row["quote_id"],
                "status": row["status"],
                "buyer": row["buyer"],
                "approvers": json.loads(row["approvers_json"]),
                "reasons": json.loads(row["reasons_json"]),
                "agent_rationale": row["rationale"],
                "lines": quote["lines"],
                "total_eur": quote["total_eur"],
                "total_with_tax_eur": quote["total_with_tax_eur"],
                "created_at": row["created_at"],
            })
        return approvals

    @locked
    def decide_approval(self, approval_id: str, approve: bool, decided_by: str | None = None) -> dict:
        if decided_by is not None and not isinstance(decided_by, str):
            return error("bad_request", "decided_by must be text.")
        row = self.conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        if row is None:
            self._log(decided_by or "approver", "approval:not_found",
                      f"Tried to decide approval {approval_id}, which does not exist.")
            return error("approval_not_found", f"No approval with id {approval_id}.")
        if row["status"] != "pending":
            return error("already_decided", f"This approval was already {row['status']} by {row['decided_by']}.")
        approvers = json.loads(row["approvers_json"])
        decided_by = decided_by or (approvers[0] if approvers else "approver")
        status = "approved" if approve else "rejected"
        now = self.now().isoformat()
        order = self._order(order_id=row["order_id"])
        reason = f"{'Approved' if approve else 'Rejected'} by {decided_by}."
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE approvals SET status = ?, decided_by = ?, decided_at = ? WHERE approval_id = ?",
                (status, decided_by, now, approval_id))
            self.conn.execute(
                "UPDATE orders SET status = ?, reasons_json = ? WHERE order_id = ?",
                ("confirmed" if approve else "rejected",
                 json.dumps(json.loads(order["reasons_json"]) + [reason]), order["order_id"]))
        self._log(decided_by, f"approval:{status}",
                  f"{reason} The order is now {'confirmed' if approve else 'rejected'}.",
                  order_id=order["order_id"], quote_id=order["quote_id"])
        return {"status": status, "decided_by": decided_by, "decided_at": now}

    # Log

    @locked
    def get_audit_log(self, order_id: str | None = None, quote_id: str | None = None,
                      actor: str = "agent", caller: dict | None = None) -> list[dict] | dict:
        if not order_id and not quote_id:
            self._log(actor, "get_audit_log", "Asked for the log without an order or quote id.")
            return error("missing_filter", "Give an order_id or a quote_id.")
        if caller:
            order_id, quote_id = self._own_ids(caller, order_id, quote_id)
        elif order_id:
            order = self._order(order_id=order_id)
            quote_id = quote_id or (order["quote_id"] if order else None)
        found = audit.entries(self.conn, order_id=order_id, quote_id=quote_id)             if order_id or quote_id else []
        self._log(actor, "get_audit_log", f"Read the log for {order_id or quote_id}: {len(found)} entries.")
        return found

    def _own_ids(self, caller: dict, order_id: str | None,
                 quote_id: str | None) -> tuple[str | None, str | None]:
        """The order and quote ids an agent may read the log for: only its own kitchen's.

        Anything else is dropped, so another kitchen's trail looks exactly like an unknown id.
        A quote that was never ordered is the agent's own if that agent requested it."""
        if order_id:
            order = self._order(order_id=order_id)
            if order is None or order["buyer_id"] != caller["buyer_id"]:
                return None, None
            return order_id, order["quote_id"]  # never another quote smuggled in beside it
        order = self._order(quote_id=quote_id)
        if order is not None:
            return (None, quote_id) if order["buyer_id"] == caller["buyer_id"] else (None, None)
        asked = self.conn.execute(
            "SELECT 1 FROM log WHERE quote_id = ? AND action = 'request_quote' AND actor = ?",
            (quote_id, caller["agent_id"])).fetchone()
        return (None, quote_id) if asked else (None, None)

    @locked
    def full_log(self) -> list[dict]:
        return audit.entries(self.conn)

    @locked
    def verify_log(self) -> dict:
        return audit.verify(self.conn)
