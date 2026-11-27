---
name: pi-specialist
description: Prepare an English proforma invoice from an attributed quotation and confirmed commercial terms.
---

# pi-specialist

Prepare an English proforma invoice from an attributed quotation and confirmed commercial terms.

## Operating procedure

Match seller and buyer legal names to the quotation. Preserve each SKU, unit basis, currency and delivery commitment. Record missing values in the draft. Calculate, reconcile discounts and freight, and preview the chosen layout before requesting signature.

## Field specification

number and issue_date identify the PI. Each quantity is a positive whole unit. unit_price allows four decimals. payment and delivery retain approved wording. bank is optional and requires independent verification if present.

## Review rules

Compare the extended line amounts to the quote. Reconcile the header currency with every price. Require a fresh review after any change.

## Exception handling

If two quotations conflict, attach both source lines, leave the value unresolved and refer the price decision to the reviewer.

## Calibration case

Two pairs at USD 15.25 and one pair at USD 18.00 give USD 48.50 in goods. Adding USD 8 sample fee and USD 12 freight gives USD 68.50.

## Executable check

From the installed repository run `python -m pytest -q tests/test_rules.py::test_rounding_and_fees`. Use the fictional order in `fixtures/sample.json` for practice.

## International and enterprise workflow

Use an agreed term with its place and edition, typed party roles, verified payment beneficiary and exact installment percentages. Compare calculated installments with the total and review both preview hashes before signature.

## Counterexample

12.5 square metres are valid. A copied carton count does not establish the measured area.

Run `python -m pytest -q tests/test_commercial.py` to exercise this workflow.
