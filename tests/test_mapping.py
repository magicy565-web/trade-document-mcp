from io import BytesIO
import base64, json
from openpyxl import Workbook
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from trade_document import mapping
from trade_document.approval import Proof
from trade_document.storage import canonical
import pytest


def test_mapping_requires_signature(monkeypatch):
    wb = Workbook()
    for row, v in [(2, "Proforma Invoice"), (4, "Seller"), (20, "SKU")]:
        wb.active.cell(row, 1, v)
    buf = BytesIO()
    wb.save(buf)
    encoded = base64.b64encode(buf.getvalue()).decode()
    candidate = mapping.propose_template_mapping(encoded)
    assert candidate.items == 20
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv(
        "TRADE_TEMPLATE_REVIEWERS",
        json.dumps(
            {"admin": base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        ),
    )
    proof = Proof(
        reviewer="admin",
        signature=base64.b64encode(
            key.sign(canonical(candidate.model_dump(mode="json")))
        ).decode(),
    )
    template = mapping.confirm_template_mapping(encoded, candidate, proof)
    assert mapping.validate_template(template.template_id).valid
    with pytest.raises(ValueError):
        mapping.confirm_template_mapping(
            encoded, candidate.model_copy(update={"title": 1}), proof
        )
