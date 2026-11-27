"""Actual dispatched quantities and box contents drive both shipping documents."""

import time, shutil
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from typing import Annotated, Literal
from collections import defaultdict
from xml.sax.saxutils import escape
from pydantic import Field
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from pypdf import PdfReader
from .approval import Proof
from .mapping import verify, Check
from .model import Model, Text, Amount, quantum
from .storage import canonical, sha, home, database, current
from .render import literal
from .audit import compact

Qty = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=4)]
Rev = Annotated[int, Field(gt=0, strict=True)]
Id = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class PackedLine(Model):
    sku: Text
    quantity: Qty
    unit: Text
    origin: Annotated[str, Field(pattern="^[A-Z]{2}$")]


class Box(Model):
    mark: Text
    net_kg: Qty
    gross_kg: Qty
    volume_m3: Qty
    contents: Annotated[list[PackedLine], Field(min_length=1, max_length=100)]


class Shipment(Model):
    number: Text
    dispatch_date: date
    consignee: Text
    freight: Amount
    fees: Amount
    discount: Amount
    source: Text
    boxes: Annotated[list[Box], Field(min_length=1, max_length=200)]


class Saved(Model):
    shipment_id: str
    version: int
    order_id: str
    order_version: int
    digest: str
    shipment: Shipment
    payable: Decimal


class Packet(Model):
    purpose: Literal["shipment.issue.v1"] = "shipment.issue.v1"
    challenge: str
    shipment_id: str
    version: int
    order_digest: str
    shipment_digest: str
    preview_hashes: dict[str, str]
    expires: int


class Bundle(Model):
    shipment_id: str
    version: int
    files: list[str]
    hashes: dict[str, str]


class Draft(Model):
    title: str
    status: Literal["draft"] = "draft"
    fields: dict[str, str]
    missing: list[str]


def quantities(shipment):
    result = defaultdict(Decimal)
    for box in shipment.boxes:
        for line in box.contents:
            result[line.sku] += line.quantity
    return result


def price(o, shipment):
    catalog = {i.sku: i for i in o.items}
    return (
        sum(
            (catalog[sku].unit_price * q).quantize(quantum(o), ROUND_HALF_UP)
            for sku, q in quantities(shipment).items()
        )
        + shipment.freight
        + shipment.fees
        - shipment.discount
    )


def load(db, sid, version=None):
    row = db.execute(
        "SELECT * FROM shipments WHERE id=? AND (? IS NULL OR ver=?) ORDER BY ver DESC LIMIT 1",
        (sid, version, version),
    ).fetchone()
    if not row:
        raise ValueError("Unknown shipment revision")
    return Saved.model_validate_json(row["body"])


def persist(db, oid, order_version, shipment, sid, rev):
    snap = current(db, oid)
    if snap.version != order_version or snap.approval_status != "issued":
        raise ValueError("Current issued order required")
    if len(set(b.mark for b in shipment.boxes)) != len(shipment.boxes):
        raise ValueError("Duplicate carton mark")
    catalog = {i.sku: i for i in snap.order.items}
    for b in shipment.boxes:
        if b.net_kg > b.gross_kg:
            raise ValueError("Gross weight below net weight")
        for l in b.contents:
            if l.sku not in catalog or l.unit != catalog[l.sku].unit:
                raise ValueError("SKU or unit mismatch")
    qty = quantities(shipment)
    for row in db.execute(
        "SELECT s.id,s.body FROM shipments s WHERE s.id<>? AND s.ver=(SELECT MAX(ver) FROM shipments WHERE id=s.id)",
        (sid,),
    ):
        other = Saved.model_validate_json(row["body"])
        if other.shipment.number == shipment.number:
            raise ValueError("Duplicate shipment number")
        if other.order_id == oid:
            for sku, q in quantities(other.shipment).items():
                qty[sku] += q
    if any(sku not in catalog or q > catalog[sku].quantity for sku, q in qty.items()):
        raise ValueError("Exceeds remaining ordered quantity")
    amount = price(snap.order, shipment)
    if amount < 0 or any(
        v != v.quantize(quantum(snap.order))
        for v in [shipment.freight, shipment.fees, shipment.discount]
    ):
        raise ValueError("Invalid batch charges")
    record = Saved(
        shipment_id=sid,
        version=rev,
        order_id=oid,
        order_version=order_version,
        digest=sha(canonical(shipment.model_dump(mode="json"))),
        shipment=shipment,
        payable=amount,
    )
    db.execute(
        "INSERT INTO shipments VALUES(?,?,?)", (sid, rev, record.model_dump_json())
    )
    return record


