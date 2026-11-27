import base64, json
from decimal import Decimal
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from trade_document import shipments as sh, server as api
from trade_document.approval import Proof, message
from trade_document.storage import canonical


def test_split_issue_and_reservation(order, monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv(
        "TRADE_DOC_REVIEWERS",
        json.dumps(
            {
                "buyer-review": base64.b64encode(
                    key.public_key().public_bytes_raw()
                ).decode()
            }
        ),
    )

    def sign(payload):
        return Proof(
            reviewer="buyer-review",
            signature=base64.b64encode(key.sign(payload)).decode(),
        )

    snap = api.create_order_draft(order)
    api.preview_document(snap.order_id, 1)
    packet = api.request_approval(snap.order_id, 1)
    api.generate_document(packet.request_id, sign(message(packet, "buyer-review")))
    shipment = sh.Shipment(
        number="SH-001",
        dispatch_date="2026-12-01",
        consignee="Example port depot",
        freight="2.00",
        fees="0",
        discount="0",
        source="Synthetic warehouse report",
        boxes=[
            {
                "mark": "CTN-1",
                "net_kg": "1.20",
                "gross_kg": "1.45",
                "volume_m3": "0.03",
                "contents": [
                    {"sku": "W-101", "quantity": "1", "unit": "pairs", "origin": "CN"}
                ],
            }
        ],
    )
    saved = sh.create_shipment(snap.order_id, 1, shipment)
    assert saved.payable == Decimal("17.25")
    packet = sh.preview_shipment(saved.shipment_id, 1)
    with pytest.raises(ValueError):
        sh.export_document_bundle(packet, sign(b"wrong"))
    released = sh.export_document_bundle(
        packet, sign(canonical(packet.model_dump(mode="json")))
    )
    assert sh.cross_check_documents(saved.shipment_id, 1).valid
    assert len(released.files) == 4
    assert released == sh.export_document_bundle(
        packet, sign(canonical(packet.model_dump(mode="json")))
    )
    with pytest.raises(ValueError):
        sh.revise_shipment(saved.shipment_id, 1, shipment)
    shipment.number = "SH-002"
    shipment.boxes[0].contents[0].quantity = Decimal(2)
    with pytest.raises(ValueError, match="remaining"):
        sh.create_shipment(snap.order_id, 1, shipment)
    returned = sh.Adjustment(
        shipment_id=saved.shipment_id,
        version=1,
        revision_digest=saved.digest,
        reference="RT-1",
        reason="Warehouse received one pair",
        action="received_return",
        quantities={"W-101": "1"},
    )
    receipt = sh.adjust_shipment(
        returned, sign(canonical(returned.model_dump(mode="json")))
    )
    assert receipt.reference == "RT-1"
    replacement = sh.create_shipment(snap.order_id, 1, shipment)
    cancel = sh.Adjustment(
        shipment_id=replacement.shipment_id,
        version=1,
        revision_digest=replacement.digest,
        reference="CANCEL-1",
        reason="Warehouse recalled pick",
        action="cancel_draft",
    )
    sh.adjust_shipment(cancel, sign(canonical(cancel.model_dump(mode="json"))))
    with pytest.raises(ValueError):
        sh.preview_shipment(replacement.shipment_id, 1)
    Path(released.files[0]).write_bytes(b"changed")
    assert not sh.cross_check_documents(saved.shipment_id, 1).valid
