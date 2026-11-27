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


def test_signed_template_keeps_fixed_brand_and_appendix(monkeypatch, order):
    from trade_document import server
    from pypdf import PdfReader
    import shutil

    if shutil.which("soffice") is None:
        pytest.skip("Calc integration requires LibreOffice")
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Fictional brand guide"
    ws.merge_cells("A1:D1")
    ws["A3"] = "Proforma Invoice"
    ws["A5"] = "Seller"
    ws["A22"] = "SKU"
    wb.create_sheet("Terms")["A1"] = "Synthetic appendix"
    buf = BytesIO()
    wb.save(buf)
    raw = base64.b64encode(buf.getvalue()).decode()
    m = mapping.propose_template_mapping(raw)
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv(
        "TRADE_TEMPLATE_REVIEWERS",
        json.dumps(
            {"review": base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        ),
    )
    proof = Proof(
        reviewer="review",
        signature=base64.b64encode(
            key.sign(canonical(m.model_dump(mode="json")))
        ).decode(),
    )
    order.template_id = mapping.confirm_template_mapping(raw, m, proof).template_id
    s = server.create_order_draft(order)
    a = server.preview_document(s.order_id, 1)
    reader = PdfReader(a.pdf_path)
    assert (
        len(reader.pages) >= 2
        and "Synthetic appendix" in reader.pages[-1].extract_text()
    )
    assert server.audit_document(a.artifact_id).passed
