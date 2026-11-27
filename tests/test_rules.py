from decimal import Decimal
import pytest
from pydantic import ValidationError
from trade_document.model import Line, Order, calculate, issues
from trade_document.extract import Source, extract


# Line rounding oracles expressed independently as integer ten-thousandths.
@pytest.mark.parametrize(
    "currency,scale",
    [("JPY", 1), ("USD", 100), ("EUR", 100), ("GBP", 100), ("CNY", 100)],
)
@pytest.mark.parametrize(
    "price,qty",
    [
        (0, 1),
        (1, 1),
        (49, 1),
        (50, 1),
        (51, 1),
        (99, 2),
        (2500, 2),
        (3333, 3),
        (10001, 9),
        (16667, 3),
        (9876543, 17),
        (123456, 999),
        (55555, 4),
        (15000, 3),
        (9999, 101),
        (99, 99),
    ],
)
def test_rounding_and_fees(order, currency, scale, price, qty):
    order.currency = currency
    order.items = order.items[:1]
    order.items[0].unit_price = Decimal(price).scaleb(-4)
    order.items[0].quantity = qty
    expected = Decimal((price * qty * scale + 5000) // 10000) / scale
    assert calculate(order).lines == [expected]
    assert calculate(order).total == expected + 20


@pytest.mark.parametrize(
    "field",
    "number issue_date seller buyer currency payment delivery freight_payer sources sample_policy sample_credit customization".split(),
)
def test_required(order, field):
    setattr(order, field, [] if field == "sources" else None)
    assert "Missing " + field in issues(order)


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", 0),
        ("quantity", -1),
        ("quantity", True),
        ("quantity", "1.00001"),
        ("quantity", "two"),
        ("quantity", 1000000),
        ("unit_price", "-1"),
        ("unit_price", "NaN"),
        ("unit_price", "1.00001"),
        ("unit_price", "Infinity"),
        ("sku", " "),
        ("unexpected", 1),
    ],
)
def test_invalid_item(order, field, value):
    data = order.items[0].model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        Line.model_validate(data)


@pytest.mark.parametrize("field", ["sample_fee", "freight", "discount"])
def test_explicit_fees(order, field):
    setattr(order, field, None)
    assert issues(order)


def test_free_still_pays_shipping(order):
    order.sample_policy = "free"
    assert issues(order)
    for item in order.items:
        item.unit_price = Decimal(0)
    order.sample_fee = Decimal(0)
    assert not issues(order)
    assert calculate(order).total == 12


def test_conflicting_sources():
    x = extract(
        [
            Source(
                name="quote",
                kind="quotation",
                text="运费: 5\nsku,quantity,unit_price\nA,2,1.50",
            ),
            Source(name="chat", kind="chat", text="freight: 6\nPlease call me"),
        ]
    )
    assert x.conflicts == ["freight"]
    assert x.evidence[2].field == "items[A].quantity"
    assert x.evidence[2].line == 3
    assert x.unmatched == ["chat:2 Please call me"]


def test_grounded_chat_into_draft():
    from trade_document.extract import Highlight, populate

    src = Source(
        kind="chat",
        name="chat-1",
        text="Please send our samples to Demo Import Ltd.\nfreight: 4\nsku,description,quantity,unit,unit_price\nT,Mock item,2,pairs,1.50",
    )
    mark = Highlight(source=src.name, line=1, field="buyer", value="Demo Import Ltd.")
    draft = populate(Order(kind="sample-pi"), [src], [mark])
    assert (
        draft.buyer == mark.value
        and draft.items[0].quantity == 2
        and draft.freight == 4
    )
    assert draft.evidence[-1].quote.startswith("Please send")
    with pytest.raises(ValueError):
        populate(draft, [src], [mark.model_copy(update={"value": "Someone else"})])


def test_conflict_blocks_issue():
    from trade_document.extract import populate

    src = Source(name="text", kind="chat", text="freight: 12\nfreight: 18")
    draft = populate(Order(kind="sample-pi"), [src], [])
    assert draft.freight is None and "Unresolved: freight" in issues(draft)


def test_binary_sources():
    import base64
    from io import BytesIO
    from openpyxl import Workbook
    from reportlab.pdfgen.canvas import Canvas

    wb = Workbook()
    wb.active.append(["buyer", "Fictional buyer"])
    wb.active.append(["sku", "description", "quantity", "unit", "unit_price"])
    wb.active.append(["QA", "Demo", 3, "pcs", "1.00"])
    x = BytesIO()
    wb.save(x)
    p = BytesIO()
    c = Canvas(p)
    c.drawString(24, 500, "freight: 12")
    c.save()
    result = extract(
        [
            Source(
                name="quote",
                kind="quotation",
                format=fmt,
                content_base64=base64.b64encode(data.getvalue()).decode(),
            )
            for fmt, data in [("xlsx", x), ("pdf", p)]
        ]
    )
    assert [
        (e.field, e.value)
        for e in result.evidence
        if e.field in ("buyer", "freight", "items[QA].quantity")
    ] == [("buyer", "Fictional buyer"), ("items[QA].quantity", "3"), ("freight", "12")]
