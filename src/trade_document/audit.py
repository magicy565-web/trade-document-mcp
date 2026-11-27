import re
from decimal import Decimal, ROUND_HALF_UP
from openpyxl import load_workbook
from pypdf import PdfReader
from .types import minor_units
from .model import Model
from .locale import label as localize
from .render import extra_details


class Audit(Model):
    passed: bool
    findings: list[str]


def compact(v):
    return re.sub(r"\s+", "", str(v))


def inspect_files(o, workbook, pdf, title, enterprise=False):
    findings = []
    ws = load_workbook(workbook, data_only=True).active
    formula = load_workbook(workbook, data_only=False).active
    text = compact(" ".join(p.extract_text() or "" for p in PdfReader(pdf).pages))
    values = {
        str(row[0].value): row[1].value
        for row in ws.iter_rows()
        if row[0].value is not None
    }
    if compact(title) not in text or title not in values:
        findings.append("Document title mismatch")
    for k, label in [
        ("seller", "Seller"),
        ("buyer", "Buyer"),
        ("number", "Document no."),
        ("issue_date", "Issue date"),
        ("currency", "Currency"),
        ("payment", "Payment terms"),
        ("delivery", "Delivery terms"),
        ("freight_payer", "Freight payable by"),
        ("bank", "Payment instructions"),
        ("customization", "Customization"),
        ("sample_policy", "Sample policy"),
        ("sample_credit", "Credit toward bulk order"),
    ]:
        label = localize(o, label)
        v = getattr(o, k)
        if v is not None and (
            str(values.get(label)) != str(v)
            or (not enterprise and compact(label + str(v)) not in text)
        ):
            findings.append(f"{label} mismatch")
    for label, v in extra_details(o):
        label = localize(o, label)
        if values.get(label) != v or (
            not enterprise and compact(label + v) not in text
        ):
            findings.append(label + " mismatch")
    start = next(row[0].row for row in ws.iter_rows() if row[0].value == "SKU") + 1
    q = Decimal(1).scaleb(-minor_units(o.currency))
    subtotal = Decimal(0)
    for idx, i in enumerate(o.items, start):
        line = (i.unit_price * i.quantity).quantize(q, ROUND_HALF_UP)
        subtotal += line
        actual = [ws.cell(idx, c).value for c in range(1, 7)]
        expected = [
            i.sku,
            "\n".join(filter(None, [i.description, i.specification])),
            i.quantity,
            i.unit,
            i.unit_price,
            line,
        ]
        row_text = compact("".join(str(v) for v in expected))
        if not enterprise and row_text not in text:
            findings.append(
                f"PDF line {idx - start + 1} differs from approved sequence"
            )
        for col, (a, e) in enumerate(zip(actual, expected), 1):
            ok = (
                Decimal(str(a)) == e
                if isinstance(e, Decimal) and a is not None
                else a == e
            )
            if not ok or (not enterprise and compact(e) not in text):
                findings.append(f"Line {idx - start + 1} column {col} mismatch")
        if (
            formula.cell(idx, 6).value
            != f"=ROUND(C{idx}*E{idx},{minor_units(o.currency)})"
        ):
            findings.append("Unexpected line formula")
    total = (
        subtotal
        + o.sample_fee
        + o.freight
        + (o.insurance or 0)
        + (o.tooling_fee or 0)
        - o.discount
    ).quantize(q)
    for n, (label, v) in enumerate(
        [
            ("Subtotal", subtotal),
            ("Sample fee", o.sample_fee),
            ("Freight", o.freight),
            *(
                (k, v)
                for k, v in [("Insurance", o.insurance), ("Tooling fee", o.tooling_fee)]
                if v is not None
            ),
            ("Discount", o.discount),
            (localize(o, "Total") + " " + o.currency, total),
        ],
        start + len(o.items),
    ):
        label = localize(o, label)
        if (
            ws.cell(n, 5).value != label
            or Decimal(str(ws.cell(n, 6).value)) != v
            or (not enterprise and compact(label + str(v)) not in text)
        ):
            findings.append(f"{label} mismatch")
    end = start + len(o.items) - 1
    if formula.cell(end + 1, 6).value != f"=SUM(F{start}:F{end})" or formula.cell(
        n, 6
    ).value not in {
        f"=SUM(F{end + 1}:F{n - 2})-F{n - 1}",
        f"=F{end + 1}+F{end + 2}+F{end + 3}-F{end + 4}" if n == end + 5 else "",
    }:
        findings.append("Summary formulas mismatch")
    if len(formula._images) < int(bool(o.logo)) + sum(
        int(bool(i.image)) + len(i.images) for i in o.items
    ):
        findings.append("Missing workbook image")
    if enterprise:
        from .print_layout import verify_printed

        findings.extend(verify_printed(workbook, pdf))
        # Check the rendered payable amount in the actual print output.
        rendered_total = format(total, f",.{minor_units(o.currency)}f")
        if compact(rendered_total) not in text:
            findings.append("Printed total missing")
    return Audit(passed=not findings, findings=findings)
