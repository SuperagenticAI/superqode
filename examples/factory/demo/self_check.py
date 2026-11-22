"""Visible regression checks. Protected acceptance uses separate CLI probes."""

import sys
from app import active, ordered, totals


case = sys.argv[1]
if case == "totals":
    assert totals([{"category": "a", "amount": 2}, {"category": "a", "amount": 3}]) == {"a": 5}
    assert totals([]) == {}
elif case == "active":
    assert active([{"id": 1}, {"id": 2, "active": True}, {"id": 3, "active": False}]) == [
        {"id": 2, "active": True}
    ]
    assert active([]) == []
elif case == "ordered":
    assert ordered(["zebra", "Apple", "banana", "Zoo"]) == ["Apple", "banana", "zebra", "Zoo"]
    assert ordered([]) == []
else:
    raise ValueError("Unknown demo case")
print("self-check passed")
