from datetime import datetime, timezone

from server import audit
from server.db import connect

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def log_three(conn):
    audit.append(conn, NOW, "buyer-agent-01", "request_quote", "Quoted 10 L of milk.", quote_id="q1")
    audit.append(conn, NOW, "policy", "decision:confirmed", "Within every limit.",
                 quote_id="q1", order_id="o1")
    audit.append(conn, NOW, "buyer-agent-02", "request_quote", "Quoted 5 kg of tomato.", quote_id="q2")


def test_entry_has_time_actor_action_reason_and_previous_hash():
    conn = connect(":memory:")
    log_three(conn)
    first, second, _ = audit.entries(conn)
    assert set(first) == {"seq", "time", "actor", "action", "reason", "prev_hash", "hash"}
    assert first["prev_hash"] == "0" * 64
    assert second["prev_hash"] == first["hash"]
    assert second["actor"] == "policy"
    assert second["reason"] == "Within every limit."


def test_verify_is_ok_for_an_untouched_log():
    conn = connect(":memory:")
    log_three(conn)
    assert audit.verify(conn) == {"ok": True}


def test_verify_names_the_row_that_was_edited_by_hand():
    conn = connect(":memory:")
    log_three(conn)
    conn.execute("UPDATE log SET reason = 'Nothing to see here.' WHERE seq = 2")
    assert audit.verify(conn) == {"ok": False, "broken_at_seq": 2}


def test_verify_catches_a_deleted_row():
    conn = connect(":memory:")
    log_three(conn)
    conn.execute("DELETE FROM log WHERE seq = 2")
    assert audit.verify(conn) == {"ok": False, "broken_at_seq": 3}


def test_entries_can_be_filtered_by_quote_or_order():
    conn = connect(":memory:")
    log_three(conn)
    assert [e["seq"] for e in audit.entries(conn, quote_id="q1")] == [1, 2]
    assert [e["seq"] for e in audit.entries(conn, order_id="o1")] == [2]
