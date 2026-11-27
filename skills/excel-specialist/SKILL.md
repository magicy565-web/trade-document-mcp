---
name: excel-specialist
description: Register a compatible company workbook and produce an editable multi-SKU document.
---

# excel-specialist

Register a compatible company workbook and produce an editable multi-SKU document.

## Operating procedure

Inspect the worksheet and locate title, details and item anchors. Register the blank layout, record its hash in the order, preview, and reopen the workbook in formula and cached-value modes. Check page breaks at actual print scale.

## Field specification

The six columns are SKU, description/specification, quantity, unit, unit price and amount. Store source strings as literal text, charges as numeric values and line totals as formulas. Page width is one A4 sheet.

## Review rules

Check each line extension, subtotal, additional charge and total. Verify visible merged metadata and the last SKU on a multipage workbook.

## Exception handling

Return the affected anchor or unsupported workbook feature. Ask for a compatible blank layout before applying enterprise branding.

## Calibration case

A2, A4 and A20 in an empty six-column workbook map the title, party details and line table. With two lines, the final amount is in F27.

## Executable check

From the installed repository run `python -m pytest -q tests/test_artifacts.py::test_enterprise_layout`. Use the fictional order in `fixtures/sample.json` for practice.
