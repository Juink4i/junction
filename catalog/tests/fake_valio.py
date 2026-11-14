"""A fake Valio Aimo API that replays the recorded responses in fixtures/. No network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"
DATE = "2026-11-16"


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeValio:
    """Serves price and availability for the 35 recorded lactose-free milks.

    Unknown ids get a price error and an empty availability, like the real API.
    `fail_next` makes the next N requests return that HTTP status.
    """

    def __init__(self):
        self.price = json.loads((FIXTURES / f"price_lf_milk_{DATE}.json").read_text(encoding="utf-8"))
        self.avail = json.loads((FIXTURES / f"availability_lf_milk_{DATE}.json").read_text(encoding="utf-8"))
        self.requests: list[httpx.Request] = []
        self.fail_next: list[int] = []

    def calls(self, endpoint: str) -> int:
        return sum(1 for r in self.requests if r.url.path == f"/api/{endpoint}")

    def requested_ids(self, endpoint: str) -> list[list[str]]:
        return [json.loads(r.content)["products"] for r in self.requests if r.url.path == f"/api/{endpoint}"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"detail": "fake failure"})
        ids = json.loads(request.content)["products"]
        if request.url.path == "/api/price":
            known = {p["productId"]: p for p in self.price["products"]}
            products = [known.get(i, {"productId": i, "quantity": 1.0, "netPriceFound": False, "error": True})
                        for i in ids]
            return httpx.Response(200, json={**self.price, "products": products})
        if request.url.path == "/api/availability":
            known = {p["productId"]: p for p in self.avail["products"]}
            products = [known.get(i, {"productId": i, "closingTime": None, "salesBlock": False,
                                      "logisticModel": None, "scheduleLines": []}) for i in ids]
            return httpx.Response(200, json={**self.avail, "products": products})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
