import base64
import math
import re
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.units import pixels_to_EMU
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
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

from .model import document_totals

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


def extra_details(o, totals):
    fields = [
        ("Seller address", o.seller_address),
        ("Buyer address", o.buyer_address),
        ("Ship to", o.ship_to),
        ("PO reference", o.purchase_order),
        ("Valid until", o.valid_until),
    ]
    fields.extend(
        (
            f"{party.role.replace('_', ' ').title()} profile",
            party.legal_name + " | " + party.address.display(),
        )
        for party in o.parties
    )
    fields.append(("Sample acceptance", o.sample_acceptance))
    if o.delivery_term:
        fields.append(
            (
                "Agreed delivery term",
                f"{o.delivery_term.term} {o.delivery_term.named_place} {o.delivery_term.edition}",
            )
        )
    if totals and o.schedule:
        fields.extend(
            (m.event + " (" + str(m.percent) + "%)", f"{o.currency} {amount}")
            for m, amount in zip(o.schedule, totals.installments)
        )
    return [(k, str(v)) for k, v in fields if v is not None]


def summary(o, subtotal, total):
    rows = [
        ("Subtotal", subtotal),
        ("Sample fee", o.sample_fee),
        ("Freight", o.freight),
    ]
    rows.extend(
        (label, fee)
        for label, fee in (("Insurance", o.insurance), ("Tooling fee", o.tooling_fee))
        if fee is not None
    )
    return [
        *rows,
        ("Discount", o.discount),
        (("Total " + o.currency) if o.currency else "Total", total),
    ]


def shown(value):
    return "Pending" if value is None else value


def paragraph(value, style):
    text = escape(str(shown(value))).replace("\n", "<br/>")
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        if "HeiseiMin-W3" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
        text = re.sub(
            r"([\u3040-\u30ff\u3400-\u9fff]+)",
            r'<font name="HeiseiMin-W3">\1</font>',
            text,
        )
    return Paragraph(text, style)


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


def workbook(o, title, path, template=None, *, draft=False):
    amounts = document_totals(o, draft)
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

    def add_image(raw, cell, offset=0):
        img = XLImage(BytesIO(picture(raw)))
        scale = min(90 / img.width, 42 / img.height)
        img.width, img.height = img.width * scale, img.height * scale
        target = ws[cell]
        anchor = AnchorMarker(
            col=target.column - 1, row=target.row - 1, colOff=pixels_to_EMU(offset)
        )
        img.anchor = OneCellAnchor(
            _from=anchor,
            ext=XDRPositiveSize2D(pixels_to_EMU(img.width), pixels_to_EMU(img.height)),
        )
        ws.add_image(img)

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
    extra = extra_details(o, amounts)
    for label, value in extra:
        ws.insert_rows(header)
        literal(ws.cell(header, 1), label)
        ws.merge_cells(start_row=header, start_column=2, end_row=header, end_column=6)
        literal(ws.cell(header, 2), value)
        ws.cell(header, 2).alignment = Alignment(wrap_text=True)
        ws.row_dimensions[header].height = max(24, 16 * math.ceil(len(value) / 70))
        header += 1
    band(header, HEAD)
    cache = {}
    precision = 0 if o.currency == "JPY" else 2
    for index, item in enumerate(o.items, 1):
        row = header + index
        desc = "\n".join(item.descriptions())
        values = [item.sku, desc, item.quantity, item.unit, item.unit_price]
        for col, v in enumerate(values, 1):
            cell = ws.cell(row, col)
            literal(cell, shown(v))
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        if amounts:
            formula = ws.cell(row, 6, f"=ROUND(C{row}*E{row},{precision})")
            cache[formula.coordinate] = amounts.lines[index - 1]
        else:
            literal(ws.cell(row, 6), "Pending")
        ws.row_dimensions[row].height = max(
            30,
            17 * (math.ceil(len(desc) / 32) + desc.count("\n")),
            17 * math.ceil(len(item.sku) / 15),
            17 * math.ceil(len(item.unit or "Pending") / 10),
        )
        images = item.images()
        if images:
            for index, image in enumerate(images):
                add_image(image, f"B{row}", offset=index * 95)
            ws.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="bottom")
            ws.row_dimensions[row].height += 38
    end = header + len(o.items)
    totals_rows = summary(o, None, None)
    last = end + len(totals_rows)
    for row, (label, value) in enumerate(totals_rows, end + 1):
        literal(ws.cell(row, 5), label)
        literal(ws.cell(row, 6), shown(value))
    if amounts:
        ws.cell(end + 1, 6).value = f"=SUM(F{header + 1}:F{end})"
        ws.cell(
            last, 6
        ).value = f"=ROUND(SUM(F{end + 1}:F{last - 2})-F{last - 1},{precision})"
        cache[f"F{end + 1}"] = amounts.subtotal
        cache[f"F{last}"] = amounts.total
    for row in range(header + 1, last + 1):
        ws.cell(row, 6).number_format = "#,##0" if precision == 0 else "#,##0.00"
    for col in (5, 6):
        cell = ws.cell(last, col)
        cell.font = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="184553")
    ws.row_dimensions[last].height = 25
    if not draft:
        ws.cell(last + 2, 1, "Authorized signature")
    ws.oddFooter.right.text = "Page &P"
    for r in range(header + 1, end + 1):
        ws.cell(r, 5).number_format = "#,##0.00##" if precision else "#,##0.####"
        ws.cell(r, 6).alignment = Alignment(vertical="center", horizontal="right")
        if (r - header) % 2 == 1:
            for cell in ws[r][:6]:
                cell.fill = PatternFill("solid", fgColor="EFF5F5")
    ws.print_area = f"A{top}:F{last + (0 if draft else 2)}"
    ws.print_title_rows = f"{header}:{header}"
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = f"C{header + 1}"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.page_setup.paperSize = (
        ws.PAPERSIZE_LETTER if o.paper == "Letter" else ws.PAPERSIZE_A4
    )
    wb.save(path)
    cached_formulas(path, cache)


def pdf(o, title, path, version, *, draft=False):
    amounts = document_totals(o, draft)
    pagesize = LETTER if o.paper == "Letter" else A4
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "terms",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#163741"),
    )

    def para(text, style=body):
        return paragraph(text, style)

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

    details.extend([para(k), para(v)] for k, v in extra_details(o, amounts))

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
    rows = [HEAD]
    for index, i in enumerate(o.items):
        amt = amounts.lines[index] if amounts else None
        desc = [para(description) for description in i.descriptions()]
        desc.extend(photo(image) for image in i.images())
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
                    for k, v in summary(
                        o,
                        amounts.subtotal if amounts else None,
                        amounts.total if amounts else None,
                    )
                ],
                [360, 141],
            ),
        ]
    )

    if not draft:
        story.extend([Spacer(1, 14), para("Authorized signature ____________________")])

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(17 * mm, 12 * mm, f"{title}  /  Revision {version}")
        canvas.drawRightString(pagesize[0] - 17 * mm, 12 * mm, f"Page {doc.page}")

    SimpleDocTemplate(
        str(path),
        pagesize=pagesize,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=title,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
