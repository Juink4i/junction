from agent.events import EventSink, scrub, summarize_result


def test_search_summary_handles_the_servers_bare_list():
    found = [{"id": "1", "name_en": "Milk A"}, {"id": "2", "name_en": "Milk B"}]
    assert summarize_result("search_products", found) == "2 products: Milk A; Milk B"
    assert summarize_result("search_products", {"count": 2, "products": found}).startswith("2 products")


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
