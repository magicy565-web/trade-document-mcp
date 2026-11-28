"""Synthetic acceptance fixture only. Keys live in memory and die with the process."""

import argparse
import base64
import json
import os
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw
import shutil
import tempfile
from decimal import Decimal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from trade_document import server
from trade_document.approval import Proof, message
from trade_document.model import Order

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/sample.json"


def configure_fixture_reviewer():
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    os.environ["TRADE_DOC_REVIEWERS"] = json.dumps({"synthetic-test-only": public})
    return key


def sign(review, key):
    return Proof(
        reviewer="synthetic-test-only",
        signature=base64.b64encode(
            key.sign(message(review, "synthetic-test-only"))
        ).decode(),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    dest = parser.parse_args().output
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        os.environ["TRADE_DOC_HOME"] = temp
        key = configure_fixture_reviewer()
        for kind in server.TITLES:
            order = Order.model_validate_json(FIXTURE.read_bytes())
            order.kind = kind
            order.number = "DEMO-" + kind.upper()
            if kind in ("standard-pi", "product-image-pi"):
                order.sample_policy = None
                order.sample_credit = None
                order.customization = None
                order.sample_fee = Decimal("0")
            if kind == "standard-pi":
                order.paper = "Letter"
            if kind == "product-image-pi":
                for item in order.items:
                    image = Image.new("RGB", (180, 80), "#e4f4f2")
                    ImageDraw.Draw(image).polygon(
                        [(12, 66), (48, 30), (84, 47), (142, 51), (166, 65)],
                        fill="#245260",
                    )
                    stream = BytesIO()
                    image.save(stream, format="PNG")
                    item.image = base64.b64encode(stream.getvalue()).decode()
                    item.additional_images = [item.image]
            s = server.create_order_draft(order)
            server.preview_document(s.order_id, 1)
            review = server.request_approval(s.order_id, 1)
            a = server.generate_document(review.request_id, sign(review, key))
            assert server.audit_document(a.artifact_id).passed
            for path in map(Path, [a.xlsx_path, a.pdf_path]):
                shutil.copyfile(path, dest / (kind + path.suffix))


if __name__ == "__main__":
    main()
