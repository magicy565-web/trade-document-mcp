import re
from decimal import Decimal, ROUND_HALF_UP

from openpyxl import load_workbook
from pypdf import PdfReader

from .model import Model, document_totals
from .render import LABELS, extra_details, shown, summary


class Audit(Model):
    passed: bool
    findings: list[str]


def compact(value):
    return re.sub(r"\s+", "", str(value))


def matches(actual, expected):
    if isinstance(expected, Decimal):
        return isinstance(actual, (int, float)) and Decimal(str(actual)) == expected
    return actual == expected


def inspect_files(order, workbook, pdf, title, *, draft=False):
    findings = []
    ws = load_workbook(workbook, data_only=True).active
    formulas = load_workbook(workbook, data_only=False).active
    pages = PdfReader(pdf).pages
    page_text = [page.extract_text() or "" for page in pages]
    text = compact(" ".join(page_text))
    if not page_text or any(not page.strip() for page in page_text):
        findings.append("PDF contains an unreadable page")

    metadata = {}
    header = None
    for row in ws.iter_rows(min_col=1, max_col=2):
        key, value = row
        if key.value == "SKU":
            header = key.row
            break
        if key.value is not None:
            metadata[str(key.value)] = value.value
    if compact(title) not in text or title not in metadata:
        findings.append("Document title mismatch")
    if header is None:
        return Audit(passed=False, findings=[*findings, "Missing SKU header"])

    totals = document_totals(order, draft)
    expected_metadata = [
        (label, str(getattr(order, field)))
        for field, label in LABELS.items()
        if getattr(order, field) is not None
    ]
    for label, value in [*expected_metadata, *extra_details(order, totals)]:
        if str(metadata.get(label)) != value or compact(label + value) not in text:
            findings.append(f"{label} mismatch")

    precision = 0 if order.currency == "JPY" else 2
    quantum = Decimal(1).scaleb(-precision)
    subtotal = Decimal(0)
    start = header + 1
    position = 0
    for row, item in enumerate(order.items, start):
        amount = None
        if totals:
            amount = (item.unit_price * item.quantity).quantize(quantum, ROUND_HALF_UP)
            subtotal += amount
        expected = [
            item.sku,
            "\n".join(item.descriptions()),
            shown(item.quantity),
            shown(item.unit),
            shown(item.unit_price),
            shown(amount),
        ]
        token = compact("".join(map(str, expected)))
        found = text.find(token, position)
        if found < 0:
            findings.append(f"PDF row {row} does not match the order")
        else:
            position = found + len(token)
        for col, value in enumerate(expected, 1):
            if not matches(ws.cell(row, col).value, value):
                findings.append(f"Workbook row {row} column {col} mismatch")
        if (
            totals
            and formulas.cell(row, 6).value != f"=ROUND(C{row}*E{row},{precision})"
        ):
            findings.append(f"Workbook row {row} formula mismatch")

    total = None
    if totals:
        total = (
            subtotal
            + order.sample_fee
            + order.freight
            + (order.insurance or 0)
            + (order.tooling_fee or 0)
            - order.discount
        ).quantize(quantum)
    end = header + len(order.items)
    rows = summary(order, subtotal if totals else None, total)
    last = end + len(rows)
    for row, (label, amount) in enumerate(rows, end + 1):
        value = shown(amount)
        if (
            ws.cell(row, 5).value != label
            or not matches(ws.cell(row, 6).value, value)
            or compact(label + str(value)) not in text
        ):
            findings.append(f"{label} mismatch")
    if totals:
        subtotal_formula = f"=SUM(F{start}:F{end})"
        total_formula = f"=ROUND(SUM(F{end + 1}:F{last - 2})-F{last - 1},{precision})"
        legacy_total = (
            f"=F{end + 1}+F{end + 2}+F{end + 3}-F{end + 4}" if len(rows) == 5 else None
        )
        if formulas.cell(end + 1, 6).value != subtotal_formula or formulas.cell(
            last, 6
        ).value not in (total_formula, legacy_total):
            findings.append("Workbook summary formula mismatch")
    expected_images = int(bool(order.logo)) + sum(
        len(item.images()) for item in order.items
    )
    drawn = 0
    for page in pages:
        resources = page["/Resources"].get("/XObject", {})
        contents = page.get_contents()
        if contents is not None:
            for operands, operator in contents.operations:
                if operator == b"Do" and resources[operands[0]]["/Subtype"] == "/Image":
                    drawn += 1
    if len(formulas._images) < expected_images or drawn < expected_images:
        findings.append("Missing document images")
    return Audit(passed=not findings, findings=findings)
