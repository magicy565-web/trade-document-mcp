"""Generate a wholly fictional multi-market PI and split-shipment acceptance pack."""

import base64, os, shutil, tempfile
from io import BytesIO
from pathlib import Path
import argparse
from PIL import Image, ImageDraw
from demo import configure_fixture_reviewer, FIXTURE, sign
from trade_document import server as api, shipments as sh
from trade_document.model import Order
from trade_document.approval import Proof
from trade_document.storage import canonical


def build(dest):
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        os.environ["TRADE_DOC_HOME"] = temp
        key = configure_fixture_reviewer()
        for kind, lang, country in [
            ("standard-pi", "de", "DE"),
            ("product-image-pi", "fr", "FR"),
            ("sample-order", "en", "GB"),
            ("sample-pi", "en", "US"),
        ]:
            order = Order.model_validate_json(FIXTURE.read_bytes())
            order.kind, order.language, order.destination = kind, lang, country
            order.number = "QA-" + country + "-001"
            order.paper = "Letter" if country == "US" else "A4"
            if kind == "product-image-pi":
                im = Image.new("RGB", (200, 100), "#e4f4f2")
                draw = ImageDraw.Draw(im)
                draw.polygon(
                    [
                        (12, 70),
                        (45, 42),
                        (65, 31),
                        (89, 48),
                        (137, 50),
                        (176, 65),
                        (183, 77),
                        (13, 77),
                    ],
                    fill="#245260",
                )
                stream = BytesIO()
                im.save(stream, "PNG")
                for i in order.items:
                    i.image = base64.b64encode(stream.getvalue()).decode()
            s = api.create_order_draft(order)
            api.preview_document(s.order_id, 1)
            req = api.request_approval(s.order_id, 1)
            result = api.generate_document(req.request_id, sign(req, key))
            assert api.audit_document(result.artifact_id).passed
            for file in [result.xlsx_path, result.pdf_path]:
                path = Path(file)
                shutil.copyfile(path, dest / (country + "-" + kind + path.suffix))
        batch = sh.Shipment(
            number="QA-US-SHIP-01",
            dispatch_date="2026-12-01",
            consignee="Example Retail Lab / East receiving",
            freight="4.20",
            fees="0",
            discount="0",
            source="Fictional warehouse packing record",
            boxes=[
                {
                    "mark": "QA-01",
                    "net_kg": "0.80",
                    "gross_kg": "1.00",
                    "volume_m3": "0.012",
                    "contents": [
                        {
                            "sku": "W-101",
                            "quantity": "1",
                            "unit": "pairs",
                            "origin": "CN",
                        }
                    ],
                }
            ],
        )
        shipment = sh.create_shipment(s.order_id, 1, batch)
        packet = sh.preview_shipment(shipment.shipment_id, 1)
        proof = Proof(
            reviewer="synthetic-test-only",
            signature=base64.b64encode(
                key.sign(canonical(packet.model_dump(mode="json")))
            ).decode(),
        )
        issued = sh.export_document_bundle(packet, proof)
        assert sh.cross_check_documents(shipment.shipment_id, 1).valid
        for file in issued.files:
            shutil.copyfile(file, dest / Path(file).name)
        draft = sh.prepare_customs_support(shipment.shipment_id, 1)
        (dest / "customs-support-draft.json").write_text(
            draft.model_dump_json(indent=2)
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    build(p.parse_args().output)
