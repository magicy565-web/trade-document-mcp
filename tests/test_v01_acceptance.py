from decimal import Decimal
from pathlib import Path
from openpyxl import load_workbook
from pypdf import PdfReader
import pytest

from trade_document import server
from trade_document.approval import Proof, message
from trade_document.model import Order
from trade_document.resolution import FieldResolution


def test_unpriced_draft_remains_reviewable_and_cannot_issue():
    order = Order(kind="standard-pi", seller="Fixture exporter")
    draft = server.create_order_draft(order)
    preview = server.preview_document(draft.order_id, 1)
    assert preview.audit.passed
    text = PdfReader(preview.pdf_path).pages[0].extract_text()
    assert "DRAFT" in text and "Pending" in text
    assert server.audit_document(preview.artifact_id).passed
    with pytest.raises(ValueError, match="Missing"):
        server.request_approval(draft.order_id, 1)


def test_field_resolution_preserves_revision_and_quote(order):
    order.freight = None
    order.unresolved = ["freight", "payment"]
    draft = server.create_order_draft(order)
    revised = server.update_order_draft(
        draft.order_id,
        1,
        resolutions=[
            FieldResolution(
                field="freight",
                value="18.00",
                source="Signed quote",
                line=5,
                quote="freight: 18.00",
            ),
        ],
    )
    assert revised.version == 2
    assert revised.order.freight == Decimal("18.00")
    assert revised.order.unresolved == ["payment"]
    assert revised.order.evidence[-1].quote == "freight: 18.00"
    assert server.get_order_draft(draft.order_id, 1).order.freight is None
    with pytest.raises(ValueError, match="Stale"):
        server.update_order_draft(draft.order_id, 1, order)


def test_fees_are_itemized_and_cross_checked(order):
    order.insurance = Decimal("2.25")
    order.tooling_fee = Decimal("11.50")
    order.buyer = "東京商事"
    draft = server.create_order_draft(order)
    preview = server.preview_document(draft.order_id, 1)
    assert server.calculate_order(draft.order_id).total == Decimal("82.25")
    assert "東京商事" in PdfReader(preview.pdf_path).pages[0].extract_text()
    sheet = load_workbook(preview.xlsx_path, data_only=True).active
    amounts = {
        r[4].value: r[5].value
        for r in sheet.iter_rows(max_col=6)
        if r[4].value is not None
    }
    assert amounts["Insurance"] == 2.25 and amounts["Tooling fee"] == 11.5
    assert server.audit_document(preview.artifact_id).passed


