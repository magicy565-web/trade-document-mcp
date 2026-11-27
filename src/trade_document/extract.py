"""Conservative evidence collection. Ambiguous candidates require operator resolution."""

import base64
import csv
from io import BytesIO
from zipfile import ZipFile
from openpyxl import load_workbook
from pypdf import PdfReader
import re
from io import StringIO
from typing import Literal
from .model import Evidence, Line, Model, Order, Text
from pydantic import Field, ValidationError, model_validator


class Source(Model):
    name: Text
    kind: Literal["chat", "quotation", "product"]
    text: str | None = Field(default=None, min_length=1, max_length=200000)
    format: Literal["text", "xlsx", "pdf"] = "text"
    content_base64: str | None = Field(default=None, max_length=2000000)

    @model_validator(mode="after")
    def check_payload(self):
        if self.format == "text" and self.text and self.content_base64 is None:
            return self
        if self.format != "text" and self.content_base64 and self.text is None:
            return self
        raise ValueError("Provide text or one encoded attachment matching the format")


def read_source(source):
    if source.format == "text":
        return source.text
    data = BytesIO(base64.b64decode(source.content_base64, validate=True))
    if source.format == "pdf":
        reader = PdfReader(data)
        if len(reader.pages) > 40:
            raise ValueError("Maximum 40 source pages")
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        if not text.strip():
            raise ValueError("No text layer; transcribe scanned source first")
    else:
        with ZipFile(data) as z:
            if sum(f.file_size for f in z.infolist()) > 8000000:
                raise ValueError("Workbook too large")
        wb = load_workbook(data, read_only=True, data_only=True, keep_links=False)
        stream = StringIO()
        writer = csv.writer(stream)
        for ws in wb:
            if (ws.max_row or 0) > 2000 or (ws.max_column or 0) > 40:
                raise ValueError("Source sheet too large")
            for row in ws.values:
                cells = list(row)
                while cells and cells[-1] is None:
                    cells.pop()
                if len(cells) == 2 and str(cells[0]).lower() in set(
                    Order.model_fields
                ) | set(ALIASES):
                    stream.write(f"{cells[0]}: {cells[1]}\n")
                else:
                    writer.writerow(cells)
        text = stream.getvalue()
    if len(text) > 200000:
        raise ValueError("Source exceeds text limit")
    return text


class Extraction(Model):
    evidence: list[Evidence]
    conflicts: list[str]
    unmatched: list[str]


ALIASES = {
    "卖方": "seller",
    "买方": "buyer",
    "买家": "buyer",
    "币种": "currency",
    "运费": "freight",
    "付款条件": "payment",
    "交期": "delivery",
    "样品费": "sample_fee",
    "定制要求": "customization",
    "运费承担": "freight_payer",
    "payment terms": "payment",
    "delivery terms": "delivery",
    "sample fee": "sample_fee",
    "单价": "unit_price",
}


def extract(sources):
    records = []
    unmatched = []
    candidates = {}
    for s in sources:
        columns = []
        for n, line in enumerate(read_source(s).splitlines(), 1):
            if not line.strip():
                continue
            cells = next(csv.reader([line]))
            if "sku" in [c.strip().lower() for c in cells] and len(cells) > 1:
                columns = [c.strip().lower() for c in cells]
                continue
            pairs = []
            if columns and len(cells) == len(columns) and "sku" in columns:
                sku = cells[columns.index("sku")].strip()
                pairs = [
                    (f"items[{sku}].{k}", v.strip())
                    for k, v in zip(columns, cells)
                    if k
                    in {
                        "sku",
                        "description",
                        "specification",
                        "quantity",
                        "unit",
                        "unit_price",
                    }
                ]
            else:
                m = re.fullmatch(r"([^:：=]{1,40})\s*[:：=]\s*(.+)", line.strip())
                if m:
                    k = m[1].strip().lower()
                    field = ALIASES.get(k, k)
                    if field in Order.model_fields or field == "unit_price":
                        pairs = [(field, m[2].strip())]
            if not pairs:
                unmatched.append(f"{s.name}:{n} {line}")
            for key, v in pairs:
                records.append(
                    Evidence(field=key, value=v, source=s.name, line=n, quote=line)
                )
                candidates.setdefault(key, set()).add(v)
    return Extraction(
        evidence=records,
        conflicts=sorted(k for k, v in candidates.items() if len(v) > 1),
        unmatched=unmatched,
    )


class Highlight(Model):
    """A host/LLM-proposed verbatim value in unstructured source text."""

    field: Text
    source: Text
    line: int = Field(ge=1)
    value: Text


def grounded(sources, highlights):
    result = extract(sources)
    indexed = {s.name: read_source(s).splitlines() for s in sources}
    if len(indexed) != len(sources):
        raise ValueError("Source names must be unique")
    for h in highlights:
        rows = indexed.get(h.source, [])
        if h.line > len(rows) or h.value not in rows[h.line - 1]:
            raise ValueError(
                "Candidate lacks verbatim evidence at the supplied location"
            )
        if h.field not in Order.model_fields and not re.fullmatch(
            r"items\[[^\]]+\]\.(sku|description|specification|quantity|unit|unit_price)",
            h.field,
        ):
            raise ValueError("Unknown trade field")
        result.evidence.append(
            Evidence(
                field=h.field,
                value=h.value,
                source=h.source,
                line=h.line,
                quote=rows[h.line - 1],
            )
        )
    values = {}
    for e in result.evidence:
        values.setdefault(e.field, set()).add(e.value)
    result.conflicts = sorted(k for k, v in values.items() if len(v) > 1)
    return result


def populate(order, sources, highlights):
    """Populate only unambiguous evidenced values. Retain conflicts for human resolution."""
    extracted = grounded(sources, highlights)
    data = order.model_dump(mode="json")
    unresolved = list(order.unresolved)
    items = {i["sku"]: i for i in data["items"]}
    if len(items) != len(data["items"]):
        raise ValueError("Use unique SKU keys during import")
    allowed = set(Order.model_fields) - {
        "kind",
        "items",
        "evidence",
        "unresolved",
        "sources",
        "template_id",
        "logo",
    }
    for e in extracted.evidence:
        if e.field in extracted.conflicts:
            continue
        match = re.fullmatch(r"items\[([^\]]+)\]\.(\w+)", e.field)
        if match:
            sku, key = match.groups()
            target = items.setdefault(sku, {"sku": sku})
            value = e.value
            if key == "quantity" and value.isascii() and value.isdigit():
                value = int(value)
        elif e.field in allowed:
            target, key, value = data, e.field, e.value
        else:
            continue
        if target.get(key) is not None and str(target[key]) != str(value):
            unresolved.append(f"Draft and source disagree on {e.field}")
            continue
        target[key] = value
    valid_items = []
    for sku, item in items.items():
        try:
            valid_items.append(Line.model_validate(item))
        except ValidationError:
            unresolved.append(f"Verify incomplete or invalid source item {sku}")
    data.update(
        items=valid_items,
        evidence=[*order.evidence, *extracted.evidence],
        sources=list(dict.fromkeys([*order.sources, *(s.name for s in sources)])),
        unresolved=list(dict.fromkeys([*unresolved, *extracted.conflicts])),
    )
    return Order.model_validate(data)
