from agent.events import EventSink, scrub, summarize_result


def test_search_summary_says_what_fits_and_what_was_dropped():
    found = {"status": "ok", "products": [{"id": "1", "name_en": "Milk A"}, {"id": "2", "name_en": "Milk B"}],
             "dropped": [{"id": "3", "name": "Coffee milk", "reason": "coffee milk"}],
             "screened_by": "keyword rules"}
    assert summarize_result("search_products", found) == (
        "2 products fit, 1 dropped by keyword rules: Milk A; Milk B")
    asked = {"status": "needs_clarification", "question": "What product do you need?"}
    assert summarize_result("search_products", asked) == "question: What product do you need?"


def test_quote_summary_names_the_best_option():
    priced = {"status": "ok", "options": [
        {"label": "best", "expected": {"status": "pending_approval"}, "quote": {"total_eur": 1560.0}},
        {"label": "better", "expected": {"status": "confirmed"}, "quote": {"total_eur": 1580.0}}]}
    assert summarize_result("request_quote", priced) == "2 options, best: €1,560.00 (pending_approval)"
    assert summarize_result("request_quote", {"status": "ok", "options": [], "not_offered": [{}]}) == (
        "no options, 1 products left out")


def test_audit_log_summary_handles_lists():
    assert summarize_result("get_audit_log", [{"seq": 1}, {"seq": 2}]) == "2 log entries"


def test_errors_are_summarised_plainly():
    err = {"error": {"code": "insufficient_stock", "message": "Only 700 L left."}}
    assert summarize_result("request_quote", err) == "error insufficient_stock: Only 700 L left."


def test_secrets_are_scrubbed_everywhere():
    sink = EventSink(None, console=False, secrets=["sk-very-secret-value"])
    e = sink.publish("tool_result", result={"nested": ["sk-very-secret-value", "ok"]})
    assert "sk-very-secret-value" not in str(e)
    assert scrub({"a": "x"}, []) == {"a": "x"}


def test_a_place_order_summary_counts_the_alternatives_offered():
    result = {"status": "pending_approval", "order_id": "ord_1", "approval_id": "apr_1",
              "reasons": ["Over the order limit."],
              "alternatives": [{"quote_id": "q_2", "rank": 2, "label": "better",
                                "summary": "6 × 10 L Milk", "total_eur": 97.2}]}
    assert summarize_result("place_order", result) == (
        "pending_approval: Over the order limit. (1 alternatives offered)")
