from trade_document.knowledge import requirements, source, search, Context


def test_unknown_destination_and_intent():
    assert requirements(Context(destination="NZ")).review_only
    r = requirements(Context(destination="US", purpose="customs_substitute"))
    assert not r.direct_issue and any(f.source_id == "US-CFR-141" for f in r.findings)


def test_paid_is_separate_from_declared():
    r = requirements(Context(destination="AU", purpose="customs_support"))
    assert any(f.rule_id == "product.valuation" for f in r.findings)
    assert not any(
        f.rule_id == "product.valuation"
        for f in requirements(Context(destination="DE")).findings
    )
    assert source("GB-HMRC-PI").training_status == "not_approved"
    assert search("HMRC").sources


def test_double_review_and_pack_invalidation(order, monkeypatch):
    from trade_document import server
    from trade_document.rules import Rule, register_reviewed_rule
    from trade_document.approval import Proof
    from trade_document.storage import canonical
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64, json, pytest

    order.destination = "US"
    s = server.create_order_draft(order)
    server.preview_document(s.order_id, 1)
    r = Rule(
        rule_id="fixture.validity",
        version=1,
        region="US",
        kinds=["sample-pi"],
        required_field="valid_until",
        source_id="US-ITA-PI",
        locator="Synthetic review fixture",
        interpretation="Test rule requiring validity",
        resolution="Confirm valid until",
        effective_from="2020-01-01",
        effective_through="2099-01-01",
        state="active",
    )
    keys = [Ed25519PrivateKey.generate() for _ in range(2)]
    monkeypatch.setenv(
        "TRADE_RULE_REVIEWERS",
        json.dumps(
            {
                str(i): base64.b64encode(k.public_key().public_bytes_raw()).decode()
                for i, k in enumerate(keys)
            }
        ),
    )
    proofs = [
        Proof(
            reviewer=str(i),
            signature=base64.b64encode(
                k.sign(canonical(r.model_dump(mode="json")))
            ).decode(),
        )
        for i, k in enumerate(keys)
    ]
    with pytest.raises(ValueError):
        register_reviewed_rule(r, proofs[0], proofs[0])
    register_reviewed_rule(r, *proofs)
    assert not server.validate_order(s.order_id).valid
    with pytest.raises(ValueError):
        server.request_approval(s.order_id, 1)
