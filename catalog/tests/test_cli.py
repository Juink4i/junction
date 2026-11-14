from datetime import date

from catalog.__main__ import options

MONDAY = date(2026, 11, 16)


def test_options_for_1000_litres_lactose_free_milk(priced):
    rows = options(1000, "L", MONDAY, category="10400", tags=["FREE_FROM_LACTOSE"])
    assert len(rows) == 35
    on_time = [r for r in rows if r["on_time"]]
    # On-time options come first, cheapest total first.
    assert rows[: len(on_time)] == on_time
    assert [r["total_eur"] for r in on_time] == sorted(r["total_eur"] for r in on_time)
    best = on_time[0]
    assert best["product_id"] == "464306" and best["units"] == 1000 and best["total_eur"] == 1010.0


def test_late_options_say_why(priced):
    rows = {r["product_id"]: r for r in options(1000, "L", MONDAY, category="10400", tags=["FREE_FROM_LACTOSE"])}
    assert rows["465039"]["on_time"] is False and "cut-off" in rows["465039"]["why_not"]
    assert rows["464440"]["on_time"] is False and "cannot be delivered" in rows["464440"]["why_not"]
    assert rows["472492"]["on_time"] is False and "per KG" in rows["472492"]["why_not"]
