import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from PIL import Image
from openpyxl import Workbook, load_workbook
import pytest
from trade_document import server as api
from trade_document.render import open_template


def template_bytes():
    wb = Workbook()
    ws = wb.active
    ws["A2"] = "{{title}}"
    ws["A4"] = "{{details}}"
    ws["A20"] = "{{items}}"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_enterprise_layout(order):
    data = template_bytes()
    name = api.register_template("Dealer layout", base64.b64encode(data).decode())
    order.template_id = name.id
    s = api.create_order_draft(order)
    a = api.preview_document(s.order_id, 1)
    ws = load_workbook(a.xlsx_path, data_only=True).active
    assert ws["A2"].value == "DRAFT - Sample Proforma Invoice"
    assert ws["A20"].value == "SKU"
    assert ws["F27"].value == 68.5
    assert len(api.list_templates().templates) == 5


@pytest.mark.parametrize("change", ["formula", "duplicate", "missing", "overlap"])
def test_reject_unsupported_template(change):
    wb = load_workbook(BytesIO(template_bytes()))
    ws = wb.active
    if change == "formula":
        ws["B2"] = "=1+1"
    if change == "duplicate":
        ws["A3"] = "{{title}}"
    if change == "missing":
        ws["A4"] = None
    if change == "overlap":
        ws["A20"] = None
        ws["A8"] = "{{items}}"
    data = BytesIO()
    wb.save(data)
    with pytest.raises(ValueError):
        open_template(data.getvalue())


def test_concurrent_revision(order):
    s = api.create_order_draft(order)

    def update(_):
        try:
            return api.update_order_draft(s.order_id, 1, order).version
        except ValueError:
            return None

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(update, range(2))).count(2) == 1
    assert api.get_order_draft(s.order_id, 1).version == 1


@pytest.mark.parametrize("kind", list(api.TITLES))
def test_visual_types(order, kind):
    order.kind = kind
    stream = BytesIO()
    Image.new("RGB", (80, 60), "teal").save(stream, format="PNG")
    order.logo = order.items[0].image = base64.b64encode(stream.getvalue()).decode()
    s = api.create_order_draft(order)
    result = api.preview_document(s.order_id, 1)
    assert result.audit.passed
    assert len(load_workbook(result.xlsx_path).active._images) == 2
    Path(result.pdf_path).write_bytes(b"modified")
    assert not api.audit_document(result.artifact_id).passed


def test_multipage(order):
    from pypdf import PdfReader

    order.items = [
        order.items[0].model_copy(update={"sku": f"SKU-{n:03}"}) for n in range(70)
    ]
    s = api.create_order_draft(order)
    a = api.preview_document(s.order_id, 1)
    pages = PdfReader(a.pdf_path).pages
    assert len(pages) > 2
    assert all(
        "SKU" in page.extract_text() for page in pages if "SKU-" in page.extract_text()
    )


def test_text_stays_literal(order):
    order.seller = "=SUM(A1:A5)"
    s = api.create_order_draft(order)
    a = api.preview_document(s.order_id, 1)
    assert load_workbook(a.xlsx_path).active["B3"].data_type == "s"
