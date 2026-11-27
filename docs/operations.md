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
trade-doc-review review.json reviewer-id reviewer.pem
```

The CLI recomputes the content digest, shows the order and totals, requires entry of the document number and unlocks the PEM interactively. Return only the final proof object. The signature covers purpose, challenge, order, revision, content digest and reviewer identity. The server validates it on each call. New revisions require another preview and signature. Repeated issue of the same challenge reuses the archived pair. Edited XLSX files are working copies and require a new order revision for formal reissue.

SQLite retains original snapshots, timestamps, requests, reviewer identity, signatures and artifact hashes. Back up the private data directory as a unit. Archive paths are local to the server. The released files do not imply a payment, dispatch or external delivery.
