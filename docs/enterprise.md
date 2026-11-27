# Running the V0.5 development candidate

Install Python 3.11 or 3.12, LibreOffice Calc for company-template print conversion, and the locked Python environment:

```sh
python -m pip install -c requirements.lock -e '.[test]'
python -m pytest -q
python tools/evaluate.py
python tools/release_demo.py /tmp/fictional-trade-pack
```

The stdio executable is `trade-doc-mcp`. Its local store belongs to one trusted workspace. For remote MCP start `trade-doc-http`, which binds loopback port 8000. Terminate TLS at the organization's gateway and forward the Authorization header. Set the gateway's request-body limit, timeout and origin allowlist. Use one HTTP worker per service instance for the in-process rate limiter. Make the public host match the SDK transport-security configuration or forward to the loopback upstream with its expected Host header. The gateway must not expose the filesystem or signing workstation.

## Identity and tenant configuration

Provision random client credentials in the company's secret manager. Configure `TRADE_HTTP_IDENTITIES` as a JSON object keyed by each token's lowercase SHA-256 digest. Each value has `tenant`, `actor`, `role` (viewer, editor or admin), and Unix-seconds `expires`. Send the original token via `Authorization: Bearer …`. Tenant is server-selected. Each tenant has a separate SQLite database, file archive and audit log in TRADE_DOC_HOME/tenants. A viewer can inspect and download. An editor can prepare orders and shipments. Template confirmation and reviewed-rule registration require administrator access and independent cryptographic proofs. The signer registry uses named public keys. The reviewer keeps the private key outside the agent environment.

`TRADE_TENANT_POLICIES` maps tenant IDs to objects with these optional registries:

| Key | Value |
|---|---|
| TRADE_DOC_REVIEWERS | Reviewer ID → base64 raw Ed25519 public key |
| TRADE_TEMPLATE_REVIEWERS | Template reviewer ID → public key |
| TRADE_RULE_REVIEWERS | Independent specialist ID → public key |
| TRADE_DOC_BENEFICIARIES | Preverified corporate beneficiary reference → exact approved instructions |

Local stdio reads top-level environment variables with the same names. Provision beneficiary changes via the organization's separate finance verification and privileged configuration deployment. Keep the configuration, local archive, snapshots and downloads private. Revoke a bearer by removing its digest and restarting. Reviewers are evaluated at issuance. An expired packet requires a fresh challenge.

## Integrate an order from an ERP

Create a draft with the `Order` JSON schema advertised by MCP. Use the external order reference as `purchase_order`, the ERP revision as part of `idempotency_key`, and `sources` or source highlights for traceability. A retry returns the original draft revision. A different payload with the same key fails. Apply amendments through `update_order_draft` with its expected version. `tests/test_remote.py` is an executable simulated client using a real HTTP socket. Reference retrieval and unit conversions are independent tools.

For formal issue, download the preview files with `get_file_download`, obtain the review packet, and pass both to the reviewer. `GET /reviews/{request_id}` renders a review page. `POST` on the same path accepts the signed proof as JSON from the matching authenticated actor. The MCP issue tool accepts a detached proof as well. Use `trade-doc-sign packet.json reviewer-id encrypted.pem preview-directory` for the hash-checking signing flow. For template mapping put the original in the review directory as original.xlsx. For reviewed regional rules, two distinct public keys must sign the same scoped rule, source locator and effective period. No jurisdiction rules ship preapproved.

## Ship actual goods

A current issued order is required. Submit actual carton contents, origins, units, net/gross weights, volumes, consignee and batch charges via `create_shipment`. Draft batches reserve quantities. Use `revise_shipment` to amend a draft. Generate a preview with `preview_shipment`; get its four files with `get_shipment_preview` or `get_file_download` using the challenge ID. Sign that packet to issue both commercial invoice and packing list through `export_document_bundle`. Use the shipment ID for issued file downloads. Use a signed `adjust_shipment` to cancel an unissued batch or record an evidenced return against an issued shipment. The issued files retain their original quantities.

Customs support, sales contract, shipping instruction, origin application and CN pre-entry outputs are review worksheets. The valuation field is independent of the commercial payable amount. Destination evidence is advisory until a signed reviewed rule is registered. These tools have no filing or payment transport.

## Store, recovery, retention and monitoring

`get_file_download` returns a tenant-authenticated relative URL with a 180-second lifetime. `get_service_status` gives local counters. Inspect tenant SQLite events for actor, tool, timestamp and outcome. The program does not log tool arguments. Set TRADE_HTTP_RATE for per-credential calls per minute.

Local archives are the default. Optional install `.[s3]` and set TRADE_ARCHIVE_BUCKET plus an optional TRADE_ARCHIVE_ENDPOINT to enable a checksum-verified second copy of issued files. Use IAM/workload credentials and bucket policies set by the operator. Object keys contain the tenant and SHA-256 digest. Failed archive writes roll back issuance, so a client can retry the signed request within its validity period. Partial remote writes are unreferenced content-addressed objects. Configure versioning, encryption, retention and lifecycle policies on the bucket. Production IAM, KMS, backups and live cloud connectivity need deployment verification.

```sh
trade-doc-store backup /private/store/tenants/example /private/backups/example-snapshot
trade-doc-store restore /private/backups/example-snapshot /private/recovery/example
```

Backup holds the tenant write lock while SQLite and the referenced file archive are copied. Restore verifies the manifest, invalidates download tokens and relocates shipment file paths. Use a new destination. Stop service before switching the configured store root. Retain the prior code and verified backup together for rollback. Older PI revisions are decoded by the current schema; pre-binding approvals require a fresh preview. Enterprise deletion and legal retention are operator decisions: inventory the tenant's SQLite store, files, replicas, snapshots and encryption keys before the approved deletion date. Do not remove individual files from a live issued bundle.

## Independent acceptance

`tools/blind_evaluation.py` takes private adjudicated JSONL, checks group overlap across company, source and template family, and separates real and synthetic metrics. A zero denominator is reported as null. It reports the first-pass Wilson interval and the rates of clarification, automatic completion, wrong release and format rework. Protect the adjudication manifest. Its rights record and reviewer IDs refer to external records that the evaluating organization must verify. The repository contains no professional blind dataset.

Versions here are development candidates. Verify real tenant onboarding, gateway configuration, archive recovery, independent region review and real trade acceptance before production release.

A separate finance workflow is available via change_beneficiary. Configure TRADE_FINANCE_VERIFIERS and TRADE_FINANCE_AUTHORIZERS in tenant policy with distinct reviewer identities and public keys. Both sign the same versioned change and verification-record reference. An administrator submits the proofs. Each change or revocation supersedes the preceding version; re-preview affected PI drafts. The finance verifier performs the external verification and retains supporting evidence.
