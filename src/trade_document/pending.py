"""Reviewable incomplete order. Unknown monetary values always remain pending."""

from openpyxl import Workbook, load_workbook
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from xml.sax.saxutils import escape
from pypdf import PdfReader
from .model import issues
from .render import literal, document_title
from .audit import Audit, compact
from .locale import label


def rows(o):
    pending = label(o, "Pending")

    def known(v):
        return pending if v is None else str(v)

    data = [
        [label(o, "Seller"), known(o.seller)],
        [label(o, "Buyer"), known(o.buyer)],
        [label(o, "Document no."), known(o.number)],
        [label(o, "Currency"), known(o.currency)],
    ]
    data.append(
        [
            "SKU",
            label(o, "Description / specification"),
            label(o, "Quantity"),
            label(o, "Unit"),
            label(o, "Unit price"),
        ]
    )
    data.extend(
        [i.sku, i.description, known(i.quantity), known(i.unit), known(i.unit_price)]
        for i in o.items
    )
    data.extend(
        [
            [label(o, k), known(v)]
            for k, v in [
                ("Freight", o.freight),
                ("Sample fee", o.sample_fee),
                ("Discount", o.discount),
                ("Total", None),
            ]
        ]
    )
    data.extend([["Review", e] for e in issues(o)])
    return data


def write(o, x, p):
    title = document_title(o, True)
    data = rows(o)
    wb = Workbook()
    ws = wb.active
    ws.append([title])
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 12)]
    for r, row in enumerate(data, 2):
        for col, v in enumerate(row, 1):
            literal(ws.cell(r, col), v)
        line = Table(
            [[Paragraph(escape(str(v)), styles["BodyText"]) for v in row]],
            colWidths=[470 / len(row)] * len(row),
        )
        line.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, -1),
                        colors.HexColor("#eff5f5") if r % 2 == 0 else colors.white,
                    ),
                ]
            )
        )
        story.append(line)
    for col, w in zip("ABCDE", [26, 70, 14, 12, 15]):
        ws.column_dimensions[col].width = w
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    wb.save(x)
    SimpleDocTemplate(str(p), pagesize=LETTER if o.paper == "Letter" else A4).build(
        story
    )


def inspect(o, x, p):
    data = rows(o)
    ws = load_workbook(x, data_only=True).active
    text = compact("".join(page.extract_text() for page in PdfReader(p).pages))
    title = document_title(o, True)
    findings = (
        []
        if ws["A1"].value == title and compact(title) in text
        else ["Draft title mismatch"]
    )
    for r, row in enumerate(data, 2):
        if (
            any(ws.cell(r, c).value != v for c, v in enumerate(row, 1))
            or compact("".join(row)) not in text
        ):
            findings.append(f"Incomplete draft row {r} mismatch")
    return Audit(passed=not findings, findings=findings)
