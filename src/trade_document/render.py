import base64
import math
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Table,
    TableStyle,
    Spacer,
    Image,
)

from .model import calculate

TITLES = {
    "standard-pi": "Proforma Invoice",
    "product-image-pi": "Proforma Invoice",
    "sample-pi": "Sample Proforma Invoice",
    "sample-order": "Sample Order Sheet",
}
HEAD = [
    "SKU",
    "Description / specification",
    "Quantity",
    "Unit",
    "Unit price",
    "Amount",
]
LABELS = {
    "seller": "Seller",
    "buyer": "Buyer",
    "number": "Document no.",
    "issue_date": "Issue date",
    "currency": "Currency",
    "customization": "Customization",
    "sample_policy": "Sample policy",
    "sample_credit": "Credit toward bulk order",
    "payment": "Payment terms",
    "delivery": "Delivery terms",
    "freight_payer": "Freight payable by",
    "bank": "Payment instructions",
}


def picture(raw):
    data = base64.b64decode(raw, validate=True)
    source = PILImage.open(BytesIO(data))
    if source.format not in ("PNG", "JPEG") or source.width * source.height > 4000000:
        raise ValueError("Use PNG/JPEG under four megapixels")
    source.thumbnail((360, 220))
    buf = BytesIO()
    source.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def open_template(data):
    with ZipFile(BytesIO(data)) as archive:
        if sum(f.file_size for f in archive.infolist()) > 4000000:
            raise ValueError("Template exceeds size limit")
        for entry in archive.namelist():
            if any(
                s in entry.lower()
                for s in (
                    "externallink",
                    "vba",
                    "embedding",
                    "connections",
                    "querytable",
                )
            ):
                raise ValueError("Template must be a standalone workbook")
    wb = load_workbook(BytesIO(data), keep_links=False)
    ws = wb.active
    if len(wb.worksheets) != 1 or ws.max_row > 80 or ws.max_column > 6:
        raise ValueError("Expected one six-column template sheet, at most 80 rows")
    found = {}
    for row in ws.iter_rows():
        for c in row:
            if c.data_type == "f" or c.hyperlink:
                raise ValueError(
                    "Only generated formulas and standalone text are supported"
                )
            if c.value in ("{{title}}", "{{details}}", "{{items}}"):
                if c.column != 1 or c.value in found:
                    raise ValueError("Each section anchor belongs in column A once")
                found[c.value] = c.row
            elif c.value is not None:
                raise ValueError(
                    "Template accepts layout/styles and three section anchors"
                )
    if set(found) != {"{{title}}", "{{details}}", "{{items}}"}:
        raise ValueError("Missing title/details/items anchors")
    a, b, c = (found[k] for k in ("{{title}}", "{{details}}", "{{items}}"))
    if not a < b or c < b + len(LABELS) or ws.merged_cells.ranges:
        raise ValueError(
            "Reserve twelve metadata rows before items; merges are generated"
        )
    if ws.sheet_state != "visible" or any(
        d.hidden
        for d in list(ws.row_dimensions.values()) + list(ws.column_dimensions.values())
    ):
        raise ValueError("Layout must be visible")
    return wb, (a, b, c)


def literal(cell, value):
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"


def cached_formulas(path, cache):
    # Preserve editable Excel formulas and numeric results for read-only clients.
    with ZipFile(path) as src:
        out = BytesIO()
        with ZipFile(out, "w") as dst:
            for info in src.infolist():
                content = src.read(info)
                if info.filename == "xl/worksheets/sheet1.xml":
                    root = ET.fromstring(content)
                    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                    for c in root.iter(ns + "c"):
                        if c.attrib["r"] in cache:
                            c.find(ns + "v").text = str(cache[c.attrib["r"]])
                    content = ET.tostring(root, encoding="utf-8")
                dst.writestr(info, content)
    path.write_bytes(out.getvalue())


