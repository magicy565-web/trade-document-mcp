import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from trade_document.approval import Review, message
from trade_document.storage import canonical
from test_artifacts import template_bytes


def test_real_stdio(order, tmp_path):
    async def run():
        key = Ed25519PrivateKey.generate()
        env = {
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "TRADE_DOC_REVIEWERS": json.dumps(
                {
                    "fixture-reviewer": base64.b64encode(
                        key.public_key().public_bytes_raw()
                    ).decode()
                }
            ),
        }
        second = Ed25519PrivateKey.generate()

        def public(k):
            return base64.b64encode(k.public_key().public_bytes_raw()).decode()

        env.update(
            TRADE_RULE_REVIEWERS=json.dumps({"qa": public(key), "qa2": public(second)}),
            TRADE_TEMPLATE_REVIEWERS=json.dumps({"qa": public(key)}),
            TRADE_FINANCE_VERIFIERS=json.dumps({"qa": public(key)}),
            TRADE_FINANCE_AUTHORIZERS=json.dumps({"qa2": public(second)}),
        )

        def signed(data, k=key, who="qa"):
            return {
                "reviewer": who,
                "signature": base64.b64encode(k.sign(canonical(data))).decode(),
            }

        params = StdioServerParameters(
            command=sys.executable, args=["-m", "trade_document.server"], env=env
        )
        async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
            await client.initialize()
            schema = (await client.list_tools()).tools
            assert len(schema) >= 18 and all(t.outputSchema for t in schema)

            successful = set()

            async def call(name, args, error=False):
                result = await client.call_tool(name, args)
                assert result.isError == error, result.content
                if not error:
                    successful.add(name)
                return result.structuredContent

            await call(
                "register_template",
                {
                    "name": "Fixture",
                    "xlsx_base64": base64.b64encode(template_bytes()).decode(),
                },
            )
            await call("list_templates", {"approve": True}, True)
            await call("list_templates", {})
            await call(
                "extract_order_information",
                {
                    "sources": [
                        {
                            "kind": "chat",
                            "name": "brief",
                            "text": "buyer: Example Retail Lab (fictional)",
                        }
                    ]
                },
            )
            order_data = order.model_dump(mode="json")
            s = await call("create_order_draft", {"order": order_data})
            oid = {"order_id": s["order_id"]}
            rev = {**oid, "expected_version": 1}
            await call("get_order_draft", oid)
            assert (await call("calculate_order", oid))["total"] == "68.50"
            assert (await call("validate_order", oid))["valid"]
            await call("request_approval", rev, True)
            await call("preview_document", rev)
            req = Review.model_validate(await call("request_approval", rev))

            def issuance(reviewer, signature):
                return {
                    "request_id": req.request_id,
                    "proof": {
                        "reviewer": reviewer,
                        "signature": base64.b64encode(signature).decode(),
                    },
                }

            await call("generate_document", issuance("unknown", b"x"), True)
            await call("generate_document", issuance("fixture-reviewer", b"x"), True)
            valid = issuance(
                "fixture-reviewer", key.sign(message(req, "fixture-reviewer"))
            )
            a = await call("generate_document", valid)
            assert (await call("audit_document", {"artifact_id": a["artifact_id"]}))[
                "passed"
            ]
            assert (await call("generate_document", valid))["artifact_id"] == a[
                "artifact_id"
            ]
            await call(
                "get_file_download",
                {"artifact_id": a["artifact_id"], "file": "document.pdf"},
            )
            for tool in ("visual_audit", "compare_template_output"):
                await call(tool, {"artifact_id": a["artifact_id"]})
            await call("get_service_status", {})
            await call(
                "convert_measure",
                {"value": {"amount": "2", "unit": "ft"}, "to_unit": "m"},
            )
            await call("list_jurisdiction_profiles", {})
            await call("get_source_reference", {"source_id": "US-ITA-PI"})
            await call("search_knowledge", {"query": "HMRC"})
            for tool in ("resolve_document_requirements", "validate_jurisdiction"):
                await call(
                    tool,
                    {"context": {"destination": "JP", "purpose": "customs_support"}},
                )
            raw = {"xlsx_base64": base64.b64encode(template_bytes()).decode()}
            await call("inspect_template", raw)
            mapping = await call("propose_template_mapping", raw)
            registered = await call(
                "confirm_template_mapping",
                {**raw, "mapping": mapping, "proof": signed(mapping)},
            )
            await call("validate_template", {"template_id": registered["template_id"]})
            finance = {
                "purpose": "trade.beneficiary.v1",
                "reference": "qa",
                "version": 1,
                "instructions": "Fictional settlement reference",
                "verification_record": "Synthetic review",
                "status": "active",
            }
            await call(
                "change_beneficiary",
                {
                    "change": finance,
                    "verifier": signed(finance),
                    "authorizer": signed(finance, second, "qa2"),
                },
            )
            rule = {
                "purpose": "trade.rule.v1",
                "rule_id": "fixture.rule",
                "version": 1,
                "region": "US",
                "kinds": ["standard-pi"],
                "required_field": "valid_until",
                "source_id": "US-ITA-PI",
                "locator": "Fixture section",
                "interpretation": "QA fixture only",
                "resolution": "Add validity",
                "effective_from": "2020-01-01",
                "effective_through": "2099-01-01",
                "state": "active",
            }
            await call(
                "register_reviewed_rule",
                {
                    "rule": rule,
                    "first": signed(rule),
                    "second": signed(rule, second, "qa2"),
                },
            )
            await call("get_rule_evidence", {"rule_id": rule["rule_id"]})
            await call("draft_sales_contract", {**oid, "version": 1})
            batch = {
                "number": "QA-BATCH",
                "dispatch_date": "2026-12-01",
                "consignee": "Example lab",
                "freight": "2",
                "fees": "0",
                "discount": "0",
                "source": "Synthetic warehouse advice",
                "boxes": [
                    {
                        "mark": "C1",
                        "net_kg": "1",
                        "gross_kg": "2",
                        "volume_m3": "0.2",
                        "contents": [
                            {
                                "sku": "W-101",
                                "unit": "pairs",
                                "quantity": "1",
                                "origin": "CN",
                            }
                        ],
                    }
                ],
            }
            shipment = await call("create_shipment", {**rev, "shipment": batch})
            sid = {"shipment_id": shipment["shipment_id"]}
            shipment = await call(
                "revise_shipment", {**sid, "expected_version": 1, "shipment": batch}
            )
            sv = {**sid, "version": 2}
            for tool in (
                "validate_shipment",
                "prepare_customs_support",
                "draft_shipping_instruction",
            ):
                await call(tool, sv)
            pack = await call("preview_shipment", {**sid, "expected_version": 2})
            await call("get_shipment_preview", {"challenge": pack["challenge"]})
            await call(
                "export_document_bundle",
                {"packet": pack, "proof": signed(pack, key, "fixture-reviewer")},
            )
            await call("cross_check_documents", sv)
            await call(
                "check_credit_terms",
                {
                    **sv,
                    "terms": {
                        "reference": "QA-LC",
                        "currency": "USD",
                        "maximum_amount": "100",
                        "latest_shipment": "2026-12-31",
                        "consignee": "Example lab",
                        "required_documents": ["Packing List"],
                    },
                },
            )
            adjustment = {
                "purpose": "shipment.adjustment.v1",
                **sv,
                "revision_digest": shipment["digest"],
                "reference": "QA-return",
                "reason": "Fixture receipt",
                "action": "received_return",
                "quantities": {"W-101": "1"},
            }
            await call(
                "adjust_shipment",
                {
                    "adjustment": adjustment,
                    "proof": signed(adjustment, key, "fixture-reviewer"),
                },
            )
            await call(
                "update_order_draft",
                {**rev, "order": {**order_data, "freight": "19.00"}},
            )
            await call("generate_document", valid, True)
            await call("update_order_draft", {**rev, "order": order_data}, True)

            assert successful == {t.name for t in schema}

    asyncio.run(run())
