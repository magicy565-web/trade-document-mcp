from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)
]
Amount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]
Kind = Literal["standard-pi", "product-image-pi", "sample-pi", "sample-order"]
Currency = Literal["USD", "EUR", "GBP", "CNY", "JPY"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Line(Model):
    sku: Text
    description: Text
    specification: Text | None = None
    quantity: Annotated[int, Field(strict=True, gt=0, le=999999)] | None = None
    unit: Text | None = None
    unit_price: Amount | None = None
    image: str | None = Field(default=None, max_length=1000000)


class Evidence(Model):
    field: str
    value: str
    source: str
    line: int
    quote: str


class Order(Model):
    kind: Kind
    number: Text | None = None
    issue_date: date | None = None
    seller: Text | None = None
    buyer: Text | None = None
    currency: Currency | None = None
    items: list[Line] = Field(default_factory=list, max_length=200)
    freight: Amount | None = None
    sample_fee: Amount | None = None
    discount: Amount | None = None
    sample_policy: Literal["free", "charged"] | None = None
    sample_credit: Text | None = None
    customization: Text | None = None
    payment: Text | None = None
    bank: Text | None = None
    delivery: Text | None = None
    freight_payer: Text | None = None
    logo: str | None = Field(default=None, max_length=1000000)
    template_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence: list[Evidence] = Field(default_factory=list, max_length=4000)
    unresolved: list[Text] = Field(default_factory=list, max_length=200)
    sources: list[Text] = Field(default_factory=list, max_length=200)


class Totals(Model):
    lines: list[Decimal]
    subtotal: Decimal
    total: Decimal


def quantum(o):
    return Decimal("1") if o.currency == "JPY" else Decimal("0.01")


def calculate(o: Order) -> Totals:
    if not o.items or not o.currency or None in (o.freight, o.sample_fee, o.discount):
        raise ValueError(
            "Currency, items and explicit freight, fee and discount required"
        )
    q = quantum(o)
    if any(x != x.quantize(q) for x in (o.freight, o.sample_fee, o.discount)):
        raise ValueError("Fees and discount must use currency precision")
    lines = []
    for item in o.items:
        if item.quantity is None or item.unit_price is None:
            raise ValueError(f"Missing quantity or unit price for {item.sku}")
        lines.append((item.quantity * item.unit_price).quantize(q, ROUND_HALF_UP))
    subtotal = sum(lines, Decimal(0))
    total = subtotal + o.freight + o.sample_fee - o.discount
    if total < 0 or total >= Decimal("1000000000000"):
        raise ValueError("Total outside supported Excel precision")
    return Totals(lines=lines, subtotal=subtotal, total=total.quantize(q))


def issues(o: Order) -> list[str]:
    required = [
        "number",
        "issue_date",
        "seller",
        "buyer",
        "currency",
        "payment",
        "delivery",
        "freight_payer",
        "sources",
    ]
    if o.kind.startswith("sample"):
        required += ["sample_policy", "sample_credit", "customization"]
    errors = [f"Missing {k}" for k in required if not getattr(o, k)]
    errors.extend(f"Unresolved: {question}" for question in o.unresolved)
    if o.kind == "product-image-pi" and any(not i.image for i in o.items):
        errors.append("Each image PI line requires a product image")
    for line in o.items:
        if not line.unit:
            errors.append(f"Missing unit for {line.sku}")
    if o.sample_policy == "free" and (
        o.sample_fee or any(i.unit_price for i in o.items)
    ):
        errors.append("Free samples require zero sample fee and item prices")
    if o.sample_policy == "charged" and not (
        o.sample_fee or any(i.unit_price for i in o.items)
    ):
        errors.append("Charged sample has no charge")
    try:
        calculate(o)
    except ValueError as e:
        errors.append(str(e))
    return errors