def workbook(o, title, path, template=None):
    wb, (top, meta, header) = (
        open_template(template) if template else (Workbook(), (1, 3, 16))
    )
    ws = wb.active
    ws.title = "Document"
    widths = [20, 42, 14, 13, 18, 19]
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    for row in (top,):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)

    def band(r, values):
        for i, value in enumerate(values, 1):
            cell = ws.cell(r, i)
            literal(cell, value)
            if not template or not cell.has_style:
                cell.fill = PatternFill("solid", fgColor="184553")
                cell.font = Font(name="Calibri", size=12, color="FFFFFF", bold=True)
        ws.row_dimensions[r].height = 28

    band(top, [title])

    def add_image(raw, cell):
        img = XLImage(BytesIO(picture(raw)))
        scale = min(90 / img.width, 42 / img.height)
        img.width, img.height = img.width * scale, img.height * scale
        ws.add_image(img, cell)

    if o.logo:
        add_image(o.logo, f"F{top}")
        ws.row_dimensions[top].height = 38
    for n, (key, label) in enumerate(LABELS.items(), meta):
        ws.merge_cells(start_row=n, start_column=2, end_row=n, end_column=6)
        raw = getattr(o, key)
        if raw is None and (
            key == "bank"
            or (
                key in ("sample_policy", "sample_credit", "customization")
                and not o.kind.startswith("sample")
            )
        ):
            ws.row_dimensions[n].hidden = True
            continue
        value = str(raw or "Pending")
        literal(ws.cell(n, 1), label)
        literal(ws.cell(n, 2), value)
        ws.cell(n, 2).alignment = Alignment(wrap_text=True, vertical="center")
        ws.cell(n, 1).alignment = Alignment(wrap_text=True, vertical="center")
        ws.row_dimensions[n].height = max(
            30, 18 * (math.ceil(len(value) / 76) + value.count("\n"))
        )
    band(header, HEAD)
    cache = {}
    amounts = calculate(o)
    precision = 0 if o.currency == "JPY" else 2
    for index, item in enumerate(o.items, 1):
        row = header + index
        desc = "\n".join(filter(None, [item.description, item.specification]))
        values = [item.sku, desc, item.quantity, item.unit, item.unit_price]
        for col, v in enumerate(values, 1):
            cell = ws.cell(row, col)
            literal(cell, v)
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        formula = ws.cell(row, 6, f"=ROUND(C{row}*E{row},{precision})")
        cache[formula.coordinate] = amounts.lines[index - 1]
        ws.row_dimensions[row].height = max(
            30,
            17 * (math.ceil(len(desc) / 32) + desc.count("\n")),
            17 * math.ceil(len(item.sku) / 15),
            17 * math.ceil(len(item.unit) / 10),
        )
        if item.image:
            add_image(item.image, f"B{row}")
            ws.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="bottom")
            ws.row_dimensions[row].height += 38
    end = header + len(o.items)
    for offset, (label, value) in enumerate(
        [
            ("Subtotal", f"=SUM(F{header + 1}:F{end})"),
            ("Sample fee", o.sample_fee),
            ("Freight", o.freight),
            ("Discount", o.discount),
            ("Total " + o.currency, f"=F{end + 1}+F{end + 2}+F{end + 3}-F{end + 4}"),
        ],
        1,
    ):
        ws.cell(end + offset, 5, label)
        ws.cell(end + offset, 6, value)
    cache[f"F{end + 1}"] = amounts.subtotal
    cache[f"F{end + 5}"] = amounts.total
    for r in range(header + 1, end + 6):
        ws.cell(r, 6).number_format = "#,##0" if precision == 0 else "#,##0.00"
    for col in (5, 6):
        cell = ws.cell(end + 5, col)
        cell.font = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="184553")
    ws.row_dimensions[end + 5].height = 25
    for r in range(header + 1, end + 1):
        ws.cell(r, 5).number_format = "#,##0.00##" if precision else "#,##0.####"
        ws.cell(r, 6).alignment = Alignment(vertical="center", horizontal="right")
        if (r - header) % 2 == 1:
            for cell in ws[r][:6]:
                cell.fill = PatternFill("solid", fgColor="EFF5F5")
    ws.print_area = f"A{top}:F{end + 5}"
    ws.print_title_rows = f"{header}:{header}"
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = f"C{header + 1}"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    wb.save(path)
    cached_formulas(path, cache)


def pdf(o, title, path, version):
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "terms",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#163741"),
    )

    def para(text, style=body):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)

    def photo(raw):
        im = Image(BytesIO(picture(raw)))
        im._restrictSize(72, 42)
        return im

    story = [para(title, styles["Title"]), Spacer(1, 6)]
    if o.logo:
        story.append(photo(o.logo))
    details = [
        [para(label), para(getattr(o, k) or "Pending")]
        for k, label in LABELS.items()
        if getattr(o, k) is not None
        or (k not in {"bank", "sample_policy", "sample_credit", "customization"})
    ]

    def table(rows, widths, head=False):
        t = Table(rows, colWidths=widths, repeatRows=int(head), hAlign="LEFT")
        rules = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            (
                "ROWBACKGROUNDS",
                (0, int(head)),
                (-1, -1),
                [colors.white, colors.HexColor("#EFF5F5")],
            ),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        if head:
            rules += [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#184553")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
            ]
        t.setStyle(TableStyle(rules))
        return t

    story.extend([table(details, [125, 376]), Spacer(1, 14)])
    totals = calculate(o)
    rows = [HEAD]
    for i, amt in zip(o.items, totals.lines):
        desc = [para(i.description)]
        if i.specification:
            desc.append(para(i.specification))
        if i.image:
            desc.append(photo(i.image))
        rows.append(
            [
                para(i.sku),
                desc,
                para(i.quantity),
                para(i.unit),
                para(i.unit_price),
                para(amt),
            ]
        )
    story.extend(
        [
            table(rows, [74, 162, 56, 52, 76, 81], True),
            Spacer(1, 12),
            table(
                [
                    [para(k), para(v)]
                    for k, v in [
                        ("Subtotal", totals.subtotal),
                        ("Sample fee", o.sample_fee),
                        ("Freight", o.freight),
                        ("Discount", o.discount),
                        ("Total " + o.currency, totals.total),
                    ]
                ],
                [360, 141],
            ),
        ]
    )

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(17 * mm, 12 * mm, f"{title}  /  Revision {version}")
        canvas.drawRightString(A4[0] - 17 * mm, 12 * mm, f"Page {doc.page}")

    SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=title,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
