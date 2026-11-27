# Review and archive operations

The server operator provisions an explicit reviewer ID to raw Ed25519 public-key mapping in the environment. Generate the private key on the reviewer's own account or machine. Use an encrypted PEM and retain the passphrase there.

```bash
openssl genpkey -algorithm ED25519 -aes-256-cbc -out reviewer.pem
openssl pkey -in reviewer.pem -pubout -out reviewer-public.pem
python -c 'import sys,base64; from cryptography.hazmat.primitives.serialization import load_pem_public_key; print(base64.b64encode(load_pem_public_key(open(sys.argv[1],"rb").read()).public_bytes_raw()).decode())' reviewer-public.pem
```

Set TRADE_DOC_REVIEWERS to a JSON object mapping each named human reviewer to that base64 public key. Protect configuration and SQLite files with OS permissions. Give the ordinary MCP host tool access only. A process with unrestricted access to the server account or the human signing key is outside this trust boundary. Remove a reviewer from configuration and restart the process to revoke future signing authority.

Save the structured review packet locally and inspect both matching previews. Compare the beneficiary with an independently verified beneficiary record before authorizing payment instructions. Reconcile amounts, sample policy, shipping obligations, dispatch promises and the bulk credit agreement against the original sources. Run:

```bash
trade-doc-review review.json reviewer-id reviewer.pem --preview-dir /private/review-files
```

The CLI checks both preview file hashes and the packet expiry, recomputes the content digest, shows the order and totals, requires entry of the document number and unlocks the PEM interactively. Return only the final proof object. The signature covers purpose, challenge, order, revision, content digest and reviewer identity. The server validates it on each call. New revisions require another preview and signature. Repeated issue for the same signed order revision reuses the archived pair. Existing unsigned drafts can be reopened after the upgrade. Produce a fresh preview and approval packet for earlier revisions awaiting signature. Edited XLSX files are working copies and require a new order revision for formal reissue.

SQLite retains original snapshots, timestamps, requests, reviewer identity, signatures and artifact hashes. Back up the private data directory as a unit. Archive paths are local to the server. The released files do not imply a payment, dispatch or external delivery.


## Verified beneficiary changes

The operator can supply initial entries in TRADE_DOC_BENEFICIARIES after confirming the beneficiary outside the application. Use separate finance verification and authorization registries for later changes. Set TRADE_FINANCE_VERIFIERS and TRADE_FINANCE_AUTHORIZERS to JSON objects mapping named reviewers to base64 raw Ed25519 public keys. Keep private keys on the respective reviewers’ workstations.

A change packet includes purpose `trade.beneficiary.v1`, reference, version, instructions, verification_record and status. The independent finance verification record refers to confirmed beneficiary details held by the enterprise. Versions start at 1. Use active or revoked status.

```sh
trade-doc-finance sign change.json verifier verifier.pem > verification.json
trade-doc-finance sign change.json approver approver.pem > authorization.json
trade-doc-finance apply change.json verification.json authorization.json
```

Each reviewer examines the change before signing. The operator applies both signed proofs. The finance command requires store access and runs outside the MCP agent. A beneficiary change supersedes prior review packets for that reference. A revoked beneficiary cannot be used for a new issuance.
