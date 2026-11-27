# Trade Document MCP

Human-in-the-loop trade documentation for professional proforma invoices and sample orders.

Initial development: draft → validate → human approval → document generation → audit.

Do not store real customer records, payment instructions, credentials or generated documents in this public repository.

## Run V0.1 locally

Python 3.11 or 3.12. Install with `python -m pip install -e '.[test]'`. Start `trade-doc-mcp` as a stdio server. Configure the host with an absolute executable and a private absolute data directory.

```json
{"mcpServers":{"trade-documents":{"command":"/path/to/venv/bin/trade-doc-mcp","env":{"TRADE_DOC_HOME":"/private/trade-doc-data","TRADE_DOC_REVIEWERS":"{}"}}}}
```

An empty reviewer registry permits drafts and previews. See [operator instructions](docs/operations.md) to enable signing. The V0.1 service runs per trusted workspace. Keep the store and server configuration inaccessible to untrusted agents. Network transport and tenant isolation require additional deployment work.

## Order workflow

1. Call `extract_order_information` with named chat, quote or product sources. Accepted inputs include text, labeled lines, SKU CSV, simple XLSX tables and PDFs with a text layer. For free prose, the host can supply field candidates with verbatim source lines. Review unmatched text and conflicts.
2. Call `create_order_draft` with a document kind and the same sources/highlights to apply unambiguous values. Alternatively provide a reviewed structured order. `update_order_draft` accepts a full replacement and an expected version. `get_order_draft` accepts a historical version.
3. Call `calculate_order`, `validate_order`, then `preview_document`. Unknown fees remain unknown. Drafts need calculable amounts for file previews.
4. Send the structured output of `request_approval` and matching previews to the assigned reviewer through your existing internal process. The reviewer signs locally. `generate_document` accepts the returned proof. It verifies the current revision inside the database transaction and audits both files before returning local paths. Use `audit_document` for later integrity checks. External delivery is manual.

Use `list_templates` and `register_template` for built-in types and bounded enterprise layouts. See [template contract](docs/templates.md).
Find the five operator playbooks in [skills](skills).

## Verify and reproduce the synthetic examples

```bash
python -m pytest -q
python tools/evaluate.py
python tools/demo.py /tmp/trade-doc-examples
```

The demo uses an ephemeral fixture signer and produces editable sample PI and sample order workbooks and PDFs. It reads only the checked-in fictional fixture. All artifacts stay outside git. The cohort evaluation includes incomplete and conflicting intakes in its denominator. It uses simulated reviewer signatures. Real first-pass acceptance, field accuracy and workload require independent professional adjudication.

## Development candidate through V0.5

See [enterprise deployment and signing](docs/enterprise.md) for authenticated HTTP, tenant isolation, ERP idempotency, signed template/rule review, shipping documents, backups and limitations. The five-stage [acceptance roadmap](docs/roadmap-v0.5.md) tracks requirements separately from the [engineering verification record](docs/verification-v05.md). Use the locked dependency install in the enterprise guide to reproduce CI.
