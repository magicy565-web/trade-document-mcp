---
name: sample-order-specialist
description: Draft a charged or free sample order, including customization, freight and future credit.
---

# sample-order-specialist

Draft a charged or free sample order, including customization, freight and future credit.

## Operating procedure

Identify the sampled variants and size. Separate product charges, one-time sample fee and freight. Capture whether and under what condition the customer earns bulk credit. Confirm dispatch wording before preview.

## Field specification

sample_policy accepts free or charged. customization describes the physical change. sample_credit records explicit conditions or an explicit no-credit decision. freight_payer names the responsible party.

## Review rules

A free sample has zero product charges and zero sample fee. Freight may still be payable. A charged sample needs a positive product charge or sample fee.

## Exception handling

When the customer requests free samples or fee credit and the seller has not accepted, keep policy or credit unresolved. Route to the seller.

## Calibration case

A free pair with USD 12 agreed freight produces a USD 12 total and retains the named freight payer.

## Executable check

From the installed repository run `python -m pytest -q tests/test_rules.py::test_free_still_pays_shipping`. Use the fictional order in `fixtures/sample.json` for practice.
