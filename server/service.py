"""What the six tools and the approval endpoints do. Plain code, no AI."""

import dataclasses
import functools
import json
import math
import secrets
import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Any, Callable

import jwt

from server import audit, signing
from server.db import transaction
from server.mandate import BUYER_ID, MandateError, check_mandate, verify_mandate
from server.policy import decide, eur, period_start
from server.unusual import MODEL, REASON_PREFIX, THRESHOLD, flag_reason

QUOTE_TTL = timedelta(minutes=15)
SUMMARY_FIELDS = ("id", "name_en", "name_fi", "category", "sales_unit", "tags", "labels")
PRODUCT_FIELDS = SUMMARY_FIELDS + (
    "allergens_contains", "allergens_may_contain", "allergens_free_from", "allergen_info_missing",
    "vendor", "country", "description", "carbon_kg_per_kg", "delivery_reliability",
    "official_substitutes",
)


def error(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable}


def _pick(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """Only the contract's fields, so nothing extra from the catalog reaches the agent."""
    if dataclasses.is_dataclass(obj):
        obj = dataclasses.asdict(obj)
    elif hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    return {f: obj[f] for f in fields}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def locked(method):
    """Tools run on worker threads but share one SQLite connection, so one call at a time."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class Service:
    def __init__(self, conn: sqlite3.Connection, catalog: Any, now: Callable[[], datetime],
                 unusual_scorer: Any = None, require_enrolment_code: bool = False):
        self.conn = conn
        self.unusual_scorer = unusual_scorer
        self.require_enrolment_code = require_enrolment_code
        self.catalog = catalog
        self.now = now
        self.key = signing.server_key(conn)
        self._lock = threading.RLock()

    def _log(self, actor: str, action: str, reason: str, order_id: str | None = None,
             quote_id: str | None = None) -> None:
        audit.append(self.conn, self.now(), actor, action, reason, order_id, quote_id)

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

    # Search and details: static data only.

    @locked
    def search_products(self, text: str, category: str | None = None,
                        must_have_tags: list[str] | None = None, actor: str = "agent") -> list[dict]:
        tags = must_have_tags or []
        found = self.catalog.search_products(text, category, tags)
        filters = "".join([f", category {category}" if category else "",
                           f", tags {', '.join(tags)}" if tags else ""])
        self._log(actor, "search_products", f"Searched for \"{text}\"{filters}. {len(found)} products found.")
        return [_pick(p, SUMMARY_FIELDS) for p in found]

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
    def request_quote(self, lines: list[dict], need_by: date | str, actor: str = "agent") -> dict:
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
                return error("bad_unit", f"{product.name_en} cannot be ordered in {line['unit']}. "
                             "Use the other unit (L or KG).")

        offers = self._offers([product.id for product, _ in plans], need_by)
        if "code" in offers and "retryable" in offers:
            return offers

        quote_lines, total_with_tax = [], 0.0
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
            quote_lines.append({
                "product_id": product.id,
                "name": product.name_en,
                "units": plan.units,
                "sales_unit": plan.sales_unit,
                "covers": plan.covers,
                "content_unit": plan.content_unit,
                "unit_price_eur": offer.unit_price_eur,
                "line_total_eur": round(plan.units * offer.unit_price_eur, 2),
                "available_date": offer.available_date.isoformat() if offer.available_date else None,
                "cutoff_passed": bool(offer.cutoff_passed),
                "stock": "confirmed" if offer.available_units is not None else "unconfirmed",
            })
            total_with_tax += plan.units * offer.unit_price_with_tax_eur

        body = {
            "quote_id": _new_id("q"),
            "lines": quote_lines,
            "total_eur": round(sum(l["line_total_eur"] for l in quote_lines), 2),
            "total_with_tax_eur": round(total_with_tax, 2),
            "expires_at": (now + QUOTE_TTL).isoformat(),
        }
        signature = signing.sign_quote(body, need_by, self.key)
        self.conn.execute(
            "INSERT INTO quotes (quote_id, body_json, signature, created_at) VALUES (?, ?, ?, ?)",
            (body["quote_id"], json.dumps(body), signature, now.isoformat()),
        )
        return {**body, "signature": signature}

    # Orders

    @locked
    def place_order(self, quote_id: str, mandate_token: str, rationale: str,
                    confirm_unusual: bool = False, agent_signature: str | None = None) -> dict:
        return self._place_order(quote_id, mandate_token, rationale, confirm_unusual, agent_signature)

    def _refuse(self, quote_id: str, reason: str) -> dict:
        """A refusal that is not tied to an order, so it cannot use up someone's quote."""
        known = self.conn.execute("SELECT 1 FROM quotes WHERE quote_id = ?", (quote_id,)).fetchone()
        self._log("policy", "decision:rejected", reason, quote_id=quote_id if known else None)
        return {"status": "rejected", "reasons": [reason]}

    def _order_result(self, order: sqlite3.Row) -> dict:
        result = {"status": order["status"], "order_id": order["order_id"]}
        if order["approval_id"]:
            result["approval_id"] = order["approval_id"]
        if order["question"]:
            result["question"] = order["question"]
        result["reasons"] = json.loads(order["reasons_json"])
        return result

    def _order(self, **where: str) -> sqlite3.Row | None:
        (column, value), = where.items()
        return self.conn.execute(f"SELECT * FROM orders WHERE {column} = ?", (value,)).fetchone()

    def _place_order(self, quote_id: str, mandate_token: str, rationale: str,
                     confirm_unusual: bool, agent_signature: str | None = None) -> dict:
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
            problem = signing.order_signature_problem(agent_signature, mandate, quote_id, confirm_unusual)
            if problem:
                self._log("unknown agent", "place_order",
                          f"Asked to order quote {quote_id} for {mandate['buyer']} with a copy of its "
                          "mandate, but without a valid signature from its agent.")
                return self._refuse(quote_id, problem)
        quote_row = self.conn.execute("SELECT * FROM quotes WHERE quote_id = ?", (quote_id,)).fetchone()
        self._log(actor, "place_order",
                  f"Asked to order quote {quote_id} for {mandate['buyer']}"
                  f"{' and confirmed the unusual amount' if confirm_unusual else ''}. "
                  f"{'The order is signed by the agent key named in the mandate. ' if signed_by_agent else ''}"
                  f"The agent's reason: \"{rationale[:500]}\"",
                  quote_id=quote_id if quote_row else None)

        existing = self._order(quote_id=quote_id)
        if existing is not None:
            if existing["buyer_id"] != buyer_id:
                return self._refuse(quote_id, "This quote has already been used by another buyer.")
            if not (existing["status"] == "needs_clarification" and confirm_unusual):
                return self._order_result(existing)

        if quote_row is None:
            return self._refuse(quote_id, f"There is no quote with id {quote_id}. Request a new quote.")
        quote = {**json.loads(quote_row["body_json"]), "signature": quote_row["signature"]}
        try:
            need_by = signing.check_quote(quote, self.key.public_key(), now)
        except signing.QuoteError as e:
            return self._refuse(quote_id, str(e))

        products = {l["product_id"]: self.catalog.get_product(l["product_id"]) for l in quote["lines"]}
        products = {pid: p for pid, p in products.items() if p is not None}
        history = [dict(row) for row in self.conn.execute(
            "SELECT category, amount, content_unit FROM order_history WHERE buyer_id = ?", (buyer_id,))]
        if existing is not None:
            # The agent is confirming an amount it was asked about. Keep the flag, don't re-score.
            ai_unusual = next((r for r in json.loads(existing["reasons_json"])
                               if r.startswith(REASON_PREFIX)), None)
        else:
            ai_unusual = self._ai_unusual(mandate["buyer"], history, quote, products, quote_id)
        decision = decide({**quote, "need_by": need_by.isoformat()}, mandate, products, history,
                          confirm_unusual, ai_unusual,
                          self._spent_in_period(buyer_id, mandate, now, quote_id))

        order_id = existing["order_id"] if existing else _new_id("ord")
        approval_id = _new_id("apr") if decision.status == "pending_approval" else None
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO orders (order_id, quote_id, buyer_id, mandate_id, status, approval_id, "
                "question, reasons_json, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (order_id) DO UPDATE SET status = excluded.status, "
                "approval_id = excluded.approval_id, question = excluded.question, "
                "reasons_json = excluded.reasons_json, rationale = excluded.rationale",
                (order_id, quote_id, buyer_id, mandate["mandate_id"], decision.status, approval_id,
                 decision.question, json.dumps(decision.reasons), rationale, now.isoformat()),
            )
            if approval_id:
                self.conn.execute(
                    "INSERT INTO approvals (approval_id, order_id, status, approvers_json) "
                    "VALUES (?, ?, 'pending', ?)",
                    (approval_id, order_id, json.dumps(mandate.get("approvers", []))),
                )
        self._log("policy", f"decision:{decision.status}", " ".join(decision.reasons),
                  order_id=order_id, quote_id=quote_id)
        return self._order_result(self._order(order_id=order_id))

    def _spent_in_period(self, buyer_id: str, mandate: dict, now: datetime, quote_id: str) -> float:
        """What this buyer's other live orders in the current budget period add up to, in euros."""
        budget = mandate.get("budget")
        if not budget:
            return 0.0
        rows = self.conn.execute(
            "SELECT q.body_json FROM orders o JOIN quotes q USING (quote_id) "
            "WHERE o.buyer_id = ? AND o.quote_id != ? AND o.created_at >= ? "
            "AND o.status IN ('confirmed', 'pending_approval')",
            (buyer_id, quote_id, period_start(budget["period"], now).isoformat()))
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
        verdict = "unusual, so the agent is asked" if score >= THRESHOLD else "not unusual"
        self._log(MODEL, "unusual_score", f"Scored {score:.2f} that this amount is unusual for "
                  f"{buyer}: {verdict}. The 5 times rule also applies.", quote_id=quote_id)
        return flag_reason(score) if score >= THRESHOLD else None

    # Approvals

    @locked
    def get_approval_status(self, approval_id: str, actor: str = "agent") -> dict:
        row = self.conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
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
                      actor: str = "agent") -> list[dict] | dict:
        if not order_id and not quote_id:
            self._log(actor, "get_audit_log", "Asked for the log without an order or quote id.")
            return error("missing_filter", "Give an order_id or a quote_id.")
        if order_id:
            order = self._order(order_id=order_id)
            quote_id = quote_id or (order["quote_id"] if order else None)
        found = audit.entries(self.conn, order_id=order_id, quote_id=quote_id)
        self._log(actor, "get_audit_log", f"Read the log for {order_id or quote_id}: {len(found)} entries.")
        return found

    @locked
    def full_log(self) -> list[dict]:
        return audit.entries(self.conn)

    @locked
    def verify_log(self) -> dict:
        return audit.verify(self.conn)
