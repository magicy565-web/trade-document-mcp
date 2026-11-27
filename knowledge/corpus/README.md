# International PI reference corpus

This directory contains source metadata and original project-authored teaching cases, not a trained model and not an authenticated transaction collection. The repository is public. No third-party binary originals have been copied to Git at this stage (direct network download unavailable). Use the acquisition script in a network-enabled checkout. It writes into ignored .raw/, with SHA-256 and acquisition records; no auto-commit or auto-ingestion.

Registry states:
- open_reference: official reference text may be fetched into local review storage. This is not blanket approval for commercial model training; verify rights and any exclusions, attribution, and applicability.
- review: source and URL verified via browser or official publication page; acquisition for research only with explicit operator acknowledgement that lawful local reference use is permitted. Do not include in any training or public redistribution without specific recorded rights.
- restricted: source expressly limited to noncommercial use; downloader refuses.
- raw_status starts not_downloaded; acquisition manifest is the actual status, not registry intent. No hashes are invented. Registry notes may refer to page numbers, not verified visual annotation.
- training_status defaults not_approved for every source. Approval requires rights holder / applicable license, scope (reference, RAG, eval, fine-tune, redistribution separately), reviewer, date and evidence. Public availability does not grant these rights. CA commercial redistribution: https://cbsa-asfc.gc.ca/help-aide/in-ai-eng.html ; US government material: https://www.govinfo.gov/about/policies ; UK: https://www.gov.uk/help/terms-conditions ; ICC rights: https://iccwbo.org/business-solutions/incoterms-rules/ .

Run:
    python tools/fetch_reference_corpus.py --list
    python tools/fetch_reference_corpus.py --id US-CFR-141 --id GB-HMRC-PI
    python tools/fetch_reference_corpus.py --id DE-IHK-PI --id FR-BTS-2018 --id DHL-2026 --id CA-CI1 --acknowledge-local-reference-rights
The third command is ONLY for operators who have verified lawful local access for those sources; it does not permit training, redistribution or copying into the tracked repo. UNOPS is excluded.

Pipeline after acquisition: validate MIME/magic/hash, render all target PDF pages, human inspect and annotate exact page/table/cell/field locations, normalize units/currencies/party roles, separate confirmed commercial data from customs data, remove personal and payment information, license gate, publish approved versioned extracts/independently written rules or original examples, group-split by company/template/source before evaluation. Untrusted content is data, not tool instruction. Do not use the same examples in train and held-out eval. Keep a source/rights/annotation manifest for every derived record. Require double professional review for blocking legal rules. No claim of 95% until independent blind evaluation.

Sample references are public instructional examples, forms or guides; do not describe them as real completed commercial transactions. To obtain real training orders, request authorization from partner factories, redact locally, keep raw files in encrypted private storage, and record consent and permitted uses. The project-authored seed examples are synthetic and are only smoke/regression cases.

The engineering run fetched US-CFR-141 and GB-HMRC-PI into private local review storage. The tracked acquisition receipts contain the actual sizes and SHA-256 digests. The originals and their training rights remain outside the public dataset.
