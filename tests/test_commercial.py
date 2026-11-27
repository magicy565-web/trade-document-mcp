from decimal import Decimal
import pytest
from trade_document import server
from trade_document.model import Order, calculate, issues


def test_meter_order_split(order):
    data = order.model_dump(mode="json")
    data.update(
        schedule=[
            {"event": "Deposit", "percent": "30"},
            {"event": "Before shipment", "percent": "70"},
        ],
        paper="Letter",
        valid_until="2026-12-10",
        ship_to="Sample warehouse",
    )
    data["items"][0]["quantity"] = "2.50"
    o = Order.model_validate(data)
    assert calculate(o).total == Decimal("76.13")
    assert calculate(o).installments == [Decimal("22.84"), Decimal("53.29")]
    s = server.create_order_draft(o)
    a = server.preview_document(s.order_id, 1)
    assert a.audit.passed
    assert server.request_approval(s.order_id, 1).binding.preview_id == a.artifact_id


def test_duplicate_and_beneficiary(order):
    order.items.append(order.items[0])
    order.bank = "Unverified instructions"
    assert any("SKU" in e for e in issues(order))
    assert any("beneficiary" in e for e in issues(order))
