"""A second opinion on "is this order unusual for this buyer?" from Google's Decisions API.

It can only add a question for the agent. The 5 times rule in policy.py always runs too,
so a low score, a slow answer or an outage never lets an order through.
"""

import os
import ssl
from statistics import median

import httpx
import truststore

URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
MODEL = "gemini-decision-1"
THRESHOLD = 0.8
REASON_PREFIX = "Google's Decisions API"


def flag_reason(score: float) -> str:
    return (f"{REASON_PREFIX} ({MODEL}) rates this order {score:.0%} likely to be unusual "
            "for this buyer, compared with its past orders.")


def _env_key() -> str | None:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    try:
        from dotenv import dotenv_values
        return dotenv_values(".env").get("GEMINI_API_KEY") or None
    except ImportError:
        return None


class DecisionsScorer:
    def __init__(self, api_key: str | None = "from-env", transport: httpx.BaseTransport | None = None,
                 timeout_s: float = 4.0):
        self.api_key = _env_key() if api_key == "from-env" else api_key
        # The OS trust store, so this also works behind a TLS-inspecting proxy.
        verify = True if transport else truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.client = httpx.Client(transport=transport, timeout=timeout_s, verify=verify)

    def _input(self, buyer: str, history: list[dict], lines: list[dict]) -> str:
        """Amounts only. No agent rationale or product descriptions, which an attacker can write."""
        past = {}
        for h in history:
            past.setdefault((h["category"], h["content_unit"]), []).append(h["amount"])
        text = [f"Buyer: {buyer}.", "Past orders, amount per order:"]
        for (category, unit), amounts in past.items():
            text.append(f"- category {category}: {', '.join(f'{a:g}' for a in amounts)} {unit} "
                        f"(median {median(amounts):g} {unit})")
        text.append("This order:")
        for line in lines:
            text.append(f"- {line['covers']:g} {line['content_unit']} of {line['name']} "
                        f"(category {line['category']})")
        return "\n".join(text)

    def score(self, buyer: str, history: list[dict], lines: list[dict]) -> float | None:
        """Probability from 0 to 1 that the order is unusual, or None if there is no answer."""
        if not self.api_key or not history:
            return None
        body = {
            "model": MODEL,
            "input": self._input(buyer, history, lines),
            "questions": {"unusual": {
                "type": "noul",
                "instructions": "Is the amount in this order unusual for this buyer, given its "
                                "past orders in the same category?",
                "criteria": {
                    "true_description": "The amount is far outside what this buyer normally orders.",
                    "false_description": "The amount is in line with this buyer's normal orders.",
                },
            }},
        }
        try:
            response = self.client.post(URL, json=body, headers={"x-goog-api-key": self.api_key})
            if response.status_code != 200:
                return None
            value = response.json()["answers"]["unusual"]["noul"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            return None
        return float(value)
