import re
from decimal import Decimal, ROUND_HALF_UP
from openpyxl import load_workbook
from pypdf import PdfReader
from .model import Model


class Audit(Model):
    passed: bool
    findings: list[str]


def compact(v):
    return re.sub(r"\s+", "", str(v))


def inspect_files(o, workbook, pdf, title):
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
        v = getattr(o, k)
        if v is not None and (
            str(values.get(label)) != str(v) or compact(label + str(v)) not in text
        ):
            findings.append(f"{label} mismatch")
    start = next(row[0].row for row in ws.iter_rows() if row[0].value == "SKU") + 1
    q = Decimal(1 if o.currency == "JPY" else "0.01")
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
        if row_text not in text:
            findings.append(
                f"PDF line {idx - start + 1} differs from approved sequence"
            )
        for col, (a, e) in enumerate(zip(actual, expected), 1):
            ok = (
                Decimal(str(a)) == e
                if isinstance(e, Decimal) and a is not None
                else a == e
            )
            if not ok or compact(e) not in text:
                findings.append(f"Line {idx - start + 1} column {col} mismatch")
        if (
            formula.cell(idx, 6).value
            != f"=ROUND(C{idx}*E{idx},{0 if o.currency == 'JPY' else 2})"
        ):
            findings.append("Unexpected line formula")
    total = (subtotal + o.sample_fee + o.freight - o.discount).quantize(q)
    for n, (label, v) in enumerate(
        [
            ("Subtotal", subtotal),
            ("Sample fee", o.sample_fee),
            ("Freight", o.freight),
            ("Discount", o.discount),
            ("Total " + o.currency, total),
        ],
        start + len(o.items),
    ):
        if (
            ws.cell(n, 5).value != label
            or Decimal(str(ws.cell(n, 6).value)) != v
            or compact(label + str(v)) not in text
        ):
            findings.append(f"{label} mismatch")
    return Audit(passed=not findings, findings=findings)