def create_shipment(order_id: Id, expected_version: Rev, shipment: Shipment) -> Saved:
    with database() as db:
        return persist(db, order_id, expected_version, shipment, uuid4().hex, 1)


def revise_shipment(
    shipment_id: Id, expected_version: Rev, shipment: Shipment
) -> Saved:
    with database() as db:
        old = load(db, shipment_id)
        if (
            old.version != expected_version
            or db.execute(
                "SELECT 1 FROM shipment_issues WHERE id=?", (shipment_id,)
            ).fetchone()
        ):
            raise ValueError("Issued or stale shipment")
        return persist(
            db,
            old.order_id,
            old.order_version,
            shipment,
            shipment_id,
            expected_version + 1,
        )


def validate_shipment(shipment_id: Id, version: Rev) -> Check:
    with database() as db:
        s = load(db, shipment_id, version)
        ok = (
            current(db, s.order_id).version == s.order_version
            and load(db, shipment_id).version == version
        )
        return Check(valid=ok, findings=[] if ok else ["Source revision superseded"])


def tables(s, o):
    batch = s.shipment
    base = [
        ["Shipment", batch.number],
        ["Dispatch date", str(batch.dispatch_date)],
        ["Order", o.number],
        ["Seller", o.seller],
        ["Buyer", o.buyer],
        ["Consignee", batch.consignee],
    ]
    amounts = [["SKU", "Description", "Quantity", "Unit", "Unit price", "Amount"]]
    catalog = {i.sku: i for i in o.items}
    for sku, q in quantities(batch).items():
        item = catalog[sku]
        amounts.append(
            [
                sku,
                item.description,
                q,
                item.unit,
                item.unit_price,
                (q * item.unit_price).quantize(quantum(o), ROUND_HALF_UP),
            ]
        )
    totals = [
        ["Freight", batch.freight],
        ["Other batch fees", batch.fees],
        ["Discount", batch.discount],
        ["Total " + o.currency, s.payable],
    ]
    packs = [["Carton", "SKU", "Qty", "Unit", "Origin"]]
    weights = [["Carton", "Net kg", "Gross kg", "Volume m3"]]
    for b in batch.boxes:
        weights.append([b.mark, b.net_kg, b.gross_kg, b.volume_m3])
        packs.extend([b.mark, l.sku, l.quantity, l.unit, l.origin] for l in b.contents)
    weights.append(
        [
            "Total",
            sum(b.net_kg for b in batch.boxes),
            sum(b.gross_kg for b in batch.boxes),
            sum(b.volume_m3 for b in batch.boxes),
        ]
    )
    return {
        "commercial-invoice": [base, amounts, totals],
        "packing-list": [base, packs, weights],
    }


