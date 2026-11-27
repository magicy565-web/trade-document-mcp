import pytest
from decimal import Decimal
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


@pytest.mark.parametrize("lang", ["en", "de", "fr"])
def test_localized_insurance_and_tooling(order, lang):
    order.language = lang
    order.insurance = Decimal("1.00")
    order.tooling_fee = Decimal("9.00")
    s = server.create_order_draft(order)
    assert calculate(order).total == Decimal("78.50")
    assert server.preview_document(s.order_id, 1).audit.passed


def test_unknown_price_preview(order):
    from openpyxl import load_workbook

    order.items[0].unit_price = None
    order.freight = None
    s = server.create_order_draft(order)
    a = server.preview_document(s.order_id, 1)
    assert a.preview and server.audit_document(a.artifact_id).passed
    ws = load_workbook(a.xlsx_path).active
    assert any(r[0].value == "Total" and r[1].value == "Pending" for r in ws)
    with pytest.raises(ValueError):
        server.request_approval(s.order_id, 1)


def test_dimension_conversion():
    from trade_document.trade_fields import Measure, convert_measure

    assert convert_measure(Measure(amount="1", unit="lb"), "g").amount == Decimal(
        "453.59237"
    )
    with pytest.raises(ValueError):
        convert_measure(Measure(amount="1", unit="lb"), "ft")


def test_preview_tampering_and_expiry(order, monkeypatch):
    import base64, json
    from pathlib import Path
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from trade_document import approval

    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv(
        "TRADE_DOC_REVIEWERS",
        json.dumps(
            {"review": base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        ),
    )
    s = server.create_order_draft(order)
    a = server.preview_document(s.order_id, 1)
    p = server.request_approval(s.order_id, 1)
    proof = approval.Proof(
        reviewer="review",
        signature=base64.b64encode(key.sign(approval.message(p, "review"))).decode(),
    )
    with monkeypatch.context() as m:
        m.setattr(approval.time, "time", lambda: p.binding.expires + 1)
        with pytest.raises(ValueError, match="Expired"):
            server.generate_document(p.request_id, proof)
    Path(a.xlsx_path).write_bytes(b"changed preview")
    with pytest.raises(ValueError, match="Preview changed"):
        server.generate_document(p.request_id, proof)


def test_three_decimal_currency(order):
    order.currency = "BHD"
    order.items[0].unit_price = Decimal("1.2345")
    s = server.create_order_draft(order)
    assert calculate(order).lines[0] == Decimal("2.469")
    assert server.preview_document(s.order_id, 1).audit.passed


def test_beneficiary_dual_control(order, monkeypatch):
    import base64, json
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from trade_document.beneficiaries import Change, change_beneficiary
    from trade_document.approval import Proof
    from trade_document.storage import canonical

    keys = [Ed25519PrivateKey.generate() for _ in range(2)]
    for i, role in enumerate(["TRADE_FINANCE_VERIFIERS", "TRADE_FINANCE_AUTHORIZERS"]):
        monkeypatch.setenv(
            role,
            json.dumps(
                {
                    str(i): base64.b64encode(
                        keys[i].public_key().public_bytes_raw()
                    ).decode()
                }
            ),
        )
    change = Change(
        reference="fixture",
        instructions="Fictional settlement instructions",
        verification_record="Synthetic callback evidence",
        status="active",
        version=1,
    )

    def proof(i, c):
        return Proof(
            reviewer=str(i),
            signature=base64.b64encode(
                keys[i].sign(canonical(c.model_dump(mode="json")))
            ).decode(),
        )

    with pytest.raises(ValueError):
        change_beneficiary(change, proof(0, change), proof(0, change))
    change_beneficiary(change, proof(0, change), proof(1, change))
    order.bank = change.instructions
    order.beneficiary_ref = change.reference
    s = server.create_order_draft(order)
    assert server.validate_order(s.order_id).valid
    revoked = change.model_copy(update={"status": "revoked", "version": 2})
    change_beneficiary(revoked, proof(0, revoked), proof(1, revoked))
    assert not server.validate_order(s.order_id).valid
