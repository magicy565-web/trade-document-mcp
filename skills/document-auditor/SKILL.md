---
name: document-auditor
description: Audit archived document pairs against the signed revision and report release discrepancies.
---

# document-auditor

Audit archived document pairs against the signed revision and report release discrepancies.

## Operating procedure

Resolve artifact ID and immutable revision. Verify both file hashes, inspect Excel formulas and cached numbers, then read PDF party details and line sequences. Escalate discrepancies and retain the artifact ID.

## Field specification

Use artifact_id, order_id, version, digest, currency, line values, totals and audit findings. A draft must carry the draft title. Current draft data may differ from the archived revision.

## Review rules

Check title, buyer/seller, payment and delivery terms, sample policy, line amounts, fees, final currency and total. Inspect product photos and pagination visually before customer delivery.

## Exception handling

If bytes or figures change, quarantine the working copy. Correct the source order, obtain a new signature and issue a fresh pair.

## Calibration case

Editing an archived workbook after issuance causes hash verification to fail. An unchanged archived prior revision remains independently auditable.

## Executable check

From the installed repository run `python -m pytest -q tests/test_artifacts.py::test_visual_types`. Use the fictional order in `fixtures/sample.json` for practice.

## International and enterprise workflow

Compare print area, all cached amounts and formulas, preview digests, signed revision, permitted beneficiary and rule pack. For split shipments cross-check the carton ledger and the actual invoice and packing-list bundle. Confirm reviewed company appendices appear in the print PDF.

## Counterexample

An unchanged order digest cannot authorize issuance after the signed preview changed. A revised rule pack requires a new preview.

Run `python -m pytest -q tests/test_recovery.py` to exercise this workflow.