def render(root, s, o, preview):
    root.mkdir(parents=True)
    files = []
    styles = getSampleStyleSheet()
    try:
        for slug, sections in tables(s, o).items():
            title = ("DRAFT - " if preview else "") + slug.replace("-", " ").title()
            ws = (wb := Workbook()).active
            ws.append([title])
            story = [Paragraph(title, styles["Title"])]
            for idx, section in enumerate(sections):
                ws.cell(ws.max_row + 1, 1, "")
                rows = []
                for j, row in enumerate(section):
                    r = ws.max_row + 1
                    for col, value in enumerate(row, 1):
                        cell = ws.cell(r, col)
                        literal(cell, value)
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                        if j == 0 and idx:
                            cell.fill = PatternFill("solid", fgColor="184553")
                            cell.font = Font(color="FFFFFF", bold=True)
                    rows.append(
                        [Paragraph(escape(str(v)), styles["BodyText"]) for v in row]
                    )
                t = Table(
                    rows,
                    colWidths=[480 / len(rows[0])] * len(rows[0]),
                    repeatRows=1 if idx else 0,
                )
                t.setStyle(
                    TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            (
                                "ROWBACKGROUNDS",
                                (0, 0),
                                (-1, -1),
                                [colors.HexColor("#e5f1f2"), colors.white],
                            ),
                        ]
                    )
                )
                story.extend([Spacer(1, 12), t])
            for col in "ABCDEF":
                ws.column_dimensions[col].width = 24
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
            x = root / (slug + ".xlsx")
            p = root / (slug + ".pdf")
            wb.save(x)
            SimpleDocTemplate(str(p), pagesize=A4).build(story)
            # Reopen both files. Check every row in sequence in the PDF and worksheet.
            actual = load_workbook(x, data_only=True).active
            reader = PdfReader(p)
            text = compact("".join(pg.extract_text() for pg in reader.pages))
            cursor = 0
            sheet_row = 1
            for section in sections:
                sheet_row += 1
                for row in section:
                    sheet_row += 1
                    for col, v in enumerate(row, 1):
                        a = actual.cell(sheet_row, col).value
                        if (Decimal(str(a)) if isinstance(v, Decimal) else a) != v:
                            raise ValueError("Workbook row mismatch")
                    token = compact("".join(map(str, row)))
                    found = text.find(token, cursor)
                    if found < 0:
                        raise ValueError("PDF row mismatch")
                    cursor = found + len(token)
            files.extend([x, p])
        return Bundle(
            shipment_id=s.shipment_id,
            version=s.version,
            files=list(map(str, files)),
            hashes={p.name: sha(p.read_bytes()) for p in files},
        )
    except BaseException:
        shutil.rmtree(root)
        raise


def preview_shipment(shipment_id: Id, expected_version: Rev) -> Packet:
    with database() as db:
        s = load(db, shipment_id)
        snap = current(db, s.order_id)
        if s.version != expected_version or s.order_version != snap.version:
            raise ValueError("Stale shipment")
        challenge = uuid4().hex
        b = render(home() / "shipping" / challenge, s, snap.order, True)
        p = Packet(
            challenge=challenge,
            shipment_id=s.shipment_id,
            version=s.version,
            order_digest=snap.digest,
            shipment_digest=s.digest,
            preview_hashes=b.hashes,
            expires=int(time.time()) + 3600,
        )
        db.execute(
            "INSERT INTO ship_reviews VALUES(?,?)", (challenge, p.model_dump_json())
        )
        return p


def export_document_bundle(packet: Packet, proof: Proof) -> Bundle:
    with database() as db:
        saved = db.execute(
            "SELECT body FROM ship_reviews WHERE id=?", (packet.challenge,)
        ).fetchone()
        if (
            not saved
            or Packet.model_validate_json(saved[0]) != packet
            or time.time() >= packet.expires
        ):
            raise ValueError("Unknown or expired shipping review")
        verify("TRADE_DOC_REVIEWERS", packet.model_dump(mode="json"), proof)
        s = load(db, packet.shipment_id)
        snap = current(db, s.order_id)
        if (
            s.version != packet.version
            or snap.digest != packet.order_digest
            or s.order_version != snap.version
        ):
            raise ValueError("Stale shipment")
        root = home() / "shipping" / packet.challenge
        if any(
            sha((root / k).read_bytes()) != v for k, v in packet.preview_hashes.items()
        ):
            raise ValueError("Preview integrity mismatch")
        prior = db.execute(
            "SELECT body FROM shipment_issues WHERE id=?", (s.shipment_id,)
        ).fetchone()
        if prior:
            result = Bundle.model_validate_json(prior[0])
            if not intact(result):
                raise ValueError("Archived files changed")
            return result
        b = render(home() / "shipping" / uuid4().hex, s, snap.order, False)
        db.execute(
            "INSERT INTO shipment_issues VALUES(?,?,?,?,?)",
            (
                s.shipment_id,
                b.model_dump_json(),
                packet.challenge,
                proof.reviewer,
                proof.signature,
            ),
        )
        return b