def test_two_challenges_cannot_issue_twice_and_preview_bytes_are_bound(
    order, monkeypatch
):
    import base64
    import json
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv(
        "TRADE_DOC_REVIEWERS",
        json.dumps(
            {"qa": base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        ),
    )

    def sign(review):
        return Proof(
            reviewer="qa",
            signature=base64.b64encode(key.sign(message(review, "qa"))).decode(),
        )

    s = server.create_order_draft(order)
    pending = server.preview_document(s.order_id, 1)
    first = server.request_approval(s.order_id, 1)
    second = server.request_approval(s.order_id, 1)
    issued = server.generate_document(first.request_id, sign(first))
    assert (
        server.generate_document(second.request_id, sign(second)).artifact_id
        == issued.artifact_id
    )
    duplicate = server.create_order_draft(order)
    server.preview_document(duplicate.order_id, 1)
    with pytest.raises(ValueError, match="Document number"):
        server.request_approval(duplicate.order_id, 1)
    Path(pending.xlsx_path).write_bytes(b"changed preview")
    with pytest.raises(ValueError, match="Preview changed"):
        server.generate_document(second.request_id, sign(second))


def test_finance_change_revokes_reuse_of_previous_approval(order, monkeypatch):
    import base64
    import json
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from trade_document.finance import BeneficiaryChange, change_beneficiary
    from trade_document.storage import canonical

    keys = {
        name: Ed25519PrivateKey.generate() for name in ("verify", "authorize", "issue")
    }
    for name, env in zip(
        keys,
        ("TRADE_FINANCE_VERIFIERS", "TRADE_FINANCE_AUTHORIZERS", "TRADE_DOC_REVIEWERS"),
    ):
        monkeypatch.setenv(
            env,
            json.dumps(
                {
                    name: base64.b64encode(
                        keys[name].public_key().public_bytes_raw()
                    ).decode()
                }
            ),
        )

    def sign(name, content):
        return Proof(
            reviewer=name, signature=base64.b64encode(keys[name].sign(content)).decode()
        )

    initial = BeneficiaryChange(
        reference="qa",
        version=1,
        instructions="Fictional payment instructions",
        verification_record="Synthetic verification log",
        status="active",
    )
    content = canonical(initial.model_dump(mode="json"))
    with pytest.raises(ValueError):
        change_beneficiary(initial, sign("verify", content), sign("verify", content))
    change_beneficiary(initial, sign("verify", content), sign("authorize", content))
    order.bank = initial.instructions
    order.beneficiary_ref = initial.reference
    draft = server.create_order_draft(order)
    server.preview_document(draft.order_id, 1)
    review = server.request_approval(draft.order_id, 1)
    assert review.binding.beneficiary_version == 1
    revoked = initial.model_copy(update={"version": 2, "status": "revoked"})
    content = canonical(revoked.model_dump(mode="json"))
    change_beneficiary(revoked, sign("verify", content), sign("authorize", content))
    assert not server.validate_order(draft.order_id).valid
    with pytest.raises(ValueError, match="Expired or invalid approval"):
        server.generate_document(
            review.request_id, sign("issue", message(review, "issue"))
        )


def business_cases():
    import json

    path = Path(__file__).parents[1] / "fixtures" / "acceptance" / "v01-cases.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize("case", business_cases(), ids=lambda case: case["id"])
def test_authored_business_case(order, case):
    data = order.model_dump(mode="json")
    data.update(case["overrides"], number=case["id"])
    draft = server.create_order_draft(Order.model_validate(data))
    validation = server.validate_order(draft.order_id)
    artifact = server.preview_document(draft.order_id, 1)
    assert artifact.audit.passed
    if "finding" in case:
        assert not validation.valid
        assert any(case["finding"] in message for message in validation.findings)
        with pytest.raises(
            ValueError, match=case["finding"].replace("[", r"\[").replace("]", r"\]")
        ):
            server.request_approval(draft.order_id, 1)
    else:
        assert validation.valid, validation.findings
        result = server.calculate_order(draft.order_id)
        assert result.total == Decimal(case["total"])
        if "installments" in case:
            assert result.installments == list(map(Decimal, case["installments"]))
        assert (
            server.request_approval(draft.order_id, 1).binding.preview_id
            == artifact.artifact_id
        )


def test_both_files_render_all_images_and_the_approved_variant(order):
    import base64
    from io import BytesIO
    from PIL import Image

    picture = BytesIO()
    Image.new("RGB", (80, 40), "#286659").save(picture, "PNG")
    encoded = base64.b64encode(picture.getvalue()).decode()
    order.kind = "product-image-pi"
    order.items[0].variant = "Indigo size 38"
    order.items[0].image = encoded
    order.items[0].additional_images = [encoded]
    order.items[1].image = encoded
    draft = server.create_order_draft(order)
    preview = server.preview_document(draft.order_id, 1)
    assert preview.audit.passed
    pdf = PdfReader(preview.pdf_path)
    assert "Indigo size 38" in pdf.pages[0].extract_text()
    assert len(load_workbook(preview.xlsx_path).active._images) == 3


def test_revision_from_before_new_fields_can_be_reviewed(order):
    from trade_document.storage import canonical, database, sha

    original = order.model_dump(mode="json", exclude_unset=True)
    body = canonical(original)
    key = "0" * 32
    with database() as db:
        db.execute(
            "INSERT INTO versions(id,version,body,digest) VALUES (?,?,?,?)",
            (key, 1, body.decode(), sha(body)),
        )
    server.preview_document(key, 1)
    request = server.request_approval(key, 1)
    assert request.snapshot.version == 1
    assert request.snapshot.digest == sha(
        canonical(request.snapshot.order.model_dump(mode="json"))
    )
