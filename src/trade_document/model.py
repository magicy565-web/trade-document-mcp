from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)
]
Amount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]
Kind = Literal["standard-pi", "product-image-pi", "sample-pi", "sample-order"]
Currency = Literal[
    "USD", "EUR", "GBP", "CNY", "JPY", "AUD", "CAD", "AED", "INR", "TRY", "MAD", "CHF"
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Line(Model):
    sku: Text
    description: Text
    specification: Text | None = None
    quantity: Annotated[Decimal, Field(gt=0, le=999999, decimal_places=4)] | None = None
    unit: Text | None = None
    unit_price: Amount | None = None
    image: str | None = Field(default=None, max_length=1000000)
    additional_images: list[Annotated[str, Field(min_length=1, max_length=1000000)]] = (
        Field(default_factory=list, max_length=2)
    )
    variant: Text | None = None

    def images(self):
        return ([self.image] if self.image else []) + self.additional_images

    def descriptions(self):
        return [
            value
            for value in (self.description, self.variant, self.specification)
            if value
        ]


class Milestone(Model):
    event: Text
    percent: Annotated[Decimal, Field(gt=0, le=100, decimal_places=4)]


class Evidence(Model):
    status: Literal[
        "candidate", "requested", "quoted", "confirmed", "disputed", "superseded"
    ] = "candidate"
    field: str
    value: str
    source: str
    line: int
    quote: str


class Address(Model):
    street: Text
    city: Text
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    region: Text | None = None
    postal_code: Text | None = None

    def display(self):
        return ", ".join(
            part
            for part in (
                self.street,
                self.city,
                self.region,
                self.postal_code,
                self.country,
            )
            if part
        )


class Party(Model):
    role: Literal["seller", "buyer", "ship_to"]
    legal_name: Text
    address: Address


class DeliveryTerm(Model):
    term: Text
    named_place: Text
    edition: Text


class Order(Model):
    parties: list[Party] = Field(default_factory=list, max_length=3)
    delivery_term: DeliveryTerm | None = None
    sample_acceptance: Text | None = None

    paper: Literal["A4", "Letter"] = "A4"
    valid_until: date | None = None
    ship_to: Text | None = None
    seller_address: Text | None = None
    buyer_address: Text | None = None
    purchase_order: Text | None = None
    schedule: list[Milestone] = Field(default_factory=list, max_length=12)
    beneficiary_ref: Text | None = None
    kind: Kind
    number: Text | None = None
    issue_date: date | None = None
    seller: Text | None = None
    buyer: Text | None = None
    currency: Currency | None = None
    items: list[Line] = Field(default_factory=list, max_length=200)
    freight: Amount | None = None
    insurance: Amount | None = None
    tooling_fee: Amount | None = None
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
    installments: list[Decimal] = Field(default_factory=list)
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
    additional = [fee for fee in (o.insurance, o.tooling_fee) if fee is not None]
    if any(
        x != x.quantize(q) for x in (o.freight, o.sample_fee, o.discount, *additional)
    ):
        raise ValueError("Fees and discount must use currency precision")
    lines = []
    for item in o.items:
        if item.quantity is None or item.unit_price is None:
            raise ValueError(f"Missing quantity or unit price for {item.sku}")
        lines.append((item.quantity * item.unit_price).quantize(q, ROUND_HALF_UP))
    subtotal = sum(lines, Decimal(0))
    total = subtotal + o.freight + o.sample_fee + sum(additional) - o.discount
    if total < 0 or total >= Decimal("1000000000000"):
        raise ValueError("Total outside supported Excel precision")
    installments = []
    if o.schedule:
        if sum(m.percent for m in o.schedule) != 100:
            raise ValueError("Payment schedule must total 100 percent")
        # Round cumulative entitlements so installments always reconcile.
        cumulative = Decimal(0)
        paid = Decimal(0)
        for m in o.schedule:
            cumulative += m.percent
            due = (total * cumulative / 100).quantize(q, ROUND_HALF_UP)
            installments.append(due - paid)
            paid = due
    return Totals(
        installments=installments,
        lines=lines,
        subtotal=subtotal,
        total=total.quantize(q),
    )


def document_totals(order: Order, draft: bool) -> Totals | None:
    if not draft:
        return calculate(order)
    try:
        return calculate(order)
    except ValueError:
        return None


def issues(o: Order, beneficiaries: dict[str, str] | None = None) -> list[str]:
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
    if len({i.sku for i in o.items}) != len(o.items):
        errors.append("Duplicate SKU")
    if len({party.role for party in o.parties}) != len(o.parties):
        errors.append("Duplicate party role")
    for party in o.parties:
        if (
            party.role in ("seller", "buyer")
            and getattr(o, party.role) != party.legal_name
        ):
            errors.append(f"Party name differs from {party.role}")
    if o.valid_until and o.issue_date and o.valid_until < o.issue_date:
        errors.append("Validity ends before issue date")
    if o.bank or o.beneficiary_ref:
        import os, json

        verified = (
            json.loads(os.environ.get("TRADE_DOC_BENEFICIARIES", "{}"))
            if beneficiaries is None
            else beneficiaries
        )
        if (
            not o.beneficiary_ref
            or not o.bank
            or verified.get(o.beneficiary_ref) != o.bank
        ):
            errors.append("Unverified beneficiary instructions")
    errors.extend(f"Unresolved: {question}" for question in o.unresolved)
    errors.extend(
        f"Disputed evidence: {e.field}" for e in o.evidence if e.status == "disputed"
    )
    if o.kind == "product-image-pi" and any(not item.images() for item in o.items):
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
