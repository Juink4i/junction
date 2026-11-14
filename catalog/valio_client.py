"""Client for Valio Aimo's two mock APIs: POST /api/price and POST /api/availability.

- One call to each endpoint per request (batches of up to 1,000 ids), shortlists only.
- Answers are cached for 5 minutes per (product, delivery date).
- "Cut-off passed" is worked out when an answer is read, from the API's own timeNow plus the
  time since the call, so a cached answer can't hide a cut-off that passed meanwhile.
- Stock of 999999 or more is a placeholder and becomes None (unknown).
- Server errors and rate limits are retried once, then reported. Stock is never guessed.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

import httpx

from catalog.load import ROOT
from catalog.models import Offer

BASE_URL = "https://junction26.valioaimo.fi"
BATCH = 1000
PLACEHOLDER_STOCK = 999_999
USER_AGENT = "valio-aimo-trade-catalog/0.1"  # the API rejects Python's default user agent (403)
CUSTOMER = "junction-demo"  # the customer number does not change answers in this challenge


class ValioApiError(Exception):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # "2026-11-12T15:00:00+0200" -> "+02:00"
    return datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value))


def _env_key() -> str | None:
    if os.environ.get("VALIO_API_KEY"):
        return os.environ["VALIO_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("VALIO_API_KEY="):
                return line.split("=", 1)[1].strip() or None
    return None


@dataclass
class _Entry:
    price: dict
    availability: dict | None
    server_time: datetime  # the API's timeNow when answered
    fetched_at: float  # our clock when answered


class ValioClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic, ttl_seconds: float = 300,
                 timeout: float = 20):
        key = api_key or _env_key()
        if not key:
            raise ValioApiError("VALIO_API_KEY is not set (.env or environment)", retryable=False)
        self._http = httpx.Client(
            base_url=base_url or os.environ.get("VALIO_API_BASE", BASE_URL),
            headers={"X-API-Key": key, "User-Agent": USER_AGENT, "Accept": "application/json"},
            transport=transport, timeout=timeout,
        )
        self._clock = clock
        self._ttl = ttl_seconds
        self._cache: dict[tuple[str, date], _Entry] = {}
        self._lock = threading.Lock()

    # -- HTTP -------------------------------------------------------------------------------

    def _post(self, endpoint: str, ids: list[str], delivery_date: date) -> dict:
        body = {"customer": CUSTOMER, "requestedDate": delivery_date.isoformat(), "products": ids}
        for attempt in (1, 2):
            try:
                r = self._http.post(f"/api/{endpoint}", json=body)
            except httpx.TransportError as e:
                if attempt == 2:
                    raise ValioApiError(f"{endpoint}: {type(e).__name__}", retryable=True) from e
                continue
            if r.status_code == 200:
                return r.json()
            retryable = r.status_code == 429 or r.status_code >= 500
            if not retryable or attempt == 2:
                raise ValioApiError(f"{endpoint}: HTTP {r.status_code}", retryable=retryable)
            time.sleep(1.0 if r.status_code == 429 else 0)
        raise AssertionError("unreachable")

    def _fetch(self, ids: list[str], delivery_date: date) -> None:
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i + BATCH]
            price = self._post("price", chunk, delivery_date)
            avail = self._post("availability", chunk, delivery_date)
            fetched_at = self._clock()
            server_time = _parse_dt(avail.get("timeNow"))
            avail_by_id = {a["productId"]: a for a in avail.get("products", [])}
            for p in price.get("products", []):
                if p.get("error") or not p.get("catalogPrice"):
                    continue  # no price: no offer
                self._cache[(p["productId"], delivery_date)] = _Entry(
                    p, avail_by_id.get(p["productId"]), server_time, fetched_at)

    # -- Public -----------------------------------------------------------------------------

    def offers(self, product_ids: list[str], delivery_date: date) -> dict[str, Offer]:
        ids = list(dict.fromkeys(str(i) for i in product_ids))
        with self._lock:
            now = self._clock()
            stale = [i for i in ids if (e := self._cache.get((i, delivery_date))) is None
                     or now - e.fetched_at >= self._ttl]
            if stale:
                self._fetch(stale, delivery_date)
            now = self._clock()
            return {i: self._offer(i, self._cache[(i, delivery_date)], now)
                    for i in ids if (i, delivery_date) in self._cache}

    def cached_price(self, product_id: str) -> dict | None:
        """Any fresh price answer for this product, whatever the date (for unit maths)."""
        now = self._clock()
        for (pid, _), e in self._cache.items():
            if pid == product_id and now - e.fetched_at < self._ttl:
                return e.price
        return None

    @staticmethod
    def _offer(product_id: str, e: _Entry, now: float) -> Offer:
        p, a = e.price, e.availability or {}
        line = (a.get("scheduleLines") or [None])[0]
        server_now = e.server_time + timedelta(seconds=now - e.fetched_at) if e.server_time else None
        closing = _parse_dt(a.get("closingTime"))
        amount = line.get("availableAmount") if line else None
        if amount is None or amount >= PLACEHOLDER_STOCK:
            units = None
        else:
            units = int(amount)
        orderable = bool(line) and not a.get("salesBlock") and not line.get("salesBlock") and units != 0
        cp = p.get("comparisonPrice") or {}
        lp = p.get("listPrice") or {}
        return Offer(
            product_id=product_id,
            unit_price_eur=p["catalogPrice"]["value"],
            unit_price_with_tax_eur=p["catalogPrice"].get("valueWithTax")
            or (p.get("priceWithTax") or {}).get("value"),
            comparison_price_eur=cp.get("value"),
            comparison_unit=p.get("comparisonUnit") if p.get("comparisonUnit") in ("L", "KG") else None,
            tax_rate=(p.get("tax") or {}).get("taxRate", 0.0),
            list_price_eur=lp.get("value"),
            price_valid_to=_parse_dt(p["catalogPrice"].get("validTo")),
            orderable=orderable,
            available_date=date.fromisoformat(line["availableDate"]) if line and line.get("availableDate") else None,
            closing_time=closing,
            cutoff_passed=bool(closing and server_now and closing <= server_now),
            logistic_model=a.get("logisticModel") if a.get("logisticModel") in ("Stock", "Terminal") else None,
            available_units=units,
        )
