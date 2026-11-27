"""Inspect company layouts, sign a mapping, retain the exact original for review."""

import base64, json, os
from io import BytesIO
from zipfile import ZipFile
from typing import Annotated, Literal
from pydantic import Field
from openpyxl import load_workbook
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from .model import Model, Text
from .storage import canonical, sha, database
from .render import open_template
from .approval import Proof

Payload = Annotated[str, Field(max_length=2000000)]


class Sheet(Model):
    name: str
    rows: int
    columns: int
    merges: list[str]
    images: int
    formulas: list[str]
    style_ids: list[int]
    print_area: str


class Scan(Model):
    digest: str
    sheets: list[Sheet]
    defined_names: list[str]


class Mapping(Model):
    purpose: Literal["trade.template.mapping.v1"] = "trade.template.mapping.v1"
    digest: str
    sheet: str
    title: Annotated[int, Field(ge=1, le=80)]
    details: Annotated[int, Field(ge=1, le=80)]
    items: Annotated[int, Field(ge=1, le=80)]


class Registered(Model):
    template_id: str
    original_digest: str


class Check(Model):
    valid: bool
    findings: list[str]


def unpack(encoded):
    data = base64.b64decode(encoded, validate=True)
    with ZipFile(BytesIO(data)) as z:
        if len(z.infolist()) > 500 or sum(f.file_size for f in z.infolist()) > 4000000:
            raise ValueError("Template exceeds unpacking limits")
        for name in z.namelist():
            if any(
                t in name.lower()
                for t in (
                    "external",
                    "vba",
                    "embedding",
                    "connection",
                    "querytable",
                    "activex",
                )
            ):
                raise ValueError("Unsupported active workbook content")
            if name.endswith(".rels") and b'TargetMode="External"' in z.read(name):
                raise ValueError("External workbook relationship")
    wb = load_workbook(BytesIO(data), keep_links=False)
    if len(wb.worksheets) > 12 or any(s.max_row > 500 or s.max_column > 48 for s in wb):
        raise ValueError("Template dimensions exceed scan limits")
    return data, wb


def inspect_template(xlsx_base64: Payload) -> Scan:
    data, wb = unpack(xlsx_base64)
    sheets = []
    for ws in wb:
        cells = [c for row in ws for c in row if c.value is not None]
        sheets.append(
            Sheet(
                name=ws.title,
                rows=ws.max_row,
                columns=ws.max_column,
                merges=sorted(map(str, ws.merged_cells.ranges)),
                images=len(ws._images),
                formulas=[c.coordinate for c in cells if c.data_type == "f"],
                style_ids=sorted({c.style_id for c in cells}),
                print_area=str(ws.print_area),
            )
        )
    return Scan(digest=sha(data), sheets=sheets, defined_names=list(wb.defined_names))


def propose_template_mapping(xlsx_base64: Payload) -> Mapping:
    data, wb = unpack(xlsx_base64)
    ws = wb.active
    groups = {
        "title": {"proforma invoice", "sample order sheet", "{{title}}"},
        "details": {"seller", "exporter", "{{details}}"},
        "items": {"sku", "item no.", "{{items}}"},
    }
    selected = {}
    for key, aliases in groups.items():
        hits = [c.row for c in ws["A"] if str(c.value).strip().lower() in aliases]
        if len(hits) != 1:
            raise ValueError(
                f"Specify the {key} row manually; candidate count {len(hits)}"
            )
        selected[key] = hits[0]
    return Mapping(digest=sha(data), sheet=ws.title, **selected)


def verify(keyring, value, proof):
    keys = json.loads(os.environ.get(keyring, "{}"))
    if proof.reviewer not in keys:
        raise ValueError("Reviewer role required")
    try:
        Ed25519PublicKey.from_public_bytes(
            base64.b64decode(keys[proof.reviewer], validate=True)
        ).verify(base64.b64decode(proof.signature, validate=True), canonical(value))
    except (ValueError, InvalidSignature) as e:
        raise ValueError("Invalid review proof") from e


def confirm_template_mapping(
    xlsx_base64: Payload, mapping: Mapping, proof: Proof
) -> Registered:
    data, wb = unpack(xlsx_base64)
    if sha(data) != mapping.digest:
        raise ValueError("Template changed after mapping")
    verify("TRADE_TEMPLATE_REVIEWERS", mapping.model_dump(mode="json"), proof)
    if len(wb.worksheets) != 1 or wb.active.title != mapping.sheet or wb.defined_names:
        raise ValueError(
            "Single-sheet layout required; named areas require explicit migration"
        )
    ws = wb.active
    for tag in ("title", "details", "items"):
        c = ws.cell(getattr(mapping, tag), 1)
        if c.data_type == "f" or c.hyperlink:
            raise ValueError("Mapped cell must be static text")
        c.value = "{{" + tag + "}}"
    buf = BytesIO()
    wb.save(buf)
    normalized = buf.getvalue()
    open_template(normalized)
    key = sha(canonical(mapping.model_dump(mode="json")))
    with database() as db:
        db.execute(
            "INSERT OR IGNORE INTO templates VALUES(?,?,?)", (key, ws.title, normalized)
        )
        db.execute(
            "INSERT OR IGNORE INTO template_reviews VALUES(?,?,?,?,?)",
            (key, data, mapping.model_dump_json(), proof.reviewer, proof.signature),
        )
    return Registered(template_id=key, original_digest=mapping.digest)


def validate_template(template_id: Text) -> Check:
    with database() as db:
        row = db.execute(
            "SELECT content FROM templates WHERE id=?", (template_id,)
        ).fetchone()
        if not row:
            return Check(valid=False, findings=["Unknown template"])
        open_template(row[0])
        return Check(valid=True, findings=[])
