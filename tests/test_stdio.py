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
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "trade_document.server"], env=env
        )
        async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
            await client.initialize()
            schema = (await client.list_tools()).tools
            assert len(schema) == 12 and all(t.outputSchema for t in schema)

            async def call(name, args, error=False):
                result = await client.call_tool(name, args)
                assert result.isError == error, result.content
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
                "update_order_draft",
                {**rev, "order": {**order_data, "freight": "19.00"}},
            )
            await call("generate_document", valid, True)
            await call("update_order_draft", {**rev, "order": order_data}, True)

    asyncio.run(run())
