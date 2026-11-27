---
name: trade-language-specialist
description: Attribute multilingual trade messages to structured fields without changing business commitments.
---

# trade-language-specialist

Attribute multilingual trade messages to structured fields without changing business commitments.

## Operating procedure

Keep original quotes and line numbers. Map explicit labels and tabular fields first. For narrative prose propose verbatim highlights to the extraction tool. Review unmatched clauses and resolve ambiguous scope with a human.

## Field specification

Source name, source kind, field, value, line and quote identify each observation. Keep conditional words, measurement units, named places and dates in the reviewed English text.

## Review rules

Verify whether “may credit” is conditional, whether a date refers to dispatch or arrival, and whether freight is included. Preserve uncertainty in unresolved issues.

## Exception handling

When translation changes the strength of a commitment, present both readings to the reviewer and block formal issue until resolved.

## Calibration case

“We may credit the fee on a bulk order” describes a possible credit. It does not establish an unconditional credit. Record the quote and request confirmation.

## Executable check

From the installed repository run `python -m pytest -q tests/test_rules.py::test_grounded_chat_into_draft`. Use the fictional order in `fixtures/sample.json` for practice.

## International and enterprise workflow

Select English, German or French labels independently of business wording. Preserve the approved original commitment or its human-reviewed translation. Resolve narrative highlights against the original named source and mark disputes explicitly.

## Counterexample

A translated document heading does not establish a German or French delivery promise. Never promote an unaccepted buyer proposal to a confirmed concession.

Run `python -m pytest -q tests/test_commercial.py` to exercise this workflow.
