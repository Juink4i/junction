import json

import httpx

from server.unusual import DecisionsScorer

HISTORY = [{"category": "10400", "amount": a, "content_unit": "L"} for a in (20, 20, 25, 15)]
LINES = [{"product_id": "464201", "name": "Lactose-free milk 1 L", "category": "10400",
          "covers": 200.0, "content_unit": "L"}]


def scorer_answering(status=200, body=None, error=None, key="test-key", seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if error:
            raise error
        return httpx.Response(status, json=body)
    return DecisionsScorer(api_key=key, transport=httpx.MockTransport(handler))


def noul(value):
    return {"answers": {"unusual": {"type": "noul", "noul": value, "confidence": value}}}


def test_sends_a_noul_question_with_the_buyers_history_and_the_order():
    seen = []
    scorer_answering(body=noul(0.97), seen=seen).score("Café Kallio", HISTORY, LINES)
    (request,) = seen
    assert request.url == "https://generativelanguage.googleapis.com/v1beta/decisions"
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["model"] == "gemini-decision-1"
    assert body["questions"]["unusual"]["type"] == "noul"
    assert "Café Kallio" in body["input"]
    assert "20, 20, 25, 15" in body["input"]
    assert "200" in body["input"] and "Lactose-free milk 1 L" in body["input"]


def test_returns_the_probability_that_the_order_is_unusual():
    assert scorer_answering(body=noul(0.97)).score("Café", HISTORY, LINES) == 0.97


def test_no_history_means_no_call_and_no_score():
    seen = []
    assert scorer_answering(body=noul(0.97), seen=seen).score("Café", [], LINES) is None
    assert seen == []


def test_any_failure_gives_no_score():
    assert scorer_answering(status=500, body={"error": {"code": 500}}).score("C", HISTORY, LINES) is None
    assert scorer_answering(status=400, body={"error": {"code": "safety"}}).score("C", HISTORY, LINES) is None
    assert scorer_answering(body={"answers": {}}).score("C", HISTORY, LINES) is None
    assert scorer_answering(body=noul("high")).score("C", HISTORY, LINES) is None
    assert scorer_answering(error=httpx.ReadTimeout("slow")).score("C", HISTORY, LINES) is None


def test_without_an_api_key_it_never_calls():
    seen = []
    scorer = scorer_answering(body=noul(0.97), key=None, seen=seen)
    assert scorer.score("Café", HISTORY, LINES) is None
    assert seen == []