def intact(b):
    from pathlib import Path

    return all(
        Path(p).is_file() and sha(Path(p).read_bytes()) == b.hashes[Path(p).name]
        for p in b.files
    )


def cross_check_documents(shipment_id: Id, version: Rev) -> Check:
    with database() as db:
        s = load(db, shipment_id, version)
        row = db.execute(
            "SELECT body FROM shipment_issues WHERE id=?", (s.shipment_id,)
        ).fetchone()
        if not row:
            return Check(valid=False, findings=["No issued pair"])
        b = Bundle.model_validate_json(row[0])
        ok = b.version == version and intact(b)
        return Check(
            valid=ok, findings=[] if ok else ["Revision or archive integrity mismatch"]
        )


def prepare_customs_support(
    shipment_id: Id,
    version: Rev,
    valuation: Amount | None = None,
    valuation_currency: Text | None = None,
    valuation_evidence: Text | None = None,
) -> Draft:
    with database() as db:
        s = load(db, shipment_id, version)
        fields = {
            "shipment": s.shipment.number,
            "consignee": s.shipment.consignee,
            "source": s.shipment.source,
        }
        supplied = {
            "valuation": valuation,
            "valuation_currency": valuation_currency,
            "valuation_evidence": valuation_evidence,
        }
        fields.update({k: str(v) for k, v in supplied.items() if v})
        return Draft(
            title="Customs supporting worksheet",
            fields=fields,
            missing=[k for k, v in supplied.items() if not v],
        )


def draft_sales_contract(order_id: Id, version: Rev) -> Draft:
    with database() as db:
        o = current(db, order_id, version).order
        terms = {
            k: getattr(o, k)
            for k in ("number", "seller", "buyer", "payment", "delivery", "currency")
        }
        return Draft(
            title="Sales contract working draft",
            fields={k: str(v) for k, v in terms.items() if v},
            missing=[k for k, v in terms.items() if not v]
            + ["Legal review and execution"],
        )


def get_shipment_preview(challenge: Id) -> Bundle:
    with database() as db:
        row = db.execute(
            "SELECT body FROM ship_reviews WHERE id=?", (challenge,)
        ).fetchone()
        if not row:
            raise ValueError("Unknown preview")
        packet = Packet.model_validate_json(row[0])
        root = home() / "shipping" / packet.challenge
        b = Bundle(
            shipment_id=packet.shipment_id,
            version=packet.version,
            files=[str(root / k) for k in packet.preview_hashes],
            hashes=packet.preview_hashes,
        )
        if not intact(b):
            raise ValueError("Preview integrity mismatch")
        return b


class ShippingDraft(Model):
    purpose: Literal[
        "shipping_instruction",
        "certificate_of_origin_application",
        "cn_export_preentry",
    ]
    status: Literal["draft"] = "draft"
    shipment: Saved
    required_review: list[str]


def draft_shipping_instruction(
    shipment_id: Id,
    version: Rev,
    purpose: Literal[
        "shipping_instruction",
        "certificate_of_origin_application",
        "cn_export_preentry",
    ] = "shipping_instruction",
) -> ShippingDraft:
    with database() as db:
        fields = {
            "shipping_instruction": ["carrier", "routing", "booking reference"],
            "certificate_of_origin_application": [
                "origin evidence",
                "issuing authority",
                "authorized applicant",
            ],
            "cn_export_preentry": [
                "exporter registration",
                "classification confirmed by specialist",
                "valuation evidence",
                "authorized declarant",
            ],
        }
        return ShippingDraft(
            purpose=purpose,
            shipment=load(db, shipment_id, version),
            required_review=fields[purpose],
        )
