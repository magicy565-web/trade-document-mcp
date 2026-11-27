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
