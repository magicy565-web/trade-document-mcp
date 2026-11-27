"""100 synthetic intake scenarios; every intake remains in the metrics denominator."""

import json
import os
import tempfile
from decimal import Decimal
from demo import FIXTURE, configure_fixture_reviewer, sign
from trade_document import server
from trade_document.model import Order


def main():
    results = dict(
        intakes=0,
        generated_after_signature=0,
        commercial_signatures=0,
        extra_clarifications=0,
        wrong_releases=0,
        false_blocks=0,
        incorrect_totals=0,
        unauthorized_releases=0,
    )
    with tempfile.TemporaryDirectory() as temp:
        os.environ["TRADE_DOC_HOME"] = temp
        key = configure_fixture_reviewer()
        for number in range(100):
            o = Order.model_validate_json(FIXTURE.read_bytes())
            o.number = f"QA-{number:03}"
            o.items[0].quantity = Decimal(number + 1)
            o.kind = ("sample-pi", "sample-order")[number % 2]
            scenario = number % 10
            ready = scenario < 7
            if scenario == 7:
                o.payment = None
            if scenario == 8:
                o.sample_policy = "free"
            if scenario == 9:
                o.unresolved = ["Conflicting dispatch dates"]
            results["intakes"] += 1
            s = server.create_order_draft(o)
            server.preview_document(s.order_id, 1)
            try:
                req = server.request_approval(s.order_id, 1)
            except ValueError:
                results["extra_clarifications"] += 1
                results["false_blocks"] += int(ready)
                continue
            proof = sign(req, key)
            try:
                server.generate_document(
                    req.request_id,
                    proof.model_copy(update={"reviewer": "unregistered"}),
                )
                results["unauthorized_releases"] += 1
            except ValueError:
                pass
            results["commercial_signatures"] += 1
            a = server.generate_document(req.request_id, proof)
            results["generated_after_signature"] += 1
            results["wrong_releases"] += int(
                not ready or not server.audit_document(a.artifact_id).passed
            )
            expected = Decimal("15.25") * (number + 1) + 38
            results["incorrect_totals"] += int(
                server.calculate_order(s.order_id).total != expected
            )
    print(json.dumps(results, indent=2))
    assert results == dict(
        intakes=100,
        generated_after_signature=70,
        commercial_signatures=70,
        extra_clarifications=30,
        wrong_releases=0,
        false_blocks=0,
        incorrect_totals=0,
        unauthorized_releases=0,
    )


if __name__ == "__main__":
    main()
