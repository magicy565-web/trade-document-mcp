"""Revise one evidenced commercial field without dropping unrelated conflicts."""

import re
from typing import Annotated

from pydantic import Field

from .model import Evidence, Model, Order, Text


class FieldResolution(Model):
    field: Text
    value: Text
    source: Text
    line: Annotated[int, Field(gt=0, strict=True)]
    quote: Text


_TOP = {
    "number",
    "issue_date",
    "seller",
    "buyer",
    "currency",
    "freight",
    "sample_fee",
    "insurance",
    "tooling_fee",
    "discount",
    "sample_policy",
    "sample_credit",
    "customization",
    "sample_acceptance",
    "payment",
    "delivery",
    "freight_payer",
    "valid_until",
    "ship_to",
    "seller_address",
    "buyer_address",
    "purchase_order",
}
_LINE = re.compile(
    r"items\[([^\]]+)\]\.(description|variant|specification|quantity|unit|unit_price)"
)


def resolve(order: Order, entries: list[FieldResolution]) -> Order:
    data = order.model_dump(mode="json")
    if len({entry.field for entry in entries}) != len(entries):
        raise ValueError("A field can be resolved once per revision")
    for entry in entries:
        if entry.value not in entry.quote:
            raise ValueError(
                f"Value must be recorded in the cited quote for {entry.field}"
            )
        line = _LINE.fullmatch(entry.field)
        if line:
            sku, key = line.groups()
            matches = [item for item in data["items"] if item["sku"] == sku]
            if len(matches) != 1:
                raise ValueError(f"Expected one item with SKU {sku}")
            matches[0][key] = entry.value
        elif entry.field in _TOP:
            data[entry.field] = entry.value
        else:
            raise ValueError(f"Unsupported field resolution: {entry.field}")
        data["unresolved"] = [
            issue
            for issue in data["unresolved"]
            if issue not in (entry.field, f"Draft and source disagree on {entry.field}")
        ]
        for evidence in data["evidence"]:
            if evidence["field"] == entry.field and evidence["status"] == "disputed":
                evidence["status"] = "superseded"
        data["evidence"].append(
            Evidence(**entry.model_dump(), status="candidate").model_dump()
        )
        if entry.source not in data["sources"]:
            data["sources"].append(entry.source)
    return Order.model_validate(data)
